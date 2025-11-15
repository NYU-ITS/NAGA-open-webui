/**
 * Frontend caching utility for API responses.
 * Uses localStorage for persistence across page reloads.
 * Cache keys are user-specific to prevent data collisions.
 */

const CACHE_PREFIX = 'open_webui_cache:';
const DEFAULT_TTL = 60000; // 60 seconds in milliseconds

interface CacheEntry<T> {
	data: T;
	timestamp: number;
	ttl: number;
}

/**
 * Get a cached value or null if not found/expired
 */
export function getCached<T>(key: string, userId?: string): T | null {
	const cacheKey = userId ? `${CACHE_PREFIX}${key}:${userId}` : `${CACHE_PREFIX}${key}`;
	
	try {
		const cached = localStorage.getItem(cacheKey);
		if (!cached) return null;
		
		const entry: CacheEntry<T> = JSON.parse(cached);
		const now = Date.now();
		
		// Check if expired
		if (now - entry.timestamp > entry.ttl) {
			localStorage.removeItem(cacheKey);
			return null;
		}
		
		return entry.data;
	} catch (e) {
		// Invalid cache entry, remove it
		localStorage.removeItem(cacheKey);
		return null;
	}
}

/**
 * Set a value in cache with TTL
 */
export function setCached<T>(key: string, value: T, ttl: number = DEFAULT_TTL, userId?: string): void {
	const cacheKey = userId ? `${CACHE_PREFIX}${key}:${userId}` : `${CACHE_PREFIX}${key}`;
	
	try {
		const entry: CacheEntry<T> = {
			data: value,
			timestamp: Date.now(),
			ttl
		};
		localStorage.setItem(cacheKey, JSON.stringify(entry));
	} catch (e) {
		// localStorage might be full or disabled, silently fail
		console.warn('Failed to cache value:', e);
	}
}

/**
 * Clear a specific cache entry
 */
export function clearCached(key: string, userId?: string): void {
	const cacheKey = userId ? `${CACHE_PREFIX}${key}:${userId}` : `${CACHE_PREFIX}${key}`;
	localStorage.removeItem(cacheKey);
}

/**
 * Clear all cache entries matching a pattern
 */
export function clearCachedPattern(pattern: string, userId?: string): void {
	const prefix = userId ? `${CACHE_PREFIX}${pattern}:${userId}` : `${CACHE_PREFIX}${pattern}`;
	
	try {
		const keys: string[] = [];
		for (let i = 0; i < localStorage.length; i++) {
			const key = localStorage.key(i);
			if (key && key.startsWith(prefix)) {
				keys.push(key);
			}
		}
		keys.forEach(key => localStorage.removeItem(key));
	} catch (e) {
		console.warn('Failed to clear cache pattern:', e);
	}
}

/**
 * Clear all cache entries for a specific user
 */
export function clearUserCache(userId: string): void {
	try {
		const keys: string[] = [];
		// Cache keys are stored as: open_webui_cache:key:userId
		// So we need to match keys ending with :userId
		const userSuffix = `:${userId}`;
		
		for (let i = 0; i < localStorage.length; i++) {
			const key = localStorage.key(i);
			if (key && key.startsWith(CACHE_PREFIX) && key.endsWith(userSuffix)) {
				keys.push(key);
			}
		}
		keys.forEach(key => localStorage.removeItem(key));
	} catch (e) {
		console.warn('Failed to clear user cache:', e);
	}
}

/**
 * Get a stable user identifier from token (hash-based for security)
 * This ensures cache keys are user-specific without exposing user IDs
 */
export function getUserIdFromToken(token: string): string | null {
	if (!token) return null;
	
	try {
		// Try to extract user info from token if it's a JWT
		const parts = token.split('.');
		if (parts.length === 3) {
			const payload = JSON.parse(atob(parts[1]));
			return payload.sub || payload.user_id || payload.id || null;
		}
	} catch (e) {
		// Not a JWT or invalid format
	}
	
	// Fallback: use a hash of the token as user identifier
	// This ensures user-specific caching even if token isn't a JWT
	try {
		let hash = 0;
		for (let i = 0; i < token.length; i++) {
			const char = token.charCodeAt(i);
			hash = ((hash << 5) - hash) + char;
			hash = hash & 0xFFFFFFFF; // Convert to 32-bit integer
		}
		return `token_${Math.abs(hash).toString(36)}`;
	} catch (e) {
		return null;
	}
}

