# Multimodal index generations

Deploy the API and RQ workers from the same revision. Drain and stop old workers
before applying migration `k1l2m3n4o5p6`, then start the updated API and workers.
The application still applies Alembic migrations during startup. Do not roll an
old worker image back against the expanded schema without a coordinated rollback.

Every new indexing operation creates a generation. Retrying failed files retains
that generation and its preparation recipes, refreshing only the failed files'
source fingerprints, memberships, and operational retry settings. A saved model
is selected immediately; its first durable file publication activates it. Empty
inventories activate immediately. Failed files and optional audio never reverse
activation or hide another file's successful publication.

The database rejects vector mutations from processes without the generation-aware
transaction marker, including deletes by obsolete whole-job finalizers. It also
rejects active/building vectors whose generation and selected model do not match
administrator state. API and vector storage must share the primary PostgreSQL
transaction for atomic file/vector/state publication, as required by the existing
model-aware indexing subsystem.

Startup and periodic reconciliation validate existing completed files using their
source, preparation recipe, and complete manifest before publishing them without
embedding calls. Baseline generations preserve attributable existing active
indexes. Unverifiable files receive a recovery reason and eligible job failures
can be retried individually; there is no automatic administrator-wide rebuild.

Required indexing and audio processing serialize ownership for the same file.
Audio checkpoints commit each completed leaf and its manifest. Queued work is
recoverable after interrupted dispatch, and abandoned execution ownership becomes
degraded after 120 seconds without a heartbeat. Queue infrastructure outages are
distinct from missing queue jobs. Provider failures await an explicit repair;
they are not automatically retried indefinitely.

Chat reconstruction has two workers per API process and a 30-second request
budget including capacity wait. Audio processing has a 300-second execution
budget. Extraction, provider timeouts, and backoff use remaining time; cancellation
retains a worker slot until the underlying work exits. Filesystem and database
operations use cooperative cancellation and their underlying transport limits.

## Verification before rollout

The Docker production build and Python syntax/static analysis have been checked.
Acceptance regression tests require explicit authorization under `AGENTS.md` and
must run inside services defined by `docker-compose.local.yaml`.

Verify the eight-success/two-failure case, failed retry repetition, an upload that
activates the model before the rebuild, all-failed and empty inventories, source
changes during failed retries, duplicate/interrupted audio delivery, audio budget
exhaustion, mixed ready/failed collections, reconstruction cancellation, structured
no-evidence errors, and recovery of completed files from pre-upgrade partial jobs.
Check per-attempt counters separately from generation coverage.

Publication, retry size, reconstruction timeout, abandoned audio recovery, and
audio budget events have bounded metrics. File, job, and generation identifiers
remain in logs rather than metric labels.
