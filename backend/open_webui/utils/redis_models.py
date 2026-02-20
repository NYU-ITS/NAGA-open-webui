"""
Redis-backed per-user model cache.

Stores and retrieves per-user model lists in Redis to avoid app.state.MODELS
overwrites across concurrent users on multi-pod deployments.

Key pattern: models:user:{user_id}
Value: JSON string of { model_id: model } dict
TTL: 300 seconds (configurable)
"""

import asyncio
import json
import logging
from typing import Optional

import redis

from open_webui.env import REDIS_URL, REDIS_USE_SENTINEL

log = logging.getLogger(__name__)

# Default TTL for model cache (seconds)
MODELS_CACHE_TTL = 300


def _get_redis_client() -> Optional[redis.Redis]:
    """
    Get a sync Redis client for model cache operations.

    Reuses existing infrastructure from socket/utils.py:
    - Sentinel: get_redis_master_connection()
    - Direct: get_redis_pool(REDIS_URL) + redis.Redis

    Returns:
        redis.Redis instance, or None if Redis is unavailable
    """
    try:
        if REDIS_USE_SENTINEL:
            from open_webui.socket.utils import get_redis_master_connection

            client = get_redis_master_connection()
            if client is None:
                log.debug(
                    "[DEBUG] [redis_models._get_redis_client] Redis Sentinel master connection unavailable. "
                    "Falling back to get_all_models."
                )
                return None
            log.debug("[DEBUG] [redis_models._get_redis_client] Using Redis Sentinel master connection.")
            return client
        else:
            from open_webui.socket.utils import get_redis_pool

            pool = get_redis_pool(REDIS_URL, use_master=True)
            if hasattr(pool, "_conn"):
                client = pool._conn
            elif hasattr(pool, "get_connection"):
                from open_webui.socket.utils import get_redis_master_connection

                client = get_redis_master_connection()
                if client is None:
                    client = redis.Redis(connection_pool=pool)
            else:
                client = redis.Redis(connection_pool=pool)
            client.ping()
            log.debug("[DEBUG] [redis_models._get_redis_client] Using Redis connection from pool.")
            return client
    except Exception as e:
        log.warning(
            f"[redis_models._get_redis_client] Redis unavailable: {e}. "
            "Model cache disabled; will use get_all_models."
        )
        return None


def get_models_for_user(user_id: str) -> Optional[dict]:
    """
    Read per-user model list from Redis.

    Args:
        user_id: User ID

    Returns:
        { model_id: model } dict, or None on cache miss or error
    """
    client = _get_redis_client()
    if client is None:
        log.debug(f"[DEBUG] [redis_models.get_models_for_user] Redis unavailable for user_id={user_id}. Returning None.")
        return None

    key = f"models:user:{user_id}"
    try:
        value = client.get(key)
        if value is None:
            log.debug(f"[DEBUG] [redis_models.get_models_for_user] Cache miss for user_id={user_id}.")
            return None
        models = json.loads(value)
        if not isinstance(models, dict):
            log.warning(f"[redis_models.get_models_for_user] Invalid cache value for user_id={user_id}: not a dict.")
            return None
        log.debug(f"[DEBUG] [redis_models.get_models_for_user] Cache hit for user_id={user_id}, {len(models)} models.")
        return models
    except json.JSONDecodeError as e:
        log.warning(f"[redis_models.get_models_for_user] JSON decode error for user_id={user_id}: {e}. Treating as miss.")
        return None
    except Exception as e:
        log.warning(f"[redis_models.get_models_for_user] Redis/read error for user_id={user_id}: {e}. Treating as miss.")
        return None


def set_models_for_user(user_id: str, models_dict: dict, ttl: int = MODELS_CACHE_TTL) -> bool:
    """
    Write per-user model list to Redis with TTL.

    Args:
        user_id: User ID
        models_dict: { model_id: model } dict (same structure as request.app.state.MODELS)
        ttl: Time-to-live in seconds (default 300)

    Returns:
        True on success, False on error (callers proceed anyway)
    """
    client = _get_redis_client()
    if client is None:
        log.debug(f"[DEBUG] [redis_models.set_models_for_user] Redis unavailable for user_id={user_id}. Skipping cache write.")
        return False

    key = f"models:user:{user_id}"
    try:
        # Use default=str for datetime/date objects (e.g. custom_model.created_at)
        value = json.dumps(models_dict, default=str)
        client.setex(key, ttl, value)
        log.debug(f"[DEBUG] [redis_models.set_models_for_user] Cached {len(models_dict)} models for user_id={user_id}, ttl={ttl}s.")
        return True
    except Exception as e:
        log.warning(f"[redis_models.set_models_for_user] Redis/write error for user_id={user_id}: {e}. Proceeding without cache.")
        return False


def invalidate_models_for_user(user_id: str) -> bool:
    """
    Invalidate (delete) the cached model list for a user.

    After model create/update/delete, call this so the next chat request
    will fetch fresh models via get_all_models and repopulate the cache.

    Args:
        user_id: User ID

    Returns:
        True on success, False on error (callers proceed anyway)
    """
    client = _get_redis_client()
    if client is None:
        log.debug(
            f"[DEBUG] [redis_models.invalidate_models_for_user] Redis unavailable for user_id={user_id}. Skipping invalidation."
        )
        return False

    key = f"models:user:{user_id}"
    try:
        client.delete(key)
        log.debug(f"[DEBUG] [redis_models.invalidate_models_for_user] Invalidated cache for user_id={user_id}.")
        return True
    except Exception as e:
        log.warning(
            f"[redis_models.invalidate_models_for_user] Redis/delete error for user_id={user_id}: {e}. Proceeding."
        )
        return False


def invalidate_models_for_all_users() -> bool:
    """
    Invalidate cached model lists for all users.

    Used when delete_all_models is called. Next chat request from any user
    will fetch fresh models via get_all_models and repopulate the cache.

    Returns:
        True on success, False on error (callers proceed anyway)
    """
    client = _get_redis_client()
    if client is None:
        log.debug("[DEBUG] [redis_models.invalidate_models_for_all_users] Redis unavailable. Skipping invalidation.")
        return False

    pattern = "models:user:*"
    try:
        count = 0
        for key in client.scan_iter(match=pattern):
            client.delete(key)
            count += 1
        log.debug(f"[DEBUG] [redis_models.invalidate_models_for_all_users] Invalidated {count} user cache(s).")
        return True
    except Exception as e:
        log.warning(f"[redis_models.invalidate_models_for_all_users] Redis error: {e}. Proceeding.")
        return False


def get_models_for_request(request) -> dict:
    """
    Get the models dict for the current request.

    Prefers request.state.MODELS (request-scoped, avoids concurrent overwrites)
    over request.app.state.MODELS (app-scoped, shared across requests).

    Returns:
        { model_id: model } dict. Never None; returns {} if neither is set.
    """
    models = getattr(request.state, "MODELS", None)
    if models is not None:
        return models
    return getattr(request.app.state, "MODELS", None) or {}


async def ensure_models_for_request(request, user) -> None:
    """
    Ensure per-user model list is available for the current request.

    Stores in request.state.MODELS (request-scoped) to avoid concurrent
    overwrites when multiple users hit different pods. Tries Redis first;
    on miss, calls get_all_models and writes to Redis.

    Args:
        request: FastAPI/Starlette request
        user: User model (must have user.id)
    """
    user_id = str(user.id)
    log.debug(f"[DEBUG] [redis_models.ensure_models_for_request] Ensuring models for user_id={user_id}.")

    # 1. Try Redis cache (sync call in thread to avoid blocking)
    models = await asyncio.to_thread(get_models_for_user, user_id)

    if models is not None:
        request.state.MODELS = models
        log.debug(
            f"[DEBUG] [redis_models.ensure_models_for_request] Loaded {len(models)} models from Redis for user_id={user_id}."
        )
        return

    # 2. Cache miss or Redis unavailable: call get_all_models
    log.debug(f"[DEBUG] [redis_models.ensure_models_for_request] Cache miss for user_id={user_id}. Calling get_all_models.")
    from open_webui.utils.models import get_all_models

    await get_all_models(request, user=user)
    models = request.app.state.MODELS

    # 3. Store in request.state (request-scoped) to avoid race with concurrent requests
    request.state.MODELS = models

    # 4. Write to Redis for future requests (sync call in thread)
    await asyncio.to_thread(set_models_for_user, user_id, models, MODELS_CACHE_TTL)
    log.debug(
        f"[DEBUG] [redis_models.ensure_models_for_request] get_all_models returned {len(models)} models for user_id={user_id}. "
        "Written to Redis."
    )
