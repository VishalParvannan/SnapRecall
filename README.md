# SnapRecall

Find screenshots by describing what you remember — words that appeared on screen ("database connection refused") or what it looked like ("a dark screen with a red button"). Search runs entirely on your computer, with no account needed. An optional account can back up screenshots and bring them to another device.

## Setup

Tested with Python 3.14 on Windows 11. Runs on CPU; a GPU is used automatically if PyTorch can see one, but is never required.

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # app + tests (small)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-models.txt # text recognition + visual search
```

Without the model packages the app still runs and searches filenames, and says that text recognition / visual search are unavailable.

### Model downloads (first run only)

| Feature | Model | Approx. download |
|---|---|---|
| Text recognition | EasyOCR, English detector + recognizer | ~100 MB |
| Visual search | OpenCLIP `ViT-B-32` / `laion2b_s34b_b79k` | ~600 MB |

Models download automatically the first time the app starts (EasyOCR to `~/.EasyOCR`, OpenCLIP to the Hugging Face cache). After that, indexing and search work offline. The Python packages themselves (PyTorch especially) are a few hundred MB more.

On a typical laptop CPU, expect very roughly 1–3 seconds per screenshot to index (OCR is the slow part). Searching is fast.

## Launch

```bash
streamlit run app.py
```

Click **Choose a folder…** and pick your screenshot folder in the window that opens (File Explorer on Windows). You can also paste a path under **Paste a folder path instead**. Previously indexed folders are remembered and reopen without re-indexing. To try it quickly, choose `samples/demo`.

The app is meant to be run and used on the same computer: the folder chooser and **Open original** open on the computer running Streamlit. If the folder window doesn't appear, check behind the browser window.

## Browsing and filtering

- **Folders:** pick one folder in the sidebar, or **All folders** to browse and search every indexed folder at once. A screenshot inside overlapping folders is listed once.
- **Dates:** the menu next to the search bar limits results to *Today*, *Past 7 days*, *Past 30 days*, *This year*, or a custom range. Dates are each file's last-modified date, which for screenshots is usually when they were taken.
- **Text excerpts:** when a search matches text inside a screenshot, the result card shows a snippet of that text with the matching words highlighted.
- **Similar screenshots:** the detail view lists up to 8 screenshots that look most like the selected one, from the same folder (or all folders). This uses the visual-search data that's already stored, so it needs visual search to be available. Screenshots count as similar above a cosine similarity of 0.5. On the sample set, unrelated pairs have a median of about 0.42, so that keeps roughly the closest 30%. It's a heuristic.

## Copy image

Select a screenshot and click **Copy image**, then paste it anywhere with Ctrl+V (⌘V on a Mac): chat apps, documents, image editors.

- The copy is the **original image at full resolution**, not the thumbnail. JPEGs are copied as PNG (lossless conversion of the decoded pixels); PNG transparency is kept. The original file is only read.
- Copying happens **in your browser**, using the browser's Clipboard API, so the image lands on the clipboard of the device you're browsing from, even if SnapRecall runs elsewhere.
- Browsers only allow this on `localhost` or `https://` pages, and only right after a click. The button says "Copied" only after the browser confirms it; otherwise it explains what went wrong (unsupported browser, permission denied, file missing or unreadable).
- **Tested:** Microsoft Edge on Windows 11. After clicking, the Windows clipboard contained the exact original pixels (verified for an opaque PNG and a semi-transparent PNG), offered as both `PNG` and a standard bitmap. A separate .NET application pasted it at full size. Chrome uses the same engine and should behave the same; Firefox (127+) and Safari support the API but haven't been tested yet.
- Some Windows apps read only the bitmap format and show transparent areas as black; apps that accept PNG keep transparency.
- Images whose PNG would be larger than 40 MB can't be copied from the browser; use **Open original** instead.
- The copy button is in the detail view only. A button on every result card would mean embedding every full-size image in the results page.

## Accounts and backup (optional)

Everything above works without an account. Signing in adds:

- **Backup:** turn on **Back up this folder** (Account in the sidebar). New and changed screenshots are uploaded after each re-index, or with **Back up now**.
- **Download on another device:** sign in there and click **Download my screenshots**. They're saved to `~/Pictures/SnapRecall Backup` (`SNAPRECALL_DOWNLOAD_DIR`), then indexed locally. Existing files are never overwritten.
- **Delete controls:** *Delete backed-up screenshots* removes every uploaded file from your account; *Delete account* removes the account and everything in it. Neither touches screenshots on your computer. *Sign out* removes the saved sign-in from this computer.

**What is uploaded.** Only for folders where backup is on: each screenshot's original file (exact bytes), its file name, and its modified time. **Never uploaded:** folder paths, recognized text, visual-search data, thumbnails. Every device builds its own search index from the files it has, so a downloaded screenshot is searchable after the download finishes indexing.

### Running the sync server

Accounts need a SnapRecall sync server. You host it yourself; there is no public SnapRecall service.

```bash
pip install -r requirements-server.txt
uvicorn sync_server.server:app --port 8765    # data in ./server_data (SNAPRECALL_SERVER_DATA)
```

The app connects to `http://127.0.0.1:8765` by default; set `SNAPRECALL_SYNC_URL` to use another server. The app refuses plain `http://` for anything but localhost, so a server on another machine must be behind HTTPS (for example a reverse proxy such as Caddy or nginx with a certificate).

**Security, as implemented:**
- Passwords are stored as salted scrypt hashes. Sessions are random tokens, stored on the server only as SHA-256 hashes, and expire after 30 days.
- Every file request is limited to the signed-in account's own files. Uploads are checked against their SHA-256 and must be valid PNG/JPEG, 50 MB max.
- After 5 failed sign-ins for an email, sign-in is blocked for 15 minutes. This is tracked in memory, so restarting the server resets it.
- On your computer, the sign-in token is saved in `SNAPRECALL_HOME/account.json`. Anyone who can read your user files could use it until you sign out.
- **Not provided:** encryption of files on the server's disk, password reset, email verification, or an independent security review. Treat the server like any machine that holds copies of your screenshots.

## Configuration

All settings are environment variables (see [config.py](config.py)):

| Variable | Default | Meaning |
|---|---|---|
| `SNAPRECALL_HOME` | `~/.snaprecall` | Where the index lives |
| `SNAPRECALL_OCR` | `1` | `0` turns text recognition off |
| `SNAPRECALL_OCR_LANGS` | `en` | EasyOCR languages, e.g. `en,de` |
| `SNAPRECALL_VISUAL` | `1` | `0` turns visual search off |
| `SNAPRECALL_CLIP_MODEL` / `SNAPRECALL_CLIP_PRETRAINED` | `ViT-B-32` / `laion2b_s34b_b79k` | OpenCLIP model |
| `SNAPRECALL_VISUAL_THRESHOLD` | `0.29` | Similarity counted as a strong visual match |
| `SNAPRECALL_SYNC_URL` | `http://127.0.0.1:8765` | Optional account server |
| `SNAPRECALL_DOWNLOAD_DIR` | `~/Pictures/SnapRecall Backup` | Where downloaded screenshots are saved |

Each stored result records which model produced it. Changing a model setting makes the next re-index reprocess the affected screenshots.

## Privacy and storage

- Screenshots and recognized text are processed locally. Without an account, the only network access is the one-time model download. With an account, screenshots are uploaded only from folders where you turned backup on (see [Accounts and backup](#accounts-and-backup-optional)). Streamlit's usage statistics are turned off in `.streamlit/config.toml`.
- Originals are only read — never moved, modified, or deleted.
- Only folders you choose are indexed.
- The index is a SQLite database (`index.db`) plus thumbnails in `SNAPRECALL_HOME` (default `~/.snaprecall`). Delete that folder to remove all indexed data. "Remove folder from index" in Settings forgets one folder.
- Screenshot contents are not written to logs. Sample images in `samples/` are synthetic, generated by `generate_samples.py`.

## How search works

**Indexing.** For each PNG/JPEG under the folder, SnapRecall stores its size and modification time, a thumbnail, the recognized text (EasyOCR), and a normalized image embedding (OpenCLIP). On re-index, files are classified as new, changed, unchanged, or missing; only new and changed files are processed, plus files that previously failed or were processed by a different model. Each image is saved as soon as it is processed, so an interrupted run keeps its progress.

If any directory or file can't be read, the scan is marked incomplete and **no records are removed** — an unreadable folder is not treated as proof that files are gone. Folders may overlap (a folder and its subfolder can both be indexed); each folder keeps its own list of images.

**Ranking.** See the docstring in [search.py](search.py) for details.

1. *Text score* — the fraction of query words found in the filename or recognized text. Whole words count 1, partial matches 0.6 (so "connect" finds "connection"). Matching ignores case and accents in a Unicode-aware way, and common filler words ("the", "with") are ignored.
2. *Visual score* — cosine similarity between the query's text embedding and each screenshot's image embedding.
3. *Combined* — the two scores are on different scales, so their **ranks** are merged with reciprocal rank fusion: `score = Σ 1 / (60 + rank)`.
   Combined search also compares the query with recognized text using the visual model's text encoder and gives likely related meanings a small ranking bonus. These suggestions are not treated as strong matches by themselves. The first search may take longer while text embeddings are created; they are cached in memory for later searches. The similarity threshold is experimental and should be evaluated on real screenshots.
4. If no result has a text score ≥ 0.5 or a visual score ≥ the threshold, the app says there are no strong matches and shows the closest ones. Results are suggestions, not guarantees.

## Evaluation

```bash
python generate_samples.py   # (re)creates samples/demo and samples/eval
python evaluate.py           # indexes samples/eval in a temp dir and reports hit rates
```

`samples/eval` has 60 synthetic screenshots (text screens, shape/color scenes, distractors) with neutral filenames, and `queries.json` has 20 labelled queries: exact text, approximate wording, visual descriptions, and no-match. `evaluate.py` reports top-1 / top-5 hit rates for text-only, visual-only, and combined search, and how often no-match queries are correctly flagged as weak.

Results on `samples/eval` (EasyOCR 1.7.2 English, OpenCLIP 3.3 `ViT-B-32`/`laion2b_s34b_b79k`, PyTorch 2.15 CPU, October 2026):

| Mode | Top-1 | Top-5 | No-match queries flagged weak |
|---|---|---|---|
| Text only | 61% | 61% | 2/2 |
| Visual only | 83% | 94% | 2/2 |
| **Combined** | **94%** | **100%** | 2/2 |

Hit rates are over the 18 queries that have a relevant screenshot. Text search handles most exact and approximate-wording queries but can't answer visual descriptions; visual search handles those, and the combination gets the best of both. Two tuning decisions came from this evaluation: scaling the text term in the fusion by its score (unscaled, stray partial matches like "red" in "refused" pushed visual-description queries to 1/6 top-1), and the 0.29 visual threshold (relevant visual matches scored ≥ 0.295, unrelated ones up to ≈ 0.28). Both are tuned on this small synthetic set, so treat them as starting points.

## Tests

```bash
pytest
```

Tests use small deterministic fake models ([tests/fakes.py](tests/fakes.py)), so they need no downloads or GPU. They cover indexing, change detection, overlapping folders, unreadable folders, files vanishing mid-scan, interrupted runs, retries, model changes, persistence, ordering, ranking, Unicode text, empty input, copy image (full resolution, transparency, errors, originals untouched), and accounts (sign-in, isolation between accounts, upload checks, backup/download, deletion). The sync tests need `fastapi` and are skipped without it.

## Project layout

| File | Responsibility |
|---|---|
| `config.py` | Settings: index location, models, thresholds |
| `storage.py` | SQLite: images, folders, folder membership |
| `indexer.py` | Discovery, change detection, thumbnails, OCR/embedding calls |
| `models.py` | EasyOCR and OpenCLIP adapters |
| `search.py` | Text, visual, and combined ranking |
| `app.py` | Streamlit interface |
| `folder_picker.py` | Native folder chooser |
| `copy_image.py` | Copy image to the browser device's clipboard |
| `sync.py` | Optional account client: backup and download |
| `sync_server/server.py` | Self-hostable account and backup server (FastAPI) |
| `generate_samples.py`, `evaluate.py` | Sample data and evaluation |

## Known limitations

- Change detection uses size + modification time; an edit that preserves both isn't noticed.
- The date filter uses file modification time. Copying or syncing files with tools that don't preserve it changes which dates screenshots appear under (SnapRecall's own download keeps the original time).
- OCR quality drops on small, stylized, or low-contrast text. Only the configured OCR languages are recognized.
- CLIP-style visual search understands broad concepts and colors but not fine details, and its similarity scores are only loosely calibrated — the "strong match" threshold is a heuristic tuned on synthetic data.
- OCR with the default English model misreads some accented words (e.g. "Käsespätzle"); add languages with `SNAPRECALL_OCR_LANGS`.
- The evaluation set is synthetic and small; real screenshot collections will behave differently.
- Upgrading from an earlier index format rebuilds the index (screenshots are re-processed once).
- Indexing runs inside the Streamlit request; closing the tab mid-index stops it (progress so far is kept).
