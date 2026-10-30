import numpy as np

from fakes import FakeEmbedder
from models import normalize
from search import query_terms, search, text_score, tokenize
from storage import ImageRecord

EMB = FakeEmbedder()


def rec(name, text="", color=None, status="ok"):
    r = ImageRecord(path=f"/shots/{name}", size=1, mtime_ns=1, ocr_text=text, status=status)
    if color is not None:
        r.embedding = normalize(np.array(color, dtype=np.float32) - 127.5)
        r.embed_model = EMB.name
    return r


RECORDS = [
    rec("IMG_001.png", "psql: connection to server failed: Connection refused", (20, 20, 20)),
    rec("IMG_002.png", "Spaghetti al pomodoro. 6 ripe tomatoes, basil", (250, 240, 230)),
    rec("IMG_003.png", "", (15, 15, 20)),  # dark screen, no text
    rec("IMG_004.png", "", (220, 30, 30)),  # red, no text
    rec("IMG_005.png", "Running shoes - ocean blue - add to cart", (30, 60, 220)),
]


def top(response, n=1):
    return [r.record.name for r in response.results[:n]]


def test_empty_and_punctuation_queries_return_nothing():
    for q in ["", "   ", "!!!"]:
        resp = search(q, RECORDS, EMB)
        assert resp.results == [] and not resp.weak


def test_exact_text_ranks_first():
    assert top(search("connection refused", RECORDS, EMB, mode="text")) == ["IMG_001.png"]
    assert top(search("database connection refused", RECORDS, EMB)) == ["IMG_001.png"]


def test_approximate_wording_matches_partial_words():
    assert text_score(["connect"], "Connection refused") > 0
    assert text_score(["tomatoes"], "ripe tomato") > 0
    assert top(search("the pasta recipe with tomatoes", RECORDS, EMB)) == ["IMG_002.png"]


def test_filename_is_searchable():
    records = [rec("pasta_recipe.png"), rec("error_log.png")]
    assert top(search("pasta recipe", records)) == ["pasta_recipe.png"]


def test_visual_search_finds_images_without_text():
    resp = search("red", RECORDS, EMB, mode="visual")
    assert top(resp) == ["IMG_004.png"]
    assert resp.results[0].text_score == 0


def test_related_ocr_words_can_match_without_exact_text():
    class MeaningEmbedder:
        name = "meaning-test"

        def embed_text(self, text):
            if text.lower() in ("flame", "fire"):
                return np.array([1.0, 0.0])
            return np.array([0.0, 1.0])

    records = [rec("one.png", "fire"), rec("two.png", "water")]
    result = search("flame", records, MeaningEmbedder())
    assert top(result) == ["one.png"]
    assert result.weak  # semantic matches are suggestions, not confirmed matches
    assert search("flame", records).results == []


def test_combined_uses_both_signals():
    resp = search("blue shoes", RECORDS, EMB)
    assert top(resp) == ["IMG_005.png"]
    first = resp.results[0]
    assert first.text_score > 0 and first.visual_score is not None


def test_no_match_is_flagged_weak():
    resp = search("giraffe passport", RECORDS, EMB, visual_threshold=0.9)
    assert resp.weak
    assert all(not r.strong for r in resp.results)


def test_text_only_without_embedder():
    resp = search("zebra", RECORDS)
    assert resp.results == []


def test_failed_images_are_excluded():
    records = [rec("broken_pasta.png", status="error")]
    assert search("pasta", records).results == []


def test_embeddings_from_other_model_are_ignored():
    other = FakeEmbedder(name="other")
    assert search("red", RECORDS, other, mode="visual").results == []


def test_unicode_tokenization():
    assert tokenize("Größe: GROSS café_menu") == ["grösse", "gross", "café", "menu"]
    assert text_score(query_terms("Größe"), "DIE GRÖSSE") == 1.0
    assert text_score(["東京"], "東京タワーの写真") > 0
    assert text_score(["café"], "Café Central") == 1.0  # NFKC normalization


def test_stopwords_dropped_unless_query_is_only_stopwords():
    assert query_terms("the pasta with tomatoes") == ["pasta", "tomatoes"]
    assert query_terms("the") == ["the"]


# ---- filters, similar, excerpts -------------------------------------------

from datetime import date, datetime

from search import excerpt, filter_by_date, similar


def dated(name, day):
    ns = int(datetime(day.year, day.month, day.day, 12).timestamp() * 1e9)
    return ImageRecord(path=f"/shots/{name}", size=1, mtime_ns=ns)


def test_filter_by_date_is_inclusive():
    recs = [dated("jan.png", date(2026, 1, 15)), dated("mar.png", date(2026, 3, 1)),
            dated("jun.png", date(2026, 6, 30))]
    names = lambda rs: [r.name for r in rs]
    assert names(filter_by_date(recs)) == ["jan.png", "mar.png", "jun.png"]
    assert names(filter_by_date(recs, date(2026, 3, 1), date(2026, 6, 30))) == ["mar.png", "jun.png"]
    assert names(filter_by_date(recs, end=date(2026, 1, 15))) == ["jan.png"]
    assert filter_by_date(recs, date(2027, 1, 1)) == []


def test_similar_ranks_by_look_and_excludes_itself():
    target = rec("dark.png", color=(15, 15, 20))
    others = [target, rec("dark2.png", color=(25, 20, 20)), rec("red.png", color=(220, 30, 30)),
              rec("blue.png", color=(30, 60, 220)), rec("notext.png")]
    results = similar(target, others, EMB.name, min_similarity=-1)
    assert results[0].record.name == "dark2.png"
    assert "dark.png" not in [r.record.name for r in results]
    assert "notext.png" not in [r.record.name for r in results]  # no embedding


def test_similar_needs_matching_model_and_threshold():
    target = rec("a.png", color=(220, 30, 30))
    others = [rec("b.png", color=(30, 200, 60))]
    assert similar(target, others, "other-model") == []
    assert similar(target, others, EMB.name, min_similarity=0.99) == []
    assert similar(rec("plain.png"), others, EMB.name) == []


def test_excerpt_highlights_query_words():
    text = "psql: error\nconnection to server at localhost failed:\nConnection refused"
    segs = excerpt(text, query_terms("connection refused"))
    marked = [s for s, hit in segs if hit]
    assert marked == ["connection", "Connection", "refused"]
    assert "".join(s for s, _ in segs).replace("…", "") in " ".join(text.split())


def test_excerpt_partial_and_none():
    assert [s for s, hit in excerpt("Connected, secured", ["connect"]) if hit] == ["Connected"]
    assert excerpt("nothing relevant here", ["zebra"]) is None
    assert excerpt("", ["zebra"]) is None


def test_excerpt_trims_long_text_with_ellipses():
    text = " ".join(["filler"] * 40 + ["invoice", "total"] + ["filler"] * 40)
    segs = excerpt(text, ["invoice"], width=60)
    joined = "".join(s for s, _ in segs)
    assert joined.startswith("…") and joined.endswith("…") and len(joined) < 80
    assert ("invoice", True) in segs
