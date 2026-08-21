import { WEBUI_API_BASE_URL } from '$lib/constants';

export type KnowledgeIndexingDisplayState =
	| 'ready'
	| 'queued'
	| 'indexing'
	| 'partial'
	| 'failed'
	| 'unavailable';

export type KnowledgeIndexingJobStatus =
	| 'queued'
	| 'processing'
	| 'completed'
	| 'failed'
	| 'partially_failed';

export type KnowledgeIndexingProgress = {
	total: number;
	processed: number;
	failed: number;
	incompatible: number;
	pending_or_processing: number;
};

export type EmbeddingModelSummary = {
	id: string;
	provider: string;
	display_name: string;
	modalities: string[];
	status: string;
};

export type KnowledgeIndexingIncompatible = {
	file_id: string;
	filename: string | null;
	source_contexts: string[];
	knowledge_bases: KnowledgeIndexingKnowledgeReference[];
	error_code: string | null;
	error_message: string | null;
	attempt_count: number;
	created_at: number | null;
	updated_at: number | null;
	started_at: number | null;
	completed_at: number | null;
};

export type KnowledgeIndexingFailure = {
	file_id: string;
	filename: string | null;
	source_contexts: string[];
	knowledge_bases: KnowledgeIndexingKnowledgeReference[];
	error_code: string | null;
	error_message: string | null;
	attempt_count: number;
	created_at: number | null;
	updated_at: number | null;
	started_at: number | null;
	completed_at: number | null;
};

export type KnowledgeIndexingKnowledgeReference = {
	id: string;
	name: string;
};

export type KnowledgeIndexingStatus = {
	knowledge_id: string;
	display_state: KnowledgeIndexingDisplayState;
	job_status: KnowledgeIndexingJobStatus | null;
	retrieval_available: boolean;
	current_file_count: number;
	job_display_state: KnowledgeIndexingDisplayState;
	retry_kind: 'indexing_operation' | 'failed_documents' | null;
	job_id: string | null;
	job_type: string | null;
	active_model: EmbeddingModelSummary | null;
	target_model: EmbeddingModelSummary | null;
	collection_progress: KnowledgeIndexingProgress;
	job_progress: KnowledgeIndexingProgress;
	failed_document_count: number;
	job_failed_document_count: number;
	job_failed_documents: KnowledgeIndexingFailure[];
	incompatible_document_count: number;
	job_incompatible_document_count: number;
	job_incompatible_documents: KnowledgeIndexingIncompatible[];
	error_code: string | null;
	error_message: string | null;
	retry_eligible: boolean;
	can_retry: boolean;
	created_at: number | null;
	updated_at: number | null;
	started_at: number | null;
	completed_at: number | null;
	last_successful_indexed_at: number | null;
	failed_documents?: KnowledgeIndexingFailure[];
	incompatible_documents?: KnowledgeIndexingIncompatible[];
};

export class KnowledgeIndexingApiError extends Error {
	status: number;
	detail: unknown;
	errorCode: string | null;

	constructor(status: number, payload: any) {
		const detail = payload?.detail ?? payload;
		const message =
			typeof detail === 'string'
				? detail
				: typeof detail?.message === 'string'
					? detail.message
					: `Knowledge indexing request failed (${status}).`;
		super(message);
		this.name = 'KnowledgeIndexingApiError';
		this.status = status;
		this.detail = detail;
		this.errorCode =
			typeof detail === 'object' && typeof detail?.error_code === 'string'
				? detail.error_code
				: null;
	}
}

const getKnowledgeIndexingResponse = async <T>(url: string, token: string): Promise<T> => {
	const response = await fetch(url, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!response.ok) {
		const payload = await response.json().catch(() => null);
		throw new KnowledgeIndexingApiError(response.status, payload);
	}

	return response.json();
};

export const getKnowledgeIndexingStatuses = async (
	token: string
): Promise<KnowledgeIndexingStatus[]> =>
	getKnowledgeIndexingResponse(`${WEBUI_API_BASE_URL}/knowledge/indexing/status`, token);

export const getKnowledgeIndexingStatus = async (
	token: string,
	id: string
): Promise<KnowledgeIndexingStatus> =>
	getKnowledgeIndexingResponse(
		`${WEBUI_API_BASE_URL}/knowledge/${encodeURIComponent(id)}/indexing/status`,
		token
	);

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

export const getKnowledgeBases = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/knowledge/`, {
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
		const detail = err.detail;
		// Preserve structured {code, message} errors; normalize for display
		if (detail && typeof detail === 'object' && detail.message) {
			error = detail;
		} else {
			error = detail;
		}
		console.log(err);
		return null;
	});

	if (error) {
		throw error;
	}

	return res;
};

export const updateFileFromKnowledgeById
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
