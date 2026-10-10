"""Fix 2: no private key leaves the process through a Telegram reply."""
import asyncio
import io

import pytest

import bot
import wallet_manager
import wallet_tools

DUMMY_SECRET = "dummy-secret-for-export-test"


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def _store_wallet(user_id, secret=DUMMY_SECRET):
    conn = wallet_manager.get_db_connection()
    conn.execute(
        "INSERT INTO users_wallets (user_id, chain_type, address, encrypted_private_key, is_master) VALUES (?, 'EVM', ?, ?, 1)",
        (user_id, "0x" + "22" * 20, wallet_manager.cipher.encrypt(secret.encode()).decode()),
    )
    conn.commit()
    conn.close()


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = type("User", (), {"id": user_id})()
        self.replies = []

    async def answer(self, text, **kwargs):
        self.replies.append((text, kwargs))


def test_bot_registers_no_callback_handlers():
    # The export button was the bot's only callback query handler.
    assert bot.dp.callback_query.handlers == []
    assert not hasattr(bot, "show_pk")


def test_wallet_reply_has_no_export_button_and_reads_no_key(monkeypatch):
    def key_read(*args, **kwargs):
        raise AssertionError("/wallet must not decrypt a private key")

    async def balance(address):
        return 0.418

    monkeypatch.setattr(bot, "get_decrypted_private_key", key_read)
    monkeypatch.setattr(bot, "get_or_create_wallet", lambda *a, **k: {"address": "0x" + "33" * 20, "is_new": False})
    monkeypatch.setattr(bot, "get_bnb_balance_async", balance)

    msg = FakeMessage(user_id=42)
    asyncio.run(bot.cmd_wallet(msg))
    [(text, kwargs)] = msg.replies
    assert "0.4180 BNB" in text
    assert kwargs.get("reply_markup") is None
    assert "private key" not in text.lower()


def test_server_export_prints_key_to_terminal():
    _store_wallet(user_id=7001)
    out = TtyBuffer()
    assert wallet_tools.export_private_key(7001, out=out) == 0
    assert DUMMY_SECRET in out.getvalue()


def test_server_export_refuses_non_terminal_output():
    _store_wallet(user_id=7002)
    out = io.StringIO()
    assert wallet_tools.export_private_key(7002, out=out) == 2
    assert DUMMY_SECRET not in out.getvalue()


def test_server_export_unknown_user():
    assert wallet_tools.export_private_key(999999, out=TtyBuffer()) == 1


def test_server_export_cli_requires_user_id():
    with pytest.raises(SystemExit):
        wallet_tools.main(["export"])
