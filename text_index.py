"""Full-text search over filenames, recognized text, and generated labels (SQLite FTS5).

The index is an in-memory SQLite database built from the screenshots being searched. It is
cached and rebuilt only when they change (new screenshots, re-recognized text, new labels), so
typing new queries doesn't rebuild it.

Text is normalized like queries (Unicode NFKC + case folding) and indexed with FTS5's
`porter unicode61 remove_diacritics 2` tokenizer, so "connect" matches "Connection",
"tomatoes" matches "tomato", and "Kasespatzle" matches "Käsespätzle".

For each query word, a screenshot scores the best of:
  1.0               the word (or its stem) appears in the filename or recognized text
  0.6               a longer word starts with it ("conn" -> "connection"), or, for scripts
                    written without spaces (Chinese, Japanese, Thai, ...), it appears inside a run
  0.4               a listed synonym appears (SYNONYMS: a small supplement, not the main mechanism)
  0.6 x confidence  a generated label matches: the likely source app or a tag (see labels.py)
The first two are facts about what the screenshot contains. Labels and synonyms help ranking but
are tracked separately so that, on their own, they never make a result a strong match.
"""
from __future__ import annotations

import sqlite3
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from labels import searchable_labels
from storage import ImageRecord

TOKENIZER = "porter unicode61 remove_diacritics 2"
EXACT_MATCH = 1.0
PARTIAL_MATCH = 0.6
SYNONYM_MATCH = 0.4
LABEL_MATCH = 0.6
NAME_WEIGHT, BODY_WEIGHT = 2.0, 1.0  # bm25 column weights, used to order equally good matches

# Query word -> words that mean nearly the same. Kept small on purpose; visual and semantic
# search handle most related meanings.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "flame": ("fire",), "flames": ("fire",), "blaze": ("fire",), "fire": ("flame",),
    "sea": ("ocean",), "ocean": ("sea",), "automobile": ("car",), "vehicle": ("car",),
    "puppy": ("dog",), "kitten": ("cat",), "kitty": ("cat",), "cash": ("money",),
    "graph": ("chart",), "chart": ("graph",), "pic": ("photo", "picture"), "photo": ("picture",),
    "tweet": ("twitter",), "insta": ("instagram",), "yt": ("youtube",), "cmd": ("command prompt",),
    "vscode": ("visual studio code",), "email": ("mail",), "mail": ("email",), "bug": ("error",),
    "error": ("err",), "film": ("movie",), "movie": ("film",),
}

_SPACELESS_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "THAI", "LAO", "KHMER", "MYANMAR", "TIBETAN")


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _spaceless(term: str) -> bool:
    return any(unicodedata.name(c, "").startswith(_SPACELESS_SCRIPTS) for c in term)


def _phrase(word: str) -> str:
    return '"' + word.replace('"', '""') + '"'


@dataclass
class TextMatch:
    path: str
    score: float  # average over query words, including labels and synonyms
    fact_score: float  # the same, counting only words found in the filename or recognized text
    bm25: float  # FTS5 relevance (lower is better), used to order equal scores


class TextIndex:
    def __init__(self, records: list[ImageRecord]):
        self._lock = threading.Lock()
        self._paths = {rowid: r.path for rowid, r in enumerate(records, start=1)}
        self._texts: dict[int, str] = {}
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute(f"CREATE VIRTUAL TABLE docs USING fts5(name, body, tokenize='{TOKENIZER}')")
        self._conn.execute("CREATE VIRTUAL TABLE labels USING fts5(doc UNINDEXED, phrase, "
                           f"confidence UNINDEXED, tokenize='{TOKENIZER}')")
        docs, labels = [], []
        for rowid, rec in enumerate(records, start=1):
            name, body = normalize_text(Path(rec.path).stem), normalize_text(rec.ocr_text or "")
            docs.append((rowid, name, body))
            self._texts[rowid] = f"{name}\n{body}"
            labels += [(rowid, normalize_text(phrase), conf)
                       for phrase, conf in searchable_labels(rec.source_app, rec.source_confidence, rec.tags)]
        with self._conn:
            self._conn.executemany("INSERT INTO docs (rowid, name, body) VALUES (?, ?, ?)", docs)
            self._conn.executemany("INSERT INTO labels (doc, phrase, confidence) VALUES (?, ?, ?)", labels)

    def _query(self, sql: str, match: str) -> list[tuple]:
        with self._lock:
            try:
                return self._conn.execute(sql, (match,)).fetchall()
            except sqlite3.OperationalError:  # e.g. a word the tokenizer reduces to nothing
                return []

    def _docs(self, match: str) -> set[int]:
        return {row[0] for row in self._query("SELECT rowid FROM docs WHERE docs MATCH ?", match)}

    def _labels(self, match: str) -> dict[int, float]:
        found: dict[int, float] = {}
        for doc, conf in self._query("SELECT doc, confidence FROM labels WHERE labels MATCH ?", match):
            found[doc] = max(found.get(doc, 0.0), float(conf))
        return found

    def term_scores(self, term: str) -> dict[int, tuple[float, float]]:
        """rowid -> (score, fact score) for one query word."""
        scores: dict[int, tuple[float, float]] = {}

        def add(rowids, score, fact):
            for rowid in rowids:
                old = scores.get(rowid, (0.0, 0.0))
                scores[rowid] = (max(old[0], score), max(old[1], score if fact else 0.0))

        column = "{name body} : "
        if _spaceless(term):
            add([r for r, text in self._texts.items() if term in text], PARTIAL_MATCH, True)
        elif len(term) >= 3:
            add(self._docs(column + _phrase(term) + "*"), PARTIAL_MATCH, True)
        add(self._docs(column + _phrase(term)), EXACT_MATCH, True)
        for synonym in SYNONYMS.get(term, ()):
            add(self._docs(column + _phrase(synonym)), SYNONYM_MATCH, False)
        for word in (term, *SYNONYMS.get(term, ())):
            for rowid, conf in self._labels("phrase : " + _phrase(word)).items():
                add([rowid], LABEL_MATCH * conf, False)
        return scores

    def search(self, terms: list[str]) -> list[TextMatch]:
        """Screenshots matching any query word, best first."""
        if not terms:
            return []
        totals: dict[int, list[float]] = {}
        for term in terms:
            for rowid, (score, fact) in self.term_scores(term).items():
                total = totals.setdefault(rowid, [0.0, 0.0])
                total[0] += score
                total[1] += fact
        any_word = "{name body} : (" + " OR ".join(_phrase(t) + "*" for t in terms) + ")"
        bm25 = {rowid: rank for rowid, rank in self._query(
            f"SELECT rowid, bm25(docs, {NAME_WEIGHT}, {BODY_WEIGHT}) FROM docs WHERE docs MATCH ?", any_word)}
        matches = [TextMatch(self._paths[rowid], score / len(terms), fact / len(terms), bm25.get(rowid, 0.0))
                   for rowid, (score, fact) in totals.items() if score > 0]
        matches.sort(key=lambda m: (-m.score, m.bm25, m.path))
        return matches


_CACHE: OrderedDict[tuple, TextIndex] = OrderedDict()
_CACHE_LIMIT = 4
_cache_lock = threading.Lock()


def text_index_for(records: list[ImageRecord]) -> TextIndex:
    """A (cached) index of `records`; rebuilt when their names, text, or labels change."""
    key = tuple((r.path, r.ocr_text, r.source_app, r.source_confidence, tuple(r.tags or ())) for r in records)
    with _cache_lock:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    index = TextIndex(records)
    with _cache_lock:
        _CACHE[key] = index
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return index
