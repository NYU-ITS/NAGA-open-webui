import { WEBUI_API_BASE_URL } from '$lib/constants';
import { getCached, setCached, clearCachedPattern, getUserIdFromToken } from '$lib/utils/cache';

type PromptItem = {
	command: string;
	title: string;
	content: string;
	access_control?: null | object;
};

export const createNewPrompt = async (token: string, prompt: PromptItem) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/prompts/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...prompt,
			command: `/${prompt.command}`
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on create
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('prompts:', userId);
			}
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getPrompts = async (token: string = '', skip?: number, limit?: number) => {
	const userId = getUserIdFromToken(token);
	// Cache key without pagination - we cache the full list
	const fullListCacheKey = 'prompts:list';
	
	// Check if we have the full list cached
	let fullList = userId ? getCached(fullListCacheKey, userId) : null;
	
	// If we have cached data, paginate client-side
	if (fullList && Array.isArray(fullList)) {
		const start = skip || 0;
		const end = limit ? start + limit : undefined;
		return fullList.slice(start, end);
	}

	let error = null;
	
	// Request full list (use large limit to get all items, backend caches full list anyway)
	// Build query params using URLSearchParams (consistent with codebase pattern)
	const searchParams = new URLSearchParams();
	searchParams.append('skip', '0');
	searchParams.append('limit', '1000'); // Large enough to get all items

	const res = await fetch(`${WEBUI_API_BASE_URL}/prompts/?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Ensure we have an array
			if (!Array.isArray(json)) {
				console.warn('getPrompts: API returned non-array response:', json);
				return [];
			}
			
			// Cache the full list
			if (userId && json) {
				setCached(fullListCacheKey, json, 60000, userId); // 60 second cache
			}
			
			// Apply pagination to the response
			const start = skip || 0;
			const end = limit ? start + limit : undefined;
			return json.slice(start, end);
		})
		.catch((err) => {
			error = err?.detail || err?.message || err;
			console.error('getPrompts error:', err);
			return [];
		});

	if (error) {
		console.error('getPrompts failed:', error);
		return [];
	}

	return res || [];
};

export const getPromptList = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/prompts/list`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getPromptByCommand = async (token: string, command: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/prompts/command/${command}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updatePromptByCommand = async (token: string, prompt: PromptItem) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/prompts/command/${prompt.command}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...prompt,
			command: `/${prompt.command}`
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on update
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('prompts:', userId);
			}
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deletePromptByCommand = async (token: string, command: string) => {
	let error = null;

	command = command.charAt(0) === '/' ? command.slice(1) : command;

	const res = await fetch(`${WEBUI_API_BASE_URL}/prompts/command/${command}/delete`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on delete
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('prompts:', userId);
			}
			return json;
		})
		.catch((err) => {
			error = err.detail;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
