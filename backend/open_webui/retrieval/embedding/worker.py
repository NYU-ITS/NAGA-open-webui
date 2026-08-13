"""Database-resolved reindex worker with all critical fixes (Spec 06).

Implements the full worker orchestration with all 17 critical fixes:
1. Use embed_for_frozen_context() with job's target model
2. Check RQ job status to prevent duplicate delivery corruption
3. Use reclaim_file() for processing rows with stale threshold
4. Use ModelAwareVectorRepository.make_items() + reconcile_model_aware()
   - Build items with full provenance and a non-retrievable "building" status
   - Idempotent upsert keyed by (admin, model, rag_chunk_id, collection)
   - Transactional per-projection reconcile: stale target rows for the same
     (admin, model, file, collection) are deleted in the same transaction;
     other models/files/collections and shared rag_chunks are never touched
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
import hashlib
import os
import time
from dataclasses import replace
from typing import Optional

from open_webui.internal.db import get_db
from open_webui.models.embeddings import EmbeddingJob, EmbeddingJobFile, RagChunk
from open_webui.models.files import File
from open_webui.models.knowledge import Knowledge
from open_webui.models.users import User
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_JOB_NOT_FOUND,
    EMBEDDING_JOB_STALE_OPERATION,
    EMBEDDING_JOB_TERMINAL,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_ADMIN_AMBIGUOUS,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_MODEL_DISABLED,
    EMBEDDING_MODEL_STATE_CONFLICT,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_FILE_WRONG_STATUS,
    EMBEDDING_CREDENTIALS_MISSING,
    EMBEDDING_PROVIDER_FAILED,
    EMBEDDING_PROVIDER_UNSUPPORTED,
    EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_IMAGE_FORMAT_UNSUPPORTED,
    EMBEDDING_IMAGE_INVALID,
    PDF_VISUAL_EXTRACTION_FAILED,
    PDF_VISUAL_LIMIT_EXCEEDED,
    EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
    EMBEDDING_INVENTORY_MISSING_FILE,
    EMBEDDING_REINDEX_SOURCE_CHANGED,
)
from open_webui.retrieval.embedding.file_processing import (
    CONTENT_ORIGIN_STORED_SOURCE,
    read_stored_content_provenance,
    resolve_authoritative_content_provenance,
)
from open_webui.retrieval.embedding.preparation import (
    PreparedChunk,
    PreparedFile,
    PreparationRecipe,
    build_persisted_chunks,
    prepare_file_for_embedding,
    preparation_recipe_from_snapshot,
)
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
from open_webui.retrieval.embedding.inventory import source_sha256_for_file
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.vector.model_aware import (
    ModelAwareVectorRepository,
    VECTOR_STATUS_BUILDING,
)
from open_webui.storage.provider import Storage
from open_webui.workers.config import get_worker_config

log = logging.getLogger(__name__)

# Maximum error message length
MAX_ERROR_LENGTH = 500

# Stale threshold for reclaiming processing files (5 minutes)
FILE_STALE_THRESHOLD_SECONDS = 300

# Stable error codes for file processing stages (Spec 08 taxonomy).
# These are the only codes recorded on failed file rows; they distinguish the
# failing stage without exposing provider or credential details.
FILE_ERROR_FILE_MISSING = "file_missing"
FILE_ERROR_STORAGE_READ_FAILED = "storage_read_failed"
FILE_ERROR_EXTRACTION_FAILED = "extraction_failed"
FILE_ERROR_EMPTY_CONTENT = "empty_content"
FILE_ERROR_ADMIN_MODEL_RESOLUTION = "admin_model_resolution_failed"
FILE_ERROR_CREDENTIALS_MISSING = "credentials_missing"
FILE_ERROR_PROVIDER_EMBEDDING_FAILED = "provider_embedding_failed"
FILE_ERROR_EMBEDDING_FAILED = "embedding_failed"
FILE_ERROR_VECTOR_WRITE_FAILED = "vector_write_failed"
FILE_ERROR_OWNERSHIP_AMBIGUOUS = "ownership_ambiguity"
FILE_ERROR_STALE_CLAIM = "worker_interrupted"
FILE_ERROR_CHUNK_REUSE_INVALID = "chunk_reuse_invalid"
FILE_ERROR_PROCESSING_FAILED = "processing_failed"

# Maps stable EmbeddingError codes onto the file-level failure taxonomy so a
# failed file row records one of the Spec 08 categories. Codes not listed here
# (e.g. embedding_dimension_mismatch) are already stable and sanitized and pass
# through unchanged.
_EMBEDDING_CODE_MAP = {
    EMBEDDING_FILE_NOT_FOUND: FILE_ERROR_FILE_MISSING,
    EMBEDDING_INVENTORY_MISSING_FILE: FILE_ERROR_FILE_MISSING,
    EMBEDDING_ADMIN_UNRESOLVED: FILE_ERROR_ADMIN_MODEL_RESOLUTION,
    EMBEDDING_ADMIN_AMBIGUOUS: FILE_ERROR_ADMIN_MODEL_RESOLUTION,
    EMBEDDING_MODEL_NOT_CONFIGURED: FILE_ERROR_ADMIN_MODEL_RESOLUTION,
    EMBEDDING_MODEL_DISABLED: FILE_ERROR_ADMIN_MODEL_RESOLUTION,
    EMBEDDING_CREDENTIALS_MISSING: FILE_ERROR_CREDENTIALS_MISSING,
    EMBEDDING_PROVIDER_FAILED: EMBEDDING_PROVIDER_FAILED,
    EMBEDDING_PROVIDER_UNSUPPORTED: FILE_ERROR_PROVIDER_EMBEDDING_FAILED,
    EMBEDDING_MODALITY_UNSUPPORTED: EMBEDDING_MODALITY_UNSUPPORTED,
    EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE: FILE_ERROR_OWNERSHIP_AMBIGUOUS,
    EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN: FILE_ERROR_OWNERSHIP_AMBIGUOUS,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE: FILE_ERROR_OWNERSHIP_AMBIGUOUS,
    EMBEDDING_INVENTORY_MALFORMED_REFERENCE: FILE_ERROR_OWNERSHIP_AMBIGUOUS,
    EMBEDDING_FILE_WRONG_STATUS: FILE_ERROR_STALE_CLAIM,
    EMBEDDING_JOB_STALE_OPERATION: FILE_ERROR_STALE_CLAIM,
    EMBEDDING_MODEL_STATE_CONFLICT: FILE_ERROR_ADMIN_MODEL_RESOLUTION,
}

# Allowlisted human-readable operation labels per file error code. Unrecognized
# stable codes that start with "embedding_" are treated as an embedding request.
_FILE_OPERATION_LABELS = {
    FILE_ERROR_FILE_MISSING: "Embedding request failed",
    FILE_ERROR_STORAGE_READ_FAILED: "File storage read failed",
    FILE_ERROR_EXTRACTION_FAILED: "File content extraction failed",
    FILE_ERROR_EMPTY_CONTENT: "File content extraction failed",
    FILE_ERROR_ADMIN_MODEL_RESOLUTION: "Embedding request failed",
    FILE_ERROR_CREDENTIALS_MISSING: "Embedding request failed",
    FILE_ERROR_PROVIDER_EMBEDDING_FAILED: "Embedding request failed",
    FILE_ERROR_EMBEDDING_FAILED: "Embedding generation failed",
    FILE_ERROR_VECTOR_WRITE_FAILED: "Vector write failed",
    FILE_ERROR_OWNERSHIP_AMBIGUOUS: "Embedding request failed",
    FILE_ERROR_STALE_CLAIM: "Embedding request failed",
    FILE_ERROR_CHUNK_REUSE_INVALID: "Embedding request failed",
    FILE_ERROR_PROCESSING_FAILED: "Processing failed",
}

# Allowlisted, user-safe cause phrases per file error code. These never contain
# provider payloads, credentials, or stack traces.
_FILE_SAFE_CAUSES = {
    FILE_ERROR_FILE_MISSING: "the source file was not found",
    FILE_ERROR_STORAGE_READ_FAILED: "the source file could not be read from storage",
    FILE_ERROR_EXTRACTION_FAILED: "content extraction failed for the file format",
    FILE_ERROR_EMPTY_CONTENT: "the file contains no extractable content",
    FILE_ERROR_ADMIN_MODEL_RESOLUTION: "the embedding model or admin could not be resolved",
    FILE_ERROR_CREDENTIALS_MISSING: "embedding credentials are missing",
    FILE_ERROR_PROVIDER_EMBEDDING_FAILED: "the embedding provider request failed",
    FILE_ERROR_EMBEDDING_FAILED: "embedding generation failed",
    FILE_ERROR_VECTOR_WRITE_FAILED: "writing vectors to the vector database failed",
    FILE_ERROR_OWNERSHIP_AMBIGUOUS: "file ownership or collection membership is ambiguous",
    FILE_ERROR_STALE_CLAIM: "the worker was interrupted or the claim became stale",
    FILE_ERROR_CHUNK_REUSE_INVALID: "persisted chunks could not be reused because the source content changed",
    FILE_ERROR_PROCESSING_FAILED: "processing failed",
    EMBEDDING_PROVIDER_FAILED: "the embedding provider request failed",
    EMBEDDING_MODALITY_UNSUPPORTED: (
        "the selected embedding model does not support this content type"
    ),
    EMBEDDING_IMAGE_FORMAT_UNSUPPORTED: "only PNG and JPEG images are supported",
    EMBEDDING_IMAGE_INVALID: "the image file is invalid or could not be decoded",
    PDF_VISUAL_EXTRACTION_FAILED: "the PDF visual content could not be processed",
    PDF_VISUAL_LIMIT_EXCEEDED: (
        "the PDF exceeds the configured visual processing limit"
    ),
}

# Safe, bounded job-level messages (no exception text is persisted).
_JOB_ERROR_MESSAGES = {
    "job_validation": "Embedding reindex job validation failed. Check admin and embedding model configuration.",
    "unexpected": "Embedding reindex job failed with an unexpected error.",
    "enqueue_failed": "Embedding reindex job could not be enqueued.",
}


def _build_file_error_message(code: str, display_name: str, error: Exception) -> str:
    """Build a concise, user-safe error message that includes operation and cause.

    Format: ``"<operation> for <filename>: <cause>."``

    Only allowlisted operation/cause phrases are used; provider payloads,
    credentials, and stack traces never reach the durable record. Unknown
    stable codes degrade to the code's words (e.g. ``embedding_vector_non_finite``
    -> ``embedding vector non finite``), which is still safe.
    """
    operation = _FILE_OPERATION_LABELS.get(code)
    if operation is None:
        operation = (
            "Embedding request failed"
            if code.startswith("embedding_")
            else "Processing failed"
        )
    cause = _FILE_SAFE_CAUSES.get(code)
    if cause is None:
        cause = code.replace("_", " ")

    prefix = f"{operation} for "
    suffix = f": {cause}."
    name_budget = max(1, MAX_ERROR_LENGTH - len(prefix) - len(suffix))
    safe_display_name = str(display_name).replace("\r", " ").replace("\n", " ")
    if len(safe_display_name) > name_budget:
        if name_budget > 1:
            safe_display_name = safe_display_name[: name_budget - 1] + "…"
        else:
            safe_display_name = safe_display_name[:name_budget]
    return f"{prefix}{safe_display_name}{suffix}"


def _sanitize_error_message(stage: str, error: Exception) -> str:
    """Return a safe, bounded job-level error message (never exception text)."""
    return _JOB_ERROR_MESSAGES.get(
        stage, "Embedding reindex job failed."
    )[:MAX_ERROR_LENGTH]


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
        job_view, reclaim_own_processing_files = _claim_job_safe(job_view)
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
            # Spec 08: a pre-file admin/model failure is terminal for every
            # nonterminal inventory row. Persist each file failure first so job
            # counters and durable document errors match the ledger.
            _fail_job_files_safe(embedding_job_id, e)
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
                file_view = replace(file_view, status=fresh_file.status)
                
                # Skip if now completed by another worker
                if file_view.status == FILE_STATUS_COMPLETED:
                    log.debug(f"[EMBEDDING_WORKER] File {file_view.file_id} completed by another worker")
                    continue
            
            try:
                completed = _process_file(
                    job_view=job_view,
                    file_view=file_view,
                    admin=admin,
                    target_model=target_model,
                    embedding_service=embedding_service,
                    vector_repo=vector_repo,
                    config=config,
                    reclaim_own_processing_files=reclaim_own_processing_files,
                )
                if completed:
                    processed_count += 1
            except Exception as file_error:
                # File-local error: mark file failed and continue (Spec 08).
                # Record a stable stage code and a safe operation+cause message
                # that identifies the file without exposing credentials.
                error_code = _get_stable_error_code(file_error)
                display_name = _get_file_display_name(file_view.file_id)
                error_msg = _build_file_error_message(error_code, display_name, file_error)
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
        error_code = _get_stable_error_code(unexpected_error)
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

    For EmbeddingError, map the code onto the Spec 08 file-level failure
    taxonomy; unmapped EmbeddingError codes pass through unchanged because they
    are already stable and sanitized. Other exceptions are mapped by class name
    to a stable stage code.
    """
    if isinstance(error, EmbeddingError):
        return _EMBEDDING_CODE_MAP.get(error.code, error.code)

    # Map common exceptions to stable codes
    error_name = type(error).__name__.lower()
    if "extraction" in error_name or "loader" in error_name:
        return FILE_ERROR_EXTRACTION_FAILED
    elif "storage" in error_name or "filenotfound" in error_name:
        return FILE_ERROR_STORAGE_READ_FAILED
    elif "embedding" in error_name:
        return FILE_ERROR_EMBEDDING_FAILED
    elif "vector" in error_name or "upsert" in error_name:
        return FILE_ERROR_VECTOR_WRITE_FAILED
    else:
        return FILE_ERROR_PROCESSING_FAILED


def _claim_job_safe(
    job_view: EmbeddingJobView,
) -> tuple[Optional[EmbeddingJobView], bool]:
    """Atomically claim job as processing with duplicate delivery detection.

    Returns the claimed job and whether the current invocation is the recorded
    RQ job resuming an existing processing row. Returns ``(None, False)`` if a
    duplicate delivery has a different live owner.
    """
    from open_webui.retrieval.embedding.jobs import _transition_to_processing

    with get_db() as db:
        # Try to transition from queued to processing.
        # Use the internal function directly so we can distinguish a fresh
        # claim (queued → processing) from an already-processing no-op.
        claimed, changed = _transition_to_processing(db, job_view.id)

        if claimed is None:
            # Job not found — treat as terminal.
            raise EmbeddingError(
                EMBEDDING_JOB_TERMINAL,
                detail=f"Job {job_view.id} not found during claim",
            )

        if changed:
            # Fresh claim: queued → processing.  Commit immediately.
            db.commit()
            log.info(f"[EMBEDDING_WORKER] Claimed job {job_view.id} as processing")
            return claimed, False

    # Job was already processing — no DB transaction to commit. A retry of the
    # same RQ job is the rightful owner even though Redis reports that job as
    # started while this function is running.
    rq_job_id = claimed.rq_job_id
    if rq_job_id:
        current_rq_job_id = None
        try:
            from rq import get_current_job

            current_rq_job = get_current_job()
            if current_rq_job is not None:
                current_rq_job_id = current_rq_job.id
        except Exception as current_job_error:
            # Fail closed below if Redis still reports a live owner.
            log.warning(
                f"[EMBEDDING_WORKER] Could not resolve the current RQ job while "
                f"claiming durable job {job_view.id}: {type(current_job_error).__name__}"
            )

        if current_rq_job_id == rq_job_id:
            log.info(
                f"[EMBEDDING_WORKER] RQ job {rq_job_id} is resuming its "
                f"durable processing job {job_view.id}"
            )
            return claimed, True

        # This invocation is not the recorded owner. Only reclaim when the
        # recorded RQ job is no longer pending or processing.
        from open_webui.utils.job_queue import get_job_status

        rq_status = get_job_status(rq_job_id)
        if rq_status and rq_status.get("status") in ("pending", "processing"):
            log.warning(
                f"[EMBEDDING_WORKER] Duplicate delivery detected for job {job_view.id}. "
                f"RQ job {rq_job_id} is {rq_status.get('status')}. No-op."
            )
            return None, False

    # RQ job not active or not found — safe to reclaim.
    log.info(
        f"[EMBEDDING_WORKER] Job {job_view.id} already processing, "
        f"continuing with restart/reclaim"
    )
    return claimed, False


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
    config,
    reclaim_own_processing_files: bool,
):
    """Process a single file with all critical fixes."""
    job_id = job_view.id
    file_id = file_view.file_id
    
    log.debug(f"[EMBEDDING_WORKER] Processing file {file_id} for job {job_id}")
    
    # Step 9: Claim file (Fix #3: use reclaim for processing rows)
    claim_result = _claim_file_safe(
        job_id,
        file_view,
        reclaim_own_processing_files=reclaim_own_processing_files,
    )
    
    # Fix #12: Treat failed claim as skip, not failure
    if claim_result is not True:
        log.debug(f"[EMBEDDING_WORKER] File {file_id} claim failed/skipped")
        return False
    
    # Step 10: Load source file and inventory membership
    source_file = _load_source_file(file_id)
    file_snapshot = file_view.file_snapshot
    try:
        preparation_recipe = preparation_recipe_from_snapshot(file_snapshot)
    except (TypeError, ValueError):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED) from None

    expected_source_sha256 = file_snapshot.get("source_sha256")
    expected_updated_at = file_snapshot.get("updated_at")
    expected_content_hash = file_snapshot.get("content_hash")
    expected_content_origin = file_snapshot.get(
        "content_origin",
        CONTENT_ORIGIN_STORED_SOURCE,
    )
    expected_content_override_sha256 = file_snapshot.get(
        "content_override_sha256"
    )
    try:
        current_content_provenance = read_stored_content_provenance(source_file)
    except ValueError:
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED) from None
    if (
        expected_updated_at is not None
        and source_file.updated_at != expected_updated_at
    ) or source_file.hash != expected_content_hash or (
        current_content_provenance.origin != expected_content_origin
        or current_content_provenance.content_override_sha256
        != expected_content_override_sha256
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
    
    # Step 11: Re-read immutable source bytes and use the canonical preparation
    # path. Cached text/vector documents are never sufficient for visual input.
    prepared = _prepare_source_file(
        source_file=source_file,
        admin_email=admin.email,
        target_model=target_model,
        config=config,
        preparation_recipe=preparation_recipe,
    )

    if not prepared.chunks:
        raise EmbeddingError(
            FILE_ERROR_EMPTY_CONTENT,
            detail=f"File {file_id} contains no extractable content",
        )

    if expected_source_sha256 != prepared.source_sha256:
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)

    # Generate and fully validate all vectors before mutating chunks/projections.
    embeddings = _generate_embeddings(
        chunks=prepared.chunks,
        admin_id=admin.id,
        target_model_id=target_model.id,
        embedding_service=embedding_service,
    )

    persisted_chunks = build_persisted_chunks(
        prepared,
        admin_id=admin.id,
        file_id=file_id,
    )
    manifest_id = RagChunk.build_manifest_id(
        persisted_chunks,
        source_sha256=prepared.source_sha256,
        extraction_version=prepared.extraction_version,
    )
    rag_chunk_ids = RagChunk.insert_chunks(
        admin.id,
        file_id,
        persisted_chunks,
        manifest_id=manifest_id,
    )

    _write_vectors(
        vector_repo=vector_repo,
        admin_id=admin.id,
        file_id=file_id,
        chunks=prepared.chunks,
        embeddings=embeddings,
        rag_chunk_ids=rag_chunk_ids,
        metadata=[chunk["chunk_metadata"] for chunk in persisted_chunks],
        file_snapshot=file_snapshot,
        target_model=target_model,
        job_id=job_id,
    )
    _stage_prepared_manifest(
        job_id,
        file_id,
        prepared,
        manifest_id,
        rag_chunk_ids,
    )

    # Step 14: Mark file completed
    _mark_file_completed_safe(job_id, file_id)
    
    log.debug(f"[EMBEDDING_WORKER] Completed file {file_id}")
    return True


def _claim_file_safe(
    job_id: str,
    file_view,
    *,
    reclaim_own_processing_files: bool,
) -> Optional[bool]:
    """Claim file for processing with proper reclaim logic (Fix #3).

    The same recorded RQ job may immediately reclaim a processing row left by
    its previous attempt. Other invocations must wait for the stale threshold.

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
            stale_threshold_seconds = (
                0
                if reclaim_own_processing_files
                else FILE_STALE_THRESHOLD_SECONDS
            )
            claimed = EmbeddingJobRepository.reclaim_file(
                job_id=job_id,
                file_id=file_view.file_id,
                stale_threshold_seconds=stale_threshold_seconds,
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


def _get_file_display_name(file_id: str) -> str:
    """Return a safe display name for error records (filename when available).

    Falls back to the stable file id so every failure record still identifies
    the file even when the source row is missing or unreadable.
    """
    try:
        with get_db() as db:
            source_file = db.query(File).filter(File.id == file_id).first()
        if source_file is not None and source_file.filename:
            return source_file.filename
    except Exception:
        pass
    return file_id


def _prepare_source_file(
    *,
    source_file: File,
    admin_email: str,
    target_model,
    config,
    preparation_recipe: PreparationRecipe,
) -> PreparedFile:
    """Read original storage bytes and invoke the shared preparation pipeline."""
    if not source_file.path:
        raise EmbeddingError(FILE_ERROR_STORAGE_READ_FAILED)
    try:
        source_path = Storage.get_file(source_file.path)
        if not source_path or not os.path.isfile(source_path):
            raise OSError("source unavailable")
        with open(source_path, "rb") as source_handle:
            source_bytes = source_handle.read()
    except Exception:
        raise EmbeddingError(FILE_ERROR_STORAGE_READ_FAILED) from None

    try:
        content_provenance = resolve_authoritative_content_provenance(
            source_file,
            source_bytes,
        )
        return prepare_file_for_embedding(
            source_bytes=source_bytes,
            source_path=source_path,
            filename=source_file.filename,
            content_type=(source_file.meta or {}).get("content_type"),
            file_id=source_file.id,
            created_by=source_file.user_id,
            model=target_model,
            config=config,
            admin_email=admin_email,
            preparation_recipe=preparation_recipe,
            content_override=content_provenance.content_override,
        )
    except EmbeddingError:
        raise
    except Exception:
        raise EmbeddingError(FILE_ERROR_EXTRACTION_FAILED) from None


def _stage_prepared_manifest(
    job_id: str,
    file_id: str,
    prepared: PreparedFile,
    manifest_id: str,
    rag_chunk_ids: list[str],
) -> None:
    """Stage prepared cache/status for publication only after promotion."""
    with get_db() as db:
        job_file = (
            db.query(EmbeddingJobFile)
            .filter(
                EmbeddingJobFile.job_id == job_id,
                EmbeddingJobFile.file_id == file_id,
            )
            .first()
        )
        if job_file is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        snapshot = dict(job_file.file_snapshot or {})
        projection_ids = _current_snapshot_knowledge_ids(
            file_id=file_id,
            knowledge_ids=snapshot.get("knowledge_collection_ids", []),
        )
        snapshot["prepared_processing_summary"] = {
            "text_content": prepared.text_content,
            "content_hash": hashlib.sha256(
                prepared.text_content.encode("utf-8")
            ).hexdigest(),
            "source_sha256": prepared.source_sha256,
            "extraction_version": prepared.extraction_version,
            "manifest_id": manifest_id,
            "chunk_count": len(prepared.chunks),
            "rag_chunk_ids": list(rag_chunk_ids),
            "projection_ids": [f"file-{file_id}", *projection_ids],
            "processing_warnings": list(dict.fromkeys(prepared.warnings)),
            "visual_summary": dict(prepared.visual_summary),
        }
        job_file.file_snapshot = snapshot
        db.commit()


def _generate_embeddings(
    chunks: tuple[PreparedChunk, ...],
    admin_id: str,
    target_model_id: str,
    embedding_service: EmbeddingService,
) -> list:
    """Generate embeddings using target model (Fix #1: use frozen context)."""
    if not chunks:
        return []
    
    # Fix #1: Use embed_for_frozen_context with target model ID
    # Spec 08: preserve the original stable EmbeddingError code so the caller's
    # error mapping can record a distinct stage (credentials_missing,
    # provider_embedding_failed, ...) instead of collapsing every failure.
    batch = embedding_service.embed_for_frozen_context(
        inputs=[chunk.embedding_input for chunk in chunks],
        admin_id=admin_id,
        embedding_model_id=target_model_id,
    )
    return batch.vectors


def _write_vectors(
    vector_repo: ModelAwareVectorRepository,
    admin_id: str,
    file_id: str,
    chunks: tuple[PreparedChunk, ...],
    embeddings: list,
    rag_chunk_ids: list[str],
    metadata: list[dict],
    file_snapshot: dict,
    target_model,
    job_id: str,
):
    """Reconcile every required vector projection (Fix #4, #5, Spec 07).

    Vectors are stamped with the non-retrievable ``building`` status and the
    durable ``embedding_job_id`` so a partially built target space is never
    searchable (Spec 07 Build Visibility). Each file/knowledge collection
    projection is reconciled transactionally: current target rows are upserted
    by ``(admin_id, embedding_model_id, rag_chunk_id, collection_name)`` and
    stale target rows for the same projection are deleted in the same
    transaction. Rows for other models, files, and collections — including old
    active-model vectors — are never touched, and shared ``rag_chunks`` rows
    are never deleted.
    """
    if not chunks or not embeddings:
        return
    
    # Extract collection info from snapshot
    file_collection_name = file_snapshot.get("file_collection_name", f"file-{file_id}")
    snapshot_knowledge_ids = file_snapshot.get("knowledge_collection_ids", [])
    knowledge_collection_ids = _current_snapshot_knowledge_ids(
        file_id=file_id,
        knowledge_ids=snapshot_knowledge_ids,
    )
    
    # Fix #5: Build items with full provenance using ModelAwareVectorRepository
    texts = [chunk.content for chunk in chunks]
    modalities = [chunk.modality for chunk in chunks]
    
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
            modalities=modalities,
            embedding_status=VECTOR_STATUS_BUILDING,
            embedding_job_id=job_id,
        )
        
        projections = [(file_collection_name, file_items)]
        for knowledge_id in knowledge_collection_ids:
            knowledge_items = vector_repo.make_items(
                texts=texts,
                vectors=embeddings,
                metadata=metadata,
                rag_chunk_ids=rag_chunk_ids,
                admin_id=admin_id,
                model=target_model,
                file_id=file_id,
                knowledge_id=knowledge_id,
                modalities=modalities,
                embedding_status=VECTOR_STATUS_BUILDING,
                embedding_job_id=job_id,
            )
            projections.append((str(knowledge_id), knowledge_items))

        vector_repo.reconcile_model_aware_many(
            projections=projections,
            model=target_model,
        )

        log.debug(
            f"[EMBEDDING_WORKER] Reconcile wrote {len(file_items)} vectors to {1 + len(knowledge_collection_ids)} collections"
        )
    except Exception:
        raise EmbeddingError(
            FILE_ERROR_VECTOR_WRITE_FAILED,
        ) from None


def _current_snapshot_knowledge_ids(
    *, file_id: str, knowledge_ids
) -> list[str]:
    """Filter a reindex snapshot through current file memberships."""
    requested = {
        str(value)
        for value in (knowledge_ids if isinstance(knowledge_ids, list) else [])
        if value
    }
    if not requested:
        return []
    current: list[str] = []
    with get_db() as db:
        rows = (
            db.query(Knowledge.id, Knowledge.data)
            .filter(Knowledge.id.in_(requested))
            .all()
        )
        for row in rows:
            data = row.data if isinstance(row.data, dict) else {}
            file_ids = data.get("file_ids", [])
            if isinstance(file_ids, list) and file_id in file_ids:
                current.append(str(row.id))
    return sorted(current)


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


def _fail_job_files_safe(job_id: str, error: EmbeddingError) -> None:
    """Persist a safe failure for every nonterminal file after job validation fails."""
    error_code = _get_stable_error_code(error)
    file_views = _load_job_files(job_id)
    error_messages = {
        file_view.file_id: _build_file_error_message(
            error_code,
            _get_file_display_name(file_view.file_id),
            error,
        )
        for file_view in file_views
        if file_view.status in (FILE_STATUS_PENDING, FILE_STATUS_PROCESSING)
    }
    with get_db() as db:
        EmbeddingJobRepository.fail_nonterminal_files(
            job_id=job_id,
            error_code=error_code,
            error_messages=error_messages,
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
    """Finalize job with full Spec 09 finalization (vector activation + model promotion).

    On success (all files completed): atomically activates target vectors,
    deactivates previous-model vectors, promotes the target model, and marks
    the job completed — all in one transaction.

    On partial/failure: delegates to the standard _finalize_job path which
    sets terminal status without promoting any model.

    Stale-operation errors (job no longer latest) are caught and recorded as
    a job failure so the worker can still return a result. Unexpected errors
    during finalization are logged but do not crash the worker.
    """
    # Load job to determine admin context and finalization path
    with get_db() as db:
        job_view = EmbeddingJobRepository.get_job(job_id, db=db)

    if job_view is None:
        log.warning(f"[EMBEDDING_WORKER] Cannot finalize job {job_id}: not found")
        return

    admin_id = job_view.admin_id
    target_model_id = job_view.embedding_model_id
    previous_model_id = job_view.previous_embedding_model_id

    vector_repo = ModelAwareVectorRepository()

    try:
        with get_db() as db:
            # First, recompute counters
            EmbeddingJobRepository.recompute_counters(job_id=job_id, db=db)

            # Determine if this is an all-success finalization
            refreshed = EmbeddingJobRepository.get_job(job_id, db=db)
            if refreshed is None:
                db.commit()
                return

            all_success = (
                refreshed.total_files == refreshed.processed_files
                and refreshed.total_files >= 0
                and refreshed.failed_files == 0
            )

            if all_success:
                # Full finalization: activate vectors + promote model + complete
                # Load target model spec within the session
                target_model_spec = get_model_spec_by_id(target_model_id)

                _apply_staged_processing_summaries(
                    job_id=job_id,
                    db=db,
                )

                EmbeddingJobRepository.finalize_job_success(
                    job_id=job_id,
                    admin_id=admin_id,
                    target_model_id=target_model_id,
                    previous_model_id=previous_model_id,
                    vector_repo=vector_repo,
                    target_model_spec=target_model_spec,
                    db=db,
                )
            else:
                # Partial/failure finalization: set terminal status, no promotion
                EmbeddingJobRepository.finalize_job(job_id=job_id, db=db)

            db.commit()

        log.info(f"[EMBEDDING_WORKER] Finalized job {job_id}")

    except EmbeddingError as error:
        # Promotion is retryable as an operation. Keep the completed file
        # ledger and target state intact; a redelivered job revalidates every
        # staged vector before promotion. Never persist exception detail.
        log.error(
            "Embedding job promotion failed | job_id=%s | code=%s",
            job_id,
            error.code,
        )
        _mark_promotion_retryable(job_id, error.code)
    except Exception as error:
        log.error(
            "Embedding job promotion failed | job_id=%s | type=%s",
            job_id,
            type(error).__name__,
        )
        _mark_promotion_retryable(job_id, FILE_ERROR_PROCESSING_FAILED)


def _mark_promotion_retryable(job_id: str, error_code: str) -> None:
    """Mark a completed-ledger promotion failure as operation-retryable."""
    with get_db() as db:
        row = db.query(EmbeddingJob).filter(EmbeddingJob.id == job_id).first()
        if row is None or row.status in (JOB_STATUS_COMPLETED,):
            return
        row.status = JOB_STATUS_FAILED
        row.error_code = error_code
        row.error_message = "Embedding model promotion could not be completed. Retry the operation."
        row.completed_at = None
        row.updated_at = int(time.time())
        db.commit()


def _apply_staged_processing_summaries(*, job_id: str, db) -> None:
    """Publish staged file cache/status in the promotion transaction."""
    now = int(time.time())
    rows = (
        db.query(EmbeddingJobFile)
        .filter(
            EmbeddingJobFile.job_id == job_id,
            EmbeddingJobFile.status == FILE_STATUS_COMPLETED,
        )
        .all()
    )
    for job_file in rows:
        snapshot = (
            job_file.file_snapshot
            if isinstance(job_file.file_snapshot, dict)
            else {}
        )
        summary = snapshot.get("prepared_processing_summary")
        if not isinstance(summary, dict):
            raise EmbeddingError(FILE_ERROR_PROCESSING_FAILED)
        file_row = (
            db.query(File)
            .filter(File.id == job_file.file_id)
            .with_for_update()
            .first()
        )
        if file_row is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        text_content = summary.get("text_content")
        content_hash = summary.get("content_hash")
        source_sha256 = summary.get("source_sha256")
        manifest_id = summary.get("manifest_id")
        if not isinstance(text_content, str):
            raise EmbeddingError(FILE_ERROR_PROCESSING_FAILED)
        for digest in (content_hash, source_sha256, manifest_id):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise EmbeddingError(FILE_ERROR_PROCESSING_FAILED)

        # The worker validated this snapshot before provider calls, but another
        # file in the same job may take minutes. Revalidate the locked source
        # immediately before cache publication and vector activation so a
        # concurrent edit can never promote stale vectors or overwrite newer
        # extracted content.
        expected_source_sha256 = snapshot.get("source_sha256")
        if expected_source_sha256 != source_sha256:
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        if source_sha256_for_file(file_row) != source_sha256:
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        if file_row.hash != snapshot.get("content_hash"):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        expected_updated_at = snapshot.get("updated_at")
        if (
            expected_updated_at is not None
            and file_row.updated_at != expected_updated_at
        ):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)
        try:
            current_provenance = read_stored_content_provenance(file_row)
        except ValueError:
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED) from None
        if (
            current_provenance.origin
            != snapshot.get("content_origin", CONTENT_ORIGIN_STORED_SOURCE)
            or current_provenance.content_override_sha256
            != snapshot.get("content_override_sha256")
        ):
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)

        file_row.data = {**(file_row.data or {}), "content": text_content}
        file_row.hash = content_hash
        file_row.meta = {
            **(file_row.meta or {}),
            "collection_name": f"file-{file_row.id}",
            "source_sha256": source_sha256,
            "extraction_version": summary.get("extraction_version"),
            "chunk_manifest_id": manifest_id,
            "processing_warnings": list(
                dict.fromkeys(summary.get("processing_warnings") or [])
            ),
            "visual_summary": dict(summary.get("visual_summary") or {}),
            "processing_status": "completed",
            "processing_completed_at": now,
            "processing_error": None,
            "processing_error_code": None,
        }
        file_row.updated_at = now
