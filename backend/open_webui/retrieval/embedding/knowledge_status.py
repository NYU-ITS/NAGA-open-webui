"""Credential-free reindex status projections for Workspace Knowledge."""

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func

from open_webui.models.embeddings import (
    AdminEmbeddingModelState,
    EmbeddingJob,
    EmbeddingJobFile,
    EmbeddingModel,
)
from open_webui.models.knowledge import Knowledge
from open_webui.retrieval.embedding.errors import EmbeddingError
from open_webui.retrieval.embedding.inventory import build_reindex_admin_resolver
from open_webui.retrieval.embedding.jobs import (
    FILE_STATUS_COMPLETED,
    FILE_STATUS_FAILED,
    FILE_STATUS_PENDING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIALLY_FAILED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_QUEUED,
    is_job_retry_eligible,
)

log = logging.getLogger(__name__)

_REINDEX_JOB_TYPES = ("reindex_model_change", "retry_failed")

KnowledgeIndexingDisplayState = Literal[
    "ready",
    "queued",
    "indexing",
    "partial",
    "failed",
    "unavailable",
]


class KnowledgeIndexingProgress(BaseModel):
    total: int = 0
    processed: int = 0
    failed: int = 0
    pending_or_processing: int = 0


class EmbeddingModelSummary(BaseModel):
    id: str
    provider: str
    display_name: str
    modalities: list[str] = Field(default_factory=list)
    status: str


class KnowledgeIndexingFailure(BaseModel):
    file_id: str
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    created_at: int | None = None
    updated_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None


class KnowledgeIndexingStatusSummary(BaseModel):
    knowledge_id: str
    display_state: KnowledgeIndexingDisplayState
    job_status: str | None = None
    retrieval_available: bool

    job_id: str | None = None
    job_type: str | None = None
    active_model: EmbeddingModelSummary | None = None
    target_model: EmbeddingModelSummary | None = None

    collection_progress: KnowledgeIndexingProgress = Field(
        default_factory=KnowledgeIndexingProgress
    )
    job_progress: KnowledgeIndexingProgress = Field(
        default_factory=KnowledgeIndexingProgress
    )
    failed_document_count: int = 0
    job_failed_document_count: int = 0

    error_code: str | None = None
    error_message: str | None = None
    retry_eligible: bool = False
    can_retry: bool = False

    created_at: int | None = None
    updated_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None
    last_successful_indexed_at: int | None = None


class KnowledgeIndexingStatusResponse(KnowledgeIndexingStatusSummary):
    failed_documents: list[KnowledgeIndexingFailure] = Field(default_factory=list)


def _model_summary(row: EmbeddingModel | None) -> EmbeddingModelSummary | None:
    if row is None:
        return None
    modalities = row.modalities if isinstance(row.modalities, list) else []
    return EmbeddingModelSummary(
        id=row.id,
        provider=row.provider,
        display_name=row.display_name,
        modalities=[str(modality) for modality in modalities],
        status=row.status,
    )


def _progress_from_rows(rows: list[EmbeddingJobFile]) -> KnowledgeIndexingProgress:
    processed = sum(row.status == FILE_STATUS_COMPLETED for row in rows)
    failed = sum(row.status == FILE_STATUS_FAILED for row in rows)
    total = len(rows)
    return KnowledgeIndexingProgress(
        total=total,
        processed=processed,
        failed=failed,
        pending_or_processing=max(0, total - processed - failed),
    )


def _job_progress(job: EmbeddingJob | None) -> KnowledgeIndexingProgress:
    if job is None:
        return KnowledgeIndexingProgress()
    return KnowledgeIndexingProgress(
        total=job.total_files,
        processed=job.processed_files,
        failed=job.failed_files,
        pending_or_processing=max(
            0,
            job.total_files - job.processed_files - job.failed_files,
        ),
    )


def _derive_display_state(
    state: AdminEmbeddingModelState | None,
    job: EmbeddingJob | None,
) -> tuple[KnowledgeIndexingDisplayState, bool]:
    if state is None:
        return "ready", True

    if state.latest_embedding_job_id is not None and job is None:
        return "unavailable", False

    if job is not None:
        if job.status == JOB_STATUS_QUEUED:
            return "queued", False
        if job.status == JOB_STATUS_PROCESSING:
            return "indexing", False
        if job.status == JOB_STATUS_PARTIALLY_FAILED:
            return "partial", False
        if job.status == JOB_STATUS_FAILED:
            return "failed", False
        if job.status != JOB_STATUS_COMPLETED:
            return "unavailable", False

    if state.target_embedding_model_id is not None:
        return "unavailable", False
    if not state.active_embedding_model_id:
        return "unavailable", False
    return "ready", True


def _stored_message(value: str | None) -> str | None:
    """Bound already-sanitized Phase 4 messages before returning them."""
    if not value:
        return None
    normalized = " ".join(str(value).split())
    return normalized[:500]


def _job_error_message(error_code: str | None) -> str | None:
    """Map durable job codes to user-safe messages without exposing details."""
    if error_code is None:
        return None
    if error_code.startswith("RQ_") or error_code == "enqueue_failed":
        return "The indexing job could not be queued. Try again later."
    if error_code == "embedding_job_stale_operation":
        return "This indexing job was superseded by a newer operation."
    if error_code == "embedding_model_state_conflict":
        return "The embedding model state changed before indexing could finish."
    if error_code == "embedding_reindex_source_changed":
        return "Source content changed during indexing. Start a new reindex operation."
    return "The embedding indexing job failed."


def _knowledge_rows_for_job(
    knowledge_id: str,
    rows: list[EmbeddingJobFile],
) -> list[EmbeddingJobFile]:
    matches = []
    for row in rows:
        snapshot = row.file_snapshot if isinstance(row.file_snapshot, dict) else {}
        collection_ids = snapshot.get("knowledge_collection_ids")
        if isinstance(collection_ids, list) and knowledge_id in collection_ids:
            matches.append(row)
    return matches


def build_knowledge_indexing_statuses(
    db,
    knowledge_rows: list[Knowledge],
    *,
    viewer_id: str,
    viewer_role: str,
    include_failure_details: bool,
) -> list[KnowledgeIndexingStatusResponse]:
    """Build status rows without mutating model state or configuration."""
    if not knowledge_rows:
        return []

    admin_resolver = build_reindex_admin_resolver(db)
    admin_by_knowledge: dict[str, str] = {}
    resolution_errors: dict[str, EmbeddingError] = {}
    for knowledge in knowledge_rows:
        try:
            admin_by_knowledge[knowledge.id] = admin_resolver.resolve_knowledge(knowledge)
        except EmbeddingError as error:
            resolution_errors[knowledge.id] = error
            log.warning(
                "[KNOWLEDGE_INDEXING_STATUS] governance unavailable for knowledge %s: %s",
                knowledge.id,
                error.code,
            )

    admin_ids = sorted(set(admin_by_knowledge.values()))
    states = (
        db.query(AdminEmbeddingModelState)
        .filter(AdminEmbeddingModelState.admin_id.in_(admin_ids))
        .all()
        if admin_ids
        else []
    )
    state_by_admin = {state.admin_id: state for state in states}

    latest_job_ids = [
        state.latest_embedding_job_id
        for state in states
        if state.latest_embedding_job_id is not None
    ]
    jobs = (
        db.query(EmbeddingJob).filter(EmbeddingJob.id.in_(latest_job_ids)).all()
        if latest_job_ids
        else []
    )
    job_by_id = {job.id: job for job in jobs}

    valid_jobs_by_admin: dict[str, EmbeddingJob] = {}
    for state in states:
        if state.latest_embedding_job_id is None:
            continue
        job = job_by_id.get(state.latest_embedding_job_id)
        if (
            job is not None
            and job.admin_id == state.admin_id
            and job.job_type in _REINDEX_JOB_TYPES
        ):
            valid_jobs_by_admin[state.admin_id] = job
        elif job is not None and job.admin_id != state.admin_id:
            log.error(
                "[KNOWLEDGE_INDEXING_STATUS] cross-admin latest job pointer for admin %s",
                state.admin_id,
            )
        elif job is not None:
            log.error(
                "[KNOWLEDGE_INDEXING_STATUS] unsupported latest job type for admin %s: %s",
                state.admin_id,
                job.job_type,
            )

    valid_job_ids = [job.id for job in valid_jobs_by_admin.values()]
    job_file_rows = (
        db.query(EmbeddingJobFile)
        .filter(EmbeddingJobFile.job_id.in_(valid_job_ids))
        .order_by(EmbeddingJobFile.file_id)
        .all()
        if valid_job_ids
        else []
    )
    files_by_job: dict[str, list[EmbeddingJobFile]] = {}
    for row in job_file_rows:
        files_by_job.setdefault(row.job_id, []).append(row)

    model_ids = {
        model_id
        for state in states
        for model_id in (
            state.active_embedding_model_id,
            state.target_embedding_model_id,
        )
        if model_id
    }
    model_rows = (
        db.query(EmbeddingModel).filter(EmbeddingModel.id.in_(sorted(model_ids))).all()
        if model_ids
        else []
    )
    model_by_id = {model.id: model for model in model_rows}

    active_admin_ids = (
        {
            row[0]
            for row in (
                db.query(EmbeddingJob.admin_id)
                .filter(
                    EmbeddingJob.admin_id.in_(admin_ids),
                    EmbeddingJob.status.in_((JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING)),
                )
                .distinct()
                .all()
            )
        }
        if admin_ids
        else set()
    )

    successful_rows = (
        db.query(EmbeddingJob.admin_id, func.max(EmbeddingJob.completed_at))
        .filter(
            EmbeddingJob.admin_id.in_(admin_ids),
            EmbeddingJob.status == JOB_STATUS_COMPLETED,
            EmbeddingJob.job_type.in_(_REINDEX_JOB_TYPES),
            EmbeddingJob.completed_at.isnot(None),
        )
        .group_by(EmbeddingJob.admin_id)
        .all()
        if admin_ids
        else []
    )
    last_success_by_admin = {
        admin_id: completed_at for admin_id, completed_at in successful_rows
    }

    responses = []
    for knowledge in knowledge_rows:
        resolution_error = resolution_errors.get(knowledge.id)
        if resolution_error is not None:
            responses.append(
                KnowledgeIndexingStatusResponse(
                    knowledge_id=knowledge.id,
                    display_state="unavailable",
                    retrieval_available=False,
                    error_code=resolution_error.code,
                    error_message="Indexing status is unavailable for this knowledge base.",
                )
            )
            continue

        admin_id = admin_by_knowledge[knowledge.id]
        state = state_by_admin.get(admin_id)
        job = valid_jobs_by_admin.get(admin_id)
        display_state, retrieval_available = _derive_display_state(state, job)
        active_model = (
            model_by_id.get(state.active_embedding_model_id) if state else None
        )
        target_model = (
            model_by_id.get(state.target_embedding_model_id)
            if state and state.target_embedding_model_id
            else None
        )
        models_available = state is None or (
            active_model is not None
            and active_model.status == "enabled"
            and (
                state.target_embedding_model_id is None
                or (target_model is not None and target_model.status == "enabled")
            )
        )
        if not models_available:
            display_state, retrieval_available = "unavailable", False
        rows = files_by_job.get(job.id, []) if job is not None else []
        collection_rows = _knowledge_rows_for_job(knowledge.id, rows)
        failed_rows = [
            row for row in collection_rows if row.status == FILE_STATUS_FAILED
        ]

        retry_eligible = False
        if job is not None and models_available:
            retry_eligible = is_job_retry_eligible(
                job,
                target_model_id=state.target_embedding_model_id if state else None,
                has_active_job=admin_id in active_admin_ids,
                has_failed_files=any(
                    row.status == FILE_STATUS_FAILED for row in rows
                ),
                all_files_pending=all(
                    row.status == FILE_STATUS_PENDING for row in rows
                ),
            )

        error_code = job.error_code if job is not None else None
        error_message = _job_error_message(error_code)
        if display_state in ("failed", "partial") and error_message is None:
            error_message = "The embedding indexing job did not finish successfully."
        if display_state == "unavailable" and error_message is None:
            error_code = error_code or "embedding_status_unavailable"
            error_message = "Indexing status is temporarily unavailable."

        responses.append(
            KnowledgeIndexingStatusResponse(
                knowledge_id=knowledge.id,
                display_state=display_state,
                job_status=job.status if job is not None else None,
                retrieval_available=retrieval_available,
                job_id=job.id if job is not None else None,
                job_type=job.job_type if job is not None else None,
                active_model=_model_summary(active_model),
                target_model=_model_summary(target_model),
                collection_progress=_progress_from_rows(collection_rows),
                job_progress=_job_progress(job),
                failed_document_count=len(failed_rows),
                job_failed_document_count=job.failed_files if job is not None else 0,
                error_code=error_code,
                error_message=error_message,
                retry_eligible=retry_eligible,
                can_retry=(
                    retry_eligible
                    and viewer_role == "admin"
                    and viewer_id == admin_id
                ),
                created_at=job.created_at if job is not None else None,
                updated_at=job.updated_at if job is not None else None,
                started_at=job.started_at if job is not None else None,
                completed_at=job.completed_at if job is not None else None,
                last_successful_indexed_at=last_success_by_admin.get(admin_id),
                failed_documents=(
                    [
                        KnowledgeIndexingFailure(
                            file_id=row.file_id,
                            error_code=row.error_code,
                            error_message=_stored_message(row.error_message),
                            attempt_count=row.attempt_count,
                            created_at=row.created_at,
                            updated_at=row.updated_at,
                            started_at=row.started_at,
                            completed_at=row.completed_at,
                        )
                        for row in failed_rows
                    ]
                    if include_failure_details
                    else []
                ),
            )
        )

    return responses
