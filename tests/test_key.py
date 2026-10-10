"""Fix 3: a missing or wrong encryption key stops startup instead of minting a new key."""
import os
import sqlite3
import subprocess  # nosec B404 # the test drives the real CLI startup in a child process
import sys

import pytest
from cryptography.fernet import Fernet

import wallet_manager
from wallet_manager import KEY_ENV_VAR, KeyConfigError, KeyNotConfigured, load_cipher

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_db(directory, key):
    path = os.path.join(directory, "bot_database.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users_wallets (id INTEGER PRIMARY KEY, user_id INTEGER, chain_type TEXT, "
                 "address TEXT, encrypted_private_key TEXT, is_master INTEGER)")
    token = Fernet(key).encrypt(b"dummy-wallet-secret").decode()
    conn.execute("INSERT INTO users_wallets VALUES (1, 1, 'EVM', '0x0', ?, 1)", (token,))
    conn.commit()
    conn.close()
    return path


def test_missing_key_with_wallets_refuses(tmp_path):
    db = make_db(str(tmp_path), Fernet.generate_key())
    with pytest.raises(KeyConfigError, match="Refusing to start") as exc:
        load_cipher(environ={}, db_path=db)
    assert not isinstance(exc.value, KeyNotConfigured)
    assert sorted(os.listdir(tmp_path)) == ["bot_database.db"]


def test_missing_key_on_empty_database_is_first_run(tmp_path):
    with pytest.raises(KeyNotConfigured):
        load_cipher(environ={}, db_path=str(tmp_path / "bot_database.db"))
    assert os.listdir(tmp_path) == []


def test_legacy_key_file_is_not_read(tmp_path):
    (tmp_path / "secret.key").write_text("placeholder")
    with pytest.raises(KeyConfigError, match=r"secret.key"):
        load_cipher(environ={}, db_path=str(tmp_path / "bot_database.db"))


def test_wrong_key_fails_boot_self_test(tmp_path):
    db = make_db(str(tmp_path), Fernet.generate_key())
    with pytest.raises(KeyConfigError, match="does not decrypt"):
        load_cipher(environ={KEY_ENV_VAR: Fernet.generate_key().decode()}, db_path=db)


def test_malformed_key_refuses(tmp_path):
    with pytest.raises(KeyConfigError, match="not a valid Fernet key"):
        load_cipher(environ={KEY_ENV_VAR: "too-short"}, db_path=str(tmp_path / "bot_database.db"))


def test_matching_key_loads(tmp_path):
    key = Fernet.generate_key()
    db = make_db(str(tmp_path), key)
    cipher = load_cipher(environ={KEY_ENV_VAR: key.decode()}, db_path=db)
    assert cipher.decrypt(Fernet(key).encrypt(b"x")) == b"x"


def _start(cwd):
    env = {k: v for k, v in os.environ.items() if k != KEY_ENV_VAR}
    env["PYTHONPATH"] = REPO
    return subprocess.run([sys.executable, "-c", "import wallet_manager"], cwd=cwd, env=env,  # nosec B603 # fixed argv, no shell
                          capture_output=True, text=True, timeout=60, check=False)


def test_process_refuses_to_start_without_key(tmp_path):
    make_db(str(tmp_path), Fernet.generate_key())
    proc = _start(tmp_path)
    assert proc.returncode != 0
    assert "Refusing to start" in proc.stderr
    assert not (tmp_path / "secret.key").exists()


def test_first_run_prints_key_once_and_writes_nothing(tmp_path):
    proc = _start(tmp_path)
    assert proc.returncode == 1
    assert KEY_ENV_VAR in proc.stderr and "shown only this once" in proc.stderr
    assert os.listdir(tmp_path) == []


def test_module_uses_env_key():
    key = os.environ[KEY_ENV_VAR].encode()
    assert wallet_manager.cipher.decrypt(Fernet(key).encrypt(b"y")) == b"y"
