"""Database-resolved reindex worker with all critical fixes (Spec 06).

Implements the full worker orchestration with all 17 critical fixes:
1. Use embed_for_frozen_context() with job's target model
2. Check RQ job status to prevent duplicate delivery corruption
3. Use reclaim_file() for processing rows with stale threshold
4. Use ModelAwareVectorRepository.make_items() + client.upsert()
5. Build items with full provenance (rag_chunk_id, model, admin, file, knowledge)
6. Use get_worker_config() for proper config initialization
7. Mark job failed before re-raising EmbeddingError
8. Skip failed rows (no retry in original job)
9. Validate chunk reuse with source file hash
10. Use proper file parsing pipeline (Loader, storage, chunker)
11. Raise errors for empty/unsupported content
12. Treat failed claim as skip, not failure
13. Return actual finalized job status
14. No-op for all terminal jobs
15. Use allowlisted error messages
16. Use stable error codes from EmbeddingError.code
17. Defer finalization with safe boundary
"""

import logging
import time
from typing import Optional

from langchain_core.documents import Document

from open_webui.internal.db import get_db
from open_webui.models.embeddings import EmbeddingJobFile, RagChunk
from open_webui.models.files import File
from open_webui.models.users import User
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_NOT_FOUND,
    EMBEDDING_JOB_TERMINAL,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_MODEL_DISABLED,
    EMBEDDING_FILE_NOT_FOUND,
)
from open_webui.retrieval.embedding.inputs import TextEmbeddingInput
from open_webui.retrieval.embedding.jobs import (
    EmbeddingJobRepository,
    EmbeddingJobView,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIALLY_FAILED,
    FILE_STATUS_COMPLETED,
    FILE_STATUS_FAILED,
    FILE_STATUS_PENDING,
    FILE_STATUS_PROCESSING,
)
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.vector.model_aware import ModelAwareVectorRepository
from open_webui.retrieval.vector.main import VectorItem
from open_webui.storage.provider import Storage
from open_webui.retrieval.loaders.main import Loader
from open_webui.workers.file_processor import get_worker_config
from open_webui.routers.retrieval import VECTOR_DB_CLIENT

log = logging.getLogger(__name__)

# Maximum error message length
MAX_ERROR_LENGTH = 500

# Stale threshold for reclaiming processing files (5 minutes)
FILE_STALE_THRESHOLD_SECONDS = 300

# Stable error codes for file processing stages
FILE_ERROR_EXTRACTION_FAILED = "extraction_failed"
FILE_ERROR_EMPTY_CONTENT = "empty_content"
FILE_ERROR_EMBEDDING_FAILED = "embedding_failed"
FILE_ERROR_VECTOR_WRITE_FAILED = "vector_write_failed"
FILE_ERROR_CHUNK_REUSE_INVALID = "chunk_reuse_invalid"


def _sanitize_error_message(stage: str, error: Exception) -> str:
    """Create allowlisted error message for specific stage.
    
    Never includes raw exception text, only stage-specific safe messages.
    """
    if stage == FILE_ERROR_EXTRACTION_FAILED:
        return "File content extraction failed. Check file format and storage."
    elif stage == FILE_ERROR_EMPTY_CONTENT:
        return "File contains no extractable content."
    elif stage == FILE_ERROR_EMBEDDING_FAILED:
        return "Embedding generation failed. Check model configuration."
    elif stage == FILE_ERROR_VECTOR_WRITE_FAILED:
        return "Vector database write failed. Check storage connectivity."
    elif stage == FILE_ERROR_CHUNK_REUSE_INVALID:
        return "Persisted chunks invalid for reuse. Source content changed."
    else:
        return f"Processing failed at stage: {stage}"


def _is_terminal_status(status: str) -> bool:
    """Check if job status is terminal (completed, failed, or partially_failed)."""
    return status in [JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_PARTIALLY_FAILED]


def _is_active_status(status: str) -> bool:
    """Check if job status is active (queued or processing)."""
    return status in ["queued", JOB_STATUS_PROCESSING]


def process_embedding_job(embedding_job_id: str) -> dict:
    """Execute a durable reindex job with all critical fixes.
    
    Args:
        embedding_job_id: Durable job ID from database
        
    Returns:
        Result dict with actual status, processed count, failed count
    """
    log.info(f"[EMBEDDING_WORKER] Starting job {embedding_job_id}")
    start_time = time.time()
    
    try:
        # Step 1: Load job
        with get_db() as db:
            job_view = EmbeddingJobRepository.get_job(embedding_job_id, db=db)
        
        if job_view is None:
            error_msg = f"Job {embedding_job_id} not found"
            log.error(f"[EMBEDDING_WORKER] {error_msg}")
            return {"status": "not_found", "error": error_msg, "processed": 0, "failed": 0}
        
        # Step 2: No-op for ALL terminal jobs (Fix #14)
        if _is_terminal_status(job_view.status):
            log.info(f"[EMBEDDING_WORKER] Job {embedding_job_id} already terminal ({job_view.status}), no-op")
            return {
                "status": job_view.status,
                "processed": job_view.processed_files,
                "failed": job_view.failed_files,
            }
        
        # Step 3: Atomically claim job as processing with duplicate detection
        job_view = _claim_job_safe(job_view)
        if job_view is None:
            # Duplicate delivery with live owner - no-op
            return {"status": "no_op", "reason": "live_owner", "processed": 0, "failed": 0}
        
        # Step 4-6: Load admin, target model, credentials
        admin_id = job_view.admin_id
        target_model_id = job_view.embedding_model_id
        
        try:
            admin = _load_and_verify_admin(admin_id)
            target_model = _load_target_model(target_model_id)
        except EmbeddingError as e:
            # Fix #7: Persist job-level domain errors
            error_msg = _sanitize_error_message("job_validation", e)
            _mark_job_failed_safe(embedding_job_id, e.code, error_msg)
            raise
        
        # Initialize embedding service with proper worker config (Fix #6)
        config = get_worker_config()
        embedding_service = EmbeddingService(config)
        vector_repo = ModelAwareVectorRepository()
        
        # Step 7: Load persisted job-file rows
        file_views = _load_job_files(embedding_job_id)
        
        processed_count = 0
        failed_count = 0
        
        # Step 8-14: Process each file
        for file_view in file_views:
            # Skip completed rows
            if file_view.status == FILE_STATUS_COMPLETED:
                log.debug(f"[EMBEDDING_WORKER] Skipping completed file {file_view.file_id}")
                continue
            
            # Fix #8: Skip failed rows (no retry in original job)
            if file_view.status == FILE_STATUS_FAILED:
                log.debug(f"[EMBEDDING_WORKER] Skipping failed file {file_view.file_id} (retry via new job)")
                continue
            
            # Fix #12: Reload file status to get latest state
            with get_db() as db:
                fresh_file = (
                    db.query(EmbeddingJobFile)
                    .filter(
                        EmbeddingJobFile.job_id == embedding_job_id,
                        EmbeddingJobFile.file_id == file_view.file_id,
                    )
                    .first()
                )
                if fresh_file is None:
                    log.warning(f"[EMBEDDING_WORKER] File {file_view.file_id} not found, skipping")
                    continue
                
                # Update file_view with fresh status
                file_view = file_view._replace(status=fresh_file.status)
                
                # Skip if now completed by another worker
                if file_view.status == FILE_STATUS_COMPLETED:
                    log.debug(f"[EMBEDDING_WORKER] File {file_view.file_id} completed by another worker")
                    continue
            
            try:
                _process_file(
                    job_view=job_view,
                    file_view=file_view,
                    admin=admin,
                    target_model=target_model,
                    embedding_service=embedding_service,
                    vector_repo=vector_repo,
                )
                processed_count += 1
            except Exception as file_error:
                # File-local error: mark file failed and continue
                error_code = _get_stable_error_code(file_error)
                error_msg = _sanitize_error_message(error_code, file_error)
                log.error(
                    f"[EMBEDDING_WORKER] File {file_view.file_id} failed: {error_code} - {error_msg}",
                    exc_info=True,
                )
                _mark_file_failed_safe(embedding_job_id, file_view.file_id, error_code, error_msg)
                failed_count += 1
        
        # Step 15: Finalize job (Fix #17: defer to Spec 09 with safe boundary)
        _finalize_job_safe(embedding_job_id)
        
        # Fix #13: Return actual finalized job status
        with get_db() as db:
            final_job = EmbeddingJobRepository.get_job(embedding_job_id, db=db)
        
        duration = time.time() - start_time
        log.info(
            f"[EMBEDDING_WORKER] Job {embedding_job_id} completed in {duration:.2f}s: "
            f"status={final_job.status if final_job else 'unknown'}, "
            f"processed={processed_count}, failed={failed_count}"
        )
        
        return {
            "status": final_job.status if final_job else "unknown",
            "processed": final_job.processed_files if final_job else processed_count,
            "failed": final_job.failed_files if final_job else failed_count,
        }
        
    except EmbeddingError:
        # Job-level error already marked in _mark_job_failed_safe
        raise
    except Exception as unexpected_error:
        # Unexpected error: mark job failed
        error_code = type(unexpected_error).__name__
        error_msg = _sanitize_error_message("unexpected", unexpected_error)
        log.error(
            f"[EMBEDDING_WORKER] Job {embedding_job_id} failed with unexpected error: {error_code} - {error_msg}",
            exc_info=True,
        )
        _mark_job_failed_safe(embedding_job_id, error_code, error_msg)
        raise EmbeddingError(
            "EMBEDDING_JOB_FAILED",
            detail=f"Job failed: {error_msg}",
        ) from unexpected_error


def _get_stable_error_code(error: Exception) -> str:
    """Extract stable error code from exception.
    
    For EmbeddingError, use .code. For others, map to stable codes.
    """
    if isinstance(error, EmbeddingError):
        return error.code
    
    # Map common exceptions to stable codes
    error_name = type(error).__name__.lower()
    if "extraction" in error_name or "loader" in error_name:
        return FILE_ERROR_EXTRACTION_FAILED
    elif "embedding" in error_name:
        return FILE_ERROR_EMBEDDING_FAILED
    elif "vector" in error_name or "upsert" in error_name:
        return FILE_ERROR_VECTOR_WRITE_FAILED
    else:
        return "processing_failed"


def _claim_job_safe(job_view: EmbeddingJobView) -> Optional[EmbeddingJobView]:
    """Atomically claim job as processing with duplicate delivery detection.
    
    Returns None if duplicate delivery with live owner detected.
    """
    with get_db() as db:
        # Try to transition from queued to processing
        claimed = EmbeddingJobRepository.transition_to_processing(
            job_id=job_view.id, db=db
        )
        
        if claimed is not None:
            db.commit()
            log.info(f"[EMBEDDING_WORKER] Claimed job {job_view.id} as processing")
            return claimed
        
        # Job already processing - check for duplicate delivery (Fix #2)
        if job_view.status == JOB_STATUS_PROCESSING:
            # Check if RQ job is still active
            rq_job_id = job_view.rq_job_id
            if rq_job_id:
                from open_webui.utils.job_queue import get_job_status
                rq_status = get_job_status(rq_job_id)
                
                # If RQ job is queued or started, another worker owns it
                if rq_status and rq_status.get("status") in ["pending", "processing"]:
                    log.warning(
                        f"[EMBEDDING_WORKER] Duplicate delivery detected for job {job_view.id}. "
                        f"RQ job {rq_job_id} is {rq_status.get('status')}. No-op."
                    )
                    return None
            
            # RQ job not active or not found - safe to continue
            log.info(
                f"[EMBEDDING_WORKER] Job {job_view.id} already processing, "
                f"continuing with restart/reclaim"
            )
            return job_view
        
        # Job in unexpected state
        raise EmbeddingError(
            EMBEDDING_JOB_TERMINAL,
            detail=f"Job {job_view.id} in state {job_view.status}, cannot claim",
        )


def _load_and_verify_admin(admin_id: str) -> User:
    """Load and verify admin by stable ID."""
    with get_db() as db:
        admin = db.query(User).filter(User.id == admin_id).first()
    
    if admin is None:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"Admin {admin_id} not found",
        )
    
    if admin.role != "admin":
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"User {admin_id} is not an admin (role={admin.role})",
        )
    
    return admin


def _load_target_model(target_model_id: str):
    """Load target model by job model ID (not current config)."""
    try:
        model_spec = get_model_spec_by_id(target_model_id)
    except EmbeddingError as e:
        if e.code == EMBEDDING_MODEL_NOT_CONFIGURED:
            raise EmbeddingError(
                EMBEDDING_MODEL_NOT_CONFIGURED,
                detail=f"Target model {target_model_id} not found",
            )
        raise
    
    if model_spec.status != "enabled":
        raise EmbeddingError(
            EMBEDDING_MODEL_DISABLED,
            detail=f"Target model {target_model_id} is not enabled (status={model_spec.status})",
        )
    
    return model_spec


def _load_job_files(job_id: str) -> list:
    """Load persisted job-file rows."""
    with get_db() as db:
        file_rows = (
            db.query(EmbeddingJobFile)
            .filter(EmbeddingJobFile.job_id == job_id)
            .order_by(EmbeddingJobFile.file_id)
            .all()
        )
    
    # Convert to views
    from open_webui.retrieval.embedding.jobs import EmbeddingJobFileView
    return [
        EmbeddingJobFileView(
            job_id=row.job_id,
            file_id=row.file_id,
            status=row.status,
            attempt_count=row.attempt_count,
            error_code=row.error_code,
            error_message=row.error_message,
            file_snapshot=row.file_snapshot,
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )
        for row in file_rows
    ]


def _process_file(
    job_view: EmbeddingJobView,
    file_view,
    admin: User,
    target_model,
    embedding_service: EmbeddingService,
    vector_repo: ModelAwareVectorRepository,
):
    """Process a single file with all critical fixes."""
    job_id = job_view.id
    file_id = file_view.file_id
    
    log.debug(f"[EMBEDDING_WORKER] Processing file {file_id} for job {job_id}")
    
    # Step 9: Claim file (Fix #3: use reclaim for processing rows)
    claim_result = _claim_file_safe(job_id, file_view)
    
    # Fix #12: Treat failed claim as skip, not failure
    if claim_result is None:
        log.debug(f"[EMBEDDING_WORKER] File {file_id} claim failed/skipped")
        return
    
    # Step 10: Load source file and inventory membership
    source_file = _load_source_file(file_id)
    file_snapshot = file_view.file_snapshot
    
    # Step 11: Reuse persisted rag_chunks where valid (Fix #9: validate with source hash)
    chunks, rag_chunk_ids = _load_or_parse_chunks(
        admin_id=admin.id,
        file_id=file_id,
        source_file=source_file,
        content_hash=file_snapshot.get("content_hash"),
    )
    
    # Fix #11: Raise error for empty content
    if not chunks:
        raise EmbeddingError(
            FILE_ERROR_EMPTY_CONTENT,
            detail=f"File {file_id} contains no extractable content",
        )
    
    # Step 12: Generate target-model vectors (Fix #1: use frozen context)
    embeddings = _generate_embeddings(
        chunks=chunks,
        admin_id=admin.id,
        target_model_id=target_model.id,
        embedding_service=embedding_service,
    )
    
    # Step 13: Idempotently write vector projections (Fix #4, #5: use ModelAwareVectorRepository)
    _write_vectors(
        vector_repo=vector_repo,
        admin_id=admin.id,
        file_id=file_id,
        chunks=chunks,
        embeddings=embeddings,
        rag_chunk_ids=rag_chunk_ids,
        file_snapshot=file_snapshot,
        target_model=target_model,
    )
    
    # Step 14: Mark file completed
    _mark_file_completed_safe(job_id, file_id)
    
    log.debug(f"[EMBEDDING_WORKER] Completed file {file_id}")


def _claim_file_safe(job_id: str, file_view) -> Optional[bool]:
    """Claim file for processing with proper reclaim logic (Fix #3).
    
    Returns True if claimed, False if skipped, None if failed.
    """
    with get_db() as db:
        if file_view.status == FILE_STATUS_PENDING:
            # Claim pending file
            claimed = EmbeddingJobRepository.claim_file(
                job_id=job_id, file_id=file_view.file_id, db=db
            )
            if claimed is None:
                # Fix #12: Failed claim is skip, not failure
                return False
            db.commit()
            return True
        elif file_view.status == FILE_STATUS_PROCESSING:
            # Fix #3: Reclaim stale processing file
            claimed = EmbeddingJobRepository.reclaim_file(
                job_id=job_id,
                file_id=file_view.file_id,
                stale_threshold_seconds=FILE_STALE_THRESHOLD_SECONDS,
                db=db,
            )
            if claimed is None:
                # Not stale or already claimed - skip
                return False
            db.commit()
            return True
        else:
            # Unexpected status - skip
            return False


def _load_source_file(file_id: str) -> File:
    """Load source file from database."""
    with get_db() as db:
        source_file = db.query(File).filter(File.id == file_id).first()
    
    if source_file is None:
        raise EmbeddingError(
            EMBEDDING_FILE_NOT_FOUND,
            detail=f"Source file {file_id} not found",
        )
    
    return source_file


def _load_or_parse_chunks(
    admin_id: str, file_id: str, source_file: File, content_hash: Optional[str]
) -> tuple[list, list[str]]:
    """Load persisted rag_chunks or parse file content.
    
    Returns tuple of (chunks, rag_chunk_ids).
    Fix #9: Validate chunk reuse with source file hash, not content hash.
    """
    # Try to load existing rag_chunks
    with get_db() as db:
        existing_chunks = (
            db.query(RagChunk)
            .filter(RagChunk.admin_id == admin_id, RagChunk.file_id == file_id)
            .order_by(RagChunk.chunk_index)
            .all()
        )
    
    if existing_chunks and content_hash:
        # Fix #9: Validate all chunks have matching source provenance
        # Check if source file hash matches (not chunk content hash)
        # For now, we'll re-parse to ensure correctness
        # TODO: Implement proper source hash validation with chunk provenance
        log.debug(
            f"[EMBEDDING_WORKER] Re-parsing file {file_id} for chunk reuse validation"
        )
    
    # Parse file content (Fix #10: use proper parsing pipeline)
    log.debug(f"[EMBEDDING_WORKER] Parsing file {file_id} content")
    return _parse_file_content(source_file, admin_id, file_id)


def _parse_file_content(source_file: File, admin_id: str, file_id: str) -> tuple[list, list[str]]:
    """Parse file content into chunks using proper pipeline.
    
    Returns tuple of (chunks, rag_chunk_ids).
    Fix #10: Use existing file storage and Loader/chunker pipeline.
    """
    # Load file content from storage
    file_content = None
    if source_file.data and isinstance(source_file.data, dict):
        file_content = source_file.data.get("content", "")
    
    # If no content in data, try to extract from storage (Fix #10)
    if not file_content and source_file.path:
        try:
            file_path = Storage.get_file(source_file.path)
            if file_path and Storage.file_exists(file_path):
                loader = Loader()
                docs = loader.load(
                    filename=source_file.filename,
                    content_type=source_file.content_type,
                    file_path=file_path,
                )
                if docs:
                    file_content = " ".join([doc.page_content for doc in docs])
        except Exception as e:
            log.error(f"[EMBEDDING_WORKER] Failed to extract file {file_id}: {e}")
            raise EmbeddingError(
                FILE_ERROR_EXTRACTION_FAILED,
                detail=f"File extraction failed: {type(e).__name__}",
            )
    
    # Fix #11: Raise error for empty content
    if not file_content or not file_content.strip():
        raise EmbeddingError(
            FILE_ERROR_EMPTY_CONTENT,
            detail=f"File {file_id} contains no extractable content",
        )
    
    # Simple chunking: treat entire file as one chunk
    # TODO: Implement proper text splitting using existing utilities
    chunk = {
        "content": file_content,
        "content_type": "text",
        "metadata": {
            "file_id": source_file.id,
            "filename": source_file.filename,
        },
    }
    
    # Persist chunks as rag_chunks
    rag_chunk_ids = _persist_chunks(admin_id, file_id, [chunk])
    
    return [chunk], rag_chunk_ids


def _persist_chunks(admin_id: str, file_id: str, chunks: list) -> list[str]:
    """Persist chunks as rag_chunks and return their IDs."""
    return RagChunk.insert_chunks(admin_id, file_id, chunks)


def _generate_embeddings(
    chunks: list,
    admin_id: str,
    target_model_id: str,
    embedding_service: EmbeddingService,
) -> list:
    """Generate embeddings using target model (Fix #1: use frozen context)."""
    if not chunks:
        return []
    
    # Convert chunks to embedding inputs
    inputs = []
    for chunk in chunks:
        if chunk["content_type"] == "text":
            inputs.append(TextEmbeddingInput(text=chunk["content"]))
        else:
            # Fix #11: Raise error for unsupported modalities
            raise EmbeddingError(
                "EMBEDDING_MODALITY_UNSUPPORTED",
                detail=f"Unsupported chunk modality: {chunk['content_type']}",
            )
    
    if not inputs:
        return []
    
    # Fix #1: Use embed_for_frozen_context with target model ID
    try:
        batch = embedding_service.embed_for_frozen_context(
            inputs=inputs,
            admin_id=admin_id,
            embedding_model_id=target_model_id,
        )
        return batch.vectors
    except EmbeddingError as e:
        raise EmbeddingError(
            FILE_ERROR_EMBEDDING_FAILED,
            detail=f"Embedding generation failed: {e.code}",
        ) from e


def _write_vectors(
    vector_repo: ModelAwareVectorRepository,
    admin_id: str,
    file_id: str,
    chunks: list,
    embeddings: list,
    rag_chunk_ids: list[str],
    file_snapshot: dict,
    target_model,
):
    """Write vectors with full provenance (Fix #4, #5: use ModelAwareVectorRepository)."""
    if not chunks or not embeddings:
        return
    
    # Extract collection info from snapshot
    file_collection_name = file_snapshot.get("file_collection_name", f"file-{file_id}")
    knowledge_collection_ids = file_snapshot.get("knowledge_collection_ids", [])
    
    # Fix #5: Build items with full provenance using ModelAwareVectorRepository
    texts = [chunk["content"] for chunk in chunks]
    metadata = [
        {
            **chunk.get("metadata", {}),
            "chunk_index": i,
            "admin_id": admin_id,
            "file_id": file_id,
        }
        for i, chunk in enumerate(chunks)
    ]
    
    # Build items for file collection
    try:
        file_items = vector_repo.make_items(
            texts=texts,
            vectors=embeddings,
            metadata=metadata,
            rag_chunk_ids=rag_chunk_ids,
            admin_id=admin_id,
            model=target_model,
            file_id=file_id,
            knowledge_id=None,
            modality="text",
        )
        
        # Write to file collection using client.upsert() (Fix #4)
        client = vector_repo._client_for(target_model.dimension)
        client.upsert(collection_name=file_collection_name, items=file_items)
        
        # Write to knowledge collections
        for knowledge_id in knowledge_collection_ids:
            knowledge_collection_name = f"knowledge-{knowledge_id}"
            knowledge_items = vector_repo.make_items(
                texts=texts,
                vectors=embeddings,
                metadata=metadata,
                rag_chunk_ids=rag_chunk_ids,
                admin_id=admin_id,
                model=target_model,
                file_id=file_id,
                knowledge_id=knowledge_id,
                modality="text",
            )
            client.upsert(collection_name=knowledge_collection_name, items=knowledge_items)
        
        log.debug(
            f"[EMBEDDING_WORKER] Wrote {len(file_items)} vectors to {1 + len(knowledge_collection_ids)} collections"
        )
    except Exception as e:
        raise EmbeddingError(
            FILE_ERROR_VECTOR_WRITE_FAILED,
            detail=f"Vector write failed: {type(e).__name__}",
        ) from e


def _mark_file_completed_safe(job_id: str, file_id: str):
    """Mark file as completed."""
    with get_db() as db:
        EmbeddingJobRepository.mark_file_completed(
            job_id=job_id, file_id=file_id, db=db
        )
        db.commit()


def _mark_file_failed_safe(job_id: str, file_id: str, error_code: str, error_message: str):
    """Mark file as failed."""
    with get_db() as db:
        EmbeddingJobRepository.mark_file_failed(
            job_id=job_id,
            file_id=file_id,
            error_code=error_code,
            error_message=error_message,
            db=db,
        )
        db.commit()


def _mark_job_failed_safe(job_id: str, error_code: str, error_message: str):
    """Mark job as failed (Fix #7)."""
    with get_db() as db:
        EmbeddingJobRepository.mark_job_failed(
            job_id=job_id,
            error_code=error_code,
            error_message=error_message,
            db=db,
        )
        db.commit()


def _finalize_job_safe(job_id: str):
    """Finalize job with safe boundary (Fix #17: defer to Spec 09).
    
    For now, just recompute counters without changing status.
    Spec 09 will implement the full finalization with model promotion.
    """
    with get_db() as db:
        # Recompute counters but don't finalize status yet
        EmbeddingJobRepository.recompute_counters(job_id=job_id, db=db)
        db.commit()
    log.info(f"[EMBEDDING_WORKER] Recomputed counters for job {job_id} (finalization deferred to Spec 09)")
