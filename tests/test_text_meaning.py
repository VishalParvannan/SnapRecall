"""Matching a query with the meaning of recognized text (search.meaning_scores and its fusion)."""
import numpy as np

from config import load_config
from fakes import FakeEmbedder, color_vector
from models import BackgroundModels, load_text_model, normalize
from search import search
from storage import ImageRecord

# Words that belong together, as a sentence-similarity model would place them.
TOPICS = {
    "travel": {"plane", "airplane", "airport", "departures", "gates", "baggage", "flight"},
    "chemistry": {"h2o", "molecule", "reaction", "ch3br"},
    "cooking": {"pasta", "tomato", "recipe"},
}


class FakeTextModel:
    """Embeds a text as the topics of the words it contains; unknown words mean nothing."""

    name = "fake-meaning-1"

    def __init__(self, fail=False):
        self.fail = fail

    def embed_texts(self, texts):
        if self.fail:
            raise RuntimeError("simulated failure")
        rows = []
        for text in texts:
            words = set(text.lower().replace(",", " ").split())
            rows.append(normalize(np.array([float(len(words & t)) for t in TOPICS.values()])))
        return np.stack(rows)

    def embed_text(self, text):
        return self.embed_texts([text])[0]


EMB = FakeEmbedder()


def rec(name, text="", color=None):
    r = ImageRecord(path=f"/shots/{name}", size=1, mtime_ns=1, ocr_text=text)
    if color is not None:
        r.embedding = color_vector(color)
        r.embed_model = EMB.name
    return r


def names(response, n=3):
    return [r.record.name for r in response.results[:n]]


# A line drawing that looks "close" to every query (the image-text model can't tell it apart), listed
# first, and a screenshot about travel whose text never says "plane". The query has no colour words,
# so the stand-in image model finds nothing and its ties are broken by order: the hub wins visually.
HUB = rec("a_diagram.png", "H2O reaction", (200, 200, 200))
AIRPORT = rec("b_comic.png", "Departures Gates Baggage", (200, 190, 180))
OTHERS = [rec(f"c_{i}.png", "pasta recipe", (210, 200, 190)) for i in range(3)]


def test_visual_hub_wins_without_the_meaning_channel():
    # Documents the failure this channel exists for.
    assert names(search("plane", [HUB, AIRPORT, *OTHERS], EMB), 1) == ["a_diagram.png"]


def test_related_text_beats_a_visual_hub():
    response = search("plane", [HUB, AIRPORT, *OTHERS], EMB, text_model=FakeTextModel())
    assert names(response, 1) == ["b_comic.png"]
    assert response.results[0].meaning_score is not None and response.results[0].text_score == 0


def test_a_clear_visual_winner_is_not_overtaken_by_related_text():
    # Found on samples/eval: one weakly related text used to jump ahead of an obvious visual match.
    red = rec("e_red.png", "", (220, 30, 30))
    related = rec("a_travel.png", "Departures Gates Baggage", (200, 190, 180))
    filler = [rec(f"f_{i}.png", "pasta recipe", (200, 150 + i, 150)) for i in range(5)]
    response = search("red plane", [related, red, *filler], EMB, text_model=FakeTextModel(), visual_threshold=0.29)
    assert names(response, 1) == ["e_red.png"]
    assert response.results[0].strong


def test_meaning_alone_never_makes_a_strong_match():
    response = search("plane", [HUB, AIRPORT], EMB, text_model=FakeTextModel())
    assert response.weak and not any(r.strong for r in response.results)


def test_works_without_an_image_model():
    response = search("flight", [HUB, AIRPORT, *OTHERS], text_model=FakeTextModel())
    assert names(response, 1) == ["b_comic.png"]


def test_unrelated_query_adds_nothing():
    response = search("giraffe", [HUB, AIRPORT, *OTHERS], EMB, text_model=FakeTextModel())
    assert all(r.meaning_score is None for r in response.results)
    assert names(response) == names(search("giraffe", [HUB, AIRPORT, *OTHERS], EMB))


def test_threshold_controls_what_counts_as_related():
    # "airport tomato" is half travel, half cooking: similarity to the airport text is about 0.7.
    loose = search("airport tomato", [AIRPORT], text_model=FakeTextModel(), meaning_threshold=0.5)
    strict = search("airport tomato", [AIRPORT], text_model=FakeTextModel(), meaning_threshold=0.9)
    assert loose.results[0].meaning_score is not None
    assert strict.results == [] or strict.results[0].meaning_score is None


def test_exact_words_still_beat_related_meaning():
    exact = rec("d_exact.png", "my plane ticket", (30, 30, 30))
    response = search("plane", [AIRPORT, exact], EMB, text_model=FakeTextModel())
    assert names(response, 1) == ["d_exact.png"]


def test_failing_model_falls_back_to_text_matches_with_a_notice():
    exact = rec("d_exact.png", "my plane ticket", (30, 30, 30))
    response = search("plane", [AIRPORT, exact], EMB, text_model=FakeTextModel(fail=True))
    assert names(response, 1) == ["d_exact.png"]
    assert response.notice and "meaning" in response.notice


def test_without_the_model_the_image_text_encoder_is_used():
    class ClipLike:
        name = "clip-like"

        def embed_text(self, text):
            return np.array([1.0, 0.0]) if text.lower() in ("glad", "happy") else np.array([0.0, 1.0])

    records = [rec("one.png", "happy"), rec("two.png", "water")]
    assert names(search("glad", records, ClipLike()), 1) == ["one.png"]


def test_setting_and_loading(tmp_path, monkeypatch):
    assert load_config(tmp_path).use_text_meaning
    assert not load_config(tmp_path, enable_text_meaning=False).use_text_meaning
    assert not load_config(tmp_path, enable_ocr=False).use_text_meaning  # nothing to compare without text
    assert load_text_model(load_config(tmp_path, enable_text_meaning=False)) is None
    monkeypatch.setenv("SNAPRECALL_TEXT_MEANING", "0")
    monkeypatch.setenv("SNAPRECALL_MEANING_THRESHOLD", "0.4")
    config = load_config(tmp_path)
    assert not config.enable_text_meaning and config.meaning_threshold == 0.4


def test_background_models_load_the_text_model(tmp_path):
    loaded = BackgroundModels(load_config(tmp_path), in_process=True,
                              loaders={"text_model": lambda config: FakeTextModel()})
    assert loaded.wait(5) and loaded.text_model.name == "fake-meaning-1" and loaded.problems == []
