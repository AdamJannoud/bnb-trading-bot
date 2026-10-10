"""The security block names the trigger(s) that actually fired; the decision is unchanged."""
import asyncio

import pytest

import security_scanner

TOKEN = "0x" + "AB" * 20


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, status, payload):
        self._status = status
        self._payload = payload
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return FakeResponse(self._status, self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def goplus(monkeypatch):
    """Returns a function that installs a canned GoPlus reply and runs the check."""
    def run(result=None, status=200, payload=None):
        if payload is None:
            payload = {"result": {TOKEN.lower(): result or {}}}
        session = FakeSession(status, payload)
        monkeypatch.setattr(security_scanner.aiohttp, "ClientSession", lambda *a, **k: session)
        res = asyncio.run(security_scanner.check_token_security(TOKEN))
        assert session.urls == [f"{security_scanner.GOPLUS_BSC_URL}?contract_addresses={TOKEN.lower()}"]
        return res
    return run


def token(is_honeypot=0, cannot_sell_all=0, buy_tax="0", sell_tax="0"):
    # GoPlus reports flags as "0"/"1" strings and taxes as fractions.
    return {"is_honeypot": str(is_honeypot), "cannot_sell_all": str(cannot_sell_all),
            "buy_tax": buy_tax, "sell_tax": sell_tax}


def test_honeypot_only_names_honeypot_not_tax(goplus):
    res = goplus(token(is_honeypot=1))
    assert res["safe"] is False
    assert "Honeypot detected" in res["reason"]
    assert "Tax" not in res["reason"]
    assert "unsellable" not in res["reason"]
    assert set(res) == {"safe", "reason", "buy_tax", "sell_tax"}


def test_unsellable_only_names_unsellable_cause(goplus):
    res = goplus(token(cannot_sell_all=1))
    assert res["safe"] is False
    assert "unsellable" in res["reason"]
    assert "Cannot sell all" in res["reason"]
    assert "Honeypot" not in res["reason"]
    assert "Tax" not in res["reason"]
    assert "0.0%" not in res["reason"]


def test_sell_tax_only_names_sell_tax_and_value(goplus):
    res = goplus(token(sell_tax="0.2"))
    assert res["safe"] is False
    assert "Sell Tax 20.0%" in res["reason"]
    assert "Honeypot" not in res["reason"]
    assert "Buy Tax" not in res["reason"]
    assert res["sell_tax"] == pytest.approx(20.0)


def test_buy_tax_only_names_buy_tax_and_value(goplus):
    res = goplus(token(buy_tax="0.2"))
    assert res["safe"] is False
    assert "Buy Tax 20.0%" in res["reason"]
    assert "Honeypot" not in res["reason"]
    assert "Sell Tax" not in res["reason"]
    assert res["buy_tax"] == pytest.approx(20.0)


def test_honeypot_with_high_sell_tax_names_both(goplus):
    res = goplus(token(is_honeypot=1, sell_tax="0.3"))
    assert res["safe"] is False
    assert "Honeypot detected" in res["reason"]
    assert "Sell Tax 30.0%" in res["reason"]
    assert "Buy Tax" not in res["reason"]


def test_every_trigger_named_when_all_fire(goplus):
    res = goplus(token(is_honeypot=1, cannot_sell_all=1, buy_tax="0.25", sell_tax="0.5"))
    assert res["reason"] == ("High Risk Detected! Honeypot detected | Cannot sell all tokens (unsellable)"
                             " | Buy Tax 25.0% exceeds 15.0% | Sell Tax 50.0% exceeds 15.0%")


def test_taxes_exactly_at_threshold_are_allowed(goplus):
    res = goplus(token(buy_tax="0.15", sell_tax="0.15"))
    assert res["safe"] is True
    assert res["buy_tax"] == pytest.approx(15.0)
    assert res["sell_tax"] == pytest.approx(15.0)


def test_clean_token_allowed_with_taxes(goplus):
    res = goplus(token(buy_tax="0.03", sell_tax="0.05"))
    assert res == {"safe": True, "buy_tax": pytest.approx(3.0), "sell_tax": pytest.approx(5.0)}


def test_empty_result_keeps_no_data_message(goplus):
    res = goplus(payload={"result": {}})
    assert res == {"safe": False, "reason": "No security data available. Contract might be unverified."}


def test_non_200_keeps_unreachable_message(goplus):
    res = goplus(status=503, payload={})
    assert res == {"safe": False, "reason": "Security API unreachable. Transaction blocked to protect your funds."}
