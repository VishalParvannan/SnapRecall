"""Sidebar: folder selection, indexing controls, account, and settings."""
from __future__ import annotations

import html

import streamlit as st

from indexer import forget_folder, remove_screenshots
from ui.account import account_panel
from ui.context import ALL_FOLDERS, AppContext
from ui.folders import choose_folder, switch_folder
from ui.formatting import folder_label
from ui.login import GUEST_NOTICE, delete_account, sign_out
from ui.styles import section_label

state = st.session_state


def render_sidebar(ctx: AppContext) -> None:
    info, known_paths = ctx.info, ctx.known_paths
    with st.sidebar:
        user = state.user
        if ctx.is_guest:
            st.markdown('<div class="sr-user"><div class="sr-avatar guest">G</div><div>'
                        '<div class="sr-user-name">Guest<span class="sr-badge">Temporary</span></div>'
                        '<div class="sr-user-kind">Deleted when this session ends</div></div></div>',
                        unsafe_allow_html=True)
            st.caption(GUEST_NOTICE)
            if st.button("End guest session", icon=":material/logout:", width="stretch",
                         help="Deletes this temporary library now and returns to sign-in."):
                sign_out()
        else:
            name = html.escape(user["username"])
            st.markdown(f'<div class="sr-user"><div class="sr-avatar">{name[:1].upper()}</div><div '
                        f'style="min-width:0"><div class="sr-user-name">{name}</div>'
                        '<div class="sr-user-kind">Local account</div></div></div>', unsafe_allow_html=True)
            if st.button("Sign out", icon=":material/logout:", width="stretch", key="local_sign_out"):
                sign_out()
        st.divider()
        section_label("Library")
        if ctx.folders:
            options = ([ALL_FOLDERS] if len(known_paths) > 1 else []) + known_paths
            choice = st.selectbox(
                "Current folder", options, index=options.index(state.folder),
                format_func=folder_label, label_visibility="collapsed",
            )
            if choice != state.folder:
                switch_folder(ctx, choice)
                st.rerun()
            where = info.path if info else f"Searching {len(known_paths)} folders"
            st.markdown(f'<div class="sr-path">{html.escape(where)}</div>', unsafe_allow_html=True)

        if st.button("Choose a folder…", icon=":material/create_new_folder:", type="primary", width="stretch",
                     key="pick_sidebar"):
            choose_folder(ctx)
        if state.folder and st.button("Re-index " + ("this folder" if info else "all folders"),
                                      icon=":material/refresh:", width="stretch"):
            state.pending = [info.path] if info else list(known_paths)
        if state.picker_error:
            st.error(state.picker_error)

        with st.expander("Paste a folder path instead", icon=":material/edit:"):
            with st.form("add_folder", clear_on_submit=True, border=False):
                typed = st.text_input("Folder path", placeholder=r"C:\Users\you\Pictures\Screenshots",
                                      label_visibility="collapsed")
                if st.form_submit_button("Index folder", width="stretch"):
                    if typed.strip():
                        state.pending = [typed.strip().strip('"')]
                    else:
                        st.warning("Enter a folder path first.")

        st.divider()
        section_label("Preferences")
        if not ctx.is_guest:
            with st.expander("Cloud backup (optional)", icon=":material/cloud:"):
                account_panel(ctx)
        with st.expander("Settings", icon=":material/settings:"):
            st.caption("Index location")
            st.code(str(ctx.config.index_dir), language=None)
            st.caption("Set SNAPRECALL_HOME to change where accounts and libraries are kept.")
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
            if not ctx.is_guest:
                with st.popover("Delete this account", width="stretch"):
                    st.markdown("**Delete your account and its library** (search data and thumbnails) "
                                "from this computer. Your screenshot files stay where they are. "
                                "Cloud backups aren't affected; delete them under Cloud backup first.")
                    with st.form("delete_local_account", border=False):
                        pw = st.text_input("Password", type="password")
                        if st.form_submit_button("Delete account", type="primary"):
                            delete_account(pw)
