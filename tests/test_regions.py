import sqlite3

from PIL import Image

import indexer
from conftest import make_image
from fakes import FakeEmbedder
from indexer import image_regions, index_folder
from search import search
from storage import Storage


def chat_with_red_avatar(path):
    """A wide, mostly white 'chat message' with a small red avatar at the left edge."""
    image = Image.new("RGB", (560, 100), (245, 245, 245))
    image.paste((220, 30, 30), (10, 25, 60, 75))
    image.save(path)
    return path


def test_regions_cover_wide_and_large_screenshots():
    wide = image_regions(Image.new("RGB", (560, 100)))
    assert 2 <= len(wide) <= indexer.MAX_REGIONS and all(r.size == (100, 100) for r in wide)
    full = image_regions(Image.new("RGB", (1920, 1080)))
    assert {r.size for r in full} == {(1080, 1080), (540, 540)} and len(full) <= indexer.MAX_REGIONS
    assert image_regions(Image.new("RGB", (40, 30))) == []


def test_small_detail_is_found_through_its_region(env):
    shots, config, storage = env
    chat_with_red_avatar(shots / "chat.png")
    make_image(shots / "pinkish.png", (245, 200, 200), size=(560, 100))
    emb = FakeEmbedder()

    index_folder(shots, storage, config, embedder=emb)
    records = storage.folder_images(str(shots))
    chat = next(r for r in records if r.name == "chat.png")
    assert chat.region_embeddings.shape[1] == chat.embedding.size
    assert chat.region_model == indexer.region_model(emb)
    assert search("red", records, emb, mode="visual").results[0].record.name == "chat.png"

    # Without regions only the whole-image average counts, and the avatar is lost.
    plain = [r for r in records]
    for r in plain:
        r.region_embeddings = None
    assert search("red", plain, emb, mode="visual").results[0].record.name == "pinkish.png"


def test_regions_can_be_turned_off_and_are_added_later_without_redoing_ocr(env, tmp_path):
    shots, config, storage = env
    chat_with_red_avatar(shots / "chat.png")
    emb = FakeEmbedder()
    off = config.__class__(**{**config.__dict__, "enable_regions": False})

    index_folder(shots, storage, off, embedder=emb)
    assert storage.folder_images(str(shots))[0].region_embeddings is None
    assert index_folder(shots, storage, off, embedder=emb).processed == 0

    report = index_folder(shots, storage, config, embedder=emb)
    assert len(report.plan.retry) == 1
    assert storage.folder_images(str(shots))[0].region_embeddings is not None


def test_version_3_index_is_upgraded_in_place(tmp_path):
    db = tmp_path / "index.db"
    Storage(db)
    with sqlite3.connect(db) as conn:  # recreate a version-3 table without the new columns
        conn.execute("ALTER TABLE images DROP COLUMN region_embeddings")
        conn.execute("ALTER TABLE images DROP COLUMN region_model")
        for column in ("ocr_confidence", "source_app", "source_confidence", "source_evidence", "tags", "label_model"):
            conn.execute(f"ALTER TABLE images DROP COLUMN {column}")
        conn.execute("INSERT INTO images (path, size, mtime_ns) VALUES ('/s/a.png', 1, 1)")
        conn.execute("PRAGMA user_version = 3")

    storage = Storage(db)
    rec = storage.get("/s/a.png")
    assert rec is not None and rec.region_embeddings is None and rec.region_model is None
