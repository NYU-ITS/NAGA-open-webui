import json
import logging
import os
import shutil
import time

import uuid
from datetime import datetime
from typing import Any, Callable, List, Literal, Optional
from uuid import UUID

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    Request,
    status,
    APIRouter,
)
from open_webui.utils.job_queue import (
    enqueue_file_processing_job,
    is_job_queue_available,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import tiktoken
from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import JSONB


from langchain.text_splitter import RecursiveCharacterTextSplitter, TokenTextSplitter
from langchain_core.documents import Document

from open_webui.internal.db import get_db
from open_webui.models.files import File as FileRecord, FileModel, Files
from open_webui.models.knowledge import Knowledges
from open_webui.models.users import Users
from open_webui.storage.provider import Storage
from open_webui.env import REDIS_URL
from open_webui.socket.utils import RedisLock


from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_CREDENTIALS_MISSING,
    EMBEDDING_FILE_NOT_FOUND,
    EMBEDDING_JOB_ACTIVE_EXISTS,
    EMBEDDING_MODEL_DISABLED,
    EMBEDDING_MODEL_NOT_CONFIGURED,
    EMBEDDING_MODEL_STATE_CONFLICT,
    EMBEDDING_PROVIDER_UNSUPPORTED,
    EMBEDDING_REINDEX_NOT_READY,
    EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
    FILE_PROCESSING_FAILED,
    safe_file_processing_error_code,
    safe_file_processing_error_message,
)
from open_webui.retrieval.embedding.model_change import (
    ModelChangeResult,
    ModelChangeNoOp,
    request_model_change,
)
from open_webui.retrieval.embedding.enqueue import dispatch_embedding_job

# Document loaders
from open_webui.retrieval.loaders.main import Loader
from open_webui.retrieval.loaders.youtube import YoutubeLoader

# Web search engines
from open_webui.retrieval.web.main import SearchResult
from open_webui.retrieval.web.utils import get_web_loader
from open_webui.retrieval.web.brave import search_brave
from open_webui.retrieval.web.kagi import search_kagi
from open_webui.retrieval.web.mojeek import search_mojeek
from open_webui.retrieval.web.bocha import search_bocha
from open_webui.retrieval.web.duckduckgo import search_duckduckgo
from open_webui.retrieval.web.google_pse import search_google_pse
from open_webui.retrieval.web.jina_search import search_jina
from open_webui.retrieval.web.searchapi import search_searchapi
from open_webui.retrieval.web.serpapi import search_serpapi
from open_webui.retrieval.web.searxng import search_searxng
from open_webui.retrieval.web.serper import search_serper
from open_webui.retrieval.web.serply import search_serply
from open_webui.retrieval.web.serpstack import search_serpstack
from open_webui.retrieval.web.tavily import search_tavily
from open_webui.retrieval.web.bing import search_bing
from open_webui.retrieval.web.exa import search_exa


from open_webui.retrieval.utils import (
    get_single_batch_embedding_function,
    get_embedding_function,
    get_model_path,
    query_collection,
    query_collection_with_hybrid_search,
    query_doc,
    query_doc_with_hybrid_search,
)
from open_webui.utils.misc import (
    calculate_sha256_string,
)
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.access_control import has_access


from open_webui.config import (
    ENV,
    RAG_EMBEDDING_MODEL_AUTO_UPDATE,
    RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE,
    RAG_RERANKING_MODEL_AUTO_UPDATE,
    RAG_RERANKING_MODEL_TRUST_REMOTE_CODE,
    UPLOAD_DIR,
    DEFAULT_LOCALE,
)
from open_webui.env import (
    SRC_LOG_LEVELS,
    DEVICE_TYPE,
    ENABLE_JOB_QUEUE,
    DOCKER,
)
from open_webui.constants import ERROR_MESSAGES

# OpenTelemetry instrumentation (conditional import)
try:
    from open_webui.utils.otel_instrumentation import (
        trace_span,
        add_span_event,
        set_span_attribute,
    )
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    # Create no-op functions if OTEL not available
    def trace_span(*args, **kwargs):
        from contextlib import contextmanager
        @contextmanager
        def _noop():
            yield None
        return _noop()
    def add_span_event(*args, **kwargs):
        pass
    def set_span_attribute(*args, **kwargs):
        pass

# Safe wrapper functions that NEVER fail - OTEL is monitoring only, must not affect task execution
def safe_add_span_event(event_name, attributes=None):
    """Safely add span event - never fails, even if OTEL is broken"""
    try:
        add_span_event(event_name, attributes)
    except Exception as e:
        log.debug(f"OTEL add_span_event failed (non-critical): {e}")

def safe_set_span_attribute(span, key, value):
    """Safely set span attribute - never fails, even if OTEL is broken"""
    try:
        if span:
            set_span_attribute(span, key, value)
    except Exception as e:
        log.debug(f"OTEL set_span_attribute failed (non-critical): {e}")

def safe_trace_span(*args, **kwargs):
    """Safely create trace span - never fails, even if OTEL is broken"""
    try:
        return trace_span(*args, **kwargs)
    except Exception as e:
        log.debug(f"OTEL trace_span failed (non-critical), using nullcontext: {e}")
        from contextlib import nullcontext
        return nullcontext(enter_result=None)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

##########################################
#
# Utility functions
#
##########################################


def get_ef(
    engine: str,
    embedding_model: str,
    auto_update: bool = False,
):
    ef = None
    if embedding_model and engine == "":
        from sentence_transformers import SentenceTransformer

        try:
            ef = SentenceTransformer(
                get_model_path(embedding_model, auto_update),
                device=DEVICE_TYPE,
                trust_remote_code=RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE,
            )
        except Exception as e:
            log.debug(f"Error loading SentenceTransformer: {e}")

    return ef


def get_rf(
    reranking_model: str,
    auto_update: bool = False,
):
    rf = None
    if reranking_model:
        if any(model in reranking_model for model in ["jinaai/jina-colbert-v2"]):
            try:
                from open_webui.retrieval.models.colbert import ColBERT

                rf = ColBERT(
                    get_model_path(reranking_model, auto_update),
                    env="docker" if DOCKER else None,
                )

            except Exception as e:
                log.error(f"ColBERT: {e}")
                raise Exception(ERROR_MESSAGES.DEFAULT(e))
        else:
            import sentence_transformers

            try:
                rf = sentence_transformers.CrossEncoder(
                    get_model_path(reranking_model, auto_update),
                    device=DEVICE_TYPE,
                    trust_remote_code=RAG_RERANKING_MODEL_TRUST_REMOTE_CODE,
                )
            except Exception:
                log.error("CrossEncoder error")
                raise Exception(ERROR_MESSAGES.DEFAULT("CrossEncoder error"))
    return rf


##########################################
#
# API routes
#
##########################################


router = APIRouter()


class CollectionNameForm(BaseModel):
    collection_name: Optional[str] = None


class ProcessUrlForm(CollectionNameForm):
    url: str


class SearchForm(CollectionNameForm):
    query: str


@router.get("/worker/status")
async def get_worker_status(request: Request, user=Depends(get_verified_user)):
    """
    Get worker and job queue status for debugging.
    """
    from open_webui.utils.job_queue import (
        get_job_queue,
        FILE_PROCESSING_QUEUE_NAME,
        is_job_queue_available,
    )
    from rq import Worker
    
    status = {
        "job_queue_enabled": ENABLE_JOB_QUEUE,
        "job_queue_available": False,
        "queue_name": FILE_PROCESSING_QUEUE_NAME,
        "queue_length": 0,
        "workers": [],
        "redis_connected": False,
    }
    
    try:
        if is_job_queue_available():
            status["job_queue_available"] = True
            queue = get_job_queue()
            if queue:
                status["queue_length"] = len(queue)
                status["redis_connected"] = True
                
                # Get active workers
                try:
                    workers = Worker.all(queue=queue)
                    status["workers"] = [
                        {
                            "name": w.name,
                            "state": w.get_state(),
                            "current_job": str(w.get_current_job_id()) if w.get_current_job_id() else None,
                        }
                        for w in workers
                    ]
                except Exception as worker_error:
                    log.warning(f"Could not get worker status: {worker_error}")
                    status["worker_error"] = str(worker_error)
    except Exception as e:
        log.error(f"Error checking worker status: {e}", exc_info=True)
        status["error"] = str(e)
    
    return status


@router.get("/")
async def get_status(request: Request, user=Depends(get_verified_user)):
    # Get chunk settings with defaults (1000/200) if not configured or invalid
    chunk_size_raw = request.app.state.config.CHUNK_SIZE.get(user.email)
    chunk_size = chunk_size_raw if chunk_size_raw and chunk_size_raw > 0 else 1000
    chunk_overlap_raw = request.app.state.config.CHUNK_OVERLAP.get(user.email)
    chunk_overlap = chunk_overlap_raw if chunk_overlap_raw is not None and chunk_overlap_raw >= 0 else 200
    template = request.app.state.config.RAG_TEMPLATE.get(user.email)

    log.info(f"[get_status] user={user.email} | chunk_size={chunk_size} | chunk_overlap={chunk_overlap} | template={template}")

    return {
        "status": True,
        
        "chunk_size": chunk_size if chunk_size and chunk_size > 0 else 1000,
        "chunk_overlap": chunk_overlap if chunk_overlap is not None and chunk_overlap > 0 else 200,
        "template": request.app.state.config.RAG_TEMPLATE.get(user.email),
        "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
        "embedding_model": request.app.state.config.RAG_EMBEDDING_MODEL,
        "reranking_model": request.app.state.config.RAG_RERANKING_MODEL,
        "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
    }


@router.get("/embedding")
async def get_embedding_config(request: Request, user=Depends(get_verified_user)):
    """
    Get embedding configuration for the requesting user.
    Returns embedding configuration, including the stored API key, for the requesting user.
    """
    requesting_email = user.email
    embedding_model = request.app.state.config.RAG_EMBEDDING_MODEL_USER.get(requesting_email) or ""
    
    return {
        "status": True,
        "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
        "embedding_model": embedding_model,
        "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
        "openai_config": {
            "url": request.app.state.config.RAG_OPENAI_API_BASE_URL,
            "key": request.app.state.config.RAG_OPENAI_API_KEY.get(requesting_email) or "",
        },
    }


@router.get("/reranking")
async def get_reraanking_config(request: Request, user=Depends(get_verified_user)):
    return {
        "status": True,
        "reranking_model": request.app.state.config.RAG_RERANKING_MODEL,
    }


class OpenAIConfigForm(BaseModel):
    url: str
    key: str


class OllamaConfigForm(BaseModel):
    url: str
    key: str


class EmbeddingModelUpdateForm(BaseModel):
    openai_config: Optional[OpenAIConfigForm] = None
    ollama_config: Optional[OllamaConfigForm] = None
    embedding_engine: str
    embedding_model: str
    embedding_batch_size: Optional[int] = 1


@router.post("/embedding/update")
async def update_embedding_config(
    request: Request, form_data: EmbeddingModelUpdateForm,
    background_tasks: BackgroundTasks, user=Depends(get_verified_user)
):
    log.info(
        f"Embedding config update: admin='{user.email}' engine='{form_data.embedding_engine}' "
        f"model='{form_data.embedding_model}' batch_size={form_data.embedding_batch_size}"
    )

    # Basic validation: model and API key are mandatory for OpenAI/Portkey engines
    if form_data.embedding_engine in ["openai", "portkey"]:
        if not form_data.embedding_model or not form_data.embedding_model.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Embedding model is required for OpenAI/Portkey engines.",
            )
        if form_data.openai_config is None or not form_data.openai_config.key.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Embedding API key is required for OpenAI/Portkey engines.",
            )

    admin_email = user.email
    try:
        request.app.state.config.RAG_EMBEDDING_ENGINE = form_data.embedding_engine
        # NOTE: RAG_EMBEDDING_MODEL_USER is NOT written here.  It is persisted
        # atomically inside request_model_change() so a validation or inventory
        # failure rolls config back together with durable state.

        if request.app.state.config.RAG_EMBEDDING_ENGINE in [
            "ollama",
            "openai",
            "portkey",
        ]:
            if form_data.openai_config is not None:
                request.app.state.config.RAG_OPENAI_API_BASE_URL = (
                    form_data.openai_config.url
                )
                request.app.state.config.RAG_OPENAI_API_KEY.set(
                    admin_email, form_data.openai_config.key
                )

            if form_data.ollama_config is not None:
                request.app.state.config.RAG_OLLAMA_BASE_URL = (
                    form_data.ollama_config.url
                )
                request.app.state.config.RAG_OLLAMA_API_KEY = (
                    form_data.ollama_config.key
                )

            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE = (
                form_data.embedding_batch_size
            )

        request.app.state.ef = get_ef(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
        )

        # Credential-safe: Do not rebuild global EMBEDDING_FUNCTION
        # Embedding service is created per-request with user-specific credentials

        # Phase 4: Create durable reindex job via model-change transaction.
        # RAG_EMBEDDING_MODEL_USER is written atomically inside the transaction
        # so a validation or inventory failure rolls config back together with
        # durable state.
        reindex_job = None
        change_result = None
        if form_data.embedding_model and form_data.embedding_model.strip():
            try:
                change_result, _admin_email = request_model_change(
                    admin_id=user.id,
                    target_model_id=form_data.embedding_model,
                    authenticated_user_id=user.id,
                    config=request.app.state.config,
                )
                # Config was written atomically inside the transaction.
                # Invalidate caches now that the transaction has committed.
                from open_webui.config import invalidate_user_scoped_config_cache
                invalidate_user_scoped_config_cache(
                    admin_email, "rag.embedding_model_user"
                )
                if isinstance(change_result, ModelChangeResult) and change_result.status in ("queued", "processing"):
                    try:
                        dispatch_mode = dispatch_embedding_job(change_result.job_id, background_tasks)
                    except Exception as enqueue_err:
                        log.error(
                            "[EMBEDDING_UPDATE] Failed to enqueue job %s: %s",
                            change_result.job_id,
                            enqueue_err,
                            exc_info=True,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={
                                "error_code": "RQ_DISPATCH_FAILED",
                                "message": "Model config saved, but the indexing job could not be queued. Retry from the embedding jobs page.",
                            },
                        )
                    reindex_job = {
                        "job_id": change_result.job_id,
                        "status": change_result.status,
                        "target_model_id": change_result.target_model_id,
                        "total_files": change_result.total_files,
                        "dispatch_mode": dispatch_mode,
                    }
                elif isinstance(change_result, ModelChangeResult):
                    reindex_job = {
                        "job_id": change_result.job_id,
                        "status": change_result.status,
                        "target_model_id": change_result.target_model_id,
                        "total_files": change_result.total_files,
                        "dispatch_mode": "background",
                    }
            except HTTPException:
                raise
            except EmbeddingError as e:
                if e.code in (EMBEDDING_JOB_ACTIVE_EXISTS, EMBEDDING_MODEL_STATE_CONFLICT):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error_code": e.code, "message": str(e.detail)},
                    )
                if e.code in (EMBEDDING_MODEL_NOT_CONFIGURED, EMBEDDING_MODEL_DISABLED):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": e.code, "message": str(e.detail)},
                    )
                if e.code in (
                    EMBEDDING_ADMIN_UNRESOLVED,
                    EMBEDDING_CREDENTIALS_MISSING,
                    EMBEDDING_PROVIDER_UNSUPPORTED,
                    EMBEDDING_STORAGE_DIMENSION_UNSUPPORTED,
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={"error_code": e.code, "message": str(e.detail)},
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=ERROR_MESSAGES.DEFAULT(e),
                )

        # Derive the authoritative model name from the transaction result
        # (falls back to the form value when no model change was attempted).
        if change_result is not None:
            saved_model = change_result.target_model_id
        else:
            saved_model = form_data.embedding_model or ""

        return {
            "status": True,
            "embedding_engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
            "embedding_model": saved_model,
            "embedding_batch_size": request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            "openai_config": {
                "url": request.app.state.config.RAG_OPENAI_API_BASE_URL,
                "key": request.app.state.config.RAG_OPENAI_API_KEY.get(user.email) or "",
            },
            "ollama_config": {
                "url": request.app.state.config.RAG_OLLAMA_BASE_URL,
                "key": request.app.state.config.RAG_OLLAMA_API_KEY,
            },
            **({"reindex_job": reindex_job} if reindex_job else {}),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Problem updating embedding model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class RerankingModelUpdateForm(BaseModel):
    reranking_model: str


@router.post("/reranking/update")
async def update_reranking_config(
    request: Request, form_data: RerankingModelUpdateForm, user=Depends(get_admin_user)
):
    log.info(
        f"Updating reranking model: {request.app.state.config.RAG_RERANKING_MODEL} to {form_data.reranking_model}"
    )
    try:
        request.app.state.config.RAG_RERANKING_MODEL = form_data.reranking_model

        try:
            request.app.state.rf = get_rf(
                request.app.state.config.RAG_RERANKING_MODEL,
                True,
            )
        except Exception as e:
            log.error(f"Error loading reranking model: {e}")
            request.app.state.config.ENABLE_RAG_HYBRID_SEARCH = False

        return {
            "status": True,
            "reranking_model": request.app.state.config.RAG_RERANKING_MODEL,
        }
    except Exception as e:
        log.exception(f"Problem updating reranking model: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


def _effective_video_max_size_mb(request: Request) -> int:
    """Return the effective video file size limit in MB.

    The effective limit is min(RAG_VIDEO_MAX_FILE_SIZE_MB, RAG_FILE_MAX_SIZE)
    when the global file limit is configured. If no global file limit exists,
    the video-specific limit applies.
    """
    video_limit = getattr(request.app.state.config, "RAG_VIDEO_MAX_FILE_SIZE_MB", 20)
    if hasattr(video_limit, "value"):
        video_limit = video_limit.value
    video_limit = int(video_limit) if video_limit else 20

    global_limit = getattr(request.app.state.config, "FILE_MAX_SIZE", None)
    if hasattr(global_limit, "value"):
        global_limit = global_limit.value

    if global_limit is not None and global_limit > 0:
        return min(video_limit, int(global_limit))
    return video_limit


@router.get("/config")
async def get_rag_config(request: Request, user=Depends(get_verified_user)):
    return {
        "status": True,
        "pdf_extract_images": request.app.state.config.PDF_EXTRACT_IMAGES,
        "RAG_FULL_CONTEXT": request.app.state.config.RAG_FULL_CONTEXT.get(user.email),
        "BYPASS_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL,
        "enable_google_drive_integration": request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
        "enable_onedrive_integration": request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION,
        "content_extraction": {
            "engine": request.app.state.config.CONTENT_EXTRACTION_ENGINE,
            "tika_server_url": request.app.state.config.TIKA_SERVER_URL,
            "document_intelligence_config": {
                "endpoint": request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
                "key": request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
            },
        },
        "chunk": {
            "text_splitter": request.app.state.config.TEXT_SPLITTER or "character",
            "chunk_size": (lambda v: v if v and v > 0 else 1000)(request.app.state.config.CHUNK_SIZE.get(user.email)),
            "chunk_overlap": (lambda v: v if v is not None and v > 0 else 200)(request.app.state.config.CHUNK_OVERLAP.get(user.email)),
        },
        "file": {
            "max_size": request.app.state.config.FILE_MAX_SIZE,
            "max_count": request.app.state.config.FILE_MAX_COUNT,
        },
        "video": {
            "max_file_size_mb": getattr(request.app.state.config, "RAG_VIDEO_MAX_FILE_SIZE_MB", 20),
            "effective_max_file_size_mb": _effective_video_max_size_mb(request),
            "chunk_duration_seconds": getattr(request.app.state.config, "RAG_VIDEO_CHUNK_DURATION", 16),
            "min_chunk_duration_seconds": getattr(request.app.state.config, "RAG_VIDEO_MIN_CHUNK_DURATION", 4),
            "max_duration_seconds": getattr(request.app.state.config, "RAG_VIDEO_MAX_DURATION", 120),
        },
        "youtube": {
            "language": request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            "translation": request.app.state.YOUTUBE_LOADER_TRANSLATION,
            "proxy_url": request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
        },
        "web": {
            "ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION": request.app.state.config.ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION,
            "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL.get(user.email),
            "search": {
                "enabled": request.app.state.config.ENABLE_RAG_WEB_SEARCH.get(user.email),
                "drive": request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
                "onedrive": request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION,
                "engine": request.app.state.config.RAG_WEB_SEARCH_ENGINE.get(user.email),
                "searxng_query_url": request.app.state.config.SEARXNG_QUERY_URL.get(user.email),
                "google_pse_api_key": request.app.state.config.GOOGLE_PSE_API_KEY.get(user.email),
                "google_pse_engine_id": request.app.state.config.GOOGLE_PSE_ENGINE_ID.get(user.email),
                "brave_search_api_key": request.app.state.config.BRAVE_SEARCH_API_KEY.get(user.email),
                "kagi_search_api_key": request.app.state.config.KAGI_SEARCH_API_KEY.get(user.email),
                "mojeek_search_api_key": request.app.state.config.MOJEEK_SEARCH_API_KEY.get(user.email),
                "bocha_search_api_key": request.app.state.config.BOCHA_SEARCH_API_KEY.get(user.email),
                "serpstack_api_key": request.app.state.config.SERPSTACK_API_KEY.get(user.email),
                "serpstack_https": request.app.state.config.SERPSTACK_HTTPS.get(user.email),
                "serper_api_key": request.app.state.config.SERPER_API_KEY.get(user.email),
                "serply_api_key": request.app.state.config.SERPLY_API_KEY.get(user.email),
                "tavily_api_key": request.app.state.config.TAVILY_API_KEY.get(user.email),
                "searchapi_api_key": request.app.state.config.SEARCHAPI_API_KEY.get(user.email),
                "searchapi_engine": request.app.state.config.SEARCHAPI_ENGINE.get(user.email),
                "serpapi_api_key": request.app.state.config.SERPAPI_API_KEY.get(user.email),
                "serpapi_engine": request.app.state.config.SERPAPI_ENGINE.get(user.email),
                "jina_api_key": request.app.state.config.JINA_API_KEY.get(user.email),
                "bing_search_v7_endpoint": request.app.state.config.BING_SEARCH_V7_ENDPOINT.get(user.email),
                "bing_search_v7_subscription_key": request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY.get(user.email),
                "exa_api_key": request.app.state.config.EXA_API_KEY.get(user.email),
                "result_count": request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(user.email),
                "trust_env": request.app.state.config.RAG_WEB_SEARCH_TRUST_ENV.get(user.email),
                "concurrent_requests": request.app.state.config.RAG_WEB_SEARCH_CONCURRENT_REQUESTS.get(user.email),
                "domain_filter_list": request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(user.email),
                "website_blocklist": request.app.state.config.RAG_WEB_SEARCH_WEBSITE_BLOCKLIST.get(user.email),
                "internal_facilities_sites": request.app.state.config.RAG_WEB_SEARCH_INTERNAL_FACILITIES_SITES.get(user.email),
            },
        },
    }


class FileConfig(BaseModel):
    max_size: Optional[int] = None
    max_count: Optional[int] = None


class DocumentIntelligenceConfigForm(BaseModel):
    endpoint: str
    key: str


class ContentExtractionConfig(BaseModel):
    engine: str = ""
    tika_server_url: Optional[str] = None
    document_intelligence_config: Optional[DocumentIntelligenceConfigForm] = None


class ChunkParamUpdateForm(BaseModel):
    text_splitter: Optional[str] = None
    chunk_size: int
    chunk_overlap: int


class YoutubeLoaderConfig(BaseModel):
    language: list[str]
    translation: Optional[str] = None
    proxy_url: str = ""


class WebSearchConfig(BaseModel):
    enabled: bool
    engine: Optional[str] = None
    searxng_query_url: Optional[str] = None
    google_pse_api_key: Optional[str] = None
    google_pse_engine_id: Optional[str] = None
    brave_search_api_key: Optional[str] = None
    kagi_search_api_key: Optional[str] = None
    mojeek_search_api_key: Optional[str] = None
    bocha_search_api_key: Optional[str] = None
    serpstack_api_key: Optional[str] = None
    serpstack_https: Optional[bool] = None
    serper_api_key: Optional[str] = None
    serply_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    searchapi_api_key: Optional[str] = None
    searchapi_engine: Optional[str] = None
    serpapi_api_key: Optional[str] = None
    serpapi_engine: Optional[str] = None
    jina_api_key: Optional[str] = None
    bing_search_v7_endpoint: Optional[str] = None
    bing_search_v7_subscription_key: Optional[str] = None
    exa_api_key: Optional[str] = None
    result_count: Optional[int] = None
    concurrent_requests: Optional[int] = None
    trust_env: Optional[bool] = None
    domain_filter_list: Optional[List[str]] = []
    website_blocklist: Optional[List[str]] = []
    internal_facilities_sites: Optional[List[str]] = []


class WebConfig(BaseModel):
    search: WebSearchConfig
    ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION: Optional[bool] = None
    BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL: Optional[bool] = None


class VideoConfig(BaseModel):
    max_file_size_mb: Optional[int] = None
    chunk_duration_seconds: Optional[int] = None
    min_chunk_duration_seconds: Optional[int] = None
    max_duration_seconds: Optional[int] = None


class ConfigUpdateForm(BaseModel):
    RAG_FULL_CONTEXT: Optional[bool] = None
    BYPASS_EMBEDDING_AND_RETRIEVAL: Optional[bool] = None
    pdf_extract_images: Optional[bool] = None
    enable_google_drive_integration: Optional[bool] = None
    enable_onedrive_integration: Optional[bool] = None
    file: Optional[FileConfig] = None
    video: Optional[VideoConfig] = None
    content_extraction: Optional[ContentExtractionConfig] = None
    chunk: Optional[ChunkParamUpdateForm] = None
    youtube: Optional[YoutubeLoaderConfig] = None
    web: Optional[WebConfig] = None


def _update_video_settings(request, video_config, user):
    """Atomically validate, persist, and audit video settings.

    Authorizes the caller, resolves omitted fields from current persisted values,
    validates the complete configuration, persists all changes, updates active
    PersistentConfig objects, and emits an audit log entry.

    Raises HTTPException on authorization failure or validation errors.
    Returns the complete configured and effective video configuration dict.
    """
    from open_webui.utils.super_admin import is_super_admin

    if not is_super_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super administrators can update video settings.",
        )

    config = request.app.state.config
    v = video_config

    # Resolve omitted fields from current persisted values
    def _current(attr, default):
        val = getattr(config, attr, default)
        return val.value if hasattr(val, "value") else val

    resolved_max_size = v.max_file_size_mb if v.max_file_size_mb is not None else int(_current("RAG_VIDEO_MAX_FILE_SIZE_MB", 20))
    resolved_chunk = v.chunk_duration_seconds if v.chunk_duration_seconds is not None else int(_current("RAG_VIDEO_CHUNK_DURATION", 16))
    resolved_min = v.min_chunk_duration_seconds if v.min_chunk_duration_seconds is not None else int(_current("RAG_VIDEO_MIN_CHUNK_DURATION", 4))
    resolved_max_dur = v.max_duration_seconds if v.max_duration_seconds is not None else int(_current("RAG_VIDEO_MAX_DURATION", 120))

    # Strict type validation — reject booleans, decimals, non-integer values
    errors = {}
    for name, val in [
        ("max_file_size_mb", resolved_max_size),
        ("chunk_duration_seconds", resolved_chunk),
        ("min_chunk_duration_seconds", resolved_min),
        ("max_duration_seconds", resolved_max_dur),
    ]:
        if isinstance(val, bool):
            errors[name] = "Must be an integer, not a boolean."
        elif isinstance(val, float) and not val.is_integer():
            errors[name] = "Must be an integer, not a decimal."

    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)

    # Range validation
    resolved_max_size = int(resolved_max_size)
    resolved_chunk = int(resolved_chunk)
    resolved_min = int(resolved_min)
    resolved_max_dur = int(resolved_max_dur)

    errors = {}
    if not (1 <= resolved_max_size <= 1024):
        errors["max_file_size_mb"] = "Must be between 1 and 1024 MB."
    if not (1 <= resolved_chunk <= 120):
        errors["chunk_duration_seconds"] = "Must be between 1 and 120 seconds."
    if resolved_min < 1:
        errors["min_chunk_duration_seconds"] = "Must be at least 1 second."
    if not (1 <= resolved_max_dur <= 3600):
        errors["max_duration_seconds"] = "Must be between 1 and 3600 seconds."
    if resolved_min >= resolved_chunk:
        errors["min_chunk_duration_seconds"] = "Must be less than chunk duration."

    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)

    # Capture old values for audit
    old_values = {
        "max_file_size_mb": int(_current("RAG_VIDEO_MAX_FILE_SIZE_MB", 20)),
        "chunk_duration": int(_current("RAG_VIDEO_CHUNK_DURATION", 16)),
        "min_chunk_duration": int(_current("RAG_VIDEO_MIN_CHUNK_DURATION", 4)),
        "max_duration": int(_current("RAG_VIDEO_MAX_DURATION", 120)),
    }

    from open_webui.config import (
        RAG_VIDEO_CHUNK_DURATION,
        RAG_VIDEO_MAX_DURATION,
        RAG_VIDEO_MAX_FILE_SIZE_MB,
        RAG_VIDEO_MIN_CHUNK_DURATION,
        save_persistent_config_values,
    )

    save_persistent_config_values(
        {
            "rag.video.max_file_size_mb": (
                RAG_VIDEO_MAX_FILE_SIZE_MB,
                resolved_max_size,
            ),
            "rag.video_chunk_duration": (
                RAG_VIDEO_CHUNK_DURATION,
                resolved_chunk,
            ),
            "rag.video_min_chunk_duration": (
                RAG_VIDEO_MIN_CHUNK_DURATION,
                resolved_min,
            ),
            "rag.video_max_duration": (
                RAG_VIDEO_MAX_DURATION,
                resolved_max_dur,
            ),
        }
    )

    new_values = {
        "max_file_size_mb": resolved_max_size,
        "chunk_duration": resolved_chunk,
        "min_chunk_duration": resolved_min,
        "max_duration": resolved_max_dur,
    }

    # Audit event
    log.info(
        "video_settings_updated",
        extra={
            "audit": True,
            "actor": user.email,
            "old_values": old_values,
            "new_values": new_values,
            "result": "success",
        },
    )

    return {
        "max_file_size_mb": resolved_max_size,
        "effective_max_file_size_mb": _effective_video_max_size_mb(request),
        "chunk_duration_seconds": resolved_chunk,
        "min_chunk_duration_seconds": resolved_min,
        "max_duration_seconds": resolved_max_dur,
    }


@router.post("/config/update")
async def update_rag_config(
    request: Request, form_data: ConfigUpdateForm, user=Depends(get_admin_user)
):
    # Authorize and validate the video block before mutating any other settings.
    if form_data.video is not None:
        _update_video_settings(request, form_data.video, user)

    request.app.state.config.PDF_EXTRACT_IMAGES = (
        form_data.pdf_extract_images
        if form_data.pdf_extract_images is not None
        else request.app.state.config.PDF_EXTRACT_IMAGES
    )

    if form_data.RAG_FULL_CONTEXT is not None:
        request.app.state.config.RAG_FULL_CONTEXT.set(user.email, form_data.RAG_FULL_CONTEXT)

    request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL = (
        form_data.BYPASS_EMBEDDING_AND_RETRIEVAL
        if form_data.BYPASS_EMBEDDING_AND_RETRIEVAL is not None
        else request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL
    )

    request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION = (
        form_data.enable_google_drive_integration
        if form_data.enable_google_drive_integration is not None
        else request.app.state.config.ENABLE_GOOGLE_DRIVE_INTEGRATION
    )

    request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION = (
        form_data.enable_onedrive_integration
        if form_data.enable_onedrive_integration is not None
        else request.app.state.config.ENABLE_ONEDRIVE_INTEGRATION
    )

    if form_data.file is not None:
        request.app.state.config.FILE_MAX_SIZE = form_data.file.max_size
        request.app.state.config.FILE_MAX_COUNT = form_data.file.max_count

    if form_data.content_extraction is not None:
        log.info(
            f"Updating content extraction: {request.app.state.config.CONTENT_EXTRACTION_ENGINE} to {form_data.content_extraction.engine}"
        )
        request.app.state.config.CONTENT_EXTRACTION_ENGINE = (
            form_data.content_extraction.engine
        )
        request.app.state.config.TIKA_SERVER_URL = (
            form_data.content_extraction.tika_server_url
        )
        if form_data.content_extraction.document_intelligence_config is not None:
            request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT = (
                form_data.content_extraction.document_intelligence_config.endpoint
            )
            request.app.state.config.DOCUMENT_INTELLIGENCE_KEY = (
                form_data.content_extraction.document_intelligence_config.key
            )

    if form_data.chunk is not None:
        requested_splitter = (form_data.chunk.text_splitter or "character").strip().lower()
        if requested_splitter in {"", "character", "recursive"}:
            requested_splitter = "character"
        elif requested_splitter in {"token", "tiktoken"}:
            requested_splitter = "token"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Text splitter must be character or token.",
            )
        request.app.state.config.TEXT_SPLITTER = requested_splitter
        # Validate and set chunk_size (must be > 0, default 1000)
        log.info(f"[CHUNK_UPDATE] Received chunk_size={form_data.chunk.chunk_size}, chunk_overlap={form_data.chunk.chunk_overlap} from user={user.email}")
        chunk_size = form_data.chunk.chunk_size if form_data.chunk.chunk_size and form_data.chunk.chunk_size > 0 else 1000
        # Validate and set chunk_overlap (must be > 0, default 200) - treat 0 as invalid
        chunk_overlap = form_data.chunk.chunk_overlap if form_data.chunk.chunk_overlap is not None and form_data.chunk.chunk_overlap > 0 else 200
        log.info(f"[CHUNK_UPDATE] Validated and saving chunk_size={chunk_size}, chunk_overlap={chunk_overlap} for user={user.email}")
        request.app.state.config.CHUNK_SIZE.set(user.email, chunk_size)
        request.app.state.config.CHUNK_OVERLAP.set(user.email, chunk_overlap)

    if form_data.youtube is not None:
        request.app.state.config.YOUTUBE_LOADER_LANGUAGE = form_data.youtube.language
        request.app.state.config.YOUTUBE_LOADER_PROXY_URL = form_data.youtube.proxy_url
        request.app.state.YOUTUBE_LOADER_TRANSLATION = form_data.youtube.translation

    if form_data.web is not None:
        request.app.state.config.ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION = (
            # Note: When UI "Bypass SSL verification for Websites"=True then ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION=False
            form_data.web.ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION
        )

        # request.app.state.config.ENABLE_RAG_WEB_SEARCH = form_data.web.search.enabled
        # request.app.state.config.RAG_WEB_SEARCH_ENGINE = form_data.web.search.engine

        request.app.state.config.ENABLE_RAG_WEB_SEARCH.set(user.email,form_data.web.search.enabled)
        request.app.state.config.RAG_WEB_SEARCH_ENGINE.set(user.email,form_data.web.search.engine) 

        # request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL = (
        #     form_data.web.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
        # )

        request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL.set(user.email,
            form_data.web.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL
        )

        request.app.state.config.SEARXNG_QUERY_URL.set(user.email,
            form_data.web.search.searxng_query_url
        )
        request.app.state.config.GOOGLE_PSE_API_KEY.set(user.email,
            form_data.web.search.google_pse_api_key
        )
        request.app.state.config.GOOGLE_PSE_ENGINE_ID.set(user.email,
            form_data.web.search.google_pse_engine_id
        )
        request.app.state.config.BRAVE_SEARCH_API_KEY.set(user.email,
            form_data.web.search.brave_search_api_key
        )
        request.app.state.config.KAGI_SEARCH_API_KEY.set(user.email,
            form_data.web.search.kagi_search_api_key
        )
        request.app.state.config.MOJEEK_SEARCH_API_KEY.set(user.email,
            form_data.web.search.mojeek_search_api_key
        )
        request.app.state.config.BOCHA_SEARCH_API_KEY.set(user.email,
            form_data.web.search.bocha_search_api_key
        )
        request.app.state.config.SERPSTACK_API_KEY.set(user.email,
            form_data.web.search.serpstack_api_key
        )
        request.app.state.config.SERPSTACK_HTTPS.set(user.email,form_data.web.search.serpstack_https)
        request.app.state.config.SERPER_API_KEY.set(user.email,form_data.web.search.serper_api_key)
        request.app.state.config.SERPLY_API_KEY.set(user.email, form_data.web.search.serply_api_key)
        request.app.state.config.TAVILY_API_KEY.set(user.email,form_data.web.search.tavily_api_key)
        request.app.state.config.SEARCHAPI_API_KEY.set(user.email,
            form_data.web.search.searchapi_api_key
        )
        request.app.state.config.SEARCHAPI_ENGINE.set(user.email,
            form_data.web.search.searchapi_engine
        )

        request.app.state.config.SERPAPI_API_KEY.set(user.email,form_data.web.search.serpapi_api_key)
        request.app.state.config.SERPAPI_ENGINE.set(user.email,form_data.web.search.serpapi_engine)

        request.app.state.config.JINA_API_KEY.set(user.email,form_data.web.search.jina_api_key)
        request.app.state.config.BING_SEARCH_V7_ENDPOINT.set(user.email,
            form_data.web.search.bing_search_v7_endpoint
        )
        request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY.set(user.email,
            form_data.web.search.bing_search_v7_subscription_key
        )

        request.app.state.config.EXA_API_KEY.set(user.email,form_data.web.search.exa_api_key)

        request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.set(user.email,
            form_data.web.search.result_count
        )
        request.app.state.config.RAG_WEB_SEARCH_CONCURRENT_REQUESTS.set(user.email,
            form_data.web.search.concurrent_requests
        )
        request.app.state.config.RAG_WEB_SEARCH_TRUST_ENV.set(user.email,
            form_data.web.search.trust_env
        )
        request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.set(user.email,
            form_data.web.search.domain_filter_list
        )
        request.app.state.config.RAG_WEB_SEARCH_WEBSITE_BLOCKLIST.set(user.email,
            form_data.web.search.website_blocklist
        )
        request.app.state.config.RAG_WEB_SEARCH_INTERNAL_FACILITIES_SITES.set(user.email,
            form_data.web.search.internal_facilities_sites
        )

    return {
        "status": True,
        "pdf_extract_images": request.app.state.config.PDF_EXTRACT_IMAGES,
        "RAG_FULL_CONTEXT": request.app.state.config.RAG_FULL_CONTEXT.get(user.email),
        "BYPASS_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL,
        "file": {
            "max_size": request.app.state.config.FILE_MAX_SIZE,
            "max_count": request.app.state.config.FILE_MAX_COUNT,
        },
        "video": {
            "max_file_size_mb": getattr(request.app.state.config, "RAG_VIDEO_MAX_FILE_SIZE_MB", 20),
            "effective_max_file_size_mb": _effective_video_max_size_mb(request),
            "chunk_duration_seconds": getattr(request.app.state.config, "RAG_VIDEO_CHUNK_DURATION", 16),
            "min_chunk_duration_seconds": getattr(request.app.state.config, "RAG_VIDEO_MIN_CHUNK_DURATION", 4),
            "max_duration_seconds": getattr(request.app.state.config, "RAG_VIDEO_MAX_DURATION", 120),
        },
        "content_extraction": {
            "engine": request.app.state.config.CONTENT_EXTRACTION_ENGINE,
            "tika_server_url": request.app.state.config.TIKA_SERVER_URL,
            "document_intelligence_config": {
                "endpoint": request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
                "key": request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
            },
        },
        "chunk": {
            "text_splitter": request.app.state.config.TEXT_SPLITTER or "character",
            "chunk_size": (lambda v: v if v and v > 0 else 1000)(request.app.state.config.CHUNK_SIZE.get(user.email)),
            "chunk_overlap": (lambda v: v if v is not None and v > 0 else 200)(request.app.state.config.CHUNK_OVERLAP.get(user.email)),
        },
        "youtube": {
            "language": request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            "proxy_url": request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
            "translation": request.app.state.YOUTUBE_LOADER_TRANSLATION,
        },
        "web": {
            "ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION": request.app.state.config.ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION,
            "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL": request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL.get(user.email),
            "search": {
                "enabled": request.app.state.config.ENABLE_RAG_WEB_SEARCH.get(user.email),
                "engine": request.app.state.config.RAG_WEB_SEARCH_ENGINE.get(user.email),
                "searxng_query_url": request.app.state.config.SEARXNG_QUERY_URL.get(user.email),
                "google_pse_api_key": request.app.state.config.GOOGLE_PSE_API_KEY.get(user.email),
                "google_pse_engine_id": request.app.state.config.GOOGLE_PSE_ENGINE_ID.get(user.email),
                "brave_search_api_key": request.app.state.config.BRAVE_SEARCH_API_KEY.get(user.email),
                "kagi_search_api_key": request.app.state.config.KAGI_SEARCH_API_KEY.get(user.email),
                "mojeek_search_api_key": request.app.state.config.MOJEEK_SEARCH_API_KEY.get(user.email),
                "bocha_search_api_key": request.app.state.config.BOCHA_SEARCH_API_KEY.get(user.email),
                "serpstack_api_key": request.app.state.config.SERPSTACK_API_KEY.get(user.email),
                "serpstack_https": request.app.state.config.SERPSTACK_HTTPS.get(user.email),
                "serper_api_key": request.app.state.config.SERPER_API_KEY.get(user.email),
                "serply_api_key": request.app.state.config.SERPLY_API_KEY.get(user.email),
                "searchapi_api_key": request.app.state.config.SEARCHAPI_API_KEY.get(user.email),
                "searchapi_engine": request.app.state.config.SEARCHAPI_ENGINE.get(user.email),
                "serpapi_api_key": request.app.state.config.SERPAPI_API_KEY.get(user.email),
                "serpapi_engine": request.app.state.config.SERPAPI_ENGINE.get(user.email),
                "tavily_api_key": request.app.state.config.TAVILY_API_KEY.get(user.email),
                "jina_api_key": request.app.state.config.JINA_API_KEY.get(user.email),
                "bing_search_v7_endpoint": request.app.state.config.BING_SEARCH_V7_ENDPOINT.get(user.email),
                "bing_search_v7_subscription_key": request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY.get(user.email),
                "exa_api_key": request.app.state.config.EXA_API_KEY.get(user.email),
                "result_count": request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(user.email),
                "concurrent_requests": request.app.state.config.RAG_WEB_SEARCH_CONCURRENT_REQUESTS.get(user.email),
                "trust_env": request.app.state.config.RAG_WEB_SEARCH_TRUST_ENV.get(user.email),
                "domain_filter_list": request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(user.email),
                "website_blocklist": request.app.state.config.RAG_WEB_SEARCH_WEBSITE_BLOCKLIST.get(user.email),
                "internal_facilities_sites": request.app.state.config.RAG_WEB_SEARCH_INTERNAL_FACILITIES_SITES.get(user.email),
            },
        },
    }


@router.get("/template")
async def get_rag_template(request: Request, user=Depends(get_verified_user)):
    return {
        "status": True,
        "template": request.app.state.config.RAG_TEMPLATE.get(user.email),
    }


@router.get("/query/settings")
async def get_query_settings(request: Request, user=Depends(get_verified_user)):
    return {
        "status": True,
        "template": request.app.state.config.RAG_TEMPLATE.get(user.email),
        "k": request.app.state.config.TOP_K.get(user.email),
        "r": request.app.state.config.RELEVANCE_THRESHOLD,
        "hybrid": request.app.state.config.ENABLE_RAG_HYBRID_SEARCH.get(user.email),
    }


class QuerySettingsForm(BaseModel):
    k: Optional[int] = None
    r: Optional[float] = None
    template: Optional[str] = None
    hybrid: Optional[bool] = None


@router.post("/query/settings/update")
async def update_query_settings(
    request: Request, form_data: QuerySettingsForm, user=Depends(get_admin_user)
):
    request.app.state.config.RAG_TEMPLATE.set(user.email,form_data.template)
    # Only update TOP_K if explicitly provided - otherwise keep existing value (defaults to 10)
    if form_data.k is not None:
        request.app.state.config.TOP_K.set(user.email, form_data.k)
    request.app.state.config.RELEVANCE_THRESHOLD = form_data.r if form_data.r else 1

    if form_data.hybrid is not None:
        request.app.state.config.ENABLE_RAG_HYBRID_SEARCH.set(user.email, form_data.hybrid)
    else:
        request.app.state.config.ENABLE_RAG_HYBRID_SEARCH.set(user.email,False)


    return {
        "status": True,
        "template": request.app.state.config.RAG_TEMPLATE.get(user.email),
        "k": request.app.state.config.TOP_K.get(user.email),
        "r": request.app.state.config.RELEVANCE_THRESHOLD,
        "hybrid": request.app.state.config.ENABLE_RAG_HYBRID_SEARCH.get(user.email),
    }


####################################
#
# Document process and retrieval
#
####################################

def _get_user_chunk_settings(request: Request, user=None):
    """
    Helper function to safely get user chunk settings.
    Handles cases where user is None (background tasks).
    """
    user_email = user.email if user and hasattr(user, 'email') else None
    if user_email:
        chunk_size = request.app.state.config.CHUNK_SIZE.get(user_email)
        chunk_overlap = request.app.state.config.CHUNK_OVERLAP.get(user_email)
        # Ensure defaults if get() returns None or invalid values (0 is invalid)
        if not chunk_size or chunk_size <= 0:
            chunk_size = 1000
        if not chunk_overlap or chunk_overlap < 0:
            chunk_overlap = 200
    else:
        # Use default chunk size if user is not available
        chunk_size = 1000
        chunk_overlap = 200
    return user_email, chunk_size, chunk_overlap


def _resolve_model_aware_ingestion(
    *,
    admin_id: Optional[str],
    embedding_model_id: Optional[str],
    file_id: Optional[str],
    texts: list[str],
    metadatas: list[dict],
):
    """Phase 3: persist rag_chunks and resolve the model spec for file ingestion.

    Returns (model_spec, rag_chunk_ids) when the caller resolved a model-aware
    admin/model context and a file_id is present; otherwise (None, None) so the
    legacy ingestion path runs unchanged.
    """
    if not (admin_id and embedding_model_id and file_id):
        return None, None
    from open_webui.retrieval.embedding.registry import get_model_spec_by_id
    from open_webui.models.embeddings import RagChunk

    model_spec = get_model_spec_by_id(embedding_model_id)
    chunks = [
        {"content": text, "content_type": "text", "chunk_metadata": metadatas[idx]}
        for idx, text in enumerate(texts)
    ]
    rag_chunk_ids = RagChunk.insert_chunks(admin_id, file_id, chunks)
    return model_spec, rag_chunk_ids


def save_docs_to_vector_db(
    request: Request,
    docs,
    collection_name,
    metadata: Optional[dict] = None,
    overwrite: bool = False,
    split: bool = True,
    add: bool = False,
    user=None,
    embedding_function: Callable = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_id: Optional[str] = None,
) -> bool:
    def _get_docs_info(docs: list[Document]) -> str:
        docs_info = set()

        # Trying to select relevant metadata identifying the document.
        for doc in docs:
            metadata = getattr(doc, "metadata", {})
            doc_name = metadata.get("name", "")
            if not doc_name:
                doc_name = metadata.get("title", "")
            if not doc_name:
                doc_name = metadata.get("source", "")
            if doc_name:
                docs_info.add(doc_name)

        return ", ".join(docs_info)

    log.info(
        f"save_docs_to_vector_db: document {_get_docs_info(docs)} {collection_name}"
    )

    # Create OTEL span for embedding generation and vector DB insertion
    # CRITICAL: Use safe_trace_span to ensure OTEL failures never prevent embedding
    with safe_trace_span(
        name="file.embedding.save",
        attributes={
            "collection.name": collection_name,
            "document.count": len(docs),
            "embedding.engine": request.app.state.config.RAG_EMBEDDING_ENGINE if request and hasattr(request.app.state, 'config') else None,
            # Note: embedding.model will be set dynamically based on owner_email (per-admin)
            "embedding.model": "per-admin" if request and hasattr(request.app.state, 'config') else None,
        },
    ) as span:
        try:
            # Check if entries with the same hash (metadata.hash) already exist
            if metadata and "hash" in metadata:
                result = VECTOR_DB_CLIENT.query(
                    collection_name=collection_name,
                    filter={"hash": metadata["hash"]},
                )

                if result is not None:
                    existing_doc_ids = result.ids[0]
                    if existing_doc_ids:
                        log.info(f"Document with hash {metadata['hash']} already exists")
                        raise ValueError(ERROR_MESSAGES.DUPLICATE_CONTENT)

            # BUG #8 fix: Validate docs are not empty before splitting
            if len(docs) == 0:
                error_msg = (
                    f"[Embedding Failed] No documents to process. "
                    f"collection_name={collection_name} | "
                    f"This usually means the file content extraction returned empty text. "
                    f"Check the '[Content Extraction ERROR]' log above for details."
                )
                log.error(error_msg)
                raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

            if split:
                user_email, chunk_size, chunk_overlap = _get_user_chunk_settings(request, user)
                log.info(f"[Splitting] user={user_email or 'background'} | chunk_size={chunk_size} | chunk_overlap={chunk_overlap}")

                # CRITICAL: Validate chunk_size to prevent character-level splitting
                if chunk_size <= 0:
                    error_msg = (
                        f"Invalid chunk_size={chunk_size}. "
                        f"chunk_size must be > 0 (typically 500-2000). "
                        f"This prevents character-level splitting which creates thousands of invalid chunks. "
                        f"Please configure chunk_size in Settings > Documents."
                    )
                    log.error(error_msg)
                    raise ValueError(error_msg)
                
                if chunk_overlap < 0:
                    log.warning(f"chunk_overlap={chunk_overlap} is negative, setting to 0")
                    chunk_overlap = 0
                
                if chunk_overlap >= chunk_size:
                    log.warning(
                        f"chunk_overlap={chunk_overlap} >= chunk_size={chunk_size}, "
                        f"setting overlap to {chunk_size // 4} (25% of chunk_size)"
                    )
                    chunk_overlap = chunk_size // 4

                if request.app.state.config.TEXT_SPLITTER in ["", "character"]:
                    text_splitter = RecursiveCharacterTextSplitter(
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        add_start_index=True,
                    )
                elif request.app.state.config.TEXT_SPLITTER == "token":
                    log.info(
                        f"Using token text splitter: {request.app.state.config.TIKTOKEN_ENCODING_NAME}"
                    )

                    tiktoken.get_encoding(str(request.app.state.config.TIKTOKEN_ENCODING_NAME))
                    text_splitter = TokenTextSplitter(
                        encoding_name=str(request.app.state.config.TIKTOKEN_ENCODING_NAME),
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        add_start_index=True,
                    )
                else:
                    raise ValueError(ERROR_MESSAGES.DEFAULT("Invalid text splitter"))

                split_start = time.time()
                docs = text_splitter.split_documents(docs)
                split_end = time.time()
                split_duration = split_end - split_start
                log.info(f"[RAG Chunking] chunks_created={len(docs)} | collection_name={collection_name} | duration={split_duration:.2f}s | timestamp={split_end:.3f}")
                log.info(f"[SPLITTING] COMPLETE | chunks={len(docs)} | duration={split_duration:.2f}s | timestamp={split_end:.3f}")
                safe_add_span_event("embedding.split.completed", {"chunk.count": len(docs)})
                safe_set_span_attribute(span, "chunk.count", len(docs))

            if len(docs) == 0:
                # Provide detailed error for debugging empty content issues
                log.error(
                    f"[Embedding Failed] No content to embed after text splitting. "
                    f"collection_name={collection_name} | "
                    f"This usually means the file content extraction returned empty text. "
                    f"Check the '[Content Extraction WARNING]' log above for details and suggestions."
                )
                raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

            texts = [doc.page_content for doc in docs]
            metadatas = [
                {
                    **doc.metadata,
                    **(metadata if metadata else {}),
                    "embedding_config": json.dumps(
                        {
                            "engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
                            "model": request.app.state.config.RAG_EMBEDDING_MODEL,
                        }
                    ),
                }
                for doc in docs
            ]

            file_id = metadata.get("file_id") if isinstance(metadata, dict) else None
            model_spec, rag_chunk_ids = _resolve_model_aware_ingestion(
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                file_id=file_id,
                texts=texts,
                metadatas=metadatas,
            )

            # ChromaDB does not like datetime formats
            # for meta-data so convert them to string.
            for metadata in metadatas:
                for key, value in metadata.items():
                    if (
                        isinstance(value, datetime)
                        or isinstance(value, list)
                        or isinstance(value, dict)
                    ):
                        metadata[key] = str(value)

            try:
                if VECTOR_DB_CLIENT.has_collection(collection_name=collection_name):
                    log.info(f"collection {collection_name} already exists")

                    if overwrite:
                        VECTOR_DB_CLIENT.delete_collection(collection_name=collection_name)
                        log.info(f"deleting existing collection {collection_name}")
                    elif add is False:
                        log.info(
                            f"collection {collection_name} already exists, overwrite is False and add is False"
                        )
                        return True

                log.info(f"adding to collection {collection_name}")
                
                # Credential-safe: Use the provided embedding_function
                if embedding_function is None:
                    raise ValueError("No embedding function provided. Cannot generate embeddings.")
                
                # Generate embeddings using the provided function
                embed_api_start = time.time()
                log.info(f"Generating embeddings for {len(texts)} chunks")
                
                safe_add_span_event("embedding.generation.started", {"text.count": len(texts)})
                
                try:
                    embeddings = embedding_function(
                        list(map(lambda x: x.replace("\n", " "), texts)), user=user
                    )
                    embed_api_end = time.time()
                    log.info(f"[EMBED_API] COMPLETE | chunks={len(texts)} | duration={embed_api_end - embed_api_start:.2f}s")
                    
                    if not embeddings or len(embeddings) == 0:
                        raise ValueError("Embedding generation returned empty result")
                    
                    if len(embeddings) != len(texts):
                        raise ValueError(f"Embedding count mismatch: expected {len(texts)}, got {len(embeddings)}")
                    
                    safe_add_span_event("embedding.generation.completed", {"embedding.count": len(embeddings)})
                except EmbeddingError as e:
                    safe_add_span_event("embedding.generation.failed", {"error.code": e.code})
                    raise
                except Exception as embed_error:
                    safe_add_span_event("embedding.generation.failed", {
                        "error.type": type(embed_error).__name__,
                    })
                    raise

                print(f"  [STEP 7] Preparing items for vector DB insertion:", flush=True)
                print(f"    collection_name: {collection_name}", flush=True)
                print(f"    items count: {len(texts)}", flush=True)
                log.info(f"  [STEP 7] Preparing items for vector DB insertion:")
                log.info(f"    collection_name: {collection_name}, items count: {len(texts)}")
                
                if rag_chunk_ids is not None:
                    from open_webui.retrieval.vector.model_aware import (
                        ModelAwareVectorRepository,
                    )

                    vector_repo = ModelAwareVectorRepository()
                    items = vector_repo.make_items(
                        texts=texts,
                        vectors=embeddings,
                        metadata=metadatas,
                        rag_chunk_ids=rag_chunk_ids,
                        admin_id=admin_id,
                        model=model_spec,
                        file_id=file_id,
                        knowledge_id=knowledge_id,
                    )
                else:
                    items = [
                        {
                            "id": str(uuid.uuid4()),
                            "text": text,
                            "vector": embeddings[idx],
                            "metadata": metadatas[idx],
                        }
                        for idx, text in enumerate(texts)
                    ]
                
                print(f"  [STEP 7.1] Items prepared, inserting into vector DB...", flush=True)
                log.info(f"  [STEP 7.1] Items prepared, inserting into vector DB...")

                safe_add_span_event("vector_db.insert.started", {"item.count": len(items)})

                try:
                    if rag_chunk_ids is not None:
                        # Spec 07: transactional per-projection reconcile keyed by
                        # (admin_id, embedding_model_id, rag_chunk_id, collection_name).
                        # Current rows are upserted and stale rows for this
                        # projection only are deleted in the same transaction.
                        vector_repo.reconcile_model_aware(
                            collection_name=collection_name,
                            items=items,
                            model=model_spec,
                        )
                    else:
                        VECTOR_DB_CLIENT.insert(
                            collection_name=collection_name,
                            items=items,
                        )
                    print(f"  [STEP 7.1] ✅ Successfully inserted {len(items)} items into collection: {collection_name}", flush=True)
                    log.info(f"  [STEP 7.1] ✅ Successfully inserted {len(items)} items into collection: {collection_name}")
                    safe_add_span_event("vector_db.insert.completed", {"item.count": len(items)})
                except Exception as insert_error:
                    error_msg = f"Failed to insert into vector DB collection {collection_name}: {insert_error}"
                    print(f"  [STEP 7.1] ❌ {error_msg}", flush=True)
                    log.error(f"  [STEP 7.1] ❌ {error_msg}", exc_info=True)
                    safe_add_span_event("vector_db.insert.failed", {
                        "error.type": type(insert_error).__name__,
                        "error.message": str(insert_error)[:200],
                    })
                    raise

                print(f"[EMBEDDING] ✅ Embeddings saved successfully", flush=True)
                log.info(f"[EMBEDDING] ✅ Embeddings saved successfully")
                print("=" * 80, flush=True)
                log.info("=" * 80)

                return True
            except Exception as e:
                log.exception(e)
                safe_add_span_event("file.embedding.save.error", {
                    "error.type": type(e).__name__,
                    "error.message": str(e)[:200],
                })
                raise e
        except Exception as e:
            log.exception(e)
            safe_add_span_event("file.embedding.save.error", {
                "error.type": type(e).__name__,
                "error.message": str(e)[:200],
            })
            raise e


def get_embeddings_with_fallback(
    embedding_engine: str,
    embedding_model: str,
    embedding_function: Callable,
    url: str,
    key: str,
    embedding_batch_size: int,
    texts: list[str],
    get_single_batch_embedding_function: Callable,
    get_embedding_function: Callable,
    user: Optional[Any] = None,
    backoff: bool = True,
) -> list[list[float]]:
    """
    Generate embeddings with a fallback mechanism to the default method of OpenWebUI with multiple API calls for each chunk

    Returns:
        list[list[float]]: List of embeddings for the input texts.
    """
    # Create OTEL span for embedding API calls
    # CRITICAL: Use safe_trace_span to ensure OTEL failures never prevent embedding generation
    with safe_trace_span(
        name="file.embedding.generate",
        attributes={
            "embedding.engine": embedding_engine,
            "embedding.model": embedding_model,
            "text.count": len(texts),
            "embedding.batch_size": embedding_batch_size,
        },
    ) as span:
        try:
            # First, try single batch embedding function
            logging.info(f"Generating embeddings for {len(texts)} chunks in a single batch")
            safe_add_span_event("embedding.api.request", {"method": "single_batch"})
            
            single_batch_func = get_single_batch_embedding_function(
                embedding_engine,
                embedding_model,
                embedding_function,
                url,
                key,
                embedding_batch_size,
                backoff=False,
            )

            # Explicitly try to generate embeddings with the single batch function
            result = single_batch_func(texts, user)
            safe_add_span_event("embedding.api.response", {
                "status": "success",
                "method": "single_batch",
                "embedding.count": len(result) if result else 0,
            })
            return result

        except Exception as e:
            # Log the specific error from single batch attempt
            logging.warning(f"Single batch embedding failed. Error: {str(e)}")
            logging.warning(f"Falling back to batched embedding function")
            
            # Set fallback attribute
            safe_set_span_attribute(span, "embedding.fallback_used", True)
            safe_add_span_event("embedding.api.fallback", {
                "error.type": type(e).__name__,
                "error.message": str(e)[:200],
            })

            # Fallback to the original get_embedding_function
            fallback_func = get_embedding_function(
                embedding_engine,
                embedding_model,
                embedding_function,
                url,
                key,
                embedding_batch_size,
                backoff=True,
            )

            # Return the result from the fallback function
            try:
                result = fallback_func(texts, user)
                safe_add_span_event("embedding.api.response", {
                    "status": "success",
                    "method": "fallback",
                    "embedding.count": len(result) if result else 0,
                })
                return result
            except Exception as fallback_error:
                safe_add_span_event("embedding.api.fallback_failed", {
                    "error.type": type(fallback_error).__name__,
                    "error.message": str(fallback_error)[:200],
                })
                raise


def save_docs_to_multiple_collections(
    request: Request,
    docs,
    collections: list[str],
    metadata: Optional[dict] = None,
    overwrite: bool = False,
    split: bool = True,
    user=None,
    embedding_function: Callable = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
    knowledge_id: Optional[str] = None,
) -> bool:
    """
    Save documents to multiple collections using a single embedding operation
    """

    def _get_docs_info(docs: list[Document]) -> str:
        docs_info = set()

        # Trying to select relevant metadata identifying the document.
        for doc in docs:
            metadata = getattr(doc, "metadata", {})
            doc_name = metadata.get("name", "")
            if not doc_name:
                doc_name = metadata.get("title", "")
            if not doc_name:
                doc_name = metadata.get("source", "")
            if doc_name:
                docs_info.add(doc_name)

        return ", ".join(docs_info)

    log.info(
        f"save_docs_to_multiple_collections: document {_get_docs_info(docs)} to collections {collections}"
    )

    # Check if entries with the same hash (metadata.hash) already exist in any collection (BUG #14 fix)
    if metadata and "hash" in metadata:
        # Check all collections, not just collections[1]
        for collection_name in collections:
            result = VECTOR_DB_CLIENT.query(
                collection_name=collection_name,
                filter={"hash": metadata["hash"]},
            )

            if result is not None:
                existing_doc_ids = result.ids[0]
                if existing_doc_ids:
                    error_msg = f"Document with hash {metadata['hash']} already exists in collection {collection_name}"
                    print(f"[DUPLICATE CHECK] ❌ {error_msg}", flush=True)
                    log.info(error_msg)
                    raise ValueError(ERROR_MESSAGES.DUPLICATE_CONTENT)

    # BUG #8 fix: Validate docs are not empty before splitting
    if len(docs) == 0:
        error_msg = (
            f"[Embedding Failed] No documents to process. "
            f"collections={collections} | "
            f"This usually means the file content extraction returned empty text. "
            f"Check the '[Content Extraction ERROR]' log above for details."
        )
        log.error(error_msg)
        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

    if split:
        user_email, chunk_size, chunk_overlap = _get_user_chunk_settings(request, user)
        log.info(f"[Splitting] user={user_email or 'background'} | chunk_size={chunk_size} | chunk_overlap={chunk_overlap}")
        if request.app.state.config.TEXT_SPLITTER in ["", "character"]:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                add_start_index=True,
            )
        elif request.app.state.config.TEXT_SPLITTER == "token":
            log.info(
                f"Using token text splitter: {request.app.state.config.TIKTOKEN_ENCODING_NAME}"
            )

            tiktoken.get_encoding(str(request.app.state.config.TIKTOKEN_ENCODING_NAME))
            text_splitter = TokenTextSplitter(
                encoding_name=str(request.app.state.config.TIKTOKEN_ENCODING_NAME),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                add_start_index=True,
            )
        else:
            raise ValueError(ERROR_MESSAGES.DEFAULT("Invalid text splitter"))

        docs = text_splitter.split_documents(docs)
        log.info(f"[RAG Chunking] chunks_created={len(docs)} | collections={list(collections)} | (multi-collection save)")

    if len(docs) == 0:
        # Provide detailed error for debugging empty content issues (multiple collections)
        log.error(
            f"[Embedding Failed] No content to embed after text splitting. "
            f"collections={collections} | "
            f"This usually means the file content extraction returned empty text. "
            f"Check the '[Content Extraction WARNING]' log above for details and suggestions."
        )
        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

    # Credential-safe: Validate embedding_function is provided
    if embedding_function is None:
        raise ValueError("No embedding function provided. Cannot generate embeddings.")
    
    texts = [doc.page_content for doc in docs]
    metadatas = [
        {
            **doc.metadata,
            **(metadata if metadata else {}),
        }
        for doc in docs
    ]

    file_id = metadata.get("file_id") if isinstance(metadata, dict) else None
    model_spec, rag_chunk_ids = _resolve_model_aware_ingestion(
        admin_id=admin_id,
        embedding_model_id=embedding_model_id,
        file_id=file_id,
        texts=texts,
        metadatas=metadatas,
    )

    # ChromaDB does not like datetime formats
    # for meta-data so convert them to string.
    for metadata in metadatas:
        for key, value in metadata.items():
            if (
                isinstance(value, datetime)
                or isinstance(value, list)
                or isinstance(value, dict)
            ):
                metadata[key] = str(value)

    try:
        # Check and prepare collections
        for collection_name in collections:
            if not VECTOR_DB_CLIENT.has_collection(collection_name=collection_name):
                log.info(f"Creating new collection {collection_name}")
            else:
                log.info(f"Collection {collection_name} already exists")
                if overwrite:
                    VECTOR_DB_CLIENT.delete_collection(collection_name=collection_name)
                    log.info(f"Deleting existing collection {collection_name}")

        # Credential-safe: Use the provided embedding_function
        log.info(f"Generating embeddings for {len(texts)} chunks")
        
        try:
            embeddings = embedding_function(
                list(map(lambda x: x.replace("\n", " "), texts)), user=user
            )
            
            if not embeddings or len(embeddings) == 0:
                raise ValueError("Embedding generation returned empty result")
            
            if len(embeddings) != len(texts):
                raise ValueError(f"Embedding count mismatch: expected {len(texts)}, got {len(embeddings)}")
            
            log.info(f"Embeddings generated successfully: {len(embeddings)} vectors")
        except EmbeddingError as e:
            log.error(f"Embedding failed: {e.code}")
            raise
        except Exception as embed_error:
            log.error(f"Failed to generate embeddings: {embed_error}")
            raise

        # Insert embeddings into all collections
        print(f"  [STEP 7] Inserting embeddings into {len(collections)} collection(s): {collections}", flush=True)
        log.info(f"  [STEP 7] Inserting embeddings into {len(collections)} collection(s): {collections}")
        
        for col_idx, collection_name in enumerate(collections):
            print(f"  [STEP 7.{col_idx+1}] Processing collection: {collection_name}", flush=True)
            log.info(f"  [STEP 7.{col_idx+1}] Processing collection: {collection_name}")
            
            if rag_chunk_ids is not None:
                from open_webui.retrieval.vector.model_aware import (
                    ModelAwareVectorRepository,
                )

                vector_repo = ModelAwareVectorRepository()
                items = vector_repo.make_items(
                    texts=texts,
                    vectors=embeddings,
                    metadata=metadatas,
                    rag_chunk_ids=rag_chunk_ids,
                    admin_id=admin_id,
                    model=model_spec,
                    file_id=file_id,
                    knowledge_id=knowledge_id,
                )
            else:
                items = [
                    {
                        "id": str(uuid.uuid4()),
                        "text": text,
                        "vector": embeddings[text_idx],
                        "metadata": metadatas[text_idx],
                    }
                    for text_idx, text in enumerate(texts)
                ]
            
            print(f"    Preparing {len(items)} items for insertion", flush=True)
            log.info(f"    Preparing {len(items)} items for insertion")

            try:
                if rag_chunk_ids is not None:
                    # Spec 07: transactional per-projection reconcile keyed by
                    # (admin_id, embedding_model_id, rag_chunk_id, collection_name).
                    # Current rows are upserted and stale rows for this
                    # projection only are deleted in the same transaction, so
                    # one collection's re-ingestion never touches another
                    # membership's rows.
                    vector_repo.reconcile_model_aware(
                        collection_name=collection_name,
                        items=items,
                        model=model_spec,
                    )
                else:
                    VECTOR_DB_CLIENT.insert(
                        collection_name=collection_name,
                        items=items,
                    )
                print(f"  [STEP 7.{col_idx+1}] ✅ Successfully inserted into collection: {collection_name}", flush=True)
                log.info(f"  [STEP 7.{col_idx+1}] ✅ Successfully inserted into collection: {collection_name}")
            except Exception as insert_error:
                error_msg = f"Failed to insert into collection {collection_name}: {insert_error}"
                print(f"  [STEP 7.{col_idx+1}] ❌ {error_msg}", flush=True)
                log.error(f"  [STEP 7.{col_idx+1}] ❌ {error_msg}", exc_info=True)
                # BUG FIX: Don't continue if one collection fails - raise exception
                raise ValueError(error_msg)

        print(f"[EMBEDDING] ✅ All embeddings saved successfully", flush=True)
        log.info(f"[EMBEDDING] ✅ All embeddings saved successfully")
        print("=" * 80, flush=True)
        log.info("=" * 80)
        
        return True
    except Exception as e:
        log.exception(e)
        raise e


class ProcessFileForm(BaseModel):
    file_id: str
    content: Optional[str] = None
    collection_name: Optional[str] = None


def _claim_file_processing_dispatch(
    file_id: str,
    stale_pending_seconds: int,
) -> tuple[bool, dict[str, Any], Optional[str], bool]:
    """Atomically claim a file-processing dispatch lease.

    A running worker (``processing``) is never reclaimable. A ``pending``
    dispatch is reclaimable only after its last durable update has aged past
    the configured bound. The updated-at compare-and-swap complements the row
    lock for databases such as SQLite that do not implement ``FOR UPDATE``.
    """

    now = int(time.time())
    with get_db() as db:
        file_row = (
            db.query(FileRecord)
            .filter(FileRecord.id == file_id)
            .with_for_update()
            .first()
        )
        if file_row is None:
            return False, {}, None, False

        meta = dict(file_row.meta or {})
        raw_status = meta.get("processing_status")
        if raw_status is not None and not isinstance(raw_status, str):
            # Fail closed on malformed state rather than overwrite a status
            # that cannot be compared portably across supported databases.
            return False, meta, None, False
        current_status = raw_status

        if current_status == "processing":
            return False, meta, current_status, False

        reclaiming_stale_pending = False
        if current_status == "pending":
            lease_at = file_row.updated_at
            if not isinstance(lease_at, int) or isinstance(lease_at, bool):
                lease_at = file_row.created_at
            if not isinstance(lease_at, int) or isinstance(lease_at, bool):
                # A pending row without a trustworthy lease timestamp cannot
                # be reclaimed without risking duplicate live work.
                return False, meta, current_status, False
            if now - lease_at < stale_pending_seconds:
                return False, meta, current_status, False
            reclaiming_stale_pending = True

        observed_updated_at = file_row.updated_at
        claimed_updated_at = now + 1 if observed_updated_at == now else now
        claimed_meta = {**meta, "processing_status": "pending"}

        claim_query = db.query(FileRecord).filter(FileRecord.id == file_id)
        if observed_updated_at is None:
            claim_query = claim_query.filter(FileRecord.updated_at.is_(None))
        else:
            claim_query = claim_query.filter(
                FileRecord.updated_at == observed_updated_at
            )

        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            status_expression = cast(FileRecord.meta, JSONB)[
                "processing_status"
            ].astext
        elif dialect_name == "sqlite":
            status_expression = func.json_extract(
                FileRecord.meta,
                "$.processing_status",
            )
        else:
            # JSONField is text-backed, so exact metadata comparison remains a
            # safe compare-and-swap fallback for other SQL dialects.
            status_expression = None

        if status_expression is None:
            if file_row.meta is None:
                claim_query = claim_query.filter(FileRecord.meta.is_(None))
            else:
                claim_query = claim_query.filter(FileRecord.meta == file_row.meta)
        elif current_status is None:
            claim_query = claim_query.filter(status_expression.is_(None))
        else:
            claim_query = claim_query.filter(status_expression == current_status)

        claimed = (
            claim_query.update(
                {
                    FileRecord.meta: claimed_meta,
                    FileRecord.updated_at: claimed_updated_at,
                },
                synchronize_session=False,
            )
            == 1
        )
        if claimed:
            db.commit()
            return True, claimed_meta, "pending", reclaiming_stale_pending

        db.rollback()
        latest_row = db.query(FileRecord).filter(FileRecord.id == file_id).first()
        if latest_row is None:
            return False, {}, None, False
        latest_meta = dict(latest_row.meta or {})
        latest_status = latest_meta.get("processing_status")
        if not isinstance(latest_status, str):
            latest_status = None
        return False, latest_meta, latest_status, False


def _effective_process_knowledge_id(
    form_data: ProcessFileForm,
    knowledge_id: Optional[str],
) -> Optional[str]:
    collection_knowledge_id = (
        form_data.collection_name
        if form_data.collection_name
        and form_data.collection_name != f"file-{form_data.file_id}"
        else None
    )
    if (
        knowledge_id
        and collection_knowledge_id
        and knowledge_id != collection_knowledge_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conflicting knowledge collection IDs.",
        )
    return knowledge_id or collection_knowledge_id


def _require_file_processing_access(
    *,
    file: FileModel,
    user,
    knowledge_id: Optional[str],
):
    is_admin = user.role == "admin"
    is_file_owner = file.user_id == user.id

    if knowledge_id is None:
        if not is_admin and not is_file_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        return None

    knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
    if knowledge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    can_write_knowledge = (
        is_admin
        or knowledge.user_id == user.id
        or has_access(user.id, "write", knowledge.access_control)
    )
    if not can_write_knowledge:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    data = knowledge.data if isinstance(knowledge.data, dict) else {}
    file_ids = data.get("file_ids", [])
    if not isinstance(file_ids, list) or file.id not in file_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    return knowledge


def _process_file_sync_legacy(
    request: Request,
    file_id: str,
    content: Optional[str] = None,
    collection_name: Optional[str] = None,
    knowledge_id: Optional[str] = None,
    user_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
) -> None:
    """
    Core file processing logic that runs synchronously.
    This is called from background tasks to process files.
    
    Args:
        request: FastAPI Request object
        file_id: ID of the file to process
        content: Optional pre-extracted content
        collection_name: Optional collection name
        knowledge_id: Optional knowledge base ID
        user_id: User ID for logging
        admin_id: Frozen admin user ID for credential-safe resolution
        embedding_model_id: Frozen embedding model ID for credential-safe resolution
    """
    log.info(f"[BACKGROUND TASK] Starting _process_file_sync file_id={file_id} user_id={user_id} admin_id={admin_id}")
    
    try:
        # Get user object if user_id is provided
        print(f"  [STEP 1] Retrieving user object...", flush=True)
        log.info(f"  [STEP 1] Retrieving user object...")
        user = None
        if user_id:
            try:
                user = Users.get_user_by_id(user_id)
                if not user:
                    warning_msg = (
                        f"User {user_id} not found for file processing (file_id={file_id}), "
                        "processing without user context"
                    )
                    print(f"  [STEP 1] ⚠️  {warning_msg}", flush=True)
                    log.warning(warning_msg)
                else:
                    print(f"  [STEP 1] ✅ User retrieved: {user.email} (role: {user.role})", flush=True)
                    log.info(f"  [STEP 1] ✅ User retrieved: {user.email} (role: {user.role})")
            except Exception as user_error:
                warning_msg = (
                    f"Error retrieving user {user_id} for file processing (file_id={file_id}): {user_error}, "
                    "processing without user context"
                )
                print(f"  [STEP 1] ⚠️  {warning_msg}", flush=True)
                log.warning(warning_msg)
        else:
            print(f"  [STEP 1] ⚠️  No user_id provided, processing without user context", flush=True)
            log.warning(f"  [STEP 1] No user_id provided, processing without user context")
        
        # Credential-safe: Create embedding function from frozen IDs
        embedding_function = None
        if admin_id and embedding_model_id and not request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL:
            from open_webui.retrieval.embedding.service import EmbeddingService
            from open_webui.retrieval.embedding.compatibility import make_embedding_function_with_storage_guard
            
            service = EmbeddingService(request.app.state.config)
            embedding_function = make_embedding_function_with_storage_guard(
                service, admin_id=admin_id, embedding_model_id=embedding_model_id
            )
        
        # Update status to processing
        print(f"  [STEP 2] Updating file status to 'processing'...", flush=True)
        log.info(f"  [STEP 2] Updating file status to 'processing'...")
        Files.update_file_metadata_by_id(
            file_id,
            {
                "processing_status": "processing",
                "processing_started_at": int(time.time()),
            },
        )
        print(f"  [STEP 2] ✅ File status updated", flush=True)
        log.info(f"  [STEP 2] ✅ File status updated")
        
        print(f"  [STEP 3] Retrieving file object...", flush=True)
        log.info(f"  [STEP 3] Retrieving file object...")
        file = Files.get_file_by_id(file_id)
        if not file:
            error_msg = f"File {file_id} not found for processing (user_id={user_id})"
            print(f"  [STEP 3] ❌ {error_msg}", flush=True)
            log.error(error_msg)
            try:
                Files.update_file_metadata_by_id(
                    file_id,
                    {
                        "processing_status": "error",
                        "processing_error": error_msg,
                    },
                )
            except Exception as update_error:
                log.error(f"Failed to update file status: {update_error}")
            return

        if collection_name is None:
            collection_name = f"file-{file.id}"

        if content:
            # Update the content in the file
            try:
                VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file.id}")
            except Exception:
                # Audio file upload pipeline - ignore deletion errors
                pass

            docs = [
                Document(
                    page_content=content.replace("<br/>", "\n"),
                    metadata={
                        **file.meta,
                        "name": file.filename,
                        "created_by": file.user_id,
                        "file_id": file.id,
                        "source": file.filename,
                    },
                )
            ]
            text_content = content
        else:
            # No content provided - need to extract from file or use cached
            docs = None
            text_content = None
            
            # First, check if file has already been processed and exists in vector DB
            if collection_name:
                print(f"  [CACHE CHECK] collection_name provided: {collection_name}", flush=True)
                log.info(f"  [CACHE CHECK] collection_name provided: {collection_name}")
                # BUG FIX: Use collection_name instead of f"file-{file.id}" when provided
                cache_collection = collection_name
                print(f"  [CACHE CHECK] Querying collection: {cache_collection} (not file-{file.id})", flush=True)
                log.info(f"  [CACHE CHECK] Querying collection: {cache_collection} (not file-{file.id})")
                try:
                    result = VECTOR_DB_CLIENT.query(
                        collection_name=cache_collection, filter={"file_id": file.id}
                    )
                    
                    if result is not None and result.ids and len(result.ids) > 0 and len(result.ids[0]) > 0:
                        # File already processed - use existing documents
                        docs = [
                            Document(
                                page_content=result.documents[0][idx],
                                metadata=result.metadatas[0][idx],
                            )
                            for idx, id in enumerate(result.ids[0])
                        ]
                        text_content = " ".join([doc.page_content for doc in docs])
                        log.info(f"[Content Cache Hit] file_id={file.id} | Using existing {len(docs)} chunks from vector DB")
                except Exception as query_error:
                    log.debug(f"Vector DB query failed for file_id={file.id}: {query_error}")
                    # Fall through to extraction
            
            # Also check if file.data already has content
            if docs is None and file.data.get("content", "").strip():
                existing_content = file.data.get("content", "")
                docs = [
                    Document(
                        page_content=existing_content,
                        metadata={
                            **file.meta,
                            "name": file.filename,
                            "created_by": file.user_id,
                            "file_id": file.id,
                            "source": file.filename,
                        },
                    )
                ]
                text_content = existing_content
                log.info(f"[Content Cache Hit] file_id={file.id} | Using existing content from file.data ({len(existing_content)} chars)")
            
            # If still no docs, extract from the actual file
            if docs is None:
                # Process the file and save the content
                file_path = file.path
                if file_path:
                    file_path = Storage.get_file(file_path)
                    
                    # Log extraction engine being used
                    extraction_engine = request.app.state.config.CONTENT_EXTRACTION_ENGINE or "default (PyPDF)"
                    log.info(
                        f"[Content Extraction] file_id={file.id} | filename={file.filename} | "
                        f"content_type={file.meta.get('content_type')} | engine={extraction_engine}"
                    )
                    
                    # CRITICAL: Force PDF_EXTRACT_IMAGES=False to prevent hangs (image extraction causes 2+ minute slowdowns)
                    loader = Loader(
                        engine=request.app.state.config.CONTENT_EXTRACTION_ENGINE,
                        TIKA_SERVER_URL=request.app.state.config.TIKA_SERVER_URL,
                        PDF_EXTRACT_IMAGES=False,  # FORCED TO FALSE - image extraction causes hangs
                        DOCUMENT_INTELLIGENCE_ENDPOINT=request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
                        DOCUMENT_INTELLIGENCE_KEY=request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
                    )
                    docs = loader.load(
                        file.filename, file.meta.get("content_type"), file_path
                    )
                    
                    # Log extraction results for debugging
                    total_chars = sum(len(doc.page_content) for doc in docs)
                    non_empty_docs = [doc for doc in docs if doc.page_content.strip()]
                    log.info(
                        f"[Content Extraction Result] file_id={file.id} | "
                        f"pages_extracted={len(docs)} | non_empty_pages={len(non_empty_docs)} | "
                        f"total_chars={total_chars}"
                    )
                    
                    # Fail early if extraction returned empty content (BUG #15 fix)
                    if total_chars == 0:
                        file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else "unknown"
                        error_msg = (
                            f"[Content Extraction ERROR] file_id={file.id} | filename={file.filename} | "
                            f"No text content extracted! Possible reasons:\n"
                            f"  - Scanned image PDF (no OCR text layer)\n"
                            f"  - Protected/encrypted file\n"
                            f"  - Unsupported encoding\n"
                            f"  Suggestions:\n"
                            f"  - For scanned PDFs: Enable Document Intelligence (Azure OCR) in Settings > Documents\n"
                            f"  - For better extraction: Configure Tika server\n"
                            f"  - Current engine: {extraction_engine}"
                        )
                        log.error(error_msg)
                        raise ValueError(f"Content extraction returned empty text for file {file.filename}. {error_msg}")

                    docs = [
                        Document(
                            page_content=doc.page_content,
                            metadata={
                                **doc.metadata,
                                "name": file.filename,
                                "created_by": file.user_id,
                                "file_id": file.id,
                                "source": file.filename,
                            },
                        )
                        for doc in docs
                    ]
                else:
                    # No file path - use empty content (should not happen normally)
                    log.warning(f"[Content Extraction] file_id={file.id} | No file path available, using empty content")
                    docs = [
                        Document(
                            page_content="",
                            metadata={
                                **file.meta,
                                "name": file.filename,
                                "created_by": file.user_id,
                                "file_id": file.id,
                                "source": file.filename,
                            },
                        )
                    ]
                text_content = " ".join([doc.page_content for doc in docs])

        log.debug(f"text_content: {text_content}")
        Files.update_file_data_by_id(
            file.id,
            {"content": text_content},
        )

        hash = calculate_sha256_string(text_content)
        Files.update_file_hash_by_id(file.id, hash)
        
        print(f"  [STEP 4] Checking BYPASS_EMBEDDING_AND_RETRIEVAL flag...", flush=True)
        log.info(f"  [STEP 4] Checking BYPASS_EMBEDDING_AND_RETRIEVAL flag...")
        print(f"    BYPASS_EMBEDDING_AND_RETRIEVAL: {request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL}", flush=True)
        log.info(f"    BYPASS_EMBEDDING_AND_RETRIEVAL: {request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL}")

        if not request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL:
            print(f"  [STEP 4] ✅ Embedding and retrieval enabled, proceeding with embedding generation", flush=True)
            log.info(f"  [STEP 4] ✅ Embedding and retrieval enabled, proceeding with embedding generation")
            try:
                # If knowledge_id is provided, we're adding to both collections at once
                if knowledge_id:
                    file_collection = f"file-{file.id}"
                    collections = [file_collection, knowledge_id]
                    
                    print(f"  [STEP 5] Knowledge ID provided, saving to multiple collections:", flush=True)
                    print(f"    collections: {collections}", flush=True)
                    log.info(
                        f"Processing file file_id={file.id}, filename={file.filename} "
                        f"for both file collection and knowledge base: collections={collections}, "
                        f"user_id={user_id}"
                    )

                    # Credential-safe: Pass embedding_function
                    result = save_docs_to_multiple_collections(
                        request,
                        docs=docs,
                        collections=collections,
                        metadata={
                            "file_id": file.id,
                            "name": file.filename,
                            "hash": hash,
                        },
                        embedding_function=embedding_function,
                        admin_id=admin_id,
                        embedding_model_id=embedding_model_id,
                        knowledge_id=knowledge_id,
                        user=user,
                    )

                    # Use file collection name for file metadata
                    print(f"  [STEP 6] Embedding save result: {result}", flush=True)
                    log.info(f"  [STEP 6] Embedding save result: {result}")
                    
                    if result:
                        print(f"  [STEP 6] ✅ Embeddings saved successfully, updating file status to 'completed'", flush=True)
                        log.info(f"  [STEP 6] ✅ Embeddings saved successfully, updating file status to 'completed'")
                        Files.update_file_metadata_by_id(
                            file.id,
                            {
                                "collection_name": file_collection,
                                "processing_status": "completed",
                                "processing_completed_at": int(time.time()),
                            },
                        )
                        print(f"  [STEP 6.1] ✅ File status updated to 'completed'", flush=True)
                        log.info(f"  [STEP 6.1] ✅ File status updated to 'completed'")
                    else:
                        error_msg = "Failed to save to vector DB"
                        print(f"  [STEP 6] ❌ {error_msg}, updating file status to 'error'", flush=True)
                        log.error(f"  [STEP 6] ❌ {error_msg}, updating file status to 'error'")
                        Files.update_file_metadata_by_id(
                            file.id,
                            {
                                "processing_status": "error",
                                "processing_error": error_msg,
                            },
                        )
                        print(f"  [STEP 6.1] ⚠️  File status updated to 'error'", flush=True)
                        log.warning(f"  [STEP 6.1] File status updated to 'error'")
                else:
                    print(f"  [STEP 5] No knowledge ID, saving to single collection:", flush=True)
                    print(f"    collection_name: {collection_name}", flush=True)
                    log.info(f"  [STEP 5] No knowledge ID, saving to single collection: {collection_name}")
                    
                    # Credential-safe: Pass embedding_function
                    result = save_docs_to_vector_db(
                        request,
                        docs=docs,
                        collection_name=collection_name,
                        metadata={
                            "file_id": file.id,
                            "name": file.filename,
                            "hash": hash,
                        },
                        add=(True if collection_name else False),
                        embedding_function=embedding_function,
                        admin_id=admin_id,
                        embedding_model_id=embedding_model_id,
                        knowledge_id=knowledge_id,
                        user=user,
                    )
                    
                    print(f"  [STEP 6] Embedding save result: {result}", flush=True)
                    log.info(f"  [STEP 6] Embedding save result: {result}")

                    if result:
                        print(f"  [STEP 6] ✅ Embeddings saved successfully, updating file status to 'completed'", flush=True)
                        log.info(f"  [STEP 6] ✅ Embeddings saved successfully, updating file status to 'completed'")
                        Files.update_file_metadata_by_id(
                            file.id,
                            {
                                "collection_name": collection_name,
                                "processing_status": "completed",
                                "processing_completed_at": int(time.time()),
                            },
                        )
                    else:
                        Files.update_file_metadata_by_id(
                            file.id,
                            {
                                "processing_status": "error",
                                "processing_error": "Failed to save to vector DB",
                            },
                        )
            except Exception as e:
                error_msg = str(e)
                log.error(
                    f"Error saving file to vector DB: file_id={file.id}, "
                    f"filename={file.filename}, user_id={user_id}, error={error_msg}"
                )
                log.exception(e)
                try:
                    Files.update_file_metadata_by_id(
                        file.id,
                        {
                            "processing_status": "error",
                            "processing_error": error_msg,
                        },
                    )
                except Exception as update_error:
                    log.error(f"Failed to update file status after vector DB error: {update_error}")
        else:
            # Bypass embedding, just mark as completed
            print(f"  [STEP 4] ⚠️  Embedding and retrieval bypassed (BYPASS_EMBEDDING_AND_RETRIEVAL=True)", flush=True)
            log.info(f"  [STEP 4] Embedding and retrieval bypassed (BYPASS_EMBEDDING_AND_RETRIEVAL=True)")
            Files.update_file_metadata_by_id(
                file.id,
                {
                    "processing_status": "completed",
                    "processing_completed_at": int(time.time()),
                },
            )
            print(f"  [STEP 4.1] ✅ File status updated to 'completed' (bypassed)", flush=True)
            log.info(f"  [STEP 4.1] File status updated to 'completed' (bypassed)")
        
        print(f"[BACKGROUND TASK] ✅ File processing completed successfully", flush=True)
        log.info(f"[BACKGROUND TASK] ✅ File processing completed successfully")
        print("=" * 80, flush=True)
        log.info("=" * 80)

    except Exception as e:
        # Consolidated error handling - log and update status
        error_msg = str(e)
        log.error(
            f"Error in background file processing for file_id={file_id}, "
            f"user_id={user_id}, error={error_msg}"
        )
        log.exception(e)
        
        # Update file status to error
        try:
            Files.update_file_metadata_by_id(
                file_id,
                {
                    "processing_status": "error",
                    "processing_error": error_msg,
                },
            )
        except Exception as update_error:
            # If we can't update status, log it but don't fail
            log.error(
                f"Failed to update file status after processing error for file_id={file_id}: {update_error}"
            )


def _process_file_sync(
    request: Request,
    file_id: str,
    content: Optional[str] = None,
    collection_name: Optional[str] = None,
    knowledge_id: Optional[str] = None,
    user_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    embedding_model_id: Optional[str] = None,
) -> None:
    """Process a stored file through the shared mixed-modality pipeline."""

    bypass_value = getattr(
        request.app.state.config,
        "BYPASS_EMBEDDING_AND_RETRIEVAL",
        False,
    )
    bypass_embedding = bool(getattr(bypass_value, "value", bypass_value))
    if bypass_embedding:
        from open_webui.retrieval.embedding.file_processing import (
            load_authoritative_content_override,
        )

        _process_file_sync_legacy(
            request=request,
            file_id=file_id,
            content=load_authoritative_content_override(file_id),
            collection_name=collection_name,
            knowledge_id=knowledge_id,
            user_id=user_id,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )
        return

    from open_webui.retrieval.embedding.file_processing import (
        FILE_PROCESSING_FAILED,
        process_stored_file_for_embedding,
    )
    from open_webui.retrieval.embedding.errors import EmbeddingError

    try:
        process_stored_file_for_embedding(
            config=request.app.state.config,
            file_id=file_id,
            admin_id=admin_id or "",
            embedding_model_id=embedding_model_id or "",
            knowledge_id=knowledge_id,
            collection_name=collection_name,
        )
    except Exception as error:
        error_code = (
            error.code
            if isinstance(error, EmbeddingError)
            else FILE_PROCESSING_FAILED
        )
        log.error(
            "Background file processing failed | file_id=%s | code=%s | type=%s",
            file_id,
            error_code,
            type(error).__name__,
        )


@router.post("/process/file")
def process_file(
    request: Request,
    form_data: ProcessFileForm,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
    knowledge_id: Optional[
        str
    ] = None,  # Add knowledge_id parameter to signify generating embeddings for both file and knowledge base at once
):
    """
    Process a file and generate embeddings.
    
    Processing runs in the background and the endpoint returns immediately
    with status "processing". The file metadata will be updated with processing status.
    """
    # BUG #8 fix: Validate file_id format before any operations
    try:
        UUID(form_data.file_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file ID format: {form_data.file_id}. File ID must be a valid UUID."
        )
    
    # BUG #7 fix: Cache file object to avoid multiple database fetches
    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    effective_knowledge_id = _effective_process_knowledge_id(
        form_data,
        knowledge_id,
    )
    _require_file_processing_access(
        file=file,
        user=user,
        knowledge_id=effective_knowledge_id,
    )
    if form_data.content is not None and not (
        user.role == "admin" or file.user_id == user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Cache file object and metadata for reuse throughout the function
    cached_file = file
    cached_meta = file.meta or {}
    
    # Use Redis distributed lock to prevent race conditions in multi-replica deployments
    # This ensures only one pod can start processing a file at a time
    # Lock timeout is configurable via environment variable (default: 1 hour for large files)
    def _safe_int_env(key: str, default: int, min_value: int = 1, max_value: int = 86400) -> int:
        """Safely parse integer environment variable with fallback to default."""
        try:
            value = os.environ.get(key)
            if value is None:
                return default
            parsed = int(value)
            if parsed < min_value or parsed > max_value:
                log.warning(
                    f"Invalid value for {key} (must be between {min_value} and {max_value}): {parsed}, "
                    f"using default {default}"
                )
                return default
            return parsed
        except (ValueError, TypeError) as e:
            log.warning(
                f"Invalid value for {key}: {os.environ.get(key)}, using default {default}. Error: {e}"
            )
            return default
    
    lock_timeout = _safe_int_env("FILE_PROCESSING_LOCK_TIMEOUT", 3600, min_value=60, max_value=86400)  # 1 min to 24 hours
    pending_reclaim_timeout = _safe_int_env(
        "FILE_PROCESSING_PENDING_RECLAIM_TIMEOUT",
        300,
        min_value=60,
        max_value=86400,
    )
    lock_name = f"open-webui:file_processing_lock:{form_data.file_id}"
    
    processing_lock = None
    lock_acquired = False
    redis_available = True
    status_update_succeeded = False  # BUG #1 fix: Initialize at function level to avoid scope issues
    lock_released = False  # BUG #1 fix: Initialize at function level to avoid scope issues (used in background task block)
    
    try:
        # Validate REDIS_URL before attempting to create lock (BUG #8 fix)
        if not REDIS_URL:
            log.warning("REDIS_URL not configured, falling back to database-level checking")
            redis_available = False
        else:
            processing_lock = RedisLock(
                redis_url=REDIS_URL,
                lock_name=lock_name,
                timeout_secs=lock_timeout,
            )
            # Try to acquire lock - distinguish between "lock held" vs "Redis unavailable" (BUG #2 fix)
            lock_acquired = processing_lock.aquire_lock()
            
            if not lock_acquired:
                # Check if Redis is actually available by testing connection
                # If Redis is down, we'll fall through to database check
                try:
                    # BUG #5 fix: Reuse existing Redis connection from processing_lock instead of creating new one
                    # This is more efficient and avoids exhausting connection pools
                    # BUG #3 fix: No need to create new connection - reuse existing one or skip test
                    if processing_lock and processing_lock.redis:
                        # Reuse the existing connection
                        processing_lock.redis.ping()
                        redis_available = True
                        # Redis is available but the lock is held, so another
                        # request still owns the dispatch window.
                        meta = cached_meta
                        current_status = meta.get(
                            "processing_status",
                            "processing",
                        )

                        log.info(
                            f"File {form_data.file_id} is already being processed (lock held by another pod), "
                            f"skipping duplicate processing request from user {user.id}"
                        )
                        return {
                            "status": current_status,
                            "file_id": form_data.file_id,
                            "filename": cached_file.filename,
                            "message": f"File is already {current_status}. Please wait for completion.",
                            "collection_name": meta.get("collection_name"),
                            "content": None,
                        }
                    else:
                        # If processing_lock doesn't have redis, it means initialization failed
                        # Don't create a new connection (resource leak), just mark as unavailable
                        log.warning(
                            f"Redis lock for file {form_data.file_id} has no connection. "
                            "Marking Redis as unavailable."
                        )
                        redis_available = False
                except Exception as redis_test_error:
                    # Redis is unavailable - fall through to database check
                    log.warning(
                        f"Redis unavailable for file processing lock (file_id={form_data.file_id}): {redis_test_error}. "
                        "Falling back to database-level checking."
                    )
                    redis_available = False
                    lock_acquired = False
    except Exception as lock_init_error:
        # Lock initialization failed - fall back to database check
        log.warning(
            f"Failed to initialize Redis lock for file {form_data.file_id}: {lock_init_error}. "
            "Falling back to database-level checking.",
            exc_info=True  # BUG #6 fix: Include full exception traceback for debugging
        )
        redis_available = False
        lock_acquired = False
    
    # Redis protects the short dispatch window across replicas. The database
    # lease is authoritative in both Redis and degraded modes, so a fresh
    # pending request is deduplicated while a stranded pending request becomes
    # reclaimable after a bounded interval.
    try:
        (
            dispatch_claimed,
            cached_meta,
            current_status,
            reclaimed_stale_pending,
        ) = _claim_file_processing_dispatch(
            form_data.file_id,
            pending_reclaim_timeout,
        )
        if not cached_meta and current_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        try:
            cached_file.meta = cached_meta
        except (AttributeError, TypeError) as assign_error:
            log.debug(
                "Could not update cached_file.meta: %s; using cached metadata",
                assign_error,
            )

        if not dispatch_claimed:
            effective_status = current_status or "processing"
            log.info(
                "File %s already has live processing state %s; skipping "
                "duplicate request from user %s",
                form_data.file_id,
                effective_status,
                user.id,
            )
            if processing_lock and lock_acquired and not lock_released:
                processing_lock.release_lock()
                lock_released = True
            return {
                "status": effective_status,
                "file_id": form_data.file_id,
                "filename": cached_file.filename,
                "message": (
                    f"File is already {effective_status}. "
                    "Please wait for completion."
                ),
                "collection_name": cached_meta.get("collection_name"),
                "content": None,
            }

        status_update_succeeded = True
        if reclaimed_stale_pending:
            log.warning(
                "Reclaimed stale pending file-processing dispatch | "
                "file_id=%s | stale_after_seconds=%s | user_id=%s",
                form_data.file_id,
                pending_reclaim_timeout,
                user.id,
            )
    except Exception:
        if processing_lock and lock_acquired and not lock_released:
            try:
                processing_lock.release_lock()
                lock_released = True
            except Exception as release_error:
                log.error(
                    "Failed to release file-processing lock after claim error: %s",
                    release_error,
                )
        raise
    
    # Enqueue job to distributed job queue (RQ) if available, otherwise fall back to BackgroundTasks
    # This enables distributed processing across multiple pods in Kubernetes
    # CRITICAL: Keep lock held until we've successfully enqueued job or added BackgroundTask
    # This prevents race conditions where multiple requests could process the same file
    job_id = None
    use_job_queue = False
    job_enqueued = False
    background_task_added = False
    
    # Credential-safe: Resolve frozen IDs (no credentials in payload)
    from open_webui.retrieval.embedding.resolution import freeze_for_enqueue, freeze_for_knowledge_enqueue

    try:
        admin_id, embedding_model_id = (
            freeze_for_knowledge_enqueue(
                effective_knowledge_id,
                user.id,
                request.app.state.config,
            )
            if effective_knowledge_id
            else freeze_for_enqueue(user.id, request.app.state.config)
        )
    except Exception as error:
        error_code = (
            error.code if isinstance(error, EmbeddingError) else FILE_PROCESSING_FAILED
        )
        public_error = safe_file_processing_error_message(error_code)
        log.error(
            "Embedding resolution failed | file_id=%s | code=%s | type=%s",
            form_data.file_id,
            error_code,
            type(error).__name__,
        )
        status_result = Files.update_file_metadata_by_id(
            form_data.file_id,
            {
                "processing_status": "error",
                "processing_completed_at": int(time.time()),
                "processing_error_code": error_code,
                "processing_error": public_error,
            },
        )
        if processing_lock and lock_acquired and not lock_released:
            try:
                processing_lock.release_lock()
                lock_released = True
            except Exception:
                pass
        if status_result is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=public_error,
            )
        return {
            "status": "error",
            "file_id": form_data.file_id,
            "processing_error_code": error_code,
            "error": public_error,
        }
    
    log.info(f"[PROCESS FILE] file_id={form_data.file_id} admin_id={admin_id} embedding_model_id={embedding_model_id}")
    
    try:
        from open_webui.retrieval.embedding.file_processing import (
            persist_content_provenance_before_dispatch,
        )

        # Background and RQ workers must read one durable, authoritative input;
        # never rely on an ephemeral request/queue payload for text overrides.
        persist_content_provenance_before_dispatch(
            form_data.file_id,
            form_data.content,
        )

        # Try to use job queue first if available
        if is_job_queue_available():
            try:
                job_id = enqueue_file_processing_job(
                    file_id=form_data.file_id,
                    content=None,
                    collection_name=form_data.collection_name,
                    knowledge_id=effective_knowledge_id,
                    user_id=user.id,
                    admin_id=admin_id,
                    embedding_model_id=embedding_model_id,
                )
                
                if job_id is not None:
                    use_job_queue = True
                    job_enqueued = True
                    log.info(f"Successfully enqueued job {job_id} for file_id={form_data.file_id}")
                else:
                    log.warning(
                        f"Job queue unavailable for file_id={form_data.file_id}, "
                        "falling back to BackgroundTasks"
                    )
            except Exception as job_enqueue_error:
                log.warning(
                    f"Failed to enqueue job for file_id={form_data.file_id}: {job_enqueue_error}, "
                    "falling back to BackgroundTasks",
                    exc_info=True
                )
        
        if not job_enqueued:
            try:
                background_tasks.add_task(
                    _process_file_sync,
                    request=request,
                    file_id=form_data.file_id,
                    content=None,
                    collection_name=form_data.collection_name,
                    knowledge_id=effective_knowledge_id,
                    user_id=user.id,
                    admin_id=admin_id,
                    embedding_model_id=embedding_model_id,
                )
                background_task_added = True
                log.debug(f"Added BackgroundTask for file_id={form_data.file_id}")
            except Exception as bg_task_error:
                log.error(
                    f"Failed to add BackgroundTask for file_id={form_data.file_id}: {bg_task_error}",
                    exc_info=True
                )
                raise
        
        # Only mark as successful if we actually enqueued/added a task
        if not (job_enqueued or background_task_added):
            raise Exception("Failed to enqueue job or add BackgroundTask - no task was created")
    except Exception as error:
        public_error = safe_file_processing_error_message(FILE_PROCESSING_FAILED)
        Files.update_file_metadata_by_id(
            form_data.file_id,
            {
                "processing_status": "error",
                "processing_completed_at": int(time.time()),
                "processing_error_code": FILE_PROCESSING_FAILED,
                "processing_error": public_error,
            },
        )
        log.error(
            "File processing dispatch failed | file_id=%s | type=%s",
            form_data.file_id,
            type(error).__name__,
        )
        if processing_lock and lock_acquired and not lock_released:
            try:
                processing_lock.release_lock()
                lock_released = True
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=public_error,
        ) from None
    finally:
        # CRITICAL FIX: Release lock AFTER successfully enqueueing job or adding BackgroundTask
        # This ensures no race condition can occur
        # Only release if we have the lock and haven't released it yet
        if processing_lock and lock_acquired and not lock_released:
            # Release lock if task was successfully created (job enqueued OR background task added)
            # Even if status update failed, we should release the lock because:
            # 1. The task will update status to "processing" when it starts
            # 2. Holding the lock prevents other requests from processing the same file
            # 3. The task is already enqueued, so we don't need the lock anymore
            if job_enqueued or background_task_added:
                try:
                    processing_lock.release_lock()
                    lock_released = True
                    log.debug(
                        f"Released file processing lock for file_id={form_data.file_id} "
                        f"after successful task creation (job_enqueued={job_enqueued}, "
                        f"background_task_added={background_task_added}, "
                        f"status_update_succeeded={status_update_succeeded})"
                    )
                except Exception as release_error:
                    log.error(f"Failed to release lock after task creation: {release_error}")
            elif not status_update_succeeded:
                # Status update failed AND no task was created - don't release lock
                # This prevents another request from trying to process the same file
                log.warning(
                    f"Lock NOT released for file_id={form_data.file_id} due to status update failure "
                    f"and no task was created. Lock will expire after timeout to prevent deadlock."
                )
            else:
                # No task was created - don't release lock to prevent duplicate processing
                log.warning(
                    f"Lock NOT released for file_id={form_data.file_id} due to task creation failure. "
                    "Lock will expire after timeout."
                )
    
    # Return immediately with processing status (backward compatible format)
    # Include both old format fields and new status for compatibility
    result = {
        "status": "processing",  # New format
        "file_id": form_data.file_id,
        "filename": cached_file.filename,
        "message": "File processing started in background",
        # Backward compatibility fields (will be None/empty until processing completes)
        "collection_name": None,
        "content": None,
    }
    
    # Add job_id if job was successfully enqueued
    if job_enqueued and job_id:
        result["job_id"] = job_id
    
    return result


class ProcessTextForm(BaseModel):
    name: str
    content: str
    collection_name: Optional[str] = None


@router.post("/process/text")
def process_text(
    request: Request,
    form_data: ProcessTextForm,
    user=Depends(get_verified_user),
):
    collection_name = form_data.collection_name
    if collection_name is None:
        collection_name = calculate_sha256_string(form_data.content)

    docs = [
        Document(
            page_content=form_data.content,
            metadata={"name": form_data.name, "created_by": user.id},
        )
    ]
    text_content = form_data.content
    log.debug(f"text_content: {text_content}")

    result = save_docs_to_vector_db(request, docs, collection_name, user=user)
    if result:
        return {
            "status": True,
            "collection_name": collection_name,
            "content": text_content,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DEFAULT(),
        )


@router.post("/process/youtube")
def process_youtube_video(
    request: Request, form_data: ProcessUrlForm, user=Depends(get_verified_user)
):
    try:
        collection_name = form_data.collection_name
        if not collection_name:
            collection_name = calculate_sha256_string(form_data.url)[:63]

        loader = YoutubeLoader(
            form_data.url,
            language=request.app.state.config.YOUTUBE_LOADER_LANGUAGE,
            proxy_url=request.app.state.config.YOUTUBE_LOADER_PROXY_URL,
        )

        docs = loader.load()
        content = " ".join([doc.page_content for doc in docs])
        log.debug(f"text_content: {content}")

        save_docs_to_vector_db(
            request, docs, collection_name, overwrite=True, user=user
        )

        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
            "file": {
                "data": {
                    "content": content,
                },
                "meta": {
                    "name": form_data.url,
                },
            },
        }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


@router.post("/process/web")
def process_web(
    request: Request, form_data: ProcessUrlForm, user=Depends(get_verified_user)
):
    try:
        collection_name = form_data.collection_name
        if not collection_name:
            collection_name = calculate_sha256_string(form_data.url)[:63]

        loader = get_web_loader(
            form_data.url,
            verify_ssl=request.app.state.config.ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION,
            requests_per_second=request.app.state.config.RAG_WEB_SEARCH_CONCURRENT_REQUESTS.get(user.email),
        )
        docs = loader.load()
        content = " ".join([doc.page_content for doc in docs])

        log.debug(f"text_content: {content}")
        save_docs_to_vector_db(
            request, docs, collection_name, overwrite=True, user=user
        )

        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
            "file": {
                "data": {
                    "content": content,
                },
                "meta": {
                    "name": form_data.url,
                },
            },
        }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


def search_web(request: Request, engine: str, query: str, email: str) -> list[SearchResult]:
    """Search the web using a search engine and return the results as a list of SearchResult objects.
    Will look for a search engine API key in environment variables in the following order:
    - SEARXNG_QUERY_URL
    - GOOGLE_PSE_API_KEY + GOOGLE_PSE_ENGINE_ID
    - BRAVE_SEARCH_API_KEY
    - KAGI_SEARCH_API_KEY
    - MOJEEK_SEARCH_API_KEY
    - BOCHA_SEARCH_API_KEY
    - SERPSTACK_API_KEY
    - SERPER_API_KEY
    - SERPLY_API_KEY
    - TAVILY_API_KEY
    - EXA_API_KEY
    - SEARCHAPI_API_KEY + SEARCHAPI_ENGINE (by default `google`)
    - SERPAPI_API_KEY + SERPAPI_ENGINE (by default `google`)
    Args:
        query (str): The query to search for
    """

    # TODO: add playwright to search the web
    if engine == "searxng":
        if request.app.state.config.SEARXNG_QUERY_URL.get(email):
            return search_searxng(
                request.app.state.config.SEARXNG_QUERY_URL.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No SEARXNG_QUERY_URL found in environment variables")
    elif engine == "google_pse":
        if (
            request.app.state.config.GOOGLE_PSE_API_KEY.get(email)
            and request.app.state.config.GOOGLE_PSE_ENGINE_ID.get(email)
        ):
            return search_google_pse(
                request.app.state.config.GOOGLE_PSE_API_KEY.get(email),
                request.app.state.config.GOOGLE_PSE_ENGINE_ID.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception(
                "No GOOGLE_PSE_API_KEY or GOOGLE_PSE_ENGINE_ID found in environment variables"
            )
    elif engine == "brave":
        if request.app.state.config.BRAVE_SEARCH_API_KEY.get(email):
            return search_brave(
                request.app.state.config.BRAVE_SEARCH_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No BRAVE_SEARCH_API_KEY found in environment variables")
    elif engine == "kagi":
        if request.app.state.config.KAGI_SEARCH_API_KEY.get(email):
            return search_kagi(
                request.app.state.config.KAGI_SEARCH_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No KAGI_SEARCH_API_KEY found in environment variables")
    elif engine == "mojeek":
        if request.app.state.config.MOJEEK_SEARCH_API_KEY.get(email):
            return search_mojeek(
                request.app.state.config.MOJEEK_SEARCH_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No MOJEEK_SEARCH_API_KEY found in environment variables")
    elif engine == "bocha":
        if request.app.state.config.BOCHA_SEARCH_API_KEY.get(email):
            return search_bocha(
                request.app.state.config.BOCHA_SEARCH_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No BOCHA_SEARCH_API_KEY found in environment variables")
    elif engine == "serpstack":
        if request.app.state.config.SERPSTACK_API_KEY.get(email):
            return search_serpstack(
                request.app.state.config.SERPSTACK_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
                https_enabled=request.app.state.config.SERPSTACK_HTTPS.get(email),
            )
        else:
            raise Exception("No SERPSTACK_API_KEY found in environment variables")
    elif engine == "serper":
        if request.app.state.config.SERPER_API_KEY.get(email):
            return search_serper(
                request.app.state.config.SERPER_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No SERPER_API_KEY found in environment variables")
    elif engine == "serply":
        if request.app.state.config.SERPLY_API_KEY.get(email):
            return search_serply(
                request.app.state.config.SERPLY_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No SERPLY_API_KEY found in environment variables")
    elif engine == "duckduckgo":
        return search_duckduckgo(
            query,
            request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
            request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            request.app.state.config.RAG_WEB_SEARCH_WEBSITE_BLOCKLIST.get(email),
        )
    elif engine == "tavily":
        if request.app.state.config.TAVILY_API_KEY.get(email):
            return search_tavily(
                request.app.state.config.TAVILY_API_KEY.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
                request.app.state.config.RAG_WEB_SEARCH_WEBSITE_BLOCKLIST.get(email),
            )
        else:
            raise Exception("No TAVILY_API_KEY found in environment variables")
    elif engine == "searchapi":
        if request.app.state.config.SEARCHAPI_API_KEY.get(email):
            return search_searchapi(
                request.app.state.config.SEARCHAPI_API_KEY.get(email),
                request.app.state.config.SEARCHAPI_ENGINE.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No SEARCHAPI_API_KEY found in environment variables")
    elif engine == "serpapi":
        if request.app.state.config.SERPAPI_API_KEY.get(email):
            return search_serpapi(
                request.app.state.config.SERPAPI_API_KEY.get(email),
                request.app.state.config.SERPAPI_ENGINE.get(email),
                query,
                request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
                request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
            )
        else:
            raise Exception("No SERPAPI_API_KEY found in environment variables")
    elif engine == "jina":
        return search_jina(
            request.app.state.config.JINA_API_KEY.get(email),
            query,
            request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
        )
    elif engine == "bing":
        return search_bing(
            request.app.state.config.BING_SEARCH_V7_SUBSCRIPTION_KEY.get(email),
            request.app.state.config.BING_SEARCH_V7_ENDPOINT.get(email),
            str(DEFAULT_LOCALE),
            query,
            request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
            request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
        )
    elif engine == "exa":
        return search_exa(
            request.app.state.config.EXA_API_KEY.get(email),
            query,
            request.app.state.config.RAG_WEB_SEARCH_RESULT_COUNT.get(email),
            request.app.state.config.RAG_WEB_SEARCH_DOMAIN_FILTER_LIST.get(email),
        )
    else:
        raise Exception("No search engine API key found in environment variables")


@router.post("/process/web/search")
async def process_web_search(
    request: Request, form_data: SearchForm, user=Depends(get_verified_user)
):
    try:
        logging.info(
            f"trying to web search with {request.app.state.config.RAG_WEB_SEARCH_ENGINE.get(user.email), form_data.query}"
        )
        web_results = search_web(
            request, request.app.state.config.RAG_WEB_SEARCH_ENGINE.get(user.email), form_data.query, user.email
        )
    except Exception as e:
        log.exception(e)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.WEB_SEARCH_ERROR(e),
        )

    log.debug(f"web_results: {web_results}")

    try:
        collection_name = form_data.collection_name
        if collection_name == "" or collection_name is None:
            collection_name = f"web-search-{calculate_sha256_string(form_data.query)}"[
                :63
            ]

        urls = [result.link for result in web_results]
        loader = get_web_loader(
            urls,
            verify_ssl=request.app.state.config.ENABLE_RAG_WEB_LOADER_SSL_VERIFICATION,
            requests_per_second=request.app.state.config.RAG_WEB_SEARCH_CONCURRENT_REQUESTS.get(user.email),
            trust_env=request.app.state.config.RAG_WEB_SEARCH_TRUST_ENV.get(user.email),
        )
        docs = await loader.aload()

        if request.app.state.config.BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL.get(user.email):
            return {
                "status": True,
                "collection_name": None,
                "filenames": urls,
                "docs": [
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                    }
                    for doc in docs
                ],
                "loaded_count": len(docs),
            }
        else:
            await run_in_threadpool(
                save_docs_to_vector_db,
                request,
                docs,
                collection_name,
                overwrite=True,
                user=user,
            )

            return {
                "status": True,
                "collection_name": collection_name,
                "filenames": urls,
                "loaded_count": len(docs),
            }
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


def _resolve_model_aware_query_context(
    request,
    user,
    *,
    knowledge_ids: Optional[list[str]] = None,
    file_ids: Optional[list[str]] = None,
):
    """Resolve the model space and any source-scoped staged-vector allowance.

    Admins without durable state use their config-resolved model. All readiness
    and resolution failures propagate so callers fail closed instead of running
    a model-unaware vector search.
    """
    try:
        from open_webui.retrieval.embedding.resolution import resolve_for_user
        from open_webui.retrieval.embedding.gate import (
            assert_embedding_retrieval_ready,
            RetrievalModelSpace,
        )

        result = assert_embedding_retrieval_ready(
            requesting_user_id=user.id,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
        )
        if isinstance(result, RetrievalModelSpace):
            return (
                result.admin_id,
                result.active_model_id,
                list(result.staged_job_ids) or None,
                list(result.staged_file_ids) or None,
                list(result.staged_collection_files) or None,
            )
        # RetrievalReadyNoState: legacy admin, use config-resolved model.
        ctx = resolve_for_user(user.id, request.app.state.config)
        return ctx.admin_id, ctx.model.id, None, None, None
    except EmbeddingError:
        # All embedding errors (MIXED, NOT_READY, resolution failures) propagate.
        raise
    except Exception as error:
        # Non-embedding resolution failure: fail closed.
        log.warning(
            "Model-aware query resolution failed | type=%s",
            type(error).__name__,
        )
        raise


def _resolve_authorized_query_collections(
    collection_names: list[str],
) -> tuple[list[str], list[str]]:
    """Derive file/knowledge scope from client-requested collection names.

    Direct query endpoints have no server-owned legacy collection allowlist, so
    every requested name must be a canonical file or Knowledge collection. The
    readiness gate performs the corresponding read-access and model-space checks.
    """
    from open_webui.models.knowledge import Knowledges

    knowledge_ids: list[str] = []
    file_ids: list[str] = []
    for raw_name in collection_names:
        collection_name = str(raw_name or "").strip()
        if not collection_name:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        if collection_name.startswith("file-"):
            file_id = collection_name.removeprefix("file-")
            if not file_id or Files.get_file_by_id(file_id) is None:
                raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
            file_ids.append(file_id)
            continue
        if Knowledges.get_knowledge_by_id(collection_name) is None:
            raise EmbeddingError(EMBEDDING_FILE_NOT_FOUND)
        knowledge_ids.append(collection_name)
    return list(dict.fromkeys(knowledge_ids)), list(dict.fromkeys(file_ids))


class QueryDocForm(BaseModel):
    collection_name: str
    query: str
    k: Optional[int] = None
    r: Optional[float] = None
    hybrid: Optional[bool] = None


@router.post("/query/doc")
def query_doc_handler(
    request: Request,
    form_data: QueryDocForm,
    user=Depends(get_verified_user),
):
    try:
        knowledge_ids, file_ids = _resolve_authorized_query_collections(
            [form_data.collection_name]
        )
        (
            admin_id,
            embedding_model_id,
            staged_job_ids,
            staged_file_ids,
            staged_collection_files,
        ) = _resolve_model_aware_query_context(
            request,
            user,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
        )

        # Bind query generation to the exact model approved by the gate.
        from open_webui.retrieval.embedding.service import EmbeddingService
        from open_webui.retrieval.embedding.compatibility import make_embedding_function

        service = EmbeddingService(request.app.state.config)
        embedding_function = make_embedding_function(
            service,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )

        if request.app.state.config.ENABLE_RAG_HYBRID_SEARCH.get(user.email):
            return query_doc_with_hybrid_search(
                collection_name=form_data.collection_name,
                query=form_data.query,
                embedding_function=embedding_function,
                k=form_data.k if form_data.k else request.app.state.config.TOP_K.get(user.email),
                reranking_function=request.app.state.rf,
                r=(
                    form_data.r
                    if form_data.r
                    else request.app.state.config.RELEVANCE_THRESHOLD
                ),
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                knowledge_ids=knowledge_ids or None,
                file_ids=file_ids or None,
                staged_job_ids=staged_job_ids,
                staged_file_ids=staged_file_ids,
                staged_collection_files=staged_collection_files,
            )
        else:
            return query_doc(
                collection_name=form_data.collection_name,
                query_embedding=embedding_function(form_data.query),
                k=form_data.k if form_data.k else request.app.state.config.TOP_K.get(user.email),
                user=user,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                knowledge_ids=knowledge_ids or None,
                file_ids=file_ids or None,
                staged_job_ids=staged_job_ids,
                staged_file_ids=staged_file_ids,
                staged_collection_files=staged_collection_files,
            )
    except EmbeddingError as e:
        if e.code == EMBEDDING_REINDEX_NOT_READY:
            detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            detail["error_code"] = e.code
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail,
            )
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class QueryCollectionsForm(BaseModel):
    collection_names: list[str]
    query: str
    k: Optional[int] = None
    r: Optional[float] = None
    hybrid: Optional[bool] = None


@router.post("/query/collection")
def query_collection_handler(
    request: Request,
    form_data: QueryCollectionsForm,
    user=Depends(get_verified_user),
):
    try:
        knowledge_ids, file_ids = _resolve_authorized_query_collections(
            form_data.collection_names
        )
        (
            admin_id,
            embedding_model_id,
            staged_job_ids,
            staged_file_ids,
            staged_collection_files,
        ) = _resolve_model_aware_query_context(
            request,
            user,
            knowledge_ids=knowledge_ids,
            file_ids=file_ids,
        )

        # Bind query generation to the exact model approved by the gate.
        from open_webui.retrieval.embedding.service import EmbeddingService
        from open_webui.retrieval.embedding.compatibility import make_embedding_function

        service = EmbeddingService(request.app.state.config)
        embedding_function = make_embedding_function(
            service,
            admin_id=admin_id,
            embedding_model_id=embedding_model_id,
        )

        if request.app.state.config.ENABLE_RAG_HYBRID_SEARCH.get(user.email):
            return query_collection_with_hybrid_search(
                collection_names=form_data.collection_names,
                queries=[form_data.query],
                embedding_function=embedding_function,
                k=form_data.k if form_data.k else request.app.state.config.TOP_K.get(user.email),
                reranking_function=request.app.state.rf,
                r=(
                    form_data.r
                    if form_data.r
                    else request.app.state.config.RELEVANCE_THRESHOLD
                ),
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                knowledge_ids=knowledge_ids or None,
                file_ids=file_ids or None,
                staged_job_ids=staged_job_ids,
                staged_file_ids=staged_file_ids,
                staged_collection_files=staged_collection_files,
            )
        else:
            return query_collection(
                collection_names=form_data.collection_names,
                queries=[form_data.query],
                embedding_function=embedding_function,
                k=form_data.k if form_data.k else request.app.state.config.TOP_K.get(user.email),
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                knowledge_ids=knowledge_ids or None,
                file_ids=file_ids or None,
                staged_job_ids=staged_job_ids,
                staged_file_ids=staged_file_ids,
                staged_collection_files=staged_collection_files,
            )

    except EmbeddingError as e:
        if e.code == EMBEDDING_REINDEX_NOT_READY:
            detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            detail["error_code"] = e.code
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail,
            )
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


####################################
#
# Vector DB operations
#
####################################


class DeleteForm(BaseModel):
    collection_name: str
    file_id: str


@router.post("/delete")
def delete_entries_from_collection(form_data: DeleteForm, user=Depends(get_admin_user)):
    try:
        if VECTOR_DB_CLIENT.has_collection(collection_name=form_data.collection_name):
            file = Files.get_file_by_id(form_data.file_id)
            hash = file.hash

            VECTOR_DB_CLIENT.delete(
                collection_name=form_data.collection_name,
                metadata={"hash": hash},
            )
            return {"status": True}
        else:
            return {"status": False}
    except Exception as e:
        log.exception(e)
        return {"status": False}


@router.post("/reset/db")
def reset_vector_db(user=Depends(get_admin_user)):
    VECTOR_DB_CLIENT.reset()
    Knowledges.delete_all_knowledge()


@router.post("/reset/uploads")
def reset_upload_dir(user=Depends(get_admin_user)) -> bool:
    folder = f"{UPLOAD_DIR}"
    try:
        # Check if the directory exists
        if os.path.exists(folder):
            # Iterate over all the files and directories in the specified directory
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)  # Remove the file or link
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)  # Remove the directory
                except Exception as e:
                    log.exception(f"Failed to delete {file_path}. Reason: {e}")
        else:
            log.warning(f"The directory {folder} does not exist")
    except Exception as e:
        log.exception(f"Failed to process the directory {folder}. Reason: {e}")
    return True


if ENV == "dev":

    @router.get("/ef/{text}")
    async def get_embeddings(request: Request, text: Optional[str] = "Hello World!", user=Depends(get_verified_user)):
        from open_webui.retrieval.embedding.compatibility import get_user_embedding_function
        ef = get_user_embedding_function(request.app.state.config, user.id)
        return {"result": ef(text)}


class BatchProcessFilesForm(BaseModel):
    files: List[FileModel]
    collection_name: str


class BatchProcessFilesResult(BaseModel):
    file_id: str
    status: Literal["completed", "failed"]
    error_code: Optional[str] = None
    message: Optional[str] = None


class BatchProcessFilesResponse(BaseModel):
    results: List[BatchProcessFilesResult]
    errors: List[BatchProcessFilesResult]


@router.post("/process/files/batch")
def process_files_batch(
    request: Request,
    form_data: BatchProcessFilesForm,
    user=Depends(get_verified_user),
) -> BatchProcessFilesResponse:
    """
    Process a batch of files and save them to the vector database.
    """
    results: List[BatchProcessFilesResult] = []
    errors: List[BatchProcessFilesResult] = []
    collection_name = form_data.collection_name

    knowledge = Knowledges.get_knowledge_by_id(id=collection_name)
    if knowledge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if (
        user.role != "admin"
        and knowledge.user_id != user.id
        and not has_access(user.id, "write", knowledge.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Never trust caller-supplied FileModel fields. Rehydrate each file from the
    # database and require ownership (or admin authority) for this add flow.
    files: List[FileModel] = []
    for submitted_file in form_data.files:
        file = Files.get_file_by_id(submitted_file.id)
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        if user.role != "admin" and file.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        files.append(file)

    from open_webui.retrieval.embedding.file_processing import (
        process_stored_file_for_embedding,
    )
    from open_webui.retrieval.embedding.resolution import (
        freeze_for_knowledge_enqueue,
    )

    try:
        admin_id, embedding_model_id = freeze_for_knowledge_enqueue(
            collection_name,
            user.id,
            request.app.state.config,
        )
    except Exception as error:
        raw_error_code = (
            error.code if isinstance(error, EmbeddingError) else FILE_PROCESSING_FAILED
        )
        error_code = (
            safe_file_processing_error_code(raw_error_code)
            or FILE_PROCESSING_FAILED
        )
        public_error = safe_file_processing_error_message(error_code)
        log.error(
            "Batch embedding resolution failed | knowledge_id=%s | code=%s | type=%s",
            collection_name,
            error_code,
            type(error).__name__,
        )
        for file in files:
            failure = BatchProcessFilesResult(
                file_id=file.id,
                status="failed",
                error_code=error_code,
                message=public_error,
            )
            results.append(failure)
            errors.append(failure)
        return BatchProcessFilesResponse(results=results, errors=errors)

    # The shared processor reads the authoritative stored bytes, prepares all
    # modalities, and reconciles the file plus every current knowledge
    # membership governed by this frozen admin/model context.
    for file in files:
        try:
            process_stored_file_for_embedding(
                config=request.app.state.config,
                file_id=file.id,
                admin_id=admin_id,
                embedding_model_id=embedding_model_id,
                knowledge_id=collection_name,
                collection_name=collection_name,
            )
            results.append(
                BatchProcessFilesResult(file_id=file.id, status="completed")
            )
        except Exception as error:
            raw_error_code = (
                error.code
                if isinstance(error, EmbeddingError)
                else FILE_PROCESSING_FAILED
            )
            error_code = (
                safe_file_processing_error_code(raw_error_code)
                or FILE_PROCESSING_FAILED
            )
            public_error = safe_file_processing_error_message(error_code)
            log.error(
                "Batch file processing failed | file_id=%s | code=%s | type=%s",
                file.id,
                error_code,
                type(error).__name__,
            )
            failure = BatchProcessFilesResult(
                file_id=file.id,
                status="failed",
                error_code=error_code,
                message=public_error,
            )
            results.append(failure)
            errors.append(failure)

    return BatchProcessFilesResponse(results=results, errors=errors)
