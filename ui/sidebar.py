"""Sidebar: folder selection, indexing controls, account, and settings."""
from __future__ import annotations

import html

import streamlit as st

from indexer import INDIVIDUAL, forget_folder, remove_screenshots
from ui.account import account_panel
from ui.context import ALL_FOLDERS, AppContext
from ui.folders import add_screenshots_button, switch_folder
from ui.formatting import folder_label
from ui.login import GUEST_NOTICE, delete_account, sign_out
from ui.styles import section_label

state = st.session_state


def render_sidebar(ctx: AppContext) -> None:
    info, known_paths = ctx.info, ctx.known_paths
    individual = bool(info and info.path == INDIVIDUAL)
    scope = ("these screenshots" if individual else "this folder") if info else "all folders"
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
            where = (("Screenshots you chose one by one" if individual else info.path) if info
                     else f"Searching {len(known_paths)} folders")
            st.markdown(f'<div class="sr-path">{html.escape(where)}</div>', unsafe_allow_html=True)

        add_screenshots_button(ctx, "sidebar")
        if state.folder and st.button("Re-index " + scope, icon=":material/refresh:", width="stretch"):
            state.pending = [info.path] if info else list(known_paths)
        if state.picker_error:
            st.error(state.picker_error)

        st.divider()
        section_label("Preferences")
        if not ctx.is_guest:
            with st.expander("Cloud backup (optional)", icon=":material/cloud:"):
                account_panel(ctx)
        with st.expander("Settings", icon=":material/settings:"):
            st.caption("Index location")
            st.code(str(ctx.config.index_dir), language=None)
            st.caption("Set SNAPRECALL_HOME to change where accounts and libraries are kept.")
            def model_state(model) -> str:
                return "on" if model else ("starting…" if ctx.models_loading else "off")
            st.caption(f"Text recognition: {model_state(ctx.ocr)} · Visual search: {model_state(ctx.embedder)}")
            with st.popover("Delete all screenshots", width="stretch"):
                what = "all of these screenshots" if individual else f"every screenshot in {scope}"
                st.markdown(f"**Delete {what} from SnapRecall?** They disappear "
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
                                           help="They return the next time you re-index their folder. "
                                                "Screenshots you chose one by one return when you "
                                                "choose them again."):
                ctx.storage.restore_removed()
                st.rerun()
            if info and st.button("Remove these from the library" if individual else "Remove folder from index",
                                  width="stretch", help="Only SnapRecall's data is removed; the files stay."):
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
