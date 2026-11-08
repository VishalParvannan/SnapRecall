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

Indexing speed depends heavily on the CPU. On the laptop used for testing (Intel i7-13620H, CPU only) it took about 12.5 seconds per screenshot, most of it text recognition, and a search took about half a second. Faster CPUs or a GPU are much quicker. `SNAPRECALL_REGIONS=0` saves about 3 seconds per screenshot.

## Launch

```bash
streamlit run app.py
```

Click **Choose a folder…** and pick your screenshot folder in the window that opens (File Explorer on Windows). You can also paste a path under **Paste a folder path instead**. Previously indexed folders are remembered and reopen without re-indexing. To try it quickly, choose `samples/demo`.

The app is meant to be run and used on the same computer: the folder chooser and **Open original** open on the computer running Streamlit. If the folder window doesn't appear, check behind the browser window.

## Browsing and filtering

- **Folders:** pick one folder in the sidebar, or **All folders** to browse and search every indexed folder at once. A screenshot inside overlapping folders is listed once.
- **Dates:** the menu next to the search bar limits results to *Today*, *Past 7 days*, *Past 30 days*, *This year*, or a custom range. Dates are each file's last-modified date, which for screenshots is usually when they were taken.
- **Sort:** the menu next to the date filter orders results by best match, date modified, name (numbers in order, so "img2" comes before "img10"), size, or file type.
- **Detail view:** click a card (thumbnail or name) for a larger preview, its folder, size, and date, and actions to copy, open, rename, or remove it. **From** and **Might show** are the likely source app and objects or scenes, guessed automatically (see [Generated labels](#how-search-works)); they may be wrong.
- **Rename:** renames the file on disk (keeping its extension), never overwrites another file, and keeps its search data.
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
| `SNAPRECALL_REGIONS` | `1` | `0` skips analysing regions of each screenshot (indexing is about 3 s per image faster on CPU, but small details like avatars and logos are found less often) |
| `SNAPRECALL_CLIP_MODEL` / `SNAPRECALL_CLIP_PRETRAINED` | `ViT-B-32` / `laion2b_s34b_b79k` | OpenCLIP model |
| `SNAPRECALL_VISUAL_THRESHOLD` | `0.29` | Similarity counted as a strong visual match |
| `SNAPRECALL_SYNC_URL` | `http://127.0.0.1:8765` | Optional account server |
| `SNAPRECALL_DOWNLOAD_DIR` | `~/Pictures/SnapRecall Backup` | Where downloaded screenshots are saved |

Each stored result records which model produced it. Changing a model setting makes the next re-index reprocess the affected screenshots.

## Privacy and storage

- Screenshots and recognized text are processed locally. Without an account, the only network access is the one-time model download. With an account, screenshots are uploaded only from folders where you turned backup on (see [Accounts and backup](#accounts-and-backup-optional)). Streamlit's usage statistics are turned off in `.streamlit/config.toml`.
- Originals are only read, never modified or deleted. The one exception is **Rename** in the detail view, which renames the file when you ask (its contents are unchanged).
- Only folders you choose are indexed.
- The index is a SQLite database (`index.db`) plus thumbnails in `SNAPRECALL_HOME` (default `~/.snaprecall`). It also keeps `label_prompts_*.npz`, the visual model's vectors for the label descriptions in [labels.py](labels.py) (no screenshot data). Delete that folder to remove all indexed data. "Remove folder from index" in Settings forgets one folder.
- Screenshot contents are not written to logs. Sample images in `samples/` are synthetic, generated by `generate_samples.py`.

## How search works

**Indexing.** Everything runs locally with pretrained models; nothing is trained. For each PNG/JPEG under the folder, SnapRecall:

1. reads the file once, records its SHA-256 as the image's identity (independent of its path), and turns it upright using its EXIF orientation, if any;
2. saves its size, modification time, and a thumbnail;
3. recognizes text with EasyOCR, storing the text and the recognizer's confidence (shown in the detail view as "clear", "mostly clear", or "hard to read");
4. stores a normalized image embedding (OpenCLIP), plus embeddings for up to 16 square regions at two scales. The model squeezes each image into 224 × 224 px and center-crops wide ones, so without regions small details such as a profile picture or logo are lost;
5. generates labels (next section) from the text and embedding.

Text recognition, embeddings, region embeddings, and labels each record the model and settings that produced them, and are redone separately when those change. On re-index, files are classified as new, changed, unchanged, or missing; only new and changed files are processed, plus files that previously failed or whose results are out of date. If redoing a step fails, the earlier successful result is kept (the screenshot stays searchable and is retried next time). An unchanged file that can't be opened right now (for example, locked by another program) keeps its earlier results too. Each image is saved as soon as it is processed, so an interrupted run keeps its progress.

**Generated labels** ([labels.py](labels.py)). These are uncertain guesses, shown in the detail view as **From** and **Might show** with a "may be wrong" note:

- *Source app* (Discord, Slack, PowerShell, Excel, … about 40 apps). An app is named only with evidence: the screenshot *looks* like it (the visual model compares the image with descriptions of each app and with generic alternatives such as "a website" or "a photo"), and/or the recognized text contains interface wording specific to it (such as "Message @alex"). Merely mentioning an app's name is weak evidence. The source stays unknown unless the best app reaches 0.5 confidence and clearly beats the runner-up. The filename and the app that was open are never used as evidence.
- *Tags* for concrete objects and scenes (fire, sunset, dog, ticket, stop sign, …), from the whole screenshot, kept only at ≥ 0.6 probability against "this is just text/an interface/shapes" alternatives. Tags never name people.

Labels reuse the stored text and embedding, so changing the label settings relabels a library in seconds per hundred screenshots, without re-running text recognition.

If any directory or file can't be read, the scan is marked incomplete and **no records are removed** — an unreadable folder is not treated as proof that files are gone. Folders may overlap (a folder and its subfolder can both be indexed); each folder keeps its own list of images.

**Ranking.** See the docstring in [search.py](search.py) for details.

1. *Text score* — candidates come from SQLite full-text search (FTS5, [text_index.py](text_index.py)) over filenames, recognized text, and generated labels. Each query word scores 1 for a whole word or its stem ("tomatoes" finds "tomato"), 0.6 for the start of a longer word ("conn" finds "connection") or, in Chinese, Japanese, and Thai, a match inside a run of text, 0.4 for a listed synonym ("flame" finds "fire"; a small supplement), and 0.6 × confidence for a label (the likely source app, its aliases such as "twitter" for X, or a tag). The text score is the average over query words; equal scores are ordered by FTS5's bm25 relevance. Matching ignores case and accents, and common filler words ("the", "with") are ignored. The full-text index is built in memory from the screenshots being searched and rebuilt only when they change.
2. *Visual score* — cosine similarity between the query's text embedding and each screenshot's image embedding, taking the best of the whole screenshot and its regions. The query is embedded both as written and as "a screenshot of …", averaged.
3. *Combined* — the two scores are on different scales, so their **ranks** are merged with reciprocal rank fusion, each term scaled by its strength: `score = text / (60 + text_rank) + (visual / best_visual)² / (60 + visual_rank)`.
   Combined search also compares the query with recognized text using the visual model's text encoder and gives likely related meanings a small ranking bonus. These suggestions are not treated as strong matches by themselves. The first search may take longer while text embeddings are created; they are cached in memory for later searches. The similarity threshold is experimental and should be evaluated on real screenshots.
4. A result is a strong match only if at least half the query is found in its filename or recognized text, or its visual score reaches the threshold. Labels, synonyms, and related meanings never make a result strong on their own. If nothing is strong, the app says there are no strong matches and shows the closest ones. Results are suggestions, not guarantees.

## Evaluation

```bash
python generate_samples.py   # (re)creates samples/demo and samples/eval
python evaluate.py           # indexes samples/eval in a temp dir and reports hit rates
```

`samples/eval` has 64 synthetic screenshots (text screens, shape/color scenes, a campfire, mock-ups of Discord, PowerShell, and Excel windows, and distractors) with neutral filenames. `queries.json` has 28 labelled queries: exact text (6), approximate wording (6), visual descriptions (6), synonyms (2: "flames" and "a blaze", words that appear in no image), visually ambiguous scenes (2: the campfire and the sunset are both orange, yellow, and dark), source apps (3), and no relevant image (3). `apps.json` lists the true source app of the three mock-ups.

`evaluate.py` reports top-1 / top-5 hit rates for text, visual, and combined search; how often no-match queries are correctly flagged as weak; indexing time per screenshot; search latency; index storage; and how often the detected source app is right, wrong, missing, or claimed for a screenshot with no particular app.

Results on `samples/eval` (EasyOCR 1.7.2 English, OpenCLIP 3.3 `ViT-B-32`/`laion2b_s34b_b79k`, PyTorch 2.15 CPU on an Intel i7-13620H laptop, November 2026):

| Mode | Top-1 | Top-5 | No-match queries flagged weak |
|---|---|---|---|
| Text (incl. labels) | 80% | 84% | 3/3 |
| Visual | 96% | 100% | 3/3 |
| **Combined** | **100%** | **100%** | 3/3 |

| Query type | Text | Visual | Combined (top-1) |
|---|---|---|---|
| Exact text | 5/6 | 5/6 | 6/6 |
| Approximate wording | 6/6 | 6/6 | 6/6 |
| Visual description | 3/6 | 6/6 | 6/6 |
| Synonym | 2/2 | 2/2 | 2/2 |
| Visually ambiguous | 1/2 | 2/2 | 2/2 |
| Source app | 3/3 | 3/3 | 3/3 |

- **Source app:** 3 of 3 mock-ups right (Discord from its interface text; Excel and PowerShell from both look and text), none wrong, and none claimed for the 61 screenshots with no particular app.
- **Cost:** indexing 12.5 s per screenshot (about 9 s of it text recognition), search 487 ms on average (570 ms at the 95th percentile, mostly embedding the query), and 31 KB of index and thumbnail storage per screenshot.

Hit rates are over the 25 queries that have a relevant screenshot. "Text" includes generated labels, which is how it answers half the visual descriptions (the "sunset" and "stop sign" tags, for example).

Tuning decisions that came from this evaluation, all on small data, so treat them as starting points:
- Scaling the text term in the fusion by its score (unscaled, stray partial matches like "red" in "refused" pushed visual-description queries to 1/6 top-1).
- The 0.29 visual threshold (relevant visual matches scored ≥ 0.295, unrelated ones up to ≈ 0.28).
- Scaling the visual term by its strength. Region embeddings alone made combined top-1 *worse* (83% on the first 20 queries), because plain rank fusion let one-word text hits ("screen", "blue") beat clear visual winners. Exponents 2, 4 and 8 all fixed it; the smallest (2) is used.
- Tags from the whole image only, at ≥ 0.6, without the "flag", "meme", "logo", "chart", "calendar" and "rain" tags, which fired on plain text and shape screens.
- Accepting OCR's common misreading of "\" as "I" or "|" in the PowerShell prompt (the PowerShell mock-up was missed before).
- The Discord description ("a Discord chat message with a round profile picture") was chosen using **one** real screenshot, which is not in the repository: with it, the screenshot was recognized as Discord (0.65), "discord" ranked it 1st instead of 2nd, and "kawhi leonard" (the person in its small profile picture) ranked it 1st.

### Evaluating on your own screenshots

The synthetic set can't show how well SnapRecall works on real screenshots. To measure that on your own:

1. Put 50–100 representative screenshots in a folder, for example `samples/private/` (ignored by Git) or anywhere outside the repository. Only use screenshots you're comfortable evaluating, and get consent for anything that shows other people's content.
2. Write `queries.json` in that folder: `[{"query": "...", "kind": "exact", "relevant": ["file.png"]}, ...]`. Include vague descriptions, visual queries, synonyms, app names, and some queries with no relevant screenshot (`"relevant": []`).
3. Optionally write `apps.json`, `{"file.png": "Discord", ...}`, for screenshots whose source app you know (names as in `labels.py`).
4. Run `python evaluate.py --folder samples/private`.

The index is built in a temporary folder, so your own index is untouched. The report prints filenames and app names, never screenshot text.

## Tests

```bash
pytest
```

Tests use small deterministic fake models ([tests/fakes.py](tests/fakes.py)), so they need no downloads or GPU. They cover indexing, change detection, overlapping folders, unreadable folders, files vanishing mid-scan, interrupted runs, retries, keeping earlier results when reprocessing fails, EXIF orientation, content hashes, model and label changes, index upgrades, persistence, ordering, ranking, full-text matching (stems, accents, scripts without spaces), synonyms, label evidence rules (unknown by default, filenames ignored, ambiguous wording), Unicode text, empty input, copy image (full resolution, transparency, errors, originals untouched), and accounts (sign-in, isolation between accounts, upload checks, backup/download, deletion). The sync tests need `fastapi` and are skipped without it.

## Project layout

| File | Responsibility |
|---|---|
| `config.py` | Settings: index location, models, thresholds |
| `storage.py` | SQLite: images, folders, folder membership |
| `indexer.py` | Discovery, change detection, thumbnails, OCR/embedding calls |
| `models.py` | EasyOCR and OpenCLIP adapters |
| `labels.py` | Generated labels: likely source app and tags |
| `text_index.py` | Full-text search (SQLite FTS5) and synonyms |
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
- CLIP-style visual search understands broad concepts, colors, and well-known people, logos, and apps, but not fine details; region embeddings help with small elements but not tiny ones (under ~64 px regions aren't analysed), and its similarity scores are only loosely calibrated — the "strong match" threshold is a heuristic tuned on synthetic data.
- OCR with the default English model misreads some accented words (e.g. "Käsespätzle" as "Kasespatzle"); search ignores accents, so these are still found. Add languages with `SNAPRECALL_OCR_LANGS`.
- The evaluation set is synthetic and small; real screenshot collections will behave differently. Its app screenshots are mock-ups drawn by `generate_samples.py`, so they test the evidence rules, not recognition of real app designs.
- Generated labels are guesses. Source-app descriptions and tag thresholds were tuned on the synthetic set and **one** real screenshot (a Discord message, found as Discord with 0.65 confidence from its look; not included in the repository). Expect missed and occasionally wrong apps until they are checked on a larger, consented set of real screenshots (see [Evaluating on your own screenshots](#evaluating-on-your-own-screenshots)). Only the ~40 apps in `labels.py` can be named; tags come from a fixed list of ~70 objects and scenes.
- The visual model runs slowly on some CPUs (about 0.3–0.4 s per text on the laptop used for testing). Each search embeds the query once; the first search after starting the app also embeds every screenshot's recognized text, which takes longer. Label descriptions are embedded once and saved in the index folder.
- Upgrading from an earlier index format rebuilds the index (screenshots are re-processed once). The upgrades that added region embeddings and labels keep the index; re-indexing adds them without re-running text recognition. EXIF orientation is applied to thumbnails then too, but text and embeddings of photos indexed sideways before this change are only redone if the file changes.
- Region embeddings make indexing slower (about 3 s more per screenshot on a laptop CPU, versus about 9 s for text recognition) and add about 32 KB per screenshot to the index.
- Indexing runs inside the Streamlit request; closing the tab mid-index stops it (progress so far is kept).
