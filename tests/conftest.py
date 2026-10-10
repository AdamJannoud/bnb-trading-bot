"""Offline test harness.

The bot's modules read config.json and open bot_database.db relative to the
working directory at import time, so the whole session runs inside a scratch
directory holding a copy of config.example.json. No network, no real keys:
sockets are blocked, and web3 is replaced by FakeW3 below.
"""
import os
import shutil
import socket
import sys
import tempfile

import pytest
from cryptography.fernet import Fernet

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SCRATCH = tempfile.mkdtemp(prefix="bnb-bot-tests-")
shutil.copy(os.path.join(REPO, "config.example.json"), os.path.join(SCRATCH, "config.json"))
os.chdir(SCRATCH)
# A throwaway key made for this test session only; it never leaves the process.
os.environ["WALLET_ENCRYPTION_KEY"] = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("Tests must not open network connections")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class _Call:
    def __init__(self, fn):
        self._fn = fn

    async def call(self):
        return self._fn()

    async def build_transaction(self, params):
        return self._fn(params)


class FakeHash(bytes):
    def hex(self):
        return "0x" + super().hex()


class _Functions:
    def __init__(self, chain, kind):
        self._chain = chain
        self._kind = kind

    # router
    def getAmountsOut(self, amount_in, path):
        def run():
            self._chain.quote_calls += 1
            item = self._chain.quotes.pop(0)
            if isinstance(item, Exception):
                raise item
            return [amount_in, item]
        return _Call(run)

    def swapExactETHForTokensSupportingFeeOnTransferTokens(self, amount_out_min, path, to, deadline):
        return _Call(lambda p: {**p, "fn": "buy", "amount_out_min": amount_out_min})

    def swapExactTokensForETHSupportingFeeOnTransferTokens(self, amount_in, amount_out_min, path, to, deadline):
        return _Call(lambda p: {**p, "fn": "sell", "amount_in": amount_in, "amount_out_min": amount_out_min})

    # token
    def balanceOf(self, owner):
        def run():
            bal = self._chain.token_balances
            return bal.pop(0) if len(bal) > 1 else bal[0]
        return _Call(run)

    def allowance(self, owner, spender):
        return _Call(lambda: 2**256 - 1)

    def approve(self, spender, value):
        return _Call(lambda p: {**p, "fn": "approve"})


class _Contract:
    def __init__(self, chain, kind):
        self.functions = _Functions(chain, kind)


class _Account:
    def __init__(self, chain):
        self._chain = chain

    def from_key(self, key):
        return type("Acct", (), {"address": "0x" + "11" * 20})()

    def sign_transaction(self, tx, key):
        self._chain.signed.append(tx)
        return type("Signed", (), {"raw_transaction": tx})()


class _Eth:
    def __init__(self, chain):
        self._chain = chain
        self.account = _Account(chain)

    @property
    def gas_price(self):
        async def gp():
            return 5 * 10**9
        return gp()

    def contract(self, address, abi):
        names = {item.get("name") for item in abi}
        return _Contract(self._chain, "router" if "getAmountsOut" in names else "token")

    async def get_balance(self, address):
        bal = self._chain.bnb_balances
        return bal.pop(0) if len(bal) > 1 else bal[0]

    async def get_transaction_count(self, address, block="latest"):
        return len(self._chain.sent)

    async def send_raw_transaction(self, raw):
        self._chain.sent.append(raw)
        return FakeHash(bytes([len(self._chain.sent)]) * 32)

    async def wait_for_transaction_receipt(self, tx_hash):
        return {"gasUsed": 0, "effectiveGasPrice": 0}


class FakeW3:
    """Just enough of AsyncWeb3 for swap_engine. Every quote, signature and
    broadcast is recorded so a test can assert what would have hit the chain."""

    def __init__(self, quotes=(), bnb_balances=(10**18,), token_balances=(0,)):
        self.quotes = list(quotes)
        self.bnb_balances = list(bnb_balances)
        self.token_balances = list(token_balances)
        self.quote_calls = 0
        self.signed = []
        self.sent = []
        self.eth = _Eth(self)

    @staticmethod
    def to_wei(value, unit):
        from web3 import Web3
        return Web3.to_wei(value, unit)

    @staticmethod
    def from_wei(value, unit):
        from web3 import Web3
        return Web3.from_wei(value, unit)

    def swaps(self):
        return [tx for tx in self.sent if isinstance(tx, dict) and tx.get("fn") in ("buy", "sell")]


@pytest.fixture
def fake_chain(monkeypatch):
    """Returns a factory that installs a FakeW3 into swap_engine."""
    import swap_engine

    async def sim_ok(rpc_url, tx):
        return {"success": True, "result_hex": "0x", "error": None}

    monkeypatch.setattr(swap_engine, "simulate_transaction", sim_ok)
    monkeypatch.setattr(swap_engine, "calculate_fee_split",
                        lambda fee, uid: {"owner_share": 0, "referrer_share": 0, "referrer_wallet": None})

    def install(**kwargs):
        chain = FakeW3(**kwargs)
        monkeypatch.setattr(swap_engine, "w3", chain)
        monkeypatch.setattr(swap_engine, "private_w3", chain)
        return chain
    return install
