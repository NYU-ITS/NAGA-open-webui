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
from open_webui.models.files import File
from open_webui.models.knowledge import Knowledge
from open_webui.retrieval.embedding.errors import EmbeddingError
from open_webui.retrieval.embedding.inventory import build_reindex_admin_resolver
from open_webui.retrieval.embedding.jobs import (
    FILE_STATUS_COMPLETED,
    FILE_STATUS_FAILED,
    FILE_STATUS_INCOMPATIBLE,
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
    incompatible: int = 0
    pending_or_processing: int = 0


class EmbeddingModelSummary(BaseModel):
    id: str
    provider: str
    display_name: str
    modalities: list[str] = Field(default_factory=list)
    status: str


class KnowledgeIndexingKnowledgeReference(BaseModel):
    id: str
    name: str


class KnowledgeIndexingFileIssue(BaseModel):
    file_id: str
    filename: str | None = None
    source_contexts: list[str] = Field(default_factory=list)
    knowledge_bases: list[KnowledgeIndexingKnowledgeReference] = Field(
        default_factory=list
    )
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    created_at: int | None = None
    updated_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None


class KnowledgeIndexingIncompatible(KnowledgeIndexingFileIssue):
    pass


class KnowledgeIndexingFailure(KnowledgeIndexingFileIssue):
    pass


class KnowledgeIndexingStatusSummary(BaseModel):
    knowledge_id: str
    display_state: KnowledgeIndexingDisplayState
    job_status: str | None = None
    retrieval_available: bool
    current_file_count: int = 0
    job_display_state: KnowledgeIndexingDisplayState = "ready"
    retry_kind: str | None = None

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
    job_failed_documents: list[KnowledgeIndexingFailure] = Field(
        default_factory=list
    )
    incompatible_document_count: int = 0
    job_incompatible_document_count: int = 0
    job_incompatible_documents: list[KnowledgeIndexingIncompatible] = Field(
        default_factory=list
    )

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
    incompatible_documents: list[KnowledgeIndexingIncompatible] = Field(
        default_factory=list
    )


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
    incompatible = sum(row.status == FILE_STATUS_INCOMPATIBLE for row in rows)
    total = len(rows)
    return KnowledgeIndexingProgress(
        total=total,
        processed=processed,
        failed=failed,
        incompatible=incompatible,
        pending_or_processing=max(0, total - processed - failed - incompatible),
    )


def _job_progress(job: EmbeddingJob | None) -> KnowledgeIndexingProgress:
    if job is None:
        return KnowledgeIndexingProgress()
    return KnowledgeIndexingProgress(
        total=job.total_files,
        processed=job.processed_files,
        failed=job.failed_files,
        incompatible=job.incompatible_files,
        pending_or_processing=max(
            0,
            job.total_files
            - job.processed_files
            - job.failed_files
            - job.incompatible_files,
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


def _file_issue_context(
    row: EmbeddingJobFile,
    *,
    filenames_by_id: dict[str, str],
    knowledge_names_by_id: dict[str, str],
) -> dict:
    """Build safe, user-facing source context for one job file."""
    snapshot = row.file_snapshot if isinstance(row.file_snapshot, dict) else {}
    source_contexts = snapshot.get("source_contexts", [])
    if not isinstance(source_contexts, list):
        source_contexts = []
    knowledge_ids = snapshot.get("knowledge_collection_ids", [])
    if not isinstance(knowledge_ids, list):
        knowledge_ids = []

    return {
        "file_id": row.file_id,
        "filename": filenames_by_id.get(row.file_id),
        "source_contexts": sorted(
            {str(context) for context in source_contexts if context}
        ),
        "knowledge_bases": [
            KnowledgeIndexingKnowledgeReference(
                id=str(knowledge_id),
                name=knowledge_names_by_id.get(
                    str(knowledge_id), "Deleted knowledge base"
                ),
            )
            for knowledge_id in knowledge_ids
            if knowledge_id
        ],
    }


def _failure_detail(
    row: EmbeddingJobFile,
    *,
    filenames_by_id: dict[str, str],
    knowledge_names_by_id: dict[str, str],
) -> KnowledgeIndexingFailure:
    return KnowledgeIndexingFailure(
        **_file_issue_context(
            row,
            filenames_by_id=filenames_by_id,
            knowledge_names_by_id=knowledge_names_by_id,
        ),
        error_code=row.error_code,
        error_message=_stored_message(row.error_message),
        attempt_count=row.attempt_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _incompatible_detail(
    row: EmbeddingJobFile,
    *,
    filenames_by_id: dict[str, str],
    knowledge_names_by_id: dict[str, str],
) -> KnowledgeIndexingIncompatible:
    return KnowledgeIndexingIncompatible(
        **_file_issue_context(
            row,
            filenames_by_id=filenames_by_id,
            knowledge_names_by_id=knowledge_names_by_id,
        ),
        error_code=row.error_code,
        error_message=_stored_message(row.error_message),
        attempt_count=row.attempt_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _snapshot_knowledge_ids(rows: list[EmbeddingJobFile]) -> list[str]:
    knowledge_ids = set()
    for row in rows:
        snapshot = row.file_snapshot if isinstance(row.file_snapshot, dict) else {}
        snapshot_ids = snapshot.get("knowledge_collection_ids", [])
        if not isinstance(snapshot_ids, list):
            continue
        knowledge_ids.update(
            str(knowledge_id) for knowledge_id in snapshot_ids if knowledge_id
        )
    return sorted(knowledge_ids)


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

    job_file_ids = sorted({row.file_id for row in job_file_rows})
    file_name_rows = (
        db.query(File.id, File.filename).filter(File.id.in_(job_file_ids)).all()
        if job_file_ids
        else []
    )
    filenames_by_id = {
        str(file_id): str(filename)
        for file_id, filename in file_name_rows
        if filename
    }
    snapshot_knowledge_ids = _snapshot_knowledge_ids(job_file_rows)
    knowledge_name_rows = (
        db.query(Knowledge.id, Knowledge.name)
        .filter(Knowledge.id.in_(snapshot_knowledge_ids))
        .all()
        if snapshot_knowledge_ids
        else []
    )
    knowledge_names_by_id = {
        str(knowledge_id): str(name)
        for knowledge_id, name in knowledge_name_rows
        if name
    }

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
        knowledge_data = knowledge.data if isinstance(knowledge.data, dict) else {}
        current_file_ids = {
            str(file_id)
            for file_id in knowledge_data.get("file_ids", [])
            if isinstance(file_id, str)
        }
        current_file_count = len(current_file_ids)
        state = state_by_admin.get(admin_id)
        job = valid_jobs_by_admin.get(admin_id)
        job_display_state, _ = _derive_display_state(state, job)
        display_state, retrieval_available = job_display_state, job_display_state == "ready"
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
        collection_rows = [row for row in collection_rows if row.file_id in current_file_ids]
        # Coverage is scoped to files the latest job was responsible for.
        # Files added after the job are indexed by the direct upload path
        # (no durable job) and must not flip the KB to unavailable.
        job_expected_file_ids = {row.file_id for row in rows} & current_file_ids
        if (
            job is not None
            and job_expected_file_ids
            and len({row.file_id for row in collection_rows}) < len(job_expected_file_ids)
        ):
            display_state, retrieval_available = "unavailable", False
        failed_rows = [
            row for row in collection_rows if row.status == FILE_STATUS_FAILED
        ]
        incompatible_rows = [
            row
            for row in collection_rows
            if row.status == FILE_STATUS_INCOMPATIBLE
        ]
        job_failed_rows = [
            row for row in rows if row.status == FILE_STATUS_FAILED
        ]
        job_incompatible_rows = [
            row for row in rows if row.status == FILE_STATUS_INCOMPATIBLE
        ]

        # A terminal partial job is source-scoped for retrieval. Knowledge
        # bases whose own frozen files did not fail remain ready; the overview
        # keeps the administrator-wide partial badge and failed-file details.
        if (
            display_state == "partial"
            and current_file_count > 0
            and not failed_rows
        ):
            display_state, retrieval_available = "ready", True

        # An empty collection is locally ready even when another governed
        # source has a failed administrator-wide operation.
        if current_file_count == 0:
            display_state, retrieval_available = "ready", True
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
        if current_file_count == 0:
            retry_eligible = False

        error_code = job.error_code if job is not None else None
        error_message = _job_error_message(error_code)
        if current_file_count == 0:
            error_code = error_message = None
        if job_display_state in ("failed", "partial") and error_message is None:
            error_message = "The embedding indexing job did not finish successfully."
        if (
            display_state == "unavailable"
            and job_display_state not in ("failed", "partial")
            and error_message is None
        ):
            error_code = error_code or "embedding_status_unavailable"
            error_message = "Indexing status is temporarily unavailable."

        responses.append(
            KnowledgeIndexingStatusResponse(
                knowledge_id=knowledge.id,
                display_state=display_state,
                current_file_count=current_file_count,
                job_display_state=job_display_state,
                job_status=job.status if job is not None else None,
                retrieval_available=retrieval_available,
                job_id=job.id if job is not None else None,
                job_type=job.job_type if job is not None else None,
                active_model=_model_summary(active_model),
                target_model=_model_summary(target_model),
                collection_progress=_progress_from_rows(collection_rows),
                job_progress=_job_progress(job),
                failed_document_count=len(failed_rows),
                job_failed_document_count=(job.failed_files if job is not None else 0),
                job_failed_documents=(
                    [
                        _failure_detail(
                            row,
                            filenames_by_id=filenames_by_id,
                            knowledge_names_by_id=knowledge_names_by_id,
                        )
                        for row in job_failed_rows
                    ]
                    if viewer_role == "admin" and viewer_id == admin_id
                    else []
                ),
                incompatible_document_count=len(incompatible_rows),
                job_incompatible_document_count=(
                    job.incompatible_files if job is not None else 0
                ),
                job_incompatible_documents=(
                    [
                        _incompatible_detail(
                            row,
                            filenames_by_id=filenames_by_id,
                            knowledge_names_by_id=knowledge_names_by_id,
                        )
                        for row in job_incompatible_rows
                    ]
                    if viewer_role == "admin" and viewer_id == admin_id
                    else []
                ),
                error_code=error_code,
                error_message=error_message,
                retry_eligible=retry_eligible,
                can_retry=(
                    retry_eligible
                    and viewer_role == "admin"
                    and viewer_id == admin_id
                ),
                retry_kind=(
                    "failed_documents"
                    if job_failed_rows
                    else (
                        "indexing_operation"
                        if display_state in ("failed", "partial", "unavailable")
                        and current_file_count
                        else None
                    )
                ),
                created_at=job.created_at if job is not None else None,
                updated_at=job.updated_at if job is not None else None,
                started_at=job.started_at if job is not None else None,
                completed_at=job.completed_at if job is not None else None,
                last_successful_indexed_at=last_success_by_admin.get(admin_id),
                failed_documents=(
                    [
                        _failure_detail(
                            row,
                            filenames_by_id=filenames_by_id,
                            knowledge_names_by_id=knowledge_names_by_id,
                        )
                        for row in failed_rows
                    ]
                    if include_failure_details
                    else []
                ),
                incompatible_documents=(
                    [
                        _incompatible_detail(
                            row,
                            filenames_by_id=filenames_by_id,
                            knowledge_names_by_id=knowledge_names_by_id,
                        )
                        for row in incompatible_rows
                    ]
                    if include_failure_details
                    else []
                ),
            )
        )

    return responses
