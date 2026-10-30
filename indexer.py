"""Folder discovery, change detection, and per-image processing.

Original screenshots are only ever opened for reading.

A scan is "complete" only if every directory and file could be read. Records
for files that seem to be missing are removed only after a complete scan,
so a temporarily unreadable folder never deletes valid index entries.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, UnidentifiedImageError

from config import SUPPORTED_EXTENSIONS, THUMBNAIL_SIZE, Config
from models import Embedder, OcrEngine
from storage import ImageRecord, Storage

ProgressFn = Callable[[int, int, str], None]


@dataclass
class ScanPlan:
    new: list[Path] = field(default_factory=list)
    changed: list[Path] = field(default_factory=list)
    retry: list[Path] = field(default_factory=list)  # failed before, or model changed
    unchanged: list[Path] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    previous: dict[str, ImageRecord] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.errors

    @property
    def to_process(self) -> list[Path]:
        return self.new + self.changed + self.retry


@dataclass
class IndexReport:
    folder: str
    plan: ScanPlan
    processed: int = 0
    removed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def _describe(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "Permission denied"
    if isinstance(exc, FileNotFoundError):
        return "No longer exists"
    return f"Could not be read ({exc.__class__.__name__})"


def discover_images(folder: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    """Find supported images below `folder`. Returns (paths, unreadable locations)."""
    errors: list[tuple[str, str]] = []
    found: list[Path] = []
    for root, _dirs, files in os.walk(folder, onerror=lambda e: errors.append((e.filename, _describe(e)))):
        for name in files:
            if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                found.append(Path(root, name).resolve())
    return sorted(found), errors


def needs_update(rec: ImageRecord, ocr: OcrEngine | None, embedder: Embedder | None) -> bool:
    if rec.status != "ok":
        return True
    if ocr is not None and rec.ocr_model != ocr.name:
        return True
    if embedder is not None and rec.embed_model != embedder.name:
        return True
    return False


def plan_scan(folder: Path, storage: Storage, ocr: OcrEngine | None = None,
              embedder: Embedder | None = None) -> ScanPlan:
    """Compare files on disk with the index using (size, mtime) fingerprints."""
    paths, errors = discover_images(folder)
    plan = ScanPlan(errors=errors)
    plan.previous = storage.get_many([str(p) for p in paths])
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        seen.add(key)
        try:
            st = path.stat()
        except OSError as exc:
            plan.errors.append((key, _describe(exc)))
            continue
        rec = plan.previous.get(key)
        if rec is None:
            plan.new.append(path)
        elif (rec.size, rec.mtime_ns) != (st.st_size, st.st_mtime_ns):
            plan.changed.append(path)
        elif needs_update(rec, ocr, embedder):
            plan.retry.append(path)
        else:
            plan.unchanged.append(path)
    if plan.complete:
        plan.missing = sorted(storage.member_paths(str(folder)) - seen)
    return plan


def _thumbnail_path(config: Config, path: Path) -> Path:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    return config.thumbnail_dir / f"{digest}.jpg"


def remove_thumbnail(config: Config, thumbnail: str | Path | None) -> None:
    """Delete a thumbnail, but only if it lives inside the managed thumbnail folder."""
    if not thumbnail:
        return
    target = Path(thumbnail).resolve()
    if not target.is_relative_to(config.thumbnail_dir.resolve()):
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


def process_image(path: Path, config: Config, ocr: OcrEngine | None = None,
                  embedder: Embedder | None = None,
                  previous: ImageRecord | None = None) -> ImageRecord:
    """Build a fresh record for one image. Raises FileNotFoundError if it vanished."""
    st = path.stat()
    rec = ImageRecord(path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns)
    if previous and (previous.size, previous.mtime_ns) == (rec.size, rec.mtime_ns):
        # Unchanged file: keep results that are still valid, redo only what's needed.
        rec.ocr_text, rec.ocr_model = previous.ocr_text, previous.ocr_model
        rec.embedding, rec.embed_model = previous.embedding, previous.embed_model
        rec.sha256 = previous.sha256

    thumb_path = _thumbnail_path(config, path)
    try:
        with Image.open(path) as img:
            img.load()
            image = img.convert("RGB")
        rec.width, rec.height = image.size
        thumb = image.copy()
        thumb.thumbnail(THUMBNAIL_SIZE)
        thumb.save(thumb_path, "JPEG", quality=85)
        rec.thumbnail = str(thumb_path)
    except FileNotFoundError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        remove_thumbnail(config, thumb_path)
        return ImageRecord(path=rec.path, size=rec.size, mtime_ns=rec.mtime_ns, status="error",
                           error=f"Could not open image ({exc.__class__.__name__})")

    problems = []
    if ocr is not None and rec.ocr_model != ocr.name:
        try:
            rec.ocr_text, rec.ocr_model = ocr.extract(image), ocr.name
        except Exception:
            rec.ocr_text = rec.ocr_model = None
            problems.append("text recognition failed")
    if embedder is not None and rec.embed_model != embedder.name:
        try:
            rec.embedding, rec.embed_model = embedder.embed_image(image), embedder.name
        except Exception:
            rec.embedding = rec.embed_model = None
            problems.append("visual analysis failed")
    if problems:
        rec.status = "partial"
        rec.error = "; ".join(problems).capitalize()
    return rec


def index_folder(folder: str | Path, storage: Storage, config: Config,
                 ocr: OcrEngine | None = None, embedder: Embedder | None = None,
                 progress: ProgressFn | None = None) -> IndexReport:
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Folder not found: {folder}")
    key = str(folder)
    storage.save_folder(key)

    plan = plan_scan(folder, storage, ocr, embedder)
    report = IndexReport(folder=key, plan=plan)
    storage.add_members(key, [str(p) for p in plan.unchanged])

    # Each image is saved as soon as it is processed, so an interrupted run
    # keeps its progress and the next scan picks up the rest.
    todo = plan.to_process
    for i, path in enumerate(todo, start=1):
        if progress:
            progress(i, len(todo), path.name)
        try:
            rec = process_image(path, config, ocr, embedder, plan.previous.get(str(path)))
        except OSError as exc:
            report.failed.append((str(path), _describe(exc)))
            continue
        storage.upsert_image(rec)
        storage.add_members(key, [rec.path])
        if rec.status == "ok":
            report.processed += 1
        else:
            report.failed.append((rec.path, rec.error or "Unknown error"))

    if plan.complete and plan.missing:
        for orphan in storage.remove_members(key, plan.missing):
            remove_thumbnail(config, orphan.thumbnail)
        report.removed = len(plan.missing)
    storage.save_folder(key, complete=plan.complete)
    return report


def forget_folder(folder: str, storage: Storage, config: Config) -> None:
    """Remove a folder from the index (screenshots on disk are untouched)."""
    for orphan in storage.remove_folder(folder):
        remove_thumbnail(config, orphan.thumbnail)
