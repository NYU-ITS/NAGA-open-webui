"""Safe actionable errors at the chat retrieval boundary."""

from fastapi import HTTPException

from open_webui.retrieval.embedding.errors import EmbeddingError, KnowledgeUnavailableError


def evidence_error(status: int, code: str, message: str, *, retryable: bool):
    return HTTPException(
        status_code=status,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def retrieval_error(error: EmbeddingError) -> HTTPException:
    if isinstance(error, KnowledgeUnavailableError):
        response = evidence_error(
            409,
            error.code,
            "This knowledge base is no longer available. Remove it or select "
            "another knowledge base to continue. If it belongs to the selected "
            "model, choose another model or ask its owner to update it.",
            retryable=False,
        )
        response.detail["knowledge_id"] = error.knowledge_id
        return response
    if error.code in {
        "embedding_reindex_not_ready",
        "embedding_reindex_source_changed",
        "embedding_model_state_conflict",
        "embedding_model_space_mixed",
        "embedding_generation_changed",
        "embedding_source_unavailable",
        "embedding_file_not_found",
    }:
        return evidence_error(
            409,
            error.code,
            "The requested sources are not ready or their index has changed. "
            "Wait for indexing to finish, retry failed files, then send your message again.",
            retryable=True,
        )
    return evidence_error(
        503,
        "retrieval_unavailable",
        "The source retrieval service is unavailable. Please retry; if this continues, "
        "ask your administrator to check the embedding provider and index.",
        retryable=True,
    )


def safe_stream_error(error: Exception) -> dict:
    """Preserve known safe errors when HTTP headers have already been sent."""
    if isinstance(error, EmbeddingError):
        error = retrieval_error(error)
    if isinstance(error, HTTPException) and isinstance(error.detail, dict):
        detail = error.detail
        if (
            detail.get("error_code")
            in {
                "embedding_reindex_not_ready",
                "embedding_reindex_source_changed",
                "embedding_model_state_conflict",
                "embedding_model_space_mixed",
                "embedding_generation_changed",
                "embedding_source_unavailable",
                "embedding_file_not_found",
                "retrieval_unavailable",
                "reconstruction_timeout",
                "answer_model_evidence_unsupported",
                "requested_evidence_unavailable",
                "knowledge_unavailable",
            }
            and isinstance(detail.get("message"), str)
            and isinstance(detail.get("retryable"), bool)
        ):
            result = {key: detail[key] for key in ("error_code", "message", "retryable")}
            if detail["error_code"] == "knowledge_unavailable" and isinstance(
                detail.get("knowledge_id"), str
            ):
                result["knowledge_id"] = detail["knowledge_id"]
            return result
    return {
        "error_code": "chat_stream_failed",
        "message": "The response could not be completed. Please retry your message.",
        "retryable": True,
    }
