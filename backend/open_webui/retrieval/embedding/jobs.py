"""Embedding job repository: transactional API for durable job and file lifecycle (Spec 03).

The repository encapsulates all CRUD for ``embedding_jobs`` and ``embedding_job_files``,
enforcing atomic claims, terminal transitions, and consistent aggregate counters. It
follows the same transactional pattern as ``AdminEmbeddingModelStateRepository``: mutating
methods accept an optional caller-owned ``db`` session and only flush when provided; the
caller commits. When ``db`` is ``None``, the method owns and commits its own session.

Concurrency is handled via row locks (``with_for_update()``) and conditional updates.
Duplicate worker delivery receives a no-op result when another worker owns or completed
the same transition. Counters are recomputed in the same transaction as finalization,
never incremented optimistically.

Invariants enforced:
1. One active (queued/processing) job per admin.
2. One file row per (job_id, file_id) — enforced by composite PK.
3. total_files equals persisted file-row count.
4. processed_files equals completed file-row count.
5. failed_files equals failed file-row count.
6. Aggregate counters never exceed total.
7. Terminal job state cannot return to processing.
8. Completed file rows are never claimed again within the same job.
9. Every transition updates updated_at; start and completion timestamps are set once.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from sqlalchemy.exc import IntegrityError

from open_webui.internal.db import get_db
from open_webui.models.embeddings import EmbeddingJob, EmbeddingJobFile
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_ACTIVE_EXISTS,
    EMBEDDING_JOB_NOT_FOUND,
    EMBEDDING_JOB_TERMINAL,
    EMBEDDING_JOB_WRONG_STATUS,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_FILE_WRONG_STATUS,
)
from open_webui.retrieval.embedding.inventory import (
    ReindexFile,
    SOURCE_KNOWLEDGE,
    SOURCE_CHAT_UPLOAD,
)

log = logging.getLogger(__name__)

# Job status constants
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_PARTIALLY_FAILED = "partially_failed"

# File status constants
FILE_STATUS_PENDING = "pending"
FILE_STATUS_PROCESSING = "processing"
FILE_STATUS_COMPLETED = "completed"
FILE_STATUS_FAILED = "failed"

_TERMINAL_JOB_STATUSES = frozenset({JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_PARTIALLY_FAILED})
_ACTIVE_JOB_STATUSES = frozenset({JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING})


@dataclass(frozen=True)
class EmbeddingJobFileView:
    """Detached view of one embedding job file row.

    Contains only stable IDs and status data; no credentials or model details.
    file_snapshot is the persisted ReindexFile inventory data.
    """

    job_id: str
    file_id: str
    status: str
    attempt_count: int
    error_code: Optional[str]
    error_message: Optional[str]
    file_snapshot: dict
    created_at: int
    updated_at: int
    started_at: Optional[int]
    completed_at: Optional[int]


@dataclass(frozen=True)
class EmbeddingJobView:
    """Detached view of one embedding job row.

    Contains only stable IDs, status, and counters; no credentials or model details.
    """

    id: str
    admin_id: str
    embedding_model_id: str
    previous_embedding_model_id: Optional[str]
    job_type: str
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    rq_job_id: Optional[str]
    created_by_user_id: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: int
    updated_at: int
    started_at: Optional[int]
    completed_at: Optional[int]


@dataclass(frozen=True)
class CreateJobResult:
    """Result of creating a new job with its file snapshot."""

    job: EmbeddingJobView
    files: tuple[EmbeddingJobFileView, ...]


# Source-context buckets for status data (Spec 08). A physical file is classified
# from its persisted snapshot's ``source_contexts`` into exactly one mutually
# exclusive bucket so aggregate counts never double-count a file referenced by
# both a knowledge base and a chat upload.
SOURCE_CONTEXT_KNOWLEDGE = SOURCE_KNOWLEDGE
SOURCE_CONTEXT_CHAT_UPLOAD = SOURCE_CHAT_UPLOAD
SOURCE_CONTEXT_BOTH = "both"


@dataclass(frozen=True)
class SourceContextCounts:
    """Ledger-derived counts for one source-context bucket.

    ``total`` counts every file row in the bucket; ``processed`` counts
    completed rows; ``failed`` counts failed rows. A processing or pending row
    is in neither terminal count, so ``pending_or_processing`` is derived.
    """

    total: int = 0
    processed: int = 0
    failed: int = 0

    @property
    def pending_or_processing(self) -> int:
        return self.total - self.processed - self.failed


@dataclass(frozen=True)
class EmbeddingJobStatusView:
    """Read-only status for one embedding job (Spec 08).

    ``job`` carries the stored aggregate counters (recomputed from the file
    ledger after every terminal transition and at finalization).
    ``pending_or_processing`` and ``source_contexts`` are derived: the three
    buckets (``knowledge``, ``chat_upload``, ``both``) are mutually exclusive
    and their totals sum to the aggregate file count without double-counting a
    file referenced by both knowledge and chat.
    """

    job: EmbeddingJobView
    pending_or_processing: int
    source_contexts: dict[str, SourceContextCounts]


def _source_bucket(source_contexts) -> Optional[str]:
    """Classify a file snapshot's ``source_contexts`` into one status bucket.

    Returns one of :data:`SOURCE_CONTEXT_KNOWLEDGE`,
    :data:`SOURCE_CONTEXT_CHAT_UPLOAD`, :data:`SOURCE_CONTEXT_BOTH`, or ``None``
    when no recognized source context is present.
    """
    contexts = set(source_contexts or [])
    has_knowledge = SOURCE_KNOWLEDGE in contexts
    has_chat_upload = SOURCE_CHAT_UPLOAD in contexts
    if has_knowledge and has_chat_upload:
        return SOURCE_CONTEXT_BOTH
    if has_knowledge:
        return SOURCE_CONTEXT_KNOWLEDGE
    if has_chat_upload:
        return SOURCE_CONTEXT_CHAT_UPLOAD
    return None


def _now() -> int:
    return int(time.time())


def _job_to_view(row: EmbeddingJob) -> EmbeddingJobView:
    return EmbeddingJobView(
        id=row.id,
        admin_id=row.admin_id,
        embedding_model_id=row.embedding_model_id,
        previous_embedding_model_id=row.previous_embedding_model_id,
        job_type=row.job_type,
        status=row.status,
        total_files=row.total_files,
        processed_files=row.processed_files,
        failed_files=row.failed_files,
        rq_job_id=row.rq_job_id,
        created_by_user_id=row.created_by_user_id,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _file_to_view(row: EmbeddingJobFile) -> EmbeddingJobFileView:
    return EmbeddingJobFileView(
        job_id=row.job_id,
        file_id=row.file_id,
        status=row.status,
        attempt_count=row.attempt_count,
        error_code=row.error_code,
        error_message=row.error_message,
        file_snapshot=row.file_snapshot or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _get_job_row(db, job_id: str) -> Optional[EmbeddingJob]:
    return db.query(EmbeddingJob).filter(EmbeddingJob.id == job_id).first()


def _create_job(
    db,
    admin_id: str,
    embedding_model_id: str,
    previous_embedding_model_id: Optional[str],
    job_type: str,
    files: Sequence[ReindexFile],
    created_by_user_id: Optional[str],
    error_message: Optional[str],
) -> CreateJobResult:
    """Internal: create job and file rows (flush only; caller commits).

    Enforces one active job per admin via row lock. Files are sorted by file_id
    for deterministic row order. The ReindexFile snapshot is persisted in
    file_snapshot so workers can rebuild collection projections and perform
    staleness checks without re-deriving mutable state.
    """
    now = _now()

    # Lock check: no active job for this admin
    active = (
        db.query(EmbeddingJob)
        .filter(
            EmbeddingJob.admin_id == admin_id,
            EmbeddingJob.status.in_(_ACTIVE_JOB_STATUSES),
        )
        .with_for_update()
        .first()
    )
    if active is not None:
        raise EmbeddingError(
            EMBEDDING_JOB_ACTIVE_EXISTS,
            detail=f"Admin {admin_id} already has an active job {active.id}.",
        )

    # Generate job ID and insert job row
    job_id = str(uuid.uuid4())
    # Dedupe by file_id and sort for determinism
    seen = set()
    sorted_files = []
    for f in files:
        if f.file_id not in seen:
            seen.add(f.file_id)
            sorted_files.append(f)
    sorted_files.sort(key=lambda f: f.file_id)
    total_files = len(sorted_files)

    job_row = EmbeddingJob(
        id=job_id,
        admin_id=admin_id,
        embedding_model_id=embedding_model_id,
        previous_embedding_model_id=previous_embedding_model_id,
        job_type=job_type,
        status=JOB_STATUS_QUEUED,
        total_files=total_files,
        processed_files=0,
        failed_files=0,
        created_by_user_id=created_by_user_id,
        error_message=error_message,
        created_at=now,
        updated_at=now,
    )
    db.add(job_row)

    # Insert file rows with inventory snapshots
    file_rows = []
    for reindex_file in sorted_files:
        file_row = EmbeddingJobFile(
            job_id=job_id,
            file_id=reindex_file.file_id,
            status=FILE_STATUS_PENDING,
            attempt_count=0,
            file_snapshot=reindex_file.to_dict(),
            created_at=now,
            updated_at=now,
        )
        db.add(file_row)
        file_rows.append(file_row)

    try:
        db.flush()
    except IntegrityError:
        # Unique constraint violation: another transaction created an active job
        # Rollback and query for the active job to raise proper error
        db.rollback()
        active = (
            db.query(EmbeddingJob)
            .filter(
                EmbeddingJob.admin_id == admin_id,
                EmbeddingJob.status.in_(_ACTIVE_JOB_STATUSES),
            )
            .first()
        )
        raise EmbeddingError(
            EMBEDDING_JOB_ACTIVE_EXISTS,
            detail=f"Admin {admin_id} already has an active job {active.id if active else 'unknown'}.",
        )

    log.info(
        "[JOB] created job %s for admin %s: %d files, model %s",
        job_id,
        admin_id,
        total_files,
        embedding_model_id,
    )
    return CreateJobResult(
        job=_job_to_view(job_row),
        files=tuple(_file_to_view(fr) for fr in file_rows),
    )


def _transition_to_processing(db, job_id: str) -> Optional[EmbeddingJobView]:
    """Internal: atomically transition queued -> processing (flush only).

    Returns None if job not found. Returns current view if already processing (no-op).
    Raises EMBEDDING_JOB_TERMINAL if job is in a terminal state.
    """
    now = _now()
    row = (
        db.query(EmbeddingJob)
        .filter(EmbeddingJob.id == job_id)
        .with_for_update()
        .first()
    )
    if row is None:
        return None
    if row.status == JOB_STATUS_PROCESSING:
        return _job_to_view(row)  # no-op: already processing
    if row.status in _TERMINAL_JOB_STATUSES:
        raise EmbeddingError(
            EMBEDDING_JOB_TERMINAL,
            detail=f"Job {job_id} is {row.status}; cannot transition to processing.",
        )
    if row.status != JOB_STATUS_QUEUED:
        # Should not happen, but defensive
        raise EmbeddingError(
            EMBEDDING_JOB_WRONG_STATUS,
            detail=f"Job {job_id} is {row.status}; expected queued.",
        )

    row.status = JOB_STATUS_PROCESSING
    if row.started_at is None:
        row.started_at = now
    row.updated_at = now
    db.flush()
    return _job_to_view(row)


def _claim_file(db, job_id: str, file_id: str) -> Optional[EmbeddingJobFileView]:
    """Internal: atomically claim a file and increment attempt_count (flush only).

    Returns None if file not found or not pending (no-op for duplicate/already-done).
    """
    now = _now()
    row = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.file_id == file_id)
        .with_for_update()
        .first()
    )
    if row is None:
        return None
    if row.status != FILE_STATUS_PENDING:
        return None  # no-op: already claimed, completed, or failed

    row.status = FILE_STATUS_PROCESSING
    row.attempt_count += 1
    if row.started_at is None:
        row.started_at = now
    row.updated_at = now
    db.flush()
    return _file_to_view(row)


def _mark_file_completed(db, job_id: str, file_id: str) -> Optional[EmbeddingJobFileView]:
    """Internal: mark file completed (flush only).

    Returns None if file not found. Returns current view if already completed (no-op).
    Raises EMBEDDING_FILE_WRONG_STATUS if file is not in processing state.
    """
    now = _now()
    row = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.file_id == file_id)
        .with_for_update()
        .first()
    )
    if row is None:
        return None
    if row.status == FILE_STATUS_COMPLETED:
        return _file_to_view(row)  # no-op: already completed
    if row.status != FILE_STATUS_PROCESSING:
        raise EmbeddingError(
            EMBEDDING_FILE_WRONG_STATUS,
            detail=f"File {file_id} in job {job_id} is {row.status}; expected processing.",
        )

    row.status = FILE_STATUS_COMPLETED
    if row.completed_at is None:
        row.completed_at = now
    row.updated_at = now
    # Recompute job counters in same transaction per Spec 03 invariant 3-5
    _recompute_counters(db, job_id)
    db.flush()
    return _file_to_view(row)


def _mark_file_failed(
    db,
    job_id: str,
    file_id: str,
    error_code: str,
    error_message: Optional[str],
) -> Optional[EmbeddingJobFileView]:
    """Internal: mark file failed with code and message (flush only).

    Returns None if file not found. Returns current view if already failed (no-op).
    Raises EMBEDDING_FILE_WRONG_STATUS if file is not in processing state.
    """
    now = _now()
    row = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.file_id == file_id)
        .with_for_update()
        .first()
    )
    if row is None:
        return None
    if row.status == FILE_STATUS_FAILED:
        return _file_to_view(row)  # no-op: already failed
    if row.status != FILE_STATUS_PROCESSING:
        raise EmbeddingError(
            EMBEDDING_FILE_WRONG_STATUS,
            detail=f"File {file_id} in job {job_id} is {row.status}; expected processing.",
        )

    row.status = FILE_STATUS_FAILED
    row.error_code = error_code
    row.error_message = error_message
    if row.completed_at is None:
        row.completed_at = now
    row.updated_at = now
    # Recompute job counters in same transaction per Spec 03 invariant 3-5
    _recompute_counters(db, job_id)
    db.flush()
    return _file_to_view(row)


def _fail_nonterminal_files(
    db,
    job_id: str,
    error_code: str,
    error_messages: Mapping[str, str],
) -> list[EmbeddingJobFileView]:
    """Atomically fail every pending or processing file in a job.

    Pending rows first enter processing and increment ``attempt_count`` so the
    persisted lifecycle remains ``pending -> processing -> failed``. Existing
    processing rows retain their current attempt. Completed and already-failed
    rows remain unchanged. Counters are recomputed once after all transitions.
    """
    now = _now()
    rows = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id)
        .with_for_update()
        .all()
    )

    failed_rows: list[EmbeddingJobFileView] = []
    for row in rows:
        if row.status not in (FILE_STATUS_PENDING, FILE_STATUS_PROCESSING):
            continue
        if row.status == FILE_STATUS_PENDING:
            row.status = FILE_STATUS_PROCESSING
            row.attempt_count += 1
            if row.started_at is None:
                row.started_at = now

        row.status = FILE_STATUS_FAILED
        row.error_code = error_code
        row.error_message = error_messages.get(row.file_id)
        row.completed_at = now
        row.updated_at = now
        failed_rows.append(_file_to_view(row))

    _recompute_counters(db, job_id)
    db.flush()
    return failed_rows


def _reclaim_file(
    db, job_id: str, file_id: str, stale_threshold_seconds: int = 300
) -> Optional[EmbeddingJobFileView]:
    """Internal: reclaim a stale processing file or retry a failed file (flush only).

    Returns None if file not found or already completed. Returns current view if
    file is processing but not stale (another worker owns it).

    Reclaim policy:
    - Processing files: reclaim if updated_at is older than stale_threshold_seconds
    - Failed files: always allow reclaim for retry
    - Pending files: treat as fresh claim
    - Completed files: no-op, return None

    The reclaim clears error fields and transitions to processing, incrementing
    attempt_count. This allows workers to recover from crashes or retry failures.
    """
    now = _now()
    row = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.file_id == file_id)
        .with_for_update()
        .first()
    )
    if row is None:
        return None

    # Already completed: no-op
    if row.status == FILE_STATUS_COMPLETED:
        return None

    # Processing: only reclaim if stale
    if row.status == FILE_STATUS_PROCESSING:
        age_seconds = now - (row.updated_at or 0)
        if age_seconds < stale_threshold_seconds:
            # Still being worked on by another worker
            return None
        # Stale processing file: reclaim it

    # Pending or stale processing or failed: transition to processing
    row.status = FILE_STATUS_PROCESSING
    row.attempt_count += 1
    row.error_code = None
    row.error_message = None
    row.completed_at = None  # Clear completion timestamp for retry
    row.updated_at = now
    # Note: started_at is not reset; it captures when work first began
    # Recompute job counters in same transaction per Spec 03 invariant 3-5
    _recompute_counters(db, job_id)
    db.flush()
    return _file_to_view(row)


def _recompute_counters(db, job_id: str) -> Optional[EmbeddingJobView]:
    """Internal: recompute job counters from file rows (flush only).

    Returns None if job not found.
    """
    now = _now()
    job_row = (
        db.query(EmbeddingJob)
        .filter(EmbeddingJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job_row is None:
        return None

    # Count file rows by status
    total = db.query(EmbeddingJobFile).filter(EmbeddingJobFile.job_id == job_id).count()
    processed = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.status == FILE_STATUS_COMPLETED)
        .count()
    )
    failed = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.status == FILE_STATUS_FAILED)
        .count()
    )

    job_row.total_files = total
    job_row.processed_files = processed
    job_row.failed_files = failed
    job_row.updated_at = now
    db.flush()
    return _job_to_view(job_row)


def _finalize_job(db, job_id: str) -> Optional[EmbeddingJobView]:
    """Internal: recompute counters and set terminal status (flush only).

    Returns None if job not found. Terminal status is deterministic:
    - completed: all files completed (including zero-file jobs)
    - failed: no file completed and at least one failed, or operation-level error
    - partially_failed: at least one completed and at least one failed

    Counters are always recomputed in the same transaction as finalization,
    even for already-terminal jobs, to satisfy Spec 03 invariant 3-5.
    """
    now = _now()
    job_row = (
        db.query(EmbeddingJob)
        .filter(EmbeddingJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job_row is None:
        return None

    is_terminal = job_row.status in _TERMINAL_JOB_STATUSES

    # Recompute counters first (same transaction) — always, even for terminal jobs
    # per Spec 03 "counters must be recomputed in the same transaction as finalization"
    total = db.query(EmbeddingJobFile).filter(EmbeddingJobFile.job_id == job_id).count()
    processed = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.status == FILE_STATUS_COMPLETED)
        .count()
    )
    failed = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.status == FILE_STATUS_FAILED)
        .count()
    )

    job_row.total_files = total
    job_row.processed_files = processed
    job_row.failed_files = failed

    # Reject finalization if any files are still unfinished (pending/processing)
    # per Spec 09: finalization requires no pending/processing rows
    unfinished = total - processed - failed
    if unfinished > 0:
        log.warning(
            "[JOB] finalize rejected for job %s: %d files still unfinished",
            job_id,
            unfinished,
        )
        db.flush()
        return _job_to_view(job_row)

    # Already terminal: preserve state/timestamps, just reconcile counters
    if is_terminal:
        job_row.updated_at = now
        db.flush()
        return _job_to_view(job_row)

    # Determine terminal status
    # Check operation-level fatal error first per Spec 03 terminal rules
    if job_row.error_message:
        # Operation-level fatal error takes precedence
        job_row.status = JOB_STATUS_FAILED
    elif total == processed:
        # All files completed (includes zero-file jobs)
        job_row.status = JOB_STATUS_COMPLETED
    elif processed > 0 and failed > 0:
        # At least one completed and at least one failed
        job_row.status = JOB_STATUS_PARTIALLY_FAILED
    elif failed > 0 and processed == 0:
        # No file completed and at least one failed
        job_row.status = JOB_STATUS_FAILED
    else:
        # Defensive: should not happen if finalize is called after all files done
        log.warning(
            "[JOB] finalize called on job %s with total=%d processed=%d failed=%d; "
            "defaulting to failed status",
            job_id,
            total,
            processed,
            failed,
        )
        job_row.status = JOB_STATUS_FAILED

    if job_row.completed_at is None:
        job_row.completed_at = now
    job_row.updated_at = now
    db.flush()
    log.info(
        "[JOB] finalized job %s: status=%s, total=%d, processed=%d, failed=%d",
        job_id,
        job_row.status,
        total,
        processed,
        failed,
    )
    return _job_to_view(job_row)


def _list_failed_files(db, job_id: str) -> list[EmbeddingJobFileView]:
    """Internal: list all failed file rows for a job."""
    rows = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id, EmbeddingJobFile.status == FILE_STATUS_FAILED)
        .order_by(EmbeddingJobFile.file_id)
        .all()
    )
    return [_file_to_view(row) for row in rows]


def _get_job_status(db, job_id: str) -> Optional[EmbeddingJobStatusView]:
    """Internal: build a read-only status view for a job (no mutation).

    Aggregate counters come from the job row (maintained to match the ledger);
    ``pending_or_processing`` and the source-context breakdown are derived from
    the persisted file rows and their inventory snapshots (Spec 08). A physical
    file belongs to exactly one bucket (knowledge / chat_upload / both) so the
    bucket totals never double-count a multi-context file.
    """
    job_row = _get_job_row(db, job_id)
    if job_row is None:
        return None
    job_view = _job_to_view(job_row)

    file_rows = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id == job_id)
        .all()
    )

    bucket_totals = {
        SOURCE_CONTEXT_KNOWLEDGE: 0,
        SOURCE_CONTEXT_CHAT_UPLOAD: 0,
        SOURCE_CONTEXT_BOTH: 0,
    }
    bucket_processed = dict(bucket_totals)
    bucket_failed = dict(bucket_totals)
    for row in file_rows:
        snapshot = row.file_snapshot if isinstance(row.file_snapshot, dict) else {}
        bucket = _source_bucket(snapshot.get("source_contexts"))
        if bucket is None:
            continue
        bucket_totals[bucket] += 1
        if row.status == FILE_STATUS_COMPLETED:
            bucket_processed[bucket] += 1
        elif row.status == FILE_STATUS_FAILED:
            bucket_failed[bucket] += 1

    source_contexts = {
        bucket: SourceContextCounts(
            total=bucket_totals[bucket],
            processed=bucket_processed[bucket],
            failed=bucket_failed[bucket],
        )
        for bucket in (
            SOURCE_CONTEXT_KNOWLEDGE,
            SOURCE_CONTEXT_CHAT_UPLOAD,
            SOURCE_CONTEXT_BOTH,
        )
    }

    pending_or_processing = (
        job_view.total_files - job_view.processed_files - job_view.failed_files
    )
    return EmbeddingJobStatusView(
        job=job_view,
        pending_or_processing=pending_or_processing,
        source_contexts=source_contexts,
    )


def _mark_job_failed(
    db, job_id: str, error_code: str, error_message: str
) -> Optional[EmbeddingJobView]:
    """Internal: mark job as failed with error details (flush only).

    Used for operation-level failures (e.g., enqueue failures) that prevent
    the job from proceeding. Sets terminal status to 'failed' and records
    the error code and message.

    Returns None if job not found. No-op if already terminal.
    """
    now = _now()
    job_row = (
        db.query(EmbeddingJob)
        .filter(EmbeddingJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job_row is None:
        return None

    # Already terminal: no-op
    if job_row.status in _TERMINAL_JOB_STATUSES:
        return _job_to_view(job_row)

    # Set failed status with error details
    job_row.status = JOB_STATUS_FAILED
    job_row.error_code = error_code
    job_row.error_message = error_message
    if job_row.completed_at is None:
        job_row.completed_at = now
    job_row.updated_at = now

    db.flush()
    log.info(
        "[JOB] marked job %s as failed: error_code=%s, message=%s",
        job_id,
        error_code,
        error_message,
    )
    return _job_to_view(job_row)


class EmbeddingJobRepository:
    """Transactional API for durable embedding-job and per-file lifecycle state."""

    @staticmethod
    def create_job(
        admin_id: str,
        embedding_model_id: str,
        files: Sequence[ReindexFile],
        job_type: str = "reindex",
        previous_embedding_model_id: Optional[str] = None,
        created_by_user_id: Optional[str] = None,
        error_message: Optional[str] = None,
        db=None,
    ) -> CreateJobResult:
        """Create a new job with its complete file snapshot in one transaction.

        Enforces one active job per admin. Files are deduplicated by file_id and sorted.
        The ReindexFile inventory snapshot is persisted so workers can rebuild
        collection projections and perform staleness checks without re-deriving
        mutable state.

        When ``db`` is provided the caller owns the transaction (only flush);
        otherwise a session is opened and committed here.

        Raises:
            EmbeddingError: EMBEDDING_JOB_ACTIVE_EXISTS if an active job already exists.
        """
        if db is None:
            with get_db() as session:
                result = _create_job(
                    session,
                    admin_id,
                    embedding_model_id,
                    previous_embedding_model_id,
                    job_type,
                    files,
                    created_by_user_id,
                    error_message,
                )
                session.commit()
                return result
        return _create_job(
            db,
            admin_id,
            embedding_model_id,
            previous_embedding_model_id,
            job_type,
            files,
            created_by_user_id,
            error_message,
        )

    @staticmethod
    def get_job(job_id: str, db=None) -> Optional[EmbeddingJobView]:
        """Return the job view for a job ID, or None if not found."""
        if db is None:
            with get_db() as session:
                row = _get_job_row(session, job_id)
        else:
            row = _get_job_row(db, job_id)
        return _job_to_view(row) if row else None

    @staticmethod
    def get_latest_job(admin_id: str, db=None) -> Optional[EmbeddingJobView]:
        """Return the latest job for an admin (by created_at DESC, id DESC), or None."""
        if db is None:
            with get_db() as session:
                row = (
                    session.query(EmbeddingJob)
                    .filter(EmbeddingJob.admin_id == admin_id)
                    .order_by(EmbeddingJob.created_at.desc(), EmbeddingJob.id.desc())
                    .first()
                )
        else:
            row = (
                db.query(EmbeddingJob)
                .filter(EmbeddingJob.admin_id == admin_id)
                .order_by(EmbeddingJob.created_at.desc(), EmbeddingJob.id.desc())
                .first()
            )
        return _job_to_view(row) if row else None

    @staticmethod
    def get_active_job(admin_id: str, db=None) -> Optional[EmbeddingJobView]:
        """Return the active (queued/processing) job for an admin, or None."""
        if db is None:
            with get_db() as session:
                row = (
                    session.query(EmbeddingJob)
                    .filter(
                        EmbeddingJob.admin_id == admin_id,
                        EmbeddingJob.status.in_(_ACTIVE_JOB_STATUSES),
                    )
                    .order_by(EmbeddingJob.created_at.desc())
                    .first()
                )
        else:
            row = (
                db.query(EmbeddingJob)
                .filter(
                    EmbeddingJob.admin_id == admin_id,
                    EmbeddingJob.status.in_(_ACTIVE_JOB_STATUSES),
                )
                .order_by(EmbeddingJob.created_at.desc())
                .first()
            )
        return _job_to_view(row) if row else None

    @staticmethod
    def attach_rq_job_id(job_id: str, rq_job_id: str, db=None) -> bool:
        """Attach an RQ job ID to a job (conditional: only when rq_job_id is NULL).

        Returns True if attached, False if already set or job not found.
        """
        if db is None:
            with get_db() as session:
                updated = (
                    session.query(EmbeddingJob)
                    .filter(EmbeddingJob.id == job_id, EmbeddingJob.rq_job_id.is_(None))
                    .update({EmbeddingJob.rq_job_id: rq_job_id, EmbeddingJob.updated_at: _now()})
                )
                session.commit()
                return updated > 0
        updated = (
            db.query(EmbeddingJob)
            .filter(EmbeddingJob.id == job_id, EmbeddingJob.rq_job_id.is_(None))
            .update({EmbeddingJob.rq_job_id: rq_job_id, EmbeddingJob.updated_at: _now()})
        )
        db.flush()
        return updated > 0

    @staticmethod
    def transition_to_processing(job_id: str, db=None) -> Optional[EmbeddingJobView]:
        """Atomically transition queued -> processing.

        Returns None if job not found. Returns current view if already processing (no-op).
        Raises EMBEDDING_JOB_TERMINAL if job is in a terminal state.
        """
        if db is None:
            with get_db() as session:
                view = _transition_to_processing(session, job_id)
                session.commit()
                return view
        return _transition_to_processing(db, job_id)

    @staticmethod
    def claim_file(job_id: str, file_id: str, db=None) -> Optional[EmbeddingJobFileView]:
        """Atomically claim a file and increment attempt_count.

        Returns None if file not found or not pending (no-op for duplicate/already-done).
        """
        if db is None:
            with get_db() as session:
                view = _claim_file(session, job_id, file_id)
                session.commit()
                return view
        return _claim_file(db, job_id, file_id)

    @staticmethod
    def reclaim_file(
        job_id: str,
        file_id: str,
        stale_threshold_seconds: int = 300,
        db=None,
    ) -> Optional[EmbeddingJobFileView]:
        """Reclaim a stale processing file or retry a failed file.

        Returns None if file not found, already completed, or processing but not stale.

        Reclaim policy:
        - Processing files: reclaim if updated_at is older than stale_threshold_seconds
        - Failed files: always allow reclaim for retry
        - Pending files: treat as fresh claim
        - Completed files: no-op, return None

        When ``db`` is provided the caller owns the transaction (only flush);
        otherwise a session is opened and committed here.
        """
        if db is None:
            with get_db() as session:
                view = _reclaim_file(session, job_id, file_id, stale_threshold_seconds)
                session.commit()
                return view
        return _reclaim_file(db, job_id, file_id, stale_threshold_seconds)

    @staticmethod
    def mark_file_completed(job_id: str, file_id: str, db=None) -> Optional[EmbeddingJobFileView]:
        """Mark a file completed.

        Returns None if file not found. Returns current view if already completed (no-op).
        Raises EMBEDDING_FILE_WRONG_STATUS if file is not in processing state.
        """
        if db is None:
            with get_db() as session:
                view = _mark_file_completed(session, job_id, file_id)
                session.commit()
                return view
        return _mark_file_completed(db, job_id, file_id)

    @staticmethod
    def mark_file_failed(
        job_id: str,
        file_id: str,
        error_code: str,
        error_message: Optional[str] = None,
        db=None,
    ) -> Optional[EmbeddingJobFileView]:
        """Mark a file failed with code and message.

        Returns None if file not found. Returns current view if already failed (no-op).
        Raises EMBEDDING_FILE_WRONG_STATUS if file is not in processing state.
        """
        if db is None:
            with get_db() as session:
                view = _mark_file_failed(session, job_id, file_id, error_code, error_message)
                session.commit()
                return view
        return _mark_file_failed(db, job_id, file_id, error_code, error_message)

    @staticmethod
    def fail_nonterminal_files(
        job_id: str,
        error_code: str,
        error_messages: Mapping[str, str],
        db=None,
    ) -> list[EmbeddingJobFileView]:
        """Fail all pending or processing files and recompute counters atomically."""
        if db is None:
            with get_db() as session:
                views = _fail_nonterminal_files(
                    session, job_id, error_code, error_messages
                )
                session.commit()
                return views
        return _fail_nonterminal_files(db, job_id, error_code, error_messages)

    @staticmethod
    def recompute_counters(job_id: str, db=None) -> Optional[EmbeddingJobView]:
        """Recompute job counters from file rows.

        Returns None if job not found.
        """
        if db is None:
            with get_db() as session:
                view = _recompute_counters(session, job_id)
                session.commit()
                return view
        return _recompute_counters(db, job_id)

    @staticmethod
    def finalize_job(job_id: str, db=None) -> Optional[EmbeddingJobView]:
        """Recompute counters and set terminal status.

        Returns None if job not found. Returns current view if already terminal (no-op).
        Terminal status is deterministic based on file completion counts.
        """
        if db is None:
            with get_db() as session:
                view = _finalize_job(session, job_id)
                session.commit()
                return view
        return _finalize_job(db, job_id)

    @staticmethod
    def list_failed_files(job_id: str, db=None) -> list[EmbeddingJobFileView]:
        """List all failed file rows for a job, sorted by file_id."""
        if db is None:
            with get_db() as session:
                return _list_failed_files(session, job_id)
        return _list_failed_files(db, job_id)

    @staticmethod
    def get_job_status(job_id: str, db=None) -> Optional[EmbeddingJobStatusView]:
        """Return a read-only status view for a job (Spec 08).

        Includes the job row, ``pending_or_processing``, and derived counts by
        source context (``knowledge`` / ``chat_upload`` / ``both``). The bucket
        totals are mutually exclusive and never double-count a physical file
        referenced by both knowledge and chat.

        Returns None if the job is not found.
        """
        if db is None:
            with get_db() as session:
                return _get_job_status(session, job_id)
        return _get_job_status(db, job_id)

    @staticmethod
    def mark_job_failed(
        job_id: str,
        error_code: str,
        error_message: str,
        db=None,
    ) -> Optional[EmbeddingJobView]:
        """Mark job as failed with error details.

        Used for operation-level failures (e.g., enqueue failures) that prevent
        the job from proceeding. Sets terminal status to 'failed' and records
        the error code and message.

        Returns None if job not found. No-op if already terminal.

        When ``db`` is provided the caller owns the transaction (only flush);
        otherwise a session is opened and committed here.
        """
        if db is None:
            with get_db() as session:
                view = _mark_job_failed(session, job_id, error_code, error_message)
                session.commit()
                return view
        return _mark_job_failed(db, job_id, error_code, error_message)
