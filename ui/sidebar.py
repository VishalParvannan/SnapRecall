"""Sidebar: folder selection, indexing controls, account, and settings."""
from __future__ import annotations

import streamlit as st

from indexer import forget_folder, remove_screenshots
from ui.account import account_panel
from ui.context import ALL_FOLDERS, AppContext
from ui.folders import choose_folder, switch_folder
from ui.formatting import folder_label

state = st.session_state


def render_sidebar(ctx: AppContext) -> None:
    info, known_paths = ctx.info, ctx.known_paths
    with st.sidebar:
        st.markdown("#### Folders")
        if ctx.folders:
            options = ([ALL_FOLDERS] if len(known_paths) > 1 else []) + known_paths
            choice = st.selectbox(
                "Current folder", options, index=options.index(state.folder),
                format_func=folder_label, label_visibility="collapsed",
            )
            if choice != state.folder:
                switch_folder(ctx, choice)
                st.rerun()
            st.caption(info.path if info else f"Searching {len(known_paths)} folders")

        if st.button("📂  Choose a folder…", type="primary", width="stretch", key="pick_sidebar"):
            choose_folder(ctx)
        if state.folder and st.button("↻  Re-index " + ("this folder" if info else "all folders"),
                                      width="stretch"):
            state.pending = [info.path] if info else list(known_paths)
        if state.picker_error:
            st.error(state.picker_error)

        with st.expander("Paste a folder path instead"):
            with st.form("add_folder", clear_on_submit=True, border=False):
                typed = st.text_input("Folder path", placeholder=r"C:\Users\you\Pictures\Screenshots",
                                      label_visibility="collapsed")
                if st.form_submit_button("Index folder", width="stretch"):
                    if typed.strip():
                        state.pending = [typed.strip().strip('"')]
                    else:
                        st.warning("Enter a folder path first.")

        st.divider()
        with st.expander("Account (optional)"):
            account_panel(ctx)
        with st.expander("Settings"):
            st.caption("Index location")
            st.code(str(ctx.config.index_dir), language=None)
            st.caption("Set SNAPRECALL_HOME to change it.")
            st.caption(f"Text recognition: {'on' if ctx.ocr else 'off'} · "
                       f"Visual search: {'on' if ctx.embedder else 'off'}")
            scope = "this folder" if info else "all folders"
            with st.popover("Delete all screenshots", width="stretch"):
                st.markdown(f"**Delete every screenshot in {scope} from SnapRecall?** They disappear "
                            "from your library and search. The image files stay on your computer, "
                            "and re-indexing won't bring them back. Backed-up copies in your account "
                            "aren't affected.")
                if st.button("Delete all screenshots", key="del_all", type="primary"):
                    shots = ctx.storage.folder_images(info.path) if info else ctx.storage.all_images()
                    remove_screenshots([r.path for r in shots], ctx.storage, ctx.config)
                    state.selected = None
                    st.rerun()
            removed_count = len(ctx.storage.removed_paths())
            if removed_count and st.button(f"Restore {removed_count} deleted screenshots",
                                           width="stretch",
                                           help="They return the next time you re-index their folder."):
                ctx.storage.restore_removed()
                st.rerun()
            if info and st.button("Remove folder from index", width="stretch"):
                forget_folder(info.path, ctx.storage, ctx.config)
                switch_folder(ctx, None)
                st.rerun()
