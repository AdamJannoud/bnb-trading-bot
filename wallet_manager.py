import os
import sqlite3
from eth_account import Account
from cryptography.fernet import Fernet
from solana_engine import generate_solana_wallet

Account.enable_unaudited_hdwallet_features()

DB_NAME = "bot_database.db"
KEY_FILE = "secret.key"

def load_or_generate_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
    return Fernet(key)

cipher = load_or_generate_key()

def init_wallet_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # ترقية الجدول لدعم المحافظ المتعددة
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chain_type TEXT DEFAULT 'EVM',
            address TEXT NOT NULL,
            encrypted_private_key TEXT NOT NULL,
            is_master INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

def get_or_create_wallet(user_id: int, chain_type: str = 'EVM', is_master: int = 1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT address FROM users_wallets WHERE user_id = ? AND chain_type = ? AND is_master = ?", 
        (user_id, chain_type, is_master)
    )
    row = cursor.fetchone()

    if row:
        conn.close()
        return {"address": row[0], "is_new": False}

    if chain_type == 'EVM':
        new_account = Account.create()
        address = new_account.address
        private_key = new_account.key.hex()
    else:
        sol_wallet = generate_solana_wallet()
        address = sol_wallet["address"]
        private_key = sol_wallet["private_key"]

    encrypted_key = cipher.encrypt(private_key.encode()).decode()

    cursor.execute(
        "INSERT INTO users_wallets (user_id, chain_type, address, encrypted_private_key, is_master) VALUES (?, ?, ?, ?, ?)",
        (user_id, chain_type, address, encrypted_key, is_master)
    )
    conn.commit()
    conn.close()
    return {"address": address, "is_new": True}

def get_decrypted_private_key(user_id: int, chain_type: str = 'EVM', is_master: int = 1):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT encrypted_private_key FROM users_wallets WHERE user_id = ? AND chain_type = ? AND is_master = ?", 
        (user_id, chain_type, is_master)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return cipher.decrypt(row[0].encode()).decode()

init_wallet_db()