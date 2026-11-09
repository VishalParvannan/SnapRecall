"""Optional account: sign-in state, cloud-data actions, and the sidebar panel."""
from __future__ import annotations

import html

import streamlit as st

from sync import SyncClient, SyncError, clear_session, load_session, save_session
from ui.context import AppContext
from ui.formatting import fmt_bytes

state = st.session_state

UPLOAD_EXPLANATION = (
    "Uploads the original image files in this folder, with their file names and dates, to your "
    "account. Folder paths and the text and search data SnapRecall extracts stay on this computer."
)


def account_client(ctx: AppContext) -> SyncClient | None:
    session = load_session(ctx.config.session_path)
    if session is None:
        return None
    try:
        return SyncClient(session.server, session.token)
    except SyncError:
        return None


def refresh_account(ctx: AppContext) -> None:
    session = load_session(ctx.config.session_path)
    client = account_client(ctx)
    state.account = None
    if client is None:
        return
    try:
        state.account = {**client.me(), "offline": False}
        state.account_error = None
    except SyncError as exc:
        if exc.status == 401:
            clear_session(ctx.config.session_path)
            state.account_error = "Your session expired. Sign in again."
        else:
            state.account = {"email": session.email, "offline": True}
            state.account_error = str(exc)


def sign_in(ctx: AppContext, email: str, password: str, create: bool = False) -> None:
    try:
        client = SyncClient(ctx.config.sync_url)
        if create:
            client.register(email.strip(), password)
        save_session(ctx.config.session_path, client.login(email.strip(), password))
    except SyncError as exc:
        state.account_error = str(exc)
        return
    state.account_error = None
    refresh_account(ctx)


def sign_out(ctx: AppContext) -> None:
    client = account_client(ctx)
    if client:
        try:
            client.logout()
        except SyncError:
            pass  # the local session is removed either way
    clear_session(ctx.config.session_path)
    state.account = state.sync_report = None


def delete_cloud(ctx: AppContext, account_too: bool) -> None:
    client = account_client(ctx)
    if client is None:
        return
    try:
        if account_too:
            client.delete_account()
        else:
            client.delete_all_files()
    except SyncError as exc:
        state.account_error = str(exc)
        return
    if account_too:
        clear_session(ctx.config.session_path)
        for folder in ctx.known_paths:
            ctx.storage.set_backup(folder, False)
    state.sync_report = None
    refresh_account(ctx)


def ensure_account_checked(ctx: AppContext) -> None:
    if "account_checked" not in state:
        refresh_account(ctx)
        state.account_checked = True


def account_panel(ctx: AppContext) -> None:
    info = ctx.info
    if not ctx.signed_in:
        st.caption("SnapRecall works fully without an account. Sign in to back up screenshots "
                   "and download them on another device. Nothing is uploaded until you turn on "
                   "backup for a folder.")
        if state.account_error:
            st.warning(state.account_error)
        tab_in, tab_new = st.tabs(["Sign in", "Create account"])
        with tab_in, st.form("sign_in", border=False):
            email = st.text_input("Email", key="in_email")
            password = st.text_input("Password", type="password", key="in_password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                sign_in(ctx, email, password)
                st.rerun()
        with tab_new, st.form("sign_up", border=False):
            email = st.text_input("Email", key="new_email")
            password = st.text_input("Password", type="password", key="new_password",
                                     help="At least 8 characters.")
            again = st.text_input("Confirm password", type="password", key="new_again")
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                if password != again:
                    state.account_error = "The passwords don't match."
                else:
                    sign_in(ctx, email, password, create=True)
                st.rerun()
        st.caption(f"Sync server: {ctx.config.sync_url}")
        return

    acc = state.account
    email_html = html.escape(acc["email"]).replace("@", "&#64;")  # keep it from becoming a link
    st.markdown(f"Signed in as <b>{email_html}</b>", unsafe_allow_html=True)
    if acc.get("offline"):
        st.warning(state.account_error or "The sync server can't be reached right now.")
    else:
        st.caption(f"{acc['file_count']} screenshots backed up · {fmt_bytes(acc['bytes'])}")
    if info:
        enabled = st.toggle("Back up this folder", value=info.backup, help=UPLOAD_EXPLANATION)
        if enabled != info.backup:
            ctx.storage.set_backup(info.path, enabled)
            if enabled:
                state.jobs = [("backup", info.path)]
            st.rerun()
        if info.backup and st.button("Back up now", icon=":material/cloud_upload:", width="stretch"):
            state.jobs = [("backup", info.path)]
        st.caption(UPLOAD_EXPLANATION)
    else:
        st.caption("Select a single folder to choose whether it's backed up.")
    if st.button("Download my screenshots", icon=":material/download:", width="stretch"):
        state.jobs = [("download", None)]
    st.caption(f"Saves backed-up screenshots to {ctx.config.download_dir} and adds that folder here. "
               "Existing files are never overwritten.")
    if st.button("Sign out", width="stretch"):
        sign_out(ctx)
        st.rerun()
    with st.popover("Delete cloud data", width="stretch"):
        st.markdown("**Delete all backed-up screenshots** from your account. "
                    "Screenshots on this computer aren't affected.")
        if st.button("Delete backed-up screenshots", key="del_files"):
            delete_cloud(ctx, account_too=False)
            st.rerun()
        st.divider()
        st.markdown("**Delete your account** and everything stored in it. This can't be undone.")
        if st.button("Delete account", key="del_account"):
            delete_cloud(ctx, account_too=True)
            st.rerun()
