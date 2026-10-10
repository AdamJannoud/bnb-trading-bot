"""Fix 4: kill switch, per-trade and exposure caps, daily loss cap, and positions
that exit exactly what they bought."""
import asyncio
import itertools
import time
import types

import pytest

import bot
import db_manager
import mempool_listener
import risk
import swap_engine

TOKEN = "0x" + "cd" * 20
FAKE_KEY = "not-a-real-key"
OWNER_ID = bot.CONFIG["OWNER_TELEGRAM_ID"]
_ids = itertools.count(50_000)


@pytest.fixture
def user():
    return next(_ids)


@pytest.fixture(autouse=True)
def reset_kill_switch():
    risk.set_buying_stopped(False)
    yield
    risk.set_buying_stopped(False)


@pytest.fixture
def sent_messages(monkeypatch):
    sent = []

    async def send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot.bot, "send_message", send_message)
    monkeypatch.setattr(bot, "get_decrypted_private_key", lambda uid: FAKE_KEY)
    return sent


class FakeMessage:
    def __init__(self, user_id, text=""):
        self.from_user = types.SimpleNamespace(id=user_id)
        self.text = text
        self.replies = []

    async def answer(self, text, **kwargs):
        self.replies.append(text)


def test_default_limits_are_the_approved_values():
    assert risk.DEFAULT_LIMITS == {"MAX_TRADE_BNB": 0.1, "MAX_OPEN_EXPOSURE_BNB": 0.3, "DAILY_LOSS_CAP_BNB": 0.05}
    assert risk.LIMITS == risk.DEFAULT_LIMITS  # config.example.json ships the same numbers


# --- per-trade cap ---------------------------------------------------------

def test_per_trade_cap(user):
    assert risk.check_buy(user, 0.1) is None
    assert "per-trade cap" in risk.check_buy(user, 0.11)


def test_oversized_buy_is_refused_before_signing(fake_chain, user):
    chain = fake_chain(quotes=[10**20, 10**20])
    res = asyncio.run(swap_engine.execute_buy_async(FAKE_KEY, TOKEN, 0.2, user, use_private_rpc=True))
    assert res["success"] is False and "per-trade cap" in res["error"]
    assert chain.signed == [] and chain.quote_calls == 0


def test_buy_command_refuses_over_cap_before_any_audit(monkeypatch, user):
    async def must_not_run(*a, **k):
        raise AssertionError("refused trade must stop at the command")
    monkeypatch.setattr(bot, "check_token_security", must_not_run)
    msg = FakeMessage(user, f"/buy {TOKEN} 0.5")
    asyncio.run(bot.cmd_buy(msg))
    assert "refused" in msg.replies[0]


# --- open exposure cap -----------------------------------------------------

def test_open_exposure_cap(user):
    db_manager.add_position(user, TOKEN, None, None, None, token_amount=10, cost_bnb=0.1)
    db_manager.add_position(user, TOKEN, None, None, None, token_amount=10, cost_bnb=0.15)
    assert risk.check_buy(user, 0.05) is None
    assert "exposure" in risk.check_buy(user, 0.06)


def test_selling_releases_exposure(user):
    db_manager.add_position(user, TOKEN, None, None, None, token_amount=1000, cost_bnb=0.3)
    assert "exposure" in risk.check_buy(user, 0.01)
    db_manager.realise_sell(user, TOKEN.upper().replace("0X", "0x"), 500, 0.2)
    assert db_manager.get_open_exposure(user) == pytest.approx(0.15)
    assert risk.check_buy(user, 0.1) is None


def test_every_buy_opens_a_position_with_its_quantity(fake_chain, user):
    fake_chain(quotes=[10**20, 10**20], token_balances=[7 * 10**21, 7 * 10**21 + 98 * 10**18])
    res = asyncio.run(swap_engine.execute_buy_async(FAKE_KEY, TOKEN, 0.05, user, use_private_rpc=True))
    assert res["success"] is True, res
    [pos] = [p for p in db_manager.get_active_positions() if p["user_id"] == user]
    assert int(pos["token_amount"]) == 98 * 10**18
    assert pos["cost_bnb"] == 0.05
    assert db_manager.get_open_exposure(user) == pytest.approx(0.05)


# --- daily loss cap --------------------------------------------------------

def test_daily_loss_cap_pauses_buying(user):
    db_manager.log_trade(user, "SELL", TOKEN, 0.01, 0.0, "0x1", realised_pnl_bnb=-0.05)
    assert "loss cap" in risk.check_buy(user, 0.01)


def test_loss_under_cap_allows_buying(user):
    db_manager.log_trade(user, "SELL", TOKEN, 0.01, 0.0, "0x1", realised_pnl_bnb=-0.04)
    assert risk.check_buy(user, 0.01) is None


def test_loss_cap_window_is_rolling_24h(monkeypatch, user):
    db_manager.log_trade(user, "SELL", TOKEN, 0.01, 0.0, "0x1", realised_pnl_bnb=-0.08)
    assert risk.check_buy(user, 0.01) is not None
    later = time.time() + 24 * 3600 + 60
    monkeypatch.setattr(risk, "time", types.SimpleNamespace(time=lambda: later))
    assert risk.check_buy(user, 0.01) is None


# --- kill switch -----------------------------------------------------------

def test_kill_switch_blocks_buys_and_persists(user):
    risk.set_buying_stopped(True)
    assert db_manager.get_flag(risk.KILL_SWITCH_FLAG) == "1"  # stored in the database
    assert "stopped" in risk.check_buy(user, 0.01)
    risk.set_buying_stopped(False)
    assert risk.check_buy(user, 0.01) is None


def test_selling_stays_open_while_stopped(fake_chain, user):
    risk.set_buying_stopped(True)
    chain = fake_chain(quotes=[10**17, 10**17], token_balances=[10**20])
    res = asyncio.run(swap_engine.execute_sell_async(FAKE_KEY, TOKEN, 100.0, user, use_private_rpc=True))
    assert res["success"] is True, res
    assert len(chain.swaps()) == 1


def test_stop_and_resume_are_owner_only():
    stranger = FakeMessage(OWNER_ID + 1)
    asyncio.run(bot.cmd_stop(stranger))
    assert "Owner only" in stranger.replies[0]
    assert not risk.is_buying_stopped()

    owner = FakeMessage(OWNER_ID)
    asyncio.run(bot.cmd_stop(owner))
    assert risk.is_buying_stopped()
    asyncio.run(bot.cmd_resume(owner))
    assert not risk.is_buying_stopped()


def test_copy_trader_checks_kill_switch_first(monkeypatch, user):
    def must_not_run(*a, **k):
        raise AssertionError("a stopped copy trade must not touch the key or the chain")
    monkeypatch.setattr(mempool_listener, "get_whale_followers", lambda w: [{"user_id": user, "buy_amount": 0.01}])
    monkeypatch.setattr(mempool_listener, "get_decrypted_private_key", must_not_run)
    monkeypatch.setattr(mempool_listener, "execute_buy_async", must_not_run)
    risk.set_buying_stopped(True)
    asyncio.run(mempool_listener.execute_copy_trade("0x" + "ee" * 20, TOKEN))


# --- TP/SL exits the recorded position -------------------------------------

def _open_autotrade(fake_chain, user, wallet_before, bought, cost=0.05):
    fake_chain(quotes=[10**20, 10**20], token_balances=[wallet_before, wallet_before + bought])
    res = asyncio.run(swap_engine.execute_buy_async(FAKE_KEY, TOKEN, cost, user, use_private_rpc=True,
                                                    entry_price=1.0, tp_percent=50, sl_percent=15))
    assert res["success"] is True, res
    [pos] = [p for p in db_manager.get_active_positions() if p["user_id"] == user]
    return pos


def test_tpsl_exit_sells_position_not_wallet(fake_chain, sent_messages, monkeypatch, user):
    wallet_other = 10**24  # tokens the user already held, never bought by this position
    bought = 5 * 10**20
    pos = _open_autotrade(fake_chain, user, wallet_other, bought)

    async def price(token):
        return 1.6  # +60%: take-profit
    monkeypatch.setattr(bot, "get_live_token_price", price)
    chain = fake_chain(quotes=[10**17, 10**17], token_balances=[wallet_other + bought],
                       bnb_balances=[10**18, 10**18 + 6 * 10**16])
    asyncio.run(bot.check_position(pos))

    [swap] = chain.swaps()
    assert swap["amount_in"] == bought
    assert not [p for p in db_manager.get_active_positions() if p["user_id"] == user]
    assert "Take-Profit Executed" in sent_messages[0][1]
    assert db_manager.get_realised_pnl_since(user, 0) == pytest.approx(0.06 * 0.99 - 0.05)


def test_losing_exit_trips_loss_cap_and_tells_owner(fake_chain, sent_messages, monkeypatch, user):
    pos = _open_autotrade(fake_chain, user, 0, 10**21, cost=0.1)

    async def price(token):
        return 0.5  # -50%: stop-loss
    monkeypatch.setattr(bot, "get_live_token_price", price)
    fake_chain(quotes=[10**17, 10**17], token_balances=[10**21], bnb_balances=[10**18, 10**18 + 4 * 10**16])
    asyncio.run(bot.check_position(pos))

    assert risk.loss_cap_hit(user)
    assert "loss cap" in risk.check_buy(user, 0.01)
    assert any(chat == OWNER_ID and "Daily loss cap" in text for chat, text in sent_messages)


def test_legacy_position_without_quantity_is_not_auto_sold(fake_chain, sent_messages, monkeypatch, user):
    db_manager.add_position(user, TOKEN, 1.0, 50, 15)  # pre-patch row: no token_amount
    [pos] = [p for p in db_manager.get_active_positions() if p["user_id"] == user]

    async def price(token):
        return 2.0
    monkeypatch.setattr(bot, "get_live_token_price", price)
    chain = fake_chain(quotes=[10**17], token_balances=[10**24])
    asyncio.run(bot.check_position(pos))

    assert chain.swaps() == []
    assert not [p for p in db_manager.get_active_positions() if p["user_id"] == user]
    assert "/sell" in sent_messages[0][1]
