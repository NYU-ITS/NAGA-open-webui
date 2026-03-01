import json
import time
import logging
import sys
import threading
from collections import OrderedDict

from aiocache import cached
from fastapi import Request
from redis import Redis

from open_webui.routers import openai, ollama
from open_webui.functions import get_function_models


from open_webui.models.functions import Functions
from open_webui.models.models import Models


from open_webui.utils.plugin import load_function_module_by_id
from open_webui.utils.access_control import has_access


from open_webui.config import (
    DEFAULT_ARENA_MODEL,
)

from open_webui.env import SRC_LOG_LEVELS, GLOBAL_LOG_LEVEL, REDIS_URL
from open_webui.models.users import UserModel
from open_webui.socket.utils import get_redis_pool, get_redis_master_connection

# Redis pub/sub channel for cross-pod models cache invalidation
MODELS_INVALIDATE_CHANNEL = "open_webui:models:invalidate"


class _ModelsLRUCache(OrderedDict):
    """
    LRU cache for models per user. Evicts least recently used when maxsize is exceeded.
    maxsize must be >= 1. Subclass of OrderedDict so isinstance(..., dict) passes.
    """

    def __init__(self, maxsize=1000, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        elif self.maxsize > 0 and len(self) >= self.maxsize:
            self.popitem(last=False)
        super().__setitem__(key, value)

    def get(self, key, default=None):
        if key not in self:
            return default
        self.move_to_end(key)
        return super().get(key, default)
# Payload meaning "clear entire cache for all users"
MODELS_INVALIDATE_ALL = "all"


def _get_super_admin_user_ids() -> list:
    """Return user_ids for all super admins (they see all models, so must be invalidated on any model change)."""
    from open_webui.models.users import Users
    from open_webui.utils.super_admin import get_super_admin_emails

    ids = []
    for email in get_super_admin_emails() or []:
        u = Users.get_user_by_email(email)
        if u and getattr(u, "id", None):
            ids.append(u.id)
    return ids


def get_affected_user_ids_for_model(model) -> list:
    """
    Return user_ids whose models cache might include this model.
    Used for per-user cache invalidation so we only clear cache for affected users.
    """
    from open_webui.models.groups import Groups

    affected = set()
    if getattr(model, "user_id", None):
        affected.add(model.user_id)
    ac = getattr(model, "access_control", None) or {}
    read = ac.get("read") or {}
    write = ac.get("write") or {}
    group_ids = list(set((read.get("group_ids") or []) + (write.get("group_ids") or [])))
    for gid in group_ids:
        group = Groups.get_group_by_id(gid)
        if group:
            if group.user_id:
                affected.add(group.user_id)
            for uid in group.user_ids or []:
                affected.add(uid)
    for uid in (read.get("user_ids") or []) + (write.get("user_ids") or []):
        affected.add(uid)
    # Super admins see all models; invalidate their cache on any model change
    for uid in _get_super_admin_user_ids():
        affected.add(uid)
    return list(affected)


logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


async def get_all_base_models(request: Request, user: UserModel = None):
    function_models = []
    openai_models = []
    ollama_models = []
    # We do not need to use Ollama and OpenAI models cuz the only models we use are via Pipe Functions (portkey) 
    # That means, we do not necessarily have to check the first two models (openai and ollama). 
    # Possibly consider commenting them out.

    if request.app.state.config.ENABLE_OPENAI_API:
        openai_models = await openai.get_all_models(request, user=user)
        openai_models = openai_models["data"]

    if request.app.state.config.ENABLE_OLLAMA_API:
        ollama_models = await ollama.get_all_models(request, user=user)
        ollama_models = [
            {
                "id": model["model"],
                "name": model["name"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "ollama",
                "ollama": model,
            }
            for model in ollama_models["models"]
        ]

    function_models = await get_function_models(request, user=user)
    models = function_models + openai_models + ollama_models

    return models


async def get_all_models(request, user: UserModel = None):
    log.debug("[DEBUG] [inside get_all_models()] get_all_models() is called...")
    models = await get_all_base_models(request, user=user)
    log.debug("[DEBUG] [inside get_all_models()] get_all_base_models() returned models.")
    log.debug(f"[DEBUG] [inside get_all_models()] get_all_base_models() defined inside functions.py called from models.py returned {len(models)} models. Not sure if these models are pre-filtered to reflect the user's own models/models accessible to the user or not prefiltered but lists ALL models/functions. Here are the models: {models}")

    # If there are no models, return an empty list
    if len(models) == 0:
        log.debug("[DEBUG] [inside get_all_models()] get_all_models() returning an empty list because get_all_base_models() returned an empty list.")
        return []

    # Add arena models
    if request.app.state.config.ENABLE_EVALUATION_ARENA_MODELS:
        log.debug("[DEBUG] get_all_models() adding arena models because ENABLE_EVALUATION_ARENA_MODELS is True. We should set the env var to FALSE")
        arena_models = []
        if len(request.app.state.config.EVALUATION_ARENA_MODELS) > 0:
            arena_models = [
                {
                    "id": model["id"],
                    "name": model["name"],
                    "info": {
                        "meta": model["meta"],
                    },
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "arena",
                    "arena": True,
                }
                for model in request.app.state.config.EVALUATION_ARENA_MODELS
            ]
        else:
            # Add default arena model
            arena_models = [
                {
                    "id": DEFAULT_ARENA_MODEL["id"],
                    "name": DEFAULT_ARENA_MODEL["name"],
                    "info": {
                        "meta": DEFAULT_ARENA_MODEL["meta"],
                    },
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "arena",
                    "arena": True,
                }
            ]
        models = models + arena_models

    global_action_ids = [
        function.id for function in Functions.get_global_action_functions()
    ]
    log.debug(f"[DEBUG] [inside get_all_models()] global_action_ids: {global_action_ids}. Length of global_action_ids: {len(global_action_ids)}. The Functions.get_global_action_functions() returned {Functions.get_global_action_functions()}")
    enabled_action_ids = [
        function.id
        for function in Functions.get_functions_by_type("action", active_only=True)
    ]
    log.debug(f"[DEBUG] [inside get_all_models()] Now, filtering for active action_ids based on the global_action_ids. enabled_action_ids: {enabled_action_ids}. Length of enabled_action_ids:{len(enabled_action_ids)}")

    custom_models = Models.get_all_models(user.id, user.email)
    log.debug(f"[DEBUG] [inside get_all_models()] custom_models: {custom_models}. Length of custom_models: {len(custom_models)}. The Models.get_all_models() returned {Models.get_all_models(user.id, user.email)}. This is for user: {user.email} and user_id: {user.id}")
    for custom_model in custom_models:
        if custom_model.base_model_id is None:
            log.debug(f"the custom.base_model_id is None for custom model: {custom_model}")
            for model in models:
                if (
                    custom_model.id == model["id"]
                    or custom_model.id == model["id"].split(":")[0]
                ):
                    if custom_model.is_active:
                        model["name"] = custom_model.name
                        model["info"] = custom_model.model_dump()

                        action_ids = []
                        if "info" in model and "meta" in model["info"]:
                            action_ids.extend(
                                model["info"]["meta"].get("actionIds", [])
                            )

                        model["action_ids"] = action_ids
                    else:
                        models.remove(model)

        elif custom_model.is_active and (
            custom_model.id not in [model["id"] for model in models]
        ):
            owned_by = "openai"
            pipe = None
            action_ids = []

            for model in models:
                if (
                    custom_model.base_model_id == model["id"]
                    or custom_model.base_model_id == model["id"].split(":")[0]
                ):
                    owned_by = model.get("owned_by", "unknown owner")
                    if "pipe" in model:
                        pipe = model["pipe"]
                    break

            if custom_model.meta:
                meta = custom_model.meta.model_dump()
                if "actionIds" in meta:
                    action_ids.extend(meta["actionIds"])

            models.append(
                {
                    "id": f"{custom_model.id}",
                    "name": custom_model.name,
                    "object": "model",
                    "created": custom_model.created_at,
                    "owned_by": owned_by,
                    "info": custom_model.model_dump(),
                    "preset": True,
                    **({"pipe": pipe} if pipe is not None else {}),
                    "action_ids": action_ids,
                }
            )

    # Process action_ids to get the actions
    def get_action_items_from_module(function, module):
        actions = []
        if hasattr(module, "actions"):
            actions = module.actions
            return [
                {
                    "id": f"{function.id}.{action['id']}",
                    "name": action.get("name", f"{function.name} ({action['id']})"),
                    "description": function.meta.description,
                    "icon_url": action.get(
                        "icon_url", function.meta.manifest.get("icon_url", None)
                    ),
                }
                for action in actions
            ]
        else:
            return [
                {
                    "id": function.id,
                    "name": function.name,
                    "description": function.meta.description,
                    "icon_url": function.meta.manifest.get("icon_url", None),
                }
            ]

    def get_function_module_by_id(function_id):
        if function_id in request.app.state.FUNCTIONS:
            function_module = request.app.state.FUNCTIONS[function_id]
        else:
            function_module, _, _ = load_function_module_by_id(function_id)
            request.app.state.FUNCTIONS[function_id] = function_module

    current_user_email = user.email if user else None

    for model in models:
        action_ids = [
            action_id
            for action_id in list(set(model.pop("action_ids", []) + global_action_ids))
            if action_id in enabled_action_ids
        ]

        model["actions"] = []
        for action_id in action_ids:
            action_function = Functions.get_function_by_id(action_id)
            if action_function is None:
                raise Exception(f"Action not found: {action_id}")

            if current_user_email and action_function.created_by != current_user_email:
                continue

            function_module = get_function_module_by_id(action_id)
            model["actions"].extend(
                get_action_items_from_module(action_function, function_module)
            )
    log.debug(f"get_all_models() returned {len(models)} models")

    _ensure_models_cache(request)
    user_id = user.id if user else ""
    request.app.state.MODELS[user_id] = {model["id"]: model for model in models}
    cache = request.app.state.MODELS
    model_names = [m.get("name", m.get("id", "")) for m in models]
    log.debug(
        "[models cache] stored user_id=%s models_count=%s model_names=%s cache_size=%s",
        user_id,
        len(models),
        model_names,
        len(cache),
    )
    return models


def _ensure_models_cache(request):
    """Ensure app.state.MODELS is a dict (user_id -> {model_id: model}). Uses LRU with max size from config."""
    mod = getattr(request.app.state, "MODELS", None)
    if not isinstance(mod, dict):
        maxsize = getattr(
            request.app.state,
            "MODELS_CACHE_MAX_USERS",
            1000,
        )
        request.app.state.MODELS = _ModelsLRUCache(maxsize=maxsize)


def _get_redis_connection_for_publish():
    """
    Get a Redis connection for one-off publish (same pattern as CacheManager).
    Uses shared pool and Sentinel when configured.
    """
    if not REDIS_URL or not REDIS_URL.strip():
        return None
    try:
        pool = get_redis_pool(REDIS_URL, use_master=True)
        if hasattr(pool, "_conn"):
            return pool._conn
        if hasattr(pool, "get_connection"):
            conn = get_redis_master_connection()
            return conn if conn is not None else Redis(connection_pool=pool)
        return Redis(connection_pool=pool)
    except Exception:
        return None


def _publish_models_invalidate(payload: str) -> None:
    """Publish an invalidation message to Redis. Payload: MODELS_INVALIDATE_ALL or JSON list of user_ids."""
    redis_conn = _get_redis_connection_for_publish()
    if redis_conn is None:
        return
    try:
        redis_conn.publish(MODELS_INVALIDATE_CHANNEL, payload)
    except Exception as e:
        log.debug("Redis publish for models cache invalidation failed: %s", e)


def invalidate_models_cache(
    request: Request, affected_user_ids: list | None = None
) -> None:
    """
    Clear the in-memory models cache so the next get_models_for_user() refetches.
    If affected_user_ids is provided, only those users' cache entries are cleared (per-user invalidation).
    Otherwise the entire cache is cleared.
    Also publishes to Redis so other pods clear the same entries (cross-pod consistency).
    Call this after create/update/toggle/delete model or when granting/revoking access.
    """
    _ensure_models_cache(request)
    mod = request.app.state.MODELS
    cache_size_before = len(mod)
    if affected_user_ids:
        for uid in affected_user_ids:
            mod.pop(str(uid), None)  # keys are user.id (string); match listener
        _publish_models_invalidate(json.dumps([str(u) for u in affected_user_ids]))
        log.debug(
            "[models cache] invalidated local affected_user_ids=%s cache_size_before=%s cache_size_after=%s",
            affected_user_ids,
            cache_size_before,
            len(mod),
        )
    else:
        mod.clear()
        _publish_models_invalidate(MODELS_INVALIDATE_ALL)
        log.debug(
            "[models cache] invalidated local all users cache_size_before=%s",
            cache_size_before,
        )


def _get_redis_connection_for_subscribe():
    """
    Get a dedicated Redis connection for pub/sub listener (must not share pool
    since subscribe() blocks). Uses Sentinel when configured, same as rest of app.
    """
    if not REDIS_URL or not REDIS_URL.strip():
        return None
    try:
        from open_webui.env import REDIS_USE_SENTINEL, REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_SERVICE_NAME
        if REDIS_USE_SENTINEL and REDIS_SENTINEL_HOSTS:
            from open_webui.socket.utils import get_redis_sentinel_connection
            from urllib.parse import urlparse
            sentinel = get_redis_sentinel_connection()
            if sentinel is None:
                return Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=None)
            master_kwargs = {
                "socket_timeout": None,  # Block indefinitely for pub/sub listen()
                "socket_connect_timeout": 5,
                "decode_responses": True,
            }
            parsed = urlparse(REDIS_URL)
            if parsed.password:
                master_kwargs["password"] = parsed.password
            return sentinel.master_for(REDIS_SENTINEL_SERVICE_NAME, **master_kwargs)
        return Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=None)
    except Exception:
        return None


def start_models_cache_invalidation_listener(app) -> None:
    """
    Start a background thread that subscribes to Redis and clears this pod's
    models cache when any pod publishes an invalidation (e.g. after model create/update/delete).
    Uses same Redis config as admin/cache (pool for publish, Sentinel-aware connection for subscribe).
    """
    if not REDIS_URL or not REDIS_URL.strip():
        log.debug("REDIS_URL not set, skipping models cache invalidation listener")
        return

    def _listener() -> None:
        while True:
            redis_conn = None
            try:
                redis_conn = _get_redis_connection_for_subscribe()
                if redis_conn is None:
                    time.sleep(10)
                    continue
                pubsub = redis_conn.pubsub()
                pubsub.subscribe(MODELS_INVALIDATE_CHANNEL)
                for message in pubsub.listen():
                    if message.get("type") == "message":
                        mod = getattr(app.state, "MODELS", None)
                        if not isinstance(mod, dict):
                            continue
                        data = message.get("data")
                        # "all" or legacy "1" = clear entire cache
                        if data == MODELS_INVALIDATE_ALL or data == "1":
                            size_before = len(mod)
                            mod.clear()
                            log.debug(
                                "[models cache] listener cleared all users cache_size_before=%s",
                                size_before,
                            )
                        else:
                            try:
                                user_ids = json.loads(data)
                                if isinstance(user_ids, list):
                                    size_before = len(mod)
                                    for uid in user_ids:
                                        mod.pop(str(uid), None)
                                    if user_ids:
                                        log.debug(
                                            "[models cache] listener cleared user_ids=%s cache_size_before=%s cache_size_after=%s",
                                            user_ids,
                                            size_before,
                                            len(mod),
                                        )
                                else:
                                    mod.clear()
                            except (json.JSONDecodeError, TypeError):
                                mod.clear()
            except Exception as e:
                log.warning("Models cache invalidation listener error: %s. Reconnecting in 10s.", e)
                if redis_conn:
                    try:
                        redis_conn.close()
                    except Exception:
                        pass
                time.sleep(10)

    thread = threading.Thread(target=_listener, daemon=True)
    thread.start()
    log.info("Models cache invalidation listener started (Redis pub/sub)")


async def get_models_for_user(request, user) -> dict:
    """
    Return the model dict for the current user (model_id -> model).
    Uses per-user cache; refreshes from get_all_models if not cached.
    Call this instead of reading request.app.state.MODELS directly.
    """
    _ensure_models_cache(request)
    if user is None:
        return {}
    user_id = user.id
    cache = request.app.state.MODELS
    models = cache.get(user_id)
    if models is None:
        log.debug(
            "[models cache] miss user_id=%s cache_size=%s",
            user_id,
            len(cache),
        )
        await get_all_models(request, user=user)
        models = cache.get(user_id, {})
    else:
        model_names = [m.get("name", m.get("id", "")) for m in (models or {}).values()]
        log.debug(
            "[models cache] hit user_id=%s models_count=%s model_names=%s cache_size=%s",
            user_id,
            len(models),
            model_names,
            len(cache),
        )
    return models


def check_model_access(user, model):
    from open_webui.utils.workspace_access import item_assigned_to_user_groups
    
    if model.get("arena"):
        if not has_access(
            user.id,
            type="read",
            access_control=model.get("info", {})
            .get("meta", {})
            .get("access_control", {}),
        ):
            raise Exception("Model not found")
    else:
        model_info = Models.get_model_by_id(model.get("id"))
        if not model_info:
            raise Exception("Model not found")
        
        # Check if user is creator
        if user.id == model_info.user_id:
            return  # Creator has access
        
        # ENFORCE: If access_control is None, treat as PRIVATE (creator only)
        if model_info.access_control is None:
            raise Exception("Model not found")  # Private to creator only
        
        # Check group assignments
        if item_assigned_to_user_groups(user.id, model_info, "read"):
            return  # User has access via group assignment
        
        # Check has_access for models with explicit access_control
        if has_access(user.id, type="read", access_control=model_info.access_control):
            return  # User has explicit access
        
        # No access
        raise Exception("Model not found")
