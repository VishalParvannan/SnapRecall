"""Background indexing jobs (index_jobs.py) and cancelling an indexing run."""
import threading
import time

import pytest

from conftest import make_image
from fakes import FakeEmbedder, FakeOcr
from index_jobs import IndexJobs
from indexer import INDIVIDUAL, index_folder


class Models:
    """Stands in for BackgroundModels: always loaded unless `loaded` is cleared."""

    def __init__(self, ocr=None, embedder=None):
        self.ocr, self.embedder = ocr, embedder
        self.loaded = threading.Event()
        self.loaded.set()

    def wait(self, timeout=None):
        return self.loaded.wait(timeout)


class BlockingOcr(FakeOcr):
    """Pauses inside the first image until released, so a test can act mid-run."""

    def __init__(self):
        super().__init__({"red": "red text"})
        self.started, self.proceed = threading.Event(), threading.Event()

    def extract(self, image):
        self.started.set()
        self.proceed.wait(10)
        return super().extract(image)


def wait_until(condition, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def add_images(folder, count):
    return [make_image(folder / f"s{i}.png", color=(220, 30, 30 + i)) for i in range(count)]


def test_job_indexes_in_the_background(env):
    shots, config, storage = env
    add_images(shots, 3)
    jobs = IndexJobs(Models(FakeOcr({"red": "red text"}), FakeEmbedder()))
    job = jobs.submit(storage, config, folders=[str(shots)])
    assert wait_until(lambda: not job.active)
    assert (job.state, job.processed, job.problems) == ("done", 3, [])
    assert len(storage.folder_images(str(shots))) == 3
    snap = job.snapshot()
    assert snap["state"] == "done" and snap["done"] == snap["total"] == 3 and not snap["active"]


def test_cancel_stops_before_the_next_image_and_keeps_progress(env):
    shots, config, storage = env
    add_images(shots, 3)
    ocr = BlockingOcr()
    jobs = IndexJobs(Models(ocr))
    job = jobs.submit(storage, config, folders=[str(shots)])
    assert ocr.started.wait(10)
    jobs.cancel(job)
    assert job.snapshot()["cancelRequested"]
    ocr.proceed.set()
    assert wait_until(lambda: not job.active)
    assert job.state == "cancelled" and job.processed == 1
    assert len(storage.folder_images(str(shots))) == 1  # the image in progress was saved
    info = storage.list_folders()[0]
    assert info.last_scan_at is None  # an unfinished scan isn't recorded as a scan
    # A later run continues with the rest and doesn't redo the first image.
    ocr.calls = 0
    again = jobs.submit(storage, config, folders=[str(shots)])
    assert wait_until(lambda: not again.active)
    assert again.state == "done" and again.processed == 2 and ocr.calls == 2
    assert len(storage.folder_images(str(shots))) == 3


def test_cancelled_scan_never_removes_missing_files(env):
    shots, config, storage = env
    files = add_images(shots, 2)
    ocr = FakeOcr({"red": "red text"})
    index_folder(shots, storage, config, ocr)
    files[0].unlink()
    make_image(shots / "new.png", color=(220, 30, 99))
    report = index_folder(shots, storage, config, ocr, cancel=lambda: True)
    assert report.cancelled and report.removed == 0
    assert len(storage.folder_images(str(shots))) == 2  # the deleted file's record is kept for now


def test_queued_job_can_be_cancelled_before_it_starts(env):
    shots, config, storage = env
    add_images(shots, 1)
    other = shots.parent / "other"
    add_images(other, 1)
    ocr = BlockingOcr()
    jobs = IndexJobs(Models(ocr))
    first = jobs.submit(storage, config, folders=[str(shots)])
    assert ocr.started.wait(10)
    second = jobs.submit(storage, config, folders=[str(other)])
    assert second.state == "queued"
    jobs.cancel(second)
    assert second.state == "cancelled" and not second.active
    ocr.proceed.set()
    assert wait_until(lambda: not first.active)
    assert first.state == "done" and storage.folder_images(str(other)) == []
    assert str(other) not in [f.path for f in storage.list_folders()]


def test_job_waits_for_models_and_can_be_cancelled_while_waiting(env):
    shots, config, storage = env
    add_images(shots, 1)
    models = Models(FakeOcr({"red": "red text"}))
    models.loaded.clear()
    jobs = IndexJobs(models)
    waiting = jobs.submit(storage, config, folders=[str(shots)])
    assert wait_until(lambda: waiting.state == "waiting")
    models.loaded.set()
    assert wait_until(lambda: not waiting.active) and waiting.state == "done" and waiting.processed == 1

    models.loaded.clear()
    stopped = jobs.submit(storage, config, folders=[str(shots)])
    assert wait_until(lambda: stopped.state == "waiting")
    jobs.cancel(stopped)
    assert wait_until(lambda: not stopped.active) and stopped.state == "cancelled"


def test_problems_are_reported_and_do_not_stop_other_targets(env):
    shots, config, storage = env
    add_images(shots, 1)
    jobs = IndexJobs(Models(FakeOcr({"red": "red text"})))
    job = jobs.submit(storage, config, folders=[str(shots.parent / "missing"), str(shots)])
    assert wait_until(lambda: not job.active)
    assert job.state == "done" and job.processed == 1
    assert len(job.problems) == 1 and "missing" in job.problems[0]


def test_individual_files_are_one_extra_target(env):
    shots, config, storage = env
    (picked,) = add_images(shots / "pics", 1)
    jobs = IndexJobs(Models(FakeOcr({"red": "red text"})))
    job = jobs.submit(storage, config, folders=[], files=[str(picked), str(shots / "notes.txt")])
    assert wait_until(lambda: not job.active)
    assert job.processed == 1 and job.target == INDIVIDUAL and job.target_count == 1
    assert [m for _, m in job.failed] == ["Not a PNG or JPEG image"]
    assert [r.path for r in storage.folder_images(INDIVIDUAL)] == [str(picked.resolve())]


def test_jobs_are_listed_per_library_and_old_ones_forgotten(env):
    shots, config, storage = env
    jobs = IndexJobs(Models(FakeOcr({})))
    submitted = [jobs.submit(storage, config, folders=[]) for _ in range(25)]
    assert wait_until(lambda: not jobs.has_active(str(config.index_dir)))
    listed = jobs.jobs_for(str(config.index_dir))
    assert listed[0] is submitted[-1] and len(listed) <= 21
    assert jobs.jobs_for("another library") == []
    assert jobs.get(submitted[-1].id, "another library") is None
    assert jobs.get(submitted[-1].id) is submitted[-1]


@pytest.mark.parametrize("cancel_first", [True, False])
def test_cancel_callback_is_optional(env, cancel_first):
    shots, config, storage = env
    add_images(shots, 2)
    report = index_folder(shots, storage, config, FakeOcr({}), cancel=(lambda: True) if cancel_first else None)
    assert report.cancelled is cancel_first
    assert report.processed == (0 if cancel_first else 2)
