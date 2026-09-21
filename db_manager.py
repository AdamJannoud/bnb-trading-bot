import sqlite3
import time

DB_PATH = "bot_database.db"

def init_extended_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()

def log_trade(user_id: int, trade_type: str, token_addr: str, amount_bnb: float, fee_bnb: float, tx_hash: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trade_history (user_id, trade_type, token_address, amount_bnb, fee_bnb, tx_hash, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, trade_type, token_addr, amount_bnb, fee_bnb, tx_hash, time.time()))
    conn.commit()
    conn.close()

def add_position(user_id: int, token_addr: str, entry_price: float, tp_percent: float, sl_percent: float):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO active_positions (user_id, token_address, entry_price, tp_percent, sl_percent, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (user_id, token_addr, entry_price, tp_percent, sl_percent, time.time()))
    conn.commit()
    conn.close()

def get_active_positions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_positions WHERE is_active = 1")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def close_position(pos_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE active_positions SET is_active = 0 WHERE id = ?", (pos_id,))
    conn.commit()
    conn.close()

def get_dashboard_metrics():
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO copy_targets (user_id, whale_address, buy_amount) VALUES (?, ?, ?)",
        (user_id, whale_address.lower(), buy_amount)
    )
    conn.commit()
    conn.close()

def get_all_whale_addresses() -> set:
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, buy_amount FROM copy_targets WHERE whale_address = ?", (whale_address.lower(),))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

init_extended_db()
init_copy_trading_db()