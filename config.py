"""Configuration: index location, supported formats, and model choices.

Every setting can be overridden with an environment variable so model
choices and index paths never require changes to core logic:

    SNAPRECALL_HOME             index directory (default ~/.snaprecall)
    SNAPRECALL_OCR              "0" disables text recognition
    SNAPRECALL_OCR_LANGS        comma-separated EasyOCR languages (default "en")
    SNAPRECALL_VISUAL           "0" disables visual search
    SNAPRECALL_REGIONS          "0" skips analysing parts of each screenshot (faster indexing)
    SNAPRECALL_CLIP_MODEL       OpenCLIP architecture (default ViT-B-32)
    SNAPRECALL_CLIP_PRETRAINED  OpenCLIP weights (default laion2b_s34b_b79k)
    SNAPRECALL_VISUAL_THRESHOLD similarity treated as a strong visual match
    SNAPRECALL_SYNC_URL         optional account server (default http://127.0.0.1:8765)
    SNAPRECALL_DOWNLOAD_DIR     where "Download my screenshots" saves files
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
THUMBNAIL_SIZE = (320, 320)


@dataclass(frozen=True)
class Config:
    index_dir: Path
    enable_ocr: bool = True
    ocr_languages: tuple[str, ...] = ("en",)
    enable_visual: bool = True
    enable_regions: bool = True
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"
    visual_threshold: float = 0.29
    sync_url: str = "http://127.0.0.1:8765"
    download_dir: Path = Path.home() / "Pictures" / "SnapRecall Backup"

    @property
    def db_path(self) -> Path:
        return self.index_dir / "index.db"

    @property
    def thumbnail_dir(self) -> Path:
        return self.index_dir / "thumbnails"

    @property
    def session_path(self) -> Path:
        """Saved sign-in for the optional account (removed on sign-out)."""
        return self.index_dir / "account.json"


def _flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() not in {"0", "false", "no", "off"}


def load_config(index_dir: str | Path | None = None, **overrides) -> Config:
    if index_dir is None:
        index_dir = os.environ.get("SNAPRECALL_HOME") or Path.home() / ".snaprecall"
    path = Path(index_dir).expanduser().resolve()
    (path / "thumbnails").mkdir(parents=True, exist_ok=True)
    env = os.environ
    settings = dict(
        enable_ocr=_flag("SNAPRECALL_OCR"),
        ocr_languages=tuple(
            lang.strip() for lang in env.get("SNAPRECALL_OCR_LANGS", "en").split(",") if lang.strip()
        ),
        enable_visual=_flag("SNAPRECALL_VISUAL"),
        enable_regions=_flag("SNAPRECALL_REGIONS"),
        clip_model=env.get("SNAPRECALL_CLIP_MODEL", Config.clip_model),
        clip_pretrained=env.get("SNAPRECALL_CLIP_PRETRAINED", Config.clip_pretrained),
        visual_threshold=float(env.get("SNAPRECALL_VISUAL_THRESHOLD", Config.visual_threshold)),
        sync_url=env.get("SNAPRECALL_SYNC_URL", Config.sync_url),
        download_dir=Path(env.get("SNAPRECALL_DOWNLOAD_DIR", Config.download_dir)).expanduser(),
    )
    settings.update(overrides)
    return Config(index_dir=path, **settings)
