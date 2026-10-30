import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from conftest import make_image
from indexer import index_folder
from sync import (Session, SyncClient, SyncError, backup_folder, check_server_url, clear_session,
                  download_all, file_sha256, load_session, save_session)
from sync_server import server as sync_server

PASSWORD = "correct horse battery"


@pytest.fixture
def api(tmp_path):
    return TestClient(sync_server.create_app(tmp_path / "server"))


def client_for(api, email="ana@example.com", register=True) -> SyncClient:
    client = SyncClient("http://localhost:8765", http=api)
    if register:
        client.register(email, PASSWORD)
    client.login(email, PASSWORD)
    return client


# ---- accounts -------------------------------------------------------------

def test_register_login_me_logout(api):
    client = client_for(api)
    assert client.me() == {"email": "ana@example.com", "file_count": 0, "bytes": 0}
    client_token = client.token
    client.logout()
    stale = SyncClient("http://localhost:8765", token=client_token, http=api)
    with pytest.raises(SyncError) as err:
        stale.me()
    assert err.value.status == 401


def test_duplicate_email_and_bad_input(api):
    client = client_for(api)
    with pytest.raises(SyncError, match="already exists"):
        client.register("ANA@example.com", PASSWORD)
    with pytest.raises(SyncError, match="valid email"):
        client.register("not-an-email", PASSWORD)
    with pytest.raises(SyncError, match="8 characters"):
        client.register("bo@example.com", "short")


def test_wrong_password_and_rate_limit(api):
    client_for(api)
    other = SyncClient("http://localhost:8765", http=api)
    for _ in range(5):
        with pytest.raises(SyncError, match="incorrect"):
            other.login("ana@example.com", "wrong password")
    with pytest.raises(SyncError) as err:
        other.login("ana@example.com", PASSWORD)
    assert err.value.status == 429


def test_passwords_are_not_stored_in_plain_text(api, tmp_path):
    client_for(api)
    assert PASSWORD.encode() not in (tmp_path / "server" / "server.db").read_bytes()


def test_requests_without_token_are_rejected(api):
    assert api.get("/files").status_code == 401
    assert api.get("/files", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_https_required_except_localhost():
    assert check_server_url("https://sync.example.com/") == "https://sync.example.com"
    assert check_server_url("http://127.0.0.1:8765") == "http://127.0.0.1:8765"
    with pytest.raises(SyncError, match="https"):
        check_server_url("http://sync.example.com")


def test_session_file_roundtrip(tmp_path):
    path = tmp_path / "account.json"
    assert load_session(path) is None
    save_session(path, Session("http://localhost:8765", "ana@example.com", "tok"))
    assert load_session(path) == Session("http://localhost:8765", "ana@example.com", "tok")
    clear_session(path)
    assert load_session(path) is None
    path.write_text("{broken")
    assert load_session(path) is None


# ---- files ----------------------------------------------------------------

def test_upload_validates_hash_and_type(api, tmp_path):
    client = client_for(api)
    img = make_image(tmp_path / "a.png")
    with pytest.raises(SyncError, match="corrupted"):
        client.upload(img, "a.png", 1, "0" * 64)
    text = tmp_path / "notes.png"
    text.write_bytes(b"hello")
    with pytest.raises(SyncError, match="PNG and JPEG"):
        client.upload(text, "notes.png", 1, file_sha256(text))
    with pytest.raises(SyncError, match="Invalid file id"):
        client.download("../../etc/passwd".replace("/", "x"))


def test_accounts_cannot_see_each_others_files(api, tmp_path):
    ana = client_for(api)
    img = make_image(tmp_path / "a.png")
    ana.upload(img, "a.png", 1, file_sha256(img))
    bo = client_for(api, "bo@example.com")
    assert bo.list_files() == []
    with pytest.raises(SyncError) as err:
        bo.download(file_sha256(img))
    assert err.value.status == 404


def test_backup_and_download_to_another_device(api, env, tmp_path):
    shots, config, storage = env
    a = make_image(shots / "a.png", (220, 30, 30))
    make_image(shots / "sub" / "b.png", (30, 60, 220))
    os.utime(a, ns=(1_600_000_000_000_000_000,) * 2)
    index_folder(shots, storage, config)

    client = client_for(api)
    report = backup_folder(str(shots), storage, client)
    assert (report.uploaded, report.already, report.failed) == (2, 0, [])
    assert storage.get(str(a)).sha256 == file_sha256(a)

    again = backup_folder(str(shots), storage, client)
    assert (again.uploaded, again.already) == (0, 2)

    # Only the image bytes, name and time leave the device — not the folder path.
    names = sorted(f.name for f in client.list_files())
    assert names == ["a.png", "b.png"]

    other_device = tmp_path / "laptop" / "SnapRecall Backup"
    down = download_all(client_for(api, register=False), other_device)
    assert down.downloaded == 2
    copy = other_device / "a.png"
    assert copy.read_bytes() == a.read_bytes()
    assert copy.stat().st_mtime_ns == a.stat().st_mtime_ns

    # Downloading again skips files that are already there and never overwrites.
    assert download_all(client, other_device).already == 2


def test_download_never_overwrites_different_file_with_same_name(api, env, tmp_path):
    shots, config, storage = env
    make_image(shots / "a.png", (220, 30, 30))
    index_folder(shots, storage, config)
    client = client_for(api)
    backup_folder(str(shots), storage, client)

    dest = tmp_path / "dest"
    existing = make_image(dest / "a.png", (0, 255, 0))
    before = existing.read_bytes()
    download_all(client, dest)
    assert existing.read_bytes() == before
    assert (dest / "a (2).png").exists()


def test_backup_skips_changed_and_missing_files(api, env):
    shots, config, storage = env
    a = make_image(shots / "a.png")
    b = make_image(shots / "b.png")
    index_folder(shots, storage, config)
    make_image(a, (1, 2, 3), size=(70, 50))
    b.unlink()
    report = backup_folder(str(shots), storage, client_for(api))
    assert report.uploaded == 0
    assert sorted(Path(p).name for p, _ in report.failed) == ["a.png", "b.png"]


def test_delete_all_files_and_account(api, env, tmp_path):
    shots, config, storage = env
    make_image(shots / "a.png")
    index_folder(shots, storage, config)
    client = client_for(api)
    backup_folder(str(shots), storage, client)
    assert client.me()["file_count"] == 1

    client.delete_all_files()
    assert client.list_files() == []

    backup_folder(str(shots), storage, client)
    client.delete_account()
    assert not any((tmp_path / "server" / "files").iterdir())
    with pytest.raises(SyncError, match="incorrect"):
        SyncClient("http://localhost:8765", http=api).login("ana@example.com", PASSWORD)
    assert (shots / "a.png").exists()  # local originals untouched


def test_unreachable_server_message():
    client = SyncClient("http://127.0.0.1:9")
    with pytest.raises(SyncError, match="Couldn't reach"):
        client.list_files()


def test_backup_setting_persists(env):
    shots, config, storage = env
    make_image(shots / "a.png")
    index_folder(shots, storage, config)
    storage.set_backup(str(shots), True)
    assert storage.list_folders()[0].backup is True
