"""Admin-scoped embedding model state: durable authority for model spaces.

The database row created here is the authoritative source for which embedding
model an admin may retrieve from (active) versus which model is currently being
built by a reindex operation (target). Model names remain presentation/config
compatibility data; only registry model IDs are stored, so credentials never
enter this table.

This module intentionally mirrors the transactional repository pattern used by
the embedding job repository (see Spec 03) and is consumed by the model-change
transaction (Spec 04), finalization (Spec 09), retrieval gate (Spec 10), and
status/retry API (Spec 11).

Cross-table atomicity
----------------------
Mutating methods (``request_target``, ``promote_target``, ``ensure_state``) accept
an optional caller-owned ``db`` session. When provided, they operate within that
session and only flush; the caller commits. This lets Spec 04/09 combine job
creation, model-state update, vector activation, and job completion in a single
transaction. When ``db`` is ``None`` the method owns and commits its own session.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError

from open_webui.internal.db import get_db
from open_webui.models.embeddings import AdminEmbeddingModelState
from open_webui.retrieval.embedding.compatibility import (
    assert_dimension_supported,
)
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_MODEL_STATE_CONFLICT,
)
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.resolution import (
    resolve_admin_for_admin_id,
    resolve_model_for_admin,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdminEmbeddingModelStateView:
    """Detached view of an admin's embedding model state.

    Contains only stable IDs; no credentials, model names, or provider details.
    """

    admin_id: str
    active_embedding_model_id: str
    target_embedding_model_id: Optional[str]
    latest_embedding_job_id: Optional[str]


def _now() -> int:
    return int(time.time())


def _to_view(row: AdminEmbeddingModelState) -> AdminEmbeddingModelStateView:
    return AdminEmbeddingModelStateView(
        admin_id=row.admin_id,
        active_embedding_model_id=row.active_embedding_model_id,
        target_embedding_model_id=row.target_embedding_model_id,
        latest_embedding_job_id=row.latest_embedding_job_id,
    )


def _get_row(db, admin_id: str) -> Optional[AdminEmbeddingModelState]:
    return (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin_id)
        .first()
    )


def _seed_row(db, admin_id: str, config, now: int) -> AdminEmbeddingModelState:
    """Create (but do not commit) a state row seeded from configured model name.

    Resolves the admin's configured model name to an enabled registry model ID.
    Raises on missing, disabled, or storage-unsupported models so no model is
    silently selected. Caller is responsible for flush/commit.
    """
    admin = resolve_admin_for_admin_id(admin_id)
    model = resolve_model_for_admin(admin.email, config)
    assert_dimension_supported(model.dimension)
    row = AdminEmbeddingModelState(
        admin_id=admin.id,
        active_embedding_model_id=model.id,
        target_embedding_model_id=None,
        latest_embedding_job_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row


def _ensure_state(db, admin_id: str, config) -> AdminEmbeddingModelStateView:
    """Seed the state row from config if absent (flush only; caller commits)."""
    resolve_admin_for_admin_id(admin_id)
    now = _now()
    row = (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin_id)
        .with_for_update()
        .first()
    )
    if row is not None:
        return _to_view(row)
    try:
        row = _seed_row(db, admin_id, config, now)
        db.flush()
    except IntegrityError:
        # A concurrent ensure_state won the race; reuse its committed row.
        db.rollback()
        existing = _get_row(db, admin_id)
        if existing is None:
            raise
        return _to_view(existing)
    return _to_view(row)


def _request_target(
    db, admin_id: str, target_model_id: str, job_id: str, config, *,
    replace_existing: bool = False,
) -> AdminEmbeddingModelStateView:
    """Set a target model for an in-flight reindex (flush only; caller commits).

    Validates the target registry model is enabled and storage-supported, seeds
    state from config if missing, and enforces the invariant that an admin cannot
    hold a pending target while another operation is requested. The active model
    is left unchanged.

    When *replace_existing* is True the caller has already validated that the
    existing target's job is terminal-failed and a different target is being
    requested, so the pending target may be overwritten.
    """
    admin = resolve_admin_for_admin_id(admin_id)
    target = get_model_spec_by_id(target_model_id)  # NOT_CONFIGURED / DISABLED
    assert_dimension_supported(target.dimension)

    now = _now()
    row = (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin.id)
        .with_for_update()
        .first()
    )
    if row is None:
        try:
            row = _seed_row(db, admin.id, config, now)
            db.flush()
        except IntegrityError:
            db.rollback()
            row = (
                db.query(AdminEmbeddingModelState)
                .filter_by(admin_id=admin.id)
                .with_for_update()
                .first()
            )
            if row is None:
                raise

    # Replay protection: no pending target may be silently overwritten
    # unless the caller explicitly opted in (replace_existing=True).
    if row.target_embedding_model_id is not None and not replace_existing:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=(
                f"Admin {admin.id} already has a pending target model "
                f"'{row.target_embedding_model_id}'; finalize or retry before "
                f"requesting another change."
            ),
        )

    row.target_embedding_model_id = target_model_id
    row.latest_embedding_job_id = job_id
    row.updated_at = now
    db.flush()
    return _to_view(row)


def _promote_target(
    db, admin_id: str, expected_job_id: str
) -> AdminEmbeddingModelStateView:
    """Atomically promote target to active and clear target (flush; caller commits).

    Verifies a target exists and that the latest job matches ``expected_job_id``
    (stale/duplicate finalizers cannot promote). The failure path never calls
    this, so a failed transition leaves the active model unchanged. Keeps
    ``latest_embedding_job_id`` pointing at the completed job.
    """
    admin = resolve_admin_for_admin_id(admin_id)
    now = _now()
    row = (
        db.query(AdminEmbeddingModelState)
        .filter_by(admin_id=admin.id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=f"No embedding model state for admin {admin.id}.",
        )
    if row.target_embedding_model_id is None:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=f"Admin {admin.id} has no target model to promote.",
        )
    if row.latest_embedding_job_id != expected_job_id:
        raise EmbeddingError(
            EMBEDDING_MODEL_STATE_CONFLICT,
            detail=(
                f"Latest job '{row.latest_embedding_job_id}' does not match "
                f"expected '{expected_job_id}'; refusing promotion."
            ),
        )
    row.active_embedding_model_id = row.target_embedding_model_id
    row.target_embedding_model_id = None
    row.updated_at = now
    db.flush()
    return _to_view(row)


class AdminEmbeddingModelStateRepository:
    """Transactional, admin-scoped embedding model state manager."""

    @staticmethod
    def ensure_state(
        admin_id: str, config, db=None
    ) -> AdminEmbeddingModelStateView:
        """Seed the state row from the admin's configured model if absent.

        Idempotent: returns the existing row when present. Raises on missing,
        disabled, or storage-unsupported configured models. When ``db`` is
        provided the caller owns the transaction (only flush); otherwise a
        session is opened and committed here.
        """
        if db is None:
            with get_db() as session:
                view = _ensure_state(session, admin_id, config)
                session.commit()
                return view
        return _ensure_state(db, admin_id, config)

    @staticmethod
    def get_state(
        admin_id: str, db=None
    ) -> Optional[AdminEmbeddingModelStateView]:
        """Return current state, or None when no row exists."""
        if db is None:
            with get_db() as session:
                row = _get_row(session, admin_id)
        else:
            row = _get_row(db, admin_id)
        return _to_view(row) if row else None

    @staticmethod
    def get_active_model_id(admin_id: str, db=None) -> Optional[str]:
        """Return the active (retrievable) model ID, or None."""
        state = AdminEmbeddingModelStateRepository.get_state(admin_id, db=db)
        return state.active_embedding_model_id if state else None

    @staticmethod
    def get_target_model_id(admin_id: str, db=None) -> Optional[str]:
        """Return the target (being built) model ID, or None."""
        state = AdminEmbeddingModelStateRepository.get_state(admin_id, db=db)
        return state.target_embedding_model_id if state else None

    @staticmethod
    def get_latest_job_id(admin_id: str, db=None) -> Optional[str]:
        """Return the latest model-change/retry job ID, or None."""
        state = AdminEmbeddingModelStateRepository.get_state(admin_id, db=db)
        return state.latest_embedding_job_id if state else None

    @staticmethod
    def request_target(
        admin_id: str,
        target_model_id: str,
        job_id: str,
        config,
        db=None,
        *,
        replace_existing: bool = False,
    ) -> AdminEmbeddingModelStateView:
        """Set a target model for an in-flight reindex without altering active.

        When ``db`` is provided the caller owns the transaction (only flush);
        otherwise a session is opened and committed here. Validates the target,
        seeds state if missing, and rejects a pending target so an in-flight or
        replayed operation cannot be silently overwritten.

        When *replace_existing* is True the caller has already validated that
        the existing target's job is terminal-failed and a different target is
        being requested, so the pending target may be overwritten.
        """
        if db is None:
            with get_db() as session:
                view = _request_target(
                    session, admin_id, target_model_id, job_id, config,
                    replace_existing=replace_existing,
                )
                session.commit()
                return view
        return _request_target(
            db, admin_id, target_model_id, job_id, config,
            replace_existing=replace_existing,
        )

    @staticmethod
    def promote_target(
        admin_id: str,
        expected_job_id: str,
        db=None,
    ) -> AdminEmbeddingModelStateView:
        """Atomically promote target to active and clear target.

        When ``db`` is provided the caller owns the transaction (only flush);
        otherwise a session is opened and committed here. The failure path never
        calls this, so a failed transition leaves the active model unchanged.
        """
        if db is None:
            with get_db() as session:
                view = _promote_target(session, admin_id, expected_job_id)
                session.commit()
                return view
        return _promote_target(db, admin_id, expected_job_id)

    @staticmethod
    def record_failure(
        admin_id: str, db=None
    ) -> Optional[AdminEmbeddingModelStateView]:
        """Failure handling: target and latest job remain visible; active unchanged.

        A failed transition must never promote the target. This method performs
        no mutation and simply returns the current view so callers can preserve
        the target and latest job for status/retry (Specs 09 and 11).
        """
        return AdminEmbeddingModelStateRepository.get_state(admin_id, db=db)
