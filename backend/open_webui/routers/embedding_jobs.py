"""Embedding job status and retry API (Spec 11).

Endpoints::

    GET  /embedding/jobs/latest      — latest job status for the authenticated admin
    GET  /embedding/jobs/{job_id}    — detailed status for one job
    POST /embedding/jobs/{job_id}/retry — retry failed files from a terminal job

Only the owning admin may access these endpoints.  Regular users and unrelated
admins receive 403/404 consistent with repository conventions.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from open_webui.internal.db import get_db
from open_webui.models.users import Users
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_ACTIVE_EXISTS,
    EMBEDDING_JOB_NOT_FOUND,
    EMBEDDING_JOB_WRONG_STATUS,
    EMBEDDING_MODEL_STATE_CONFLICT,
    EMBEDDING_REINDEX_SOURCE_CHANGED,
    EMBEDDING_RETRY_ACTIVE_EXISTS,
)
from open_webui.retrieval.embedding.jobs import (
    EmbeddingJobRepository,
    EmbeddingJobView,
    EmbeddingJobFileView,
    EmbeddingJobStatusView,
    FILE_STATUS_FAILED,
    FILE_STATUS_PENDING,
    is_job_retry_eligible,
)
from open_webui.retrieval.embedding.enqueue import enqueue_embedding_job
from open_webui.retrieval.embedding.state import AdminEmbeddingModelStateRepository
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)

router = APIRouter()

# ─── Status response models ─────────────────────────────────────────────────


class FailedFileInfo(BaseModel):
    """Per-file failure detail."""

    file_id: str
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    created_at: int | None = None
    updated_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None


class EmbeddingJobStatusResponse(BaseModel):
    """Full status response for an embedding job."""

    job_id: str
    job_type: str
    status: str
    admin_id: str

    # Model context
    embedding_model_id: str
    previous_embedding_model_id: str | None = None

    # Admin state
    active_model_id: str | None = None
    target_model_id: str | None = None

    # Aggregate counters
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    pending_or_processing: int = 0

    # Source-context breakdown
    source_contexts: dict[str, dict] | None = None

    # Failed file details
    failed_files_detail: list[FailedFileInfo] = []

    # Operation-level error
    error_code: str | None = None
    error_message: str | None = None

    # Retry eligibility (considers active jobs, target state, source changes)
    retry_eligible: bool = False

    # Timestamps
    created_at: int | None = None
    updated_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None


class RetryResponse(BaseModel):
    """Response for a successful retry request."""

    job_id: str
    source_job_id: str
    job_type: str
    status: str
    total_files: int


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _require_admin(user) -> str:
    """Verify the requesting user is an admin and return their ID.

    Regular users and group members receive 403 Forbidden.  Only direct admins
    may access embedding job status and retry endpoints (Spec 11).
    """
    subject = Users.get_user_by_id(user.id)
    if subject is None or subject.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins may access embedding job endpoints.",
        )
    return subject.id


def _compute_retry_eligible(
    job_view: EmbeddingJobView,
    admin_id: str,
) -> bool:
    """Compute accurate retry eligibility for a job.

    Returns True when the stable retry prerequisites are met. The retry
    endpoint still revalidates source freshness transactionally.
    """
    active = EmbeddingJobRepository.get_active_job(admin_id)
    state = AdminEmbeddingModelStateRepository.get_state(admin_id)
    files = EmbeddingJobRepository.list_files(job_view.id)
    return is_job_retry_eligible(
        job_view,
        target_model_id=state.target_embedding_model_id if state else None,
        has_active_job=active is not None,
        has_failed_files=any(file.status == FILE_STATUS_FAILED for file in files),
        all_files_pending=all(file.status == FILE_STATUS_PENDING for file in files),
    )


def _build_status_response(
    job_view: EmbeddingJobView,
    failed_files: list[EmbeddingJobFileView],
    admin_id: str,
    state_view=None,
    status_view: EmbeddingJobStatusView | None = None,
) -> EmbeddingJobStatusResponse:
    """Build a rich status response from repository data."""

    # Source-context breakdown
    source_contexts = None
    pending_or_processing = job_view.total_files - job_view.processed_files - job_view.failed_files
    if status_view is not None:
        source_contexts = {
            bucket: {
                "total": counts.total,
                "processed": counts.processed,
                "failed": counts.failed,
                "pending_or_processing": counts.pending_or_processing,
            }
            for bucket, counts in status_view.source_contexts.items()
        }
        pending_or_processing = status_view.pending_or_processing

    retry_eligible = _compute_retry_eligible(job_view, admin_id)

    return EmbeddingJobStatusResponse(
        job_id=job_view.id,
        job_type=job_view.job_type,
        status=job_view.status,
        admin_id=job_view.admin_id,
        embedding_model_id=job_view.embedding_model_id,
        previous_embedding_model_id=job_view.previous_embedding_model_id,
        active_model_id=state_view.active_embedding_model_id if state_view else None,
        target_model_id=state_view.target_embedding_model_id if state_view else None,
        total_files=job_view.total_files,
        processed_files=job_view.processed_files,
        failed_files=job_view.failed_files,
        pending_or_processing=pending_or_processing,
        source_contexts=source_contexts,
        failed_files_detail=[
            FailedFileInfo(
                file_id=f.file_id,
                error_code=f.error_code,
                error_message=f.error_message,
                attempt_count=f.attempt_count,
                created_at=f.created_at,
                updated_at=f.updated_at,
                started_at=f.started_at,
                completed_at=f.completed_at,
            )
            for f in failed_files
        ],
        error_code=job_view.error_code,
        error_message=job_view.error_message,
        retry_eligible=retry_eligible,
        created_at=job_view.created_at,
        updated_at=job_view.updated_at,
        started_at=job_view.started_at,
        completed_at=job_view.completed_at,
    )


def _get_job_for_admin(job_id: str, admin_id: str) -> EmbeddingJobView:
    """Load a job and verify it belongs to the requesting admin."""
    job = EmbeddingJobRepository.get_job(job_id)
    if job is None or job.admin_id != admin_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embedding job not found.",
        )
    return job


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/embedding/jobs/latest")
def get_latest_job_status(
    request: Request,
    user=Depends(get_verified_user),
):
    """Return the latest embedding job status for the authenticated admin."""
    admin_id = _require_admin(user)

    job_view = EmbeddingJobRepository.get_latest_job(admin_id)
    if job_view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No embedding job found for this admin.",
        )

    failed_files = EmbeddingJobRepository.list_failed_files(job_view.id)
    state_data = AdminEmbeddingModelStateRepository.get_state(admin_id)
    status_view = EmbeddingJobRepository.get_job_status(job_view.id)

    return _build_status_response(
        job_view=job_view,
        failed_files=failed_files,
        admin_id=admin_id,
        state_view=state_data,
        status_view=status_view,
    )


@router.get("/embedding/jobs/{job_id}")
def get_job_status(
    job_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """Return detailed status for a specific embedding job."""
    admin_id = _require_admin(user)
    job_view = _get_job_for_admin(job_id, admin_id)

    failed_files = EmbeddingJobRepository.list_failed_files(job_id)
    state_data = AdminEmbeddingModelStateRepository.get_state(admin_id)
    status_view = EmbeddingJobRepository.get_job_status(job_id)

    return _build_status_response(
        job_view=job_view,
        failed_files=failed_files,
        admin_id=admin_id,
        state_view=state_data,
        status_view=status_view,
    )


@router.post("/embedding/jobs/{job_id}/retry")
def retry_failed_job(
    job_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """Retry failed files from a terminal embedding job.

    Creates a new ``retry_failed`` job containing only the source job's failed
    files.  The source job is never modified.  Returns 409 if an active job
    exists, the source content has changed, or the target is mismatched.
    """
    admin_id = _require_admin(user)

    # Verify source job belongs to this admin before attempting retry.
    _get_job_for_admin(job_id, admin_id)

    try:
        with get_db() as db:
            result = EmbeddingJobRepository.create_retry_job(
                source_job_id=job_id,
                admin_id=admin_id,
                db=db,
            )
            db.commit()
    except EmbeddingError as e:
        if e.code in (EMBEDDING_JOB_ACTIVE_EXISTS, EMBEDDING_RETRY_ACTIVE_EXISTS):
            detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            detail["error_code"] = e.code
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail,
            )
        if e.code == EMBEDDING_REINDEX_SOURCE_CHANGED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": e.code, "message": str(e.detail)},
            )
        if e.code == EMBEDDING_JOB_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e.detail),
            )
        if e.code in (EMBEDDING_JOB_WRONG_STATUS, EMBEDDING_MODEL_STATE_CONFLICT):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": e.code, "message": str(e.detail)},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.detail),
        )

    # Enqueue the job.  On failure, mark the job as failed so it does not
    # remain stuck as queued.
    try:
        enqueue_embedding_job(result.job.id)
    except Exception as e:
        log.error(
            "[RETRY] Failed to enqueue job %s: %s",
            result.job.id,
            e,
            exc_info=True,
        )
        try:
            EmbeddingJobRepository.mark_job_failed(
                job_id=result.job.id,
                error_code="enqueue_failed",
                error_message=f"Failed to enqueue retry job: {type(e).__name__}",
            )
        except Exception as persist_err:
            log.error(
                "[RETRY] Failed to mark job %s as failed after enqueue error: %s",
                result.job.id,
                persist_err,
                exc_info=True,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retry job created but enqueue failed. Try again later.",
        )

    return RetryResponse(
        job_id=result.job.id,
        source_job_id=job_id,
        job_type=result.job.job_type,
        status=result.job.status,
        total_files=result.job.total_files,
    )
