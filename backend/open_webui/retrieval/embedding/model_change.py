"""Model-change transaction: atomically create reindex job for admin model change (Spec 04).

This module implements the transaction that turns one accepted admin model change
into exactly one durable reindex operation. It coordinates admin state validation,
target model resolution, duplicate guards, inventory building, and job creation
in a single atomic transaction.

Authorization precondition: Caller must authenticate requester and pass
authenticated_user_id matching admin_id. This function enforces the precondition
but does not perform HTTP authentication.

Transaction flow:
1.  Verify requester == admin_id
2.  Lock admin embedding-state row; resolve admin email
3.  Resolve target model by ID or name (within transaction)
4.  Validate enabled status and dimension support
5.  Pending-target guard: reject active jobs, require retry for same failed
    target, allow atomic replacement for a different failed target
6.  Reject if active job exists (when no pending target)
7.  Reject if target equals active model (unless retry needed); repair stale
    compatibility config on no-op
8.  Build deterministic inventory before mutation
9.  Create job + file rows atomically
10. Set target model and latest job ID (replace_existing if replacing)
11. Write RAG_EMBEDDING_MODEL_USER inside the transaction
12. Commit once
13. Reload job from DB
14. Return (result, admin_email); caller invalidates caches after commit
    Enqueue job (caller responsible via Spec 05)

Non-goals:
- Executing reindex work (Spec 05/06)
- Promoting target model (Spec 09)
- Frontend UI
"""

import logging
from dataclasses import dataclass
from typing import Optional

from open_webui.internal.db import get_db
from open_webui.models.users import Users
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_ACTIVE_EXISTS,
    EMBEDDING_MODEL_STATE_CONFLICT,
    EMBEDDING_MODEL_DISABLED,
    EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_ADMIN_UNRESOLVED,
)
from open_webui.retrieval.embedding.state import (
    AdminEmbeddingModelStateRepository,
)
from open_webui.retrieval.embedding.jobs import (
    EmbeddingJobRepository,
    JOB_STATUS_QUEUED,
    JOB_STATUS_PROCESSING,
)
from open_webui.retrieval.embedding.inventory import (
    build_reindex_inventory,
)
from open_webui.retrieval.embedding.registry import (
    get_model_spec_by_id,
    get_model_spec_by_name,
    EmbeddingModelSpec,
)
from open_webui.retrieval.embedding.compatibility import assert_dimension_supported

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelChangeResult:
    """Response contract for successful model-change acceptance.

    Contains job ID, status, model IDs, and file count. No claim of reindex
    completion is made here; that's handled by finalization (Spec 09).
    """

    job_id: str
    status: str
    active_model_id: str
    target_model_id: str
    total_files: int


@dataclass(frozen=True)
class ModelChangeNoOp:
    """Response for no-change cases where no job is created.

    Occurs when target equals active model and no retry is needed.
    """

    active_model_id: str
    target_model_id: str
    reason: str


def request_model_change(
    admin_id: str,
    target_model_id: str,
    authenticated_user_id: str,
    config=None,
) -> tuple[ModelChangeResult | ModelChangeNoOp, str]:
    """Execute the model-change transaction atomically.

    Authorization precondition: authenticated_user_id must equal admin_id.
    Caller must perform HTTP authentication before invoking this function.

    The admin's ``RAG_EMBEDDING_MODEL_USER`` compatibility config is written
    inside the same transaction so a validation or inventory failure rolls
    config back together with durable state.  The second element of the
    returned tuple is the admin's email, which the caller uses to invalidate
    caches *after* commit.

    Args:
        admin_id: Stable user ID of the admin whose model to change.
        target_model_id: Registry model ID or exact approved model name.
        authenticated_user_id: Authenticated requester's user ID (must == admin_id).
        config: Optional config for resolving admin/model if not in DB yet.

    Returns:
        ``(ModelChangeResult, admin_email)`` on success, or
        ``(ModelChangeNoOp, admin_email)`` if no change needed.

    Raises:
        EmbeddingError: On authorization failure, validation error, duplicate guard,
                       or inventory error.
    """
    # Step 1: Verify requester authorization
    if authenticated_user_id != admin_id:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"Requester {authenticated_user_id} is not authorized to change admin {admin_id}.",
        )

    # Step 2-14: Atomic transaction
    with get_db() as db:
        # Step 2: Ensure admin state exists and lock (creates if missing)
        state_view = AdminEmbeddingModelStateRepository.ensure_state(
            admin_id, config, db=db
        )

        # Resolve admin email once for config writes and return value.
        admin_user = Users.get_user_by_id(admin_id)
        if admin_user is None:
            raise EmbeddingError(
                EMBEDDING_ADMIN_UNRESOLVED,
                detail=f"Admin {admin_id} not found.",
            )
        admin_email = admin_user.email

        # Step 3-4: Resolve and validate target model (within transaction)
        target_spec = _resolve_target_model(target_model_id)

        # Step 5: Pending-target guard with failed-target replacement.
        replace_existing = False
        if state_view.target_embedding_model_id is not None:
            # An active (queued/processing) job always blocks — no replacement.
            active_job = EmbeddingJobRepository.get_active_job(admin_id, db=db)
            if active_job is not None:
                raise EmbeddingError(
                    EMBEDDING_JOB_ACTIVE_EXISTS,
                    detail=f"Admin {admin_id} has active job {active_job.id} in status {active_job.status}.",
                )

            # No active job — the latest job must be terminal.
            latest_job_id = state_view.latest_embedding_job_id
            latest_job = (
                EmbeddingJobRepository.get_job(latest_job_id, db=db)
                if latest_job_id
                else None
            )
            if latest_job is None or latest_job.status not in (
                "failed",
                "partially_failed",
            ):
                # Target is set but job is not terminal-failed (e.g. completed
                # but promotion hasn't run, or status is unknown).  Reject to
                # avoid silently overwriting an in-flight operation.
                raise EmbeddingError(
                    EMBEDDING_MODEL_STATE_CONFLICT,
                    detail=(
                        f"Admin {admin_id} has pending target "
                        f"{state_view.target_embedding_model_id} with job "
                        f"{latest_job_id} in status "
                        f"{latest_job.status if latest_job else 'missing'}; "
                        f"cannot replace."
                    ),
                )

            # Latest job is terminal-failed.
            if target_spec.id == state_view.target_embedding_model_id:
                # Same failed target — retry only, no new job.
                raise EmbeddingError(
                    EMBEDDING_MODEL_STATE_CONFLICT,
                    detail=(
                        f"Target model {target_spec.id} matches pending failed "
                        f"target. Use retry endpoint instead."
                    ),
                )

            # Different target — allow atomic replacement.
            replace_existing = True

        # Step 6: Check for active job (only when no pending target)
        if not replace_existing:
            active_job = EmbeddingJobRepository.get_active_job(admin_id, db=db)
            if active_job is not None:
                raise EmbeddingError(
                    EMBEDDING_JOB_ACTIVE_EXISTS,
                    detail=f"Admin {admin_id} has active job {active_job.id} in status {active_job.status}.",
                )

        # Step 7: Check if target equals active (no-change case)
        if target_spec.id == state_view.active_embedding_model_id:
            # Check if latest job failed and needs retry
            latest_job_id = state_view.latest_embedding_job_id
            if latest_job_id is not None:
                latest_job = EmbeddingJobRepository.get_job(latest_job_id, db=db)
                if latest_job is not None:
                    # If latest job failed/partially_failed to same target, require retry
                    if latest_job.embedding_model_id == target_spec.id:
                        if latest_job.status in ("failed", "partially_failed"):
                            raise EmbeddingError(
                                EMBEDDING_MODEL_STATE_CONFLICT,
                                detail=(
                                    f"Target model {target_spec.id} equals active model and "
                                    f"latest job {latest_job.id} failed. Use retry endpoint instead."
                                ),
                            )
            # No failed job to same target.  Repair stale compatibility
            # config if it doesn't match the active model, then return no-op.
            if config is not None:
                current_cfg = config.RAG_EMBEDDING_MODEL_USER.get(admin_email) or ""
                if current_cfg != target_spec.model_name:
                    config.RAG_EMBEDDING_MODEL_USER.set(
                        admin_email, target_spec.model_name, db=db
                    )
            return ModelChangeNoOp(
                active_model_id=state_view.active_embedding_model_id,
                target_model_id=target_spec.id,
                reason="Target equals active model; no reindex needed.",
            ), admin_email

        # Step 8: Build inventory before mutation (failures abort transaction)
        inventory = build_reindex_inventory(admin_id, db=db)

        # Step 9: Create job atomically
        job_result = EmbeddingJobRepository.create_job(
            admin_id=admin_id,
            embedding_model_id=target_spec.id,
            files=inventory,
            job_type="reindex_model_change",
            previous_embedding_model_id=state_view.active_embedding_model_id,
            created_by_user_id=authenticated_user_id,
            db=db,
        )

        # Step 10: Set target model and latest job ID
        state_view = AdminEmbeddingModelStateRepository.request_target(
            admin_id=admin_id,
            target_model_id=target_spec.id,
            job_id=job_result.job.id,
            config=config,
            db=db,
            replace_existing=replace_existing,
        )

        # Step 11: Write compatibility config inside the transaction so a
        # failure rolls config back together with durable state.
        if config is not None:
            config.RAG_EMBEDDING_MODEL_USER.set(
                admin_email, target_spec.model_name, db=db
            )

        # Step 12: Commit (happens automatically when exiting with block)
        db.commit()

        log.info(
            "[MODEL_CHANGE] created job %s for admin %s: target=%s, files=%d",
            job_result.job.id,
            admin_id,
            target_spec.id,
            len(inventory),
        )

        # Step 13: Reload job from DB to get authoritative state after commit
        committed_job = EmbeddingJobRepository.get_job(job_result.job.id, db=db)
        if committed_job is None:
            # Should not happen, but defensive
            raise EmbeddingError(
                EMBEDDING_JOB_NOT_FOUND,
                detail=f"Job {job_result.job.id} not found after commit.",
            )

        # Step 14: Return response contract from committed state
        return ModelChangeResult(
            job_id=committed_job.id,
            status=committed_job.status,
            active_model_id=state_view.active_embedding_model_id,
            target_model_id=target_spec.id,
            total_files=committed_job.total_files,
        ), admin_email


def _resolve_target_model(target_model_id: str) -> EmbeddingModelSpec:
    """Resolve target model by ID or name, validate enabled and dimension.

    Args:
        target_model_id: Registry model ID or exact approved model name.

    Returns:
        EmbeddingModelSpec for the target model.

    Raises:
        EmbeddingError: If model not found, disabled, or dimension unsupported.
                       Propagates EMBEDDING_MODEL_DISABLED from registry lookup.
    """
    # Try by ID first, only catch NOT_CONFIGURED to allow fallback to name
    try:
        spec = get_model_spec_by_id(target_model_id)
    except EmbeddingError as e:
        if e.code != EMBEDDING_MODEL_NOT_CONFIGURED:
            # Propagate disabled, unsupported, or other errors
            raise
        # Try by name only if ID lookup returned NOT_CONFIGURED
        try:
            spec = get_model_spec_by_name(target_model_id)
        except EmbeddingError:
            raise EmbeddingError(
                EMBEDDING_MODEL_NOT_CONFIGURED,
                detail=f"Target model '{target_model_id}' not found by ID or name.",
            )

    # Validate enabled status
    if spec.status != "enabled":
        raise EmbeddingError(
            EMBEDDING_MODEL_DISABLED,
            detail=f"Target model {spec.id} is not enabled (status={spec.status}).",
        )

    # Validate dimension support
    try:
        assert_dimension_supported(spec.dimension)
    except EmbeddingError:
        raise EmbeddingError(
            EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
            detail=f"Target model {spec.id} dimension {spec.dimension} not supported.",
        )

    return spec
