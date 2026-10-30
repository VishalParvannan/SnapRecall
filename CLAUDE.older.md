SnapRecall — Project Guide

## Project goal

Build a local-first application that helps users find screenshots by describing what they remember. Search should work with both text visible in an image and the visual content of the image.

The signature experience is “I barely remember it” search a user can enter an imperfect description and get a useful set of screenshot previews.

Example searches

- “the pasta recipe with tomatoes”
- “blue sneakers I wanted to buy”
- “database connection refused”
- “a dark screen with a red button”

## Intended user experience

1. The user opens the application.
2. They choose a folder containing screenshots.
3. The application indexes supported images and shows its progress.
4. The user enters a natural-language query.
5. The application displays ranked screenshot previews.
6. The user selects a result to view it and open the original file.

The interface should make it clear when indexing is in progress, complete, or has encountered an error.

## Key tools and libraries

Use Python for the application. Prefer a small, understandable set of dependencies.

 Tool or library  Purpose 
------
 Python  Core application logic 
 Streamlit  Local web interface for the first version 
 Pillow  Open and preprocess images; create previews 
 An OCR library, such as EasyOCR  Extract visible text from screenshots 
 A pretrained image–text model, such as OpenCLIP  Create comparable image and query embeddings for visual search 
 PyTorch  Run the selected embedding model 
 NumPy  Store and compare embedding vectors 
 SQLite  Store image paths, extracted text, file metadata, and indexing state 
 pytest  Test indexing and search behavior 
 Git  Track changes and document project progress 

Choose specific model versions and dependencies during implementation. Document installation requirements, model download size, and whether the app works on CPU. A GPU should be optional, not required.

## First version required behavior

### Folder indexing

- Let the user select or enter a screenshot folder.
- Support PNG and JPEG files at minimum.
- Extract visible text and generate an image embedding for each supported image.
- Save enough information to reuse the index after restarting the app.
- Show indexing progress and report files that could not be processed.
- On re-indexing, avoid reprocessing unchanged files. Detect new, changed, and missing files.
- Keep the original screenshots unchanged.

### Search

- Accept a natural-language text query.
- Search both OCR text and visual embeddings.
- Combine the two signals into a ranked list. Keep the ranking approach simple and document how it works.
- Display previews, filenames, and enough information to distinguish results.
- Allow the user to inspect a larger preview and open the original file.
- Handle empty queries and searches with no useful results gracefully.

### Privacy and storage

- Process screenshots locally by default.
- Store the index locally and make its location clear in the documentation.
- Explain that pretrained models may need an initial download; after setup, search and indexing should work offline.
- Never upload screenshots or extracted text to a service without the user’s explicit choice.

## What the first version should not do

- Do not train an image model from scratch.
- Do not require a user account, cloud service, or GPU.
- Do not delete, move, or modify original screenshots.
- Do not automatically scan the user’s entire computer; index only folders the user chooses.
- Do not claim results are always accurate or that a screenshot is safe, genuine, or relevant.
- Do not add features such as automatic screenshot capture, mobile sync, or collaboration before the core search works.
- Do not expose private screenshots or extracted text in logs or sample data.

## Interface and appearance

The app should feel like a simple personal search tool, not a dashboard full of settings.

- Use a clean, uncluttered layout with a prominent search bar.
- Show the selected folder and indexing status near the top.
- Display results as a responsive grid of screenshot thumbnails.
- Show a larger preview when a result is selected, with an Open original action.
- Include clear empty states no folder selected, indexing underway, no results, and an image that cannot be opened.
- Put advanced settings, such as re-indexing or index location, in a small sidebar or settings area.
- Keep labels straightforward and avoid displaying model or embedding details in the main search flow.

## Suggested implementation order

1. Set up the project and a basic Streamlit interface.
2. Add folder selection, image discovery, thumbnails, and persistent metadata.
3. Add OCR indexing and text search.
4. Add image and query embeddings for visual search.
5. Combine the two rankings and improve result previews.
6. Add incremental re-indexing and useful error messages.
7. Test search quality and document setup and limitations.

Each stage should leave the application runnable.

## Evaluation

Create a small, shareable sample dataset and a separate test set of approximately 50–100 screenshots and 20 representative queries where practical. Record which screenshots are relevant to each query.

Compare

- OCR text search alone.
- Visual embedding search alone.
- The combined ranking.

Report how often a relevant screenshot appears in the top one and top five results. Include queries with exact text, approximate wording, visual descriptions, and no relevant match. Use only screenshots that are safe to include in the repository.

## Engineering expectations

- Keep indexing, search, storage, and interface code in separate modules.
- Make model choices and index paths configurable without changing core logic.
- Handle corrupt images, missing files, and model-loading failures with clear messages.
- Add focused tests for indexing, changed and missing files, ranking, and empty inputs.
- Provide a README with setup, launch instructions, privacy behavior, known limitations, and a short explanation of how search works.
- Prefer a working, understandable implementation over premature optimization.

## Possible later features

Only consider these after the core experience works

- Filter by date or folder.
- Find screenshots similar to a selected image.
- Group related screenshots into topics or events.
- Use feedback to improve ranking.
- Add a timeline view.

## Current implementation review (October 2026)

The current foundation discovers PNG/JPEG files recursively, stores metadata in SQLite, creates thumbnails, incrementally scans by size and modification time, reports corrupt images, and provides filename keyword search and a Streamlit interface. OCR, image embeddings, and combined semantic search are not yet implemented. Do not present them as working features. Existing tests cover basic indexing, re-indexing, corrupt images, original preservation, and filename search.

### Priority improvements

1. **Fix folder ownership and overlapping folders.** Images currently use path as their sole primary key with one folder field. Indexing a parent and its child can reassign the same image and make it disappear from the first folder. Separate image records from folder membership (or otherwise explicitly support overlaps); test indexing and removing overlapping roots in both orders.
2. **Make scans resilient and safe.** Discovery/stat or thumbnail deletion errors can abort a scan. Do not treat a partially inaccessible scan as proof that unseen files are missing; report failures and only remove missing records after a complete successful discovery. Handle files disappearing during a scan, permission errors, and interrupted processing. Constrain thumbnail deletion to the managed thumbnail directory, and clean up stale thumbnails after failed processing. Retry previously failed items even when their fingerprint has not changed.
3. **Restore a usable session.** The database persists, but the selected folder is stored only in Streamlit session state, so reopening the app requires entering and indexing it again. Persist or offer a list of previously indexed folders. The list labelled Recent currently sorts by path, not date: order by a meaningful timestamp or change the label. Clear stale indexing reports when switching folders.
4. **Implement OCR.** Add an OCR adapter, load the model once, save extracted text and model/version status per image, and support retries and reprocessing when configuration changes. Improve tokenization beyond ASCII and test exact and multilingual text. Document first-time downloads and offline behavior.
5. **Implement visual and combined search.** Use a compatible pretrained image/text model on CPU, store normalized embeddings with model identity and dimensions, and rebuild when the model changes. Combine independently ranked text and visual results with a documented method; tune using evaluation data rather than assuming raw scores have matching scales. Handle weak matches without asserting certainty.
6. **Improve interaction and robustness.** Make the four-column results layout adapt to smaller screens, show meaningful no-match and model/indexing error states, and handle open-original failures. Streamlit runs on the host: opening a file launches on that host, so document the local-only assumption. Avoid shared SQLite connection concurrency problems across Streamlit sessions; use appropriate per-operation/session connections or synchronization.
7. **Test and document.** Add tests for overlapping roots, failed scans, permission errors, retrying errors, persistence, accurate ordering, search ranking, and future OCR/embedding integrations using small deterministic fakes. Update README and dependencies as features are added; document tested Python and model versions, CPU requirements, index location, and limitations.

### Acceptance criteria

- A user can select an existing indexed folder after restarting and search without reprocessing unchanged images.
- Indexing overlapping folders keeps each folder's membership correct; a failed or incomplete scan does not delete valid records.
- OCR finds visible words and visual search finds relevant images without matching text. Combined search and no-match behavior are evaluated on labelled examples.
- New, changed, missing, corrupt, and previously failed files are handled clearly; originals remain untouched.
- Models and indexes are local after any explicitly documented initial model download, and private screenshot contents are not logged.
- Tests run without downloading large models or requiring a GPU; evaluate real models separately.

