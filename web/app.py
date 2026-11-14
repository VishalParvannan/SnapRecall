"""The SnapRecall web backend.

It serves the frontend in `static/` and a JSON API for it, and reuses the same code as the
Streamlit app: accounts, the indexer, search, copy image, rename. It is meant to run on this
computer only (127.0.0.1), as a desktop window or in a browser tab:

    python snaprecall.py

Because any web page you visit can send requests to a local server, the API checks the `Host`
header (against DNS rebinding), requires a custom header on every request that changes something
(a page on another site can't add one without our permission), and keeps its session cookie
`SameSite=Strict`. The page itself is served with a Content-Security-Policy that blocks scripts
and styles from anywhere else. These are protections for a local app, not a security audit.
"""
from __future__ import annotations

import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from accounts import AccountError, GuestLibraries, LocalAccounts, User
from config import SUPPORTED_EXTENSIONS, Config, load_config, snaprecall_home
from copy_image import CopyImageError, clipboard_png
from folder_picker import FolderPickerError, pick_screenshots
from index_jobs import IndexJobs
from indexer import (INDIVIDUAL, RenameError, forget_folder, remove_screenshots, rename_screenshot)
from labels import describe_confidence
from models import BackgroundModels
from search import (BEST_MATCH, SORT_OPTIONS, excerpt, filter_by_date, group_duplicates, identical_copies,
                    query_terms, same_image, search, similar, sort_records)
from storage import ImageRecord, Storage

STATIC = Path(__file__).parent / "static"
ALL_FOLDERS = "__all__"
COOKIE = "sr_session"
GUEST_ACTIVE_SECONDS = 45  # a guest tab pings every ~15 s; silent for this long means it was closed
LOGIN_ATTEMPTS, LOGIN_WINDOW = 5, 300  # failed sign-ins allowed per username per window (seconds)
BROWSE_LIMIT = 60
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
CSP = ("default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Session:
    def __init__(self, user: dict | None = None):
        self.user = user  # {"kind": "account" | "guest", "id", "username", "dir"}
        self.last_seen = time.monotonic()
        self.storage: Storage | None = None
        self.config: Config | None = None


class Credentials(BaseModel):
    username: str
    password: str


class Registration(Credentials):
    confirm: str
    claimLegacy: bool = False


class Password(BaseModel):
    password: str


class IndexRequest(BaseModel):
    folders: list[str] = []
    files: list[str] = []


class FolderRef(BaseModel):
    folder: str | None = None


class PickRequest(BaseModel):
    start: str | None = None


class PathRef(BaseModel):
    path: str


class RenameRequest(PathRef):
    name: str


class AppState:
    def __init__(self, home: Path, models, picker: Callable[[str | None], list[str]]):
        self.home = home
        self.accounts = LocalAccounts(home)
        self.guests = GuestLibraries(home)
        self.accounts.cache_dir.mkdir(exist_ok=True)
        self.models = models
        self.jobs = IndexJobs(models)
        self.picker = picker
        self.sessions: dict[str, Session] = {}
        self.libraries: dict[str, tuple[Config, Storage]] = {}
        self.failures: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self._last_sweep = 0.0

    # ---- sessions ------------------------------------------------------------
    def start_session(self, user: dict) -> str:
        token = secrets.token_hex(16)  # letters and digits only: also names a guest's library folder
        with self.lock:
            self.sessions[token] = Session(user)
        return token

    def end_session(self, token: str) -> None:
        with self.lock:
            session = self.sessions.pop(token, None)
        if session and session.user and session.user["kind"] == "guest":
            self.drop_library(session.user["dir"])
            self.guests.delete(Path(session.user["dir"]))

    def drop_library(self, directory: str) -> None:
        with self.lock:
            self.libraries.pop(directory, None)

    def library(self, user: dict) -> tuple[Config, Storage]:
        directory = user["dir"]
        with self.lock:
            if directory not in self.libraries:
                config = load_config(directory, cache_dir=self.accounts.cache_dir)
                self.libraries[directory] = (config, Storage(config.db_path))
            return self.libraries[directory]

    def sweep_guests(self) -> None:
        """Delete the libraries of guests whose tab went away (throttled; runs on requests)."""
        now = time.monotonic()
        if now - self._last_sweep < 10:
            return
        self._last_sweep = now

        def is_active(session_id: str) -> bool:
            with self.lock:
                session = self.sessions.get(session_id)
                return bool(session and now - session.last_seen < GUEST_ACTIVE_SECONDS)

        for path in self.guests.sweep(is_active):
            self.drop_library(str(path))
        with self.lock:
            for token in [t for t, s in self.sessions.items()
                          if s.user and s.user["kind"] == "guest" and not Path(s.user["dir"]).exists()]:
                self.sessions.pop(token)

    # ---- sign-in throttling ----------------------------------------------------
    def check_attempts(self, name: str) -> None:
        now = time.monotonic()
        recent = [t for t in self.failures.get(name.lower(), []) if now - t < LOGIN_WINDOW]
        self.failures[name.lower()] = recent
        if len(recent) >= LOGIN_ATTEMPTS:
            raise HTTPException(429, "Too many failed attempts. Wait a few minutes and try again.")

    def failed_attempt(self, name: str) -> None:
        self.failures.setdefault(name.lower(), []).append(time.monotonic())


class Library:
    """The signed-in visitor's library for one request."""

    def __init__(self, state: AppState, session: Session):
        self.state, self.session = state, session
        self.user = session.user
        self.config, self.storage = state.library(session.user)

    def records(self, folder: str | None) -> list[ImageRecord]:
        found = (self.storage.all_images() if folder in (None, "", ALL_FOLDERS)
                 else self.storage.folder_images(folder))
        return [r for r in found if r.status != "error"]

    def known(self, path: str) -> ImageRecord:
        rec = self.storage.get(path)
        if rec is None:
            raise HTTPException(404, "That screenshot isn't in your library.")
        return rec


# ---- JSON shapes ---------------------------------------------------------------
def label_of(path: str) -> str:
    return "Individual screenshots" if path == INDIVIDUAL else (Path(path).name or path)


def image_url(path: str, kind: str, version: int = 0) -> str:
    return "/api/image?" + urlencode({"path": path, "kind": kind, "v": version})


def card(rec: ImageRecord, copies: dict[str, list[ImageRecord]] | None = None,
         terms: list[str] | None = None, strong: bool | None = None) -> dict:
    segments = excerpt(rec.ocr_text or "", terms) if terms else None
    return {
        "path": rec.path, "name": rec.name, "thumb": image_url(rec.path, "thumb", rec.mtime_ns // 10**9),
        "mtimeMs": rec.mtime_ns // 10**6, "copies": len((copies or {}).get(rec.path, ())),
        "excerpt": [[text, hit] for text, hit in segments] if segments else None, "strong": strong,
    }


def date_range(when: str, start: str | None, end: str | None) -> tuple[date | None, date | None]:
    today = date.today()
    if when == "today":
        return today, None
    if when == "7d":
        return today - timedelta(days=6), None
    if when == "30d":
        return today - timedelta(days=29), None
    if when == "year":
        return date(today.year, 1, 1), None
    if when == "custom":
        try:
            return (date.fromisoformat(start) if start else None), (date.fromisoformat(end) if end else None)
        except ValueError:
            raise HTTPException(400, "Those dates aren't valid.") from None
    return None, None


def open_file(path: str) -> None:
    if not Path(path).exists():
        raise FileNotFoundError("The file is no longer at this location.")
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens with the default viewer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def ocr_quality(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    return "clear" if confidence >= 0.8 else "mostly clear" if confidence >= 0.5 else "hard to read; may contain mistakes"


def create_app(home: str | Path | None = None, models=None,
               picker: Callable[[str | None], list[str]] = pick_screenshots) -> FastAPI:
    """`models` is a BackgroundModels (started with the app when omitted); tests pass a stand-in."""
    state: AppState | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal state
        root = Path(home).expanduser().resolve() if home else snaprecall_home()
        state = AppState(root, models or BackgroundModels(load_config(root, create=False)), picker)
        app.state.snaprecall = state
        yield
        state.guests.delete_all_mine()

    app = FastAPI(title="SnapRecall", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    # ---- protections for a local server -----------------------------------------
    @app.middleware("http")
    async def protect(request: Request, call_next):
        host = request.headers.get("host", "")
        hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if hostname not in ALLOWED_HOSTS:
            return JSONResponse({"error": "SnapRecall only answers on this computer."}, status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-requested-with") != "SnapRecall":
                return JSONResponse({"error": "Request not allowed."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1] != host:
                return JSONResponse({"error": "Request not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "That request wasn't understood."}, status_code=422)

    # ---- dependencies --------------------------------------------------------------
    def session_of(request: Request) -> tuple[str | None, Session | None]:
        token = request.cookies.get(COOKIE)
        with state.lock:
            session = state.sessions.get(token) if token else None
            if session:
                session.last_seen = time.monotonic()
        return token, session

    def library(request: Request) -> Library:
        state.sweep_guests()
        _, session = session_of(request)
        if session is None or session.user is None:
            raise HTTPException(401, "Sign in first.")
        if session.user["kind"] == "guest" and not Path(session.user["dir"]).exists():
            raise HTTPException(401, "Your guest session ended, so its temporary library was deleted.")
        return Library(state, session)

    def enter(response: Response, user: dict) -> None:
        response.set_cookie(COOKIE, state.start_session(user), httponly=True, samesite="strict", path="/")

    def session_info(request: Request) -> dict:
        state.sweep_guests()
        _, session = session_of(request)
        user = session.user if session else None
        if user and user["kind"] == "guest" and not Path(user["dir"]).exists():
            user = None
        models_now = state.models
        return {
            "user": {"kind": user["kind"], "username": user["username"]} if user else None,
            "canClaimLegacy": state.accounts.count() == 0 and state.accounts.has_legacy_library(),
            "models": {
                "loading": not models_now.done,
                "ocr": models_now.ocr is not None, "visual": models_now.embedder is not None,
                "textMeaning": models_now.text_model is not None,
                "problems": models_now.problems if models_now.done else [],
            },
            "sortOptions": SORT_OPTIONS,
        }

    # ---- sign-in -----------------------------------------------------------------------
    @app.get("/api/session")
    def get_session(request: Request):
        return session_info(request)

    @app.post("/api/session/login")
    def login(body: Credentials, request: Request, response: Response):
        state.check_attempts(body.username)
        try:
            found = state.accounts.verify(body.username, body.password)
        except AccountError as exc:
            state.failed_attempt(body.username)
            raise HTTPException(401, str(exc)) from None
        state.failures.pop(body.username.lower(), None)
        enter(response, {"kind": "account", "id": found.id, "username": found.username,
                         "dir": str(state.accounts.user_dir(found))})
        return {"ok": True}

    @app.post("/api/session/register")
    def register(body: Registration, response: Response):
        try:
            if body.password != body.confirm:
                raise AccountError("The passwords don't match.")
            first = state.accounts.count() == 0
            created = state.accounts.create(body.username, body.password)
            if body.claimLegacy and first and state.accounts.has_legacy_library():
                state.accounts.claim_legacy_library(created)
        except AccountError as exc:
            raise HTTPException(400, str(exc)) from None
        enter(response, {"kind": "account", "id": created.id, "username": created.username,
                         "dir": str(state.accounts.user_dir(created))})
        return {"ok": True}

    @app.post("/api/session/guest")
    def guest(response: Response):
        token = secrets.token_hex(16)
        directory = state.guests.path_for(token)
        directory.mkdir(parents=True, exist_ok=True)
        with state.lock:
            state.sessions[token] = Session({"kind": "guest", "id": None, "username": "Guest", "dir": str(directory)})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
        return {"ok": True}

    @app.post("/api/session/logout")
    def logout(request: Request, response: Response):
        token, _ = session_of(request)
        if token:
            state.end_session(token)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/account/delete")
    def delete_account(body: Password, request: Request, response: Response, lib: Library = Depends(library)):
        if lib.user["kind"] != "account":
            raise HTTPException(400, "Guests have no account to delete.")
        try:
            state.accounts.delete(User(lib.user["id"], lib.user["username"]), body.password)
        except AccountError as exc:
            raise HTTPException(400, str(exc)) from None
        state.drop_library(lib.user["dir"])
        token, _ = session_of(request)
        with state.lock:
            state.sessions.pop(token, None)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    # ---- library and indexing ----------------------------------------------------------
    @app.get("/api/library")
    def get_library(lib: Library = Depends(library)):
        folders = lib.storage.list_folders()
        return {
            "folders": [{"path": f.path, "label": label_of(f.path), "count": f.image_count,
                         "individual": f.path == INDIVIDUAL, "lastScanAt": f.last_scan_at,
                         "scanComplete": f.last_scan_complete} for f in folders],
            "removedCount": len(lib.storage.removed_paths()),
            "indexDir": str(lib.config.index_dir),
            "guest": lib.user["kind"] == "guest",
            "username": lib.user["username"],
            "canClaimLegacy": lib.user["kind"] == "account" and state.accounts.has_legacy_library()
            and state.accounts.library_is_empty(User(lib.user["id"], lib.user["username"])),
        }

    @app.post("/api/library/open")
    def open_folder(body: FolderRef, lib: Library = Depends(library)):
        if body.folder and body.folder != ALL_FOLDERS:
            lib.storage.mark_opened(body.folder)
        return {"ok": True}

    @app.post("/api/library/pick")
    def pick(body: PickRequest, lib: Library = Depends(library)):
        """Open the window for choosing folders and screenshots on this computer."""
        try:
            chosen = state.picker(body.start)
        except FolderPickerError as exc:
            raise HTTPException(503, f"{exc} Please try again.") from None
        return {"folders": [p for p in chosen if Path(p).is_dir()],
                "files": [p for p in chosen if not Path(p).is_dir()]}

    @app.post("/api/library/index", status_code=202)
    def index(body: IndexRequest, lib: Library = Depends(library)):
        if not body.folders and not body.files:
            raise HTTPException(400, "Choose a folder or some screenshots to add.")
        job = state.jobs.submit(lib.storage, lib.config, body.folders, body.files)
        return job.snapshot()

    @app.post("/api/library/reindex", status_code=202)
    def reindex(body: FolderRef, lib: Library = Depends(library)):
        known = [f.path for f in lib.storage.list_folders()]
        targets = known if body.folder in (None, "", ALL_FOLDERS) else [body.folder]
        if not targets or any(t not in known for t in targets):
            raise HTTPException(404, "That folder isn't in your library.")
        return state.jobs.submit(lib.storage, lib.config, targets).snapshot()

    @app.post("/api/library/refresh", status_code=202)
    def refresh(body: FolderRef, lib: Library = Depends(library)):
        """Re-check the screenshots already indexed (labels, regions, changed files), without
        looking for new ones."""
        known = [f.path for f in lib.storage.list_folders()]
        targets = known if body.folder in (None, "", ALL_FOLDERS) else [body.folder]
        if not targets or any(t not in known for t in targets):
            raise HTTPException(404, "That folder isn't in your library.")
        return state.jobs.submit(lib.storage, lib.config, targets, refresh=True).snapshot()

    @app.post("/api/library/claim-legacy")
    def claim_legacy(lib: Library = Depends(library)):
        """Take over the library from before accounts existed (an account with an empty library only)."""
        if lib.user["kind"] != "account":
            raise HTTPException(400, "Sign in with an account to take over the earlier library.")
        if state.jobs.has_active(str(lib.config.index_dir)):
            raise HTTPException(409, "Wait for indexing to finish first.")
        try:
            state.accounts.claim_legacy_library(User(lib.user["id"], lib.user["username"]))
        except AccountError as exc:
            raise HTTPException(400, str(exc)) from None
        state.drop_library(lib.user["dir"])  # reopened from the moved files on the next request
        return {"ok": True}

    @app.post("/api/library/forget")
    def forget(body: FolderRef, lib: Library = Depends(library)):
        if body.folder not in [f.path for f in lib.storage.list_folders()]:
            raise HTTPException(404, "That folder isn't in your library.")
        forget_folder(body.folder, lib.storage, lib.config)
        return {"ok": True}

    @app.post("/api/library/delete-all")
    def delete_all(body: FolderRef, lib: Library = Depends(library)):
        shots = lib.records(body.folder)
        return {"removed": remove_screenshots([r.path for r in shots], lib.storage, lib.config)}

    @app.post("/api/library/restore-removed")
    def restore(lib: Library = Depends(library)):
        return {"restored": lib.storage.restore_removed()}

    @app.get("/api/jobs")
    def jobs(lib: Library = Depends(library)):
        listed = state.jobs.jobs_for(str(lib.config.index_dir))
        return {"active": [j.snapshot() for j in listed if j.active],
                "recent": [j.snapshot() for j in listed if not j.active][:5]}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, lib: Library = Depends(library)):
        job = state.jobs.get(job_id, str(lib.config.index_dir))
        if job is None:
            raise HTTPException(404, "That indexing run isn't known any more.")
        state.jobs.cancel(job)
        return job.snapshot()

    # ---- browsing and search -----------------------------------------------------------
    @app.get("/api/search")
    def find(q: str = "", folder: str = ALL_FOLDERS, when: str = "any", start: str | None = None,
             end: str | None = None, sort: str = BEST_MATCH, lib: Library = Depends(library)):
        visible = lib.records(folder)
        if not visible:
            return {"state": "empty", "results": [], "count": 0, "hidden": 0}
        first, last = date_range(when, start, end)
        pool = filter_by_date(visible, first, last)
        if not pool:
            return {"state": "no-dates", "results": [], "count": 0, "hidden": 0}
        everything = len(pool)
        pool, copies = group_duplicates(pool)
        hidden = everything - len(pool)
        sort = sort if sort in SORT_OPTIONS else BEST_MATCH
        m = state.models
        if q.strip():
            response = search(q, pool, m.embedder, visual_threshold=lib.config.visual_threshold,
                              text_model=m.text_model, meaning_threshold=lib.config.meaning_threshold)
            strong = {r.record.path: r.strong for r in response.results}
            shown = sort_records([r.record for r in response.results], sort)
            terms = query_terms(q)
            return {"state": "results" if shown else "no-match", "weak": response.weak,
                    "notice": response.notice, "hidden": hidden, "count": len(shown),
                    "results": [card(r, copies, terms, strong.get(r.path)) for r in shown]}
        order = "Date modified (newest)" if sort == BEST_MATCH else sort
        shown = sort_records(pool, order)[:BROWSE_LIMIT]
        return {"state": "browse", "order": order, "hidden": hidden, "count": len(shown),
                "total": len(pool), "results": [card(r, copies) for r in shown]}

    @app.get("/api/detail")
    def detail(path: str, folder: str = ALL_FOLDERS, lib: Library = Depends(library)):
        rec = lib.known(path)
        visible = lib.records(folder)
        embedder = state.models.embedder
        twins = identical_copies(rec, visible)
        similar_cards, similar_state = [], "none"
        if embedder is None:
            similar_state = "loading" if not state.models.done else "unavailable"
        elif rec.embed_model != embedder.name:
            similar_state = "unanalysed"
        else:
            candidates = [r for r in group_duplicates(visible)[0] if r.path == rec.path or not same_image(r, rec)]
            found = similar(rec, candidates, embedder.name)
            similar_cards = [card(m.record) for m in found]
            similar_state = "ok" if found else "none"
        return {
            "path": rec.path, "name": rec.name, "folder": str(Path(rec.path).parent),
            "width": rec.width, "height": rec.height, "size": rec.size, "mtimeMs": rec.mtime_ns // 10**6,
            "image": image_url(rec.path, "full", rec.mtime_ns // 10**9),
            "png": image_url(rec.path, "png", rec.mtime_ns // 10**9),
            "source": ({"app": rec.source_app, "confidence": describe_confidence(rec.source_confidence or 0)}
                       if rec.source_app else None),
            "tags": [label for label, _ in rec.tags or []],
            "ocrText": rec.ocr_text or "", "ocrQuality": ocr_quality(rec.ocr_confidence) if rec.ocr_text else None,
            "copies": [r.path for r in twins], "similarState": similar_state, "similar": similar_cards,
        }

    @app.get("/api/image")
    def image(path: str, kind: str = "thumb", v: int = 0, lib: Library = Depends(library)):
        rec = lib.known(path)
        if kind == "thumb":
            if rec.thumbnail and Path(rec.thumbnail).is_file():
                return FileResponse(rec.thumbnail, media_type="image/jpeg",
                                    headers={"Cache-Control": "private, max-age=86400"})
            raise HTTPException(404, "No preview is available.")
        if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS or not Path(path).is_file():
            raise HTTPException(404, "The original file is missing. It may have been moved or deleted.")
        if kind == "full":
            return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "image/png",
                                headers={"Cache-Control": "private, max-age=3600"})
        if kind == "png":
            try:
                return Response(clipboard_png(path), media_type="image/png")
            except CopyImageError as exc:
                raise HTTPException(409, str(exc)) from None
        raise HTTPException(400, "Unknown image kind.")

    # ---- actions on one screenshot -----------------------------------------------------
    @app.post("/api/screenshot/rename")
    def rename(body: RenameRequest, lib: Library = Depends(library)):
        lib.known(body.path)
        try:
            return {"path": rename_screenshot(body.path, body.name, lib.storage, lib.config)}
        except RenameError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/screenshot/delete")
    def delete(body: PathRef, lib: Library = Depends(library)):
        lib.known(body.path)
        remove_screenshots([body.path], lib.storage, lib.config)
        return {"ok": True}

    @app.post("/api/screenshot/open")
    def open_original(body: PathRef, lib: Library = Depends(library)):
        lib.known(body.path)
        try:
            open_file(body.path)
        except OSError as exc:
            raise HTTPException(400, f"Could not open the file: {exc}") from None
        return {"ok": True}

    # ---- the frontend -----------------------------------------------------------------------
    @app.get("/")
    def index_page():
        return FileResponse(STATIC / "index.html", media_type="text/html",
                            headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
