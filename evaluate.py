"""Evaluate text, visual, and combined search on a labelled folder.

    python evaluate.py                      # uses samples/eval
    python evaluate.py --folder F --queries F/queries.json [--apps F/apps.json]

The index is built in a temporary directory (or --index-dir) so your own
index is untouched.
For queries with relevant screenshots we report top-1 and top-5 hit rates.
For queries with no relevant screenshot, a correct answer is "no results"
or results flagged as weak.
Also reported: indexing time per screenshot, search latency, index storage,
and, when apps.json lists each screenshot's real source app, how often the
detected source app is right, wrong, missing, or claimed for a screenshot
that has none. Only filenames and app names are printed, never screenshot text.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
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


def latency_ms(records, queries, embedder, visual_threshold) -> dict:
    """Combined-search latency per query (after one warm-up query, which builds the text index)."""
    search(queries[0]["query"], records, embedder, visual_threshold=visual_threshold)
    times = []
    for q in queries:
        start = time.perf_counter()
        search(q["query"], records, embedder, visual_threshold=visual_threshold)
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return {"mean": statistics.fmean(times), "p95": times[min(len(times) - 1, int(0.95 * len(times)))]}


def storage_bytes(config) -> dict:
    db = sum(p.stat().st_size for p in config.index_dir.glob("index.db*"))
    thumbs = sum(p.stat().st_size for p in config.thumbnail_dir.glob("*.jpg"))
    return {"database": db, "thumbnails": thumbs}


def app_detection(records, expected: dict[str, str]) -> dict:
    """Compare detected source apps with the true ones (screenshots missing from `expected` have none)."""
    counts = {"right": 0, "wrong": 0, "missed": 0, "false_alarm": 0, "unknown_ok": 0}
    details = []
    for rec in records:
        truth, found = expected.get(rec.name), rec.source_app
        if truth:
            kind = "right" if found == truth else "wrong" if found else "missed"
        else:
            kind = "false_alarm" if found else "unknown_ok"
        counts[kind] += 1
        if kind != "unknown_ok":
            details.append((rec.name, truth, found, rec.source_confidence, rec.source_evidence, kind))
    return {"counts": counts, "details": details}


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
    parser.add_argument("--apps", type=Path, help="JSON {filename: source app} (default: FOLDER/apps.json)")
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
        start = time.perf_counter()
        report = index_folder(args.folder, storage, config, ocr, embedder,
                              lambda i, n, _: print(f"\rIndexing {i}/{n}", end=""))
        index_seconds = time.perf_counter() - start
        print(f"\nIndexed {report.processed} images, {len(report.failed)} problems")
        records = storage.folder_images(report.folder)
        rows = evaluate(records, queries, embedder, config.visual_threshold)
        latency = latency_ms(records, queries, embedder, config.visual_threshold)
        sizes = storage_bytes(config)
        apps_file = args.apps or args.folder / "apps.json"
        apps = None
        if apps_file.exists():
            apps = app_detection(records, json.loads(apps_file.read_text(encoding="utf-8")))
        models = {"ocr": getattr(ocr, "name", None), "visual": getattr(embedder, "name", None)}

    print(f"Models: {models}")
    print_table(rows)
    per_image = index_seconds / max(report.processed, 1)
    total = sizes["database"] + sizes["thumbnails"]
    print(f"\nIndexing: {index_seconds:.0f} s for {report.processed} screenshots ({per_image:.1f} s each)")
    print(f"Search latency (combined): mean {latency['mean']:.0f} ms, p95 {latency['p95']:.0f} ms")
    print(f"Storage: database {sizes['database'] / 1024:.0f} KB + thumbnails {sizes['thumbnails'] / 1024:.0f} KB "
          f"({total / max(len(records), 1) / 1024:.0f} KB per screenshot)")
    if apps:
        c = apps["counts"]
        print(f"Source app: {c['right']} right, {c['wrong']} wrong, {c['missed']} missed, "
              f"{c['false_alarm']} claimed for screenshots with no particular app, "
              f"{c['unknown_ok']} correctly unknown")
        for name, truth, found, conf, evidence, kind in apps["details"]:
            detected = f"{found} ({conf:.2f}, {evidence})" if found else "-"
            print(f"  {name}: expected {truth or '-'}, detected {detected}  [{kind}]")
    if args.output:
        args.output.write_text(json.dumps({"models": models, "results": rows, "index_seconds": index_seconds,
                                           "latency_ms": latency, "storage_bytes": sizes, "apps": apps},
                                          indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
