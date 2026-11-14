"""Background indexing jobs.

Indexing takes seconds per screenshot, so it runs on a worker thread of the app's own process
instead of inside a web request: closing the tab or reloading the page doesn't stop it, the
interface stays usable, and it can be watched (`snapshot`) and cancelled.

One worker handles one job at a time (indexing already uses the CPU fully), in the order they were
submitted. A job waits for the models to finish loading first, because screenshots indexed
without them would be stored with no text or visual data.

Cancelling stops before the next screenshot. Everything already processed is kept, and the next
scan continues from there (see `indexer._index`).
"""
from __future__ import annotations

import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from config import Config
from indexer import INDIVIDUAL, IndexReport, index_files, index_folder, refresh_folder
from storage import Storage

KEEP_FINISHED = 20  # finished jobs remembered, for the "last run" summary


class ModelsLike(Protocol):
    """What a job needs from BackgroundModels (tests pass a small stand-in)."""
    ocr: Any
    embedder: Any

    def wait(self, timeout: float | None = None) -> bool: ...


@dataclass
class Job:
    id: str
    library: str  # which library it belongs to (its index folder)
    folders: list[str]
    files: list[str]
    refresh: bool = False  # re-check what is already indexed instead of scanning for new screenshots
    state: str = "queued"  # queued | waiting | running | done | cancelled | failed
    target: str = ""  # folder (or INDIVIDUAL) being indexed now
    target_number: int = 0
    target_count: int = 0
    done: int = 0  # screenshots processed in the current target
    total: int = 0  # screenshots to process in the current target
    current: str = ""  # name of the screenshot being processed
    processed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    removed: int = 0
    problems: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def active(self) -> bool:
        return self.state in ("queued", "waiting", "running")

    def snapshot(self) -> dict:
        return {
            "id": self.id, "state": self.state, "active": self.active, "refresh": self.refresh,
            "target": self.target, "targetNumber": self.target_number, "targetCount": self.target_count,
            "done": self.done, "total": self.total, "current": self.current,
            "processed": self.processed, "failed": [{"path": p, "message": m} for p, m in self.failed],
            "removed": self.removed, "problems": list(self.problems),
            "cancelRequested": self.cancel.is_set(), "finishedAt": self.finished_at,
        }


class IndexJobs:
    def __init__(self, models: ModelsLike):
        self.models = models
        self._jobs: list[Job] = []
        self._queue: queue.Queue[tuple[Job, Storage, Config]] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # ---- submitting and watching -------------------------------------------
    def submit(self, storage: Storage, config: Config, folders: list[str] | None = None,
               files: list[str] | None = None, refresh: bool = False) -> Job:
        """Queue indexing of `folders` (with subfolders) and/or individually chosen `files`.
        Files are indexed as one extra target, after the folders. With `refresh`, the screenshots
        already in `folders` are re-checked instead and nothing new is looked for (see
        indexer.refresh_folder)."""
        job = Job(secrets.token_hex(8), str(config.index_dir), list(folders or []), list(files or []), refresh)
        with self._lock:
            self._jobs.append(job)
            self._forget_old()
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="snaprecall-indexing", daemon=True)
                self._worker.start()
        self._queue.put((job, storage, config))
        return job

    def jobs_for(self, library: str) -> list[Job]:
        """The library's jobs, newest first."""
        with self._lock:
            return [j for j in reversed(self._jobs) if j.library == library]

    def get(self, job_id: str, library: str | None = None) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs if j.id == job_id and (library is None or j.library == library)), None)

    def cancel(self, job: Job) -> None:
        """Ask a job to stop. A queued job is cancelled at once; a running one after its current image."""
        job.cancel.set()
        with self._lock:
            if job.state == "queued":
                job.state, job.finished_at = "cancelled", time.time()

    def has_active(self, library: str) -> bool:
        return any(j.active for j in self.jobs_for(library))

    def _forget_old(self) -> None:
        finished = [j for j in self._jobs if not j.active]
        for job in finished[:-KEEP_FINISHED]:
            self._jobs.remove(job)

    # ---- the worker ----------------------------------------------------------
    def _run(self) -> None:
        while True:
            job, storage, config = self._queue.get()
            if job.state == "cancelled":  # cancelled while queued
                continue
            try:
                self._execute(job, storage, config)
            except Exception as exc:  # never let one job kill the worker
                job.problems.append(f"Indexing stopped unexpectedly ({exc.__class__.__name__}).")
                job.state = "failed"
            finally:
                job.finished_at = time.time()
                if job.state in ("queued", "waiting", "running"):
                    job.state = "done"
                with self._lock:
                    self._forget_old()

    def _execute(self, job: Job, storage: Storage, config: Config) -> None:
        job.state = "waiting"
        # Wait for the models in short steps so a cancel is noticed.
        while not self.models.wait(0.25):
            if job.cancel.is_set():
                job.state = "cancelled"
                return
        job.state = "running"
        targets = [(folder, False) for folder in job.folders] + ([(INDIVIDUAL, True)] if job.files else [])
        job.target_count = len(targets)
        for number, (target, is_files) in enumerate(targets, start=1):
            if job.cancel.is_set():
                break
            job.target, job.target_number, job.done, job.total, job.current = target, number, 0, 0, ""

            def progress(i: int, total: int, name: str) -> None:
                job.done, job.total, job.current = i - 1, total, name  # i is the image starting now

            try:
                args = (storage, config, self.models.ocr, self.models.embedder, progress, job.cancel.is_set)
                if is_files:
                    report = index_files(job.files, *args)
                else:
                    report = (refresh_folder if job.refresh else index_folder)(target, *args)
            except (OSError, ValueError) as exc:
                job.problems.append(f"{target}: {exc}")
                continue
            self._add(job, report)
            job.done, job.current = job.total, ""
        job.state = "cancelled" if job.cancel.is_set() else "done"

    @staticmethod
    def _add(job: Job, report: IndexReport) -> None:
        job.processed += report.processed
        job.removed += report.removed
        job.failed += report.failed
        job.failed += [(path, message) for path, message in report.plan.errors]
