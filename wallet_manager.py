import logging
import os
import sqlite3
import sys

from cryptography.fernet import Fernet, InvalidToken
from eth_account import Account

from solana_engine import generate_solana_wallet

Account.enable_unaudited_hdwallet_features()

DB_NAME = "bot_database.db"
KEY_ENV_VAR = "WALLET_ENCRYPTION_KEY"
# Where older versions kept the key, next to the database. No longer read.
LEGACY_KEY_FILE = "secret.key"

class KeyConfigError(RuntimeError):
    """The wallet encryption key is missing or wrong. The bot must not start."""

class KeyNotConfigured(KeyConfigError):
    """No key is set and no wallets exist yet: a first run."""

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def _first_stored_wallet(db_path: str):
    """One encrypted key from the database, or None when there are no wallets. Never creates the file."""
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=30.0)
    try:
        row = conn.execute("SELECT encrypted_private_key FROM users_wallets LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    return row[0] if row else None

def load_cipher(environ=None, db_path: str | None = None) -> Fernet:
    environ = os.environ if environ is None else environ
    db_path = db_path or DB_NAME
    legacy_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), LEGACY_KEY_FILE)
    raw_key = environ.get(KEY_ENV_VAR, "").strip()
    stored = _first_stored_wallet(db_path)

    if not raw_key:
        if os.path.exists(legacy_path):
            raise KeyConfigError(
                f"{KEY_ENV_VAR} is not set, and a legacy {LEGACY_KEY_FILE} sits next to the database at {legacy_path}. "
                f"The key is no longer read from that file. Put its contents into {KEY_ENV_VAR}, then move the file "
                f"out of the database directory. Refusing to start."
            )
        if stored is not None:
            raise KeyConfigError(
                f"{KEY_ENV_VAR} is not set and {db_path} holds wallets. Refusing to start: generating a new key "
                f"would make every stored wallet undecryptable. Set {KEY_ENV_VAR} to the key these wallets were encrypted with."
            )
        raise KeyNotConfigured(f"{KEY_ENV_VAR} is not set and no wallets exist yet.")

    try:
        cipher = Fernet(raw_key.encode())
    except Exception:
        raise KeyConfigError(f"{KEY_ENV_VAR} is not a valid Fernet key. Refusing to start.") from None

    # Boot self-test: prove the key fits the data now, not at the first trade.
    if stored is not None:
        try:
            cipher.decrypt(stored.encode())
        except InvalidToken:
            raise KeyConfigError(
                f"{KEY_ENV_VAR} does not decrypt the wallets stored in {db_path} (wrong key?). Refusing to start."
            ) from None

    if os.path.exists(legacy_path):
        logging.warning(f"A legacy {LEGACY_KEY_FILE} still sits next to the database at {legacy_path}. "
                        f"It is no longer used; move it off this directory.")
    return cipher

def _startup_cipher() -> Fernet:
    try:
        return load_cipher()
    except KeyNotConfigured:
        # First run on an empty database: mint a key, show it once, write it nowhere.
        new_key = Fernet.generate_key().decode()
        sys.stderr.write(
            f"\n{KEY_ENV_VAR} is not set and there are no wallets yet. A new key was generated:\n\n"
            f"    {new_key}\n\n"
            f"It is shown only this once and has not been saved anywhere. Store it safely, set {KEY_ENV_VAR} "
            f"to it, and start the bot again.\n\n"
        )
        raise SystemExit(1)
    except KeyConfigError as e:
        raise SystemExit(f"FATAL: {e}")

cipher = _startup_cipher()

def init_wallet_db():
    conn = get_db_connection()
    cursor = conn.cursor()
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
    conn = get_db_connection()
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
    elif chain_type == 'SOLANA':
        sol_wallet = generate_solana_wallet()
        address = sol_wallet["address"]
        private_key = sol_wallet["private_key"]
    else:
        conn.close()
        raise ValueError(f"Unsupported chain type: {chain_type}")

    encrypted_key = cipher.encrypt(private_key.encode()).decode()

    cursor.execute(
        "INSERT INTO users_wallets (user_id, chain_type, address, encrypted_private_key, is_master) VALUES (?, ?, ?, ?, ?)",
        (user_id, chain_type, address, encrypted_key, is_master)
    )
    conn.commit()
    conn.close()
    return {"address": address, "is_new": True}

def get_decrypted_private_key(user_id: int, chain_type: str = 'EVM', is_master: int = 1):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT encrypted_private_key FROM users_wallets WHERE user_id = ? AND chain_type = ? AND is_master = ?", 
        (user_id, chain_type, is_master)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    try:
        return cipher.decrypt(row[0].encode()).decode()
    except Exception:
        raise ValueError(f"Critical Security Error: Cannot decrypt private key. Check {KEY_ENV_VAR}.")

init_wallet_db()