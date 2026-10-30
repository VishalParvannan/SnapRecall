"""Small display-formatting helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ui.context import ALL_FOLDERS


def fmt_time(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1e9).strftime("%b %d, %Y · %H:%M")


def fmt_scan_time(utc_text: str) -> str:
    """SQLite CURRENT_TIMESTAMP (UTC) -> local, human-readable time."""
    try:
        moment = datetime.fromisoformat(utc_text).replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        return utc_text
    return moment.strftime("%b %d, %Y at %H:%M")


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def folder_label(path: str) -> str:
    if path == ALL_FOLDERS:
        return "All folders"
    return Path(path).name or path
