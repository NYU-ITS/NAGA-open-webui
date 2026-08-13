"""Model-aware vector repository: dimension routing, provenance writes, filtered search.

Phase 3 of the multi-provider multimodal embedding plan. Routes an embedding
model's dimension to its approved physical pgvector table and centralizes the
provenance shape written alongside every vector.

The approved text-only and multimodal models both use 1536 dimensions, backed
by the renamed ``embeddings_1536`` table (formerly ``document_chunk``). Adding
a new dimension requires:

1. an Alembic migration creating the ``embeddings_<dim>`` table with the same
   provenance columns, and
2. an entry in :data:`DIMENSION_TABLE` plus a dimension-aware client selection
   in :meth:`ModelAwareVectorRepository._client_for`.

Writes carry ``(admin_id, embedding_model_id, file_id, knowledge_id,
rag_chunk_id, modality, embedding_status)`` and are never padded or truncated;
the embedding service validates the exact dimension upstream. Searches are
restricted to one admin/model provenance space so a query vector is never
compared with document vectors from another model.
"""

import logging
import uuid
from typing import Optional, Sequence

from open_webui.retrieval.embedding.inputs import EmbeddingModelSpec
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
)
from open_webui.retrieval.vector.main import SearchResult, VectorItem

log = logging.getLogger(__name__)

# Approved dimension -> physical table name. Add a row only after the matching
# Alembic migration has created the table.
DIMENSION_TABLE = {
    1536: "embeddings_1536",
}

# Non-retrievable vs retrievable build status carried on every model-aware row.
# Ordinary ingestion writes ``active`` immediately. Reindex target builds write
# ``building`` and only become ``active`` when Spec 09 promotes the job; search
# filters to ``active`` only, so a partially built target space is never
# retrievable.
VECTOR_STATUS_ACTIVE = "active"
VECTOR_STATUS_BUILDING = "building"


def supported_dimensions() -> list[int]:
    """Return the list of approved vector dimensions."""
    return list(DIMENSION_TABLE)


def assert_dimension_supported(dimension: int) -> str:
    """Return the physical table name for a dimension or raise.

    Raises:
        EmbeddingError: EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED if no approved
            table exists for the dimension.
    """
    table = DIMENSION_TABLE.get(dimension)
    if table is None:
        raise EmbeddingError(
            EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
            detail=f"No approved vector table for dimension {dimension}.",
        )
    return table


class ModelAwareVectorRepository:
    """Stores and searches vectors with full admin/model provenance.

    Storage is delegated to the active vector DB client (pgvector today). The
    repository owns the dimension->table routing decision and the provenance
    shape; the client owns the physical insert/search.
    """

    def __init__(self, vector_db_client=None):
        # Lazily resolve the global client so this module stays import-safe.
        self._default_client = vector_db_client

    def _client_for(self, dimension: int):
        """Select the vector client for a dimension.

        Today every approved dimension is served by the single pgvector client
        bound to ``embeddings_1536``. When a second dimension is added, route to
        a dimension-specific client/table here.
        """
        assert_dimension_supported(dimension)
        if self._default_client is not None:
            return self._default_client
        from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT

        return VECTOR_DB_CLIENT

    def make_items(
        self,
        *,
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        metadata: Sequence[dict],
        rag_chunk_ids: Sequence[str],
        admin_id: str,
        model: EmbeddingModelSpec,
        file_id: Optional[str],
        knowledge_id: Optional[str],
        modalities: Optional[Sequence[str]] = None,
        modality: str = "text",
        embedding_status: str = VECTOR_STATUS_ACTIVE,
        embedding_job_id: Optional[str] = None,
    ) -> list[VectorItem]:
        """Build provenance-bearing vector items aligned by index.

        The returned items keep the legacy ``metadata`` (vmetadata) contract and
        add the model-aware provenance keys read by the enriched pgvector
        insert. Fresh ids are assigned per item.

        ``embedding_status`` defaults to :data:`VECTOR_STATUS_ACTIVE` (ordinary
        ingestion). A reindex worker passes :data:`VECTOR_STATUS_BUILDING` plus
        its durable ``embedding_job_id`` so the partially built target space is
        non-retrievable (Spec 07 Build Visibility).

        Raises:
            EmbeddingError: if the model dimension is unsupported or the inputs
                do not align in length.
        """
        assert_dimension_supported(model.dimension)
        if modalities is None:
            modalities = [modality] * len(texts)
        if not (
            len(texts)
            == len(vectors)
            == len(metadata)
            == len(rag_chunk_ids)
            == len(modalities)
        ):
            raise EmbeddingError(
                EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
                detail=(
                    "texts, vectors, metadata, rag_chunk_ids, and modalities "
                    "must align in length."
                ),
            )

        items: list[VectorItem] = []
        for text, vector, meta, rag_chunk_id, item_modality in zip(
            texts, vectors, metadata, rag_chunk_ids, modalities
        ):
            if item_modality not in {"text", "image"}:
                raise EmbeddingError(EMBEDDING_MODALITY_UNSUPPORTED)
            items.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": text,
                    "vector": vector,
                    "metadata": {
                        **meta,
                        "rag_chunk_id": rag_chunk_id,
                        "modality": item_modality,
                    },
                    # Model-aware provenance (no credentials, no PII).
                    "admin_id": admin_id,
                    "embedding_model_id": model.id,
                    "file_id": file_id,
                    "knowledge_id": knowledge_id,
                    "rag_chunk_id": rag_chunk_id,
                    "modality": item_modality,
                    "embedding_status": embedding_status,
                    "embedding_job_id": embedding_job_id,
                }
            )
        return items

    def reconcile_model_aware(
        self,
        *,
        collection_name: str,
        items: Sequence[VectorItem],
        model: EmbeddingModelSpec,
    ) -> None:
        """Atomically reconcile one target file/collection projection.

        Delegates to the dimension's vector client, which in a single
        transaction upserts the current provenance-bearing rows keyed by
        ``(admin_id, embedding_model_id, rag_chunk_id, collection_name)`` and
        deletes stale rows for the same ``(admin_id, embedding_model_id,
        file_id, collection_name)`` projection whose ``rag_chunk_id`` is no
        longer current (Spec 07 Vector Identity). Rows for other models, files,
        and collections — including old active-model vectors — are never
        touched, and shared ``rag_chunks`` rows are never deleted here.
        """
        client = self._client_for(model.dimension)
        if not hasattr(client, "reconcile_model_aware"):
            raise EmbeddingError(
                EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
                detail=(
                    f"Vector client {type(client).__name__} does not support "
                    "model-aware reconcile."
                ),
            )
        client.reconcile_model_aware(
            collection_name=collection_name, items=list(items)
        )

    def reconcile_model_aware_many(
        self,
        *,
        projections: Sequence[tuple[str, Sequence[VectorItem]]],
        model: EmbeddingModelSpec,
        session=None,
    ) -> None:
        """Atomically reconcile all collection projections for a file."""
        collection_names = [name for name, _ in projections]
        if len(collection_names) != len(set(collection_names)):
            raise EmbeddingError(EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED)
        client = self._client_for(model.dimension)
        if not hasattr(client, "reconcile_model_aware_many"):
            raise EmbeddingError(
                EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
                detail=(
                    f"Vector client {type(client).__name__} does not support "
                    "multi-projection reconcile."
                ),
            )
        client.reconcile_model_aware_many(
            [(name, list(items)) for name, items in projections],
            session=session,
        )

    def activate_target_vectors(
        self,
        admin_id: str,
        model: EmbeddingModelSpec,
        session=None,
        job_ids: list[str] | None = None,
    ) -> int:
        """Promote target vectors from building to active (Spec 09).

        Returns the number of vectors promoted. Only vectors previously written
        with ``embedding_status="building"`` for this admin/model are affected.
        When *job_ids* is provided, activation is scoped to vectors written by
        those specific jobs (the job lineage) so stale vectors from unrelated
        abandoned operations are never promoted. ``session`` is forwarded to
        the vector client for cross-table atomicity.
        """
        client = self._client_for(model.dimension)
        if not hasattr(client, "bulk_update_embedding_status"):
            raise EmbeddingError(
                EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
                detail=(
                    f"Vector client {type(client).__name__} does not support "
                    "bulk status update."
                ),
            )
        return client.bulk_update_embedding_status(
            admin_id=admin_id,
            embedding_model_id=model.id,
            from_status=VECTOR_STATUS_BUILDING,
            to_status=VECTOR_STATUS_ACTIVE,
            session=session,
            job_ids=job_ids,
        )

    def deactivate_previous_model_vectors(
        self,
        admin_id: str,
        model: EmbeddingModelSpec,
        session=None,
    ) -> int:
        """Mark previous-model vectors inactive so they are excluded from search (Spec 09).

        Returns the number of vectors deactivated. Only vectors with
        ``embedding_status="active"`` for this admin/model are affected; vectors
        already building or inactive are untouched. ``session`` is forwarded to
        the vector client for cross-table atomicity.
        """
        client = self._client_for(model.dimension)
        if not hasattr(client, "bulk_update_embedding_status"):
            raise EmbeddingError(
                EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
                detail=(
                    f"Vector client {type(client).__name__} does not support "
                    "bulk status update."
                ),
            )
        return client.bulk_update_embedding_status(
            admin_id=admin_id,
            embedding_model_id=model.id,
            from_status=VECTOR_STATUS_ACTIVE,
            to_status="inactive",
            session=session,
        )

    def get_job_vector_manifest(
        self,
        *,
        admin_id: str,
        model: EmbeddingModelSpec,
        job_id: str,
        session=None,
    ) -> dict[tuple[str, str], tuple[str, ...]]:
        """Return exact building chunk identities for a durable reindex job."""
        client = self._client_for(model.dimension)
        if not hasattr(client, "get_job_vector_manifest"):
            raise EmbeddingError(EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED)
        return client.get_job_vector_manifest(
            admin_id=admin_id,
            embedding_model_id=model.id,
            job_id=job_id,
            session=session,
        )

    def search(
        self,
        *,
        collection_name: str,
        query_vectors: Sequence[Sequence[float]],
        admin_id: str,
        model: EmbeddingModelSpec,
        limit: Optional[int] = None,
        knowledge_ids: Optional[Sequence[str]] = None,
        file_ids: Optional[Sequence[str]] = None,
    ) -> Optional[SearchResult]:
        """Cosine search restricted to one admin/model provenance space.

        The collection name still scopes the existing RBAC boundary (``file-<id>``
        or a knowledge id); admin_id + embedding_model_id harden it so the
        result set cannot include vectors from another admin context or model.
        """
        client = self._client_for(model.dimension)
        return client.search_model_aware(
            collection_name=collection_name,
            vectors=list(query_vectors),
            admin_id=admin_id,
            embedding_model_id=model.id,
            limit=limit,
            knowledge_ids=list(knowledge_ids) if knowledge_ids else None,
            file_ids=list(file_ids) if file_ids else None,
        )


# Module-level singleton for convenience. Callers may also construct their own
# repository with an injected client.
repository = ModelAwareVectorRepository()
