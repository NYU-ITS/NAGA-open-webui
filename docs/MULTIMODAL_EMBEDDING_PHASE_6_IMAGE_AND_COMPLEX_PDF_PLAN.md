# Phase 6 — Direct Multimodal Image and Complex PDF Support

## Summary

Phase 6 will add direct image embeddings for:

- Standalone PNG and JPEG files uploaded to Knowledge or chat.
- Qualifying raster figures extracted from PDFs.
- Full table crops when a PDF table contains qualifying raster images.

This is the detailed implementation plan for Phase 6 in `docs/MULTI_PROVIDER_MULTIMODAL_EMBEDDING_ACTION_PLAN_14_DAY_ESTIMATES.md`. It expands the earlier standalone-image plan to cover PDFs with visual content.

All text, table-text, and image vectors governed by an admin will use that admin's selected embedding model and the same model-aware vector space. The approved first multimodal model is `@vertexai/gemini-embedding-2` through Portkey with 1536-dimensional text and image vectors.

There will be no OCR, image captioning, vision-LLM description generation, filename inference, or text fallback for an image chunk. When the selected admin model supports images, every qualifying visual admitted by the extraction rules must be embedded directly. A provider or rendering failure must not silently leave a partially indexed multimodal PDF.

## Source Branch Audit and Reuse Boundary

This plan was prepared against:

- Current implementation branch: `feat/multimodal-embeddings` at `5673f62a1f`.
- Reference worktree: `../complex-pdf-processing`, branch `feat/complex-pdf-processing` at `ddc3b3817b`.

The reference branch predates the current model registry, frozen admin/model context, model-aware vector repository, reindex jobs, and retrieval-readiness gate. Do not merge or cherry-pick its worker or router wholesale.

### Reuse from `feat/complex-pdf-processing`

- `pdfplumber` word and table extraction.
- Table conversion to Markdown and removal of table words from surrounding text.
- PyMuPDF image enumeration through `page.get_images(full=True)` and `page.get_image_rects()`.
- Existing qualifying-figure filters: at least 64 by 64 PDF-coordinate units and area at least 10,000.
- Two-times PyMuPDF crop rendering to PNG with `alpha=False`.
- Page/document visual guardrails and deterministic page order.
- Normalized vertical positioning used to preserve page reading order.
- Per-page parse warnings and table/figure counts.

### Do not port

- `describe_pdf_images_via_chat()` or any chat-completion call from a loader or worker.
- The image-description prompt, JSON response parsing, generated descriptions, or placeholder descriptions.
- `PDF_IMAGE_DESCRIPTION_MODEL`, `PDF_IMAGE_DESCRIPTION_MODEL_USER`, model guessing, or user-scoped description-model APIs.
- Base64-bearing `PageImage` records; extraction should use raw bytes in memory.
- Request/user objects in the PDF loader. Extraction must be deterministic and independent of answer-model access.
- Legacy worker logging, request mocks, embedding functions, or vector writes. The reference worker is not model-aware and contains logging patterns that violate the current credential-safety contract.

### Additional work not implemented on the reference branch

The reference branch extracts tables as Markdown and raster images as standalone figure crops. Its `docs/SELECTIVE_PDF_VISION_PROCESSING_PLAN.md` describes, but does not implement:

- Normalized full bounding boxes for figures and tables.
- Figure-to-table overlap classification.
- Full image-bearing table crops.
- Suppression of table-contained images from the standalone-figure list.
- Durable visual identities and retrieval-time image reconstruction.
- File-status warnings for visual extraction.

These items are part of this Phase 6 implementation.

## Target Behavior

| Input | Selected admin embedding model | Result |
| --- | --- | --- |
| Standalone valid PNG/JPEG | Supports `image` | Store file and create one direct image vector. |
| Standalone valid PNG/JPEG | Text only | Store file and record a visible `embedding_modality_unsupported` processing error. |
| GIF, WebP, AVIF, or invalid standalone image | Any | Reject visibly; do not convert, caption, or OCR it. |
| PDF with text and no qualifying visuals | Supports `text` | Extract, split, and embed text/table Markdown normally. |
| PDF with text and qualifying visuals | Supports `text` and `image` | Embed text/table Markdown as text and every qualifying figure/table crop directly as an image. |
| PDF with text and qualifying visuals | Text only | Embed the available text/table Markdown, omit visuals, and persist a visible warning that a multimodal embedding model is required. |
| PDF with only qualifying visuals | Supports `image` | Succeed with image chunks even when extracted text is empty. |
| PDF with only qualifying visuals | Text only | Fail visibly because there is no supported content to index. |

A multimodal PDF indexing attempt is atomic at the file/projection level: prepare all chunks and generate all vectors before reconciling any target vectors. If any qualifying visual cannot be rendered or embedded, the attempt fails and the previous active projection remains unchanged.

## Implementation Plan

### 1. Register and verify the multimodal model

- Add an expand-only Alembic seed for:
  - ID: `embmdl-portkey-vertexai-gemini-embedding-2-1536`
  - Provider: `portkey`
  - Model name: `@vertexai/gemini-embedding-2`
  - Display name: `Vertex AI Gemini Embedding 2`
  - Dimension: `1536`
  - Modalities: `['text', 'image']`
  - Status: `enabled`
- Reuse the existing 1536-dimensional PGVector table; do not create a separate image table or pad/truncate vectors.
- Do not automatically change any admin's selected model.
- Before rollout, run a Portkey canary for a text input, a PNG, and a JPEG using the exact alias and 1536 dimensions. If the gateway contract fails, block rollout rather than substituting a model.

### 2. Extend the Portkey embedding adapter

- Make `ImageEmbeddingInput` bytes-only with canonical `image/png` or `image/jpeg` MIME.
- Keep the existing text-only Portkey SDK path unchanged for existing models.
- Add the multimodal `/embeddings` request path:
  - Text inputs may be batched.
  - Send one image per provider request.
  - Encode Base64 only inside the provider adapter and omit a data-URL prefix.
  - Use the Portkey/Vertex shape `input: [{"text": "", "image": {"base64": "...", "mimeType": "image/png"}}]` and request `dimensions: 1536`.
  - Parse OpenAI-style `data[].embedding` and Vertex-style `predictions[].textEmbedding` or `predictions[].imageEmbedding`.
  - Restore logical input order after modality-specific calls.
- Verify the final wire contract against the [Portkey Vertex AI embeddings guide](https://portkey.ai/docs/integrations/llms/vertex-ai/embeddings), the [Portkey embeddings API](https://portkey.ai/docs/api-reference/inference-api/embeddings), and the required internal-gateway canary.
- Preserve the service-level modality, count, dimension, numeric, and finite-value validation.
- A valid image provider failure remains `embedding_provider_failed`; never retry it as text.
- Remove raw exception messages, response bodies, image bytes, Base64, credentials, and provider payloads from logs and durable errors.

### 3. Port the PDF extractor as a typed, deterministic component

- Add `pdfplumber==0.11.4` and `pymupdf==1.24.11` as direct backend dependencies and update the lock/exported requirements through the Docker workflow.
- Refactor the reusable branch code into a pure `ComplexPDFExtractor` that returns structured blocks instead of LangChain documents containing generated descriptions.
- Define two internal block types:
  - Text block: text, `paragraph` or `table_text`, zero-based page index, page-local sequence, normalized vertical order, and optional bounding box.
  - Visual block: raw PNG bytes, `figure` or `table_image`, zero-based page index, page-local sequence, normalized vertical order, full PDF-coordinate bounding box, rendered pixel dimensions, and byte SHA-256.
- Normalize pdfplumber and PyMuPDF geometry into one full-page coordinate system, accounting for crop boxes and page rotation before comparing or rendering rectangles.
- Preserve the existing standalone-figure qualification thresholds.
- Replace silent truncation with visible limits:
  - `RAG_PDF_MAX_VISUALS_PER_PAGE`, default `6`.
  - `RAG_PDF_MAX_VISUALS_PER_DOCUMENT`, default `80`.
  - An exceeded limit fails processing with `pdf_visual_limit_exceeded`; it must not index only the first N visuals.
- Treat one image-bearing table crop as one visual regardless of the number of contained images.

### 4. Classify and render image-bearing tables

For each page:

1. Detect tables and retain their pdfplumber Markdown and normalized bounding boxes.
2. Enumerate qualifying PyMuPDF raster image placements with their full bounding boxes.
3. Assign an image to a table when its center is inside the table or at least 50 percent of the image area overlaps the table.
4. For every table with one or more assigned images:
   - Render the complete table rectangle as a two-times PNG with two PDF-point padding, clipped to the page.
   - Create one `table_image` visual block.
   - Keep the extracted Markdown as a separate `table_text` block when it is non-empty.
5. Do not also emit assigned images as standalone figures.
6. Render remaining qualifying images as `figure` blocks.
7. Order paragraph, table-text, table-image, and figure blocks deterministically by page, normalized vertical position, element type, and source sequence.

Vector artwork and images below the reference branch's qualification thresholds remain outside Phase 6. Fully flattened/scanned pages are supported only when PyMuPDF exposes the page raster as a qualifying image placement; no rasterization-of-every-page or OCR fallback is added.

### 5. Create one shared mixed-modality preparation pipeline

- Add a shared `prepare_file_for_embedding()` path used by:
  - Synchronous/background upload processing.
  - Normal RQ file processing.
  - Model-change and retry reindex jobs.
- Return ordered prepared chunks containing:
  - Persisted chunk content and content type.
  - An aligned `TextEmbeddingInput` or `ImageEmbeddingInput`.
  - Explicit content SHA-256.
  - Per-item vector modality.
  - Safe source metadata and private reconstruction metadata.
- Split only paragraph and table-Markdown blocks with the canonical admin chunk settings. Never pass image blocks through a text splitter.
- Create exactly one image chunk per standalone image, PDF figure, or image-bearing table crop:
  - `content=''`
  - `content_type='image'`
  - `content_sha256` from rendered/source image bytes
  - vector modality `image`
- Keep `file.data.content` limited to extracted PDF text and table Markdown. Do not add generated descriptions, placeholders, Base64, or empty figure markers.
- Replace text-only empty-content checks with `no prepared chunks`. A visual-only PDF is valid for an image-capable selected model.
- Generate every embedding before persisting/reconciling the target vector projection. Preserve deterministic chunk order and model-aware idempotent upserts.
- Update model-aware vector construction to accept per-item modality rather than one batch-level `text` value.
- Normalize the current chunk metadata contract so all paths use `chunk_metadata`, and allow `RagChunk.insert_chunks()` to accept a validated caller-provided SHA-256 for image bytes.

### 6. Preserve PDF visual bytes through deterministic reconstruction

Do not create duplicate child files or persist Base64/crop blobs. The uploaded PDF remains the canonical object in the existing storage provider.

- Assign each visual an opaque deterministic ID such as `pdfvis_<sha256>` computed from source-file SHA-256, extraction version, page index, visual kind, source sequence, normalized bounding box, and render recipe.
- Assign standalone images a corresponding stable `fileimg_<sha256>` identity derived from the immutable file ID and source-byte hash.
- Compute the source-file SHA-256 from the original bytes loaded from `Storage`; do not reuse the current extracted-text hash as source identity.
- Persist a private visual reconstruction record inside `rag_chunks.chunk_metadata` and vector metadata:
  - Parent `file_id`.
  - `visual_asset_id`.
  - Extraction/render version.
  - Page index.
  - Visual kind and page-local sequence.
  - Bounding box.
  - Render scale, output format, and alpha setting.
  - Rendered pixel dimensions and image SHA-256.
- Never persist a local file path, object-store key, signed URL, or Base64 in chunk/vector metadata.
- At retrieval time, resolve the authorized parent file, load it through `Storage`, open each parent PDF once per request, validate the saved rectangle against the page, and reproduce the PNG crop using the saved render recipe.
- Standalone images continue to resolve directly through their existing `file_id` and storage record.
- Because PDF crops are reconstructed from the parent file, existing file deletion cascades remove chunks/vectors without requiring derived-object cleanup.

### 7. Make extraction and reindex cache-safe

- Add an extraction version such as `complex_pdf_visual_v1` and persist it with the raw source-file hash and visual summary.
- Treat cached `file.data.content` and existing vector documents as insufficient for multimodal PDF ingestion.
- Reuse persisted text/visual chunk manifests only when source SHA-256 and extraction version both match. Reconstruct image inputs from the original PDF and saved visual references.
- Force full re-extraction when:
  - Existing chunks predate the visual extraction version.
  - An admin moves from a text-only model to the multimodal model.
  - The source hash, extraction version, render recipe, or chunk settings change.
- Fix shared-reader assumptions while consolidating the paths: read content type from `file.meta.content_type` and use the supported `Storage` API rather than the current reindex worker's nonexistent `Storage.file_exists()` call.

### 8. Record safe status, warnings, and failures

- Add stable failure codes:
  - `embedding_image_format_unsupported`
  - `embedding_image_invalid`
  - `pdf_visual_extraction_failed`
  - `pdf_visual_limit_exceeded`
  - Reuse `embedding_modality_unsupported` and `embedding_provider_failed`.
- Extend normal file metadata and `GET /files/{id}/status` with:
  - `processing_error_code`
  - Sanitized `processing_error`
  - Deduplicated `processing_warnings: string[]`
  - `visual_summary` containing figure, image-bearing-table, image-chunk, and text-chunk counts.
- Map the same stable codes into `embedding_job_files` for reindex/retry failures.
- Under a multimodal selected model, table detection, visual enumeration, crop rendering, or any image embedding failure fails the file attempt rather than producing a partial active projection.
- Under a text-only selected model, a mixed text/visual PDF may complete with text vectors and a visible `pdf_visuals_require_multimodal_model` warning. A standalone image or visual-only PDF fails.
- Remove the stale `PDF_IMAGE_DESCRIPTION_MODEL` and separate image-model comments from `docker-compose.local.yaml`. Keep PyPDFLoader image extraction disabled; the new PyMuPDF path owns PDF visuals.

### 9. Retrieve and deliver image hits safely

- Generate text query embeddings with the same selected multimodal model used for PDF text and visual vectors.
- Use model-aware dense retrieval for multimodal model spaces. Keep current hybrid/reranking behavior for text-only model spaces and never feed empty image chunks to BM25 or a text reranker.
- Change result merging/deduplication from document-text hashes to stable `rag_chunk_id` or `visual_asset_id`; all image chunks have empty text and must not collapse into one result.
- Return safe visual metadata with image hits:
  - Parent file ID and display name.
  - `visual_asset_id`.
  - `standalone_image`, `pdf_figure`, or `pdf_table` kind.
  - One-based page and element number for PDF visuals.
  - MIME and rendered dimensions.
- Do not return private bounding boxes, render recipes, source hashes, storage paths, or Base64 to the browser.
- Across retrieved image hits:
  - Sort by dense distance.
  - Deduplicate by `visual_asset_id`, not parent `file_id`, so different figures in one PDF remain eligible.
  - Cap images attached to the answer model at the user's effective `RAG_TOP_K`.
- For a server-confirmed vision-capable answer model, load/reconstruct authorized image hits and append them as `image_url` parts to the latest user message.
- For a non-vision answer model, omit image-only hits and continue with usable text/table hits. Emit a safe warning for explicit standalone-image attachments.
- Build the textual RAG prompt only from non-empty text/table chunks. Image citations should display the parent PDF name, page, and figure/table number without pretending an empty image chunk supplied text.
- Apply the same image cap in full-context mode; select PDF visuals in deterministic page order when no similarity ranking is available.

### 10. Update standalone-image and upload UI behavior

- Restrict standalone image uploads to PNG and JPEG while leaving existing non-image document types, including PDF, available.
- Upload chat images through the existing file API instead of persisting inline Base64 in chat history.
- Persist file descriptors with `type`, `id`, `name`, MIME, size, processing status, and collection name; build previews with transient object URLs or the authenticated file-content API.
- Include image file IDs in `chatFiles` and completion metadata so inventory and reindexing use the same admin context as other chat files.
- Remove unconditional client-side forwarding of every historical image to the answer model. Only backend-retrieved and authorized images are sent.
- Require a non-empty text prompt with a newly attached standalone image.
- Block submission while an attachment is pending or processing, and require removal/retry for failed attachments.
- Do not change a timed-out poll to `uploaded`; retain a truthful processing state and allow status refresh, which is important for complex PDFs.
- Reuse existing file/reindex status components and styles. Show parse warnings and visual summaries without adding frontend PDF/image-processing logic.

## Public and Internal Interface Changes

### Embedding input

```python
@dataclass(frozen=True)
class ImageEmbeddingInput:
    image: bytes
    mime_type: Literal["image/png", "image/jpeg"]
    modality: Literal["image"] = "image"
```

### Prepared chunk

The shared prepared-chunk type must align one persisted chunk, one embedding input, one SHA-256, one modality, and one metadata record. Callers must not rebuild these parallel lists independently.

### PDF visual identity

`visual_asset_id` is the stable deduplication/reconstruction identity. The parent PDF `file_id` remains the authorization and storage identity. Multiple figures from the same PDF therefore remain distinct retrieval candidates.

### File status response

`GET /files/{id}/status` adds `processing_error_code`, `processing_warnings`, and `visual_summary`. Existing files return `null`, `[]`, and zero/unknown counts as appropriate.

### Retrieved source metadata

Image-source responses add safe content kind, visual asset ID, parent filename, page/element number, MIME, and dimensions. The server retains all reconstruction fields privately.

## Verification Plan

Do not create or run tests without separate explicit permission. When authorized, run all validation inside containers using only `docker-compose.local.yaml`.

### Extractor scenarios

- Text-only PDF and text-only table preserve current text behavior.
- Standalone figure creates one PNG visual block and no generated description.
- Image-bearing table produces one table-image block plus its Markdown text block.
- Multiple images inside one table produce one table crop and no duplicate figure blocks.
- Images outside tables remain standalone figures.
- Center-inside and 50-percent-overlap boundary cases classify deterministically.
- Rotated/cropped pages render correct rectangles and reading order.
- Small/decorative images remain outside the qualifying set.
- Exceeding either visual limit fails visibly rather than truncating.
- Vector-only artwork and unsupported flattened-page cases follow the documented scope.

### Ingestion and model scenarios

- Knowledge and chat PDFs resolve the correct governing admin and frozen model.
- Mixed text/image chunks retain aligned indices, hashes, metadata, and per-item modality.
- PNG, JPEG, PDF figure, and PDF table crops produce exact 1536-dimensional image vectors.
- A multimodal provider failure for any visual leaves no partial target projection.
- A text-only admin receives the defined mixed-PDF warning and standalone/visual-only errors.
- A text-only-to-multimodal model change re-extracts existing PDFs instead of trusting cached text.
- Retry and reindex remain idempotent, and source/version changes invalidate stale manifests.
- Deleting a parent PDF removes its chunks and vectors and leaves no derived storage object.

### Retrieval and chat scenarios

- Model/admin/RBAC filters apply equally to text and image vectors.
- Multiple figures from one PDF survive deduplication; duplicate collection projections do not.
- Mixed retrieval orders image hits by dense distance and respects effective `RAG_TOP_K`.
- Vision answer models receive reconstructed, authorized crops; non-vision models receive no image bytes.
- Image citations identify PDF/page/figure or table accurately.
- Full-context mode applies the image cap.
- No API, event, log, RQ payload, or chat record exposes Base64, credentials, private geometry, or storage paths.

### Frontend scenarios

- Chat PNG/JPEG uploads persist file references rather than Base64.
- Unsupported standalone image formats fail visibly.
- Processing, warning, error, retry/removal, and polling-timeout states remain truthful.
- Knowledge and chat uploads show PDF visual counts and warnings using existing components.

## Rollout and Rollback

1. Verify the Portkey text/PNG/JPEG contract in the Docker environment.
2. Deploy the registry seed, provider support, dependencies, typed extractor, and status contracts without changing admin selections.
3. Select the multimodal model for one pilot admin and run the existing full reindex.
4. Compare source-file counts, text/image chunk counts, vectors by modality, failures, latency, and representative text/figure/table queries.
5. Confirm retrieved PDF visuals reach only authorized vision-capable answer models.
6. Expand admin by admin through the existing model-change workflow.

Rollback switches the admin back to the previous text model and runs the normal reindex. Standalone images and visual-only PDFs become visible unsupported-content failures; mixed PDFs retain their text/table vectors with the defined warning. No PDF crop cleanup is needed because the source PDF remains the only stored object.

## Assumptions

- “All PDF images” means every qualifying raster placement or image-bearing table admitted by the reused size rules and configured safety ceilings. Limit overflow fails the file; it is never silently partial.
- PNG/JPEG are the only standalone image formats. PDF-derived visuals are always rendered to PNG before embedding.
- Image-bearing tables receive both a text vector when pdfplumber returns Markdown and a direct table-crop image vector.
- There is no OCR, caption generation, image-description LLM, or image-to-text embedding fallback.
- The complex PDF parser is the canonical PDF path when `RAG_PDF_COMPLEX_PARSER_ENABLED=true`; PyPDFLoader remains the text-only fallback when explicitly disabled.
- The original stored PDF plus a deterministic visual reference is sufficient to reconstruct retrieved crops, so Phase 6 adds no derived-image table or duplicate crop storage.
- Multimodal model spaces use dense retrieval in Phase 6; extending hybrid/reranking across modalities remains separate work.
- Provider and answer-model image traffic continues through Portkey.
