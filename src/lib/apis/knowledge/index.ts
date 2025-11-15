import { WEBUI_API_BASE_URL } from '$lib/constants';
import { getCached, setCached, clearCachedPattern, getUserIdFromToken } from '$lib/utils/cache';

export const createNewKnowledge = async (
	token: string,
	name: string,
	description: string,
	accessControl: null | object,
	assignToEmail?: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: name,
			description: description,
			access_control: accessControl,
			assign_to_email: assignToEmail
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
				clearCachedPattern('knowledge:', userId);
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

export const getKnowledgeBases = async (token: string = '', skip?: number, limit?: number) => {
	const userId = getUserIdFromToken(token);
	// Cache key without pagination - we cache the full list
	const fullListCacheKey = 'knowledge:list';
	
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

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/?${searchParams.toString()}`, {
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
				console.warn('getKnowledgeBases: API returned non-array response:', json);
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
			console.error('getKnowledgeBases error:', err);
			return [];
		});

	if (error) {
		console.error('getKnowledgeBases failed:', error);
		return [];
	}

	return res || [];
};

export const getKnowledgeBaseList = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/list`, {
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

export const getKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}`, {
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
			// This is a read operation, no need to clear cache
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

type KnowledgeUpdateForm = {
	name?: string;
	description?: string;
	data?: object;
	access_control?: null | object;
};

export const updateKnowledgeById = async (token: string, id: string, form: KnowledgeUpdateForm) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			name: form?.name ? form.name : undefined,
			description: form?.description ? form.description : undefined,
			data: form?.data ? form.data : undefined,
			access_control: form.access_control,
			assign_to_email: form.assign_to_email
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on delete
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('knowledge:', userId);
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

// Update frontend API call to match new backend function signature
export const addFileToKnowledgeById = async (token: string, knowledgeId: string, file: File) => {
	const data = new FormData();
	data.append('file', file);

	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${knowledgeId}/file/add`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		},
		body: data
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
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

export const updateFileFromKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on delete
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('knowledge:', userId);
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

export const removeFileFromKnowledgeById = async (token: string, id: string, fileId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/file/remove`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: fileId
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			// Clear cache on delete
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('knowledge:', userId);
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

export const resetKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/reset`, {
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
			// Clear cache on delete
			const userId = getUserIdFromToken(token);
			if (userId) {
				clearCachedPattern('knowledge:', userId);
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

export const deleteKnowledgeById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/${id}/delete`, {
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
				clearCachedPattern('knowledge:', userId);
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
