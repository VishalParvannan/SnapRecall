"""Long-running work started from the interface: indexing and backup/download."""
from __future__ import annotations

import html

import streamlit as st

from indexer import INDIVIDUAL, index_files, index_folder
from sync import SyncError, backup_folder, clear_session, download_all
from ui.account import account_client, refresh_account
from ui.context import AppContext
from ui.folders import switch_folder
from ui.formatting import folder_label

state = st.session_state


def run_pending_index(ctx: AppContext) -> None:
    if not state.pending and not state.pending_files:
        return
    # Folders are indexed by path; chosen screenshots go into the INDIVIDUAL collection.
    targets = list(state.pending or []) + ([INDIVIDUAL] if state.pending_files else [])
    files, state.pending, state.pending_files = list(state.pending_files or []), None, None
    with st.container(border=True):
        heading = st.empty()
        bar = st.progress(0.0, text="Scanning folder…")

    def progress(i: int, total: int, name: str) -> None:
        bar.progress(i / total, text=f"{i} of {total} · {name}")

    # Indexing without the models would store screenshots with no text or visual data, so wait
    # for them here (they're usually ready by now: loading starts on the sign-in screen).
    if ctx.models_loading:
        heading.markdown("**Getting text recognition and visual search ready…**")
        bar.progress(0.0, text="This takes a few seconds after SnapRecall starts.")
        ctx.models.wait()

    reports = []
    for n, target in enumerate(targets, start=1):
        suffix = f" ({n} of {len(targets)})" if len(targets) > 1 else ""
        if target == INDIVIDUAL and files:
            count = f"{len(files)} screenshot{'s' if len(files) != 1 else ''}"
            heading.markdown(f"**Adding {count}{suffix}**")
            bar.progress(0.0, text="Checking files…")
            reports.append(index_files(files, ctx.storage, ctx.config, ctx.ocr, ctx.embedder, progress))
            continue
        heading.markdown(f"**Indexing {html.escape(folder_label(target))}{suffix}**")
        bar.progress(0.0, text="Scanning folder…")
        try:
            reports.append(index_folder(target, ctx.storage, ctx.config, ctx.ocr, ctx.embedder, progress))
        except NotADirectoryError as exc:
            st.error(str(exc))
    if reports:
        if len(targets) == 1:
            switch_folder(ctx, reports[0].folder)
        state.report = reports
        backup_on = {f.path for f in ctx.storage.list_folders() if f.backup}
        if ctx.signed_in:
            state.jobs = [("backup", r.folder) for r in reports if r.folder in backup_on]
        st.rerun()
    bar.empty()


def run_sync_jobs(ctx: AppContext) -> None:
    if not state.jobs:
        return
    jobs, state.jobs = list(state.jobs), []
    client = account_client(ctx)
    if client is None:
        st.warning("Sign in to your account first.", icon=":material/warning:")
        return
    with st.container(border=True):
        heading = st.empty()
        bar = st.progress(0.0, text="Contacting the sync server…")

    def sync_progress(i: int, total: int, name: str) -> None:
        bar.progress(i / total, text=f"{i} of {total} · {name}")

    state.sync_report = []
    try:
        for kind, job_folder in jobs:
            heading.markdown(f"**Backing up {html.escape(folder_label(job_folder))}**" if kind == "backup"
                             else "**Downloading your screenshots**")
            if kind == "backup":
                state.sync_report.append(
                    ("backup", backup_folder(job_folder, ctx.storage, client, sync_progress)))
            else:
                result = download_all(client, ctx.config.download_dir, sync_progress)
                state.sync_report.append(("download", result))
                state.pending = [result.folder]  # index the downloaded screenshots locally
    except SyncError as exc:
        if exc.status == 401:
            clear_session(ctx.config.session_path)
            state.account_error = "Your session expired. Sign in again."
        else:
            state.account_error = str(exc)
    except OSError as exc:
        state.sync_report = None
        state.account_error = f"Couldn't save the downloaded screenshots ({exc.__class__.__name__})."
    refresh_account(ctx)
    st.rerun()
