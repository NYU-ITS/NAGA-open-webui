"""Credential-free reindex status projections for Workspace Knowledge."""

import logging
from typing import Literal
from types import SimpleNamespace

from pydantic import BaseModel, Field
from open_webui.internal.db import get_db

from open_webui.models.embeddings import (
    AdminEmbeddingModelState,
    EmbeddingJob,
    EmbeddingJobFile,
    EmbeddingModel,
)
from open_webui.models.files import File
from open_webui.models.knowledge import Knowledge
from open_webui.models.chats import Chat
from open_webui.retrieval.embedding.gate import file_publication_is_current
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
    retry_file_count: int = 0
    index_generation_id: str | None = None
    availability: str = "unavailable"
    selected_model: EmbeddingModelSummary | None = None

    job_id: str | None = None
    job_type: str | None = None
    active_model: EmbeddingModelSummary | None = None
    target_model: EmbeddingModelSummary | None = None
    effective_model: EmbeddingModelSummary | None = None
    model_scope: Literal["active", "staged", "legacy", "unavailable"] = "unavailable"

    collection_progress: KnowledgeIndexingProgress = Field(
        default_factory=KnowledgeIndexingProgress
    )
    job_progress: KnowledgeIndexingProgress = Field(
        default_factory=KnowledgeIndexingProgress
    )
    generation_progress: KnowledgeIndexingProgress = Field(
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


def _generation_snapshot(db, state, resolver):
    """Latest attempt outcomes plus current published uploads, without re-preparing sources."""
    from open_webui.retrieval.embedding.inventory import (
        _iter_chat_refs,
        _iter_knowledge_refs,
    )

    # Polling must not load every document's extracted text into API memory.
    all_files = {
        row.id: SimpleNamespace(
            id=row.id,
            filename=row.filename,
            meta=row.meta,
            data={"status": row.legacy_status},
        )
        for row in db.query(
            File.id,
            File.filename,
            File.meta,
            File.data["status"].as_string().label("legacy_status"),
        ).all()
    }
    memberships: dict[str, set[str]] = {}
    for knowledge in db.query(Knowledge).all():
        try:
            if resolver.resolve_knowledge(knowledge) == state.admin_id:
                for file_id in _iter_knowledge_refs(knowledge):
                    memberships.setdefault(file_id, set()).add(knowledge.id)
        except EmbeddingError:
            continue
    for chat in db.query(Chat).all():
        try:
            if resolver.resolve_chat(chat) == state.admin_id:
                for file_id in _iter_chat_refs(chat):
                    memberships.setdefault(file_id, set()).add(f"file-{file_id}")
        except EmbeddingError:
            continue

    # Follow explicit ancestry: timestamps can collide when retries are created rapidly.
    outcomes = {}
    cursor = state.latest_embedding_job_id
    visited = set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        job = db.query(EmbeddingJob).filter(EmbeddingJob.id == cursor).first()
        if (
            job is None
            or job.admin_id != state.admin_id
            or job.index_generation_id != state.index_generation_id
        ):
            break
        for row in (
            db.query(EmbeddingJobFile).filter(EmbeddingJobFile.job_id == cursor).all()
        ):
            if row.file_id in all_files and row.file_id in memberships:
                outcomes.setdefault(row.file_id, row)
        cursor = job.source_job_id

    published = {
        file_id
        for file_id, file in all_files.items()
        if (file.meta or {}).get("index_generation_id") == state.index_generation_id
        and file_publication_is_current(file, state)
    }
    candidate_ids = (set(outcomes) | set(memberships) | published) & all_files.keys()
    statuses = {}
    for file_id in candidate_ids:
        file = all_files[file_id]
        if file_publication_is_current(file, state) and (
            file_id in published or file_id in memberships
        ):
            statuses[file_id] = FILE_STATUS_COMPLETED
        elif file_id in outcomes:
            row_status = outcomes[file_id].status
            statuses[file_id] = (
                FILE_STATUS_FAILED
                if row_status == FILE_STATUS_COMPLETED
                else row_status
            )
        else:
            statuses[file_id] = FILE_STATUS_PENDING
    return outcomes, all_files, statuses


def _coverage(statuses: dict[str, str]) -> KnowledgeIndexingProgress:
    processed = sum(value == FILE_STATUS_COMPLETED for value in statuses.values())
    failed = sum(value == FILE_STATUS_FAILED for value in statuses.values())
    incompatible = sum(value == FILE_STATUS_INCOMPATIBLE for value in statuses.values())
    return KnowledgeIndexingProgress(
        total=len(statuses),
        processed=processed,
        failed=failed,
        incompatible=incompatible,
        pending_or_processing=len(statuses) - processed - failed - incompatible,
    )


def get_generation_coverage(admin_id: str, db=None) -> dict:
    """A read-only projection shared by admin job status and knowledge status."""
    if db is None:
        with get_db() as session:
            return get_generation_coverage(admin_id, db=session)
    state = (
        db.query(AdminEmbeddingModelState)
        .filter(AdminEmbeddingModelState.admin_id == admin_id)
        .first()
    )
    if state is None:
        return KnowledgeIndexingProgress().model_dump()
    _outcomes, _files, statuses = _generation_snapshot(
        db, state, build_reindex_admin_resolver(db)
    )
    return _coverage(statuses).model_dump()


def get_generation_retry_files(admin_id: str, db=None) -> list:
    if db is None:
        with get_db() as session:
            return get_generation_retry_files(admin_id, db=session)
    state = (
        db.query(AdminEmbeddingModelState)
        .filter(AdminEmbeddingModelState.admin_id == admin_id)
        .first()
    )
    if state is None:
        return []
    outcomes, _files, statuses = _generation_snapshot(
        db, state, build_reindex_admin_resolver(db)
    )
    return [
        row
        for file_id, row in outcomes.items()
        if row.status == FILE_STATUS_FAILED
        and statuses.get(file_id) == FILE_STATUS_FAILED
    ]


def build_knowledge_indexing_statuses(
    db,
    knowledge_rows: list[Knowledge],
    *,
    viewer_id: str,
    viewer_role: str,
    include_failure_details: bool,
) -> list[KnowledgeIndexingStatusResponse]:
    """Project attempt progress separately from publication coverage."""
    resolver = build_reindex_admin_resolver(db)
    admin_snapshots = {}
    models = {model.id: model for model in db.query(EmbeddingModel).all()}
    knowledge_names = {
        knowledge.id: knowledge.name for knowledge in db.query(Knowledge).all()
    }
    responses = []
    for knowledge in knowledge_rows:
        try:
            admin_id = resolver.resolve_knowledge(knowledge)
        except EmbeddingError as error:
            responses.append(
                KnowledgeIndexingStatusResponse(
                    knowledge_id=knowledge.id,
                    display_state="unavailable",
                    retrieval_available=False,
                    error_code=error.code,
                    error_message="Indexing status is unavailable for this knowledge base.",
                )
            )
            continue

        if admin_id not in admin_snapshots:
            state = (
                db.query(AdminEmbeddingModelState)
                .filter(AdminEmbeddingModelState.admin_id == admin_id)
                .first()
            )
            job = (
                db.query(EmbeddingJob)
                .filter(EmbeddingJob.id == state.latest_embedding_job_id)
                .first()
                if state and state.latest_embedding_job_id
                else None
            )
            if job and job.admin_id != admin_id:
                job = None
            outcomes, files, statuses = (
                _generation_snapshot(db, state, resolver) if state else ({}, {}, {})
            )
            has_active = (
                db.query(EmbeddingJob.id)
                .filter(
                    EmbeddingJob.admin_id == admin_id,
                    EmbeddingJob.status.in_((JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING)),
                )
                .first()
                is not None
            )
            admin_snapshots[admin_id] = (
                state,
                job,
                outcomes,
                files,
                statuses,
                has_active,
            )
        state, job, outcomes, files, statuses, has_active = admin_snapshots[admin_id]
        current_ids = {
            file_id
            for file_id in (knowledge.data or {}).get("file_ids", [])
            if isinstance(file_id, str) and file_id
        }
        active_model = models.get(state.active_embedding_model_id) if state else None
        target_model = models.get(state.target_embedding_model_id) if state else None
        selected_model = target_model or active_model
        model_available = bool(
            state is None
            or (
                active_model
                and active_model.status == "enabled"
                and state.target_embedding_model_id is None
            )
        )
        local_statuses = {
            file_id: (
                FILE_STATUS_COMPLETED
                if state is None
                or (
                    model_available
                    and file_publication_is_current(
                        files.get(file_id), state, knowledge.id
                    )
                )
                else statuses.get(file_id, FILE_STATUS_PENDING)
            )
            for file_id in current_ids
        }
        # A completed ledger row alone does not publish a new collection projection.
        for file_id in local_statuses:
            if (
                state
                and local_statuses[file_id] == FILE_STATUS_COMPLETED
                and not (
                    model_available
                    and file_publication_is_current(
                        files.get(file_id), state, knowledge.id
                    )
                )
            ):
                local_statuses[file_id] = FILE_STATUS_PENDING
        progress = _coverage(local_statuses)
        generation_progress = _coverage(statuses)
        retrieval_available = (
            bool(progress.processed and model_available) or not current_ids
        )
        if (
            not current_ids
            or progress.processed == len(current_ids)
            and model_available
        ):
            display_state = "ready"
        elif retrieval_available:
            display_state = "partial"
        elif job and job.status == JOB_STATUS_QUEUED:
            display_state = "queued"
        elif job and job.status == JOB_STATUS_PROCESSING:
            display_state = "indexing"
        elif progress.failed:
            display_state = "failed"
        else:
            display_state = "unavailable"
        job_display_state, _unused = _derive_display_state(state, job)
        failures = [
            row
            for file_id, row in outcomes.items()
            if row.status == FILE_STATUS_FAILED
            and statuses.get(file_id) == FILE_STATUS_FAILED
        ]
        incompatible = [
            row
            for file_id, row in outcomes.items()
            if statuses.get(file_id) == FILE_STATUS_INCOMPATIBLE
        ]
        attempt_rows = (
            db.query(EmbeddingJobFile).filter(EmbeddingJobFile.job_id == job.id).all()
            if job
            else []
        )
        dispatch_only = bool(attempt_rows) and all(
            row.status == FILE_STATUS_PENDING for row in attempt_rows
        )
        retry_eligible = bool(
            job
            and state
            and job.index_generation_id == state.index_generation_id
            and selected_model
            and selected_model.status == "enabled"
            and is_job_retry_eligible(
                job,
                target_model_id=selected_model.id,
                has_active_job=has_active,
                has_failed_files=bool(failures),
                all_files_pending=dispatch_only,
            )
        )
        can_manage = viewer_role == "admin" and viewer_id == admin_id
        filenames = {file_id: file.filename for file_id, file in files.items()}
        local_failures = [row for row in failures if row.file_id in current_ids]
        local_incompatible = [row for row in incompatible if row.file_id in current_ids]
        failure_kwargs = dict(
            filenames_by_id=filenames, knowledge_names_by_id=knowledge_names
        )
        publication_times = [
            int((files[file_id].meta or {}).get("processing_completed_at") or 0)
            for file_id, value in statuses.items()
            if value == FILE_STATUS_COMPLETED
        ]
        responses.append(
            KnowledgeIndexingStatusResponse(
                knowledge_id=knowledge.id,
                display_state=display_state,
                job_display_state=job_display_state,
                job_status=job.status if job else None,
                retrieval_available=retrieval_available,
                availability=(
                    "partial"
                    if retrieval_available and progress.processed < len(current_ids)
                    else "ready" if retrieval_available else "unavailable"
                ),
                current_file_count=len(current_ids),
                job_id=job.id if job else None,
                job_type=job.job_type if job else None,
                index_generation_id=state.index_generation_id if state else None,
                active_model=_model_summary(active_model),
                target_model=_model_summary(target_model),
                selected_model=_model_summary(selected_model),
                effective_model=(
                    _model_summary(active_model) if retrieval_available else None
                ),
                model_scope=(
                    "legacy"
                    if state is None
                    else "active" if retrieval_available else "unavailable"
                ),
                collection_progress=progress,
                job_progress=_job_progress(job),
                generation_progress=generation_progress,
                failed_document_count=len(local_failures),
                job_failed_document_count=len(failures),
                job_failed_documents=(
                    [_failure_detail(row, **failure_kwargs) for row in failures]
                    if can_manage
                    else []
                ),
                incompatible_document_count=len(local_incompatible),
                job_incompatible_document_count=len(incompatible),
                job_incompatible_documents=(
                    [
                        _incompatible_detail(row, **failure_kwargs)
                        for row in incompatible
                    ]
                    if can_manage
                    else []
                ),
                failed_documents=(
                    [_failure_detail(row, **failure_kwargs) for row in local_failures]
                    if include_failure_details
                    else []
                ),
                incompatible_documents=(
                    [
                        _incompatible_detail(row, **failure_kwargs)
                        for row in local_incompatible
                    ]
                    if include_failure_details
                    else []
                ),
                error_code=job.error_code if job and current_ids else None,
                error_message=(
                    _job_error_message(job.error_code) if job and current_ids else None
                ),
                retry_eligible=retry_eligible,
                can_retry=retry_eligible and can_manage,
                retry_kind=(
                    "indexing_operation"
                    if dispatch_only
                    else "failed_documents" if failures else None
                ),
                retry_file_count=len(attempt_rows) if dispatch_only else len(failures),
                created_at=job.created_at if job else None,
                updated_at=job.updated_at if job else None,
                started_at=job.started_at if job else None,
                completed_at=job.completed_at if job else None,
                last_successful_indexed_at=max(publication_times, default=0) or None,
            )
        )
    return responses
