"""Local accounts and temporary guest libraries.

Everything lives under the SnapRecall home folder (SNAPRECALL_HOME, default ~/.snaprecall):

    accounts.db          usernames and scrypt password hashes (no passwords are stored)
    users/<id>/          each account's library: index.db, thumbnails/, cloud sign-in
    guests/<pid>-<sid>/  a guest session's library, deleted when the session ends
    cache/               model data shared by everyone (label prompt embeddings)

Accounts are local to this computer and separate from the optional cloud backup account.
Only SnapRecall's own data is ever deleted here; original screenshot files are never touched.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{3,64}$")
# A guest library is deleted once its session has been inactive this long, so a brief network
# drop (Streamlit reconnects to the same session) doesn't wipe it.
GUEST_GRACE_SECONDS = 60
LEGACY_FILES = ("index.db", "index.db-wal", "index.db-shm", "account.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    username   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    salt       BLOB NOT NULL,
    pw_hash    BLOB NOT NULL,
    created_at REAL NOT NULL
);
"""


class AccountError(ValueError):
    """A problem to show the user (bad password, name taken, ...)."""


@dataclass(frozen=True)
class User:
    id: int
    username: str


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)


class LocalAccounts:
    def __init__(self, home: str | Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.db_path = self.home / "accounts.db"
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    def user_dir(self, user: User) -> Path:
        return self.home / "users" / str(int(user.id))

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create(self, username: str, password: str) -> User:
        username = username.strip()
        if not USERNAME_RE.match(username):
            raise AccountError("Use 3–64 letters, numbers, or . _ @ - for the username.")
        if len(password) < MIN_PASSWORD:
            raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
        salt = secrets.token_bytes(16)
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO users (username, salt, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                    (username, salt, _hash(password, salt), time.time()))
        except sqlite3.IntegrityError:
            raise AccountError("That username is already taken on this computer.") from None
        user = User(cur.lastrowid, username)
        self.user_dir(user).mkdir(parents=True, exist_ok=True)
        return user

    def verify(self, username: str, password: str) -> User:
        with self._connect() as conn:
            row = conn.execute("SELECT id, username, salt, pw_hash FROM users WHERE username = ?",
                               (username.strip(),)).fetchone()
        # Hash even for unknown names so both failures take the same time.
        salt = row["salt"] if row else b"\0" * 16
        ok = hmac.compare_digest(_hash(password, salt), row["pw_hash"] if row else b"")
        if not (row and ok):
            raise AccountError("Wrong username or password.")
        return User(row["id"], row["username"])

    def delete(self, user: User, password: str) -> None:
        """Delete the account and its library (index, thumbnails). Screenshots are not touched."""
        self.verify(user.username, password)
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user.id,))
        shutil.rmtree(self.user_dir(user), ignore_errors=True)

    # ---- the library from before accounts existed ---------------------------
    def has_legacy_library(self) -> bool:
        return (self.home / "index.db").exists()

    def claim_legacy_library(self, user: User) -> None:
        """Move the pre-accounts library (home/index.db, thumbnails, cloud sign-in) into `user`."""
        dest = self.user_dir(user)
        dest.mkdir(parents=True, exist_ok=True)
        for name in LEGACY_FILES:
            if (self.home / name).exists():
                shutil.move(str(self.home / name), str(dest / name))
        old_thumbs, new_thumbs = self.home / "thumbnails", dest / "thumbnails"
        if old_thumbs.is_dir():
            new_thumbs.mkdir(exist_ok=True)
            for f in old_thumbs.iterdir():
                shutil.move(str(f), str(new_thumbs / f.name))
        self.cache_dir.mkdir(exist_ok=True)
        for f in self.home.glob("label_prompts_*.npz"):
            shutil.move(str(f), str(self.cache_dir / f.name))
        db = dest / "index.db"
        if db.exists():
            conn = sqlite3.connect(db)
            try:
                with conn:
                    rows = conn.execute("SELECT path, thumbnail FROM images WHERE thumbnail IS NOT NULL")
                    conn.executemany("UPDATE images SET thumbnail = ? WHERE path = ?",
                                     [(str(new_thumbs / Path(t).name), p) for p, t in rows.fetchall()])
            finally:
                conn.close()


# ---- guest libraries --------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class GuestLibraries:
    """Temporary libraries, one per guest browser session, deleted when the session ends."""

    def __init__(self, home: str | Path):
        self.root = Path(home) / "guests"
        self._inactive_since: dict[Path, float] = {}

    def path_for(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9-]", "", session_id)[:64] or "session"
        return self.root / f"{os.getpid()}-{safe}"

    @staticmethod
    def session_of(path: Path) -> tuple[int, str] | None:
        pid, _, sid = path.name.partition("-")
        return (int(pid), sid) if pid.isdigit() and sid else None

    def delete(self, path: Path) -> bool:
        shutil.rmtree(path, ignore_errors=True)
        self._inactive_since.pop(path, None)
        return not path.exists()

    def sweep(self, is_active: Callable[[str], bool], now: float | None = None) -> list[Path]:
        """Delete guest libraries whose session ended: this process's sessions that have been
        inactive for GUEST_GRACE_SECONDS, and any left by a SnapRecall process that has exited."""
        now = time.monotonic() if now is None else now
        removed = []
        if not self.root.is_dir():
            return removed
        for path in self.root.iterdir():
            owner = self.session_of(path)
            if owner is None or not path.is_dir():
                continue
            pid, sid = owner
            if pid != os.getpid():
                if not _pid_alive(pid) and self.delete(path):
                    removed.append(path)
                continue
            if is_active(sid):
                self._inactive_since.pop(path, None)
                continue
            first = self._inactive_since.setdefault(path, now)
            if now - first >= GUEST_GRACE_SECONDS and self.delete(path):
                removed.append(path)
        return removed

    def delete_all_mine(self) -> None:
        """Remove every guest library of this process (used when the app shuts down)."""
        if self.root.is_dir():
            for path in self.root.iterdir():
                owner = self.session_of(path)
                if owner and owner[0] == os.getpid():
                    self.delete(path)
