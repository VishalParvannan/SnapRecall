"""Sign-in throttling in the Streamlit interface (driven with Streamlit's test runner)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
import streamlit as st
from streamlit.testing.v1 import AppTest

from accounts import LOGIN_ATTEMPTS, LocalAccounts

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SNAPRECALL_HOME", str(tmp_path))
    for flag in ("SNAPRECALL_OCR", "SNAPRECALL_VISUAL", "SNAPRECALL_TEXT_MEANING"):
        monkeypatch.setenv(flag, "0")
    st.cache_resource.clear()  # the accounts folder and throttle are cached per process
    LocalAccounts(tmp_path).create("sam", "correct horse")
    yield AppTest.from_file(str(APP), default_timeout=60).run()
    st.cache_resource.clear()


def sign_in(at, password):
    at.text_input(key="login_name").set_value("sam")
    at.text_input(key="login_password").set_value(password)
    next(b for b in at.button if b.label == "Sign in").click().run()
    return [e.value for e in at.error]


def signed_in(at):
    return "user" in at.session_state and at.session_state["user"] is not None


def test_right_password_signs_in(app):
    assert sign_in(app, "correct horse") == []
    assert signed_in(app)


def test_failed_sign_ins_are_throttled(app):
    for _ in range(LOGIN_ATTEMPTS):
        assert sign_in(app, "wrong password") == ["Wrong username or password."]
    # Even the right password is refused while locked out.
    assert sign_in(app, "correct horse") == ["Too many failed attempts. Wait a few minutes and try again."]
    assert not signed_in(app)
