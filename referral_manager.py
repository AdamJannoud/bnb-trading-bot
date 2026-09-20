import os
import sqlite3
import time

DB_PATH = "bot_database.db"

def init_referral_db():
    conn = sqlite3.connect(DB_PATH)
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
        
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT referred_by FROM referrals WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    referrer_id = row[0] if row else None
    
    if referrer_id:
        owner_share = int(total_fee_wei * 0.8)
        referrer_share = total_fee_wei - owner_share
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT address FROM users WHERE user_id = ?", (referrer_id,))
        referrer_wallet = cursor.fetchone()
        conn.close()
        
        return {
            "owner_share": owner_share,
            "referrer_share": referrer_share,
            "referrer_wallet": referrer_wallet[0] if referrer_wallet else None
        }
    
    return {
        "owner_share": total_fee_wei, 
        "referrer_share": 0, 
        "referrer_wallet": None
    }

if not os.path.exists(DB_PATH):
    init_referral_db()