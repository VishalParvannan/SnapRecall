"""Password hashing shared by local accounts and the sync server.

Hashes are salted scrypt. Each stored hash records the parameters that made it (for example
"scrypt:131072:8:1"), so the cost can be raised later: a hash made with other parameters is
still checked with its own, and replaced with a current one at the next successful sign-in.
Rows from before parameters were stored used LEGACY_PARAMS.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# OWASP Password Storage Cheat Sheet minimum for scrypt: N=2^17, r=8, p=1 (128 MiB, about
# 1 s per hash on a laptop CPU). Tests lower SCRYPT_N to stay fast (tests/conftest.py).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
LEGACY_PARAMS = "scrypt:16384:8:1"
SALT_BYTES = 16
DKLEN = 32


class UnknownHashFormat(ValueError):
    """A stored hash names parameters this version can't use."""


def current_params() -> str:
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}"


def _parse(params: str | None) -> tuple[int, int, int]:
    kind, *values = (params or LEGACY_PARAMS).split(":")
    if kind != "scrypt" or len(values) != 3:
        raise UnknownHashFormat(params)
    n, r, p = (int(v) for v in values)
    if n < 2 or n & (n - 1) or r < 1 or p < 1:
        raise UnknownHashFormat(params)
    return n, r, p


def hash_password(password: str, salt: bytes, params: str | None) -> bytes:
    n, r, p = _parse(params)
    # scrypt needs about 128 * n * r * p bytes; OpenSSL refuses more than maxmem (32 MiB by default).
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN,
                          maxmem=128 * n * r * p + (32 << 20))


def new_hash(password: str) -> tuple[bytes, bytes, str]:
    """(salt, hash, parameters) for a new password."""
    salt, params = secrets.token_bytes(SALT_BYTES), current_params()
    return salt, hash_password(password, salt, params), params


def check(password: str, salt: bytes | None, stored: bytes | None, params: str | None) -> bool:
    """True if `password` matches. With no stored hash (unknown user) a hash is still computed,
    with current parameters, so both kinds of failure take about the same time."""
    if stored is None or salt is None:
        hash_password(password, b"\0" * SALT_BYTES, current_params())
        return False
    return hmac.compare_digest(hash_password(password, salt, params), stored)


def needs_rehash(params: str | None) -> bool:
    return _parse(params) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
