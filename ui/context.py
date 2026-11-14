"""Per-run application context: backend, loaded models, and the current folder selection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from config import Config, load_config, snaprecall_home
from models import BackgroundModels
from storage import FolderInfo, Storage

ALL_FOLDERS = "__all__"  # sentinel: browse and search every indexed folder


def _library_config(index_dir: str) -> Config:
    from ui.login import get_home
    return load_config(index_dir, cache_dir=get_home()[0].cache_dir)


@st.cache_resource
def get_account_backend(index_dir: str):
    config = _library_config(index_dir)
    return config, Storage(config.db_path)


def get_backend():
    """The signed-in user's library. A guest library isn't cached between sessions: it is
    deleted when the session ends."""
    user = st.session_state.user
    if user["kind"] == "account":
        return get_account_backend(user["dir"])
    config = _library_config(user["dir"])
    return config, Storage(config.db_path)


@st.cache_resource(show_spinner=False)
def get_models() -> BackgroundModels:
    """One set of models for the whole app, loaded in the background. Called as early as the
    sign-in screen so loading overlaps with signing in. Model settings come from the environment,
    so they're the same for every library."""
    return BackgroundModels(load_config(snaprecall_home(), create=False))


@dataclass(frozen=True)
class AppContext:
    config: Config
    storage: Storage
    models: BackgroundModels
    folders: list[FolderInfo]
    known_paths: list[str]
    info: FolderInfo | None  # None for "All folders"

    # None while still loading (or when unavailable): search then uses text matches only.
    @property
    def ocr(self) -> Any:
        return self.models.ocr

    @property
    def embedder(self) -> Any:
        return self.models.embedder

    @property
    def text_model(self) -> Any:
        return self.models.text_model

    @property
    def models_loading(self) -> bool:
        return not self.models.done

    @property
    def model_problems(self) -> list[str]:
        return self.models.problems if self.models.done else []

    @property
    def signed_in(self) -> bool:
        """Signed in to the optional cloud backup account (not the local account)."""
        return st.session_state.account is not None

    @property
    def is_guest(self) -> bool:
        return st.session_state.user["kind"] == "guest"


def init_state() -> None:
    state = st.session_state
    state.setdefault("folder", None)
    state.setdefault("selected", None)
    state.setdefault("report", None)
    state.setdefault("pending", None)        # folders to index
    state.setdefault("pending_files", None)  # individually chosen screenshots to add
    state.setdefault("picker_error", None)
    state.setdefault("account", None)        # {"email", "file_count", "bytes", "offline"} when signed in
    state.setdefault("account_error", None)
    state.setdefault("jobs", [])             # queue of ("backup", folder) / ("download", None)
    state.setdefault("sync_report", None)    # list of (kind, report)


def build_context() -> AppContext:
    config, storage = get_backend()
    models = get_models()
    init_state()
    state = st.session_state

    folders = storage.list_folders()
    known_paths = [f.path for f in folders]
    if state.folder not in known_paths and not (state.folder == ALL_FOLDERS and len(known_paths) > 1):
        state.folder = known_paths[0] if known_paths else None
    info = next((f for f in folders if f.path == state.folder), None)
    return AppContext(config, storage, models, folders, known_paths, info)
