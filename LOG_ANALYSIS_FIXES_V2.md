# Log Analysis & Performance Fixes V2

## Analysis Date
2025-11-14

## Log File Analyzed
`open-webui-0-open-webui (5).log`

## Summary of Findings

### ✅ Good News
1. **No Errors** - Application running without crashes
2. **Plugin Loading Optimized** - 12 plugins in 2.81s (parallel, down from 6.1s sequential)
3. **Models API Improved** - 3.7s total (down from 9.2s)
4. **Migrations Successful** - JSONB conversion and GIN indexes created

### 🔴 Issues Identified

#### 1. Tools API - Duplicate Calls
- **Issue**: 11 calls in 6.37s (lines 290-305)
- **Root Cause**: Cache may not be working or TTL too short
- **Status**: Caching already implemented, but still seeing duplicates

#### 2. Portkey API - Sequential Calls
- **Issue**: 4 sequential calls per `/api/models` request
- **Impact**: Each call adds ~0.5-1s delay
- **Root Cause**: Function plugins call Portkey API independently in their `pipes()` methods
- **Location**: `backend/open_webui/functions.py` - `pipes()` calls were sequential

#### 3. Individual Chat API Calls
- **Issue**: 58 individual chat calls over 197 seconds
- **Impact**: Could be batched or cached
- **Example**: Same chat fetched 4 times (`4def6283-7159-44a0-9a69-a9be172aa001`)

#### 4. `/api/config` - Multiple Group Lookups
- **Issue**: Lines 172-190 show repeated "User is part of groups: []" lookups
- **Root Cause**: Each config call triggers group lookup
- **Impact**: Unnecessary database queries

## Fixes Implemented

### Fix 1: Increased `get_all_models` Cache TTL ✅
**File**: `backend/open_webui/routers/openai.py`
- **Change**: Increased cache TTL from 3s to 60s
- **Impact**: Reduces repeated model API calls
- **Expected Improvement**: 70-80% reduction in `/api/models` calls

```python
@cached(ttl=60, key_builder=_models_cache_key)
async def get_all_models(request: Request, user: UserModel) -> dict[str, list]:
```

### Fix 2: Cached Group Lookups in Config ✅
**File**: `backend/open_webui/config.py`
- **Change**: Added `_get_user_groups_cached()` function with 30s TTL
- **Impact**: Eliminates repeated database queries for group membership
- **Expected Improvement**: 50-70% reduction in group lookup queries

```python
def _get_user_groups_cached(user_id: str) -> list:
    """Get user groups with caching to avoid repeated database queries"""
    # 30 second TTL cache
```

### Fix 3: Parallelized Portkey API Calls ✅
**File**: `backend/open_webui/functions.py`
- **Change**: Parallelized `pipes()` calls using `asyncio.gather()`
- **Impact**: Portkey API calls now execute in parallel instead of sequentially
- **Expected Improvement**: 4 sequential calls (2-4s) → 1 parallel batch (~0.5-1s)

```python
# Collect all pipes() calls and execute them in parallel
pipes_tasks = [
    get_pipes_from_module(pipe, function_module)
    for pipe, function_module in pipe_modules.values()
]
pipes_results = await asyncio.gather(*pipes_tasks, return_exceptions=True)
```

### Fix 4: Batch Chat Endpoint ✅
**File**: `backend/open_webui/routers/chats.py`
- **Change**: Added `POST /api/v1/chats/batch` endpoint
- **Impact**: Frontend can fetch multiple chats in one request
- **Expected Improvement**: 58 individual calls → 1-2 batch calls

```python
@router.post("/batch", response_model=BatchChatResponse)
async def batch_get_chats(
    form_data: BatchChatRequest, user=Depends(get_verified_user)
):
    """Get multiple chats in a single request to reduce API calls"""
```

## Expected Performance Improvements

| Operation | Before | After | Improvement |
|-----------|--------|-------|-------------|
| `/api/models` cache | 3s TTL | 60s TTL | 70-80% fewer calls |
| Group lookups | Every call | 30s cache | 50-70% fewer queries |
| Portkey API calls | 4 sequential (2-4s) | 1 parallel (~0.5-1s) | 75-87% faster |
| Chat API calls | 58 individual | 1-2 batch | 95%+ fewer calls |

## Next Steps (Optional Future Optimizations)

1. **Frontend Integration**: Update frontend to use batch chat endpoint
2. **Tools API**: Investigate why cache isn't preventing duplicates
3. **Response Compression**: Already implemented (GzipMiddleware)
4. **Database Connection Pooling**: Verify pool settings are optimal

## Testing Recommendations

1. Monitor `/api/models` endpoint - should see fewer calls
2. Check group lookup queries in database logs - should see caching
3. Verify Portkey API calls are parallel in logs
4. Test batch chat endpoint: `POST /api/v1/chats/batch` with `{"chat_ids": ["id1", "id2", ...]}`

## Files Modified

1. `backend/open_webui/routers/openai.py` - Increased cache TTL
2. `backend/open_webui/config.py` - Added group lookup caching
3. `backend/open_webui/functions.py` - Parallelized pipes() calls
4. `backend/open_webui/routers/chats.py` - Added batch endpoint

