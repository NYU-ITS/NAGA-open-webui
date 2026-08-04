"""Embedding worker placeholder for Spec 05.

This module provides the worker function boundary for RQ jobs.
Full implementation will be in Spec 06 (worker orchestration).

Spec 05 only defines the enqueue mechanism; actual processing is deferred.
"""

import logging

log = logging.getLogger(__name__)


def process_embedding_job(embedding_job_id: str) -> dict:
    """Process an embedding reindex job (placeholder for Spec 06).
    
    This function is enqueued by Spec 05 but actual processing is implemented
    in Spec 06 (worker orchestration). This placeholder ensures the import
    boundary exists for Spec 05 acceptance testing.
    
    Args:
        embedding_job_id: Durable job ID from database
        
    Returns:
        Result dictionary (placeholder)
        
    Raises:
        NotImplementedError: Until Spec 06 implementation
    """
    log.warning(
        f"[EMBEDDING_WORKER] process_embedding_job called for {embedding_job_id} "
        f"but worker orchestration is not yet implemented (Spec 06)"
    )
    raise NotImplementedError(
        f"Worker orchestration not implemented. Job {embedding_job_id} cannot be processed yet."
    )
