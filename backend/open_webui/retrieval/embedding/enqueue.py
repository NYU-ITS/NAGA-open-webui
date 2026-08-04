"""Durable reindex enqueue: connect committed embedding jobs to RQ (Spec 05).

This module bridges committed embedding jobs and the RQ worker queue. It ensures:
- Only embedding_job_id is passed (no sensitive data)
- Deterministic RQ job IDs for duplicate detection
- rq_job_id is persisted to the durable job BEFORE enqueue
- Enqueue failures are durable and visible
- Worker-level crashes use bounded RQ retry

Critical invariants:
- Queue unavailable → mark job failed with sanitized error
- Concurrent enqueue → detect race, return existing RQ job ID
- Persistence failure → raise explicit error, never silent failure
- RQ lookup errors → distinguish NoSuchJobError from connection failures
- Error messages → bounded category/message only, no raw exceptions

Non-goals:
- Processing individual files (handled by worker)
- File-level retry semantics (database-driven via Spec 03)
- General upload queue replacement
"""

import logging
from typing import Optional

from rq import Queue, Retry
from rq.job import Job, JobStatus
from rq.exceptions import NoSuchJobError
from redis.exceptions import ConnectionError, TimeoutError

from open_webui.internal.db import get_db
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_NOT_FOUND,
    EMBEDDING_JOB_WRONG_STATUS,
)
from open_webui.retrieval.embedding.jobs import (
    EmbeddingJobRepository,
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
)
from open_webui.utils.job_queue import get_job_queue
from open_webui.env import (
    JOB_RESULT_TTL,
    JOB_FAILURE_TTL,
)

log = logging.getLogger(__name__)

# Queue name for embedding reindex jobs
EMBEDDING_REINDEX_QUEUE_NAME = "embedding_reindex"

# Job timeout (30 minutes for large reindex operations)
EMBEDDING_JOB_TIMEOUT = 1800  # 30 minutes

# Max retries for worker-level crashes
EMBEDDING_MAX_RETRIES = 3

# Retry delay in seconds
EMBEDDING_RETRY_DELAY = 60  # 1 minute


def _make_rq_job_id(embedding_job_id: str) -> str:
    """Generate deterministic RQ job ID for an embedding job.
    
    Args:
        embedding_job_id: Durable embedding job ID from database
        
    Returns:
        Deterministic RQ job ID
    """
    return f"embedding_reindex_{embedding_job_id}"


def _sanitize_error_message(error: Exception, category: str) -> str:
    """Sanitize exception to bounded category/message.
    
    Never stores raw exception text which may contain credentials or connection details.
    
    Args:
        error: Exception to sanitize
        category: Error category (e.g., "RQ_ENQUEUE_FAILED", "RQ_PERSISTENCE_FAILED")
        
    Returns:
        Sanitized error message: "category: exception_type"
    """
    return f"{category}: {type(error).__name__}"


def _mark_job_failed_with_error(
    embedding_job_id: str,
    error_code: str,
    error: Exception,
    category: str,
) -> None:
    """Mark durable job as failed with sanitized error message.
    
    Raises explicit error if persistence itself fails (no silent failure).
    
    Args:
        embedding_job_id: Durable job ID
        error_code: Stable error code
        error: Exception that caused failure
        category: Error category for sanitization
    """
    sanitized_message = _sanitize_error_message(error, category)
    
    try:
        with get_db() as db:
            EmbeddingJobRepository.mark_job_failed(
                job_id=embedding_job_id,
                error_code=error_code,
                error_message=sanitized_message,
                db=db,
            )
            db.commit()
    except Exception as persist_error:
        # Explicit reconciliation signal: cannot guarantee durable failure state
        log.critical(
            f"[EMBEDDING_ENQUEUE] CRITICAL: Failed to persist job failure for {embedding_job_id}. "
            f"Job may remain in queued state indefinitely. Manual intervention required. "
            f"Original error: {sanitized_message}, Persistence error: {type(persist_error).__name__}"
        )
        raise RuntimeError(
            f"Failed to persist job failure for {embedding_job_id}. "
            f"Job state is inconsistent. Manual intervention required."
        ) from persist_error


def enqueue_embedding_job(embedding_job_id: str) -> str:
    """Enqueue an embedding job to RQ for processing.
    
    Connects a committed embedding job to the RQ worker queue. Only the
    embedding_job_id is passed in the payload (no sensitive data).
    
    Critical flow:
    1. Verify job exists and is enqueueable (queued OR processing with STARTED RQ job)
    2. Persist rq_job_id BEFORE enqueue (prevents split-brain)
    3. Check for existing RQ job (handle concurrent enqueue race)
    4. Enqueue to RQ (handle duplicate-ID race)
    5. On any failure: mark job failed with sanitized error
    
    Args:
        embedding_job_id: Durable embedding job ID
        
    Returns:
        RQ job ID (deterministic: embedding_reindex_{embedding_job_id})
        
    Raises:
        EmbeddingError: EMBEDDING_JOB_NOT_FOUND if job doesn't exist
        EmbeddingError: EMBEDDING_JOB_WRONG_STATUS if job is not enqueueable
        RuntimeError: If RQ queue is unavailable
    """
    log.info(f"[EMBEDDING_ENQUEUE] Starting enqueue for job {embedding_job_id}")
    
    # Step 1: Verify job exists and is enqueueable
    with get_db() as db:
        job_view = EmbeddingJobRepository.get_job(embedding_job_id, db=db)
        if job_view is None:
            raise EmbeddingError(
                EMBEDDING_JOB_NOT_FOUND,
                detail=f"Embedding job {embedding_job_id} not found.",
            )
        
        # Allow queued status OR processing status (worker may have started)
        if job_view.status not in [JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING]:
            raise EmbeddingError(
                EMBEDDING_JOB_WRONG_STATUS,
                detail=f"Embedding job {embedding_job_id} is {job_view.status}, expected 'queued' or 'processing'.",
            )
    
    # Step 2: Generate deterministic RQ job ID and persist BEFORE enqueue
    rq_job_id = _make_rq_job_id(embedding_job_id)
    
    try:
        with get_db() as db:
            EmbeddingJobRepository.attach_rq_job_id(
                job_id=embedding_job_id,
                rq_job_id=rq_job_id,
                db=db,
            )
            db.commit()
        log.debug(f"[EMBEDDING_ENQUEUE] Persisted rq_job_id={rq_job_id} for job {embedding_job_id}")
    except Exception as persist_error:
        # Persistence failure: mark job failed with explicit error
        log.error(
            f"[EMBEDDING_ENQUEUE] Failed to persist rq_job_id for job {embedding_job_id}: {persist_error}",
            exc_info=True
        )
        _mark_job_failed_with_error(
            embedding_job_id=embedding_job_id,
            error_code="RQ_PERSISTENCE_FAILED",
            error=persist_error,
            category="Failed to persist RQ job ID",
        )
        raise RuntimeError(
            f"Failed to persist RQ job ID for {embedding_job_id}"
        ) from persist_error
    
    # Step 3: Get RQ queue (handle queue unavailable)
    try:
        queue = get_job_queue(queue_name=EMBEDDING_REINDEX_QUEUE_NAME)
        if queue is None:
            raise RuntimeError(f"RQ queue '{EMBEDDING_REINDEX_QUEUE_NAME}' unavailable")
        
        # Step 4: Check for existing RQ job (handle concurrent enqueue race)
        try:
            existing_rq_job = Job.fetch(rq_job_id, connection=queue.connection)
            if existing_rq_job:
                rq_status = existing_rq_job.get_status()
                
                # Allow queued or started status (worker may be running)
                if rq_status in [JobStatus.QUEUED, JobStatus.STARTED]:
                    log.info(
                        f"[EMBEDDING_ENQUEUE] RQ job {rq_job_id} already exists with status {rq_status}, "
                        f"returning existing job ID"
                    )
                    return rq_job_id
                
                # Finished/failed RQ record: check durable job status
                if job_view.status == JOB_STATUS_QUEUED:
                    # Durable job is still queued but RQ record is stale
                    # Follow Spec 11 retry/re-enqueue policy (out of scope for Spec 05)
                    log.warning(
                        f"[EMBEDDING_ENQUEUE] RQ job {rq_job_id} is {rq_status} but durable job is queued. "
                        f"Retry/re-enqueue policy not implemented in Spec 05."
                    )
                    # Allow re-enqueue (will create new RQ job with same ID)
                else:
                    # Durable job is terminal (completed/failed)
                    log.warning(
                        f"[EMBEDDING_ENQUEUE] Durable job {embedding_job_id} is {job_view.status}, "
                        f"rejecting enqueue despite stale RQ record {rq_status}"
                    )
                    raise EmbeddingError(
                        EMBEDDING_JOB_WRONG_STATUS,
                        detail=f"Cannot enqueue terminal job {embedding_job_id} (status={job_view.status})",
                    )
        
        except NoSuchJobError:
            # Job doesn't exist in RQ - proceed with enqueue
            log.debug(f"[EMBEDDING_ENQUEUE] RQ job {rq_job_id} does not exist, proceeding with enqueue")
        
        except (ConnectionError, TimeoutError) as redis_error:
            # Redis connection failure: mark job failed
            log.error(
                f"[EMBEDDING_ENQUEUE] Redis connection error while checking RQ job {rq_job_id}: {redis_error}",
                exc_info=True
            )
            _mark_job_failed_with_error(
                embedding_job_id=embedding_job_id,
                error_code="RQ_CONNECTION_FAILED",
                error=redis_error,
                category="Redis connection error",
            )
            raise RuntimeError(
                f"Redis connection error while checking RQ job {rq_job_id}"
            ) from redis_error
        
        except Exception as fetch_error:
            # Unexpected error during fetch: mark job failed
            log.error(
                f"[EMBEDDING_ENQUEUE] Unexpected error fetching RQ job {rq_job_id}: {fetch_error}",
                exc_info=True
            )
            _mark_job_failed_with_error(
                embedding_job_id=embedding_job_id,
                error_code="RQ_FETCH_FAILED",
                error=fetch_error,
                category="RQ job fetch error",
            )
            raise RuntimeError(
                f"Failed to fetch RQ job {rq_job_id}"
            ) from fetch_error
        
        # Step 5: Enqueue to RQ (handle duplicate-ID race)
        try:
            # Import worker function (Spec 10: worker import boundary)
            # Worker may not exist yet in Spec 05, so use string path
            from open_webui.workers.embedding_worker import process_embedding_job
            
            rq_job = queue.enqueue(
                process_embedding_job,
                embedding_job_id=embedding_job_id,
                job_timeout=EMBEDDING_JOB_TIMEOUT,
                retry=Retry(max=EMBEDDING_MAX_RETRIES, interval=EMBEDDING_RETRY_DELAY),
                job_id=rq_job_id,
                result_ttl=JOB_RESULT_TTL,
                failure_ttl=JOB_FAILURE_TTL,
            )
            
            log.info(
                f"[EMBEDDING_ENQUEUE] Enqueued embedding job | job_id={embedding_job_id} | "
                f"rq_job_id={rq_job.id} | queue={EMBEDDING_REINDEX_QUEUE_NAME}"
            )
            
            return rq_job.id
        
        except Exception as enqueue_error:
            # Check if this is a duplicate-ID race (another caller already enqueued)
            error_str = str(enqueue_error).lower()
            if "already exists" in error_str or "duplicate" in error_str:
                # Concurrent enqueue race: fetch existing job
                log.warning(
                    f"[EMBEDDING_ENQUEUE] Duplicate RQ job ID {rq_job_id} detected, "
                    f"fetching existing job (concurrent enqueue race)"
                )
                try:
                    existing_rq_job = Job.fetch(rq_job_id, connection=queue.connection)
                    if existing_rq_job:
                        log.info(
                            f"[EMBEDDING_ENQUEUE] Resolved duplicate-ID race, returning existing job {rq_job_id}"
                        )
                        return rq_job_id
                except Exception as fetch_error:
                    log.error(
                        f"[EMBEDDING_ENQUEUE] Failed to fetch existing RQ job after duplicate-ID race: {fetch_error}",
                        exc_info=True
                    )
            
            # Enqueue failure: mark job failed
            log.error(
                f"[EMBEDDING_ENQUEUE] Failed to enqueue job {embedding_job_id}: {enqueue_error}",
                exc_info=True
            )
            _mark_job_failed_with_error(
                embedding_job_id=embedding_job_id,
                error_code="RQ_ENQUEUE_FAILED",
                error=enqueue_error,
                category="RQ enqueue failed",
            )
            raise RuntimeError(
                f"Failed to enqueue embedding job {embedding_job_id} to RQ"
            ) from enqueue_error
    
    except RuntimeError:
        # Re-raise RuntimeError (queue unavailable, Redis errors, enqueue failures)
        raise
    
    except Exception as unexpected_error:
        # Unexpected error: mark job failed
        log.error(
            f"[EMBEDDING_ENQUEUE] Unexpected error enqueueing job {embedding_job_id}: {unexpected_error}",
            exc_info=True
        )
        _mark_job_failed_with_error(
            embedding_job_id=embedding_job_id,
            error_code="RQ_UNEXPECTED_ERROR",
            error=unexpected_error,
            category="Unexpected enqueue error",
        )
        raise RuntimeError(
            f"Unexpected error enqueueing job {embedding_job_id}"
        ) from unexpected_error
