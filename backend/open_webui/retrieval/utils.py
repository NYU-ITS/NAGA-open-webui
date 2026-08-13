import logging
import os
import uuid
from typing import Optional, Union, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import asyncio
import requests
import hashlib
import math
from dataclasses import dataclass

from huggingface_hub import snapshot_download
from langchain.retrievers import ContextualCompressionRetriever, EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

try:
    from portkey_ai import Portkey
    PORTKEY_SDK_AVAILABLE = True
except ImportError:
    PORTKEY_SDK_AVAILABLE = False

log = logging.getLogger(__name__)


from open_webui.config import VECTOR_DB, RAG_EMBEDDING_MODEL
from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT
from open_webui.utils.misc import get_last_user_message, calculate_sha256_string

from open_webui.models.users import UserModel
from open_webui.models.files import Files

from open_webui.env import (
    SRC_LOG_LEVELS,
    OFFLINE_MODE,
    ENABLE_FORWARD_USER_INFO_HEADERS,
)

log.setLevel(SRC_LOG_LEVELS["RAG"])

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever


@dataclass(frozen=True)
class AuthorizedAttachmentScope:
    """Canonical, server-authorized file/knowledge retrieval scope."""

    file_ids: frozenset[str]
    knowledge_ids: frozenset[str]


@dataclass(frozen=True)
class RetrievalResult:
    """Retrieved sources plus the canonical scope used to obtain them."""

    sources: list[dict]
    authorized_scope: AuthorizedAttachmentScope


class VectorSearchRetriever(BaseRetriever):
    collection_name: Any
    embedding_function: Any
    top_k: int
    admin_id: Any = None
    embedding_model_id: Any = None
    knowledge_ids: Optional[list[str]] = None
    file_ids: Optional[list[str]] = None
    allow_unscoped_legacy: bool = False

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if self.admin_id and self.embedding_model_id and hasattr(
            VECTOR_DB_CLIENT, "search_model_aware"
        ):
            result = VECTOR_DB_CLIENT.search_model_aware(
                collection_name=self.collection_name,
                vectors=[self.embedding_function(query)],
                admin_id=self.admin_id,
                embedding_model_id=self.embedding_model_id,
                limit=self.top_k,
                knowledge_ids=self.knowledge_ids,
                file_ids=self.file_ids,
            )
        else:
            result = VECTOR_DB_CLIENT.search(
                collection_name=self.collection_name,
                vectors=[self.embedding_function(query)],
                limit=self.top_k,
            )

        if result is None:
            return []

        ids = result.ids[0]
        metadatas = result.metadatas[0]
        documents = result.documents[0]

        results = []
        for idx in range(len(ids)):
            metadata = metadatas[idx] or {}
            page_content = documents[idx] or ""
            has_scope = bool(self.knowledge_ids or self.file_ids)
            authorized = (
                _metadata_matches_scope(
                    metadata,
                    knowledge_ids=self.knowledge_ids,
                    file_ids=self.file_ids,
                )
                if has_scope
                else self.allow_unscoped_legacy
            )
            if metadata.get("modality") == "image" or not page_content.strip():
                continue
            if not authorized:
                continue
            results.append(
                Document(
                    metadata=metadata,
                    page_content=page_content,
                )
            )
        return results


def query_doc(
    collection_name: str,
    query_embedding: list[float],
    k: int,
    user: UserModel = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
    allow_unscoped_legacy: bool = False,
):
    log.info(
        "[VECTOR_SEARCH] query_doc START | k=%s | model_aware=%s | embedding_len=%s",
        k,
        bool(admin_id and embedding_model_id),
        len(query_embedding) if query_embedding else 0,
    )
    try:
        if admin_id and embedding_model_id and hasattr(
            VECTOR_DB_CLIENT, "search_model_aware"
        ):
            # Phase 3: restrict the result set to one admin/model provenance space.
            result = VECTOR_DB_CLIENT.search_model_aware(
                collection_name=collection_name,
                vectors=[query_embedding],
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                limit=k,
                knowledge_ids=knowledge_ids,
                file_ids=file_ids,
            )
        else:
            result = VECTOR_DB_CLIENT.search(
                collection_name=collection_name,
                vectors=[query_embedding],
                limit=k,
            )
        result = _filter_search_result_to_scope(
            result,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
            allow_unscoped_legacy=allow_unscoped_legacy,
        )

        if result:
            num_results = len(result.ids[0]) if result.ids and result.ids[0] else 0
            log.info(
                "[VECTOR_SEARCH] query_doc SUCCESS | results_count=%s",
                num_results,
            )
        else:
            log.info("[VECTOR_SEARCH] query_doc EMPTY | no results")

        return result
    except Exception as error:
        log.exception(
            "[VECTOR_SEARCH] query_doc ERROR | k=%s | error_type=%s",
            k,
            type(error).__name__,
        )
        raise


def get_doc(collection_name: str, user: UserModel = None):
    log.info("[VECTOR_GET] get_doc START")
    try:
        result = VECTOR_DB_CLIENT.get(collection_name=collection_name)

        if result:
            num_docs = len(result.ids[0]) if result.ids and result.ids[0] else 0
            log.info("[VECTOR_GET] get_doc SUCCESS | docs_count=%s", num_docs)
        else:
            log.info("[VECTOR_GET] get_doc EMPTY | no documents")

        return result
    except Exception as error:
        log.exception(
            "[VECTOR_GET] get_doc ERROR | error_type=%s", type(error).__name__
        )
        raise


def query_doc_with_hybrid_search(
    collection_name: str,
    query: str,
    embedding_function,
    k: int,
    reranking_function,
    r: float,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
    allow_unscoped_legacy: bool = False,
) -> dict:
    if _is_multimodal_model_space(admin_id, embedding_model_id):
        result = query_doc(
            collection_name=collection_name,
            query_embedding=embedding_function(query),
            k=k,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
            allow_unscoped_legacy=allow_unscoped_legacy,
        )
        if result is None:
            return {
                "distances": [[]],
                "documents": [[]],
                "metadatas": [[]],
            }
        return result.model_dump()

    try:
        # Model-aware get: only active rows for the resolved admin/model space.
        if admin_id and embedding_model_id and hasattr(
            VECTOR_DB_CLIENT, "get_model_aware"
        ):
            result = VECTOR_DB_CLIENT.get_model_aware(
                collection_name=collection_name,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
            )
        else:
            result = VECTOR_DB_CLIENT.get(collection_name=collection_name)

        if result is None or not result.documents or not result.documents[0]:
            return {
                "distances": [[]],
                "documents": [[]],
                "metadatas": [[]],
            }

        text_rows = [
            (document, metadata or {})
            for document, metadata in zip(
                result.documents[0], result.metadatas[0]
            )
            if isinstance(document, str)
            and document.strip()
            and (metadata or {}).get("modality", "text") == "text"
            and (
                _metadata_matches_scope(
                    metadata or {}, knowledge_ids=knowledge_ids, file_ids=file_ids
                )
                if (knowledge_ids or file_ids)
                else allow_unscoped_legacy
            )
        ]
        if not text_rows:
            return {
                "distances": [[]],
                "documents": [[]],
                "metadatas": [[]],
            }

        bm25_retriever = BM25Retriever.from_texts(
            texts=[row[0] for row in text_rows],
            metadatas=[row[1] for row in text_rows],
        )
        bm25_retriever.k = k

        vector_search_retriever = VectorSearchRetriever(
            collection_name=collection_name,
            embedding_function=embedding_function,
            top_k=k,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
            allow_unscoped_legacy=allow_unscoped_legacy,
        )

        ensemble_retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_search_retriever], weights=[0.5, 0.5]
        )
        compressor = RerankCompressor(
            embedding_function=embedding_function,
            top_n=k,
            reranking_function=reranking_function,
            r_score=r,
        )

        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=ensemble_retriever
        )

        result = compression_retriever.invoke(query)
        result = {
            "distances": [[d.metadata.get("score") for d in result]],
            "documents": [[d.page_content for d in result]],
            "metadatas": [[d.metadata for d in result]],
        }

        result_count = len(result["documents"][0]) if result["documents"] else 0
        log.info(
            "query_doc_with_hybrid_search complete | results_count=%s",
            result_count,
        )
        return result
    except Exception:
        raise


def _is_multimodal_model_space(
    admin_id: Optional[str], embedding_model_id: Optional[str]
) -> bool:
    if not admin_id or not embedding_model_id:
        return False
    from open_webui.retrieval.embedding.registry import get_model_spec_by_id

    return "image" in get_model_spec_by_id(embedding_model_id).modalities


def merge_get_results(get_results: list[dict]) -> dict:
    # Initialize lists to store combined data
    combined_documents = []
    combined_metadatas = []
    combined_ids = []

    for data in get_results:
        combined_documents.extend(data["documents"][0])
        combined_metadatas.extend(data["metadatas"][0])
        combined_ids.extend(data["ids"][0])

    # Create the output dictionary
    result = {
        "documents": [combined_documents],
        "metadatas": [combined_metadatas],
        "ids": [combined_ids],
    }

    return result


def merge_and_sort_query_results(
    query_results: list[dict], k: int, reverse: bool = False
) -> dict:
    best_by_identity: dict[tuple[str, str], tuple[object, str, dict]] = {}

    for data in query_results:
        distances = data["distances"][0]
        documents = data["documents"][0]
        metadatas = data["metadatas"][0]

        for distance, document, metadata in zip(distances, documents, metadatas):
            metadata = metadata or {}
            visual_id = metadata.get("visual_asset_id")
            rag_chunk_id = metadata.get("rag_chunk_id")
            if visual_id:
                identity = ("visual", str(visual_id))
            elif rag_chunk_id:
                identity = ("chunk", str(rag_chunk_id))
            elif metadata.get("file_id") is not None and metadata.get(
                "chunk_index"
            ) is not None:
                identity = (
                    "file_chunk",
                    f'{metadata.get("file_id")}:{metadata.get("chunk_index")}',
                )
            elif isinstance(document, str):
                identity = (
                    "text",
                    hashlib.sha256(document.encode("utf-8")).hexdigest(),
                )
            else:
                continue

            candidate = (
                distance,
                document if isinstance(document, str) else "",
                metadata,
            )
            current = best_by_identity.get(identity)
            if current is None or _query_result_sort_key(
                candidate, reverse=reverse
            ) < _query_result_sort_key(current, reverse=reverse):
                best_by_identity[identity] = candidate

    combined = sorted(
        best_by_identity.values(),
        key=lambda row: _query_result_sort_key(row, reverse=reverse),
    )

    # Slice to keep only the top k elements
    sorted_distances, sorted_documents, sorted_metadatas = (
        zip(*combined[: max(0, int(k))]) if combined else ([], [], [])
    )

    # Create and return the output dictionary
    return {
        "distances": [list(sorted_distances)],
        "documents": [list(sorted_documents)],
        "metadatas": [list(sorted_metadatas)],
    }


def _query_result_sort_key(
    row: tuple[object, str, dict], *, reverse: bool
) -> tuple:
    distance, document, metadata = row
    numeric_distance = _finite_float(distance)
    distance_key = (
        math.inf
        if numeric_distance is None
        else (-numeric_distance if reverse else numeric_distance)
    )
    return (
        numeric_distance is None,
        distance_key,
        str(metadata.get("file_id") or ""),
        _sortable_number(metadata.get("chunk_index")),
        _sortable_number(metadata.get("page_index")),
        _sortable_number(metadata.get("source_sequence")),
        str(metadata.get("knowledge_id") or ""),
        str(metadata.get("visual_asset_id") or metadata.get("rag_chunk_id") or ""),
        hashlib.sha256(document.encode("utf-8")).hexdigest(),
    )


def _finite_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sortable_number(value) -> tuple[int, int | str]:
    if isinstance(value, bool):
        return (1, "")
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value or ""))


def _metadata_matches_scope(
    metadata: dict,
    *,
    knowledge_ids: Optional[list[str]],
    file_ids: Optional[list[str]],
) -> bool:
    knowledge_scope = {str(value) for value in knowledge_ids or []}
    file_scope = {str(value) for value in file_ids or []}
    if not knowledge_scope and not file_scope:
        return True
    return bool(
        str(metadata.get("file_id") or "") in file_scope
        or str(metadata.get("knowledge_id") or "") in knowledge_scope
    )


def _filter_search_result_to_scope(
    result,
    *,
    knowledge_ids: Optional[list[str]],
    file_ids: Optional[list[str]],
    allow_unscoped_legacy: bool,
):
    if result is None:
        return None

    has_scope = bool(knowledge_ids or file_ids)
    rows_by_query = []
    for documents, metadatas, ids, distances in zip(
        result.documents,
        result.metadatas,
        result.ids,
        result.distances,
    ):
        rows = [
            (document, metadata or {}, vector_id, distance)
            for document, metadata, vector_id, distance in zip(
                documents, metadatas, ids, distances
            )
            if (
                _metadata_matches_scope(
                    metadata or {},
                    knowledge_ids=knowledge_ids,
                    file_ids=file_ids,
                )
                if has_scope
                else allow_unscoped_legacy
            )
        ]
        rows_by_query.append(rows)

    from open_webui.retrieval.vector.main import SearchResult

    return SearchResult(
        documents=[[row[0] for row in rows] for rows in rows_by_query],
        metadatas=[[row[1] for row in rows] for rows in rows_by_query],
        ids=[[row[2] for row in rows] for rows in rows_by_query],
        distances=[[row[3] for row in rows] for rows in rows_by_query],
    )


def _filter_get_result_to_scope(
    result,
    *,
    knowledge_ids: Optional[list[str]],
    file_ids: Optional[list[str]],
    allow_unscoped_legacy: bool = False,
):
    """Filter a vector get result before it can enter full-context retrieval."""
    if result is None:
        return None

    documents = result.documents[0] if result.documents else []
    metadatas = result.metadatas[0] if result.metadatas else []
    ids = result.ids[0] if result.ids else []
    has_scope = bool(knowledge_ids or file_ids)
    rows = [
        (document, metadata or {}, vector_id)
        for document, metadata, vector_id in zip(documents, metadatas, ids)
        if (
            _metadata_matches_scope(
                metadata or {}, knowledge_ids=knowledge_ids, file_ids=file_ids
            )
            if has_scope
            else allow_unscoped_legacy
        )
    ]
    if not rows:
        return None

    from open_webui.retrieval.vector.main import GetResult

    return GetResult(
        documents=[[row[0] for row in rows]],
        metadatas=[[row[1] for row in rows]],
        ids=[[row[2] for row in rows]],
    )


def get_all_items_from_collections(
    collection_names: list[str],
    *,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
    allow_unscoped_legacy: bool = False,
) -> dict:
    results = []

    for collection_name in collection_names:
        if collection_name:
            try:
                if (
                    admin_id
                    and embedding_model_id
                    and hasattr(VECTOR_DB_CLIENT, "get_model_aware")
                ):
                    result = VECTOR_DB_CLIENT.get_model_aware(
                        collection_name=collection_name,
                        admin_id=admin_id,
                        embedding_model_id=embedding_model_id,
                        knowledge_ids=knowledge_ids,
                        file_ids=file_ids,
                    )
                    result = _filter_get_result_to_scope(
                        result,
                        knowledge_ids=knowledge_ids,
                        file_ids=file_ids,
                        allow_unscoped_legacy=allow_unscoped_legacy,
                    )
                else:
                    result = get_doc(collection_name=collection_name)
                    result = _filter_get_result_to_scope(
                        result,
                        knowledge_ids=knowledge_ids,
                        file_ids=file_ids,
                        allow_unscoped_legacy=allow_unscoped_legacy,
                    )
                if result is not None:
                    results.append(result.model_dump())
            except Exception as e:
                log.exception(
                    "Error when querying a collection | error_type=%s",
                    type(e).__name__,
                )
        else:
            pass

    merged = merge_get_results(results)
    merged_rows = list(
        zip(
            merged.get("documents", [[]])[0],
            merged.get("metadatas", [[]])[0],
            merged.get("ids", [[]])[0],
        )
    )
    rows_by_identity = {}
    for row in merged_rows:
        identity = _full_context_identity(row[0], row[1] or {})
        current = rows_by_identity.get(identity)
        if current is None or _full_context_sort_key(row) < _full_context_sort_key(
            current
        ):
            rows_by_identity[identity] = row
    rows = list(rows_by_identity.values())
    rows.sort(key=_full_context_sort_key)
    return {
        "documents": [[row[0] for row in rows]],
        "metadatas": [[row[1] for row in rows]],
        "ids": [[row[2] for row in rows]],
    }


def _full_context_identity(document, metadata: dict) -> tuple:
    file_id = str(metadata.get("file_id") or "")
    if file_id and metadata.get("chunk_index") is not None:
        return ("file_chunk", file_id, str(metadata.get("chunk_index")))
    visual_id = str(metadata.get("visual_asset_id") or "")
    if visual_id:
        return ("visual", visual_id)
    if isinstance(document, str):
        return (
            "content",
            file_id,
            hashlib.sha256(document.encode("utf-8")).hexdigest(),
        )
    return (
        "position",
        file_id,
        str(metadata.get("page_index") or ""),
        str(metadata.get("source_sequence") or ""),
        str(metadata.get("modality") or ""),
    )


def _full_context_sort_key(row: tuple) -> tuple:
    document, metadata, _vector_id = row
    metadata = metadata or {}
    top_norm = _finite_float(metadata.get("top_norm"))
    return (
        str(metadata.get("file_id") or ""),
        _sortable_number(metadata.get("chunk_index")),
        _sortable_number(metadata.get("page_index")),
        top_norm if top_norm is not None else math.inf,
        1 if metadata.get("modality") == "image" else 0,
        _sortable_number(metadata.get("source_sequence")),
        hashlib.sha256(
            (document if isinstance(document, str) else "").encode("utf-8")
        ).hexdigest(),
    )


def query_collection(
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    k: int,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
    allow_unscoped_legacy: bool = False,
) -> dict:
    log.info(
        "[QUERY_COLLECTION] START | collections_count=%s | queries_count=%s | k=%s",
        len(collection_names) if collection_names else 0,
        len(queries) if queries else 0,
        k,
    )
    results = []
    # pgvector model-aware search returns cosine distance (smaller is better).
    # Other connector paths retain their legacy score direction.
    reverse_distances = bool(
        VECTOR_DB != "chroma" and not (admin_id and embedding_model_id)
    )
    
    # Handle edge cases
    if not queries or len(queries) == 0:
        log.warning("[QUERY_COLLECTION] EMPTY | called with empty queries list")
        return merge_and_sort_query_results(results, k=k, reverse=reverse_distances)
    
    if not collection_names or len(collection_names) == 0:
        log.warning("query_collection called with empty collection_names list")
        return merge_and_sort_query_results(results, k=k, reverse=reverse_distances)
    
    # Filter out empty queries
    queries = [q for q in queries if q and q.strip()]
    if not queries:
        log.warning("All queries were empty after filtering")
        return merge_and_sort_query_results(results, k=k, reverse=reverse_distances)
    
    # Batch embedding generation for multiple queries (faster than individual calls)
    # The embedding_function supports both single strings and lists of strings
    query_embedding_map = {}
    try:
        if len(queries) > 1:
            # Batch embed all queries at once - significantly faster for multiple queries
            log.debug(f"Batching {len(queries)} queries for embedding generation")
            query_embeddings = embedding_function(queries)
            
            # Handle different return formats:
            # - List of embeddings: [[emb1], [emb2], ...] or [emb1, emb2, ...]
            # - Single embedding: [emb1] or just emb1 (shouldn't happen for batch)
            if isinstance(query_embeddings, list):
                if len(query_embeddings) == len(queries):
                    # Check if embeddings are nested lists or flat lists
                    if len(query_embeddings) > 0 and isinstance(query_embeddings[0], list):
                        # Already in correct format: [[emb1], [emb2], ...]
                        # Validate embeddings are not empty
                        for i, emb in enumerate(query_embeddings):
                            if isinstance(emb, list) and len(emb) > 0:
                                query_embedding_map[queries[i]] = emb
                            else:
                                log.warning(
                                    "Empty or invalid embedding for query index %s", i
                                )
                    else:
                        # Flat list: might be single embedding or needs wrapping
                        # If length matches, assume each element is an embedding vector
                        for i, emb in enumerate(query_embeddings):
                            if isinstance(emb, list) and len(emb) > 0:
                                query_embedding_map[queries[i]] = emb
                            else:
                                log.warning(
                                    "Empty or invalid embedding for query index %s", i
                                )
                else:
                    # Mismatch - fallback to individual calls
                    log.warning(f"Batch embedding returned {len(query_embeddings)} results for {len(queries)} queries, falling back to individual calls")
                    raise ValueError("Batch embedding result length mismatch")
            else:
                # Unexpected return type - fallback
                log.warning(f"Batch embedding returned unexpected type: {type(query_embeddings)}, falling back to individual calls")
                raise ValueError("Unexpected batch embedding return type")
        elif len(queries) == 1:
            # Single query - embed normally
            embedding = embedding_function(queries[0])
            # Ensure it's a list (embedding functions should return list[float])
            if isinstance(embedding, list) and len(embedding) > 0:
                query_embedding_map[queries[0]] = embedding
            else:
                # Invalid embedding - log and skip
                log.warning("Empty or invalid embedding for single query")
                if not isinstance(embedding, list):
                    # Try wrapping as fallback
                    query_embedding_map[queries[0]] = [embedding] if embedding else None
    except Exception as error:
        log.exception(
            "Error generating batch embeddings | error_type=%s",
            type(error).__name__,
        )
        # Fallback to individual embedding generation
        log.debug("Falling back to individual embedding generation")
        for query in queries:
            try:
                embedding = embedding_function(query)
                if isinstance(embedding, list) and len(embedding) > 0:
                    query_embedding_map[query] = embedding
                elif isinstance(embedding, list) and len(embedding) == 0:
                    log.warning("Empty embedding returned for query")
                else:
                    # Wrap non-list embeddings
                    query_embedding_map[query] = [embedding] if embedding else None
            except Exception as embed_error:
                log.exception(
                    "Error embedding query | error_type=%s",
                    type(embed_error).__name__,
                )
                continue
    
    # Validate we have at least some embeddings
    if not query_embedding_map:
        log.error("Failed to generate embeddings for any queries")
        return merge_and_sort_query_results(results, k=k, reverse=reverse_distances)
    
    # Parallelize query processing for faster RAG retrieval
    # Note: Thread-safety depends on the vector DB implementation:
    # - Postgres (pgvector): Uses scoped_session - thread-safe
    # - SQLite-based DBs: May have issues with concurrent access
    # - Chroma/Qdrant/Milvus: Generally thread-safe if using separate clients per thread
    def process_query_collection_pair(query: str, collection_name: str, query_embedding: list[float]):
        """Process a single query against a single collection using pre-computed embedding"""
        try:
            if collection_name:
                result = query_doc(
                    collection_name=collection_name,
                    k=k,
                    query_embedding=query_embedding,
                    admin_id=admin_id,
                    embedding_model_id=embedding_model_id,
                    knowledge_ids=knowledge_ids,
                    file_ids=file_ids,
                    allow_unscoped_legacy=allow_unscoped_legacy,
                )
                if result is not None:
                    return result.model_dump()
        except Exception as error:
            log.exception(
                "Error when querying collection | error_type=%s",
                type(error).__name__,
            )
        return None
    
    # Create all query-collection pairs with pre-computed embeddings
    # Filter out None embeddings and ensure embeddings are valid lists
    query_collection_pairs = []
    for query in queries:
        if query not in query_embedding_map:
            continue
        embedding = query_embedding_map[query]
        if embedding is None or not isinstance(embedding, list) or len(embedding) == 0:
            continue
        for collection_name in collection_names:
            query_collection_pairs.append((query, collection_name, embedding))
    
    if not query_collection_pairs:
        log.warning("No valid query-collection pairs after filtering invalid embeddings")
        return merge_and_sort_query_results(results, k=k, reverse=reverse_distances)
    
    # For single query-collection pair, process sequentially to avoid overhead
    # For multiple queries/collections, use parallel processing
    if len(query_collection_pairs) == 1:
        # Sequential processing for single query-collection pair
        query, collection_name, query_embedding = query_collection_pairs[0]
        if query_embedding and isinstance(query_embedding, list) and len(query_embedding) > 0:
            result = process_query_collection_pair(query, collection_name, query_embedding)
            if result is not None:
                results.append(result)
    elif len(query_collection_pairs) > 1:
        # Process in parallel using ThreadPoolExecutor
        # Limit workers to prevent resource exhaustion and potential SQLite lock issues
        max_workers = min(len(query_collection_pairs), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pair = {
                executor.submit(process_query_collection_pair, query, collection_name, query_embedding): (query, collection_name)
                for query, collection_name, query_embedding in query_collection_pairs
                if query_embedding is not None and isinstance(query_embedding, list) and len(query_embedding) > 0
            }
            
            if not future_to_pair:
                log.warning("No valid futures created for parallel query processing")
            else:
                for future in as_completed(future_to_pair):
                    try:
                        result = future.result()
                        if result is not None:
                            results.append(result)
                    except Exception as error:
                        log.exception(
                            "Error in parallel query processing | error_type=%s",
                            type(error).__name__,
                        )

    merged = merge_and_sort_query_results(
        results, k=k, reverse=reverse_distances
    )
    
    merged_count = len(merged.get("documents", [[]])[0]) if merged and merged.get("documents") else 0
    log.info(
        "[QUERY_COLLECTION] DONE | collections_count=%s | results_merged=%s | k=%s",
        len(collection_names),
        merged_count,
        k,
    )
    return merged


def query_collection_with_hybrid_search(
    collection_names: list[str],
    queries: list[str],
    embedding_function,
    k: int,
    reranking_function,
    r: float,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
    allow_unscoped_legacy: bool = False,
) -> dict:
    if _is_multimodal_model_space(admin_id, embedding_model_id):
        log.info("[HYBRID_SEARCH] multimodal model space uses dense retrieval")
        return query_collection(
            collection_names=collection_names,
            queries=queries,
            embedding_function=embedding_function,
            k=k,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
            allow_unscoped_legacy=allow_unscoped_legacy,
        )

    log.info(
        "[HYBRID_SEARCH] START | collections_count=%s | queries_count=%s | k=%s | r=%s",
        len(collection_names) if collection_names else 0,
        len(queries) if queries else 0,
        k,
        r,
    )
    results = []
    errors = []
    
    # Handle edge cases
    if not queries or len(queries) == 0:
        log.warning("query_collection_with_hybrid_search called with empty queries list")
        return merge_and_sort_query_results(results, k=k, reverse=True) if VECTOR_DB != "chroma" else merge_and_sort_query_results(results, k=k, reverse=False)
    
    if not collection_names or len(collection_names) == 0:
        log.warning("query_collection_with_hybrid_search called with empty collection_names list")
        return merge_and_sort_query_results(results, k=k, reverse=True) if VECTOR_DB != "chroma" else merge_and_sort_query_results(results, k=k, reverse=False)
    
    # Filter out empty queries
    queries = [q for q in queries if q and q.strip()]
    if not queries:
        log.warning("All queries were empty after filtering in hybrid search")
        return merge_and_sort_query_results(results, k=k, reverse=True) if VECTOR_DB != "chroma" else merge_and_sort_query_results(results, k=k, reverse=False)
    
    # Parallelize query processing for faster RAG retrieval with hybrid search
    # Note: Thread-safety depends on the vector DB implementation
    def process_hybrid_search(query: str, collection_name: str):
        """Process a single query against a single collection with hybrid search"""
        try:
            result = query_doc_with_hybrid_search(
                collection_name=collection_name,
                query=query,
                embedding_function=embedding_function,
                k=k,
                reranking_function=reranking_function,
                r=r,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                knowledge_ids=knowledge_ids,
                file_ids=file_ids,
                allow_unscoped_legacy=allow_unscoped_legacy,
            )
            return {"result": result, "error": None, "collection": collection_name}
        except Exception as error:
            log.exception(
                "Error when querying collection with hybrid search | error_type=%s",
                type(error).__name__,
            )
            return {
                "result": None,
                "error": type(error).__name__,
                "collection": collection_name,
            }
    
    # Create all query-collection pairs
    query_collection_pairs = [
        (query, collection_name)
        for collection_name in collection_names
        for query in queries
    ]
    
    if not query_collection_pairs:
        log.warning("No valid query-collection pairs for hybrid search")
        return merge_and_sort_query_results(results, k=k, reverse=True) if VECTOR_DB != "chroma" else merge_and_sort_query_results(results, k=k, reverse=False)
    
    # For single query-collection pair, process sequentially to avoid overhead
    # For multiple queries/collections, use parallel processing
    if len(query_collection_pairs) == 1:
        # Sequential processing for single query-collection pair
        pair_result = process_hybrid_search(query_collection_pairs[0][0], query_collection_pairs[0][1])
        if pair_result["result"] is not None:
            results.append(pair_result["result"])
        elif pair_result["error"]:
            errors.append(pair_result)
    else:
        # Process in parallel using ThreadPoolExecutor
        # Limit workers to prevent resource exhaustion and potential SQLite lock issues
        max_workers = min(len(query_collection_pairs), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pair = {
                executor.submit(process_hybrid_search, query, collection_name): (query, collection_name)
                for query, collection_name in query_collection_pairs
            }
            
            for future in as_completed(future_to_pair):
                try:
                    pair_result = future.result()
                    if pair_result["result"] is not None:
                        results.append(pair_result["result"])
                    elif pair_result["error"]:
                        errors.append(pair_result)
                except Exception as error:
                    log.exception(
                        "Error in parallel hybrid search processing | error_type=%s",
                        type(error).__name__,
                    )
                    errors.append(
                        {
                            "result": None,
                            "error": type(error).__name__,
                            "collection": "unknown",
                        }
                    )

    # Only raise error if ALL searches failed
    if len(errors) == len(query_collection_pairs):
        log.error(
            "[HYBRID_SEARCH] ALL_FAILED | collections_count=%s | errors_count=%s",
            len(collection_names),
            len(errors),
        )
        raise Exception(
            "Hybrid search failed for all collections. Using Non hybrid search as fallback."
        )

    if VECTOR_DB == "chroma":
        # Chroma uses unconventional cosine similarity, so we don't need to reverse the results
        # https://docs.trychroma.com/docs/collections/configure#configuring-chroma-collections
        merged = merge_and_sort_query_results(results, k=k, reverse=False)
    else:
        merged = merge_and_sort_query_results(results, k=k, reverse=True)
    
    merged_count = len(merged.get("documents", [[]])[0]) if merged and merged.get("documents") else 0
    log.info(
        "[HYBRID_SEARCH] DONE | collections_count=%s | results_merged=%s | errors_count=%s | k=%s",
        len(collection_names),
        merged_count,
        len(errors),
        k,
    )
    return merged


def get_embedding_function(
    embedding_engine,
    embedding_model,
    embedding_function,
    url,
    key,
    embedding_batch_size,
    backoff=True,
):
    if embedding_engine == "":
        return lambda query, user=None: embedding_function.encode(query).tolist()
    elif embedding_engine in ["ollama", "openai", "portkey"]:
        func = lambda query, user=None: generate_embeddings(
            engine=embedding_engine,
            model=embedding_model,
            text=query,
            url=url,
            key=key,
            user=user,
            backoff=backoff,
        )

        def generate_multiple(query, user, func):
            if isinstance(query, list):
                embeddings = []
                for i in range(0, len(query), embedding_batch_size):
                    embeddings.extend(
                        func(query[i : i + embedding_batch_size], user=user)
                    )
                return embeddings
            else:
                return func(query, user)

        return lambda query, user=None: generate_multiple(query, user, func)
    else:
        raise ValueError(f"Unknown embedding engine: {embedding_engine}")


# Modified get_embedding_function to send all texts in one batch
def get_single_batch_embedding_function(
    embedding_engine,
    embedding_model,
    embedding_function,
    url,
    key,
    embedding_batch_size,
    backoff=True,
):
    if embedding_engine == "":
        return lambda query, user=None: embedding_function.encode(query).tolist()
    elif embedding_engine in ["ollama", "openai", "portkey"]:
        engine = embedding_engine
        model = embedding_model
        url = url
        key = key

        # Return a function that processes everything in one go
        return lambda query, user=None: generate_embeddings(
            engine=engine,
            model=model,
            text=query,
            url=url,
            key=key,
            user=user,
            backoff=backoff,
        )
    else:
        raise ValueError(f"Unknown embedding engine: {embedding_engine}")


def get_sources_from_files(
    request,
    files,
    queries,
    embedding_function,
    k,
    reranking_function,
    r,
    hybrid_search,
    full_context=False,
    user=None,
    trusted_legacy_collection_names: Optional[set[str]] = None,
    trusted_attachment_ids: Optional[set[int]] = None,
) -> RetrievalResult:
    log.debug(
        "Preparing retrieval | files_count=%s | queries_count=%s | full_context=%s",
        len(files) if files else 0,
        len(queries) if queries else 0,
        bool(full_context),
    )

    if user is None:
        raise ValueError("Authenticated user is required for file retrieval")

    from open_webui.retrieval.embedding.compatibility import make_embedding_function
    from open_webui.retrieval.embedding.service import EmbeddingService

    embedding_service = EmbeddingService(request.app.state.config)

    trusted_legacy_collection_names = {
        str(value)
        for value in (trusted_legacy_collection_names or set())
        if value
    }
    trusted_attachment_ids = set(trusted_attachment_ids or set())
    canonical_files: list[dict] = []
    direct_file_ids: list[str] = []
    knowledge_ids_in_scope: list[str] = []
    pending_file_attachments: dict[str, tuple[dict, object]] = {}
    pending_knowledge_attachments: dict[str, tuple[dict, object]] = {}

    from open_webui.models.knowledge import Knowledges
    from open_webui.retrieval.embedding.gate import assert_embedding_retrieval_ready

    for attached_file in files or []:
        if not isinstance(attached_file, dict):
            continue

        attachment_type = attached_file.get("type")
        is_trusted_server_attachment = id(attached_file) in trusted_attachment_ids
        if attachment_type == "web_search":
            if is_trusted_server_attachment:
                canonical_files.append(attached_file)
            continue
        if attachment_type == "text":
            if is_trusted_server_attachment:
                canonical_files.append(attached_file)
            continue

        if attachment_type == "collection":
            knowledge_id = str(attached_file.get("id") or "").strip()
            if knowledge_id:
                knowledge = Knowledges.get_knowledge_by_id(knowledge_id)
                if knowledge is not None:
                    knowledge_ids_in_scope.append(knowledge_id)
                    pending_knowledge_attachments.setdefault(
                        knowledge_id, (attached_file, knowledge)
                    )
                    continue

            requested_legacy_names = attached_file.get("collection_names") or []
            if not isinstance(requested_legacy_names, list):
                requested_legacy_names = []
            # Trust comes from the server-side model allowlist, never from the
            # descriptor's client-controlled ``legacy`` flag or raw names.
            legacy_names = [
                str(value)
                for value in requested_legacy_names
                if value and str(value) in trusted_legacy_collection_names
            ]
            if legacy_names:
                canonical_files.append(
                    {
                        "name": attached_file.get("name"),
                        "type": "collection",
                        "collection_names": list(dict.fromkeys(legacy_names)),
                        "legacy": True,
                    }
                )
            continue

        file_id = str(attached_file.get("id") or "").strip()
        if not file_id:
            continue
        file_object = Files.get_file_by_id(file_id)
        if file_object is None:
            continue
        direct_file_ids.append(file_id)
        pending_file_attachments.setdefault(file_id, (attached_file, file_object))

    knowledge_ids_in_scope = list(dict.fromkeys(knowledge_ids_in_scope))
    file_ids_in_scope = list(dict.fromkeys(direct_file_ids))
    authorized_scope = AuthorizedAttachmentScope(
        file_ids=frozenset(file_ids_in_scope),
        knowledge_ids=frozenset(knowledge_ids_in_scope),
    )
    if not canonical_files and not pending_file_attachments and not pending_knowledge_attachments:
        return RetrievalResult([], authorized_scope)

    # Phase 3: resolve the requesting user's admin/model provenance space.
    # Mixed-model requests return no sources, while other model-space errors
    # propagate so callers cannot fall back to model-unaware vector search.
    # This guard covers both the hybrid and non-hybrid paths because invalid
    # requests are rejected before any vector search runs.
    admin_id = None
    embedding_model_id = None
    multimodal_model_space = False
    if canonical_files or pending_file_attachments or pending_knowledge_attachments:
        try:
            from open_webui.retrieval.embedding.errors import (
                EmbeddingError,
                EMBEDDING_MODEL_SPACE_MIXED,
                EMBEDDING_REINDEX_NOT_READY,
            )
            from open_webui.retrieval.embedding.gate import RetrievalModelSpace

            # Spec 10: single gate call — resolves admin/model space, validates
            # knowledge/file ownership, and checks readiness.
            result = assert_embedding_retrieval_ready(
                requesting_user_id=user.id,
                knowledge_ids=knowledge_ids_in_scope or None,
                file_ids=file_ids_in_scope or None,
            )
            if isinstance(result, RetrievalModelSpace):
                admin_id = result.admin_id
                embedding_model_id = result.active_model_id
                # Bind the query callable to the exact active model space approved
                # by this gate result; mutable compatibility config cannot switch it.
                embedding_function = make_embedding_function(
                    embedding_service,
                    admin_id=admin_id,
                    embedding_model_id=embedding_model_id,
                )
                from open_webui.retrieval.embedding.registry import (
                    get_model_spec_by_id,
                )

                model_spec = get_model_spec_by_id(embedding_model_id)
                multimodal_model_space = "image" in model_spec.modalities
                if multimodal_model_space:
                    # Empty image chunks must never enter BM25 or reranking.
                    hybrid_search = False
            else:
                # RetrievalReadyNoState: legacy admin, no model-aware search.
                admin_id = None
                embedding_model_id = None
                embedding_function = make_embedding_function(
                    embedding_service,
                    user_id=user.id,
                )
        except EmbeddingError as error:
            if error.code == EMBEDDING_MODEL_SPACE_MIXED:
                # Mixed-model request: no valid cross-model results exist.
                log.warning("[RAG Query] retrieval rejected | code=%s", error.code)
                return RetrievalResult(
                    [], AuthorizedAttachmentScope(frozenset(), frozenset())
                )
            if error.code == EMBEDDING_REINDEX_NOT_READY:
                # Blocked state: propagate so callers can distinguish
                # "no matches" from "reindex in progress / failed."
                log.warning("[RAG Query] retrieval blocked | code=%s", error.code)
                raise
            # Ownership, missing-source, and admin-resolution failures must
            # fail closed rather than silently searching without provenance.
            log.warning("[RAG Query] retrieval rejected | code=%s", error.code)
            raise
        except Exception as error:
            log.warning(
                "[RAG Query] retrieval readiness check failed | error_type=%s",
                type(error).__name__,
            )
            raise

    for knowledge_id, (
        _attached_file,
        knowledge,
    ) in pending_knowledge_attachments.items():
        canonical_files.append(
            {
                "id": knowledge_id,
                "name": knowledge.name,
                "type": "collection",
            }
        )
    for file_id, (attached_file, file_object) in pending_file_attachments.items():
        canonical_files.append(
            {
                "id": file_id,
                "name": file_object.filename,
                "type": "image" if attached_file.get("type") == "image" else "file",
                "collection_name": f"file-{file_id}",
            }
        )

    extracted_collections = []
    relevant_contexts = []

    for file in canonical_files:
        queried_collections_this_file = []

        context = None
        if file.get("type") == "web_search" and file.get("docs"):
            # BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
            context = {
                "documents": [[doc.get("content") for doc in file.get("docs")]],
                "metadatas": [[doc.get("metadata") for doc in file.get("docs")]],
            }
        elif (
            file.get("type") != "web_search"
            and request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
        ):
            # BYPASS_EMBEDDING_AND_RETRIEVAL
            if file.get("type") == "collection":
                knowledge = Knowledges.get_knowledge_by_id(str(file.get("id") or ""))
                file_ids = (
                    knowledge.data.get("file_ids", [])
                    if knowledge is not None and isinstance(knowledge.data, dict)
                    else []
                )

                documents = []
                metadatas = []
                for file_id in file_ids:
                    file_object = Files.get_file_by_id(file_id)

                    if file_object:
                        documents.append(file_object.data.get("content", ""))
                        metadatas.append(
                            {
                                "file_id": file_id,
                                "knowledge_id": file.get("id"),
                                "name": file_object.filename,
                                "source": file_object.filename,
                            }
                        )

                context = {
                    "documents": [documents],
                    "metadatas": [metadatas],
                }

            elif file.get("id"):
                file_object = Files.get_file_by_id(file.get("id"))
                if file_object:
                    context = {
                        "documents": [[file_object.data.get("content", "")]],
                        "metadatas": [
                            [
                                {
                                    "file_id": file.get("id"),
                                    "name": file_object.filename,
                                    "source": file_object.filename,
                                }
                            ]
                        ],
                    }
        else:
            collection_names = []
            item_knowledge_ids = None
            item_file_ids = None
            if file.get("type") == "collection":
                if file.get("legacy"):
                    collection_names = file.get("collection_names", [])
                else:
                    collection_names.append(file["id"])
                    item_knowledge_ids = [str(file["id"])]
            elif file.get("id"):
                collection_names.append(f"file-{file['id']}")
                item_file_ids = [str(file["id"])]

            collection_names = [
                collection_name
                for collection_name in dict.fromkeys(collection_names)
                if collection_name not in extracted_collections
            ]
            if not collection_names:
                log.debug("Skipping attachment already included in retrieval")
                continue

            queried_collections_this_file = list(collection_names)

            log.info(
                "[RAG Query] collections_count=%s | queries_count=%s",
                len(queried_collections_this_file),
                len(queries),
            )
            
            # Check if collections actually exist and have documents
            for coll_name in collection_names:
                try:
                    has_coll = VECTOR_DB_CLIENT.has_collection(collection_name=coll_name)
                    if not has_coll:
                        log.warning(
                            "[RAG Query WARNING] A requested collection does not exist; "
                            "the source may not have completed processing"
                        )
                except Exception as check_error:
                    log.debug(
                        "Could not check collection existence | error_type=%s",
                        type(check_error).__name__,
                    )

            if full_context:
                try:
                    context = get_all_items_from_collections(
                        collection_names,
                        admin_id=admin_id,
                        embedding_model_id=embedding_model_id,
                        knowledge_ids=item_knowledge_ids,
                        file_ids=item_file_ids,
                        allow_unscoped_legacy=bool(file.get("legacy")),
                    )
                except Exception as error:
                    log.exception(
                        "Full-context retrieval failed | error_type=%s",
                        type(error).__name__,
                    )

            else:
                try:
                    context = None
                    allow_unscoped_legacy = bool(
                        file.get("legacy") or file.get("type") == "web_search"
                    )
                    if file.get("type") == "text":
                        context = file["content"]
                    else:
                        if hybrid_search:
                            try:
                                context = query_collection_with_hybrid_search(
                                    collection_names=collection_names,
                                    queries=queries,
                                    embedding_function=embedding_function,
                                    k=k,
                                    reranking_function=reranking_function,
                                    r=r,
                                    admin_id=admin_id,
                                    embedding_model_id=embedding_model_id,
                                    knowledge_ids=item_knowledge_ids,
                                    file_ids=item_file_ids,
                                    allow_unscoped_legacy=allow_unscoped_legacy,
                                )
                            except Exception as e:
                                log.debug(
                                    "Error when using hybrid search, using"
                                    " non hybrid search as fallback."
                                )

                        if (not hybrid_search) or (context is None):
                            context = query_collection(
                                collection_names=collection_names,
                                queries=queries,
                                embedding_function=embedding_function,
                                k=k,
                                admin_id=admin_id,
                                embedding_model_id=embedding_model_id,
                                knowledge_ids=item_knowledge_ids,
                                file_ids=item_file_ids,
                                allow_unscoped_legacy=allow_unscoped_legacy,
                            )
                            
                            # Log if no results were found for debugging
                            if context is None or not context.get("documents") or not context["documents"][0]:
                                log.warning(
                                    "[RAG Query WARNING] No documents found for an attached source; "
                                    "processing, extraction, or embedding may be incomplete"
                                )
                except Exception as error:
                    log.exception(
                        "Source retrieval failed | error_type=%s",
                        type(error).__name__,
                    )

            extracted_collections.extend(collection_names)

        if context:
            if "data" in file:
                del file["data"]

            # RAG debug: per-file retrieval result (which file, how many chunks retrieved)
            num_chunks = 0
            if context.get("documents") and context["documents"]:
                num_chunks = len(context["documents"][0])
            log.info(
                "[RAG Retrieval] chunks_retrieved=%s | collections_queried=%s",
                num_chunks,
                len(queried_collections_this_file),
            )
            relevant_contexts.append({**context, "file": file})

    sources = []
    for context in relevant_contexts:
        try:
            if "documents" in context:
                if "metadatas" in context:
                    source = {
                        "source": context["file"],
                        "document": context["documents"][0],
                        "metadata": context["metadatas"][0],
                    }
                    if "distances" in context and context["distances"]:
                        source["distances"] = context["distances"][0]

                    sources.append(source)
        except Exception as error:
            log.exception(
                "Source assembly failed | error_type=%s", type(error).__name__
            )

    return RetrievalResult(sources, authorized_scope)


def get_model_path(model: str, update_model: bool = False):
    # Construct huggingface_hub kwargs with local_files_only to return the snapshot path
    cache_dir = os.getenv("SENTENCE_TRANSFORMERS_HOME")

    local_files_only = not update_model

    if OFFLINE_MODE:
        local_files_only = True

    snapshot_kwargs = {
        "cache_dir": cache_dir,
        "local_files_only": local_files_only,
    }

    log.debug(f"model: {model}")
    log.debug(f"snapshot_kwargs: {snapshot_kwargs}")

    # Inspiration from upstream sentence_transformers
    if (
        os.path.exists(model)
        or ("\\" in model or model.count("/") > 1)
        and local_files_only
    ):
        # If fully qualified path exists, return input, else set repo_id
        return model
    elif "/" not in model:
        # Set valid repo_id for model short-name
        model = "sentence-transformers" + "/" + model

    snapshot_kwargs["repo_id"] = model

    # Attempt to query the huggingface_hub library to determine the local path and/or to update
    try:
        model_repo_path = snapshot_download(**snapshot_kwargs)
        log.debug(f"model_repo_path: {model_repo_path}")
        return model_repo_path
    except Exception as e:
        log.exception(f"Cannot determine model snapshot path: {e}")
        return model


def generate_openai_batch_embeddings(
    model: str,
    texts: list[str],
    url: str = "https://api.openai.com/v1",
    key: str = "",
    user: UserModel = None,
) -> Optional[list[list[float]]]:
    try:
        r = requests.post(
            f"{url}/embeddings",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                **(
                    {
                        "X-OpenWebUI-User-Name": user.name,
                        "X-OpenWebUI-User-Id": user.id,
                        "X-OpenWebUI-User-Email": user.email,
                        "X-OpenWebUI-User-Role": user.role,
                    }
                    if ENABLE_FORWARD_USER_INFO_HEADERS and user
                    else {}
                ),
            },
            json={"input": texts, "model": model},
        )
        r.raise_for_status()
        data = r.json()
        if "data" in data:
            return [elem["embedding"] for elem in data["data"]]
        else:
            raise "Something went wrong :/"
    except Exception as e:
        log.exception(f"Error generating openai batch embeddings: {e}")
        return None


from typing import Optional, List, Union


def generate_portkey_embeddings_sdk(
    model: str,
    texts: Union[str, List[str]],
    base_url: str,
    api_key: str,
    encoding_format: str = "float",
) -> Union[List[float], List[List[float]]]:
    """
    Generate embeddings using Portkey Python SDK.
    
    This function uses the official Portkey SDK to generate embeddings for either
    a single string or a batch of strings. The SDK handles retries, error handling,
    and HTTP management automatically.
    
    Args:
        model: Portkey model identifier (e.g., "@openai-embedding/text-embedding-3-small")
        texts: Single string or list of strings to embed
        base_url: Portkey API base URL (e.g., "https://ai-gateway.apps.cloud.rt.nyu.edu/v1")
        api_key: Portkey API key
        encoding_format: "float" for uncompressed embeddings (default)
        
    Returns:
        list[float] if texts is a single string
        list[list[float]] if texts is a list of strings
        
    Raises:
        ImportError: If portkey_ai SDK is not installed
        Exception: For any Portkey API errors (handled by SDK)
    """
    if not PORTKEY_SDK_AVAILABLE:
        raise ImportError(
            "Portkey SDK (portkey_ai) is not installed. "
            "Install it with: pip install portkey-ai"
        )
    
    if not api_key:
        log.error(
            "Portkey API key is empty! This will result in 401 Unauthorized. "
            "Ensure the admin has configured an embedding API key in Settings > Documents."
        )
    
    # Initialize Portkey client (simple - no deprecated virtual_key)
    portkey = Portkey(
        base_url=base_url,
        api_key=api_key
    )
    
    # Generate embeddings using SDK
    # The SDK handles retries, rate limiting, and error handling automatically
    # CRITICAL: Azure OpenAI (via Portkey) has a limit of 2048 items per request
    # We need to batch large requests into chunks of max 2048 items
    MAX_BATCH_SIZE = 2048
    
    try:
        # Convert single string to list for uniform processing
        is_single_string = isinstance(texts, str)
        if is_single_string:
            texts_list = [texts]
        elif isinstance(texts, list):
            texts_list = texts
        else:
            raise ValueError(f"Invalid input type: {type(texts)}. Expected str or list[str]")
        
        texts_count = len(texts_list)
        
        # Validate input format without logging request content.
        log.info(
            "Portkey embedding input validation | input_type=%s | texts_count=%s",
            type(texts).__name__,
            texts_count,
        )

        non_string_count = 0
        empty_count = 0
        very_short_count = 0  # Items with length <= 1
        
        for i, text in enumerate(texts_list[:10]):  # Check first 10 items
            if not isinstance(text, str):
                non_string_count += 1
            elif len(text.strip()) == 0:
                empty_count += 1
            elif len(text) <= 1:
                very_short_count += 1
        
        # Check beyond first 10 for patterns
        for i in range(10, min(100, texts_count)):
            text = texts_list[i]
            if not isinstance(text, str):
                non_string_count += 1
            elif len(text.strip()) == 0:
                empty_count += 1
            elif len(text) <= 1:
                very_short_count += 1
        
        log.warning(
            "Portkey input diagnostics | non_string_items=%s | empty_items=%s | "
            "very_short_items=%s",
            non_string_count,
            empty_count,
            very_short_count,
        )
        
        # Validate all items are strings
        for i, text in enumerate(texts_list):
            if not isinstance(text, str):
                raise ValueError(
                    f"Item at index {i} is not a string ({type(text).__name__}). "
                    f"This suggests incorrect chunking or document processing."
                )
            if not text.strip():
                log.warning(f"Empty string at index {i} - may cause API errors")
        
        # Warn if most items are very short (suggests character-level chunking bug)
        if texts_count > 100 and very_short_count > texts_count * 0.9:
            error_msg = (
                f"CRITICAL: {very_short_count}/{texts_count} items are <=1 character. "
                f"This suggests chunk_size=0 or character-level splitting bug. "
                f"Check chunk_size configuration (should be >0, typically 500-2000)."
            )
            log.error(error_msg)
            raise ValueError(error_msg)
        
        if texts_list:
            avg_len = sum(len(t) for t in texts_list[:100]) / min(100, texts_count)
        else:
            avg_len = 0
        
        log.info(
            "Generating Portkey embeddings | texts_count=%s | avg_text_length=%.1f | "
            "will_batch=%s",
            texts_count,
            avg_len,
            texts_count > MAX_BATCH_SIZE,
        )
        
        # Batch processing for large requests
        if texts_count <= MAX_BATCH_SIZE:
            response = portkey.embeddings.create(
                model=model,
                input=texts_list,
                encoding_format=encoding_format
            )
            
            # Extract embeddings from response
            embeddings = [item.embedding for item in response.data]
        else:
            # Multiple batches needed - process in chunks
            log.info(f"Batching {texts_count} texts into chunks of {MAX_BATCH_SIZE} for Azure OpenAI limit")
            all_embeddings = []
            
            for i in range(0, texts_count, MAX_BATCH_SIZE):
                batch = texts_list[i:i + MAX_BATCH_SIZE]
                batch_num = (i // MAX_BATCH_SIZE) + 1
                total_batches = (texts_count + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
                log.info(
                    "Portkey embedding batch | batch=%s/%s | input_length=%s | avg_length=%.1f",
                    batch_num,
                    total_batches,
                    len(batch),
                    sum(len(t) for t in batch) / len(batch),
                )
                response = portkey.embeddings.create(
                    model=model,
                    input=batch,
                    encoding_format=encoding_format
                )
                
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            
            embeddings = all_embeddings
        
        # Validate embeddings were generated
        if not embeddings:
            raise ValueError("No embeddings returned from Portkey SDK")
        
        if len(embeddings) != texts_count:
            raise ValueError(
                f"Embedding count mismatch: expected {texts_count}, got {len(embeddings)}"
            )
        
        # Return single embedding for single string, list for batch
        if is_single_string:
            if len(embeddings) == 0:
                raise ValueError("Expected at least one embedding for single text input")
            return embeddings[0]
        return embeddings
        
    except Exception as e:
        log.exception(
            "Portkey embedding generation failed | error_type=%s",
            type(e).__name__,
        )
        raise


def generate_ollama_batch_embeddings(
    model: str, texts: list[str], url: str, key: str = "", user: UserModel = None
) -> Optional[list[list[float]]]:
    try:
        r = requests.post(
            f"{url}/api/embed",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                **(
                    {
                        "X-OpenWebUI-User-Name": user.name,
                        "X-OpenWebUI-User-Id": user.id,
                        "X-OpenWebUI-User-Email": user.email,
                        "X-OpenWebUI-User-Role": user.role,
                    }
                    if ENABLE_FORWARD_USER_INFO_HEADERS
                    else {}
                ),
            },
            json={"input": texts, "model": model},
        )
        r.raise_for_status()
        data = r.json()

        if "embeddings" in data:
            return data["embeddings"]
        else:
            raise "Something went wrong :/"
    except Exception as e:
        log.exception(f"Error generating ollama batch embeddings: {e}")
        return None


def generate_embeddings(
    engine: str, model: str, text: Union[str, list[str]], backoff: bool, **kwargs
):
    """
    Generate embeddings using the specified engine.
    
    This function routes embedding requests to the appropriate engine implementation.
    For Portkey, it uses the official Python SDK for clean, maintainable code.
    
    Args:
        engine: Embedding engine ("ollama", "openai", "portkey", or "" for local)
        model: Model identifier (e.g., "@openai-embedding/text-embedding-3-small")
        text: Single string or list of strings to embed
        backoff: Whether to use exponential backoff (for legacy compatibility)
        **kwargs: Additional engine-specific parameters:
            - url: API base URL
            - key: API key
            - user: UserModel instance
            
    Returns:
        list[float] if text is a single string
        list[list[float]] if text is a list of strings
    """
    url = kwargs.get("url", "")
    key = kwargs.get("key", "")
    user = kwargs.get("user")
    text_count = len(text) if isinstance(text, list) else 1
    log.info(
        "[GENERATE_EMBEDDINGS] START | engine=%s | texts_count=%s",
        engine,
        text_count,
    )
    
    # CRITICAL FIX: For portkey/openai engines, dynamically retrieve the user's API key
    # The `key` passed in may be the startup default (empty), but users configure their own keys
    # This ensures per-user API key scoping works correctly for RAG queries
    if engine in ["openai", "portkey"] and user and hasattr(user, 'email') and user.email:
        try:
            from open_webui.config import RAG_OPENAI_API_KEY
            user_key = RAG_OPENAI_API_KEY.get(user.email)
            if user_key:
                log.debug("Using configured per-user embedding credential")
                key = user_key
            else:
                log.warning("No per-user embedding credential found; using configured default")
        except Exception as e:
            log.warning(
                "Failed to retrieve per-user embedding credential | error_type=%s",
                type(e).__name__,
            )

    if engine == "ollama":
        if isinstance(text, list):
            embeddings = generate_ollama_batch_embeddings(
                **{"model": model, "texts": text, "url": url, "key": key, "user": user}
            )
        else:
            embeddings = generate_ollama_batch_embeddings(
                **{
                    "model": model,
                    "texts": [text],
                    "url": url,
                    "key": key,
                    "user": user,
                }
            )
        emb_count = len(embeddings) if isinstance(embeddings, list) else 1
        log.info("[GENERATE_EMBEDDINGS] SUCCESS | engine=ollama | embeddings_count=%s", emb_count)
        return embeddings[0] if isinstance(text, str) else embeddings
    elif engine == "openai":
        if isinstance(text, list):
            embeddings = generate_openai_batch_embeddings(model, text, url, key, user)
        else:
            embeddings = generate_openai_batch_embeddings(model, [text], url, key, user)

        emb_count = len(embeddings) if isinstance(embeddings, list) else 1
        log.info("[GENERATE_EMBEDDINGS] SUCCESS | engine=openai | embeddings_count=%s", emb_count)
        return embeddings[0] if isinstance(text, str) else embeddings
    elif engine == "portkey":
        # Use SDK-based implementation
        embeddings = generate_portkey_embeddings_sdk(
            model=model,
            texts=text,
            base_url=url,
            api_key=key,
            encoding_format="float"
        )
        emb_count = len(embeddings) if isinstance(embeddings, list) else 1
        log.info("[GENERATE_EMBEDDINGS] SUCCESS | engine=portkey | embeddings_count=%s", emb_count)
        return embeddings
    else:
        log.error(f"[GENERATE_EMBEDDINGS] ERROR | unknown engine={engine}")
        raise ValueError(f"Unknown embedding engine: {engine}")


import operator
from typing import Optional, Sequence

from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document


class RerankCompressor(BaseDocumentCompressor):
    embedding_function: Any
    top_n: int
    reranking_function: Any
    r_score: float

    class Config:
        extra = "forbid"
        arbitrary_types_allowed = True

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        reranking = self.reranking_function is not None

        if reranking:
            scores = self.reranking_function.predict(
                [(query, doc.page_content) for doc in documents]
            )
        else:
            from sentence_transformers import util

            query_embedding = self.embedding_function(query)
            document_embedding = self.embedding_function(
                [doc.page_content for doc in documents]
            )
            scores = util.cos_sim(query_embedding, document_embedding)[0]

        docs_with_scores = list(zip(documents, scores.tolist()))
        if self.r_score:
            docs_with_scores = [
                (d, s) for d, s in docs_with_scores if s >= self.r_score
            ]

        result = sorted(docs_with_scores, key=operator.itemgetter(1), reverse=True)
        final_results = []
        for doc, doc_score in result[: self.top_n]:
            metadata = doc.metadata
            metadata["score"] = doc_score
            doc = Document(
                page_content=doc.page_content,
                metadata=metadata,
            )
            final_results.append(doc)
        return final_results
