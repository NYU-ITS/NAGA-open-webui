"""Process a frozen reindex inventory and publish each successful file atomically.

Generation and source checks fence every publication. Required text/visual
vectors become searchable on commit, optional audio is dispatched afterward,
and job finalization only reconciles the attempt's counters and terminal status.
Failed rows are retried through a new failed-file-only attempt.
"""

import logging
import os
import time
from dataclasses import replace
from typing import Optional

from open_webui.internal.db import get_db
from open_webui.models.embeddings import EmbeddingJobFile
from open_webui.models.files import File
from open_webui.models.users import User
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
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
    PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL,
    EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
    EMBEDDING_INVENTORY_MISSING_FILE,
    EMBEDDING_REINDEX_SOURCE_CHANGED,
)
from open_webui.retrieval.embedding.file_processing import (
    CONTENT_ORIGIN_STORED_SOURCE,
    embed_prepared_file_best_effort_audio,
    read_stored_content_provenance,
    resolve_authoritative_content_provenance,
)
from open_webui.retrieval.embedding.preparation import (
    PreparedFile,
    PreparationRecipe,
    prepare_file_for_embedding,
    preparation_recipe_from_snapshot,
)
from open_webui.retrieval.embedding.reliability import EmbeddingReliabilityPolicy
from open_webui.retrieval.embedding.jobs import (
    EmbeddingJobRepository,
    EmbeddingJobView,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_FAILED,
    JOB_STATUS_PARTIALLY_FAILED,
    FILE_STATUS_COMPLETED,
    FILE_STATUS_FAILED,
    FILE_STATUS_INCOMPATIBLE,
    FILE_STATUS_PENDING,
    FILE_STATUS_PROCESSING,
)
from open_webui.retrieval.embedding.registry import get_model_spec_by_id
from open_webui.retrieval.embedding.service import EmbeddingService
from open_webui.retrieval.vector.model_aware import (
    ModelAwareVectorRepository,
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
    """Execute a durable reindex attempt with independent file publication.

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
                if file_view.status in (FILE_STATUS_COMPLETED, FILE_STATUS_INCOMPATIBLE):
                    log.debug(
                        f"[EMBEDDING_WORKER] File {file_view.file_id} already terminal ({file_view.status})"
                    )
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
                if _is_incompatible_outcome(file_error):
                    error_code = file_error.code
                    log.info(
                        "[EMBEDDING_WORKER] File %s skipped as incompatible | code=%s",
                        file_view.file_id,
                        error_code,
                    )
                    _mark_file_incompatible_safe(
                        embedding_job_id, file_view.file_id, error_code
                    )
                    continue

                # File-local error: mark file failed and continue. Record a
                # stable stage code and safe operation+cause message.
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
    """Prepare, embed, and publish one file against its frozen generation."""
    job_id = job_view.id
    file_id = file_view.file_id
    from open_webui.retrieval.embedding.publication import reuse_current_publication

    if reuse_current_publication(job_id, file_id):
        return True

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
        current_content_provenance.origin != expected_content_origin
        or current_content_provenance.content_override_sha256
        != expected_content_override_sha256
    ):
        raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)

    from open_webui.retrieval.embedding.publication import (
        claim_required_indexing,
        publish_prepared_file,
        release_required_indexing,
    )

    token = claim_required_indexing(
        admin_id=admin.id,
        model_id=target_model.id,
        snapshot=file_snapshot,
        job_id=job_id,
    )
    try:
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

        incompatible_code = (
            PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL
            if PDF_VISUALS_REQUIRE_MULTIMODAL_MODEL in prepared.warnings
            else None
        )

        if expected_source_sha256 != prepared.source_sha256:
            raise EmbeddingError(EMBEDDING_REINDEX_SOURCE_CHANGED)

        # Generate and fully validate all vectors before mutating chunks/projections.
        file_embedding_service = EmbeddingService(
            config,
            reliability_policy=EmbeddingReliabilityPolicy.from_dict(
                file_snapshot.get("reliability_policy")
            ),
            call_context={
                "call_id": job_id,
                "operation": "reindex",
                "job_id": job_id,
                "file_id": file_id,
            },
        )
        prepared, embeddings = embed_prepared_file_best_effort_audio(
            prepared=prepared,
            embedding_service=file_embedding_service,
            admin_id=admin.id,
            embedding_model_id=target_model.id,
            preparation_recipe=preparation_recipe,
            index_generation_id=job_view.index_generation_id,
        )
        if not prepared.chunks or len(embeddings) != len(prepared.chunks):
            raise EmbeddingError(FILE_ERROR_EMBEDDING_FAILED)

        publish_prepared_file(
            admin_id=admin.id,
            model=target_model,
            snapshot=file_snapshot,
            prepared=prepared,
            vectors=embeddings,
            owner_token=token,
            job_id=job_id,
            incompatible_code=incompatible_code,
        )
    finally:
        release_required_indexing(file_id, token)
    try:
        from open_webui.retrieval.embedding.audio_repair import dispatch_pending_audio

        dispatch_pending_audio(
            config=config,
            file_id=file_id,
            admin_id=admin.id,
            embedding_model_id=target_model.id,
            reliability_policy=file_snapshot.get("reliability_policy"),
        )
    except Exception as error:
        log.warning(
            "reindex_audio_dispatch_pending file_id=%s type=%s",
            file_id,
            type(error).__name__,
        )
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
            defer_audio=True,
        )
    except EmbeddingError:
        raise
    except Exception:
        raise EmbeddingError(FILE_ERROR_EXTRACTION_FAILED) from None


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


def _mark_file_incompatible_safe(
    job_id: str, file_id: str, error_code: str
):
    """Mark file as an allowlisted incompatibility without retry semantics."""
    with get_db() as db:
        EmbeddingJobRepository.mark_file_incompatible(
            job_id=job_id,
            file_id=file_id,
            error_code=error_code,
            db=db,
        )
        db.commit()


def _is_incompatible_outcome(error: Exception) -> bool:
    return isinstance(error, EmbeddingError) and error.code == EMBEDDING_MODALITY_UNSUPPORTED


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
    """Mark job failed without restoring the previous embedding model."""
    with get_db() as db:
        EmbeddingJobRepository.mark_job_failed(
            job_id=job_id,
            error_code=error_code,
            error_message=error_message,
            db=db,
        )
        db.commit()


def _finalize_job_safe(job_id: str):
    """Finalization reports attempt outcomes and never changes publications."""
    try:
        with get_db() as db:
            EmbeddingJobRepository.finalize_job(job_id=job_id, db=db)
            db.commit()
    except Exception as error:
        log.error(
            "Embedding job finalization failed job_id=%s type=%s",
            job_id,
            type(error).__name__,
        )
