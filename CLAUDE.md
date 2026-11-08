# SnapRecall — Project Guide

## Vision

Build SnapRecall as a personal screenshot library that helps users find, use, and organize screenshots by describing what they remember. Search should work with visible text, visual content, filenames, and imperfect descriptions. Local search should work without an account; optional accounts can enable cross-device features.

## Core experience

- Let users choose and manage multiple screenshot folders. Index PNG and JPEG at minimum, including subfolders, without modifying original files.
- Remember indexed folders and search data between sessions. Detect new, changed, and missing images, and avoid reprocessing unchanged images.
- Show indexing progress, failures, and retry options. An incomplete scan must not remove valid records.
- Search with natural language across extracted text and visual content. Rank results using a documented combination of both signals.
- Display a responsive grid of thumbnails with filenames and useful dates. Allow users to filter by folder and date, inspect a larger preview, and open the original.
- Support finding visually similar screenshots and show a matching text excerpt where useful.
- Provide understandable empty, loading, error, and no-match states. Avoid suggesting that search results are guaranteed to be relevant.

## Copy images

Provide a prominent **Copy image** action in the detail view, with a convenient result-card action where practical. Copy the actual original-resolution image so it can be pasted into another application using the normal paste shortcut. Copying only a path, link, or thumbnail does not satisfy this feature. Never modify the original.

Show success only after copying succeeds and explain failures, including missing files, denied clipboard access, and unsupported platforms. Preserve transparency where supported. Test a real paste into another application. Since Streamlit runs in a browser while Python runs on the host, implement and document clipboard behavior for the user's device; a remote server's clipboard is not the user's clipboard.

## Library and future features

- Automatically notice changes in user-selected folders, with visible status and controls.
- Offer a timeline, favorites, tags, and notes.
- Group related screenshots and detect duplicate or near-duplicate images.
- Optionally learn from user feedback to improve ranking, with clear controls.
- Consider a packaged desktop app and onboarding that makes setup accessible without Python knowledge.

## Accounts and sync

Keep core local search available without signing in. Optional accounts may provide cross-device sync, backup, and synchronized favorites, notes, and preferences. Before implementing sync, decide and clearly explain whether original images, extracted text, embeddings, metadata, or combinations of these are uploaded. An index alone does not make an original image available on another device.

Require explicit opt-in for uploads. Provide clear controls to manage and delete local and cloud data, and design authentication, access controls, and secure storage appropriately. Never promise privacy or security properties that have not been verified.

## Privacy and reliability

- Index only folders explicitly selected by the user. Do not automatically scan the entire computer.
- Process and store data locally by default. Explain model downloads and support offline indexing and search after setup when models are available.
- Never upload screenshots or extracted content without explicit user choice. Do not put private screenshot contents in logs or public sample data.
- Support overlapping folders correctly by separating image identity from folder membership.
- Handle inaccessible folders, corrupt images, missing files, clipboard failures, and interrupted indexing without losing valid records. Retry previously failed images.
- Store model identity and version with generated data, and reprocess as needed when models or settings change.
- Make CPU use possible; a GPU can be an optional performance improvement.

## Tools and architecture

- **Python** for application logic; **Streamlit** for the current interface while evaluating whether a dedicated desktop interface is needed.
- **Pillow** for image handling and thumbnails.
- An OCR library such as **EasyOCR** for text extraction.
- A compatible pretrained image–text model such as **OpenCLIP**, with **PyTorch** and **NumPy**, for visual search.
- **SQLite** for local metadata, extracted text, index state, and folder membership. Choose and document an appropriate embedding storage format.
- **pytest** for focused tests and **Git** for version control.
- Select and document any clipboard, background indexing, authentication, or sync dependencies when those features are implemented.

Separate interface, indexing, storage, search, and model integrations. Load models efficiently, manage SQLite access safely across sessions, and keep choices configurable. Document model versions, downloads, storage locations, tested platforms, and CPU requirements.

## Interface

Create a clean, responsive personal library with a prominent search bar, a thumbnail grid, and a larger detail view. Show folder and indexing status clearly. Put folder management, privacy, storage, model settings, and optional account controls in settings. Use straightforward labels and keep model details out of the main search flow.

## Quality and evaluation

Test indexing, overlapping folders, incomplete scans, changed and missing files, retries, persistence, ranking, clipboard behavior, and original-file preservation. Use small deterministic model substitutes in automated tests so they do not require a GPU or large downloads.

Build a shareable evaluation set where practical, with roughly 50–100 screenshots and 20 labelled queries. Compare text-only, visual-only, and combined search using top-one and top-five relevance. Include exact text, vague descriptions, visual queries, and queries with no relevant image. Measure indexing time, search latency, and storage use as the library grows. Test real models separately and document limitations.

## Delivery priorities

1. Make folder indexing, persistence, and recovery reliable.
2. Implement OCR, visual embeddings, combined ranking, and evaluation.
3. Add copy image, filters, multiple-folder management, and similar-image search.
4. Develop the broader library experience and optional account and sync features.
5. Improve onboarding, performance, accessibility, and packaging throughout.

Keep the README accurate about what is implemented, how to run it, where data is stored, and known limitations.


## Recognition and retrieval implementation plan

Use pretrained models first; do not assume a custom model needs to be trained. Process each changed image locally: normalize orientation, extract OCR text and confidence, generate an image embedding, and save model versions and image identity. Optionally use a local caption or tagging model for concrete objects and scenes; store captions as uncertain generated metadata, not facts. Identify source apps only when visual branding, interface elements, or OCR provide evidence, and store a confidence score; otherwise leave the source unknown. Never assume the foreground application or filename proves the source.

At query time, retrieve candidates from SQLite full-text search over OCR, filenames, and optional captions, and from text-to-image embedding similarity. Normalize or fuse ranks, then rank exact text matches and visual semantic matches together; tune weights using labelled examples. Support visual similarity with image-to-image embeddings. For example, a query for flame should retrieve a fire image through semantic similarity even without visible text; evaluate this explicitly rather than guaranteeing it. Use optional synonyms as a supplement, not as the only mechanism.

Track OCR and embedding versions separately, reprocess stale data, and preserve prior successful data when processing fails. Keep model inference and stored content local by default. Measure retrieval quality, latency, storage, and CPU performance on a consented, representative evaluation set, including app screenshots, synonyms, visually ambiguous scenes, and no-match queries.

.venv\Scripts\activate
streamlit run app.py

