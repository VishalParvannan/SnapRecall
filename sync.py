"""Optional account sync: back up screenshots and download them on another device.

Nothing is uploaded unless the user signs in AND turns on backup for a folder.

What is uploaded, per backed-up screenshot:
    the original image file (exact bytes), its file name, its modified time.
What is never uploaded:
    folder paths, recognized text, visual-search embeddings, thumbnails.

Each device builds its own search index locally, so downloaded screenshots
are indexed on the device that downloads them.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from config import SUPPORTED_EXTENSIONS
from storage import Storage

ProgressFn = Callable[[int, int, str], None]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class SyncError(RuntimeError):
    """A sync problem; the message is safe to show to users."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class RemoteFile:
    sha256: str
    name: str
    size: int
    mtime_ns: int
    uploaded_at: float


@dataclass
class Session:
    server: str
    email: str
    token: str


def check_server_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return url.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS:
        return url.rstrip("/")
    raise SyncError("Use an https:// address for the sync server (http is allowed only for localhost).")


# ---- session persistence ----------------------------------------------------

def load_session(path: Path) -> Session | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Session(data["server"], data["email"], data["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_session(path: Path, session: Session) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session.__dict__), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clear_session(path: Path) -> None:
    path.unlink(missing_ok=True)


# ---- API client -------------------------------------------------------------

class SyncClient:
    def __init__(self, server: str, token: str | None = None, http: httpx.Client | None = None):
        self.server = check_server_url(server)
        self.token = token
        self.http = http or httpx.Client(base_url=self.server, timeout=60)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise SyncError(f"Couldn't reach the sync server at {self.server}.") from None
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            message = detail if isinstance(detail, str) else f"The sync server returned an error ({response.status_code})."
            raise SyncError(message, response.status_code)
        return response

    def register(self, email: str, password: str) -> None:
        self._request("POST", "/register", json={"email": email, "password": password})

    def login(self, email: str, password: str) -> Session:
        data = self._request("POST", "/login", json={"email": email, "password": password}).json()
        self.token = data["token"]
        return Session(self.server, data["email"], data["token"])

    def logout(self) -> None:
        self._request("POST", "/logout")
        self.token = None

    def me(self) -> dict:
        return self._request("GET", "/me").json()

    def delete_account(self) -> None:
        self._request("DELETE", "/me")
        self.token = None

    def list_files(self) -> list[RemoteFile]:
        return [RemoteFile(**f) for f in self._request("GET", "/files").json()]

    def upload(self, path: Path, name: str, mtime_ns: int, sha256: str) -> None:
        self._request("PUT", f"/files/{sha256}", params={"name": name, "mtime_ns": mtime_ns},
                      content=Path(path).read_bytes())

    def download(self, sha256: str) -> bytes:
        return self._request("GET", f"/files/{sha256}").content

    def delete_all_files(self) -> None:
        self._request("DELETE", "/files")


# ---- backup and download ----------------------------------------------------

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class BackupReport:
    folder: str = ""
    uploaded: int = 0
    already: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def backup_folder(folder: str, storage: Storage, client: SyncClient,
                  progress: ProgressFn | None = None) -> BackupReport:
    """Upload this folder's indexed screenshots that the account doesn't have yet."""
    report = BackupReport(folder=folder)
    remote = {f.sha256 for f in client.list_files()}
    records = [r for r in storage.folder_images(folder) if r.status != "error"]
    for i, rec in enumerate(records, start=1):
        if progress:
            progress(i, len(records), rec.name)
        path = Path(rec.path)
        try:
            st = path.stat()
            if (st.st_size, st.st_mtime_ns) != (rec.size, rec.mtime_ns):
                report.failed.append((rec.path, "Changed since it was indexed; re-index first"))
                continue
            sha = rec.sha256 or file_sha256(path)
        except OSError:
            report.failed.append((rec.path, "File is missing or can't be read"))
            continue
        if not rec.sha256:
            storage.set_sha256(rec.path, sha, rec.size, rec.mtime_ns)
        if sha in remote:
            report.already += 1
            continue
        try:
            client.upload(path, rec.name, rec.mtime_ns, sha)
        except SyncError as exc:
            if exc.status == 401:
                raise
            report.failed.append((rec.path, str(exc)))
            continue
        except OSError:
            report.failed.append((rec.path, "File is missing or can't be read"))
            continue
        remote.add(sha)
        report.uploaded += 1
    return report


@dataclass
class DownloadReport:
    folder: str
    downloaded: int = 0
    already: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def _unique_path(folder: Path, name: str) -> Path:
    candidate = folder / name
    stem, suffix = candidate.stem, candidate.suffix
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def download_all(client: SyncClient, dest: Path, progress: ProgressFn | None = None) -> DownloadReport:
    """Download backed-up screenshots missing from `dest`. Existing files are never overwritten."""
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    report = DownloadReport(folder=str(dest.resolve()))
    local = set()
    for p in dest.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                local.add(file_sha256(p))
            except OSError:
                pass
    remote = client.list_files()
    for i, f in enumerate(remote, start=1):
        if progress:
            progress(i, len(remote), f.name)
        if f.sha256 in local:
            report.already += 1
            continue
        try:
            data = client.download(f.sha256)
        except SyncError as exc:
            if exc.status == 401:
                raise
            report.failed.append((f.name, str(exc)))
            continue
        if hashlib.sha256(data).hexdigest() != f.sha256:
            report.failed.append((f.name, "Download was corrupted"))
            continue
        name = Path(f.name).name
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            name += ".png"
        target = _unique_path(dest, name)
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        os.utime(target, ns=(f.mtime_ns, f.mtime_ns))
        local.add(f.sha256)
        report.downloaded += 1
    return report
