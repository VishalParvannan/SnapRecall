"""Folder selection actions and opening files on this computer."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

from folder_picker import FolderPickerError, pick_folder
from ui.context import ALL_FOLDERS, AppContext

state = st.session_state


def switch_folder(ctx: AppContext, folder: str | None) -> None:
    state.folder = folder
    state.selected = None
    state.report = None
    if folder and folder != ALL_FOLDERS:
        ctx.storage.mark_opened(folder)


def choose_folder(ctx: AppContext) -> None:
    state.picker_error = None
    try:
        chosen = pick_folder(ctx.info.path if ctx.info else None)
    except FolderPickerError as exc:
        state.picker_error = f"{exc} You can paste the folder path instead."
        return
    if chosen:
        state.pending = [chosen]


def open_original(path: str) -> None:
    if not Path(path).exists():
        raise FileNotFoundError("The file is no longer at this location.")
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens with the default viewer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
