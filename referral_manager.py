import os
import sqlite3
import time

DB_PATH = "bot_database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_referral_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            referred_by INTEGER,
            joined_at REAL
        )
    """)
    conn.commit()
    conn.close()

def register_referral(user_id: int, referred_by: int):
    if user_id == referred_by:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM referrals WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO referrals (user_id, referred_by, joined_at) VALUES (?, ?, ?)",
            (user_id, referred_by, time.time())
        )
        conn.commit()
    conn.close()

def calculate_fee_split(total_fee_wei: int, user_id: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT referred_by FROM referrals WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    referrer_id = row[0] if row else None
    
    if referrer_id:
        owner_share = int(total_fee_wei * 0.8)
        referrer_share = total_fee_wei - owner_share
        
        cursor.execute(
            "SELECT address FROM users_wallets WHERE user_id = ? AND chain_type = 'EVM' AND is_master = 1", 
            (referrer_id,)
        )
        referrer_wallet = cursor.fetchone()
        conn.close()
        
        return {
            "owner_share": owner_share,
            "referrer_share": referrer_share,
            "referrer_wallet": referrer_wallet[0] if referrer_wallet else None
        }
    
    conn.close()
    return {
        "owner_share": total_fee_wei, 
        "referrer_share": 0, 
        "referrer_wallet": None
    }

init_referral_db()