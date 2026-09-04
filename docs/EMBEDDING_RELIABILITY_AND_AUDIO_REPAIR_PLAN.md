# Embedding Reliability and Audio Repair Plan

## Objective

Make multimodal embedding jobs resilient to transient provider failures, preserve usable visual retrieval when audio embedding is degraded, and provide a knowledge-base-only repair path for failed audio chunks. Improve diagnostics without exposing file contents, prompts, credentials, or provider response bodies.

## 1. Configurable provider reliability

Add an administrator-controlled **Embedding Provider Reliability** section to the Documents settings page:

- Maximum attempts: default `3`, range `1–5`.
- Connection timeout: default `10` seconds, range `1–60`.
- Read timeout: default `120` seconds, range `30–600`.
- Backoff: `2` seconds, then `4` seconds, with up to `25%` jitter. Honor `Retry-After`, capped at `120` seconds.

Retry all Portkey modalities, including text, image, audio, and video, for connection failures, timeouts, and HTTP `408`, `429`, `500`, `502`, `503`, and `504`. Do not retry authentication failures, other client errors, malformed responses, or invalid vectors.

Snapshot this policy when an embedding operation is dispatched so a settings change cannot alter an in-flight job. These reliability settings are operational policy, not part of the embedding recipe, and must not trigger a reindex.

## 2. Correct settings and reindex behavior

Change the Documents save flow so a model-change reindex is requested only when an embedding-recipe setting actually changes. The embedding model and chunk/extraction settings require a deliberate reindex; upload limits, retrieval settings, API keys, and reliability settings do not.

Make selecting the same target model idempotent, including when the previous model-change job ended partially failed. A separate retry/repair action should be used instead of creating another full reindex job. Saving credentials or batch settings must not implicitly reindex knowledge bases.

## 3. Adaptive audio recovery

The current pipeline already divides extracted audio into chunks, but an individual chunk can still exceed the provider's practical request or processing limits. Use a two-stage recovery policy:

1. Retry the original audio chunk for transient failures.
2. If repeated attempts end in a timeout or payload-too-large response, split that chunk into smaller time ranges and embed the resulting subchunks independently.

Limit recursive splitting to a small, configurable depth or a minimum duration (for example, two splits or `5–10` seconds). Do not split permanent errors such as authentication or invalid-model failures. Preserve exact offsets and source hashes for every subchunk so repaired vectors can be traced and replaced safely.

## 4. Degraded audio state

Represent audio processing as a structured outcome rather than only a warning string. Persist private repair state containing the source hash, active model, extraction/chunking version, failed chunk indices or offsets, and timestamps. Never store raw provider responses, audio bytes, transcripts, or request bodies in this state.

Expose a safe public `audio_embedding` summary such as:

```json
{
  "status": "degraded",
  "total_chunks": 3,
  "embedded_chunks": 2,
  "failed_chunks": 1,
  "repairable": true,
  "updated_at": "2026-09-04T00:00:00Z"
}
```

Use statuses such as `complete`, `degraded`, `repairing`, and `not_applicable`. Keep existing warning semantics, but make it clear that visual retrieval remains available when only audio failed.

## 5. Knowledge-base audio repair endpoint

Add `POST /api/v1/knowledge/{knowledge_id}/file/{file_id}/audio/repair`.

- Require knowledge-base write access or membership authorization.
- Return `202 Accepted` for queued or active repairs.
- Make repeated requests idempotent.
- Reject stale source hashes or model versions with a stable `audio_repair_state_stale` error.
- Return `audio_repair_not_required` when no repair is needed and `audio_repair_unavailable` when the failed state cannot be reconstructed.
- Repair only failed audio chunks; do not re-embed successful audio or video chunks.
- Use non-destructive upserts and commit successful repairs incrementally.
- Use a lease/heartbeat so abandoned repairs can be retried safely.
- Lazily reconstruct repair state for legacy files when the source and chunking metadata are still available.
- Promote or repair only against the currently active model; never mix vectors from an unintended model.

Add a knowledge-base UI action such as **Retry audio** with a clear degraded-state message. Chat uploads should show the warning but should not expose the knowledge-base repair action.

## 6. Model and retrieval state consistency

Separate the configured target model, the durable active model, and the effective model available for each file or knowledge-base scope. During a partial reindex, completed target-model sources may be usable while failed sources remain unavailable; the UI must not label the entire system with the old model when successful target vectors are already being served.

Show the effective model and scope explicitly, and prevent stale model labels from being derived solely from the global active-model field.

## 7. Structured logs and metrics

Emit structured events for each provider request and file outcome with:

- correlation/call ID;
- provider and model ID;
- modality and operation (`initial`, `reindex`, `repair`, or `split`);
- file/job IDs;
- chunk index and time offsets;
- payload size and duration, where available;
- attempt number, elapsed time, retryability, HTTP status, and safe provider request ID;
- selected retry delay and final outcome.

Never log secrets, authorization headers, raw request bodies, base64 media, transcripts, filenames, or provider response bodies. Add counters and duration metrics for attempts, retries, timeouts, splits, degraded files, and repaired chunks.

## 8. Tests and verification

Add focused automated coverage for:

- retryable versus permanent Portkey failures;
- timeout and payload-too-large adaptive splitting;
- all supported modalities using the retry policy;
- degraded audio preserving visual chunks;
- additive, non-destructive audio repair and idempotency;
- stale repair-state rejection and authorization;
- settings saves that do and do not trigger reindexing;
- effective model reporting during partial reindex;
- structured logs containing safe diagnostic fields and no sensitive payloads.

Run backend and frontend tests only inside the Docker workflow defined by `docker-compose.local.yaml`.

## Assumptions

- Use existing file metadata for private repair state; no database migration is required unless implementation constraints prove otherwise.
- Preserve existing working-tree changes while implementing this plan.
- Reliability settings apply to newly dispatched operations; in-flight jobs use their captured policy.
