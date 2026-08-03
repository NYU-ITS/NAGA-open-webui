"""
Background job store for chat PDF exports.

A large export takes tens of seconds, which is longer than most reverse proxy
and browser timeouts are willing to hold a single request open. Callers submit
the conversation, poll for status and fetch the bytes when the job is done.

State lives in Redis when it is configured so that any replica can serve the
poll and the download. Without Redis the store falls back to process memory,
which is correct for a single replica deployment and for local development.
"""

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from open_webui.env import REDIS_URL
from open_webui.models.chats import ChatTitleMessagesForm
from open_webui.utils.pdf_generator import PDFGenerator

log = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"

# How long a finished job stays retrievable.
JOB_TTL_SEC = int(os.environ.get("PDF_EXPORT_JOB_TTL", "900"))

# Exports are CPU bound in a child process. Bounding the pool keeps a burst of
# submissions from starving the API worker of CPU.
MAX_CONCURRENT_EXPORTS = int(os.environ.get("PDF_EXPORT_CONCURRENCY", "2"))

_REDIS_PREFIX = "pdf:export:"

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()

_memory_jobs: Dict[str, Dict[str, Any]] = {}
_memory_lock = threading.Lock()

_redis_client = None
_redis_checked_at = 0.0
_redis_lock = threading.Lock()

# How long to stay in memory mode after a failed connection before probing again.
_REDIS_RETRY_SEC = 60.0


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=MAX_CONCURRENT_EXPORTS, thread_name_prefix="pdf-export"
            )
        return _executor


def _get_redis():
    """
    Redis client for job state, or None when Redis is not available.

    The connection is probed once and the outcome is remembered, so a
    deployment without Redis does not pay for, or log, a failed connection on
    every status poll.
    """
    global _redis_client, _redis_checked_at

    if not REDIS_URL:
        return None

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        if time.monotonic() - _redis_checked_at < _REDIS_RETRY_SEC:
            return None

        _redis_checked_at = time.monotonic()
        try:
            from redis import Redis
            from open_webui.socket.utils import get_redis_pool

            pool = get_redis_pool(REDIS_URL, use_master=True)
            client = pool._conn if hasattr(pool, "_conn") else Redis(connection_pool=pool)
            client.ping()
            _redis_client = client
            return _redis_client
        except Exception as e:
            log.warning(f"PDF export jobs falling back to in-memory store: {e}")
            return None


def _drop_redis() -> None:
    """Forget a client that failed mid-operation so the next call re-probes."""
    global _redis_client
    with _redis_lock:
        _redis_client = None


def _prune_memory_jobs() -> None:
    now = time.time()
    for job_id, job in list(_memory_jobs.items()):
        if job.get("expires_at", 0) < now:
            _memory_jobs.pop(job_id, None)


def _write(job_id: str, fields: Dict[str, Any], data: Optional[bytes] = None) -> None:
    client = _get_redis()
    if client is not None:
        key = f"{_REDIS_PREFIX}{job_id}"
        try:
            client.hset(key, mapping={k: str(v) for k, v in fields.items()})
            client.expire(key, JOB_TTL_SEC)
            if data is not None:
                client.set(f"{key}:data", data, ex=JOB_TTL_SEC)
            return
        except Exception as e:
            log.warning(f"Failed to persist PDF job {job_id} in Redis: {e}")
            _drop_redis()

    with _memory_lock:
        _prune_memory_jobs()
        job = _memory_jobs.setdefault(job_id, {})
        job.update(fields)
        job["expires_at"] = time.time() + JOB_TTL_SEC
        if data is not None:
            job["data"] = data


def _read(job_id: str) -> Optional[Dict[str, Any]]:
    client = _get_redis()
    if client is not None:
        try:
            raw = client.hgetall(f"{_REDIS_PREFIX}{job_id}")
            if raw:
                return {
                    (k.decode() if isinstance(k, bytes) else k):
                    (v.decode() if isinstance(v, bytes) else v)
                    for k, v in raw.items()
                }
        except Exception as e:
            log.warning(f"Failed to read PDF job {job_id} from Redis: {e}")
            _drop_redis()

    with _memory_lock:
        _prune_memory_jobs()
        job = _memory_jobs.get(job_id)
        return {k: v for k, v in job.items() if k != "data"} if job else None


def _read_data(job_id: str) -> Optional[bytes]:
    client = _get_redis()
    if client is not None:
        try:
            data = client.get(f"{_REDIS_PREFIX}{job_id}:data")
            if data:
                return data
        except Exception as e:
            log.warning(f"Failed to read PDF job payload {job_id} from Redis: {e}")
            _drop_redis()

    with _memory_lock:
        job = _memory_jobs.get(job_id)
        return job.get("data") if job else None


def _run(job_id: str, form_data: ChatTitleMessagesForm) -> None:
    _write(job_id, {"status": STATUS_PROCESSING, "started_at": time.time()})
    started = time.perf_counter()
    try:
        pdf_bytes = PDFGenerator(form_data).generate_chat_pdf()
        _write(
            job_id,
            {
                "status": STATUS_COMPLETED,
                "ended_at": time.time(),
                "size": len(pdf_bytes),
            },
            data=pdf_bytes,
        )
        log.info(
            f"PDF export job {job_id} completed in {time.perf_counter() - started:.2f}s "
            f"({len(pdf_bytes)} bytes, {len(form_data.messages)} messages)"
        )
    except Exception as e:
        log.exception(f"PDF export job {job_id} failed: {e}")
        _write(job_id, {"status": STATUS_ERROR, "ended_at": time.time(), "error": str(e)})


def submit(form_data: ChatTitleMessagesForm, user_id: str) -> str:
    """Queue an export and return its job id."""
    job_id = str(uuid.uuid4())
    _write(
        job_id,
        {
            "status": STATUS_PENDING,
            "user_id": user_id,
            "title": form_data.title,
            "messages": len(form_data.messages),
            "created_at": time.time(),
        },
    )
    _get_executor().submit(_run, job_id, form_data)
    return job_id


def status(job_id: str) -> Optional[Dict[str, Any]]:
    """Job state without the payload, or None if unknown or expired."""
    job = _read(job_id)
    if job is None:
        return None
    return {
        "id": job_id,
        "status": job.get("status", STATUS_PENDING),
        "user_id": job.get("user_id"),
        "title": job.get("title"),
        "error": job.get("error"),
        "size": int(job["size"]) if job.get("size") else None,
    }


def result(job_id: str) -> Optional[bytes]:
    """Finished PDF bytes, or None if the job is unfinished or expired."""
    return _read_data(job_id)
