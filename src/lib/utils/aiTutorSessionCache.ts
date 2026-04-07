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

const inflightSessionCacheLoads = new Map<string, Promise<unknown>>();

async function loadFreshAndPersist<T>(key: string, loader: () => Promise<T>) {
	const existing = inflightSessionCacheLoads.get(key) as Promise<T> | undefined;
	if (existing) return existing;

	const nextLoad = loader()
		.then((fresh) => {
			writeAITutorSessionCache(key, fresh);
			return fresh;
		})
		.finally(() => {
			inflightSessionCacheLoads.delete(key);
		});

	inflightSessionCacheLoads.set(key, nextLoad as Promise<unknown>);
	return nextLoad;
}

export async function loadWithAITutorSessionCache<T>(options: {
	key: string;
	ttlMs: number;
	loader: () => Promise<T>;
	onCached?: (value: T) => void;
	onRefreshError?: (error: unknown) => void;
	revalidateInBackground?: boolean;
}): Promise<T> {
	const cached = readAITutorSessionCache<T>(options.key, options.ttlMs);
	if (cached !== null) {
		options.onCached?.(cached);
		if (options.revalidateInBackground !== false) {
			void loadFreshAndPersist(options.key, options.loader)
				.then((fresh) => {
					options.onCached?.(fresh);
				})
				.catch((error) => {
					options.onRefreshError?.(error);
				});
		}
		return cached;
	}

	const fresh = await loadFreshAndPersist(options.key, options.loader);
	options.onCached?.(fresh);
	return fresh;
}
