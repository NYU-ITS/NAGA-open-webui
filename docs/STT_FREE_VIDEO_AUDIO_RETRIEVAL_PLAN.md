# Direct Video-Audio Embeddings and Retrieval-Time Understanding

## Executive summary

Video ingestion indexes the original visual stream and its audio stream in the
same `@vertexai/gemini-embedding-2` vector space. Each existing temporal video
segment receives an aligned raw-audio sibling when the source contains an audio
track. Audio is transcoded once per video to mono, 16 kHz PCM WAV and sliced in
memory on the existing video boundaries.

Audio chunks contain no text. They store only an audio-byte digest and factual
source metadata, so ingestion does not depend on transcription, subtitle
parsing, or generated descriptions. Audio failures are best effort and never
invalidate successfully embedded visual chunks.

At retrieval time, a text query can match an audio vector directly. For the
highest-ranked authorized audio hits, the server reconstructs the corresponding
WAV ranges from the original video and attaches them transiently to the selected
answer model using that model provider's supported request contract. Unknown,
embedding-only, or incompatible answer models receive timestamp and compatible
frame context but no audio bytes.

## Design principles

- Keep video and audio in one cross-modal embedding space.
- Preserve the current 16-second temporal video segmentation policy.
- Store no transcript, subtitle text, generated audio description, WAV payload,
  or Base64 payload in chunk content or citation metadata.
- Treat audio extraction and embedding as optional siblings of required visual
  processing.
- Authorize retrieval from canonical server-side file and knowledge scope.
- Reconstruct only bounded, top-ranked evidence from the original source file.
- Send audio only when answer-model support is declared or safely inferred.
- Let the selected answer model analyze retrieved audio directly; do not route
  it through a task model or transcription service.
- Keep existing image, video-vector, and video-frame behavior unchanged.
- Add no audio feature flag or separate audio model configuration.

## End-to-end flow

### 1. Video preparation

The shared preparation path used by normal ingestion and reindex workers:

1. Validates the video container and duration with the existing video policy.
2. Plans the existing temporal visual segments.
3. Uses `ffprobe` to determine whether the first audio stream exists.
4. If present, invokes `ffmpeg` once to produce mono PCM signed 16-bit WAV at
   16 kHz.
5. Reads the PCM frames and slices them in memory using the exact visual segment
   start and end times.
6. Pads a short trailing audio stream with silence so each planned visual range
   has a deterministic, aligned audio sibling.

MP4, MPEG, and QuickTime/MOV sources use the same supported container policy as
temporal video embeddings. A missing stream or extraction failure returns stable
warnings and leaves the visual chunk list intact.

### 2. Chunk construction

Each temporal range keeps its visual chunk and, when audio is available, gains
one audio sibling. Both chunks share `video_segment_id`, timestamps, source
identity, and duration.

The audio chunk contract is:

- `content_type`: `audio`
- `modality`: `audio`
- `content_kind`: `audio_temporal`
- `content`: empty string
- `content_sha256`: SHA-256 of the segment WAV bytes
- `mime_type`: `audio/wav`
- `source_mime_type`: the original video MIME type
- `startTimeSeconds` / `endTimeSeconds`
- `segment_start_s` / `segment_end_s`
- `chunkIndex`
- `video_segment_id`
- `duration_seconds`
- `audio_extraction_version`
- `chunking_version`

`AudioEmbeddingInput` is immutable and carries only `audio: bytes` plus the
literal MIME type `audio/wav`. Provider input bytes remain process-local; only
their digest and the approved metadata above enter the chunk manifest.

### 3. Embedding

Audio uses the existing Portkey multimodal embedding route and the same model
space as text, images, and video. The gateway request follows its media
contract:

```json
{
  "model": "@vertexai/gemini-embedding-2",
  "input": [
    {
      "text": "",
      "audio": {
        "base64": "<transient WAV bytes>",
        "mimeType": "audio/wav"
      }
    }
  ]
}
```

The provider adapter accepts both supported response forms:

- OpenAI-compatible `data[].embedding`
- Vertex-compatible `predictions[].audioEmbedding`

Text, image, and video chunks follow their normal embedding path. Each audio
chunk is sent in its own provider call so one audio failure removes only that
audio chunk. Successful chunks and vectors retain their original relative
order, then produce one canonical manifest and the normal file and knowledge
projections.

If every audio call fails, the file still completes as visual-only with stable
warnings. A failure in required visual processing retains its existing failure
semantics.

### 4. Dense retrieval

An embedding model whose declared modalities include `audio`, `image`, or
`video` is treated as a dense multimodal space. This avoids applying text-only
ranking stages to media vectors.

Retrieval behavior is:

- Admit empty-content audio rows returned by dense vector search.
- Exclude audio rows from BM25 indexing.
- Exclude audio rows from text reranking and text-embedding fallback scoring.
- Keep audio and visual sibling hits as separate evidence rows.
- Rank reconstruction candidates by dense distance and stable metadata
  tie-breakers.
- Deduplicate frame and audio reconstruction by `video_segment_id` without
  suppressing either sibling from retrieval results.

Text queries are embedded by the active model and can therefore match spoken or
other acoustic evidence without text being generated during ingestion.

### 5. Authorized reconstruction

Audio bytes are reconstructed only after retrieval and only for rows within the
server-validated attachment scope. A candidate must belong to an attached file
or attached knowledge collection and must contain the expected audio/video
metadata contract.

For each selected segment, the server:

1. Resolves the stored original video by `file_id`.
2. Verifies its SHA-256 against the indexed source digest.
3. Validates finite timestamps against the recorded source duration.
4. Enforces the configured top-k selection, the audio reconstruction limit, and
   the maximum video duration bound.
5. Extracts only the selected range as mono, 16 kHz signed 16-bit PCM.
6. Wraps the PCM in WAV format in memory.

Reconstructed audio is not written to file metadata, chunk rows, vector
metadata, chat citations, logs, or telemetry. It exists only long enough to
assemble the answer-model request.

Audio hits remain eligible for the existing timestamped frame reconstruction
path. This preserves visual grounding when the dense match came from audio and
allows a model without audio input support to receive compatible frame context.

### 6. Answer-model capability gate

Audio attachment is stricter than the existing optimistic vision behavior. The
selected answer model receives WAV evidence only when all of the following are
true:

- It is not an embedding model.
- Audio input support is explicitly declared or safely inferred from a known
  audio-capable model identifier.
- A concrete request format is known for the selected provider.

Known Gemini 1.5-and-later identifiers use Portkey's Gemini media data-URL
contract. Known OpenAI Chat Completions audio models use native `input_audio`
parts. An explicit `audio_input_format` model metadata value can declare one of
those contracts for a compatible custom route using `gemini_data_url` or
`openai_input_audio`. Explicit `capabilities.audio: false` remains authoritative.
Plain `gpt-4o` and `gpt-4o-mini` are treated as unsupported because those models
do not accept audio input; an audio-family model such as `gpt-audio-1.5` is
required for the OpenAI contract. Known OpenAI audio-only models are also kept
from receiving reconstructed image or video-frame parts.

The transient Portkey Gemini media part uses a WAV data URL:

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:audio/wav;base64,<transient WAV bytes>"
  }
}
```

The transient OpenAI Chat Completions part carries raw Base64 without a data-URL
prefix:

```json
{
  "type": "input_audio",
  "input_audio": {
    "data": "<transient WAV bytes>",
    "format": "wav"
  }
}
```

Both forms are appended to the latest user message sent to the model selected
for that chat. Neither form invokes or substitutes the configured task model.

Caller-supplied non-text media is removed before processing. Only media
reconstructed from the authorized retrieval scope can be appended to the latest
user message.

When retrieved audio cannot be attached because model support is false or
unknown, the user receives a clear status message. Factual source context is
still included, for example:

> Retrieved audio evidence from "meeting.mov", 00:16.000–00:32.000.

No inferred meaning, transcript, or description of the audio is added to that
text.

### 7. Citation sanitization

Frontend source metadata is allowlisted independently for text, visual, and
audio rows. Audio citations may expose factual identity and timing fields such
as file name, MIME types, segment ID, timestamps, and duration.

They never expose:

- reconstructed WAV or PCM bytes
- Base64 or data URLs
- source filesystem or object-storage paths
- source or content hashes
- provider requests or responses
- private extraction recipes

Audio and visual sibling citations remain separate even when reconstruction is
deduplicated by segment ID.

## Failure semantics and warnings

| Condition | Result |
|---|---|
| No audio stream | Visual ingestion succeeds; `audio_absent` and `audio_fallback_visual_only` are recorded. |
| Audio probe/transcode/slice failure | Visual ingestion succeeds; `audio_extraction_failed` and visual-only fallback are recorded. |
| One audio embedding call fails | Only that audio sibling is removed; remaining chunks are persisted. |
| All audio embedding calls fail | Visual ingestion succeeds with `audio_embedding_failed` and visual-only fallback warnings. |
| Retrieval source is unauthorized | No frame, audio, or file-backed citation is emitted. |
| Source bytes no longer match | Audio reconstruction is skipped. |
| Selected answer model is unsupported or unknown | No audio payload is sent; the user sees a model-specific status warning and retains timestamp/frame context. |
| FFmpeg is unavailable at retrieval | Audio attachment is skipped and visual-only fallback telemetry is recorded. |

Warnings are public stable codes, while provider exception details and media
bytes remain private.

## Observability

The audio path uses bounded counters and span events without media content:

- `retrieval.video.audio_extractions`, labeled by outcome
- `retrieval.video.audio_chunks_created`
- `retrieval.video.audio_embedding_failures`
- `retrieval.video.audio_attachments`
- `retrieval.video.audio_answer_model_unsupported`
- `retrieval.video.audio_fallback_visual_only`

Failure events may contain an error type, model identifier, stable segment ID,
or a short source-hash prefix. They never contain audio, Base64, transcripts, or
provider credentials.

## Persistence and lifecycle

- Chunk manifests include audio modality, byte digest, timing, and extraction
  version so reprocessing is deterministic.
- Existing job idempotence, frozen model resolution, and model-aware projection
  rules remain authoritative.
- Old private video-audio cache metadata is discarded when a file state is
  published; no new audio-content cache is created.
- Existing videos remain valid as visual-only until they are reprocessed through
  the normal upload or reindex workflow.
- No automatic backfill or database stamping is part of this change.

## Database migration

Revision `j0k1l2m3n4o5`:

- extends `rag_chunks.content_type` to allow `audio`
- appends `audio` to the Gemini embedding model's modality list
- has `c4d5e6f7g8h9` as its sole parent, which is the repository's existing
  merge head

The database was checked read-only before the parent correction and remained at
`c4d5e6f7g8h9`; `j0k1l2m3n4o5` had not been applied. The migration history must
not be stamped, rewritten, or supplemented with another merge revision. With
the parent corrected, the intended Alembic graph has one head:
`j0k1l2m3n4o5`.

## Validation scenarios

- MP4 and MOV files with audio produce one raw-audio sibling per visual segment
  without transcription- or caption-related warnings.
- A spoken-content text query can retrieve an audio vector and attach the
  corresponding WAV and timestamps to a supported Gemini or OpenAI Chat
  Completions audio answer model, plus reconstructed frames when the model also
  supports vision.
- Files without an audio stream complete visual ingestion with stable warnings.
- An individual audio extraction or embedding failure does not invalidate
  successful visual chunks.
- Plain GPT-4o Mini, unknown, and embedding answer models receive no audio
  payload and produce a clear status message.
- Existing image retrieval, video-vector retrieval, and frame reconstruction
  behave as before.
- Citation events and frontend metadata never contain WAV or Base64 data.
- The intended migration graph has the single head `j0k1l2m3n4o5`.

## Definition of done

- Raw audio is embedded directly in the Gemini cross-modal vector space.
- Every extractable video audio track produces aligned segment siblings.
- Audio failures preserve successful visual ingestion and reindex results.
- Empty audio chunks participate only in dense retrieval.
- Top-ranked authorized audio hits are reconstructed from their original files.
- Audio is attached directly to compatible selected answer models using their
  provider-specific request contract.
- Unsupported or unknown models receive no audio bytes and a clear warning.
- Citations contain factual source timing only and expose no media payload.
- The audio migration is based directly on `c4d5e6f7g8h9`.
- No transcription service, subtitle parser, generated audio description, or
  audio-content cache remains in this design.
