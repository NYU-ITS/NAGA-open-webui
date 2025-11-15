"""
Multi-replica safe caching utility with Redis support and in-memory fallback.
Cache keys are user-specific to prevent data collisions across users.
Works safely in multi-replica OpenShift deployments.
"""
import json
import time
import logging
from typing import Optional, Dict, Any, Callable
from threading import Lock

log = logging.getLogger(__name__)

# Try to import and use Redis if available
_redis_client = None
_redis_available = False

try:
    from open_webui.env import REDIS_URL
    try:
        import redis
    except ImportError:
        redis = None
        log.debug("Redis package not installed, using in-memory cache only")
    
    if redis is not None:
        # Test Redis connection
        try:
            test_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            test_redis.ping()
            _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            _redis_available = True
            log.info("Redis cache enabled - using shared cache across replicas")
        except Exception as e:
            log.warning(f"Redis not available, using in-memory cache: {e}")
            _redis_available = False
    else:
        _redis_available = False
except Exception as e:
    log.debug(f"Redis not configured, using in-memory cache: {e}")
    _redis_available = False

# In-memory fallback cache (per-replica)
_in_memory_cache: Dict[str, tuple[Any, float]] = {}
_cache_lock = Lock()

# Default TTL: 5 minutes (300 seconds)
DEFAULT_TTL = 300

# Cache key prefix to namespace all cache entries
CACHE_PREFIX = "open_webui:cache:"


def _serialize_value(value: Any) -> str:
    """Serialize value for Redis storage."""
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError) as e:
        log.warning(f"Failed to serialize cache value: {e}")
        raise


def _deserialize_value(serialized: str) -> Any:
    """Deserialize value from Redis storage."""
    try:
        return json.loads(serialized)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning(f"Failed to deserialize cache value: {e}")
        return None


def _make_cache_key(key: str) -> str:
    """Create a namespaced cache key."""
    return f"{CACHE_PREFIX}{key}"


def get_cached(
    key: str,
    ttl: float = DEFAULT_TTL,
    factory: Optional[Callable[[], Any]] = None
) -> Optional[Any]:
    """
    Get a value from cache, or compute it using factory if not found/expired.
    Cache keys should be user-specific to prevent data collisions.
    
    Args:
        key: Cache key (should include user_id for user-specific data)
        ttl: Time to live in seconds (default: 5 minutes)
        factory: Optional callable that returns the value if cache miss
    
    Returns:
        Cached value or None if not found and no factory provided
    """
    cache_key = _make_cache_key(key)
    
    if _redis_available:
        try:
            # Try Redis first
            serialized = _redis_client.get(cache_key)
            if serialized:
                value = _deserialize_value(serialized)
                if value is not None:
                    return value
        except Exception as e:
            # Redis failed, fall back to in-memory
            log.debug(f"Redis get failed, using in-memory cache: {e}")
    
    # Check in-memory cache
    with _cache_lock:
        if cache_key in _in_memory_cache:
            value, timestamp = _in_memory_cache[cache_key]
            if time.time() - timestamp < ttl:
                return value
            # Expired, remove it
            del _in_memory_cache[cache_key]
    
    # Cache miss or expired - use factory if provided
    if factory is not None:
        try:
            value = factory()
            set_cached(key, value, ttl)
            return value
        except Exception as e:
            log.warning(f"Factory function failed for cache key {key}: {e}")
            # Return None if factory fails - caller should handle this
            return None
    
    return None


def set_cached(key: str, value: Any, ttl: float = DEFAULT_TTL) -> None:
    """
    Set a value in cache with TTL.
    Cache keys should be user-specific to prevent data collisions.
    
    Args:
        key: Cache key (should include user_id for user-specific data)
        value: Value to cache (must be JSON serializable)
        ttl: Time to live in seconds (default: 5 minutes)
    """
    cache_key = _make_cache_key(key)
    
    if _redis_available:
        try:
            # Try Redis first
            serialized = _serialize_value(value)
            _redis_client.setex(cache_key, int(ttl), serialized)
            return
        except Exception as e:
            # Redis failed, fall back to in-memory
            log.debug(f"Redis set failed, using in-memory cache: {e}")
    
    # Fall back to in-memory cache
    with _cache_lock:
        _in_memory_cache[cache_key] = (value, time.time())


def clear_cached(key: Optional[str] = None, pattern: Optional[str] = None) -> None:
    """
    Clear cache entry(s).
    
    Args:
        key: If provided, clear only this specific key
        pattern: If provided, clear all keys matching this pattern (Redis only)
                 For in-memory, this will match keys containing the pattern
    """
    if key is not None:
        cache_key = _make_cache_key(key)
        
        if _redis_available:
            try:
                _redis_client.delete(cache_key)
            except Exception as e:
                log.debug(f"Redis delete failed: {e}")
        
        with _cache_lock:
            if cache_key in _in_memory_cache:
                del _in_memory_cache[cache_key]
    
    elif pattern is not None:
        # Clear by pattern
        pattern_key = _make_cache_key(pattern)
        
        if _redis_available:
            try:
                # Use Redis SCAN to find matching keys
                cursor = 0
                while True:
                    cursor, keys = _redis_client.scan(cursor, match=f"{pattern_key}*", count=100)
                    if keys:
                        _redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                log.debug(f"Redis pattern delete failed: {e}")
        
        # Clear from in-memory cache
        with _cache_lock:
            keys_to_delete = [
                k for k in _in_memory_cache.keys()
                if k.startswith(pattern_key)
            ]
            for k in keys_to_delete:
                del _in_memory_cache[k]
    
    else:
        # Clear all cache (use with caution in multi-replica setup)
        if _redis_available:
            try:
                # Only clear our namespace
                cursor = 0
                while True:
                    cursor, keys = _redis_client.scan(cursor, match=f"{CACHE_PREFIX}*", count=100)
                    if keys:
                        _redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                log.debug(f"Redis clear all failed: {e}")
        
        with _cache_lock:
            _in_memory_cache.clear()


def clear_user_cache(user_id: str) -> None:
    """
    Clear all cache entries for a specific user.
    This is safer than clearing all cache in multi-replica setups.
    
    Args:
        user_id: User ID to clear cache for
    """
    # Clear user-specific cache patterns
    patterns = [
        f"user_groups:{user_id}",
        f"models_list:{user_id}",
        f"tools_list:{user_id}",
        f"prompts_list:{user_id}",
        f"knowledge_list:{user_id}",
    ]
    
    for pattern in patterns:
        clear_cached(pattern=pattern)


def clear_expired() -> None:
    """Remove all expired entries from cache."""
    current_time = time.time()
    
    if _redis_available:
        # Redis handles TTL automatically, no need to clean up
        pass
    
    # Clean up in-memory cache
    with _cache_lock:
        expired_keys = [
            key for key, (_, timestamp) in _in_memory_cache.items()
            if current_time - timestamp >= DEFAULT_TTL
        ]
        for key in expired_keys:
            del _in_memory_cache[key]
