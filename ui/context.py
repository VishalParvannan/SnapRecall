"""Per-run application context: backend, loaded models, and the current folder selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from config import Config, load_config
from models import ModelLoadError, load_embedder, load_ocr
from storage import FolderInfo, Storage

ALL_FOLDERS = "__all__"  # sentinel: browse and search every indexed folder


@st.cache_resource
def get_backend():
    config = load_config()
    return config, Storage(config.db_path)


@st.cache_resource(show_spinner="Loading search models (the first run may download them)…")
def get_models(_config):
    ocr = embedder = None
    problems = []
    try:
        ocr = load_ocr(_config)
    except ModelLoadError as exc:
        problems.append(str(exc))
    try:
        embedder = load_embedder(_config)
    except ModelLoadError as exc:
        problems.append(str(exc))
    return ocr, embedder, problems


@dataclass(frozen=True)
class AppContext:
    config: Config
    storage: Storage
    ocr: Any
    embedder: Any
    model_problems: list[str]
    folders: list[FolderInfo]
    known_paths: list[str]
    info: FolderInfo | None  # None for "All folders"

    @property
    def signed_in(self) -> bool:
        return st.session_state.account is not None


def init_state() -> None:
    state = st.session_state
    state.setdefault("folder", None)
    state.setdefault("selected", None)
    state.setdefault("report", None)
    state.setdefault("pending", None)
    state.setdefault("picker_error", None)
    state.setdefault("account", None)        # {"email", "file_count", "bytes", "offline"} when signed in
    state.setdefault("account_error", None)
    state.setdefault("jobs", [])             # queue of ("backup", folder) / ("download", None)
    state.setdefault("sync_report", None)    # list of (kind, report)


def build_context() -> AppContext:
    config, storage = get_backend()
    ocr, embedder, model_problems = get_models(config)
    init_state()
    state = st.session_state

    folders = storage.list_folders()
    known_paths = [f.path for f in folders]
    if state.folder not in known_paths and not (state.folder == ALL_FOLDERS and len(known_paths) > 1):
        state.folder = known_paths[0] if known_paths else None
    info = next((f for f in folders if f.path == state.folder), None)
    return AppContext(config, storage, ocr, embedder, model_problems, folders, known_paths, info)
