import { RETRIEVAL_API_BASE_URL } from '$lib/constants';

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

const saveRetrievalSettings = async (token: string, path: string, payload: unknown) => {
	const response = await fetch(`${RETRIEVAL_API_BASE_URL}/${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify(payload)
	});
	if (!response.ok) {
		const body = await response.json().catch(() => null);
		const detail = body?.detail ?? body;
		const message = Array.isArray(detail)
			? detail.map((item) => item.msg).filter(Boolean).join(' ')
			: typeof detail === 'string' ? detail : detail?.message;
		throw {
			...(detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : {}),
			message: message ?? 'The settings request failed.',
			settings_saved: detail?.settings_saved ?? (response.status < 500 ? false : undefined)
		};
	}
	return response.json();
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
