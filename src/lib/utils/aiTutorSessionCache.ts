const SESSION_CACHE_PREFIX = 'ai_tutor_session_cache';

type SessionCacheEnvelope<T> = {
	value: T;
	storedAt: number;
};

function getStorageKey(key: string) {
	return `${SESSION_CACHE_PREFIX}:${key}`;
}

export function readAITutorSessionCache<T>(key: string, ttlMs: number): T | null {
	if (typeof sessionStorage === 'undefined') return null;

	try {
		const raw = sessionStorage.getItem(getStorageKey(key));
		if (!raw) return null;

		const parsed = JSON.parse(raw) as SessionCacheEnvelope<T>;
		if (!parsed || typeof parsed.storedAt !== 'number') return null;
		if (Date.now() - parsed.storedAt > ttlMs) {
			sessionStorage.removeItem(getStorageKey(key));
			return null;
		}

		return parsed.value;
	} catch {
		return null;
	}
}

export function writeAITutorSessionCache<T>(key: string, value: T) {
	if (typeof sessionStorage === 'undefined') return;

	const payload: SessionCacheEnvelope<T> = {
		value,
		storedAt: Date.now()
	};

	sessionStorage.setItem(getStorageKey(key), JSON.stringify(payload));
}

export function clearAITutorSessionCache(key: string) {
	if (typeof sessionStorage === 'undefined') return;
	sessionStorage.removeItem(getStorageKey(key));
}

export function clearAITutorSessionCacheByPrefix(prefix: string) {
	if (typeof sessionStorage === 'undefined') return;

	const targetPrefix = getStorageKey(prefix);
	for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
		const storageKey = sessionStorage.key(i);
		if (storageKey && storageKey.startsWith(targetPrefix)) {
			sessionStorage.removeItem(storageKey);
		}
	}
}

export async function loadWithAITutorSessionCache<T>(options: {
	key: string;
	ttlMs: number;
	loader: () => Promise<T>;
	onCached?: (value: T) => void;
}): Promise<T> {
	const cached = readAITutorSessionCache<T>(options.key, options.ttlMs);
	if (cached !== null) {
		options.onCached?.(cached);
		return cached;
	}

	const fresh = await options.loader();
	writeAITutorSessionCache(options.key, fresh);
	return fresh;
}
