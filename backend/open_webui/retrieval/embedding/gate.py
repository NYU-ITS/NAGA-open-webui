"""Retrieval readiness gate (Spec 10).

Centralizes the decision of whether an admin's embedding model space is ready
for retrieval.  The gate runs before query embedding generation and before any
vector search so blocked states (queued, processing, failed, partially_failed)
never produce search results from a stale or incomplete model space.

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
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIALLY_FAILED,
)
from open_webui.retrieval.embedding.resolution import (
    assert_single_model_space,
)
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

# Job statuses that block retrieval.  Only ``completed`` restores retrieval.
_BLOCKING_JOB_STATUSES = frozenset(
    {JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING, JOB_STATUS_FAILED, JOB_STATUS_PARTIALLY_FAILED}
)


@dataclass(frozen=True)
class RetrievalModelSpace:
    """Resolved admin and active model for a retrieval request."""

    admin_id: str
    active_model_id: str


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
    - **Latest job queued/processing/failed/partially_failed** → blocked.
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
    from open_webui.internal.db import get_db
    from open_webui.models.files import Files

    # 1. Resolve effective admin/model space and validate knowledge ownership.
    config = _get_app_config()
    admin_id, embedding_model_id = assert_single_model_space(
        requesting_user_id, knowledge_ids, config
    )

    # 2. Validate file ownership: every file must belong to the resolved admin.
    #    Resolution errors (missing file, unresolved owner, ambiguous admin)
    #    propagate as EmbeddingError — never treated as permission success.
    if file_ids:
        for fid in file_ids:
            owner_id = _resolve_file_owner(fid)
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

    # 4. Latest job must exist, be known, and be completed.
    latest_job_id = state.latest_embedding_job_id

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

        if latest_job.status in _BLOCKING_JOB_STATUSES:
            _raise_blocked(
                job_id=latest_job_id,
                job_status=latest_job.status,
                retryable=latest_job.status in (JOB_STATUS_FAILED, JOB_STATUS_PARTIALLY_FAILED),
                message=(
                    f"Retrieval blocked: latest embedding job {latest_job_id} is "
                    f"{latest_job.status}."
                ),
            )

    # 5. Target present without a matching completed promotion: blocked.
    if state.target_embedding_model_id is not None:
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

    return RetrievalModelSpace(
        admin_id=admin_id,
        active_model_id=active_model_id,
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


def _resolve_file_owner(file_id: str) -> str:
    """Resolve the admin owner of a file.

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
