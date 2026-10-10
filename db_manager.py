import sqlite3
import time

DB_PATH = "bot_database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_extended_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            token_address TEXT,
            entry_price REAL,
            tp_percent REAL,
            sl_percent REAL,
            is_active INTEGER DEFAULT 1,
            created_at REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            trade_type TEXT,
            token_address TEXT,
            amount_bnb REAL,
            fee_bnb REAL,
            tx_hash TEXT,
            timestamp REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_flags (
            name TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Columns added after the first release; existing databases gain them in place.
    # token_amount is the raw token quantity as text (uint256 overflows SQLite INTEGER).
    _add_column(cursor, "active_positions", "token_amount", "TEXT")
    _add_column(cursor, "active_positions", "cost_bnb", "REAL")
    _add_column(cursor, "trade_history", "realised_pnl_bnb", "REAL")
    conn.commit()
    conn.close()

def _add_column(cursor, table: str, column: str, col_type: str):
    cursor.execute(f"PRAGMA table_info({table})")
    if column not in {row[1] for row in cursor.fetchall()}:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

def log_trade(user_id: int, trade_type: str, token_addr: str, amount_bnb: float, fee_bnb: float, tx_hash: str,
              realised_pnl_bnb: float = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trade_history (user_id, trade_type, token_address, amount_bnb, fee_bnb, tx_hash, timestamp, realised_pnl_bnb)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, trade_type, token_addr, amount_bnb, fee_bnb, tx_hash, time.time(), realised_pnl_bnb))
    conn.commit()
    conn.close()

def add_position(user_id: int, token_addr: str, entry_price: float, tp_percent: float, sl_percent: float,
                 token_amount: int = None, cost_bnb: float = None):
    """tp_percent/sl_percent are None for a plain buy: it counts toward exposure but has no auto exit."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO active_positions (user_id, token_address, entry_price, tp_percent, sl_percent, is_active, created_at, token_amount, cost_bnb)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
    """, (user_id, token_addr, entry_price, tp_percent, sl_percent, time.time(),
          None if token_amount is None else str(int(token_amount)), cost_bnb))
    conn.commit()
    conn.close()

def get_active_positions():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_positions WHERE is_active = 1")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def close_position(pos_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE active_positions SET is_active = 0 WHERE id = ?", (pos_id,))
    conn.commit()
    conn.close()

def realise_sell(user_id: int, token_addr: str, sold_amount: int, proceeds_bnb: float, position_id: int = None):
    """Book a sale against open positions and return the realised PnL in BNB (None if nothing matched).

    With position_id, that position is closed outright (a TP/SL exit). Otherwise the
    sold quantity is matched against the user's positions in that token, oldest first;
    tokens beyond what the positions hold (sent to the wallet separately) carry no cost
    basis and their share of the proceeds is left out.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if position_id is not None:
        cursor.execute("SELECT * FROM active_positions WHERE id = ? AND is_active = 1", (position_id,))
    else:
        cursor.execute(
            "SELECT * FROM active_positions WHERE user_id = ? AND lower(token_address) = lower(?) "
            "AND is_active = 1 AND token_amount IS NOT NULL ORDER BY id",
            (user_id, token_addr)
        )
    rows = cursor.fetchall()

    remaining = int(sold_amount)
    matched = 0
    cost = 0.0
    for row in rows:
        qty = int(row["token_amount"] or 0)
        row_cost = row["cost_bnb"] or 0.0
        if position_id is None and remaining <= 0:
            break
        take = qty if position_id is not None else min(qty, remaining)
        if position_id is not None or take >= qty:
            cost += row_cost
            cursor.execute("UPDATE active_positions SET is_active = 0 WHERE id = ?", (row["id"],))
        else:
            cost += row_cost * take / qty
            cursor.execute("UPDATE active_positions SET token_amount = ?, cost_bnb = ? WHERE id = ?",
                           (str(qty - take), row_cost * (qty - take) / qty, row["id"]))
        remaining -= take
        matched += take
    conn.commit()
    conn.close()

    if not rows:
        return None
    if position_id is not None or sold_amount <= 0:
        return proceeds_bnb - cost
    return proceeds_bnb * min(matched, sold_amount) / sold_amount - cost

def get_open_exposure(user_id: int) -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(cost_bnb) FROM active_positions WHERE user_id = ? AND is_active = 1", (user_id,))
    total = cursor.fetchone()[0]
    conn.close()
    return total or 0.0

def get_realised_pnl_since(user_id: int, since: float) -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT SUM(realised_pnl_bnb) FROM trade_history WHERE user_id = ? AND timestamp >= ? AND realised_pnl_bnb IS NOT NULL",
        (user_id, since)
    )
    total = cursor.fetchone()[0]
    conn.close()
    return total or 0.0

def get_flag(name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_flags WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_flag(name: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO bot_flags (name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                   (name, value))
    conn.commit()
    conn.close()

def get_dashboard_metrics():
    conn = get_db_connection()
    cursor = conn.cursor()

    total_users = 0
    try:
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM users_wallets")
        total_users = cursor.fetchone()[0] or 0
    except Exception as e:
        pass

    total_volume = 0.0
    total_fees = 0.0
    total_trades = 0
    try:
        cursor.execute("SELECT SUM(amount_bnb), SUM(fee_bnb), COUNT(id) FROM trade_history")
        row = cursor.fetchone()
        if row:
            vol, fees, count = row
            total_volume = vol or 0.0
            total_fees = fees or 0.0
            total_trades = count or 0
    except Exception as e:
        pass

    recent_trades = []
    try:
        cursor.execute("SELECT trade_type, token_address, amount_bnb, fee_bnb, tx_hash FROM trade_history ORDER BY id DESC LIMIT 10")
        recent_trades = cursor.fetchall()
    except Exception as e:
        pass

    conn.close()

    return {
        "total_users": total_users,
        "total_volume": round(total_volume, 4),
        "total_fees": round(total_fees, 4),
        "total_trades": total_trades,
        "recent_trades": recent_trades
    }

def init_copy_trading_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS copy_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            whale_address TEXT,
            buy_amount REAL
        )
    """)
    conn.commit()
    conn.close()

def add_whale_target(user_id: int, whale_address: str, buy_amount: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO copy_targets (user_id, whale_address, buy_amount) VALUES (?, ?, ?)",
        (user_id, whale_address.lower(), buy_amount)
    )
    conn.commit()
    conn.close()

def get_all_whale_addresses() -> set:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT whale_address FROM copy_targets")
        rows = cursor.fetchall()
        addresses = {row[0].lower() for row in rows}
    except Exception:
        addresses = set()
    finally:
        conn.close()
    return addresses

def get_whale_followers(whale_address: str) -> list:
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, buy_amount FROM copy_targets WHERE whale_address = ?", (whale_address.lower(),))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

init_extended_db()
init_copy_trading_db()