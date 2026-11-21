import sqlite3

import pytest

import passwords
from accounts import AccountError, LocalAccounts, LoginThrottle
from conftest import PRODUCTION_SCRYPT_N


def test_default_cost_meets_owasp_minimum():
    # OWASP Password Storage Cheat Sheet: scrypt N=2^17, r=8, p=1.
    assert PRODUCTION_SCRYPT_N >= 2**17
    assert (passwords.SCRYPT_R, passwords.SCRYPT_P) == (8, 1)


def test_full_cost_hash_works_and_is_deterministic():
    # hashlib.scrypt refuses N=2^17 with its default 32 MiB memory limit; hash_password raises it.
    params = f"scrypt:{2**17}:8:1"
    first = passwords.hash_password("correct horse", b"s" * 16, params)
    assert len(first) == passwords.DKLEN
    assert first == passwords.hash_password("correct horse", b"s" * 16, params)
    assert first != passwords.hash_password("correct horse", b"t" * 16, params)


def test_check_and_rehash():
    salt, stored, params = passwords.new_hash("correct horse")
    assert params == passwords.current_params()
    assert passwords.check("correct horse", salt, stored, params)
    assert not passwords.check("wrong horse", salt, stored, params)
    assert not passwords.check("correct horse", None, None, None)  # unknown user
    assert not passwords.needs_rehash(params)
    assert passwords.needs_rehash(None)  # legacy rows
    with pytest.raises(passwords.UnknownHashFormat):
        passwords.hash_password("x", salt, "bcrypt:12")


def _legacy_row(home, username, password):
    """An accounts.db row as written before hash parameters were stored (scrypt N=2^14, no kdf)."""
    acc = LocalAccounts(home)
    salt = b"legacy-salt-0001"
    with sqlite3.connect(acc.db_path) as conn:
        conn.execute("INSERT INTO users (username, salt, pw_hash, created_at, kdf) VALUES (?, ?, ?, 0, NULL)",
                     (username, salt, passwords.hash_password(password, salt, passwords.LEGACY_PARAMS)))
    return acc


def _kdf(acc, username):
    with sqlite3.connect(acc.db_path) as conn:
        return conn.execute("SELECT kdf FROM users WHERE username = ?", (username,)).fetchone()[0]


def test_new_accounts_store_current_parameters(tmp_path):
    acc = LocalAccounts(tmp_path)
    acc.create("sam", "correct horse")
    assert _kdf(acc, "sam") == passwords.current_params()


def test_legacy_hash_is_upgraded_at_sign_in(tmp_path):
    acc = _legacy_row(tmp_path, "sam", "correct horse")
    with pytest.raises(AccountError):
        acc.verify("sam", "wrong horse")
    assert _kdf(acc, "sam") is None  # a wrong password changes nothing
    user = acc.verify("sam", "correct horse")
    assert _kdf(acc, "sam") == passwords.current_params()
    assert acc.verify("sam", "correct horse") == user  # still works after the upgrade


def test_old_database_gains_the_kdf_column(tmp_path):
    with sqlite3.connect(tmp_path / "accounts.db") as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, "
                     "salt BLOB NOT NULL, pw_hash BLOB NOT NULL, created_at REAL NOT NULL)")
        salt = b"legacy-salt-0001"
        conn.execute("INSERT INTO users (username, salt, pw_hash, created_at) VALUES ('sam', ?, ?, 0)",
                     (salt, passwords.hash_password("correct horse", salt, passwords.LEGACY_PARAMS)))
    acc = LocalAccounts(tmp_path)
    assert acc.verify("sam", "correct horse").username == "sam"
    assert _kdf(acc, "sam") == passwords.current_params()


def test_unknown_hash_format_is_refused(tmp_path):
    acc = LocalAccounts(tmp_path)
    acc.create("sam", "correct horse")
    with sqlite3.connect(acc.db_path) as conn:
        conn.execute("UPDATE users SET kdf = 'argon2id:1'")
    with pytest.raises(AccountError, match="Wrong"):
        acc.verify("sam", "correct horse")


def test_login_throttle():
    now = [0.0]
    throttle = LoginThrottle(attempts=3, window=60, clock=lambda: now[0])
    for _ in range(3):
        assert not throttle.blocked("Sam")
        throttle.failed("Sam")
    assert throttle.blocked("sam")  # names ignore case
    assert not throttle.blocked("ana")  # other names unaffected
    now[0] = 61
    assert not throttle.blocked("sam")  # failures expire after the window
    throttle.failed("sam")
    throttle.succeeded("SAM")
    for _ in range(2):
        throttle.failed("sam")
    assert not throttle.blocked("sam")  # a success cleared the earlier failure
