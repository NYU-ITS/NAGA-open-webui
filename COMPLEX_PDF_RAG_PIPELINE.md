# Complex PDF RAG Pipeline

## Purpose

This document explains how the new complex PDF pipeline works in NAGA/Open WebUI for RAG ingestion, including:

- where PDF images are extracted and represented,
- how image descriptions are generated via an LLM,
- how extracted content is stored/chunked/embedded,
- all important environment/config variables developers should know.

## High-Level Flow

1. A PDF is uploaded and stored via `Storage.upload_file(...)`.
2. `process_file` schedules ingestion (RQ job queue if available, otherwise FastAPI background task).
3. `_process_file_sync` builds a `Loader(...)` and calls `loader.load(...)`.
4. For PDF files, `Loader._get_loader(...)` routes to:
  - `ComplexPDFLoader` (default path), or
  - `PyPDFLoader` fallback depending on config/conditions.
5. `ComplexPDFLoader` extracts:
  - text blocks,
  - table blocks (as markdown),
  - image crops (in-memory, base64 PNG).
6. Image crops are passed to `describe_images_with_task_model(...)`, which calls chat completion with multimodal payload.
7. Each image crop carries a nearby-text snippet from the same page so the vision model can use document terminology from surrounding text while staying grounded in the visible crop.
8. Figure descriptions are inserted into page content as `[Figure N | Page M] ...`.
9. Combined page content is saved to `file.data.content`, chunked, embedded, and written to vector collections.

## Code Entry Points

- Upload + process kickoff:
  - `backend/open_webui/routers/files.py` (`upload_file`)
  - `backend/open_webui/routers/retrieval.py` (`process_file`, `_process_file_sync`)
- Loader selection:
  - `backend/open_webui/retrieval/loaders/main.py` (`Loader._get_loader`)
- Complex PDF parser:
  - `backend/open_webui/retrieval/loaders/pdf_complex.py` (`ComplexPDFLoader`)
- Image description LLM call:
  - `backend/open_webui/retrieval/loaders/pdf_complex.py` (`describe_images_with_task_model`)

## Where Uploaded PDFs and Extracted Images Live

### Uploaded PDF storage

- Upload path is `UPLOAD_DIR = {DATA_DIR}/uploads`.
- Defaults:
  - `DATA_DIR` -> `backend/data`
  - PDF file path in container -> `/app/backend/data/uploads/...`

Configured in:

- `backend/open_webui/env.py` (`DATA_DIR`)
- `backend/open_webui/config.py` (`UPLOAD_DIR`)
- `backend/open_webui/storage/provider.py` (`LocalStorageProvider.upload_file`)

### Extracted image storage

Extracted PDF images are **not persisted as separate files** by the complex parser.

- They are held in-memory as `PageImage` objects:
  - `image_id`, `top_norm`, `width`, `height`, `png_base64`, `context_text`.
- `png_base64` is inserted directly into the LLM request as `data:image/png;base64,...`.

This happens in:

- `ComplexPDFLoader._extract_page_images(...)`
- `describe_images_with_task_model(...)` payload assembly

## Complex PDF Parsing Details

`ComplexPDFLoader` performs a merged pass per page:

- `pdfplumber` for tables + words/text structure.
- `fitz` (PyMuPDF) for image extraction and cropped rendering.

Important behavior:

- Small images are filtered out (`width < 64`, `height < 64`, `area < 10000`).
- Per-page image cap: `max_images_per_page` (default 6).
- Per-document image budget: `max_images_per_document` (default 80).
- Blocks are merged in top-to-bottom order (`top_norm`) across text/tables/images.
- Each extracted image now gets a nearby text window from the same page before description generation.
- Page metadata includes:
  - `table_count`
  - `image_count`
  - `parse_warnings`

If description is missing for an image, fallback text is inserted:

- `"Image content could not be described."`

## Image Description Model Selection

`describe_images_with_task_model(...)` chooses model in this order:

1. `TASK_MODEL_EXTERNAL` for the current admin/user (if set and accessible),
2. `TASK_MODEL` (global),
3. fallback guess from accessible models using keywords (`gpt-4o`, `gemini`, `claude`, `vision`, `multimodal`), excluding embedding/rerank models.

Then it:

- checks vision capability metadata if present,
- builds a multimodal chat payload that pairs each image with nearby page text context,
- calls `generate_chat_completion(...)`,
- expects JSON array output, with text fallback parsing if needed.

Operational log line to verify usage:

- `PDF image description request | user=... | page=... | model=... | images=... | context_chars=...`

## Current Image Description Prompt Location

The exact prompt used for PDF image description is hardcoded in:

- `backend/open_webui/retrieval/loaders/pdf_complex.py`
- helper: `_build_image_description_content(...)`

This is the place to edit if you want different description style/length/format.

Current prompt behavior:

- explicitly tells the model to stay grounded in visible evidence,
- uses nearby page text for terminology and topic grounding,
- tells the model not to invent hands/people/extra objects unless clearly visible,
- tells the model not to guess a different instrument when the crop is ambiguous.

## Fallback and Routing Behavior

For `.pdf` in `Loader._get_loader(...)`:

- Uses `ComplexPDFLoader` when:
  - `RAG_PDF_COMPLEX_PARSER_ENABLED=true` (default),
  - extraction engine is empty (`CONTENT_EXTRACTION_ENGINE=""` in practice).
- Falls back to `PyPDFLoader(extract_images=PDF_EXTRACT_IMAGES)` when:
  - complex parser is disabled,
  - or extraction engine directs another route,
  - or complex parser import fails.

For non-PDF files:

- existing Tika / Azure Document Intelligence / unstructured loaders remain in place.

## RQ Worker Path vs Background Task Path

Both paths call the same loader pipeline.

- API/background path: `routers/retrieval.py` -> `_process_file_sync`.
- RQ path: `workers/file_processor.py` (uses same `Loader` and passes `REQUEST` + `USER`).

Important worker note:

- Worker initializes app config and now respects `PDF_EXTRACT_IMAGES` from config/env.

## Config and Environment Variables to Know

### Complex PDF + extraction routing

- `RAG_PDF_COMPLEX_PARSER_ENABLED` (env-only, default `True`)
  - Controls whether complex parser is considered.
- `CONTENT_EXTRACTION_ENGINE` (persistent config / env seed)
  - Complex parser is used only when this is effectively empty in PDF path.
- `PDF_EXTRACT_IMAGES` (persistent config / env seed, default `False`)
  - Used by PyPDF fallback; also now consistently passed in retrieval + worker paths.
- `TIKA_SERVER_URL` (default `http://tika:9998`)
- `DOCUMENT_INTELLIGENCE_ENDPOINT`
- `DOCUMENT_INTELLIGENCE_KEY`

### Image-description model selection

- `TASK_MODEL` (global task model)
- `TASK_MODEL_EXTERNAL` (user/admin-scoped task model)

### Ingestion execution and locking

- `ENABLE_JOB_QUEUE` (default `True`)
  - `True`: uses Redis RQ worker.
  - `False`: falls back to FastAPI `BackgroundTasks`.
- `REDIS_URL` (default `redis://localhost:6379/0`)
- `WEBSOCKET_REDIS_URL` (defaults to `REDIS_URL`)
- `FILE_PROCESSING_LOCK_TIMEOUT` (used in `process_file`, default `3600`)
- `JOB_TIMEOUT` (default `3600`)
- `JOB_MAX_RETRIES` (default `3`)

### Chunking + embedding (post-extraction)

- `BYPASS_EMBEDDING_AND_RETRIEVAL` (default `False`)
- `RAG_TEXT_SPLITTER`
- `CHUNK_SIZE` (default `1000`, user-scoped)
- `CHUNK_OVERLAP` (default `200`, user-scoped)
- `RAG_EMBEDDING_ENGINE` (default `portkey`)
- `RAG_EMBEDDING_MODEL_USER` (admin/user-scoped embedding model)
- `RAG_EMBEDDING_BATCH_SIZE` (default `1`)
- `RAG_OPENAI_API_BASE_URL`
- `RAG_OPENAI_API_KEY` (scoped in app config for owner/admin usage)

## Important Recent Pipeline Changes

These are important behavior changes in this branch:

1. `PDF_EXTRACT_IMAGES` is now respected end-to-end (no forced disable at app startup).
2. Retrieval + worker loader calls now pass `PDF_EXTRACT_IMAGES` from runtime config.
3. `PyPDFLoader` fallback path now honors `PDF_EXTRACT_IMAGES`.
4. Complex parser image description path includes model fallback logic (vision-model guess) and better logging.
5. Parsing robustness improved for non-JSON model responses when mapping descriptions.
6. PostgreSQL cursor ordering issue in file-processing flow was fixed (`fetchone()` before commit).

## Recommended Debug Log Signals

When validating this pipeline, watch for:

- `[LOADER] PDF_DETECTED | ... | loader=ComplexPDFLoader`
- `PDF image description fallback model selected ...`
- `PDF image description request | ...`
- `[Content Extraction Result] ... pages_extracted=... total_chars=...`
- Embedding diagnostics `sample_items` / `sample_texts` showing `[Figure ...]` content.

If descriptions are missing, also check for:

- `PDF image description returned empty result`
- `image description failed`
- placeholder text in embedding samples: `"Image content could not be described."`
