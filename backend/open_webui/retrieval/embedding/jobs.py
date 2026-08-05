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
    EMBEDDING_JOB_STALE_OPERATION,
    EMBEDDING_JOB_TERMINAL,
    EMBEDDING_JOB_WRONG_STATUS,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_FILE_WRONG_STATUS,
    EMBEDDING_MODEL_STATE_CONFLICT,
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
    source_job_id: Optional[str]
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
        source_job_id=getattr(row, "source_job_id", None),
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


def _create_retry_job(
    db,
    source_job_id: str,
    admin_id: str,
) -> CreateJobResult:
    """Create a retry_failed job from a source job's failed files (Spec 11).

    Validates (in lock order):
    1. Source job exists, belongs to admin, and is failed/partially_failed.
    2. Lock admin state row first (serialises concurrent retries per admin).
    3. No active (queued/processing) job exists (rechecked after state lock).
    4. Source job's target matches admin's current target; missing state or
       cleared target fails closed.
    5. ALL source job files (not just failed) have unchanged content hashes.
    6. At least one failed file exists, or all files are pending (enqueue-only
       failure re-enqueue path).

    For enqueue-only failures (queued source job with no processing/completed
    files), the source job itself is re-enqueued rather than creating a new
    retry job — the source job and its latest-job pointer are already correct.

    Creates a new ``retry_failed`` job with fresh pending file rows for each
    failed file.  The source job is never modified.  The admin's
    ``latest_embedding_job_id`` is updated atomically.

    Raises:
        EmbeddingError (EMBEDDING_JOB_NOT_FOUND): source job missing.
        EmbeddingError (EMBEDDING_JOB_WRONG_STATUS): source job not failed
            and not an enqueue-only failure.
        EmbeddingError (EMBEDDING_JOB_ACTIVE_EXISTS): active job already exists.
        EmbeddingError (EMBEDDING_MODEL_STATE_CONFLICT): target mismatch or
            missing state.
        EmbeddingError (EMBEDDING_REINDEX_SOURCE_CHANGED): file content changed.
    """
    from open_webui.models.embeddings import AdminEmbeddingModelState
    from open_webui.models.files import File

    now = _now()

    # 1. Lock and validate source job.
    source_row = (
        db.query(EmbeddingJob)
        .filter(EmbeddingJob.id == source_job_id)
        .with_for_update()
        .first()
    )
    if source_row is None:
        raise EmbeddingError(
            EMBEDDING_JOB_NOT_FOUND,
            detail=f"Source job {source_job_id} not found.",
        )
    if source_row.admin_id != admin_id:
        raise EmbeddingError(
            EMBEDDING_JOB_NOT_FOUND,
            detail=f"Source job {source_job_id} not found.",
        )

    # Explicitly validate source terminal status (Finding 3).
    # Active jobs are blocked by the active-job check below, but completed
    # jobs with failed rows must also be rejected — only failed/partially_failed
    # are valid retry sources.  Queued jobs with no started files are the
    # enqueue-only failure path (handled below).
    if source_row.status not in (
        JOB_STATUS_FAILED,
        JOB_STATUS_PARTIALLY_FAILED,
        JOB_STATUS_QUEUED,
    ):
        raise EmbeddingError(
            EMBEDDING_JOB_WRONG_STATUS,
            detail=(
                f"Source job {source_job_id} is {source_row.status}; "
                f"expected failed, partially_failed, or queued (enqueue-only)."
            ),
        )

    # 2. Lock admin state row FIRST to serialise concurrent retries.
    state_row = (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin_id)
        .with_for_update()
        .first()
    )

    # 3. Recheck active job AFTER acquiring state lock.
    active = (
        db.query(EmbeddingJob)
        .filter(
            EmbeddingJob.admin_id == admin_id,
            EmbeddingJob.status.in_(_ACTIVE_JOB_STATUSES),
        )
        .first()
    )
    if active is not None:
        raise EmbeddingError(
            EMBEDDING_RETRY_ACTIVE_EXISTS,
            detail={
                "message": f"Admin {admin_id} already has an active job {active.id}.",
                "active_job_id": active.id,
                "active_job_status": active.status,
            },
        )

    # 4. Target consistency: state must exist and target must match source.
    if state_row is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=f"No embedding model state for admin {admin_id}.",
        )
    if state_row.target_embedding_model_id is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=f"Admin {admin_id} has no target model; retry requires a pending target.",
        )
    if state_row.target_embedding_model_id != source_row.embedding_model_id:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=(
                f"Source job target '{source_row.embedding_model_id}' does not "
                f"match current admin target '{state_row.target_embedding_model_id}'."
            ),
        )

    # 5. Walk the full retry lineage chain to collect ALL files that will
    #    contribute vectors to the final promoted model space.  A retry
    #    activates ALL building vectors (source + retry), so every file in
    #    the chain must be content-checked.
    #
    #    Depth is capped at 16 to prevent runaway walks from corrupted or
    #    circular lineage data.  Practical retry chains are ≤3 deep.
    _MAX_LINEAGE_DEPTH = 16
    lineage_job_ids: list[str] = []
    cursor_id: str | None = source_job_id
    while cursor_id is not None and len(lineage_job_ids) < _MAX_LINEAGE_DEPTH:
        if cursor_id in lineage_job_ids:
            break  # cycle guard
        lineage_job_ids.append(cursor_id)
        cursor_row = (
            db.query(EmbeddingJob.source_job_id)
            .filter(EmbeddingJob.id == cursor_id)
            .first()
        )
        cursor_id = cursor_row[0] if cursor_row else None
    if len(lineage_job_ids) >= _MAX_LINEAGE_DEPTH:
        log.warning(
            "[JOB] lineage depth cap (%d) reached for source job %s; "
            "some ancestor files may not be checked",
            _MAX_LINEAGE_DEPTH,
            source_job_id,
        )

    all_lineage_rows = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id.in_(lineage_job_ids))
        .order_by(EmbeddingJobFile.job_id, EmbeddingJobFile.file_id)
        .all()
    )

    # Deduplicate by file_id, keeping the most recent snapshot (last in chain).
    seen_files: dict[str, object] = {}
    for frow in all_lineage_rows:
        seen_files[frow.file_id] = frow

    all_source_rows = list(seen_files.values())

    failed_rows = []
    has_processing_or_completed = False
    for frow in all_source_rows:
        if frow.status == FILE_STATUS_FAILED:
            failed_rows.append(frow)
        elif frow.status in (FILE_STATUS_PROCESSING, FILE_STATUS_COMPLETED):
            has_processing_or_completed = True

    # Content staleness: check ALL files in the lineage chain so stale
    # vectors from previously successful files are never silently promoted.
    for frow in all_source_rows:
        snapshot = frow.file_snapshot if isinstance(frow.file_snapshot, dict) else {}
        original_hash = snapshot.get("content_hash")
        if not original_hash:
            # Missing hash: cannot verify — fail closed.
            raise EmbeddingError(
                EMBEDDING_REINDEX_SOURCE_CHANGED,
                detail=(
                    f"File {frow.file_id} has no content hash in snapshot; "
                    f"cannot verify staleness. A fresh model-change is required."
                ),
            )
        current_file = db.query(File).filter(File.id == frow.file_id).first()
        if current_file is None:
            raise EmbeddingError(
                EMBEDDING_REINDEX_SOURCE_CHANGED,
                detail=(
                    f"File {frow.file_id} no longer exists. "
                    f"A fresh model-change is required."
                ),
            )
        if not current_file.hash:
            raise EmbeddingError(
                EMBEDDING_REINDEX_SOURCE_CHANGED,
                detail=(
                    f"File {frow.file_id} has no current content hash; "
                    f"cannot verify staleness. A fresh model-change is required."
                ),
            )
        if current_file.hash != original_hash:
            raise EmbeddingError(
                EMBEDDING_REINDEX_SOURCE_CHANGED,
                detail=(
                    f"File {frow.file_id} content has changed since the original job "
                    f"(original={original_hash}, current={current_file.hash}). "
                    f"A fresh model-change operation is required."
                ),
            )

    # 6. Enqueue-only failure path: source job is queued, no files were ever
    #    started, and all files are still pending.  Re-enqueue the source job
    #    rather than creating a duplicate retry job.
    if (
        source_row.status in (JOB_STATUS_FAILED, JOB_STATUS_QUEUED)
        and not has_processing_or_completed
        and not failed_rows
    ):
        # All files are pending — this is an enqueue-only failure.
        # Mark source job as queued (reset if it was failed) and return it
        # for re-enqueue.  Clear completed_at so finalization timestamps
        # reflect the actual completion, not the original enqueue failure.
        if source_row.status in (JOB_STATUS_FAILED, JOB_STATUS_QUEUED):
            source_row.status = JOB_STATUS_QUEUED
            source_row.error_code = None
            source_row.error_message = None
            source_row.completed_at = None
            source_row.updated_at = now
        db.flush()
        log.info(
            "[JOB] re-enqueue path for source job %s (enqueue-only failure)",
            source_job_id,
        )
        return CreateJobResult(
            job=_job_to_view(source_row),
            files=tuple(_file_to_view(fr) for fr in all_source_rows),
        )

    if not failed_rows:
        raise EmbeddingError(
            EMBEDDING_JOB_WRONG_STATUS,
            detail=f"Source job {source_job_id} has no failed files to retry.",
        )

    # 7. Create new retry_failed job with fresh pending file rows.
    retry_files = [ReindexFile.from_dict(fr.file_snapshot) for fr in failed_rows]

    new_job_id = str(uuid.uuid4())
    job_row = EmbeddingJob(
        id=new_job_id,
        admin_id=admin_id,
        embedding_model_id=source_row.embedding_model_id,
        previous_embedding_model_id=source_row.previous_embedding_model_id,
        job_type="retry_failed",
        status=JOB_STATUS_QUEUED,
        total_files=len(retry_files),
        processed_files=0,
        failed_files=0,
        source_job_id=source_job_id,
        created_at=now,
        updated_at=now,
    )
    db.add(job_row)

    for reindex_file in retry_files:
        file_row = EmbeddingJobFile(
            job_id=new_job_id,
            file_id=reindex_file.file_id,
            status=FILE_STATUS_PENDING,
            attempt_count=0,
            file_snapshot=reindex_file.to_dict(),
            created_at=now,
            updated_at=now,
        )
        db.add(file_row)

    # 8. Update latest job pointer atomically.
    state_row.latest_embedding_job_id = new_job_id
    state_row.updated_at = now

    db.flush()

    log.info(
        "[JOB] created retry job %s from source %s for admin %s: %d failed files",
        new_job_id,
        source_job_id,
        admin_id,
        len(retry_files),
    )
    return CreateJobResult(
        job=_job_to_view(job_row),
        files=tuple(
            EmbeddingJobFileView(
                job_id=new_job_id,
                file_id=rf.file_id,
                status=FILE_STATUS_PENDING,
                attempt_count=0,
                error_code=None,
                error_message=None,
                file_snapshot=rf.to_dict(),
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
            )
            for rf in retry_files
        ),
    )


def _transition_to_processing(
    db, job_id: str
) -> tuple[Optional[EmbeddingJobView], bool]:
    """Internal: atomically transition queued -> processing (flush only).

    Returns ``(view, changed)`` where *changed* is True when the job was
    actually transitioned (queued → processing) and False when the job was
    already processing (no-op).

    Returns ``(None, False)`` if job not found.
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
        return None, False
    if row.status == JOB_STATUS_PROCESSING:
        return _job_to_view(row), False  # no-op: already processing
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
    return _job_to_view(row), True


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


def _collect_job_lineage(db, job_id: str) -> list[str]:
    """Walk the source_job_id chain and return all IDs in the lineage.

    The returned list always contains *job_id* itself plus every ancestor
    reachable via ``source_job_id``.  The walk is bounded by the depth of
    the retry chain (typically 1–2 hops).
    """
    lineage: list[str] = []
    current: str | None = job_id
    while current is not None:
        if current in lineage:
            break  # defensive: cycle guard
        lineage.append(current)
        current = (
            db.query(EmbeddingJob.source_job_id)
            .filter(EmbeddingJob.id == current)
            .scalar()
        )
    return lineage


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


def _finalize_job_success(
    db,
    job_id: str,
    admin_id: str,
    target_model_id: str,
    previous_model_id: Optional[str],
    vector_repo,
    target_model_spec,
) -> Optional[EmbeddingJobView]:
    """Atomically finalize a successful job: activate vectors, promote model, complete job (Spec 09).

    Steps (all within the caller-owned ``db`` session):
    1. Lock the job row (``SELECT … FOR UPDATE``).
    2. Reject if any file is still unfinished (pending/processing).
    3. If already terminal, return current view (idempotent no-op).
    4. Lock admin model state and validate target consistency.
    5. Activate target job vectors (building → active).
    6. Deactivate previous-model vectors (active → inactive).
    7. Promote target model to active and clear target.
    8. Mark job completed and set completion timestamp.
    9. Flush (caller commits atomically).

    A zero-file job may complete and promote because no governed vectors
    can be mixed.

    Raises:
        EmbeddingError (EMBEDDING_JOB_STALE_OPERATION): if the job is no
            longer the latest for this admin and cannot promote a model.
        EmbeddingError (EMBEDDING_MODEL_STATE_CONFLICT): if admin state
            has no target, target mismatches job, or latest-job mismatch.
    """
    from open_webui.models.embeddings import AdminEmbeddingModelState

    now = _now()

    # 1. Lock job
    job_row = (
        db.query(EmbeddingJob)
        .filter(EmbeddingJob.id == job_id)
        .with_for_update()
        .first()
    )
    if job_row is None:
        return None

    # 3. Already terminal: idempotent no-op
    if job_row.status in _TERMINAL_JOB_STATUSES:
        return _job_to_view(job_row)

    # 2. Recompute and verify no files are unfinished
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
    unfinished = total - processed - failed
    if unfinished > 0:
        log.warning(
            "[JOB] finalize_job_success rejected for job %s: %d files still unfinished",
            job_id,
            unfinished,
        )
        job_row.total_files = total
        job_row.processed_files = processed
        job_row.failed_files = failed
        job_row.updated_at = now
        db.flush()
        return _job_to_view(job_row)

    # Update counters
    job_row.total_files = total
    job_row.processed_files = processed
    job_row.failed_files = failed

    # All files must be completed for a successful finalization
    if total != processed:
        log.warning(
            "[JOB] finalize_job_success called on job %s with %d/%d completed; "
            "caller should use _finalize_job for partial/failure outcomes",
            job_id,
            processed,
            total,
        )
        # Fall through to _finalize_job behavior for non-all-success cases
        job_row.status = JOB_STATUS_PARTIALLY_FAILED if processed > 0 and failed > 0 else JOB_STATUS_FAILED
        if job_row.completed_at is None:
            job_row.completed_at = now
        job_row.updated_at = now
        db.flush()
        return _job_to_view(job_row)

    # 4. Lock admin model state and validate target consistency
    state_row = (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin_id)
        .with_for_update()
        .first()
    )
    if state_row is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=f"No embedding model state for admin {admin_id}.",
        )
    if state_row.latest_embedding_job_id != job_id:
        raise EmbeddingError(
            EMBEDDING_JOB_STALE_OPERATION,
            detail=(
                f"Job {job_id} is no longer the latest for admin {admin_id} "
                f"(latest is {state_row.latest_embedding_job_id}); "
                f"refusing promotion."
            ),
        )
    if state_row.target_embedding_model_id is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=f"Admin {admin_id} has no target model to promote.",
        )
    if state_row.target_embedding_model_id != target_model_id:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=(
                f"Admin target model '{state_row.target_embedding_model_id}' does not "
                f"match job target '{target_model_id}'; refusing promotion."
            ),
        )

    # 5. Activate target vectors (building → active) for this admin/model,
    #    scoped to the job lineage (current job + source chain).  This ensures
    #    a retry publishes both its own repaired rows and the prior successful
    #    rows from the source job, while leaving vectors from unrelated
    #    abandoned operations in building status.
    lineage = _collect_job_lineage(db, job_id)
    activated = vector_repo.activate_target_vectors(
        admin_id=admin_id,
        model=target_model_spec,
        session=db,
        job_ids=lineage,
    )
    log.info(
        "[JOB] activated %d target vectors for admin %s model %s",
        activated,
        admin_id,
        target_model_id,
    )

    # 6. Deactivate previous-model vectors (active → inactive).
    #    Uses caller's db session; failure aborts finalization.
    if previous_model_id:
        from open_webui.retrieval.embedding.registry import get_model_spec_by_id

        prev_spec = get_model_spec_by_id(previous_model_id)
        deactivated = vector_repo.deactivate_previous_model_vectors(
            admin_id=admin_id,
            model=prev_spec,
            session=db,
        )
        log.info(
            "[JOB] deactivated %d previous-model vectors for admin %s model %s",
            deactivated,
            admin_id,
            previous_model_id,
        )

    # 7. Promote target model → active, clear target
    state_row.active_embedding_model_id = state_row.target_embedding_model_id
    state_row.target_embedding_model_id = None
    state_row.updated_at = now

    # 8. Mark job completed
    job_row.status = JOB_STATUS_COMPLETED
    if job_row.completed_at is None:
        job_row.completed_at = now
    job_row.updated_at = now
    db.flush()

    log.info(
        "[JOB] finalized successful job %s: completed, target model %s promoted for admin %s",
        job_id,
        target_model_id,
        admin_id,
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

        Note: the internal ``_transition_to_processing`` returns ``(view, changed)``;
        this public wrapper discards the flag for backward compatibility.  Use the
        internal function directly when you need to distinguish a fresh claim from an
        already-processing no-op.
        """
        if db is None:
            with get_db() as session:
                view, _changed = _transition_to_processing(session, job_id)
                session.commit()
                return view
        view, _changed = _transition_to_processing(db, job_id)
        return view

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
    def finalize_job_success(
        job_id: str,
        admin_id: str,
        target_model_id: str,
        previous_model_id: Optional[str],
        vector_repo,
        target_model_spec,
        db=None,
    ) -> Optional[EmbeddingJobView]:
        """Atomically finalize a successful job: activate vectors, promote model, complete job.

        All steps (vector activation, model promotion, job completion) execute
        within a single transaction for atomicity. Idempotent: returns current
        view if already terminal.

        Raises:
            EmbeddingError (EMBEDDING_JOB_STALE_OPERATION): if the job is no
                longer the latest for this admin.
            EmbeddingError (EMBEDDING_MODEL_STATE_CONFLICT): if admin state
                is missing or inconsistent.
        """
        if db is None:
            with get_db() as session:
                view = _finalize_job_success(
                    session,
                    job_id,
                    admin_id,
                    target_model_id,
                    previous_model_id,
                    vector_repo,
                    target_model_spec,
                )
                session.commit()
                return view
        return _finalize_job_success(
            db,
            job_id,
            admin_id,
            target_model_id,
            previous_model_id,
            vector_repo,
            target_model_spec,
        )

    @staticmethod
    def create_retry_job(
        source_job_id: str,
        admin_id: str,
        db=None,
    ) -> CreateJobResult:
        """Create a retry_failed job from a source job's failed files.

        Validates source job status, no active jobs, target consistency, and
        content staleness.  Creates a new ``retry_failed`` job with fresh
        pending file rows.  The source job is never modified.

        Raises:
            EmbeddingError: on validation failure (wrong status, active job,
                target mismatch, source content changed).
        """
        if db is None:
            with get_db() as session:
                result = _create_retry_job(session, source_job_id, admin_id)
                session.commit()
                return result
        return _create_retry_job(db, source_job_id, admin_id)

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
