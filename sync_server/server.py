"""SnapRecall sync server: optional accounts and backed-up screenshots.

    uvicorn sync_server.server:app --port 8765

Data lives in SNAPRECALL_SERVER_DATA (default ./server_data): a SQLite
database of accounts and file records, plus one folder of image files per
account. The server only ever receives what a user explicitly backs up: the
original image bytes, the file name, and the modified time.

Security notes (also in the README):
- Passwords are stored as salted scrypt hashes; session tokens are random
  and stored only as SHA-256 hashes, expiring after 30 days.
- Each request is limited to the signed-in account's own files.
- Files are stored unencrypted on the server's disk. Serve the API over
  https (e.g. behind a reverse proxy) for anything beyond localhost.
- This has not had an independent security review.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import os
import re
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TOKEN_SECONDS = 30 * 24 * 3600
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash  BLOB NOT NULL,
    salt           BLOB NOT NULL,
    created_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sha256       TEXT NOT NULL,
    name         TEXT NOT NULL,
    size         INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    uploaded_at  REAL NOT NULL,
    PRIMARY KEY (user_id, sha256)
);
"""


class Credentials(BaseModel):
    email: str
    password: str


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"/\\|?*').strip(" .")
    return name[:200] or "screenshot.png"


def create_app(data_dir: str | Path) -> FastAPI:
    data_dir = Path(data_dir)
    files_dir = data_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "server.db"
    failures: dict[str, list[float]] = {}

    @contextmanager
    def db() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)

    def user_dir(user_id: int) -> Path:
        return files_dir / str(int(user_id))

    def bearer(authorization: str) -> str:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
        return token

    def current_user(authorization: str = Header(default="")) -> int:
        token = bearer(authorization)
        with db() as conn:
            row = conn.execute("SELECT user_id, expires_at FROM tokens WHERE token_hash = ?",
                               (_token_hash(token),)).fetchone()
        if row is None or row["expires_at"] < time.time():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.")
        return row["user_id"]

    def check_sha(sha256: str) -> str:
        if not SHA_RE.match(sha256):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid file id.")
        return sha256

    app = FastAPI(title="SnapRecall sync", docs_url=None, redoc_url=None)

    # ---- accounts ----------------------------------------------------------
    @app.post("/register", status_code=status.HTTP_201_CREATED)
    def register(creds: Credentials):
        email = creds.email.strip()
        if not EMAIL_RE.match(email) or len(email) > 254:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a valid email address.")
        if not 8 <= len(creds.password) <= 1024:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use a password of at least 8 characters.")
        salt = secrets.token_bytes(16)
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO users (email, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                    (email, _hash_password(creds.password, salt), salt, time.time()),
                )
        except sqlite3.IntegrityError:
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.") from None
        return {"email": email}

    @app.post("/login")
    def login(creds: Credentials):
        email = creds.email.strip()
        key = email.lower()
        now = time.time()
        recent = [t for t in failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
        if len(recent) >= LOGIN_MAX_FAILURES:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "Too many failed sign-in attempts. Try again in 15 minutes.")
        with db() as conn:
            user = conn.execute("SELECT id, email, password_hash, salt FROM users WHERE email = ?",
                                (email,)).fetchone()
        if user is None or not hmac.compare_digest(
            _hash_password(creds.password, user["salt"]), user["password_hash"]
        ):
            failures[key] = recent + [now]
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
        failures.pop(key, None)
        token = secrets.token_urlsafe(32)
        with db() as conn:
            conn.execute("DELETE FROM tokens WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                         (_token_hash(token), user["id"], now + TOKEN_SECONDS))
        return {"token": token, "email": user["email"]}

    @app.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(authorization: str = Header(default="")):
        with db() as conn:
            conn.execute("DELETE FROM tokens WHERE token_hash = ?", (_token_hash(bearer(authorization)),))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/me")
    def me(user_id: int = Depends(current_user)):
        with db() as conn:
            user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            stats = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM files "
                                 "WHERE user_id = ?", (user_id,)).fetchone()
        return {"email": user["email"], "file_count": stats["n"], "bytes": stats["bytes"]}

    @app.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
    def delete_account(user_id: int = Depends(current_user)):
        shutil.rmtree(user_dir(user_id), ignore_errors=True)
        with db() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ---- files -------------------------------------------------------------
    @app.get("/files")
    def list_files(user_id: int = Depends(current_user)):
        with db() as conn:
            rows = conn.execute("SELECT sha256, name, size, mtime_ns, uploaded_at FROM files "
                                "WHERE user_id = ? ORDER BY mtime_ns DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    @app.put("/files/{sha256}", status_code=status.HTTP_201_CREATED)
    async def upload(sha256: str, name: str, mtime_ns: int, request: Request,
                     user_id: int = Depends(current_user)):
        check_sha(sha256)
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "This file is too large to back up.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD_BYTES:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "This file is too large to back up.")
        if hashlib.sha256(body).hexdigest() != sha256:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The upload was corrupted. Try again.")
        try:
            with Image.open(io.BytesIO(body)) as img:
                fmt = img.format
                img.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            fmt = None
        if fmt not in ("PNG", "JPEG"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PNG and JPEG images can be backed up.")

        folder = user_dir(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{sha256}.{secrets.token_hex(4)}.tmp"
        tmp.write_bytes(body)
        os.replace(tmp, folder / sha256)
        with db() as conn:
            conn.execute(
                "INSERT INTO files (user_id, sha256, name, size, mtime_ns, uploaded_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, sha256) DO UPDATE SET name = excluded.name, mtime_ns = excluded.mtime_ns",
                (user_id, sha256, _safe_name(name), len(body), int(mtime_ns), time.time()),
            )
        return {"sha256": sha256}

    @app.get("/files/{sha256}")
    def download(sha256: str, user_id: int = Depends(current_user)):
        check_sha(sha256)
        with db() as conn:
            row = conn.execute("SELECT 1 FROM files WHERE user_id = ? AND sha256 = ?",
                               (user_id, sha256)).fetchone()
        path = user_dir(user_id) / sha256
        if row is None or not path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
        return FileResponse(path, media_type="application/octet-stream")

    @app.delete("/files/{sha256}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_file(sha256: str, user_id: int = Depends(current_user)):
        check_sha(sha256)
        with db() as conn:
            conn.execute("DELETE FROM files WHERE user_id = ? AND sha256 = ?", (user_id, sha256))
        (user_dir(user_id) / sha256).unlink(missing_ok=True)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.delete("/files", status_code=status.HTTP_204_NO_CONTENT)
    def delete_all_files(user_id: int = Depends(current_user)):
        with db() as conn:
            conn.execute("DELETE FROM files WHERE user_id = ?", (user_id,))
        shutil.rmtree(user_dir(user_id), ignore_errors=True)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    # `uvicorn sync_server.server:app` builds the app on first access, so merely
    # importing this module (e.g. in tests) doesn't create a data folder.
    global _app
    if name == "app":
        if _app is None:
            _app = create_app(os.environ.get("SNAPRECALL_SERVER_DATA", "server_data"))
        return _app
    raise AttributeError(name)
