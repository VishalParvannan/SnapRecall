"""Sign-in screen shown before the library: a local account, or a temporary guest library."""
from __future__ import annotations

import atexit
from pathlib import Path

import streamlit as st
from streamlit import runtime
from streamlit.runtime.scriptrunner import get_script_run_ctx

from accounts import MIN_PASSWORD, AccountError, GuestLibraries, LocalAccounts
from config import snaprecall_home
from ui.styles import icon_svg

state = st.session_state

_FEATURES = [
    ("search", "Search by memory", "Type words that were on screen, or describe what it looked like."),
    ("lock", "Stays on this computer", "Screenshots are indexed locally. Nothing is uploaded unless you "
                                       "turn on backup for a folder."),
    ("copy", "Copy the original", "Put the full-resolution image on your clipboard and paste it anywhere."),
]
_HERO = (
    '<div class="sr-hero">'
    '<svg width="44" height="44" viewBox="0 0 40 40" aria-hidden="true"><defs><linearGradient id="srg" x1="0" '
    'y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#6d28d9"/>'
    '</linearGradient></defs><rect x="4" y="4" width="32" height="32" rx="9" fill="url(#srg)"/><rect x="11" '
    'y="11" width="14" height="11" rx="2.5" fill="none" stroke="#fff" stroke-width="2.2"/><circle cx="23.5" '
    'cy="23.5" r="5" fill="#6d28d9" stroke="#fff" stroke-width="2.2"/><path d="M27.2 27.2 L30.6 30.6" '
    'stroke="#fff" stroke-width="2.4" stroke-linecap="round"/></svg>'
    '<h1>Find any screenshot by <span class="sr-grad">describing it.</span></h1>'
    "<p>SnapRecall reads the text in your screenshots and compares what they show with your description, "
    "so you can look for one the way you remember it.</p>"
    '<ul class="sr-features">'
    + "".join(f'<li><div class="ic">{icon_svg(icon, 18)}</div><div><b>{title}</b><span>{text}</span></div></li>'
              for icon, title, text in _FEATURES)
    + "</ul></div>"
)

GUEST_NOTICE = ("Guest libraries are temporary. The search data SnapRecall builds (recognized text, "
                "thumbnails, visual search data) is deleted when you close or refresh this tab, "
                "sign out, or stop the app. Your screenshot files are never deleted.")


@st.cache_resource
def get_home() -> tuple[LocalAccounts, GuestLibraries]:
    home = snaprecall_home()
    accounts, guests = LocalAccounts(home), GuestLibraries(home)
    accounts.cache_dir.mkdir(exist_ok=True)
    atexit.register(guests.delete_all_mine)
    return accounts, guests


def _session_id() -> str:
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else "local"


def _is_active(session_id: str) -> bool:
    if not runtime.exists():
        return True  # outside a Streamlit server: never delete anything we can't check
    return runtime.get_instance().is_active_session(session_id)


def sweep_guest_libraries() -> None:
    """Delete guest libraries whose browser session has ended. Runs on every page run, since
    Streamlit has no reliable "tab closed" event."""
    get_home()[1].sweep(_is_active)


def _reset_session() -> None:
    for key in list(state.keys()):
        del state[key]


def _enter(user: dict) -> None:
    _reset_session()
    state.user = user
    st.rerun()


def sign_out() -> None:
    user = state.get("user")
    if user and user["kind"] == "guest":
        get_home()[1].delete(user_dir())
    _reset_session()
    st.rerun()


def delete_account(password: str) -> None:
    from accounts import User
    from ui.context import get_account_backend
    accounts = get_home()[0]
    user = state.user
    try:
        accounts.delete(User(user["id"], user["username"]), password)
    except AccountError as exc:
        st.error(str(exc))
        return
    get_account_backend.clear()
    _reset_session()
    state.login_notice = "Your account and its library were deleted."
    st.rerun()


def user_dir() -> Path:
    return Path(state.user["dir"])


def require_login() -> None:
    """Show the sign-in screen and stop the page until the visitor signs in or picks guest."""
    sweep_guest_libraries()
    user = state.get("user")
    if user:
        if user["kind"] == "guest" and not user_dir().exists():
            state.login_notice = "Your guest session ended, so its temporary library was deleted."
            _reset_session()
        else:
            return
    accounts, guests = get_home()

    _, hero, _, card = st.columns([0.15, 1.15, 0.12, 1], vertical_alignment="top")
    with hero:
        st.markdown(_HERO, unsafe_allow_html=True)
    with card, st.container(border=True, key="login_card"):
        st.markdown('<p class="sr-card-title">Welcome</p>'
                    '<p class="sr-muted sr-card-sub">Sign in to keep your library between sessions.</p>',
                    unsafe_allow_html=True)
        if state.get("login_notice"):
            st.info(state.login_notice, icon=":material/info:")
        if state.get("login_error"):
            st.error(state.login_error, icon=":material/error:")

        tab_in, tab_new = st.tabs(["Sign in", "Create account"])
        with tab_in, st.form("local_sign_in", border=False):
            name = st.text_input("Username", key="login_name")
            password = st.text_input("Password", type="password", key="login_password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                try:
                    found = accounts.verify(name, password)
                except AccountError as exc:
                    state.login_error = str(exc)
                    st.rerun()
                _enter({"kind": "account", "id": found.id, "username": found.username,
                        "dir": str(accounts.user_dir(found))})
        with tab_new, st.form("local_sign_up", border=False):
            name = st.text_input("Username", key="new_name")
            password = st.text_input("Password", type="password", key="new_pw",
                                     help=f"At least {MIN_PASSWORD} characters.")
            again = st.text_input("Confirm password", type="password", key="new_pw_again")
            claim = False
            if accounts.count() == 0 and accounts.has_legacy_library():
                claim = st.checkbox("Add the library already on this computer to this account",
                                    value=True, help="Folders you indexed before accounts existed. "
                                    "Without this they stay unused until an account adds them.")
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                try:
                    if password != again:
                        raise AccountError("The passwords don't match.")
                    created = accounts.create(name, password)
                    if claim:
                        accounts.claim_legacy_library(created)
                except AccountError as exc:
                    state.login_error = str(exc)
                    st.rerun()
                _enter({"kind": "account", "id": created.id, "username": created.username,
                        "dir": str(accounts.user_dir(created))})
        st.caption("Accounts are stored on this computer. Passwords are saved only as secure hashes, "
                   "and a forgotten password can't be recovered.")

        st.markdown('<div class="sr-or">or</div>', unsafe_allow_html=True)
        if st.button("Continue as guest", icon=":material/person_outline:", width="stretch"):
            path = guests.path_for(_session_id())
            path.mkdir(parents=True, exist_ok=True)
            _enter({"kind": "guest", "username": "Guest", "dir": str(path)})
        st.caption(GUEST_NOTICE)
    st.stop()
