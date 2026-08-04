"""Embedding worker entry point for RQ jobs.

This module provides the worker function that RQ calls to process embedding jobs.
The actual orchestration logic is in worker.py (Spec 06).
"""

import logging
from open_webui.retrieval.embedding.worker import process_embedding_job

log = logging.getLogger(__name__)

# Re-export for RQ workers
__all__ = ["process_embedding_job"]
