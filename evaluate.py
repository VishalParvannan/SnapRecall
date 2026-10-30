"""Evaluate text, visual, and combined search on a labelled folder.

    python evaluate.py                      # uses samples/eval
    python evaluate.py --folder F --queries F/queries.json

The index is built in a temporary directory (or --index-dir) so your own
index is untouched.
For queries with relevant screenshots we report top-1 and top-5 hit rates.
For queries with no relevant screenshot, a correct answer is "no results"
or results flagged as weak.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from config import load_config
from indexer import index_folder
from models import ModelLoadError, load_embedder, load_ocr
from search import search
from storage import Storage

MODES = ("text", "visual", "combined")


def evaluate(records, queries, embedder, visual_threshold):
    rows = {}
    for mode in MODES:
        if mode != "text" and embedder is None:
            continue
        top1 = top5 = answerable = none_ok = none_total = 0
        by_kind: dict[str, list[int]] = {}
        for q in queries:
            resp = search(q["query"], records, embedder, mode=mode, visual_threshold=visual_threshold)
            names = [r.record.name for r in resp.results]
            if q["relevant"]:
                answerable += 1
                hit1 = bool(names[:1]) and names[0] in q["relevant"]
                hit5 = any(n in q["relevant"] for n in names[:5])
                top1 += hit1
                top5 += hit5
                by_kind.setdefault(q["kind"], [0, 0, 0])
                by_kind[q["kind"]][0] += hit1
                by_kind[q["kind"]][1] += hit5
                by_kind[q["kind"]][2] += 1
            else:
                none_total += 1
                none_ok += (not resp.results) or resp.weak
        rows[mode] = dict(top1=top1, top5=top5, answerable=answerable,
                          none_ok=none_ok, none_total=none_total, by_kind=by_kind)
    return rows


def print_table(rows) -> None:
    print(f"\n{'mode':<10}{'top-1':>10}{'top-5':>10}{'no-match flagged':>20}")
    for mode, r in rows.items():
        n = r["answerable"]
        print(f"{mode:<10}{r['top1'] / n:>10.0%}{r['top5'] / n:>10.0%}"
              f"{r['none_ok']:>14}/{r['none_total']}")
    print("\nBy query type (top-1 / top-5):")
    kinds = sorted({k for r in rows.values() for k in r["by_kind"]})
    print(f"{'type':<14}" + "".join(f"{m:>16}" for m in rows))
    for kind in kinds:
        cells = []
        for r in rows.values():
            h1, h5, n = r["by_kind"].get(kind, [0, 0, 0])
            cells.append(f"{h1}/{n} , {h5}/{n}" if n else "-")
        print(f"{kind:<14}" + "".join(f"{c:>16}" for c in cells))


def main() -> None:
    root = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", type=Path, default=root / "samples" / "eval")
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--output", type=Path, help="write results as JSON")
    parser.add_argument("--index-dir", type=Path,
                        help="reuse an index directory (default: a fresh temporary one)")
    args = parser.parse_args()
    queries = json.loads((args.queries or args.folder / "queries.json").read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        config = load_config(args.index_dir or tmp)
        ocr = embedder = None
        try:
            ocr = load_ocr(config)
        except ModelLoadError as exc:
            print(f"OCR unavailable: {exc}")
        try:
            embedder = load_embedder(config)
        except ModelLoadError as exc:
            print(f"Visual search unavailable: {exc}")
        storage = Storage(config.db_path)
        report = index_folder(args.folder, storage, config, ocr, embedder,
                              lambda i, n, _: print(f"\rIndexing {i}/{n}", end=""))
        print(f"\nIndexed {report.processed} images, {len(report.failed)} problems")
        records = storage.folder_images(report.folder)
        rows = evaluate(records, queries, embedder, config.visual_threshold)
        models = {"ocr": getattr(ocr, "name", None), "visual": getattr(embedder, "name", None)}

    print(f"Models: {models}")
    print_table(rows)
    if args.output:
        args.output.write_text(json.dumps({"models": models, "results": rows}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
