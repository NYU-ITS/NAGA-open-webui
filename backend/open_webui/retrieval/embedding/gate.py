"""Retrieval readiness gate (Spec 10).

Centralizes the decision of whether an admin's embedding model space is ready
for retrieval.  The gate runs before query embedding generation and before any
vector search. Queued, processing, and failed operations remain blocked. A
terminal partially-failed operation may expose only the completed files that
belong to the explicitly requested knowledge/file scope.

Required contract::

    assert_embedding_retrieval_ready(
        requesting_user_id: str,
        knowledge_ids: list[str] | None,
        file_ids: list[str] | None,
    ) -> RetrievalModelSpace

When no durable state row exists the admin is treated as a legacy admin whose
data was ingested before the durable state system.  The caller uses the
config-resolved model path for these admins (the legacy compatibility path).
Durable-state resolution errors always fail closed — never legacy-fallback.
"""

import logging
from dataclasses import dataclass, asdict

from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_MODEL_SPACE_MIXED,
    EMBEDDING_REINDEX_NOT_READY,
)
from open_webui.retrieval.embedding.jobs import (
    EmbeddingJobRepository,
    FILE_STATUS_COMPLETED,
    FILE_STATUS_INCOMPATIBLE,
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIALLY_FAILED,
)
from open_webui.retrieval.embedding.resolution import (
    assert_single_model_space,
)
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.state import (
    AdminEmbeddingModelStateRepository,
)

log = logging.getLogger(__name__)

# Every recognized job status.  A status not in this set is unknown and
# must fail closed.
_KNOWN_JOB_STATUSES = frozenset(
    {
        JOB_STATUS_QUEUED,
        JOB_STATUS_PROCESSING,
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_PARTIALLY_FAILED,
    }
)

# Non-terminal and fully failed jobs block every retrieval scope.
_BLOCKING_JOB_STATUSES = frozenset(
    {JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING, JOB_STATUS_FAILED}
)


@dataclass(frozen=True)
class RetrievalModelSpace:
    """Resolved model space and any safely scoped staged-vector allowance."""

    admin_id: str
    active_model_id: str
    staged_job_ids: tuple[str, ...] = ()
    staged_file_ids: tuple[str, ...] = ()
    staged_collection_files: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RetrievalReadyNoState:
    """Sentinel: admin has no durable state row; caller should use legacy path."""

    admin_id: str


@dataclass(frozen=True)
class _BlockedMetadata:
    """Structured metadata carried by EMBEDDING_REINDEX_NOT_READY errors."""

    job_id: str | None
    job_status: str | None
    retryable: bool


def assert_embedding_retrieval_ready(
    requesting_user_id: str,
    knowledge_ids: list[str] | None = None,
    file_ids: list[str] | None = None,
) -> RetrievalModelSpace | RetrievalReadyNoState:
    """Check whether an admin's embedding model space allows retrieval.

    The gate resolves the effective admin/model space, validates that all
    requested knowledge bases and files belong to the same space, then checks
    the durable admin state and latest embedding job:

    - **No durable state row** → ``RetrievalReadyNoState`` (legacy admin).
    - **Latest job completed** → ``RetrievalModelSpace`` with the active model.
    - **Latest job queued/processing/failed** → blocked.
    - **Latest job partially_failed** → completed files in the explicit request
      scope are allowed; any failed file in that scope blocks the request.
    - **Latest job missing or unknown status** → fail closed (blocked).
    - **Target present without completed promotion** → blocked.
    - **Active model missing** → blocked.
    - **Mixed knowledge spaces** → blocked.

    Returns:
        ``RetrievalModelSpace`` when retrieval is allowed, or
        ``RetrievalReadyNoState`` when no durable state exists.

    Raises:
        EmbeddingError (EMBEDDING_REINDEX_NOT_READY): when retrieval is
            blocked by an incomplete or failed reindex operation.  The
            error ``detail`` is a dict with ``job_id``, ``job_status``,
            and ``retryable`` fields (plus ``message``) so HTTP adapters
            can produce a 409 Conflict response with structured metadata.
        EmbeddingError (EMBEDDING_MODEL_SPACE_MIXED): when knowledge
            bases or files resolve to different model spaces.
    """
    # 1. Resolve effective admin/model space and validate knowledge read access.
    config = _get_app_config()
    admin_id, embedding_model_id = assert_single_model_space(
        requesting_user_id, knowledge_ids, config
    )

    # 2. Validate file ownership: every file must belong to the resolved admin.
    #    Resolution errors (missing file, unresolved owner, ambiguous admin)
    #    propagate as EmbeddingError — never treated as permission success.
    if file_ids:
        for fid in file_ids:
            owner_id = _resolve_file_owner(fid, requesting_user_id)
            if owner_id != admin_id:
                raise EmbeddingError(
                    EMBEDDING_MODEL_SPACE_MIXED,
                    detail=(
                        f"File {fid} belongs to admin {owner_id}, "
                        f"expected {admin_id}."
                    ),
                )

    # 3. Check durable admin state.
    state = AdminEmbeddingModelStateRepository.get_state(admin_id)

    if state is None:
        # No durable state: legacy admin, use config-resolved model path.
        return RetrievalReadyNoState(admin_id=admin_id)

    # 4. Latest job must exist and have a known status. A terminal partial job
    # may expose only completed files from the explicitly requested scope.
    latest_job_id = state.latest_embedding_job_id
    staged_job_ids: tuple[str, ...] = ()
    staged_file_ids: tuple[str, ...] = ()
    staged_collection_files: tuple[tuple[str, str], ...] = ()
    partial_scope_ready = False

    if latest_job_id is not None:
        latest_job = EmbeddingJobRepository.get_job(latest_job_id)

        if latest_job is None:
            # Job referenced but not found: fail closed.
            _raise_blocked(
                job_id=latest_job_id,
                job_status="missing",
                retryable=False,
                message=(
                    f"Retrieval blocked: latest embedding job {latest_job_id} "
                    f"not found."
                ),
            )

        if latest_job.status not in _KNOWN_JOB_STATUSES:
            # Unknown status: fail closed.
            _raise_blocked(
                job_id=latest_job_id,
                job_status=latest_job.status,
                retryable=False,
                message=(
                    f"Retrieval blocked: latest embedding job {latest_job_id} "
                    f"has unknown status '{latest_job.status}'."
                ),
            )

        if latest_job.status == JOB_STATUS_PARTIALLY_FAILED:
            if (
                latest_job.admin_id != admin_id
                or latest_job.embedding_model_id != embedding_model_id
                or latest_job.embedding_model_id
                not in {
                    state.active_embedding_model_id,
                    state.target_embedding_model_id,
                }
            ):
                _raise_blocked(
                    job_id=latest_job_id,
                    job_status=latest_job.status,
                    retryable=False,
                    message=(
                        "Retrieval blocked: partial embedding job does not "
                        "match the selected model state."
                    ),
                )
            approved_file_ids, approved_collection_files = (
                _completed_files_for_partial_scope(
                    latest_job_id,
                    knowledge_ids=knowledge_ids,
                    file_ids=file_ids,
                )
            )
            staged_job_ids = (latest_job_id,)
            staged_file_ids = tuple(sorted(approved_file_ids))
            staged_collection_files = tuple(sorted(approved_collection_files))
            partial_scope_ready = True
        elif latest_job.status in _BLOCKING_JOB_STATUSES:
            _raise_blocked(
                job_id=latest_job_id,
                job_status=latest_job.status,
                retryable=latest_job.status == JOB_STATUS_FAILED,
                message=(
                    f"Retrieval blocked: latest embedding job {latest_job_id} is "
                    f"{latest_job.status}."
                ),
            )

        if latest_job.status == JOB_STATUS_COMPLETED:
            if (
                latest_job.admin_id != admin_id
                or latest_job.embedding_model_id
                != state.active_embedding_model_id
            ):
                _raise_blocked(
                    job_id=latest_job_id,
                    job_status=latest_job.status,
                    retryable=False,
                    message=(
                        "Retrieval blocked: completed embedding job does not "
                        "match active model state."
                    ),
                )

    # 5. A target normally remains blocked until complete promotion. The only
    # exception is the source-scoped terminal-partial allowance above.
    if state.target_embedding_model_id is not None and not partial_scope_ready:
        _raise_blocked(
            job_id=latest_job_id,
            job_status=None,
            retryable=False,
            message=(
                f"Admin {admin_id} has pending target model "
                f"'{state.target_embedding_model_id}' that has not been promoted."
            ),
        )

    # 6. Active model must exist.
    active_model_id = state.active_embedding_model_id
    if not active_model_id:
        _raise_blocked(
            job_id=latest_job_id,
            job_status=None,
            retryable=False,
            message=f"Admin {admin_id} has no active embedding model.",
        )
    try:
        active_model = get_model_spec_by_id(active_model_id)
    except EmbeddingError:
        _raise_blocked(
            job_id=latest_job_id,
            job_status=None,
            retryable=False,
            message="Retrieval blocked: active embedding model is unavailable.",
        )
    if active_model.status != "enabled":
        _raise_blocked(
            job_id=latest_job_id,
            job_status=None,
            retryable=False,
            message="Retrieval blocked: active embedding model is disabled.",
        )

    return RetrievalModelSpace(
        admin_id=admin_id,
        active_model_id=active_model_id,
        staged_job_ids=staged_job_ids,
        staged_file_ids=staged_file_ids,
        staged_collection_files=staged_collection_files,
    )


def _completed_files_for_partial_scope(
    job_id: str,
    *,
    knowledge_ids: list[str] | None,
    file_ids: list[str] | None,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Return completed job files that are safe for the requested scope.

    A knowledge request is blocked only when one of its current, snapshotted
    files failed in the partial job. Files added after the frozen job inventory
    continue to use their ordinary active-vector path. No unscoped partial-job
    retrieval is allowed.
    """
    from open_webui.models.knowledge import Knowledges

    requested_knowledge_ids = {
        str(knowledge_id) for knowledge_id in (knowledge_ids or []) if knowledge_id
    }
    requested_file_ids = {str(file_id) for file_id in (file_ids or []) if file_id}
    if not requested_knowledge_ids and not requested_file_ids:
        _raise_blocked(
            job_id=job_id,
            job_status=JOB_STATUS_PARTIALLY_FAILED,
            retryable=True,
            message="Retrieval blocked: a partial embedding job requires an explicit source scope.",
        )

    rows_by_file_id = {
        row.file_id: row for row in EmbeddingJobRepository.list_files(job_id)
    }
    approved_file_ids = set()
    approved_collection_files = set()

    for file_id in requested_file_ids:
        row = rows_by_file_id.get(file_id)
        if row is None:
            continue
        if row.status not in (FILE_STATUS_COMPLETED, FILE_STATUS_INCOMPATIBLE):
            _raise_partial_source_blocked(job_id)
        if row.status == FILE_STATUS_COMPLETED:
            if not _staged_projection_is_current(row, f"file-{file_id}"):
                _raise_partial_source_blocked(job_id)
            approved_file_ids.add(file_id)
            approved_collection_files.add((f"file-{file_id}", file_id))

    for knowledge_id in requested_knowledge_ids:
        knowledge = Knowledges.get_knowledge_by_id(knowledge_id)
        data = (
            knowledge.data
            if knowledge is not None and isinstance(knowledge.data, dict)
            else {}
        )
        current_file_ids = {
            str(file_id)
            for file_id in data.get("file_ids", [])
            if isinstance(file_id, str) and file_id
        }
        for file_id in current_file_ids:
            row = rows_by_file_id.get(file_id)
            if row is None:
                continue
            snapshot = row.file_snapshot if isinstance(row.file_snapshot, dict) else {}
            snapshot_knowledge_ids = snapshot.get("knowledge_collection_ids", [])
            if (
                not isinstance(snapshot_knowledge_ids, list)
                or knowledge_id not in snapshot_knowledge_ids
            ):
                continue
            if row.status not in (FILE_STATUS_COMPLETED, FILE_STATUS_INCOMPATIBLE):
                _raise_partial_source_blocked(job_id)
            if row.status == FILE_STATUS_COMPLETED:
                if not _staged_projection_is_current(row, knowledge_id):
                    _raise_partial_source_blocked(job_id)
                approved_file_ids.add(file_id)
                approved_collection_files.add((knowledge_id, file_id))

    return approved_file_ids, approved_collection_files


def _staged_projection_is_current(row, collection_id: str) -> bool:
    """Validate the frozen source and exact staged collection projection."""
    from open_webui.models.files import Files

    source_file = Files.get_file_by_id(row.file_id)
    snapshot = row.file_snapshot if isinstance(row.file_snapshot, dict) else {}
    summary = snapshot.get("prepared_processing_summary")
    projection_ids = (
        summary.get("projection_ids", []) if isinstance(summary, dict) else []
    )
    if (
        source_file is None
        or not isinstance(projection_ids, list)
        or collection_id not in projection_ids
        or source_file.hash != snapshot.get("content_hash")
    ):
        return False
    expected_updated_at = snapshot.get("updated_at")
    return expected_updated_at is None or source_file.updated_at == expected_updated_at


def _raise_partial_source_blocked(job_id: str) -> None:
    _raise_blocked(
        job_id=job_id,
        job_status=JOB_STATUS_PARTIALLY_FAILED,
        retryable=True,
        message=(
            "Retrieval blocked: the requested source did not complete the "
            "partial embedding job."
        ),
    )


def _raise_blocked(
    *,
    job_id: str | None,
    job_status: str | None,
    retryable: bool,
    message: str,
) -> None:
    """Raise an EMBEDDING_REINDEX_NOT_READY error with structured metadata."""
    detail = {
        "message": message,
        "job_id": job_id,
        "job_status": job_status,
        "retryable": retryable,
    }
    raise EmbeddingError(EMBEDDING_REINDEX_NOT_READY, detail=detail)


def _resolve_file_owner(file_id: str, requesting_user_id: str) -> str:
    """Authorize a file read and resolve its governing admin.

    Returns the admin user ID on success.

    Raises:
        EmbeddingError (EMBEDDING_FILE_NOT_FOUND): file does not exist or
            DB lookup failed.
        EmbeddingError (EMBEDDING_INVENTORY_UNRESOLVED_SOURCE): file exists
            but has no recorded owner (user_id is NULL).
        EmbeddingError (EMBEDDING_ADMIN_UNRESOLVED / EMBEDDING_ADMIN_AMBIGUOUS):
            owner user exists but admin resolution failed.  Propagated from
            ``resolve_admin_for_user``.
    """
    from open_webui.models.files import Files
    from open_webui.models.knowledge import Knowledges
    from open_webui.models.users import Users
    from open_webui.retrieval.embedding.resolution import resolve_admin_for_user

    try:
        file_obj = Files.get_file_by_id(file_id)
    except Exception as e:
        raise EmbeddingError(
            EMBEDDING_FILE_NOT_FOUND,
            detail=f"Failed to look up file {file_id}: {type(e).__name__}",
        ) from e

    if file_obj is None:
        raise EmbeddingError(
            EMBEDDING_FILE_NOT_FOUND,
            detail=f"File {file_id} not found.",
        )

    requesting_user = Users.get_user_by_id(requesting_user_id)
    if requesting_user is None or not (
        requesting_user.role == "admin"
        or file_obj.user_id == requesting_user_id
        or Knowledges.user_has_read_access_to_file(requesting_user_id, file_id)
    ):
        raise EmbeddingError(
            EMBEDDING_FILE_NOT_FOUND,
            detail=f"File {file_id} not found.",
        )

    if file_obj.user_id is None:
        raise EmbeddingError(
            EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
            detail=f"File {file_id} has no recorded owner.",
        )

    # Propagates EMBEDDING_ADMIN_UNRESOLVED / EMBEDDING_ADMIN_AMBIGUOUS
    admin = resolve_admin_for_user(file_obj.user_id)
    return admin.id


def _get_app_config():
    """Retrieve the app config from the request state (best-effort)."""
    try:
        from open_webui.main import app
        return app.state.config
    except Exception:
        return None
