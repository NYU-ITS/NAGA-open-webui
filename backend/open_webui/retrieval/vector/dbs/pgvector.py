from typing import Optional, List, Dict, Any
import logging
import time
from sqlalchemy import (
    BigInteger,
    cast,
    column,
    create_engine,
    Column,
    Integer,
    MetaData,
    or_,
    select,
    String,
    text,
    Text,
    Table,
    values,
)
from sqlalchemy.sql import true
from sqlalchemy.pool import NullPool

from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB, array
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.exc import NoSuchTableError

from open_webui.retrieval.vector.main import VectorItem, SearchResult, GetResult
from open_webui.config import PGVECTOR_DB_URL, PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH

from open_webui.env import SRC_LOG_LEVELS

VECTOR_LENGTH = PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH
Base = declarative_base()

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])


class DocumentChunk(Base):
    """ORM view of the embeddings_1536 physical vector table.

    The table was renamed from ``document_chunk`` to ``embeddings_1536`` in the
    Phase 3 migration. The legacy columns (collection_name, vmetadata, text)
    remain for the collection-name read path during the transition; the
    provenance columns (admin_id, embedding_model_id, file_id, knowledge_id,
    rag_chunk_id, modality, embedding_status, provenance_status) back the
    model-aware write/read path introduced in Phase 3.
    """

    __tablename__ = "embeddings_1536"

    id = Column(Text, primary_key=True)
    vector = Column(Vector(dim=VECTOR_LENGTH), nullable=True)
    collection_name = Column(Text, nullable=False)
    text = Column(Text, nullable=True)
    vmetadata = Column(MutableDict.as_mutable(JSONB), nullable=True)

    # Phase 1/3 model-aware provenance columns.
    admin_id = Column(Text, nullable=True)
    embedding_model_id = Column(Text, nullable=True)
    file_id = Column(Text, nullable=True)
    knowledge_id = Column(Text, nullable=True)
    rag_chunk_id = Column(Text, nullable=True)
    modality = Column(String(16), nullable=True)
    embedding_status = Column(String(16), nullable=True)
    provenance_status = Column(String(20), nullable=False, default="unattributed")
    created_at = Column(BigInteger, nullable=True)
    updated_at = Column(BigInteger, nullable=True)


class PgvectorClient:
    def __init__(self) -> None:
        log.info("[PGVECTOR] init START | use_existing_db=%s", not PGVECTOR_DB_URL)
        # if no pgvector uri, use the existing database connection
        if not PGVECTOR_DB_URL:
            from open_webui.internal.db import Session

            self.session = Session
        else:
            engine = create_engine(
                PGVECTOR_DB_URL, pool_pre_ping=True, poolclass=NullPool
            )
            SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
            )
            self.session = scoped_session(SessionLocal)

        # Schema ownership belongs to Alembic.  Runtime initialization is deliberately
        # read-only so a worker cannot create a differently shaped vector table.
        self.check_vector_length()
        log.info("[PGVECTOR] init SUCCESS")

    def check_vector_length(self) -> None:
        """
        Check if the VECTOR_LENGTH matches the existing vector column dimension in the database.
        Raises an exception if there is a mismatch.
        """
        metadata = MetaData()
        try:
            # Reflect the renamed embeddings_1536 table.
            embeddings_table = Table(
                "embeddings_1536", metadata, autoload_with=self.session.bind
            )
        except NoSuchTableError:
            # Table does not exist; no action needed
            return

        # Proceed to check the vector column
        if "vector" in embeddings_table.columns:
            vector_column = embeddings_table.columns["vector"]
            vector_type = vector_column.type
            if isinstance(vector_type, Vector):
                db_vector_length = vector_type.dim
                if db_vector_length != VECTOR_LENGTH:
                    raise Exception(
                        f"VECTOR_LENGTH {VECTOR_LENGTH} does not match existing vector column dimension {db_vector_length}. "
                        "Cannot change vector size after initialization without migrating the data."
                    )
            else:
                raise Exception(
                    "The 'vector' column exists but is not of type 'Vector'."
                )
        else:
            raise Exception(
                "The 'vector' column does not exist in the 'embeddings_1536' table."
            )

    def adjust_vector_length(self, vector: List[float]) -> List[float]:
        # Adjust vector to have length VECTOR_LENGTH
        current_length = len(vector)
        if current_length < VECTOR_LENGTH:
            # Pad the vector with zeros
            vector += [0.0] * (VECTOR_LENGTH - current_length)
        elif current_length > VECTOR_LENGTH:
            raise Exception(
                f"Vector length {current_length} not supported. Max length must be <= {VECTOR_LENGTH}"
            )
        return vector

    @staticmethod
    def _is_model_aware(item: VectorItem) -> bool:
        """A model-aware write carries registry provenance (embedding_model_id)."""
        return bool(item.get("embedding_model_id"))

    @staticmethod
    def _provenance_kwargs(item: VectorItem, now: int) -> dict:
        """Provenance columns written alongside model-aware vectors."""
        return {
            "admin_id": item.get("admin_id"),
            "embedding_model_id": item.get("embedding_model_id"),
            "file_id": item.get("file_id"),
            "knowledge_id": item.get("knowledge_id"),
            "rag_chunk_id": item.get("rag_chunk_id"),
            "modality": item.get("modality") or "text",
            "embedding_status": item.get("embedding_status") or "active",
            "provenance_status": "attributed",
            "created_at": now,
            "updated_at": now,
        }

    def insert(self, collection_name: str, items: List[VectorItem]) -> None:
        log.info("[PGVECTOR] insert START | collection=%s | items_count=%s", collection_name, len(items))
        try:
            now = int(time.time())
            new_items = []
            for item in items:
                # Model-aware writes are validated to the exact table dimension
                # upstream; never pad or truncate them. Legacy writes pad.
                vector = (
                    item["vector"]
                    if self._is_model_aware(item)
                    else self.adjust_vector_length(item["vector"])
                )
                kwargs = {
                    "id": item["id"],
                    "vector": vector,
                    "collection_name": collection_name,
                    "text": item["text"],
                    "vmetadata": item["metadata"],
                }
                if self._is_model_aware(item):
                    kwargs.update(self._provenance_kwargs(item, now))
                new_items.append(DocumentChunk(**kwargs))
            self.session.bulk_save_objects(new_items)
            self.session.commit()
            log.info("[PGVECTOR] insert SUCCESS | collection=%s | inserted=%s", collection_name, len(new_items))
        except Exception as e:
            self.session.rollback()
            log.exception(f"Error during insert: {e}")
            raise

    def upsert(self, collection_name: str, items: List[VectorItem]) -> None:
        log.info("[PGVECTOR] upsert START | collection=%s | items_count=%s", collection_name, len(items))
        try:
            now = int(time.time())
            for item in items:
                vector = (
                    item["vector"]
                    if self._is_model_aware(item)
                    else self.adjust_vector_length(item["vector"])
                )
                existing = (
                    self.session.query(DocumentChunk)
                    .filter(DocumentChunk.id == item["id"])
                    .first()
                )
                if existing:
                    existing.vector = vector
                    existing.text = item["text"]
                    existing.vmetadata = item["metadata"]
                    existing.collection_name = (
                        collection_name  # Update collection_name if necessary
                    )
                    if self._is_model_aware(item):
                        for key, value in self._provenance_kwargs(item, now).items():
                            setattr(existing, key, value)
                else:
                    kwargs = {
                        "id": item["id"],
                        "vector": vector,
                        "collection_name": collection_name,
                        "text": item["text"],
                        "vmetadata": item["metadata"],
                    }
                    if self._is_model_aware(item):
                        kwargs.update(self._provenance_kwargs(item, now))
                    self.session.add(DocumentChunk(**kwargs))
            self.session.commit()
            log.info("[PGVECTOR] upsert SUCCESS | collection=%s | upserted=%s", collection_name, len(items))
        except Exception as e:
            self.session.rollback()
            log.exception(f"Error during upsert: {e}")
            raise

    def search(
        self,
        collection_name: str,
        vectors: List[List[float]],
        limit: Optional[int] = None,
    ) -> Optional[SearchResult]:
        log.info("[PGVECTOR] search START | collection=%s | vectors_count=%s | limit=%s", collection_name, len(vectors) if vectors else 0, limit)
        try:
            if not vectors:
                log.info("[PGVECTOR] search EMPTY | collection=%s | reason=no_vectors", collection_name)
                return None

            # Adjust query vectors to VECTOR_LENGTH
            vectors = [self.adjust_vector_length(vector) for vector in vectors]
            num_queries = len(vectors)

            def vector_expr(vector):
                return cast(array(vector), Vector(VECTOR_LENGTH))

            # Create the values for query vectors
            qid_col = column("qid", Integer)
            q_vector_col = column("q_vector", Vector(VECTOR_LENGTH))
            query_vectors = (
                values(qid_col, q_vector_col)
                .data(
                    [(idx, vector_expr(vector)) for idx, vector in enumerate(vectors)]
                )
                .alias("query_vectors")
            )

            # Build the lateral subquery for each query vector
            subq = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.text,
                    DocumentChunk.vmetadata,
                    (
                        DocumentChunk.vector.cosine_distance(query_vectors.c.q_vector)
                    ).label("distance"),
                )
                .where(DocumentChunk.collection_name == collection_name)
                .order_by(
                    (DocumentChunk.vector.cosine_distance(query_vectors.c.q_vector))
                )
            )
            if limit is not None:
                subq = subq.limit(limit)
            subq = subq.lateral("result")

            # Build the main query by joining query_vectors and the lateral subquery
            stmt = (
                select(
                    query_vectors.c.qid,
                    subq.c.id,
                    subq.c.text,
                    subq.c.vmetadata,
                    subq.c.distance,
                )
                .select_from(query_vectors)
                .join(subq, true())
                .order_by(query_vectors.c.qid, subq.c.distance)
            )

            result_proxy = self.session.execute(stmt)
            results = result_proxy.all()

            ids = [[] for _ in range(num_queries)]
            distances = [[] for _ in range(num_queries)]
            documents = [[] for _ in range(num_queries)]
            metadatas = [[] for _ in range(num_queries)]

            if not results:
                log.info("[PGVECTOR] search SUCCESS | collection=%s | num_queries=%s | results_total=0", collection_name, num_queries)
                return SearchResult(
                    ids=ids,
                    distances=distances,
                    documents=documents,
                    metadatas=metadatas,
                )

            for row in results:
                qid = int(row.qid)
                ids[qid].append(row.id)
                distances[qid].append(row.distance)
                documents[qid].append(row.text)
                metadatas[qid].append(row.vmetadata)

            total_hits = sum(len(d) for d in documents)
            log.info("[PGVECTOR] search SUCCESS | collection=%s | num_queries=%s | results_total=%s", collection_name, num_queries, total_hits)
            return SearchResult(
                ids=ids, distances=distances, documents=documents, metadatas=metadatas
            )
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            log.exception(f"Error during search: {e}")
            return None

    def search_model_aware(
        self,
        collection_name: str,
        vectors: List[List[float]],
        admin_id: str,
        embedding_model_id: str,
        limit: Optional[int] = None,
        knowledge_ids: Optional[List[str]] = None,
        file_ids: Optional[List[str]] = None,
    ) -> Optional[SearchResult]:
        """Cosine search restricted to one admin/model provenance space.

        Adds admin_id and embedding_model_id filters on top of the collection
        name so a query can never match vectors from another admin context or
        another embedding model. Optional knowledge_ids/file_ids further scope
        the RBAC-authorized result set (OR semantics). Query vectors are never
        padded because they are validated to the exact dimension upstream.
        """
        log.info(
            "[PGVECTOR] search_model_aware START | collection=%s | admin=%s | model=%s | vectors=%s | limit=%s",
            collection_name,
            admin_id,
            embedding_model_id,
            len(vectors) if vectors else 0,
            limit,
        )
        try:
            if not vectors:
                log.info(
                    "[PGVECTOR] search_model_aware EMPTY | collection=%s | reason=no_vectors",
                    collection_name,
                )
                return None

            num_queries = len(vectors)

            def vector_expr(vector):
                return cast(array(vector), Vector(VECTOR_LENGTH))

            qid_col = column("qid", Integer)
            q_vector_col = column("q_vector", Vector(VECTOR_LENGTH))
            query_vectors = (
                values(qid_col, q_vector_col)
                .data(
                    [(idx, vector_expr(vector)) for idx, vector in enumerate(vectors)]
                )
                .alias("query_vectors")
            )

            distance = DocumentChunk.vector.cosine_distance(query_vectors.c.q_vector)

            subq = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.text,
                    DocumentChunk.vmetadata,
                    distance.label("distance"),
                )
                .where(DocumentChunk.collection_name == collection_name)
                .where(DocumentChunk.admin_id == admin_id)
                .where(DocumentChunk.embedding_model_id == embedding_model_id)
            )

            scope_clauses = []
            if knowledge_ids:
                scope_clauses.append(DocumentChunk.knowledge_id.in_(knowledge_ids))
            if file_ids:
                scope_clauses.append(DocumentChunk.file_id.in_(file_ids))
            if scope_clauses:
                subq = subq.where(or_(*scope_clauses))

            subq = subq.order_by(distance)
            if limit is not None:
                subq = subq.limit(limit)
            subq = subq.lateral("result")

            stmt = (
                select(
                    query_vectors.c.qid,
                    subq.c.id,
                    subq.c.text,
                    subq.c.vmetadata,
                    subq.c.distance,
                )
                .select_from(query_vectors)
                .join(subq, true())
                .order_by(query_vectors.c.qid, subq.c.distance)
            )

            results = self.session.execute(stmt).all()

            ids = [[] for _ in range(num_queries)]
            distances = [[] for _ in range(num_queries)]
            documents = [[] for _ in range(num_queries)]
            metadatas = [[] for _ in range(num_queries)]

            if not results:
                log.info(
                    "[PGVECTOR] search_model_aware SUCCESS | collection=%s | results_total=0",
                    collection_name,
                )
                return SearchResult(
                    ids=ids,
                    distances=distances,
                    documents=documents,
                    metadatas=metadatas,
                )

            for row in results:
                qid = int(row.qid)
                ids[qid].append(row.id)
                distances[qid].append(row.distance)
                documents[qid].append(row.text)
                metadatas[qid].append(row.vmetadata)

            total_hits = sum(len(d) for d in documents)
            log.info(
                "[PGVECTOR] search_model_aware SUCCESS | collection=%s | results_total=%s",
                collection_name,
                total_hits,
            )
            return SearchResult(
                ids=ids, distances=distances, documents=documents, metadatas=metadatas
            )
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            log.exception(f"Error during model-aware search: {e}")
            return None

    def query(
        self, collection_name: str, filter: Dict[str, Any], limit: Optional[int] = None
    ) -> Optional[GetResult]:
        log.info("[PGVECTOR] query START | collection=%s | filter=%s | limit=%s", collection_name, filter, limit)
        try:
            query = self.session.query(DocumentChunk).filter(
                DocumentChunk.collection_name == collection_name
            )

            for key, value in filter.items():
                query = query.filter(DocumentChunk.vmetadata[key].astext == str(value))

            if limit is not None:
                query = query.limit(limit)

            results = query.all()

            if not results:
                log.info("[PGVECTOR] query EMPTY | collection=%s | filter=%s", collection_name, filter)
                return None

            ids = [[result.id for result in results]]
            documents = [[result.text for result in results]]
            metadatas = [[result.vmetadata for result in results]]

            log.info("[PGVECTOR] query SUCCESS | collection=%s | results_count=%s", collection_name, len(results))
            return GetResult(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            log.exception(f"Error during query: {e}")
            return None

    def get(
        self, collection_name: str, limit: Optional[int] = None
    ) -> Optional[GetResult]:
        log.info("[PGVECTOR] get START | collection=%s | limit=%s", collection_name, limit)
        try:
            query = self.session.query(DocumentChunk).filter(
                DocumentChunk.collection_name == collection_name
            )
            if limit is not None:
                query = query.limit(limit)

            results = query.all()

            if not results:
                log.info("[PGVECTOR] get EMPTY | collection=%s", collection_name)
                return None

            ids = [[result.id for result in results]]
            documents = [[result.text for result in results]]
            metadatas = [[result.vmetadata for result in results]]

            log.info("[PGVECTOR] get SUCCESS | collection=%s | results_count=%s", collection_name, len(results))
            return GetResult(ids=ids, documents=documents, metadatas=metadatas)
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            log.exception(f"Error during get: {e}")
            return None

    def delete(
        self,
        collection_name: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
    ) -> None:
        log.info("[PGVECTOR] delete START | collection=%s | ids_count=%s | filter=%s", collection_name, len(ids) if ids else 0, filter)
        try:
            query = self.session.query(DocumentChunk).filter(
                DocumentChunk.collection_name == collection_name
            )
            if ids:
                query = query.filter(DocumentChunk.id.in_(ids))
            if filter:
                for key, value in filter.items():
                    query = query.filter(
                        DocumentChunk.vmetadata[key].astext == str(value)
                    )
            deleted = query.delete(synchronize_session=False)
            self.session.commit()
            log.info("[PGVECTOR] delete SUCCESS | collection=%s | deleted=%s", collection_name, deleted)
        except Exception as e:
            self.session.rollback()
            log.exception(f"Error during delete: {e}")
            raise

    def reset(self) -> None:
        log.info("[PGVECTOR] reset START")
        try:
            deleted = self.session.query(DocumentChunk).delete()
            self.session.commit()
            log.info("[PGVECTOR] reset SUCCESS | deleted=%s", deleted)
        except Exception as e:
            self.session.rollback()
            log.exception(f"Error during reset: {e}")
            raise

    def close(self) -> None:
        pass

    def has_collection(self, collection_name: str) -> bool:
        log.info("[PGVECTOR] has_collection START | collection=%s", collection_name)
        try:
            exists = (
                self.session.query(DocumentChunk)
                .filter(DocumentChunk.collection_name == collection_name)
                .first()
                is not None
            )
            log.info("[PGVECTOR] has_collection SUCCESS | collection=%s | exists=%s", collection_name, exists)
            return exists
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            log.exception(f"Error checking collection existence: {e}")
            return False

    def delete_collection(self, collection_name: str) -> None:
        log.info("[PGVECTOR] delete_collection START | collection=%s", collection_name)
        self.delete(collection_name)
        log.info("[PGVECTOR] delete_collection SUCCESS | collection=%s", collection_name)
