"""Folder and screenshot selection actions, and opening files on this computer."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

from folder_picker import FolderPickerError, pick_screenshots
from indexer import INDIVIDUAL
from ui.context import ALL_FOLDERS, AppContext

state = st.session_state


def switch_folder(ctx: AppContext, folder: str | None) -> None:
    state.folder = folder
    state.selected = None
    state.report = None
    if folder and folder != ALL_FOLDERS:
        ctx.storage.mark_opened(folder)


def _start_dir(ctx: AppContext) -> str | None:
    return ctx.info.path if ctx.info and ctx.info.path != INDIVIDUAL else None


def choose_screenshots(ctx: AppContext) -> None:
    """Open the picker. Chosen folders are indexed as folders (with subfolders); chosen
    files go to the individually chosen screenshots. Both can be picked at once."""
    state.picker_error = None
    try:
        chosen = pick_screenshots(_start_dir(ctx))
    except FolderPickerError as exc:
        state.picker_error = f"{exc} Please try again."
        return
    folders = [p for p in chosen if Path(p).is_dir()]
    files = [p for p in chosen if not Path(p).is_dir()]
    if folders:
        state.pending = folders
    if files:
        state.pending_files = files


def add_screenshots_button(ctx: AppContext, key: str) -> None:
    """The one "Add screenshots…" button: opens a window to pick folders, screenshots, or both."""
    if st.button("Add screenshots…", icon=":material/add_photo_alternate:", type="primary",
                 width="stretch", key=f"{key}_add",
                 help="Pick folders, individual screenshots, or both (hold Ctrl or Shift to pick several). "
                      "Folders include their subfolders. Files stay where they are on your computer."):
        choose_screenshots(ctx)
        st.rerun()


def open_original(path: str) -> None:
    if not Path(path).exists():
        raise FileNotFoundError("The file is no longer at this location.")
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens with the default viewer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
