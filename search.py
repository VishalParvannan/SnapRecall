"""Search over indexed screenshots.

How ranking works
-----------------
1. Text candidates come from SQLite full-text search (see text_index.py) over filenames,
   recognized text, and generated labels. Each query word scores 1 for a whole word or stem,
   0.6 for the start of a longer word, 0.4 for a listed synonym, and 0.6 x confidence for a
   generated label (likely source app or tag). The text score is the average over query words;
   ties are ordered by FTS5's bm25 relevance.
2. Visual candidates: the query and every screenshot are embedded with the same image-text
   model; the visual score is their cosine similarity. The query is embedded both as written
   and as "a screenshot of <query>", averaged. Each screenshot also has embeddings for square
   regions of itself (see indexer.image_regions), and the visual score is the best of the whole
   image and its regions, so small details like a profile picture or a logo can match. Only
   the top `visual_top_k` screenshots join the ranking.
3. Combined search also compares the query embedding with recognized text embeddings, adding
   a small bonus for likely related meanings ("flame" for a screenshot that says "fire").
4. Combination: the scores live on different scales, so we combine *ranks* with reciprocal
   rank fusion (RRF), each term scaled by its strength:
       score = text_score / (60 + text_rank)
             + (visual_score / best_visual_score) ** 2 / (60 + visual_rank)
   Scaling each term keeps a stray one-word text match from outranking a clear visual winner
   (measured with evaluate.py).
5. A result is "strong" if at least half the query is found in its filename or recognized text,
   or its visual score reaches the configured threshold. Labels, synonyms, and related meanings
   are suggestions and never make a result strong on their own. If no result is strong, the
   response is marked weak so the interface can say the matches are uncertain.
"""
from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np

from indexer import region_model
from models import Embedder, embed_texts, normalize
from storage import ImageRecord
from text_index import text_index_for

RRF_K = 60
VISUAL_SHARPNESS = 2  # see search(); smallest value that fixed visual queries on samples/eval
SEMANTIC_TEXT_THRESHOLD = 0.75
_text_embedding_cache = OrderedDict()
_TEXT_CACHE_LIMIT = 2048
STRONG_TEXT = 0.5
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from",
    "by", "is", "it", "that", "this", "i", "my", "me", "was", "some", "about", "wanted",
}
_WORD_RE = re.compile(r"[^\W_]+")


@dataclass
class SearchResult:
    record: ImageRecord
    score: float
    text_score: float = 0.0
    visual_score: float | None = None
    strong: bool = False


@dataclass
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    weak: bool = False
    notice: str | None = None


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(unicodedata.normalize("NFKC", text).casefold())


def query_terms(query: str) -> list[str]:
    terms = tokenize(query)
    meaningful = [t for t in terms if t not in STOPWORDS]
    return meaningful or terms


def _partial_match(term: str, words: set[str], joined: str) -> bool:
    if not term.isascii():
        # Scripts written without spaces (e.g. CJK) form long "words".
        return term in joined
    if len(term) >= 3 and any(w.startswith(term) for w in words):
        return True  # "connect" -> "connection"
    return any(len(w) >= 4 and term.startswith(w) for w in words)  # "tomatoes" -> "tomato"


def _semantic_text_vectors(embedder: Embedder, texts: list[str]) -> list[np.ndarray]:
    # Cache by model instance and content: changed OCR is automatically re-encoded.
    # Texts not seen before are embedded together in batches.
    missing = list(dict.fromkeys(t for t in texts if (embedder, t) not in _text_embedding_cache))
    if missing:
        for text, vector in zip(missing, embed_texts(embedder, missing)):
            _text_embedding_cache[(embedder, text)] = vector
    vectors = []
    for text in texts:
        _text_embedding_cache.move_to_end((embedder, text))
        vectors.append(_text_embedding_cache[(embedder, text)])
    while len(_text_embedding_cache) > max(_TEXT_CACHE_LIMIT, len(texts)):
        _text_embedding_cache.popitem(last=False)
    return vectors


def visual_scores(records: list[ImageRecord], q: np.ndarray, embedder: Embedder) -> np.ndarray:
    """Similarity of each record to the query: the best of the whole image and its regions,
    so a small detail (an avatar, a logo) can match even when the whole screenshot doesn't."""
    scores = np.stack([r.embedding for r in records]) @ q
    regions_name = region_model(embedder)
    for i, rec in enumerate(records):
        if rec.region_embeddings is not None and rec.region_model == regions_name:
            scores[i] = max(scores[i], float((rec.region_embeddings @ q).max()))
    return scores


def query_vectors(embedder: Embedder, query: str) -> tuple[np.ndarray, np.ndarray]:
    """(plain query, query for visual search). The visual one averages the plain query with
    "a screenshot of ..."; CLIP matches screenshots better that way. One batched model pass."""
    plain, framed = embed_texts(embedder, [query, f"a screenshot of {query}"])
    return plain, normalize(plain + framed)


def search(query: str, records: list[ImageRecord], embedder: Embedder | None = None,
           mode: str = "combined", limit: int = 30, visual_top_k: int = 50,
           visual_threshold: float = 0.29) -> SearchResponse:
    """Rank `records` for `query`. `mode` is "combined", "text", or "visual"."""
    terms = query_terms(query)
    if not terms:
        return SearchResponse()
    response = SearchResponse()
    records = [r for r in records if r.status != "error"]

    text: dict[str, float] = {}
    facts: dict[str, float] = {}
    if mode in ("combined", "text"):
        for match in text_index_for(records).search(terms):  # best first
            text[match.path], facts[match.path] = match.score, match.fact_score

    visual: dict[str, float] = {}
    semantic: dict[str, float] = {}
    if mode in ("combined", "visual") and embedder is not None:
        usable = [r for r in records if r.embedding is not None and r.embed_model == embedder.name]
        if usable or (mode == "combined" and any(r.ocr_text for r in records)):
            try:
                q, q_visual = query_vectors(embedder, query)
            except Exception:
                response.notice = "Visual search is unavailable right now; showing text matches only."
            else:
                if usable:
                    sims = visual_scores(usable, q_visual, embedder)
                    order = np.argsort(-sims)[:visual_top_k]
                    visual = {usable[i].path: float(sims[i]) for i in order}
                with_text = [rec for rec in records if rec.ocr_text] if mode == "combined" else []
                try:
                    vectors = _semantic_text_vectors(embedder, [rec.ocr_text for rec in with_text])
                except Exception:
                    response.notice = "Recognized text could not be searched by meaning right now."
                    vectors = []
                for rec, vector in zip(with_text, vectors):
                    similarity = float(vector @ q)
                    if similarity >= SEMANTIC_TEXT_THRESHOLD:
                        # Exact matches remain stronger than related meanings.
                        semantic[rec.path] = similarity

    fused: dict[str, float] = {}
    best_visual = max(visual.values(), default=0.0)
    for scores, is_text in ((text, True), (visual, False)):
        ranked = list(scores) if is_text else sorted(scores, key=lambda p: (-scores[p], p))
        for rank, path in enumerate(ranked, start=1):
            if is_text:
                weight = scores[path]
            else:
                # Rank alone treats visual #1 and #20 almost alike; weighting by closeness to the
                # best visual match keeps a clear visual winner ahead of a one-word text hit.
                weight = (max(scores[path], 0.0) / best_visual) ** VISUAL_SHARPNESS if best_visual > 0 else 1.0
            fused[path] = fused.get(path, 0.0) + weight / (RRF_K + rank)

    for rank, path in enumerate(sorted(semantic, key=lambda p: (-semantic[p], p)), start=1):
        fused[path] = fused.get(path, 0.0) + 0.25 * semantic[path] / (RRF_K + rank)

    by_path = {r.path: r for r in records}
    for path, score in fused.items():
        t, v = text.get(path, 0.0), visual.get(path)
        strong = facts.get(path, 0.0) >= STRONG_TEXT or (v is not None and v >= visual_threshold)
        response.results.append(SearchResult(by_path[path], score, t, v, strong))
    response.results.sort(key=lambda r: (-r.score, -r.text_score, r.record.path))
    response.results = response.results[:limit]
    response.weak = bool(response.results) and not any(r.strong for r in response.results)
    return response


# ---- filters, similar screenshots, and text excerpts ------------------------

def filter_by_date(records: list[ImageRecord], start: date | None = None,
                   end: date | None = None) -> list[ImageRecord]:
    """Keep screenshots whose file was modified between `start` and `end` (inclusive, local time)."""
    def day(rec: ImageRecord) -> date:
        return datetime.fromtimestamp(rec.mtime_ns / 1e9).date()
    return [r for r in records if (start is None or day(r) >= start) and (end is None or day(r) <= end)]


BEST_MATCH = "Best match"
SORT_OPTIONS = [BEST_MATCH, "Date modified (newest)", "Date modified (oldest)", "Name (A–Z)", "Name (Z–A)",
                "Size (largest)", "Size (smallest)", "Type"]


def _natural_key(name: str) -> list:
    """Sort names like a file explorer: case-insensitive, with digit runs compared as numbers (2 < 10)."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in re.split(r"(\d+)", name.casefold()) if part]


def sort_records(records: list[ImageRecord], order: str) -> list[ImageRecord]:
    """Return `records` in the chosen order. "Best match" keeps the given (relevance) order.

    Ties are broken by name so the grid order is stable between reruns."""
    by_name = sorted(records, key=lambda r: _natural_key(r.name))
    if order == "Date modified (newest)":
        return sorted(by_name, key=lambda r: r.mtime_ns, reverse=True)
    if order == "Date modified (oldest)":
        return sorted(by_name, key=lambda r: r.mtime_ns)
    if order == "Name (A–Z)":
        return by_name
    if order == "Name (Z–A)":
        return by_name[::-1]
    if order == "Size (largest)":
        return sorted(by_name, key=lambda r: r.size, reverse=True)
    if order == "Size (smallest)":
        return sorted(by_name, key=lambda r: r.size)
    if order == "Type":
        return sorted(by_name, key=lambda r: Path(r.path).suffix.casefold())
    return list(records)


@dataclass
class SimilarResult:
    record: ImageRecord
    similarity: float


def similar(target: ImageRecord, records: list[ImageRecord], embedder_name: str,
            limit: int = 8, min_similarity: float = 0.5) -> list[SimilarResult]:
    """Screenshots that look most like `target`, by cosine similarity of image embeddings.

    On the sample set, unrelated pairs have a median similarity of about 0.42; 0.5 keeps
    roughly the closest 30%, then the top `limit` are shown.
    """
    if target.embedding is None or target.embed_model != embedder_name:
        return []
    usable = [r for r in records if r.path != target.path and r.status != "error"
              and r.embedding is not None and r.embed_model == embedder_name]
    if not usable:
        return []
    sims = np.stack([r.embedding for r in usable]) @ target.embedding
    order = np.argsort(-sims)[:limit]
    return [SimilarResult(usable[i], float(sims[i])) for i in order if sims[i] >= min_similarity]


def excerpt(text: str, terms: list[str], width: int = 90) -> list[tuple[str, bool]] | None:
    """A short passage of `text` around the query words, as (segment, is_match) pairs.

    Returns None when no query word appears in the text.
    """
    if not text or not terms:
        return None
    text = " ".join(text.split())
    matches = []
    for m in re.finditer(r"[^\W_]+", text):
        word = unicodedata.normalize("NFKC", m.group()).casefold()
        if any(word == t or _partial_match(t, {word}, word) for t in terms):
            matches.append((m.start(), m.end()))
    if not matches:
        return None
    # Window starting a little before the first match, snapped to word boundaries.
    start = max(0, matches[0][0] - width // 3)
    end = min(len(text), start + width)
    if start > 0:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < matches[0][0] else start
    if end < len(text):
        space = text.rfind(" ", matches[0][1], end)
        end = space if space > 0 else end
    segments: list[tuple[str, bool]] = [("…", False)] if start > 0 else []
    pos = start
    for s, e in matches:
        if s < start or e > end:
            continue
        if s > pos:
            segments.append((text[pos:s], False))
        segments.append((text[s:e], True))
        pos = e
    if pos < end:
        segments.append((text[pos:end], False))
    if end < len(text):
        segments.append(("…", False))
    return segments
