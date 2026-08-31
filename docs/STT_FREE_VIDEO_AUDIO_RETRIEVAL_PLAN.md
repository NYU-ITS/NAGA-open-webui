# STT-Free Audio-from-Video Retrieval Plan (Revised)

## Executive Summary

Implement audio-aware retrieval for videos without adding STT services or env-based feature toggles.
For every video file ingest path, create audio-derived text chunks (when available) alongside current visual chunks and include them in the same retrieval pipeline.

- No STT APIs/models/keys are introduced.
- No new env variables for enabling/disabling video audio features.
- No separate model/env selection for this feature; use the existing admin-config model/routing path:
  - Embeddings resolve from existing `rag.embedding_model_user` / `rag.embedding_model` config flow.
  - Captioning/fallback uses the already-configured admin RAG multimodal/LLM path for that tenant.
- `mp4` and `.mov` remain first-class supported input video containers (no optional MOV gating).
- Retrieval merges visual + audio-derived candidates and presents both sources in context while preserving current behavior.

Effort: ~5–8 engineer days depending on migration friction.

## Ground Rules (applied throughout plan)

- Audio processing is required on video ingestion and always attempted.
- `mp4`/`.mov` parsing is mandatory where container + codecs are supported.
- If audio extraction or captioning fails, ingestion continues with visual chunks only.
- Keep STT dependency count at zero.
- Keep model calls low:
  - Prefer embedded subtitles/closed captions first.
  - Only call captioning model when needed and capped to one per video segment batch strategy.

## A) Ingest → Extraction/Attachment → Embedding → Retrieval → Answer-Context Assembly

1. Ingest
   - Existing upload / knowledge ingestion paths accept video and pass through existing pipeline.
   - Add video stream inspection and optional audio extraction into temporary working files.

2. Extraction/Attachment
   - If embedded subtitles exist in container, extract by segment and normalize to text for chunking.
   - If not, generate multimodal caption summaries from short audio segments via admin-selected LLM.
   - Attach `audio_signal` chunk metadata to a sibling chunk with shared segment IDs.

3. Embedding
   - Keep existing visual `VideoEmbeddingInput` flow untouched.
   - Add new audio-derived `AudioEmbeddingInput` flow routed through existing EmbeddingService.
   - Persist both chunk types in a single chunk manifest and vector write.

4. Retrieval
   - Expand retrieval query pipeline to include `modality=audio` chunks in text retrieval candidates.
   - Preserve existing video and image retrieval ranking behavior.

5. Answer-context assembly
- Maintain existing visual reconstruction path for frame context.
- For audio chunks, attach:
  - text snippet,
  - source citation metadata,
  - timestamps,
  - and optionally reconstructed frames from same segment for visual grounding.

## B) Phased Implementation Plan

### Phase 1 — Ingestion + extraction (3–5 days)

1. Add audio metadata extraction path in a new helper module (e.g., `retrieval/video_audio.py`) without touching existing visual code.
   - ffprobe + temp extraction of audio track (`wav` or `mp3`) per file.
   - Parse embedded subtitle tracks (`mov_text`, `tx3g`, `srt`, `vtt`, `ass`, `ssa`, `subrip`, etc.).
   - Return empty/noisy tracks as unsupported with explicit warning.

2. Update `_prepare_video` in `retrieval/embedding/preparation.py`.
   - Keep current visual chunking unchanged.
   - Add audio-derived sibling chunks per segment only when text exists.
   - Use immutable shared keys (`video_file_id`, `segment_id`, `start_ms`, `end_ms`) for dedupe and join.

3. Update `retrieval/embedding/inputs.py`.
   - Add `AudioEmbeddingInput` structure and support in input-type unions.

4. Update `PreparedChunk`/manifest metadata handling (minimal scope).
   - Add modality-specific fields:
     - `modality: audio | video`
     - `content_kind: captioned_subtitle | captioned_summarized_audio | speech_absent | visual_temporal`
     - `source_type` and `source_confidence`
   - Ensure content/content hash behavior supports text-bearing audio chunks.

5. Add DB schema + model awareness.
   - Migration: extend allowed modalities to include `audio`.
   - If migration currently seeds supported modalities for providers, add `audio` where embedding/call path truly supports it.

6. Add best-effort cache key in file metadata (private key).
   - Cache extracted/parsed subtitle hashes + captioning outputs + offsets by source hash + segment bounds + prompt/model fingerprint.

### Phase 2 — Retrieval integration (1.5–2.5 days)

7. `routers/files.py` and `routers/knowledge.py`.
   - Keep STT/transcription routes untouched/unchanged.
   - Ensure video paths call shared preparation + background/job queue path and skip any explicit STT branch for video.
   - Add warning telemetry for audio extraction/captioning failures.

8. `retrieval/embedding/file_processing*` entrypoints (`file_processing.py`, `enqueuing`/reindex worker path).
   - Ensure both sync and worker paths invoke unified video+audio preparation.
   - Enforce partial success policy: audio extraction warnings do not fail full video ingest.

9. Retrieval filters/rerankers.
   - Allow `modality == audio` in text retrieval candidate flow where empty visual vectors appear.
   - Keep BM25/lexical guardrails to not introduce empty-text vectors.
   - Preserve dense/hybrid defaults; no separate ranking architecture now.

10. `retrieval/visuals.py`.
    - No major rewrite.
    - Add citation merge helper path: audio chunk with timestamps can resolve frame reconstruction through its sibling video segment metadata.
    - Keep existing frame reconstruction for visual chunks as-is.

### Phase 3 — Rollout + migration (1 day)

11. Migration/backfill.
    - Existing videos remain valid with current `video` chunks.
    - Add async reindex plan to add audio siblings for prior videos when reprocessing is acceptable.
    - For legacy jobs, fallback remains visual-only.

12. Release strategy.
    - No additional env flags to flip.
    - Canaries by admin/model compatibility and model capability matrix only.
    - If captioning model for admin has insufficient multimodal support, ingestion logs warning and stores visual-only.

## C) File-by-file action list with anchors

- `routers/files.py`
  - Shared video ingestion entrypoint: remove any model-specific STT route split for video files.
  - Add upload validation warnings metadata for unsupported audio streams and caption fallback status.
  - Preserve `preview`/`visual_summary` behavior.

- `routers/knowledge.py`
  - Same as files: no new STT branch for video.
  - Ensure knowledge-file metadata carries new audio extraction warning fields.

- `retrieval/embedding/preparation.py::_prepare_video`
  - Keep current visual chunking behavior.
  - Add optional audio extraction stage and attach audio-derived chunks with consistent segment IDs.
  - Update chunk metadata schema as above.

- `retrieval/embedding/inputs.py`
  - Add `AudioEmbeddingInput`.
  - Ensure model routing/validation accepts new input type.

- `retrieval/embedding/file_processing.py`, `retrieval/embedding/worker.py`
  - Reuse single prepare path for both immediate and async processing.
  - Ensure warnings/errors are carried as non-fatal unless no indexable chunks are produced.

- Retrieval filter/reranker modules (primarily `retrieval/utils.py`)
  - Include `audio` in allowed retrieval modality list where text exists.
  - Preserve `image`/`video` behavior unchanged.
  - Keep scoring defaults; no new ranking model.

- `retrieval/visuals.py`
  - Merge audio chunk citations with reconstructed frames from matching video segment.
  - Maintain existing ordering and citation dedupe logic.

## D) Metadata and lifecycle design

Chunk metadata keys:
- `modality`: `audio`, `video`, `image`, `text`
- `content_kind`: `captioned_subtitle`, `captioned_summarized_audio`, `visual_temporal`
- `source_type`: `embedded_subtitle`, `embedded_closed_caption`, `transcoded_audio_summary`
- `source_confidence`: `0.0 - 1.0`
- `video_file_id`: file identifier
- `video_segment_id`: deterministic segment fingerprint
- `segment_start_s` / `segment_end_s`
- `caption_model_name`: resolved admin model name for captions
- `chunking_version`: `audio_v1` / `video_temporal_v1`

Caching and dedupe:
- Cache key = hash(content_id + source fingerprint + stream fingerprint + segment bounds + model version + caption prompt fingerprint).
- If cache key unchanged, skip re-extract/recompute captioning for that segment.
- Job/job-id level idempotence remains via existing embedding job keys and manifest hashes.

Failure semantics:
- No audio track: mark warning `audio_absent` and proceed visual-only.
- Subtitle parse partial fail: continue with available subtitle tracks; caption missing segments may still attempt multimodal fallback.
- Caption model unavailable/per-failure: continue visual-only for failed segments and continue ingestion.
- If all audio extraction methods fail: ingestion status remains success with warnings.

## E) STT-free audio understanding strategy

1) Subtitle-first (preferred)
- Prefer embedded tracks extracted from container.
- Parse and align to segment boundaries.
- No external API.

2) Captioning fallback (admin multimodal model)
- Trigger only for segments with no usable subtitle text.
- Use one model call per planned segment batch.
- Generate brief semantic summaries of spoken content (not raw transcript reconstruction).
- Keep captions short and deterministic.

3) No-caption fallback
- If neither subtitles nor captioning succeed:
  - continue with visual chunks only;
  - add visible warning metadata for diagnosis;
  - never call any transcription/STT service.

## F) Retrieval query-routing strategy

- Include both `video` and `audio` modality chunks in retrieval candidate union.
- `audio` chunks should be scored with same retrieval path as text where present, but final rank order continues to prefer:
  - high semantic similarity first,
  - recency/segment order as secondary.
- Overlap handling:
  - same video segment may return both audio and visual chunks;
  - do not suppress one solely because the other exists;
  - preserve both and let downstream rank merge.
- Optional hardening later: small tie-break multiplier on `audio` for intent keywords in question text (e.g., speak/said/asked/response), deferred.

## G) Security, performance, and cost

- New worker costs:
  - ffprobe parsing and audio extraction are local I/O/CPU bounded.
  - Caption model calls bounded by segment policy and cached by key.
- Segment policy:
  - default 16s segmenting already exists for visuals.
  - keep/adjust segment alignment to avoid extra extractions.
- Queue pressure:
- Existing job queue behavior remains unchanged.
  - Add per-file warning metadata; mark job partially failed only if all embeddings fail.
- Storage:
  - One additional audio chunk per video chunk in successful subtitle/caption cases.
  - Dedupe + pruning by existing TTL/cleanup policy.
- Observability:
  - increment counters for:
    - `retrieval.video.audio_chunks_created`
    - `retrieval.video.audio_subtitle_hits`
    - `retrieval.video.audio_caption_calls`
    - `retrieval.video.audio_fallback_visual_only`
  - include segment-level warning events for ops visibility.

Expected latency impact (typical):
- No-caption/subtitle-only: low, local extraction only.
- Captioning fallback: +1 model call per segment batch.
- No extra embedding model type because embeddings still go through the existing selected provider/model.

## H) `mp4` / `.mov` handling

- Support both formats by default in this feature.
- Container handling:
  - Accept `video/mp4` and `video/quicktime`/`mov` where decode + stream maps allow.
  - Validate codec/container compatibility with ffprobe before processing.
  - For unsupported video-only container edge cases, fail fast with a clear reason and preserve existing upload behavior.
- No separate feature flag for MOV support.
- Never transcode unless already necessary for extraction pipeline in existing flow.

## I) Rollout and migration

- Backward-compatible:
  - current video retrieval remains unchanged.
  - existing embeddings continue to work.
  - no schema break for UI behavior.
- Reprocess path:
  - start with newly uploaded files only,
  - optionally requeue older videos in maintenance windows.
- Config:
  - no new env vars for this feature.
  - model/LLM behavior remains admin-config driven from existing settings.

## Validation checklist

- With embedded captions: spoken-content questions return audio-derived citations + frame context.
- Without captions: fallback path returns visual-only results without failure.
- Silent/no-audio videos: ingest succeeds with clear warning and no crash.
- Long videos: audio extraction and indexing run under background queue and complete incrementally.
- Mixed modalities in results: answer context contains both visual and audio-derived chunks where relevant.
- Observability:
  - warnings emitted for unsupported codecs, subtitle parse misses, caption model fallback.
  - metrics/events show ratio of visual-only vs audio-enriched chunks.

## Risk register

- High: Admin-configured caption model lacks required multimodal audio capability.
  - Mitigation: capability check + clear warning + visual-only safe mode.
- High: Subtitle parsing for uncommon container variants fails.
  - Mitigation: robust parser selection + fallback to captioning + explicit segment-level warnings.
- Medium: chunk volume increases.
  - Mitigation: segment alignment, dedupe, and warnings-driven triage.
- Medium: embedding vector search includes extra non-visual docs.
  - Mitigation: existing filters, no schema changes to query path, conservative text guards.
- Low: codec/container regressions on rare MOV variants.
  - Mitigation: ffprobe-first validation and clear skip message instead of silent failure.

## Definition of Done

- Video ingestion always attempts audio-aware extraction for captions and generates audio-derived chunks when possible.
- Visual chunk path remains unchanged and fully backward-compatible.
- Retrieval returns audio-derived results for audio-relevant prompts and remains robust when audio processing is unavailable.
- No STT dependency added.
- No new runtime toggles required.
- `.mp4` and `.mov` are treated as supported containers.
- Migration and observability artifacts are in place.
