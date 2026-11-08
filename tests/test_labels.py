import numpy as np
from PIL import Image

import labels
from conftest import make_image
from fakes import FakeEmbedder, FakeOcr
from indexer import index_folder
from labels import APPS, compute_labels, text_evidence
from models import normalize

APP_INDEX = {app.name: i for i, app in enumerate(APPS)}


class PromptEmbedder:
    """Text: one direction per known app prompt, plus a generic direction for everything else.
    Images: whatever vector the test puts in."""

    name = "prompt-test"

    def __init__(self):
        self.dim = len(APPS) + 2

    def embed_text(self, text):
        v = np.zeros(self.dim)
        for i, app in enumerate(APPS):
            if text in app.prompts:
                v[i] = 1.0
                return v
        v[-1] = 1.0
        return v

    def looks_like(self, app_name, strength=0.05):  # similarity ~0.05 above the rest: probability ~0.7
        v = np.zeros(self.dim)
        v[APP_INDEX[app_name]] = strength
        v[-2] = 1.0  # the rest of the image matches nothing in particular
        return normalize(v)


def test_source_stays_unknown_without_evidence():
    result = compute_labels("Spaghetti al pomodoro, 6 ripe tomatoes")
    assert result.source_app is None and result.source_confidence is None


def test_interface_text_identifies_the_app():
    result = compute_labels("alex  Today at 6:58 PM\nyo peanut brain\nMessage @alex")
    assert result.source_app == "Discord" and result.source_evidence == "text"
    assert 0.5 <= result.source_confidence < 0.8


def test_mentioning_an_app_is_only_weak_evidence():
    assert compute_labels("I sent it to you on Discord yesterday").source_app is None
    assert text_evidence(APPS[APP_INDEX["Discord"]], "see you on discord") == labels.NAME_MENTION


def test_wording_shared_by_two_apps_is_ambiguous():
    # Both Discord and Slack show "Message #general" in their message box.
    assert compute_labels("Message #general").source_app is None


def test_interface_look_identifies_the_app_and_breaks_ties():
    emb = PromptEmbedder()
    looks = compute_labels("", emb, emb.looks_like("Discord"))
    assert looks.source_app == "Discord" and looks.source_evidence == "interface"
    both = compute_labels("Message #general", emb, emb.looks_like("Slack"))
    assert both.source_app == "Slack" and both.source_evidence == "interface, text"
    assert both.source_confidence > looks.source_confidence


def test_filename_is_never_evidence(env):
    shots, config, storage = env
    make_image(shots / "discord_screenshot.png", (220, 30, 30))
    index_folder(shots, storage, config, FakeOcr({"red": "Spaghetti recipe"}), FakeEmbedder())
    rec = storage.folder_images(str(shots))[0]
    assert rec.source_app is None and rec.label_model == labels.label_model(FakeEmbedder())


def test_labels_are_stored_and_recomputed_without_redoing_ocr(env, monkeypatch):
    shots, config, storage = env
    make_image(shots / "a.png", (220, 30, 30))
    ocr = FakeOcr({"red": "Windows PowerShell\nPS C:\\Users\\sam> npm run build"})
    index_folder(shots, storage, config, ocr)
    rec = storage.folder_images(str(shots))[0]
    assert rec.source_app == "PowerShell" and rec.ocr_confidence == 0.9
    assert ocr.calls == 1

    monkeypatch.setattr(labels, "LABELS_VERSION", "labels-test")
    report = index_folder(shots, storage, config, ocr)
    assert len(report.plan.retry) == 1 and ocr.calls == 1  # only labels were redone
    assert storage.folder_images(str(shots))[0].label_model.startswith("labels-test")


def test_tags_need_a_clear_match(tmp_path):
    class FireTags:
        name = "fire-tags"

        def embed_text(self, text):
            if "fire" in text or "flames" in text:
                return normalize(np.array([1.0, 0.0, 0.0]))
            return normalize(np.array([0.0, 0.0, 1.0]))

    interface = normalize(np.array([0.0, 0.3, 1.0]))  # looks like "just an interface"
    flames = normalize(np.array([1.0, 0.0, 0.05]))
    labels._CLASS_CACHE.clear()
    assert compute_labels("", FireTags(), interface, cache_dir=tmp_path).tags == []
    tags = compute_labels("", FireTags(), flames, cache_dir=tmp_path).tags
    assert tags and tags[0][0] == "fire"
    # The prompt vectors were saved, so a fresh process reuses them instead of re-embedding.
    assert list(tmp_path.glob("label_prompts_*.npz"))
    labels._CLASS_CACHE.clear()
    assert compute_labels("", FireTags(), flames, cache_dir=tmp_path).tags == tags
