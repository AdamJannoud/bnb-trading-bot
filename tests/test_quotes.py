"""Fix 1: a trade the router cannot price is refused, never sent with a zero floor."""
import asyncio

import pytest

import swap_engine

TOKEN = "0x" + "ab" * 20
FAKE_KEY = "not-a-real-key"


def buy(amount=0.05, user_id=1):
    return asyncio.run(swap_engine.execute_buy_async(FAKE_KEY, TOKEN, amount, user_id, use_private_rpc=True))


def sell(percent=100.0, user_id=1):
    return asyncio.run(swap_engine.execute_sell_async(FAKE_KEY, TOKEN, percent, user_id, use_private_rpc=True))


def test_failing_buy_quote_refuses_trade(fake_chain):
    chain = fake_chain(quotes=[ConnectionError("execution reverted")])
    res = buy()
    assert res["success"] is False
    assert "No price quote" in res["error"]
    assert chain.signed == [] and chain.sent == []


def test_zero_quote_refuses_trade(fake_chain):
    chain = fake_chain(quotes=[0])
    res = buy()
    assert res["success"] is False
    assert chain.sent == []


def test_failing_sell_quote_refuses_trade(fake_chain):
    chain = fake_chain(quotes=[ValueError("no pair")], token_balances=[10**21])
    res = sell()
    assert res["success"] is False
    assert "No price quote" in res["error"]
    assert chain.swaps() == []


def test_buy_sends_nonzero_minimum_from_quote(fake_chain):
    chain = fake_chain(quotes=[10**20, 10**20], token_balances=[0, 10**20])
    res = buy()
    assert res["success"] is True, res
    [swap] = chain.swaps()
    assert swap["amount_out_min"] == int(10**20 * (1 - swap_engine.SLIPPAGE_TOLERANCE))
    assert swap["amount_out_min"] > 0


def test_requote_past_tolerance_abandons_buy(fake_chain):
    # First quote 100, second quote 90: a 10% move against a 5% tolerance.
    chain = fake_chain(quotes=[100 * 10**18, 90 * 10**18])
    res = buy()
    assert res["success"] is False
    assert "moved past slippage" in res["error"]
    assert chain.quote_calls == 2
    assert chain.signed == [] and chain.sent == []


def test_requote_failure_abandons_sell(fake_chain):
    chain = fake_chain(quotes=[10**18, RuntimeError("rpc down")], token_balances=[10**21])
    res = sell()
    assert res["success"] is False
    assert chain.swaps() == []


@pytest.mark.parametrize("value", [0, -0.01, 0.5, 1.0])
def test_slippage_outside_ceiling_is_refused(value):
    with pytest.raises(ValueError):
        swap_engine.load_slippage_tolerance({"SLIPPAGE_TOLERANCE": value})


def test_slippage_within_ceiling_is_accepted():
    assert swap_engine.load_slippage_tolerance({"SLIPPAGE_TOLERANCE": 0.03}) == 0.03
    assert swap_engine.load_slippage_tolerance({}) == 0.05
