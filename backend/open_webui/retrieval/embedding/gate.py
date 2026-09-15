"""Authorize retrieval against individually published files in one generation."""

from dataclasses import dataclass

from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_MODEL_SPACE_MIXED,
    EMBEDDING_REINDEX_NOT_READY,
)
from open_webui.retrieval.embedding.resolution import assert_single_model_space
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.state import AdminEmbeddingModelStateRepository


@dataclass(frozen=True)
class RetrievalModelSpace:
    admin_id: str
    active_model_id: str | None
    effective_model_id: str
    index_generation_id: str | None = None
    ready_file_ids: tuple[str, ...] = ()
    excluded_file_ids: tuple[str, ...] = ()
    partial_availability: bool = False
    # Additive compatibility; unpublished vectors are never queryable.
    staged_job_ids: tuple[str, ...] = ()
    staged_file_ids: tuple[str, ...] = ()
    staged_collection_files: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RetrievalReadyNoState:
    admin_id: str


def file_publication_is_current(file, state, collection_id: str | None = None) -> bool:
    """Check publication without treating cache/heartbeat edits as source edits."""
    if file is None:
        return False
    meta = file.meta if isinstance(file.meta, dict) else {}
    data = file.data if isinstance(file.data, dict) else {}
    generation = state.index_generation_id
    baseline = generation == f"baseline:{state.admin_id}"
    if (
        state.target_embedding_model_id is not None
        or not state.active_embedding_model_id
    ):
        return False
    if meta.get("index_generation_id") != generation:
        if not baseline or meta.get("index_generation_id"):
            return False
    if meta.get("embedding_model_id") != state.active_embedding_model_id:
        if not baseline or meta.get("embedding_model_id"):
            return False
    if meta.get("processing_status", data.get("status")) != "completed":
        return False
    if not baseline and (
        not meta.get("chunk_manifest_id")
        or not meta.get("source_sha256")
        or not meta.get("preparation_recipe_sha256")
        or meta.get("published_content_origin", "stored_source")
        != meta.get("content_origin", "stored_source")
        or meta.get("published_content_override_sha256")
        != meta.get("content_override_sha256")
    ):
        return False
    projections = meta.get("published_projection_ids")
    if collection_id and (
        not isinstance(projections, list) or collection_id not in projections
    ):
        if not baseline:
            return False
    return True


def assert_embedding_retrieval_ready(
    requesting_user_id: str,
    knowledge_ids: list[str] | None = None,
    file_ids: list[str] | None = None,
) -> RetrievalModelSpace | RetrievalReadyNoState:
    from open_webui.models.files import Files
    from open_webui.models.knowledge import Knowledges

    admin_id, _selected_model_id = assert_single_model_space(
        requesting_user_id, knowledge_ids, _get_app_config()
    )
    for file_id in file_ids or []:
        if _resolve_file_owner(file_id, requesting_user_id) != admin_id:
            raise EmbeddingError(EMBEDDING_MODEL_SPACE_MIXED)

    state = AdminEmbeddingModelStateRepository.get_state(admin_id)
    if state is None:
        return RetrievalReadyNoState(admin_id=admin_id)
    if state.target_embedding_model_id or not state.active_embedding_model_id:
        _raise_blocked(
            state,
            "The selected index has no published files yet. Wait for indexing or retry failed files.",
        )
    model = get_model_spec_by_id(state.active_embedding_model_id)
    if model.status != "enabled":
        _raise_blocked(
            state,
            "The active embedding model is unavailable. Contact your administrator.",
        )

    projections: dict[str, set[str]] = {}
    for file_id in file_ids or []:
        projections.setdefault(file_id, set()).add(f"file-{file_id}")
    for knowledge_id in knowledge_ids or []:
        knowledge = Knowledges.get_knowledge_by_id(knowledge_id)
        data = (
            knowledge.data
            if knowledge is not None and isinstance(knowledge.data, dict)
            else {}
        )
        for file_id in data.get("file_ids", []):
            if isinstance(file_id, str) and file_id:
                projections.setdefault(file_id, set()).add(knowledge_id)

    ready = set()
    excluded = set()
    for file_id, collection_ids in projections.items():
        file = Files.get_file_by_id(file_id)
        publication_checks = [
            file_publication_is_current(file, state, collection_id)
            for collection_id in collection_ids
        ]
        if any(publication_checks):
            ready.add(file_id)
        if not all(publication_checks):
            excluded.add(file_id)
    if (knowledge_ids or file_ids) and not ready:
        _raise_blocked(
            state,
            "None of the requested files are ready. Wait for indexing or retry the failed files.",
            excluded_file_ids=sorted(excluded),
        )

    result = RetrievalModelSpace(
        admin_id=admin_id,
        active_model_id=state.active_embedding_model_id,
        effective_model_id=state.active_embedding_model_id,
        index_generation_id=state.index_generation_id,
        ready_file_ids=tuple(sorted(ready)),
        excluded_file_ids=tuple(sorted(excluded)),
        partial_availability=bool(excluded),
    )
    assert_retrieval_generation_current(result)
    return result


def assert_retrieval_generation_current(space: RetrievalModelSpace | None) -> None:
    """Reject a request if model selection/rebuild changed after its gate check."""
    if space is None:
        return
    state = AdminEmbeddingModelStateRepository.get_state(space.admin_id)
    if (
        state is None
        or state.index_generation_id != space.index_generation_id
        or state.active_embedding_model_id != space.effective_model_id
        or state.target_embedding_model_id is not None
    ):
        raise EmbeddingError(
            EMBEDDING_REINDEX_NOT_READY,
            detail={
                "error_code": EMBEDDING_REINDEX_NOT_READY,
                "message": "The index changed during retrieval. Please retry your request.",
                "retryable": True,
            },
        )


def _raise_blocked(state, message: str, **metadata) -> None:
    raise EmbeddingError(
        EMBEDDING_REINDEX_NOT_READY,
        detail={
            "error_code": EMBEDDING_REINDEX_NOT_READY,
            "message": message,
            "job_id": state.latest_embedding_job_id,
            "retryable": True,
            **metadata,
        },
    )


def _resolve_file_owner(file_id: str, requesting_user_id: str) -> str:
    from open_webui.models.files import Files
    from open_webui.models.knowledge import Knowledges
    from open_webui.models.users import Users
    from open_webui.retrieval.embedding.resolution import resolve_admin_for_user

    file = Files.get_file_by_id(file_id)
    requester = Users.get_user_by_id(requesting_user_id)
    if (
        file is None
        or requester is None
        or not (
            requester.role == "admin"
            or file.user_id == requesting_user_id
            or Knowledges.user_has_read_access_to_file(requesting_user_id, file_id)
        )
    ):
        raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
    if file.user_id is None:
        raise EmbeddingError(EMBEDDING_INVENTORY_UNRESOLVED_SOURCE)
    return resolve_admin_for_user(file.user_id).id


def _get_app_config():
    try:
        from open_webui.main import app
        return app.state.config
    except Exception:
        return None
