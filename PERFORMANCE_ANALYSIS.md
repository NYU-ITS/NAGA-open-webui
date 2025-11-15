# Performance Analysis - OpenShift Deployment Logs

**Analysis Date**: 2025-11-15  
**Log File**: open-webui-0-open-webui (7).log  
**Time Range**: 05:02:32 - 05:03:12 (40 seconds)

---

## Executive Summary

The application shows **significant performance issues** with:
- **Sequential Portkey API calls** causing 1.6+ second delays
- **Excessive super-admin checks** (40+ calls in 2 seconds)
- **Repeated user group lookups** (N+1 query pattern)
- **Redis cache unavailable** (falling back to in-memory cache)
- **Delayed workspace tab loading** (16+ second gap between tools and knowledge)

---

## Detailed Latency Breakdown

### 1. Initial Page Load (05:02:36.962 - 05:02:39.885)

| Operation | Timestamp | Duration | Notes |
|-----------|-----------|----------|-------|
| GET / | 05:02:36.962 | - | Initial page request |
| Static assets (parallel) | 05:02:37.094 - 05:02:39.358 | ~2.3s | 60+ asset requests |
| GET /api/config | 05:02:39.572 | ~2.6s from start | **6 user group lookups** (lines 173-190) |
| GET /api/v1/auths/ | 05:02:39.885 | ~2.9s from start | **6 more user group lookups** (lines 196-213) |

**Total Initial Load**: ~2.9 seconds  
**Issue**: User group lookups happening 12 times for same user in 0.3 seconds

---

### 2. Models Loading (05:02:41.731 - 05:02:43.318)

| Operation | Timestamp | Duration | Notes |
|-----------|-----------|----------|-------|
| get_all_models() called | 05:02:41.731 | - | Function entry |
| Load function_llm_german_professor | 05:02:41.976 | 0.245s | Portkey API call (lines 219-231) |
| Load function_portkey_admin1 | 05:02:42.138 | 0.162s | Portkey API call (lines 233-245) |
| Load function_llm_coadmin_professor2_admin | 05:02:42.251 | 0.113s | Portkey API call (lines 247-259) |
| Load function_llm_jy4421 | 05:02:42.412 | 0.161s | No Portkey call |
| Load function_llm_test1 | 05:02:42.540 | 0.128s | No Portkey call |
| Load function_llm_beta_jy4421 | 05:02:42.582 | 0.042s | Portkey API call (lines 263-275) |
| Load function_llm_sm11538 | 05:02:42.687 | 0.105s | No Portkey call |
| Load function_llms | 05:02:42.725 | 0.038s | No Portkey call |
| Load function_llm_ps5226 | 05:02:42.762 | 0.037s | No Portkey call |
| Load function_llm_rss9347 | 05:02:42.798 | 0.036s | No Portkey call |
| Load function_llm_stutimshra | 05:02:42.835 | 0.037s | No Portkey call |
| Load function_llms_aa12947 | 05:02:42.871 | 0.036s | No Portkey call |
| GET /api/models | 05:02:43.318 | **1.587s total** | Response sent |

**Total Models Load Time**: **1.59 seconds**  
**Portkey API Calls**: 4 sequential calls (should be parallel)  
**Function Module Loads**: 12 modules loaded sequentially

---

### 3. Tools Loading (05:02:43.817)

| Operation | Timestamp | Duration | Notes |
|-----------|-----------|----------|-------|
| GET /api/v1/tools/?skip=0&limit=1000 | 05:02:43.817 | **<0.1s** | ✅ Fast (cached) |

**Tools Load Time**: **<100ms** ✅ **Excellent**

---

### 4. Knowledge Loading (05:02:59.972)

| Operation | Timestamp | Duration | Notes |
|-----------|-----------|----------|-------|
| GET /api/v1/knowledge/?skip=0&limit=1000 | 05:02:59.972 | **~16s delay** | ⚠️ **16 seconds after tools!** |
| GET /api/v1/knowledge/list | 05:03:00.903 | 0.931s | Additional call |

**Knowledge Load Time**: **~1 second** (but delayed by 16 seconds)  
**Issue**: Why is knowledge loading 16 seconds after tools? Likely lazy loading or user interaction trigger.

---

### 5. Prompts Loading (05:03:01.640 - 05:03:01.697)

| Operation | Timestamp | Duration | Notes |
|-----------|-----------|----------|-------|
| GET /api/v1/prompts/list | 05:03:01.640 | - | First call |
| GET /api/v1/prompts/?skip=0&limit=1000 | 05:03:01.697 | 0.057s | Second call |

**Prompts Load Time**: **<100ms** ✅ **Excellent**

---

### 6. Super-Admin Checks (05:02:47.506 - 05:03:12.915)

| Operation | Count | Duration | Notes |
|-----------|-------|----------|-------|
| GET /api/v1/users/is-super-admin | **40+ calls** | ~25 seconds | ⚠️ **Excessive!** |

**Timeline**:
- First batch: 05:02:47.506 - 05:02:48.933 (1.4 seconds, 20 calls)
- Second batch: 05:02:49.014 - 05:02:49.144 (0.13 seconds, 5 calls)
- Third batch: 05:03:11.314 - 05:03:12.915 (1.6 seconds, 15+ calls)

**Issue**: Checking super-admin status for **every user in the list** individually. Should be batched or cached.

---

### 7. User Group Lookups (Repeated Pattern)

**Pattern Observed**:
```
User ms15138@nyu.edu maps to user_id=199e3d14-0c91-4668-a0fd-8fd6e2dd99d1
User ms15138@nyu.edu is part of groups: []
Using default for ms15138@nyu.edu for rag.web.search.enable
```

This pattern repeats **6 times** in 0.3 seconds (lines 173-190, 196-213).

**Issue**: User group lookup happening for **every config property check**. Should be cached per request.

---

### 8. Portkey API Calls (Sequential)

**Observed Pattern**:
- 05:02:41.976 - Portkey API call #1 (function_llm_german_professor)
- 05:02:42.138 - Portkey API call #2 (function_portkey_admin1)
- 05:02:42.251 - Portkey API call #3 (function_llm_coadmin_professor2_admin)
- 05:02:42.582 - Portkey API call #4 (function_llm_beta_jy4421)
- 05:02:55.121 - Portkey API call #5 (get_all_models again)
- 05:02:58.099 - Portkey API call #6 (get_all_models again)

**Issue**: These are **sequential** when they could be **parallel**. Each call takes ~0.15-0.25 seconds.

---

## Critical Problems Identified

### 🔴 Problem 1: Redis Cache Unavailable
**Line 41**: `Redis not available, using in-memory cache: Error 111 connecting to localhost:6379. Connection refused.`

**Impact**: 
- Cache is per-replica (not shared)
- Cache invalidation doesn't work across replicas
- Each replica has its own cache

**Solution**: Configure Redis URL properly or use shared Redis instance.

---

### 🔴 Problem 2: Excessive Super-Admin Checks
**40+ individual API calls** to `/api/v1/users/is-super-admin?email=...`

**Impact**:
- Each call likely hits the database
- No batching or caching
- 25+ seconds of cumulative latency

**Solution**: 
- Batch check all users in one query
- Cache super-admin list
- Return super-admin status in user list endpoint

---

### 🔴 Problem 3: Sequential Portkey API Calls
**4-6 sequential calls** to Portkey API during models loading

**Impact**:
- 0.6-1.0 seconds wasted on sequential network calls
- Could be parallelized to ~0.2 seconds

**Solution**: Use `asyncio.gather()` or `concurrent.futures` to parallelize.

---

### 🟡 Problem 4: Repeated User Group Lookups
**12 lookups** for the same user in 0.3 seconds

**Impact**:
- Each lookup hits database/cache
- Wasted queries for same data

**Solution**: Cache user groups per request context (request-scoped cache).

---

### 🟡 Problem 5: Delayed Knowledge Loading
**16-second gap** between tools (05:02:43.817) and knowledge (05:02:59.972)

**Impact**:
- Poor user experience
- Likely lazy loading or user-triggered

**Solution**: Pre-load all workspace tabs in parallel.

---

### 🟡 Problem 6: Multiple get_all_models() Calls
**3 separate calls** to `get_all_models()`:
- 05:02:41.731 (initial)
- 05:02:55.121 (second)
- 05:02:58.099 (third)

**Impact**:
- Each call loads 12 function modules
- Redundant work

**Solution**: Cache models list with longer TTL or use request-scoped cache.

---

## Performance Metrics Summary

| Metric | Value | Status |
|--------|-------|--------|
| **Initial Page Load** | 2.9s | ⚠️ Slow |
| **Models Loading** | 1.6s | ⚠️ Slow (Portkey API) |
| **Tools Loading** | <0.1s | ✅ Excellent |
| **Knowledge Loading** | 1.0s | ✅ Fast (but delayed 16s) |
| **Prompts Loading** | <0.1s | ✅ Excellent |
| **Super-Admin Checks** | 40+ calls | 🔴 Excessive |
| **User Group Lookups** | 12+ per request | 🟡 Excessive |
| **Portkey API Calls** | 4-6 sequential | 🔴 Should be parallel |

---

## Recommendations for Improvement

### 🔴 High Priority (Immediate Impact)

#### 1. Fix Redis Configuration
**Problem**: Redis not available, using in-memory cache per replica.

**Solution**:
- Configure `REDIS_URL` environment variable in StatefulSet
- Ensure Redis service is accessible from pods
- Verify Redis connection on startup

**Expected Impact**: Shared cache across replicas, proper cache invalidation.

---

#### 2. Batch Super-Admin Checks
**Problem**: 40+ individual API calls to check super-admin status.

**Solution**:
- Create endpoint: `POST /api/v1/users/is-super-admin/batch` that accepts list of emails
- Or: Include `is_super_admin` flag in `GET /api/v1/users/` response
- Cache super-admin list (changes infrequently)

**Expected Impact**: Reduce 40+ calls to 1 call, save ~2-3 seconds.

---

#### 3. Parallelize Portkey API Calls
**Problem**: Sequential Portkey API calls during models loading.

**Solution**:
```python
# Instead of sequential:
for function in functions:
    result = await portkey_api_call(function)

# Use parallel:
results = await asyncio.gather(*[
    portkey_api_call(function) 
    for function in functions
])
```

**Expected Impact**: Reduce 0.6-1.0s to ~0.2s (3-5x faster).

---

### 🟡 Medium Priority (Significant Impact)

#### 4. Request-Scoped User Group Cache
**Problem**: User group lookup happening 12+ times per request.

**Solution**:
- Cache user groups in request context (FastAPI `Request.state`)
- Lookup once per request, reuse for all config checks

**Expected Impact**: Reduce 12+ queries to 1 query per request.

---

#### 5. Pre-load All Workspace Tabs
**Problem**: Knowledge loads 16 seconds after tools (lazy loading).

**Solution**:
- Load models, tools, prompts, and knowledge in parallel on initial page load
- Use `Promise.all()` or `asyncio.gather()` on frontend

**Expected Impact**: All tabs ready in ~1-2 seconds instead of 16+ seconds.

---

#### 6. Cache Models List Longer
**Problem**: `get_all_models()` called 3 times, reloading function modules.

**Solution**:
- Increase cache TTL for models list (currently 60s, try 300s)
- Use request-scoped cache to avoid duplicate calls in same request

**Expected Impact**: Reduce redundant function module loading.

---

### 🟢 Low Priority (Nice to Have)

#### 7. Optimize Static Asset Loading
**Problem**: 60+ static asset requests (though parallel).

**Solution**:
- Use HTTP/2 Server Push
- Bundle smaller assets
- Use CDN for static assets

**Expected Impact**: Slight improvement in initial load.

---

#### 8. Add Response Compression
**Problem**: Large JSON responses (models, tools, etc.).

**Solution**:
- Enable gzip/brotli compression in FastAPI
- Compress API responses

**Expected Impact**: Reduce network transfer time by 60-80%.

---

## Estimated Performance Improvements

| Optimization | Current | After Fix | Improvement |
|--------------|---------|-----------|-------------|
| **Models Loading** | 1.6s | 0.3-0.5s | **3-5x faster** |
| **Super-Admin Checks** | 2-3s | 0.1s | **20-30x faster** |
| **User Group Lookups** | 12+ queries | 1 query | **12x fewer queries** |
| **Workspace Tabs** | 16s delay | 1-2s | **8-16x faster** |
| **Initial Page Load** | 2.9s | 1.5-2.0s | **1.5x faster** |

**Total Estimated Improvement**: **3-5x faster** overall page load and tab switching.

---

## Implementation Priority

1. **🔴 Fix Redis** (Critical - affects multi-replica cache)
2. **🔴 Batch Super-Admin Checks** (High impact, easy fix)
3. **🔴 Parallelize Portkey API** (High impact, medium effort)
4. **🟡 Request-Scoped User Cache** (Medium impact, easy fix)
5. **🟡 Pre-load Workspace Tabs** (Medium impact, frontend change)
6. **🟡 Cache Models Longer** (Low impact, easy fix)

---

## Notes

- **Redis Warning**: Line 41 shows Redis connection refused. This is critical for multi-replica deployments.
- **Cache Working**: Tools and prompts are loading fast (<100ms), indicating backend cache is working.
- **Frontend Caching**: Frontend cache appears to be working (no duplicate API calls for same data).
- **Database Performance**: Individual queries are fast, but volume is the issue (N+1 patterns).

---

## Next Steps

1. **Immediate**: Fix Redis configuration
2. **Short-term**: Implement batched super-admin checks
3. **Short-term**: Parallelize Portkey API calls
4. **Medium-term**: Add request-scoped caching for user groups
5. **Medium-term**: Pre-load all workspace tabs in parallel

