"""SQLite storage for images, folders, and indexing state.

Images and folders are stored separately: `folder_images` records which
indexed folders contain each image, so overlapping folders (a parent and
one of its subfolders) can both be indexed without interfering.

Every operation opens its own short-lived connection, so the Storage
object is safe to share between Streamlit sessions and threads.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterator

import numpy as np

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    path         TEXT PRIMARY KEY,
    size         INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    width        INTEGER,
    height       INTEGER,
    thumbnail    TEXT,
    status       TEXT NOT NULL DEFAULT 'ok',   -- ok | partial | error
    error        TEXT,
    ocr_text     TEXT,
    ocr_model    TEXT,
    embedding    BLOB,
    embed_model  TEXT,
    embed_dim    INTEGER,
    sha256       TEXT,                         -- content hash, computed for backup
    indexed_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS folders (
    path                TEXT PRIMARY KEY,
    added_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_opened_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_scan_at        TEXT,
    last_scan_complete  INTEGER,
    backup              INTEGER NOT NULL DEFAULT 0  -- user opted in to account backup
);
CREATE TABLE IF NOT EXISTS folder_images (
    folder  TEXT NOT NULL REFERENCES folders(path) ON DELETE CASCADE,
    image   TEXT NOT NULL REFERENCES images(path) ON DELETE CASCADE,
    PRIMARY KEY (folder, image)
);
CREATE TABLE IF NOT EXISTS removed_images (   -- screenshots the user removed; skipped by later scans
    path        TEXT PRIMARY KEY,
    removed_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_folder_images_image ON folder_images(image);
"""


@dataclass
class ImageRecord:
    path: str
    size: int
    mtime_ns: int
    width: int | None = None
    height: int | None = None
    thumbnail: str | None = None
    status: str = "ok"
    error: str | None = None
    ocr_text: str | None = None
    ocr_model: str | None = None
    embedding: np.ndarray | None = None
    embed_model: str | None = None
    sha256: str | None = None

    @property
    def name(self) -> str:
        return Path(self.path).name


@dataclass
class FolderInfo:
    path: str
    last_scan_at: str | None
    last_scan_complete: bool | None
    image_count: int
    backup: bool = False


_COLUMNS = [f.name for f in fields(ImageRecord)] + ["embed_dim"]


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            has_tables = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
            ).fetchone()
            if has_tables and version == 2:
                # Version 3 only adds columns, so existing indexes are kept.
                conn.execute("ALTER TABLE images ADD COLUMN sha256 TEXT")
                conn.execute("ALTER TABLE folders ADD COLUMN backup INTEGER NOT NULL DEFAULT 0")
            elif has_tables and version != SCHEMA_VERSION:
                # The index is a rebuildable cache, so an outdated schema is dropped.
                conn.executescript(
                    "DROP TABLE IF EXISTS folder_images; DROP TABLE IF EXISTS folders;"
                    "DROP TABLE IF EXISTS images;"
                )
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---- images ------------------------------------------------------------
    def upsert_image(self, rec: ImageRecord) -> None:
        values = _to_row(rec)
        cols = ", ".join(_COLUMNS)
        marks = ", ".join("?" for _ in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "path")
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO images ({cols}) VALUES ({marks}) "
                f"ON CONFLICT(path) DO UPDATE SET {updates}, indexed_at=CURRENT_TIMESTAMP",
                [values[c] for c in _COLUMNS],
            )

    def get(self, path: str) -> ImageRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM images WHERE path = ?", (path,)).fetchone()
        return _to_record(row) if row else None

    def get_many(self, paths: list[str]) -> dict[str, ImageRecord]:
        found: dict[str, ImageRecord] = {}
        with self._connect() as conn:
            for start in range(0, len(paths), 500):
                chunk = paths[start:start + 500]
                marks = ", ".join("?" for _ in chunk)
                for row in conn.execute(f"SELECT * FROM images WHERE path IN ({marks})", chunk):
                    found[row["path"]] = _to_record(row)
        return found

    def remove_images(self, paths: list[str]) -> list[ImageRecord]:
        """Remove images from the library and remember them so re-indexing doesn't bring them back.

        Only index data is deleted; the files on disk are never touched. Returns the removed
        records so the caller can clean up their thumbnails.
        """
        removed = list(self.get_many(paths).values())
        with self._connect() as conn:
            conn.executemany("INSERT OR IGNORE INTO removed_images (path) VALUES (?)",
                             [(p,) for p in paths])
            conn.executemany("DELETE FROM images WHERE path = ?", [(p,) for p in paths])
        return removed

    def rename_image(self, old: str, new: str, thumbnail: str | None) -> None:
        """Move an image's index data and folder memberships to a new path in one transaction."""
        rec = self.get(old)
        if rec is None:
            raise KeyError(old)
        rec.path, rec.thumbnail = new, thumbnail
        values = _to_row(rec)
        with self._connect() as conn:
            conn.execute(f"INSERT INTO images ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
                         [values[c] for c in _COLUMNS])
            conn.execute("UPDATE folder_images SET image = ? WHERE image = ?", (new, old))
            conn.execute("DELETE FROM images WHERE path = ?", (old,))
            conn.execute("DELETE FROM removed_images WHERE path = ?", (new,))

    def removed_paths(self) -> set[str]:
        with self._connect() as conn:
            return {r["path"] for r in conn.execute("SELECT path FROM removed_images")}

    def restore_removed(self) -> int:
        """Forget all removals, so the next re-index adds those screenshots again."""
        with self._connect() as conn:
            return conn.execute("DELETE FROM removed_images").rowcount

    # ---- folders and membership ------------------------------------------
    def save_folder(self, folder: str, complete: bool | None = None) -> None:
        """Register a folder; when `complete` is given, record a finished scan."""
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO folders (path) VALUES (?)", (folder,))
            if complete is not None:
                conn.execute(
                    "UPDATE folders SET last_scan_at = CURRENT_TIMESTAMP, last_scan_complete = ? "
                    "WHERE path = ?",
                    (int(complete), folder),
                )

    def mark_opened(self, folder: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE folders SET last_opened_at = CURRENT_TIMESTAMP WHERE path = ?", (folder,)
            )

    def list_folders(self) -> list[FolderInfo]:
        """Indexed folders, most recently opened first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT f.path, f.last_scan_at, f.last_scan_complete, f.backup,
                          (SELECT COUNT(*) FROM folder_images m WHERE m.folder = f.path) AS n
                   FROM folders f ORDER BY f.last_opened_at DESC, f.rowid DESC"""
            ).fetchall()
        return [
            FolderInfo(
                r["path"], r["last_scan_at"],
                None if r["last_scan_complete"] is None else bool(r["last_scan_complete"]),
                r["n"], bool(r["backup"]),
            )
            for r in rows
        ]

    def set_backup(self, folder: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE folders SET backup = ? WHERE path = ?", (int(enabled), folder))

    def set_sha256(self, path: str, sha256: str, size: int, mtime_ns: int) -> None:
        """Record a content hash, only if the file is still the version that was indexed."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE images SET sha256 = ? WHERE path = ? AND size = ? AND mtime_ns = ?",
                (sha256, path, size, mtime_ns),
            )

    def member_paths(self, folder: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT image FROM folder_images WHERE folder = ?", (folder,))
            return {r["image"] for r in rows}

    def add_members(self, folder: str, paths: list[str]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO folder_images (folder, image) VALUES (?, ?)",
                [(folder, p) for p in paths],
            )

    def remove_members(self, folder: str, paths: list[str]) -> list[ImageRecord]:
        """Remove images from a folder. Returns images no longer in any folder (now deleted)."""
        with self._connect() as conn:
            conn.executemany(
                "DELETE FROM folder_images WHERE folder = ? AND image = ?",
                [(folder, p) for p in paths],
            )
            return _delete_orphans(conn, paths)

    def remove_folder(self, folder: str) -> list[ImageRecord]:
        """Forget a folder. Returns images no longer in any folder (now deleted)."""
        paths = sorted(self.member_paths(folder))
        with self._connect() as conn:
            conn.execute("DELETE FROM folders WHERE path = ?", (folder,))
            return _delete_orphans(conn, paths)

    def all_images(self) -> list[ImageRecord]:
        """Every image in at least one indexed folder (each listed once), newest file first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM images i
                   WHERE EXISTS (SELECT 1 FROM folder_images m WHERE m.image = i.path)
                   ORDER BY i.mtime_ns DESC, i.path"""
            ).fetchall()
        return [_to_record(r) for r in rows]

    def folder_images(self, folder: str) -> list[ImageRecord]:
        """Images in a folder, newest file first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT i.* FROM images i JOIN folder_images m ON m.image = i.path
                   WHERE m.folder = ? ORDER BY i.mtime_ns DESC, i.path""",
                (folder,),
            ).fetchall()
        return [_to_record(r) for r in rows]


def _delete_orphans(conn: sqlite3.Connection, paths: list[str]) -> list[ImageRecord]:
    orphans = []
    for path in paths:
        row = conn.execute(
            "SELECT * FROM images WHERE path = ? AND NOT EXISTS "
            "(SELECT 1 FROM folder_images WHERE image = images.path)",
            (path,),
        ).fetchone()
        if row:
            orphans.append(_to_record(row))
            conn.execute("DELETE FROM images WHERE path = ?", (path,))
    return orphans


def _to_row(rec: ImageRecord) -> dict:
    values = {f.name: getattr(rec, f.name) for f in fields(ImageRecord)}
    if rec.embedding is not None:
        vector = np.asarray(rec.embedding, dtype=np.float32)
        values["embedding"] = vector.tobytes()
        values["embed_dim"] = int(vector.size)
    else:
        values["embed_dim"] = None
    return values


def _to_record(row: sqlite3.Row) -> ImageRecord:
    values = {f.name: row[f.name] for f in fields(ImageRecord)}
    if values["embedding"] is not None:
        values["embedding"] = np.frombuffer(values["embedding"], dtype=np.float32)
    return ImageRecord(**values)
