# Phase 6 Multimodal Embedding Rollout

This runbook covers the admin-by-admin rollout and rollback of direct PNG,
JPEG, and qualifying PDF-visual embeddings. The approved provider contract is
Portkey model `@vertexai/gemini-embedding-2` with 1536-dimensional text and
image vectors.

## Hard gates

Do not change an administrator's selected model until all of these are true:

- The Phase 6 migrations and application/worker image are deployed together.
- The application and RQ workers use the same release and configuration.
- `DATABASE_URL` and `PGVECTOR_DB_URL` resolve to the same PostgreSQL database.
- There is no active embedding job for the pilot administrator.
- The previous model ID, governed file count, representative queries, and
  baseline latency/failure measurements have been recorded.
- The environment-specific Portkey text/PNG/JPEG canary passes in full.

A failed canary is a rollout blocker. Do not change the model alias,
dimensions, MIME, request shape, or response validation to make it pass.

## Run the Portkey contract canary

Use known-valid, non-sensitive PNG and JPEG samples. Keep them outside the
repository and mount their directory read-only. Supply the gateway credential
through the environment, never a command-line argument or checked-in `.env`
file.

```bash
read -r -s PORTKEY_CANARY_API_KEY
export PORTKEY_CANARY_API_KEY
export PORTKEY_CANARY_BASE_URL="https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
export PORTKEY_CANARY_FIXTURES_DIR="/absolute/path/to/non-sensitive/canary-images"

docker compose -f docker-compose.local.yaml run --rm \
  -e PORTKEY_CANARY_API_KEY \
  -e PORTKEY_CANARY_BASE_URL \
  -v "${PORTKEY_CANARY_FIXTURES_DIR}:/canary:ro" \
  open-webui \
  python /app/backend/scripts/portkey_multimodal_embedding_canary.py \
  --png /canary/sample.png \
  --jpeg /canary/sample.jpg

unset PORTKEY_CANARY_API_KEY
```

Success prints four `PASS` lines: text, PNG, JPEG, and the fixed contract. The
script never prints credentials, request image data, response bodies, or
embedding values. Any `FAIL` or nonzero exit blocks the rollout; retain only
the safe failure line and environment/release identifiers in operational
records.

Run the canary separately against every gateway environment used by the
rollout. The script requires HTTPS and refuses redirects so a bearer credential
is not silently sent to a different endpoint.

## Pilot rollout

1. Deploy Phase 6 without changing any administrator's model selection. Confirm
   the web application and worker are healthy and the registry contains
   `embmdl-portkey-vertexai-gemini-embedding-2-1536` as enabled.
2. Run the canary above with the same gateway base URL and credential scope the
   pilot administrator will use.
3. In Admin Settings > Documents, select **Vertex AI Gemini Embedding 2** for
   one pilot administrator. Use the existing model-change workflow; do not
   launch a parallel/manual migration.
4. Monitor the embedding job status until it is terminal. Promotion is allowed
   only when `processed_files == total_files`, `failed_files == 0`, and the
   administrator's active model is the new model with no target model pending.
5. Reconcile the governed source-file count against the job inventory, then
   compare text/image chunk counts and vectors by modality. Investigate any
   missing, extra, legacy, or still-building projection before proceeding.
6. Exercise representative text-only PDFs, standalone PNG/JPEG files, PDF
   figures, and image-bearing tables. Confirm expected retrieval quality and
   compare indexing latency, query latency, warning counts, and provider
   failures with the recorded baseline.
7. Confirm that reconstructed visuals reach only authorized, server-confirmed
   vision-capable answer models. Verify non-vision models receive usable text
   only, and that API responses, events, logs, RQ payloads, and chat records do
   not expose Base64, credentials, private geometry, source hashes, or storage
   paths.

Pause on the first failed gate. Expand to one administrator at a time only
after the prior administrator's counts, retrieval checks, authorization checks,
and operational metrics have been accepted.

## Rollback

Rollback is a normal model change, not a schema downgrade:

1. Stop expanding the rollout and record the affected administrator, release,
   active/target model IDs, job ID, and safe error codes.
2. In Admin Settings > Documents, select that administrator's recorded previous
   text embedding model. Let the normal model-change reindex complete; do not
   delete vectors or chunk manifests while it is running.
3. Confirm the rollback job has processed every governed file with no failures,
   the previous model is active, no target is pending, and representative text
   retrieval matches the pre-rollout baseline.
4. Expect standalone images and visual-only PDFs to become visible
   unsupported-content failures. Mixed PDFs retain text/table vectors and show
   `pdf_visuals_require_multimodal_model` where qualifying visuals were omitted.

Do not downgrade the expand-only registry/schema migrations or delete original
PDFs, immutable manifests, or inactive model projections during immediate
rollback. PDF crops are reconstructed from their parent PDFs, so there are no
derived crop objects to clean up. Use the established retention process for
inactive projections only after the rollback has been verified.
