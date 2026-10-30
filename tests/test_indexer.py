import os
from pathlib import Path

import pytest

import indexer
from conftest import bump_mtime, make_image
from fakes import FakeEmbedder, FakeOcr
from indexer import forget_folder, index_folder, plan_scan, remove_thumbnail
from storage import Storage


def names(records):
    return {Path(r.path).name for r in records}


def test_indexes_supported_images_only(env):
    shots, config, storage = env
    make_image(shots / "a.png")
    make_image(shots / "sub" / "b.JPG")
    (shots / "notes.txt").write_text("x")

    report = index_folder(shots, storage, config)

    assert report.processed == 2
    recs = storage.folder_images(str(shots))
    assert names(recs) == {"a.png", "b.JPG"}
    assert all(Path(r.thumbnail).exists() for r in recs)


def test_reindex_skips_unchanged_and_detects_changes(env):
    shots, config, storage = env
    a = make_image(shots / "a.png")
    b = make_image(shots / "b.png")
    index_folder(shots, storage, config)

    make_image(a, (30, 60, 220))
    bump_mtime(a)
    b.unlink()
    make_image(shots / "c.png")

    plan = plan_scan(shots, storage)
    assert [p.name for p in plan.changed] == ["a.png"]
    assert [p.name for p in plan.new] == ["c.png"]
    assert [Path(p).name for p in plan.missing] == ["b.png"]

    report = index_folder(shots, storage, config)
    assert report.processed == 2 and report.removed == 1
    assert storage.get(str(shots / "b.png")) is None
    assert plan_scan(shots, storage).to_process == []


def test_corrupt_image_is_reported_and_retried(env):
    shots, config, storage = env
    broken = shots / "broken.png"
    broken.write_bytes(b"not an image")
    make_image(shots / "ok.png")

    report = index_folder(shots, storage, config)
    assert report.processed == 1
    assert [Path(p).name for p, _ in report.failed] == ["broken.png"]
    assert storage.get(str(broken)).thumbnail is None

    # Unchanged fingerprint, but a failed item is retried on the next scan.
    assert [p.name for p in plan_scan(shots, storage).retry] == ["broken.png"]


def test_originals_are_not_modified(env):
    shots, config, storage = env
    a = make_image(shots / "a.png")
    before = (a.read_bytes(), a.stat().st_mtime_ns)
    index_folder(shots, storage, config, FakeOcr({}), FakeEmbedder())
    assert (a.read_bytes(), a.stat().st_mtime_ns) == before


def test_missing_folder_raises(env):
    _, config, storage = env
    with pytest.raises(NotADirectoryError):
        index_folder("does/not/exist", storage, config)


# ---- overlapping folders --------------------------------------------------

@pytest.mark.parametrize("parent_first", [True, False])
def test_overlapping_folders_keep_membership(env, parent_first):
    shots, config, storage = env
    child = shots / "child"
    make_image(shots / "top.png")
    make_image(child / "inner.png")

    for folder in ([shots, child] if parent_first else [child, shots]):
        index_folder(folder, storage, config)

    assert names(storage.folder_images(str(shots))) == {"top.png", "inner.png"}
    assert names(storage.folder_images(str(child))) == {"inner.png"}

    # Removing one root must not affect the other.
    forget_folder(str(child), storage, config)
    assert names(storage.folder_images(str(shots))) == {"top.png", "inner.png"}
    inner = storage.get(str(child / "inner.png"))
    assert inner is not None and Path(inner.thumbnail).exists()

    forget_folder(str(shots), storage, config)
    assert storage.get(str(child / "inner.png")) is None
    assert not Path(inner.thumbnail).exists()
    assert (child / "inner.png").exists()  # originals untouched


def test_file_deleted_in_child_is_removed_only_from_scanned_folder(env):
    shots, config, storage = env
    child = shots / "child"
    inner = make_image(child / "inner.png")
    index_folder(shots, storage, config)
    index_folder(child, storage, config)

    inner.unlink()
    index_folder(child, storage, config)
    assert storage.folder_images(str(child)) == []
    # The parent still lists it until the parent is rescanned.
    assert names(storage.folder_images(str(shots))) == {"inner.png"}
    index_folder(shots, storage, config)
    assert storage.folder_images(str(shots)) == []


# ---- resilience -----------------------------------------------------------

def test_unreadable_subfolder_does_not_remove_records(env, monkeypatch):
    shots, config, storage = env
    make_image(shots / "a.png")
    b = make_image(shots / "b.png")
    index_folder(shots, storage, config)
    b.unlink()

    real_walk = os.walk

    def walk_with_error(top, onerror=None, **kw):
        onerror(PermissionError(13, "Permission denied", str(Path(top) / "locked")))
        yield from real_walk(top, onerror=onerror, **kw)

    monkeypatch.setattr(indexer.os, "walk", walk_with_error)
    report = index_folder(shots, storage, config)

    assert not report.plan.complete
    assert report.plan.errors[0][1] == "Permission denied"
    assert report.removed == 0
    assert names(storage.folder_images(str(shots))) == {"a.png", "b.png"}
    assert storage.list_folders()[0].last_scan_complete is False


def test_file_disappearing_during_scan_is_reported(env):
    shots, config, storage = env
    make_image(shots / "a.png")
    make_image(shots / "b.png")

    def progress(i, total, name):
        if name == "b.png":
            (shots / "b.png").unlink()

    report = index_folder(shots, storage, config, progress=progress)

    assert report.processed == 1
    assert report.failed == [(str(shots / "b.png"), "No longer exists")]
    assert names(storage.folder_images(str(shots))) == {"a.png"}


def test_interrupted_indexing_keeps_progress(env):
    shots, config, storage = env
    for n in range(3):
        make_image(shots / f"{n}.png")

    def stop_after_first(i, total, name):
        if i == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        index_folder(shots, storage, config, progress=stop_after_first)

    plan = plan_scan(shots, storage)
    assert [p.name for p in plan.unchanged] == ["0.png"]
    assert [p.name for p in plan.new] == ["1.png", "2.png"]


def test_thumbnail_removal_is_limited_to_index(env, tmp_path):
    _, config, _ = env
    outside = tmp_path / "keep.jpg"
    outside.write_bytes(b"x")
    remove_thumbnail(config, outside)
    assert outside.exists()


# ---- models ---------------------------------------------------------------

def test_ocr_and_embedding_saved_and_reused(env):
    shots, config, storage = env
    make_image(shots / "a.png")
    ocr, emb = FakeOcr({"red": "Connection refused"}), FakeEmbedder()
    index_folder(shots, storage, config, ocr, emb)

    rec = storage.get(str(shots / "a.png"))
    assert rec.ocr_text == "Connection refused" and rec.ocr_model == ocr.name
    assert rec.embed_model == emb.name and rec.embedding.shape == (3,)

    index_folder(shots, storage, config, ocr, emb)
    assert ocr.calls == 1 and emb.calls == 1


def test_model_change_triggers_reprocessing(env):
    shots, config, storage = env
    make_image(shots / "a.png")
    index_folder(shots, storage, config, FakeOcr({}), FakeEmbedder())

    new_emb = FakeEmbedder(name="fake-clip-2")
    ocr = FakeOcr({})
    plan = plan_scan(shots, storage, ocr, new_emb)
    assert [p.name for p in plan.retry] == ["a.png"]

    index_folder(shots, storage, config, ocr, new_emb)
    assert storage.get(str(shots / "a.png")).embed_model == "fake-clip-2"
    assert ocr.calls == 0  # OCR result was still valid


def test_failed_ocr_is_partial_and_retried(env):
    shots, config, storage = env
    make_image(shots / "a.png")
    report = index_folder(shots, storage, config, FakeOcr({}, fail=True), FakeEmbedder())

    rec = storage.get(str(shots / "a.png"))
    assert rec.status == "partial" and rec.ocr_model is None
    assert rec.embedding is not None
    assert report.failed[0][1] == "Text recognition failed"

    ocr = FakeOcr({"red": "hello"})
    index_folder(shots, storage, config, ocr, FakeEmbedder())
    rec = storage.get(str(shots / "a.png"))
    assert rec.status == "ok" and rec.ocr_text == "hello"


# ---- persistence ----------------------------------------------------------

def test_index_and_folders_persist_across_restarts(env):
    shots, config, storage = env
    other = shots.parent / "other"
    make_image(shots / "a.png")
    make_image(other / "b.png")
    index_folder(shots, storage, config)
    index_folder(other, storage, config)
    storage.mark_opened(str(shots))

    reopened = Storage(config.db_path)
    folders = reopened.list_folders()
    assert {f.path for f in folders} == {str(shots), str(other)}
    assert folders[0].image_count == 1 and folders[0].last_scan_complete is True
    assert plan_scan(shots, reopened).to_process == []


def test_folder_images_are_ordered_newest_first(env):
    shots, config, storage = env
    for i, name in enumerate(["c.png", "a.png", "b.png"]):
        p = make_image(shots / name)
        os.utime(p, ns=(1_000_000_000 * (i + 1),) * 2)
    index_folder(shots, storage, config)
    assert [r.name for r in storage.folder_images(str(shots))] == ["b.png", "a.png", "c.png"]


def test_outdated_schema_is_rebuilt(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE images (path TEXT PRIMARY KEY, folder TEXT)")
    conn.commit()
    conn.close()
    storage = Storage(db)
    assert storage.list_folders() == []


def test_version_2_index_is_upgraded_without_losing_data(env):
    import sqlite3
    shots, config, storage = env
    make_image(shots / "a.png")
    index_folder(shots, storage, config, FakeOcr({"red": "hello"}))
    conn = sqlite3.connect(config.db_path)
    conn.executescript("""
        CREATE TABLE images_v2 AS SELECT path, size, mtime_ns, width, height, thumbnail, status, error,
            ocr_text, ocr_model, embedding, embed_model, embed_dim, indexed_at FROM images;
        DROP TABLE folder_images; DROP TABLE images; ALTER TABLE images_v2 RENAME TO images;
        CREATE TABLE folders_v2 AS SELECT path, added_at, last_opened_at, last_scan_at,
            last_scan_complete FROM folders;
        DROP TABLE folders; ALTER TABLE folders_v2 RENAME TO folders;
        CREATE TABLE folder_images (folder TEXT, image TEXT, PRIMARY KEY (folder, image));
        PRAGMA user_version = 2;
    """)
    conn.execute("INSERT INTO folder_images VALUES (?, ?)", (str(shots), str(shots / "a.png")))
    conn.commit()
    conn.close()

    upgraded = Storage(config.db_path)
    rec = upgraded.get(str(shots / "a.png"))
    assert rec.ocr_text == "hello" and rec.sha256 is None
    assert upgraded.list_folders()[0].backup is False


def test_all_images_lists_each_image_once(env):
    shots, config, storage = env
    make_image(shots / "top.png")
    make_image(shots / "child" / "inner.png")
    index_folder(shots, storage, config)
    index_folder(shots / "child", storage, config)
    assert sorted(r.name for r in storage.all_images()) == ["inner.png", "top.png"]
    forget_folder(str(shots), storage, config)
    assert [r.name for r in storage.all_images()] == ["inner.png"]
