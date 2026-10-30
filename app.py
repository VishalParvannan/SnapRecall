"""SnapRecall Streamlit interface. Run with: streamlit run app.py

Streamlit runs on this computer: the folder picker and "Open original" open
on this computer too. The app is meant to be used locally.

This file only wires the screens together; each area lives in the `ui` package.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SnapRecall", page_icon="🔎", layout="wide")

from ui.account import ensure_account_checked  # noqa: E402
from ui.components import empty_state  # noqa: E402
from ui.context import build_context  # noqa: E402
from ui.detail import show_detail  # noqa: E402
from ui.folders import choose_folder  # noqa: E402
from ui.jobs import run_pending_index, run_sync_jobs  # noqa: E402
from ui.library import render_library_status  # noqa: E402
from ui.search_view import render_search  # noqa: E402
from ui.sidebar import render_sidebar  # noqa: E402
from ui.styles import apply_branding  # noqa: E402

apply_branding()
ctx = build_context()
state = st.session_state
ensure_account_checked(ctx)

render_sidebar(ctx)

for problem in ctx.model_problems:
    st.warning(problem + " Searching by filename still works.", icon="⚠️")

run_pending_index(ctx)
run_sync_jobs(ctx)

if state.account_error and ctx.signed_in and not state.account.get("offline"):
    st.error(state.account_error, icon="⚠️")

if not state.folder:
    empty_state("🗂️", "Find any screenshot by describing it",
                "Choose a folder of screenshots to get started. They stay on this computer.")
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        if st.button("📂  Choose a folder…", type="primary", width="stretch", key="pick_main"):
            choose_folder(ctx)
            st.rerun()
    st.stop()

visible = render_library_status(ctx)

if state.selected:
    rec = ctx.storage.get(state.selected)
    if rec:
        show_detail(ctx, rec, visible)
        st.stop()
    state.selected = None

render_search(ctx, visible)
