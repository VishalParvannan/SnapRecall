import os
import sqlite3

import pytest

import accounts
from accounts import AccountError, GuestLibraries, LocalAccounts
from conftest import make_image
from config import load_config
from indexer import index_folder
from storage import Storage


def test_create_and_verify(tmp_path):
    acc = LocalAccounts(tmp_path)
    user = acc.create("sam", "correct horse")
    assert acc.verify("SAM", "correct horse") == user  # usernames ignore case
    assert acc.user_dir(user).is_dir()
    raw = (tmp_path / "accounts.db").read_bytes()
    assert b"correct horse" not in raw  # only a hash is stored


@pytest.mark.parametrize("name, password", [("sam", "short"), ("x", "long enough"), ("a b", "long enough")])
def test_create_rejects_bad_input(tmp_path, name, password):
    with pytest.raises(AccountError):
        LocalAccounts(tmp_path).create(name, password)


def test_wrong_password_and_duplicate(tmp_path):
    acc = LocalAccounts(tmp_path)
    acc.create("sam", "correct horse")
    with pytest.raises(AccountError, match="Wrong"):
        acc.verify("sam", "wrong password")
    with pytest.raises(AccountError, match="Wrong"):
        acc.verify("nobody", "correct horse")
    with pytest.raises(AccountError, match="taken"):
        acc.create("Sam", "another password")


def test_delete_account_keeps_screenshots(tmp_path):
    shots = tmp_path / "shots"
    shot = make_image(shots / "a.png")
    acc = LocalAccounts(tmp_path / "home")
    user = acc.create("sam", "correct horse")
    config = load_config(acc.user_dir(user))
    index_folder(str(shots), Storage(config.db_path), config)
    with pytest.raises(AccountError):
        acc.delete(user, "wrong password")
    acc.delete(user, "correct horse")
    assert not acc.user_dir(user).exists()
    assert shot.exists()
    with pytest.raises(AccountError):
        acc.verify("sam", "correct horse")


def test_claim_legacy_library(tmp_path):
    home, shots = tmp_path / "home", tmp_path / "shots"
    make_image(shots / "a.png")
    legacy = load_config(home)
    index_folder(str(shots), Storage(legacy.db_path), legacy)
    (home / "label_prompts_abc.npz").write_bytes(b"x")
    acc = LocalAccounts(home)
    assert acc.has_legacy_library()
    user = acc.create("sam", "correct horse")
    acc.claim_legacy_library(user)

    assert not acc.has_legacy_library()
    assert (acc.cache_dir / "label_prompts_abc.npz").exists()
    moved = load_config(acc.user_dir(user))
    records = Storage(moved.db_path).all_images()
    assert len(records) == 1
    thumb = records[0].thumbnail
    assert thumb.startswith(str(moved.thumbnail_dir)) and os.path.exists(thumb)


def test_guest_sweep_waits_for_grace_period(tmp_path):
    guests = GuestLibraries(tmp_path)
    live, gone = guests.path_for("live-session"), guests.path_for("gone-session")
    for p in (live, gone):
        p.mkdir(parents=True)
    active = {"live-session"}

    def is_active(sid):
        return sid in active

    assert guests.sweep(is_active, now=0) == []          # inactive, but within the grace period
    assert guests.sweep(is_active, now=accounts.GUEST_GRACE_SECONDS + 1) == [gone]
    assert live.exists() and not gone.exists()


def test_guest_sweep_reconnect_resets_grace(tmp_path):
    guests = GuestLibraries(tmp_path)
    path = guests.path_for("s1")
    path.mkdir(parents=True)
    active = set()
    guests.sweep(lambda s: s in active, now=0)
    active.add("s1")                                       # the browser reconnected
    guests.sweep(lambda s: s in active, now=30)
    active.clear()
    assert guests.sweep(lambda s: s in active, now=accounts.GUEST_GRACE_SECONDS + 10) == []
    assert path.exists()


def test_guest_sweep_removes_libraries_of_exited_processes(tmp_path, monkeypatch):
    guests = GuestLibraries(tmp_path)
    stale = guests.root / "999999-old"
    other_live = guests.root / "123-other"
    for p in (stale, other_live):
        p.mkdir(parents=True)
    monkeypatch.setattr(accounts, "_pid_alive", lambda pid: pid == 123)
    assert guests.sweep(lambda s: True) == [stale]
    assert other_live.exists()


def test_pid_alive_for_this_process():
    assert accounts._pid_alive(os.getpid())


def test_delete_all_mine(tmp_path):
    guests = GuestLibraries(tmp_path)
    mine = guests.path_for("s1")
    theirs = guests.root / "1-other"
    for p in (mine, theirs):
        p.mkdir(parents=True)
    guests.delete_all_mine()
    assert not mine.exists() and theirs.exists()


def test_accounts_db_schema(tmp_path):
    LocalAccounts(tmp_path)
    conn = sqlite3.connect(tmp_path / "accounts.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    conn.close()
    assert {"username", "salt", "pw_hash"} <= cols
