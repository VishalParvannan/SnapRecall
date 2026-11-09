"""Folder discovery, change detection, and per-image processing.

Original screenshots are only ever opened for reading. The one exception is
`rename_screenshot`, which renames a file when the user asks; its contents are
never changed.

A scan is "complete" only if every directory and file could be read. Records
for files that seem to be missing are removed only after a complete scan,
so a temporarily unreadable folder never deletes valid index entries.
"""
from __future__ import annotations

import dataclasses
import hashlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from config import SUPPORTED_EXTENSIONS, THUMBNAIL_SIZE, Config
from labels import compute_labels, label_model
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


# Bump when the region layout changes so existing screenshots are re-analysed.
REGIONS_VERSION = "regions-1"
MIN_REGION = 64  # px; smaller regions carry too little detail to recognise
MAX_REGIONS = 16


def region_model(embedder: Embedder) -> str:
    return f"{embedder.name}+{REGIONS_VERSION}"


def image_regions(image: Image.Image) -> list[Image.Image]:
    """Square crops covering the screenshot at two scales.

    The visual model squeezes a whole screenshot into 224x224 px (and crops wide images to
    a centre square), so small details such as a profile picture or a logo get lost.
    Each crop is analysed on its own so search can match those details.
    """
    width, height = image.size
    boxes: list[tuple[int, int, int, int]] = []
    short = min(width, height)
    # Coarse: squares as tall as the short side, half-overlapping along the long side.
    # Fine: quarter-area squares in a grid, for full-screen captures.
    for side, step in ((short, short // 2), (short // 2, short // 2)):
        if side < MIN_REGION:
            continue
        xs = sorted({min(x, width - side) for x in range(0, width, step)})
        ys = sorted({min(y, height - side) for y in range(0, height, step)})
        boxes += [(x, y, x + side, y + side) for y in ys for x in xs]
    boxes = list(dict.fromkeys(boxes))
    if len(boxes) <= 1:
        return []  # a single square crop adds nothing over the whole image
    if len(boxes) > MAX_REGIONS:
        keep = np.linspace(0, len(boxes) - 1, MAX_REGIONS).round().astype(int)
        boxes = [boxes[i] for i in keep]
    return [image.crop(box) for box in boxes]


def needs_update(rec: ImageRecord, ocr: OcrEngine | None, embedder: Embedder | None,
                 regions: bool = False) -> bool:
    if rec.status != "ok":
        return True
    if ocr is not None and rec.ocr_model != ocr.name:
        return True
    if embedder is not None and rec.embed_model != embedder.name:
        return True
    if embedder is not None and regions and rec.region_model != region_model(embedder):
        return True
    if rec.label_model != label_model(embedder):
        return True
    return False


def plan_scan(folder: Path, storage: Storage, ocr: OcrEngine | None = None,
              embedder: Embedder | None = None, regions: bool = False) -> ScanPlan:
    """Compare files on disk with the index using (size, mtime) fingerprints."""
    paths, errors = discover_images(folder)
    removed = storage.removed_paths()  # screenshots the user removed from the library
    paths = [p for p in paths if str(p) not in removed]
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
        elif needs_update(rec, ocr, embedder, regions):
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


def _open_upright(data: bytes) -> Image.Image:
    """Decode an image and apply its EXIF orientation, so text and content are upright."""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:  # malformed orientation data: use the pixels as stored
            pass
        return img.convert("RGB")


def process_image(path: Path, config: Config, ocr: OcrEngine | None = None,
                  embedder: Embedder | None = None,
                  previous: ImageRecord | None = None) -> ImageRecord:
    """Build a fresh record for one image. Raises FileNotFoundError if it vanished.

    When the file is unchanged, results that are still valid are kept and only stale ones are
    redone; if redoing a step fails, its earlier successful result is kept (and the image is
    marked for retry) rather than being thrown away.
    """
    st = path.stat()
    rec = ImageRecord(path=str(path), size=st.st_size, mtime_ns=st.st_mtime_ns)
    unchanged = previous is not None and (previous.size, previous.mtime_ns) == (rec.size, rec.mtime_ns)
    if unchanged:
        rec = dataclasses.replace(previous, path=rec.path, status="ok", error=None)

    thumb_path = _thumbnail_path(config, path)
    try:
        data = path.read_bytes()
        image = _open_upright(data)
        rec.sha256 = hashlib.sha256(data).hexdigest()  # the image's identity, independent of its path
        rec.width, rec.height = image.size
        thumb = image.copy()
        thumb.thumbnail(THUMBNAIL_SIZE)
        thumb.save(thumb_path, "JPEG", quality=85)
        rec.thumbnail = str(thumb_path)
    except FileNotFoundError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        reason = f"Could not open image ({exc.__class__.__name__})"
        if unchanged and previous.status != "error":
            # Same file as before (perhaps locked right now): keep what was found earlier.
            rec.status, rec.error = "partial", f"{reason}; showing earlier results"
            return rec
        remove_thumbnail(config, thumb_path)
        return ImageRecord(path=rec.path, size=rec.size, mtime_ns=rec.mtime_ns, status="error", error=reason)

    problems = []
    if ocr is not None and rec.ocr_model != ocr.name:
        try:
            result = ocr.extract(image)
            rec.ocr_text, rec.ocr_confidence, rec.ocr_model = result.text, result.confidence, ocr.name
        except Exception:
            problems.append("text recognition failed")
    if embedder is not None and rec.embed_model != embedder.name:
        try:
            rec.embedding, rec.embed_model = embedder.embed_image(image), embedder.name
        except Exception:
            problems.append("visual analysis failed")
    embedding_current = embedder is not None and rec.embed_model == embedder.name
    if embedding_current and config.enable_regions and rec.region_model != region_model(embedder):
        try:
            crops = image_regions(image)
            rec.region_embeddings = embedder.embed_images(crops) if crops else None
            rec.region_model = region_model(embedder)
        except Exception:
            problems.append("detail analysis failed")
    # Labels are cheap (they reuse the text and embeddings), so they are recomputed whenever the
    # image is processed. With visual search on, they wait for a current embedding.
    if embedder is None or embedding_current:
        try:
            labels = compute_labels(rec.ocr_text, embedder, rec.embedding if embedder is not None else None,
                                    cache_dir=config.cache_dir or config.index_dir)
            rec.source_app, rec.source_confidence = labels.source_app, labels.source_confidence
            rec.source_evidence, rec.tags = labels.source_evidence, labels.tags
            rec.label_model = label_model(embedder)
        except Exception:
            problems.append("labelling failed")
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

    plan = plan_scan(folder, storage, ocr, embedder, config.enable_regions)
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


class RenameError(Exception):
    """A screenshot couldn't be renamed; the message is safe to show to users."""


_INVALID_NAME_CHARS = set('<>:"/\\|?*')


def rename_screenshot(path: str, new_stem: str, storage: Storage, config: Config) -> str:
    """Rename a screenshot file on disk (keeping its extension) and update the index.

    Never overwrites another file, and puts the original name back if the index can't be updated.
    Returns the new path.
    """
    old = Path(path)
    stem = new_stem.strip()
    if stem.lower().endswith(old.suffix.lower()):
        stem = stem[:-len(old.suffix)].rstrip()
    if not stem or stem in {".", ".."}:
        raise RenameError("Enter a name.")
    if any(c in _INVALID_NAME_CHARS or ord(c) < 32 for c in stem) or stem.endswith("."):
        raise RenameError('Names can\'t contain < > : " / \\ | ? * or end with a period.')
    new = old.with_name(stem + old.suffix)
    if new == old:
        return path
    if not old.exists():
        raise RenameError("The original file is missing. It may have been moved or deleted.")
    # On Windows a case-only change ("shot" -> "Shot") points at the same file, which is fine.
    if new.exists() and not os.path.samefile(new, old):
        raise RenameError(f"A file named {new.name} already exists in this folder.")
    try:
        old.rename(new)
    except OSError as exc:
        raise RenameError(f"Could not rename the file: {_describe(exc)}.") from exc

    rec = storage.get(path)
    thumbnail = rec.thumbnail if rec else None
    new_thumb = _thumbnail_path(config, new)
    if thumbnail and Path(thumbnail).exists():
        try:
            os.replace(thumbnail, new_thumb)
            thumbnail = str(new_thumb)
        except OSError:
            pass  # keep the old thumbnail file; it still shows the right image
    try:
        storage.rename_image(path, str(new), thumbnail)
    except Exception as exc:
        new.rename(old)  # undo so the file and the index agree
        if thumbnail == str(new_thumb) and rec and rec.thumbnail:
            os.replace(new_thumb, rec.thumbnail)
        raise RenameError("The file couldn't be renamed in the library, so its original name was kept.") from exc
    return str(new)


def remove_screenshots(paths: list[str], storage: Storage, config: Config) -> int:
    """Remove screenshots from the library (screenshots on disk are untouched)."""
    removed = storage.remove_images(paths)
    for rec in removed:
        remove_thumbnail(config, rec.thumbnail)
    return len(removed)
