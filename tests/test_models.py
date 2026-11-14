import threading

import numpy as np
import pytest
from PIL import Image

import fakes
from config import load_config
from models import BackgroundModels, ModelLoadError, embed_texts


def test_background_models_load_visual_first(tmp_path, monkeypatch):
    order = []
    release = threading.Event()

    def fake_embedder(config):
        order.append("embedder")
        return "embedder"

    def fake_ocr(config):
        release.wait(5)  # OCR still loading while search can already use the embedder
        order.append("ocr")
        return "ocr"

    loaded = BackgroundModels(load_config(tmp_path), in_process=True,
                              loaders={"embedder": fake_embedder, "ocr": fake_ocr})
    for _ in range(500):
        if loaded.embedder:
            break
        threading.Event().wait(0.01)
    assert loaded.embedder == "embedder" and loaded.ocr is None and not loaded.done
    release.set()
    assert loaded.wait(5)
    assert (loaded.ocr, order, loaded.problems) == ("ocr", ["embedder", "ocr"], [])


def test_background_models_report_failures_and_finish(tmp_path, monkeypatch):
    def broken(config):
        raise ModelLoadError("Visual search needs OpenCLIP.")

    def crashes(config):
        raise RuntimeError("weights corrupt")

    loaded = BackgroundModels(load_config(tmp_path), in_process=True,
                              loaders={"embedder": broken, "ocr": crashes})
    assert loaded.wait(5)  # a failure must never leave the app waiting
    assert loaded.embedder is None and loaded.ocr is None
    assert loaded.problems == ["Visual search needs OpenCLIP.", "A model failed to load (RuntimeError)."]


def test_disabled_models_are_not_loaded(tmp_path):
    loaded = BackgroundModels(load_config(tmp_path, enable_visual=False, enable_ocr=False))
    assert loaded.wait(5)
    assert (loaded.embedder, loaded.ocr, loaded.problems) == (None, None, [])


def test_models_in_helper_processes(tmp_path):
    """The real (default) path: each model runs in its own process and is called through a pipe."""
    loaded = BackgroundModels(load_config(tmp_path),
                              loaders={"embedder": fakes.load_fake_embedder, "ocr": fakes.load_failing_model})
    assert loaded.wait(60)
    emb = loaded.embedder
    assert emb.name == fakes.FakeEmbedder().name
    image = Image.new("RGB", (40, 30), fakes.COLORS["red"])
    local = fakes.FakeEmbedder()
    np.testing.assert_allclose(emb.embed_image(image), local.embed_image(image))
    np.testing.assert_allclose(embed_texts(emb, ["red", "blue"]), embed_texts(local, ["red", "blue"]))
    assert loaded.ocr is None and loaded.problems == ["Fake model refused to load."]
    with pytest.raises(AttributeError):
        emb.not_a_model_method  # noqa: B018
    emb._process.kill()
    emb._process.wait(10)
    with pytest.raises(RuntimeError, match="stopped"):
        emb.embed_text("red")


def test_helper_process_exits_when_app_goes_away(tmp_path):
    loaded = BackgroundModels(load_config(tmp_path, enable_ocr=False),
                              loaders={"embedder": fakes.load_fake_embedder})
    assert loaded.wait(60)
    process = loaded.embedder._process
    process.stdin.close()  # what happens when SnapRecall stops or crashes
    assert process.wait(10) == 0


def test_load_config_without_creating_folders(tmp_path):
    load_config(tmp_path / "home", create=False)
    assert not (tmp_path / "home").exists()
