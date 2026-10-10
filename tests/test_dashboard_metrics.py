"""get_dashboard_metrics is total: whatever fails, the owner gets zeroed metrics."""
import os
import sqlite3

import pytest

import db_manager

ZERO = {"total_users": 0, "total_volume": 0.0, "total_fees": 0.0, "total_trades": 0, "recent_trades": []}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "metrics.db")
    monkeypatch.setattr(db_manager, "DB_PATH", path)
    return path


def test_missing_tables_give_zero_metrics(db_path):
    assert db_manager.get_dashboard_metrics() == ZERO


def test_db_path_is_a_directory_gives_zero_metrics(db_path):
    os.mkdir(db_path)
    assert db_manager.get_dashboard_metrics() == ZERO


def test_corrupt_db_file_gives_zero_metrics(db_path):
    with open(db_path, "wb") as f:
        f.write(b"this is not a sqlite database" * 100)
    assert db_manager.get_dashboard_metrics() == ZERO


def test_unopenable_location_gives_zero_metrics(db_path, monkeypatch):
    monkeypatch.setattr(db_manager, "DB_PATH", os.path.join(db_path, "no", "such", "dir", "x.db"))
    assert db_manager.get_dashboard_metrics() == ZERO


def test_cursor_failure_gives_zero_metrics_and_closes(monkeypatch):
    closed = []

    class BrokenConn:
        def cursor(self):
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(db_manager, "get_db_connection", BrokenConn)
    assert db_manager.get_dashboard_metrics() == ZERO
    assert closed == [True]


def test_failing_query_still_closes_connection(db_path, monkeypatch):
    closed = []
    real = db_manager.get_db_connection

    class Tracked:
        def __init__(self):
            self._conn = real()

        def cursor(self):
            return self._conn.cursor()

        def close(self):
            closed.append(True)
            self._conn.close()

    monkeypatch.setattr(db_manager, "get_db_connection", Tracked)
    assert db_manager.get_dashboard_metrics() == ZERO
    assert closed == [True]


def test_known_rows_give_correct_totals(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users_wallets (id INTEGER PRIMARY KEY, user_id INTEGER, chain_type TEXT, "
                 "address TEXT, encrypted_private_key TEXT, is_master INTEGER)")
    conn.executemany("INSERT INTO users_wallets (user_id, chain_type) VALUES (?, ?)",
                     [(1, "EVM"), (1, "SOL"), (2, "EVM"), (3, "EVM")])
    conn.execute("CREATE TABLE trade_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
                 "trade_type TEXT, token_address TEXT, amount_bnb REAL, fee_bnb REAL, tx_hash TEXT, timestamp REAL)")
    rows = [(1, "BUY" if i % 2 else "SELL", f"0xtok{i}", 0.100013, 0.0010004, f"0xhash{i}", float(i))
            for i in range(1, 13)]
    conn.executemany("INSERT INTO trade_history (user_id, trade_type, token_address, amount_bnb, fee_bnb, "
                     "tx_hash, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()

    m = db_manager.get_dashboard_metrics()
    assert m["total_users"] == 3
    assert m["total_trades"] == 12
    # 12 * 0.100013 = 1.200156 and 12 * 0.0010004 = 0.0120048, each rounded to 4 places.
    assert m["total_volume"] == 1.2002
    assert m["total_fees"] == 0.012
    assert len(m["recent_trades"]) == 10
    assert m["recent_trades"][0] == ("BUY" if 12 % 2 else "SELL", "0xtok12", 0.100013, 0.0010004, "0xhash12")
    assert [t[1] for t in m["recent_trades"]] == [f"0xtok{i}" for i in range(12, 2, -1)]
