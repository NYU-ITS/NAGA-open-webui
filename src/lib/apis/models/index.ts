import { WEBUI_API_BASE_URL } from '$lib/constants';
import { getCached, setCached, clearCachedPattern, getUserIdFromToken } from '$lib/utils/cache';

export const getModels = async (token: string = '', skip?: number, limit?: number) => {
	const userId = getUserIdFromToken(token);
	// Cache key without pagination - we cache the full list
	const fullListCacheKey = 'models:list';
	
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

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/?${searchParams.toString()}`, {
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
				console.warn('getModels: API returned non-array response:', json);
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
			console.error('getModels error:', err);
			return [];
		});

	if (error) {
		console.error('getModels failed:', error);
		return [];
	}

	return res || [];
};

export const getBaseModels = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/base`, {
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
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createNewModel = async (token: string, model: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(model)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on create
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('models:', userId);
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

export const getModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model?${searchParams.toString()}`, {
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
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const toggleModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/toggle?${searchParams.toString()}`, {
		method: 'POST',
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
			// Clear cache on toggle
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('models:', userId);
			}
			return json;
		})
		.catch((err) => {
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateModelById = async (token: string, id: string, model: object) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/update?${searchParams.toString()}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(model)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on update
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('models:', userId);
			}
			return json;
		})
		.catch((err) => {
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteModelById = async (token: string, id: string) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('id', id);

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/model/delete?${searchParams.toString()}`, {
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
				clearCachedPattern('models:', userId);
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

export const deleteAllModels = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/models/delete/all`, {
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
			return json;
		})
		.catch((err) => {
			error = err;

			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
