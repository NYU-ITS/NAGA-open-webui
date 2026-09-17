import { RETRIEVAL_API_BASE_URL } from '$lib/constants';
import { v4 as uuidv4 } from 'uuid';

export const getRAGConfig = async (token: string,email: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/config?email=${email}`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type ChunkConfigForm = {
	chunk_size: number;
	chunk_overlap: number;
};

type DocumentIntelligenceConfigForm = {
	key: string;
	endpoint: string;
};

type ContentExtractConfigForm = {
	engine: string;
	tika_server_url: string | null;
	document_intelligence_config: DocumentIntelligenceConfigForm | null;
};

type YoutubeConfigForm = {
	language: string[];
	translation?: string | null;
	proxy_url: string;
};

type VideoConfigForm = {
	max_file_size_mb?: number;
	chunk_duration_seconds?: number;
	min_chunk_duration_seconds?: number;
	max_duration_seconds?: number;
};

type RAGConfigForm = {
	email: string;
	audio_max_clips?: number;
	defer_embedding_reindex?: boolean;
	embedding?: EmbeddingModelUpdateForm;
	force_reindex?: boolean;
	RAG_FULL_CONTEXT?: boolean;
	BYPASS_EMBEDDING_AND_RETRIEVAL?: boolean;
	pdf_extract_images?: boolean;
	enable_google_drive_integration?: boolean;
	enable_onedrive_integration?: boolean;
	chunk?: ChunkConfigForm;
	video?: VideoConfigForm;
	content_extraction?: ContentExtractConfigForm;
	web_loader_ssl_verification?: boolean;
	youtube?: YoutubeConfigForm;
};

const saveRetrievalSettings = async (token: string, path: string, payload: object) => {
	const saveId = uuidv4();
	let failure;
	try {
		const response = await fetch(`${RETRIEVAL_API_BASE_URL}/${path}`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
			body: JSON.stringify({ ...payload, save_id: saveId })
		});
		const body = await response.json().catch(() => null);
		if (response.ok && body?.status === true) return body;
		const detail = body?.detail ?? body;
		const message = Array.isArray(detail)
			? detail.map((item) => item.msg).filter(Boolean).join(' ')
			: typeof detail === 'string' ? detail : detail?.message;
		const fallback = response.ok
			? 'The server returned an invalid save response. Your edits are preserved.'
			: `The server returned an error while saving settings (HTTP ${response.status}). Your edits are preserved.`;
		failure = {
			...(detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : {}),
			message: message || fallback,
			settings_saved: detail?.settings_saved ??
				(response.status >= 400 && response.status < 500 && response.status !== 408 ? false : undefined)
		};
	} catch {
		failure = {
			message: 'The connection was interrupted while saving. Your edits are preserved. Check your connection and try again.'
		};
	}
	if (failure.settings_saved === false) throw failure;

	// A lost response does not imply rollback. Confirm the exact save from its
	// transactionally stored receipt; never resend the mutation automatically.
	for (const delay of [0, 500, 1500]) {
		if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
		try {
			const response = await fetch(`${RETRIEVAL_API_BASE_URL}/config/saves/${saveId}`, {
				headers: { Authorization: `Bearer ${token}` },
				cache: 'no-store',
				signal: AbortSignal.timeout(5000)
			});
			if (!response.ok) continue;
			const result = await response.json();
			if (result.settings_saved === true) return result;
		} catch {
			// Keep the original error if the server remains unreachable.
		}
	}
	throw failure;
};

export const updateRAGConfig = async (token: string, payload: RAGConfigForm) =>
	saveRetrievalSettings(token, 'config/update', payload);

export type SettingsIndexingStatus = {
	status: 'not_required' | 'pending' | 'failed' | 'ready' | 'unknown';
	in_progress?: boolean;
	dispatch_failed?: boolean;
	jobs: {
		job_id: string;
		status: string;
		total_files: number;
		processed_files: number;
		failed_files: number;
		incompatible_files: number;
		own_index: boolean;
		can_retry: boolean;
	}[];
};

export const getSettingsIndexingStatus = async (token: string): Promise<SettingsIndexingStatus> => {
	const response = await fetch(`${RETRIEVAL_API_BASE_URL}/config/indexing`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!response.ok) throw new Error('Could not load indexing status.');
	return response.json();
};

export const getRAGTemplate = async (token: string, email: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/template?email=${email}`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res?.template ?? '';
};

export const getQuerySettings = async (token: string, email: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/query/settings?email=${email}`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type QuerySettings = {
	email: string;
	k: number | null;
	r: number | null;
	template: string | null;
};

export const updateQuerySettings = async (token: string, settings: QuerySettings) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/query/settings/update`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...settings
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getEmbeddingConfig = async (token: string, email: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/embedding?email=${email}`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type OpenAIConfigForm = {
	key: string;
	url: string;
};

type EmbeddingModelUpdateForm = {
	email: string;
	openai_config?: OpenAIConfigForm;
	embedding_engine: string;
	embedding_model: string;
	embedding_batch_size?: number;
	reliability?: {
		max_attempts: number;
		connection_timeout_seconds: number;
		read_timeout_seconds: number;
	};
	force_reindex?: boolean;
};

export const updateEmbeddingConfig = async (token: string, payload: EmbeddingModelUpdateForm) =>
	saveRetrievalSettings(token, 'embedding/update', payload);

export const getRerankingConfig = async (token: string, email: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/reranking?email=${email}`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type RerankingModelUpdateForm = {
	email: string;
	reranking_model: string;
};

export const updateRerankingConfig = async (token: string, payload: RerankingModelUpdateForm) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/reranking/update`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...payload
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export interface SearchDocument {
	status: boolean;
	collection_name: string;
	filenames: string[];
}

export const processFile = async (
	token: string,
	file_id: string,
	collection_name: string | null = null
) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/process/file`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			file_id: file_id,
			collection_name: collection_name ? collection_name : undefined
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

export const processYoutubeVideo = async (token: string, url: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/process/youtube`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			url: url
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

export const processWeb = async (token: string, collection_name: string, url: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/process/web`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			url: url,
			collection_name: collection_name
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

export const processWebSearch = async (
	token: string,
	query: string,
	collection_name?: string
): Promise<SearchDocument | null> => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/process/web/search`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			query,
			collection_name: collection_name ?? ''
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const queryDoc = async (
	token: string,
	collection_name: string,
	query: string,
	k: number | null = null
) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/query/doc`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			collection_name: collection_name,
			query: query,
			k: k
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const queryCollection = async (
	token: string,
	collection_names: string,
	query: string,
	k: number | null = null
) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/query/collection`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			collection_names: collection_names,
			query: query,
			k: k
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const resetUploadDir = async (token: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/reset/uploads`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const resetVectorDB = async (token: string) => {
	let error = null;

	const res = await fetch(`${RETRIEVAL_API_BASE_URL}/reset/db`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
