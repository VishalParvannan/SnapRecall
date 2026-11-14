"""The web backend (web/app.py), exercised through FastAPI's test client with stand-in models."""
import shutil
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from conftest import make_image  # noqa: E402
from fakes import FakeEmbedder, FakeOcr  # noqa: E402
from web.app import create_app  # noqa: E402


class Models:
    """Stands in for BackgroundModels: everything loaded."""
    text_model = None
    problems: list = []
    done = True

    def __init__(self, ocr=None, embedder=None):
        self.ocr, self.embedder = ocr, embedder

    def wait(self, timeout=None):
        return True


class BlockingOcr(FakeOcr):
    def __init__(self):
        super().__init__({"red": "invoice total"})
        self.started, self.proceed = threading.Event(), threading.Event()

    def extract(self, image):
        self.started.set()
        self.proceed.wait(10)
        return super().extract(image)


def make_client(tmp_path, models=None, picker=lambda start: []):
    models = models or Models(FakeOcr({"red": "invoice total", "blue": "hello world"}), FakeEmbedder())
    app = create_app(home=tmp_path / "home", models=models, picker=picker)
    client = TestClient(app, base_url="http://127.0.0.1")
    client.headers.update({"X-Requested-With": "SnapRecall"})
    return client


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


@pytest.fixture
def guest(client):
    assert client.post("/api/session/guest").status_code == 200
    return client


def wait_for_jobs(client, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        jobs = client.get("/api/jobs").json()
        if not jobs["active"]:
            return jobs
        time.sleep(0.02)
    raise AssertionError("indexing did not finish")


def library_folder(tmp_path):
    shots = tmp_path / "shots"
    make_image(shots / "a.png", color=(220, 30, 30))
    make_image(shots / "b.png", color=(30, 60, 220))
    shutil.copy(shots / "a.png", shots / "a copy.png")  # an identical copy
    return shots


# ---- protections ----------------------------------------------------------------
def test_only_answers_on_this_computer(client):
    assert client.get("/api/session").status_code == 200
    assert client.get("/api/session", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/", headers={"Host": "192.168.1.5:8610"}).status_code == 400


def test_changes_need_the_custom_header_and_same_origin(client):
    plain = TestClient(client.app, base_url="http://127.0.0.1")
    assert plain.post("/api/session/guest").status_code == 403
    cross = client.post("/api/session/guest", headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403
    same = client.post("/api/session/guest", headers={"Origin": "http://127.0.0.1"})
    assert same.status_code == 200


def test_page_is_served_with_a_content_security_policy(client):
    page = client.get("/")
    assert page.status_code == 200 and "SnapRecall" in page.text
    policy = page.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_library_needs_sign_in(client):
    response = client.get("/api/library")
    assert response.status_code == 401 and "Sign in" in response.json()["error"]
    assert client.get("/api/search?q=x").status_code == 401


# ---- accounts and guests ------------------------------------------------------------
def test_account_lifecycle(client):
    assert client.get("/api/session").json()["user"] is None
    bad = client.post("/api/session/register", json={"username": "sam", "password": "longenough", "confirm": "other"})
    assert bad.status_code == 400 and "match" in bad.json()["error"]
    ok = client.post("/api/session/register", json={"username": "sam", "password": "longenough", "confirm": "longenough"})
    assert ok.status_code == 200
    assert client.get("/api/session").json()["user"] == {"kind": "account", "username": "sam"}
    assert client.get("/api/library").json()["username"] == "sam"
    client.post("/api/session/logout")
    assert client.get("/api/session").json()["user"] is None
    assert client.get("/api/library").status_code == 401
    assert client.post("/api/session/login", json={"username": "sam", "password": "longenough"}).status_code == 200
    taken = client.post("/api/session/register", json={"username": "SAM", "password": "longenough", "confirm": "longenough"})
    assert taken.status_code == 400


def test_failed_sign_ins_are_throttled(client):
    client.post("/api/session/register", json={"username": "sam", "password": "longenough", "confirm": "longenough"})
    client.post("/api/session/logout")
    codes = [client.post("/api/session/login", json={"username": "sam", "password": f"wrong{i}"}).status_code
             for i in range(6)]
    assert codes == [401] * 5 + [429]
    # Even the right password is refused while locked out.
    assert client.post("/api/session/login", json={"username": "sam", "password": "longenough"}).status_code == 429


def test_delete_account_needs_the_password(client):
    client.post("/api/session/register", json={"username": "sam", "password": "longenough", "confirm": "longenough"})
    assert client.post("/api/account/delete", json={"password": "nope"}).status_code == 400
    assert client.post("/api/account/delete", json={"password": "longenough"}).status_code == 200
    assert client.get("/api/session").json()["user"] is None
    assert client.post("/api/session/login", json={"username": "sam", "password": "longenough"}).status_code == 401


def test_guest_library_is_temporary(client, tmp_path):
    client.post("/api/session/guest")
    assert client.get("/api/library").json()["guest"] is True
    folders = list((tmp_path / "home" / "guests").iterdir())
    assert len(folders) == 1
    client.post("/api/session/logout")
    assert not folders[0].exists()


# ---- index, search, detail -------------------------------------------------------------
def test_index_search_and_detail(guest, tmp_path):
    shots = library_folder(tmp_path)
    started = guest.post("/api/library/index", json={"folders": [str(shots)], "files": []})
    assert started.status_code == 202
    finished = wait_for_jobs(guest)
    assert finished["recent"][0]["state"] == "done" and finished["recent"][0]["processed"] == 3

    library = guest.get("/api/library").json()
    assert library["folders"][0]["count"] == 3

    found = guest.get("/api/search", params={"q": "invoice", "folder": str(shots)}).json()
    assert found["state"] == "results" and found["hidden"] == 1  # the identical copy is hidden
    top = found["results"][0]
    assert top["name"] in ("a.png", "a copy.png") and top["copies"] == 1 and top["thumb"].startswith("/api/image")
    assert any(hit for _, hit in top["excerpt"])

    browse = guest.get("/api/search", params={"folder": str(shots)}).json()
    assert browse["state"] == "browse" and browse["count"] == 2 and browse["order"] == "Date modified (newest)"

    nothing = guest.get("/api/search", params={"q": "zzzzqq", "folder": str(shots), "when": "today"}).json()
    assert nothing["state"] in ("results", "no-match")

    detail = guest.get("/api/detail", params={"path": top["path"], "folder": str(shots)}).json()
    assert detail["name"] == top["name"] and len(detail["copies"]) == 1 and "invoice" in detail["ocrText"]
    assert guest.get(detail["image"]).headers["content-type"] == "image/png"
    assert guest.get(detail["png"]).headers["content-type"] == "image/png"
    assert guest.get(top["thumb"]).headers["content-type"] == "image/jpeg"


def test_only_library_files_can_be_read(guest, tmp_path):
    shots = library_folder(tmp_path)
    secret = tmp_path / "secret.png"
    make_image(secret)
    guest.post("/api/library/index", json={"folders": [str(shots)], "files": []})
    wait_for_jobs(guest)
    for kind in ("thumb", "full", "png"):
        assert guest.get("/api/image", params={"path": str(secret), "kind": kind}).status_code == 404
    assert guest.get("/api/detail", params={"path": str(secret)}).status_code == 404
    assert guest.post("/api/screenshot/delete", json={"path": str(secret)}).status_code == 404
    assert secret.exists()


def test_invalid_dates_are_rejected(guest, tmp_path):
    shots = library_folder(tmp_path)
    guest.post("/api/library/index", json={"folders": [str(shots)], "files": []})
    wait_for_jobs(guest)
    assert guest.get("/api/search", params={"when": "custom", "start": "not-a-date"}).status_code == 400


def test_rename_and_delete(guest, tmp_path):
    shots = library_folder(tmp_path)
    guest.post("/api/library/index", json={"folders": [str(shots)], "files": []})
    wait_for_jobs(guest)
    path = str(shots / "b.png")
    renamed = guest.post("/api/screenshot/rename", json={"path": path, "name": "receipt"})
    assert renamed.status_code == 200 and Path(renamed.json()["path"]).name == "receipt.png"
    assert (shots / "receipt.png").exists() and not (shots / "b.png").exists()
    bad = guest.post("/api/screenshot/rename", json={"path": renamed.json()["path"], "name": "a?b"})
    assert bad.status_code == 400
    assert guest.post("/api/screenshot/delete", json={"path": renamed.json()["path"]}).status_code == 200
    assert (shots / "receipt.png").exists()  # only SnapRecall's data is removed
    assert guest.get("/api/library").json()["removedCount"] == 1
    assert guest.post("/api/library/restore-removed").json()["restored"] == 1


def test_folder_management(guest, tmp_path):
    shots = library_folder(tmp_path)
    guest.post("/api/library/index", json={"folders": [str(shots)], "files": []})
    wait_for_jobs(guest)
    assert guest.post("/api/library/reindex", json={"folder": str(shots)}).status_code == 202
    wait_for_jobs(guest)
    assert guest.post("/api/library/reindex", json={"folder": "/not/in/library"}).status_code == 404
    assert guest.post("/api/library/forget", json={"folder": str(shots)}).status_code == 200
    assert guest.get("/api/library").json()["folders"] == []
    assert guest.get("/api/search").json()["state"] == "empty"
    assert guest.post("/api/library/index", json={"folders": [], "files": []}).status_code == 400


def test_picker_splits_folders_from_files(client, tmp_path):
    shots = library_folder(tmp_path)
    chosen = [str(shots), str(shots / "a.png")]
    with make_client(tmp_path / "other", picker=lambda start: chosen) as picking:
        picking.post("/api/session/guest")
        assert picking.post("/api/library/pick", json={}).json() == {"folders": [str(shots)], "files": [str(shots / "a.png")]}


def test_cancel_an_indexing_run(tmp_path):
    ocr = BlockingOcr()
    shots = tmp_path / "shots"
    for i in range(3):
        make_image(shots / f"s{i}.png", color=(220, 30, 30 + i))
    with make_client(tmp_path / "web", Models(ocr)) as client:
        client.post("/api/session/guest")
        job = client.post("/api/library/index", json={"folders": [str(shots)], "files": []}).json()
        assert ocr.started.wait(10)
        assert client.get("/api/jobs").json()["active"][0]["id"] == job["id"]
        assert client.post(f"/api/jobs/{job['id']}/cancel").json()["cancelRequested"]
        assert client.post("/api/jobs/unknown/cancel").status_code == 404
        ocr.proceed.set()
        recent = wait_for_jobs(client)["recent"][0]
        assert recent["state"] == "cancelled" and recent["processed"] == 1
        assert client.get("/api/library").json()["folders"][0]["count"] == 1


def test_one_visitor_cannot_use_anothers_jobs(tmp_path):
    shots = library_folder(tmp_path)
    with make_client(tmp_path / "web") as client:
        client.post("/api/session/register", json={"username": "ann", "password": "longenough", "confirm": "longenough"})
        job = client.post("/api/library/index", json={"folders": [str(shots)], "files": []}).json()
        wait_for_jobs(client)
        client.post("/api/session/logout")
        client.post("/api/session/register", json={"username": "bob", "password": "longenough", "confirm": "longenough"})
        assert client.get("/api/library").json()["folders"] == []
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 404
        assert client.get("/api/jobs").json() == {"active": [], "recent": []}


# ---- refreshing and taking over the earlier library ------------------------------------

def test_refresh_endpoint_rechecks_without_scanning_for_new_files(guest, tmp_path):
    shots = library_folder(tmp_path)
    guest.post("/api/library/index", json={"folders": [str(shots)], "files": []})
    wait_for_jobs(guest)
    make_image(shots / "late.png", color=(30, 220, 30))  # added after indexing
    assert guest.post("/api/library/refresh", json={"folder": "/not/in/library"}).status_code == 404
    started = guest.post("/api/library/refresh", json={"folder": str(shots)})
    assert started.status_code == 202 and started.json()["refresh"] is True
    recent = wait_for_jobs(guest)["recent"][0]
    assert recent["refresh"] and recent["state"] == "done"
    assert guest.get("/api/library").json()["folders"][0]["count"] == 3  # "late.png" is not picked up


def test_account_takes_over_the_earlier_library(tmp_path):
    from config import load_config
    from indexer import index_folder
    from storage import Storage

    shots = library_folder(tmp_path)
    legacy = load_config(tmp_path / "web" / "home")
    index_folder(shots, Storage(legacy.db_path), legacy, FakeOcr({"red": "invoice total"}))
    with make_client(tmp_path / "web") as client:
        client.post("/api/session/guest")
        assert client.get("/api/library").json()["canClaimLegacy"] is False  # guests can't
        assert client.post("/api/library/claim-legacy").status_code == 400
        client.post("/api/session/logout")

        client.post("/api/session/register", json={"username": "sam", "password": "longenough", "confirm": "longenough"})
        library = client.get("/api/library").json()
        assert library["canClaimLegacy"] is True and library["folders"] == []
        assert client.post("/api/library/claim-legacy").status_code == 200
        library = client.get("/api/library").json()
        assert library["canClaimLegacy"] is False and library["folders"][0]["count"] == 3
        assert client.get("/api/search", params={"q": "invoice"}).json()["state"] == "results"
        assert client.post("/api/library/claim-legacy").status_code == 400  # nothing left to take over


def test_an_account_with_screenshots_cannot_take_over(tmp_path):
    from config import load_config
    from indexer import index_folder
    from storage import Storage

    shots = library_folder(tmp_path)
    legacy = load_config(tmp_path / "web" / "home")
    index_folder(shots, Storage(legacy.db_path), legacy, FakeOcr({}))
    mine = tmp_path / "mine"
    make_image(mine / "own.png", color=(30, 60, 220))
    with make_client(tmp_path / "web") as client:
        client.post("/api/session/register", json={"username": "ann", "password": "longenough", "confirm": "longenough"})
        client.post("/api/library/index", json={"folders": [str(mine)], "files": []})
        wait_for_jobs(client)
        assert client.get("/api/library").json()["canClaimLegacy"] is False
        refused = client.post("/api/library/claim-legacy")
        assert refused.status_code == 400 and "already has" in refused.json()["error"]
        assert [f["label"] for f in client.get("/api/library").json()["folders"]] == ["mine"]
