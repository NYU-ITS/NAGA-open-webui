import { WEBUI_API_BASE_URL } from '$lib/constants';

export type RetryEmbeddingJobResponse = {
	job_id: string;
	source_job_id: string;
	job_type: string;
	status: string;
	total_files: number;
	index_generation_id?: string | null;
	dispatch_mode?: string;
	nothing_to_retry?: boolean;
	message?: string;
};

export type EmbeddingJobStatus = {
	job_id: string;
	status: string;
	embedding_model_id: string;
	selected_model_id: string | null;
	active_model_id: string | null;
	effective_model_id: string | null;
	index_generation_id: string | null;
	availability: 'ready' | 'partial' | 'unavailable';
	total_files: number;
	processed_files: number;
	failed_files: number;
	retry_file_count: number;
	generation_progress: { total: number; processed: number; failed: number };
};

export class EmbeddingJobApiError extends Error {
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
					: `Embedding job request failed (${status}).`;
		super(message);
		this.name = 'EmbeddingJobApiError';
		this.status = status;
		this.detail = detail;
		this.errorCode =
			typeof detail === 'object' && typeof detail?.error_code === 'string'
				? detail.error_code
				: null;
	}
}

export const retryEmbeddingJob = async (
	token: string,
	jobId: string
): Promise<RetryEmbeddingJobResponse> => {
	const response = await fetch(
		`${WEBUI_API_BASE_URL}/embedding/jobs/${encodeURIComponent(jobId)}/retry`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	);

	if (!response.ok) {
		const payload = await response.json().catch(() => null);
		throw new EmbeddingJobApiError(response.status, payload);
	}

	return response.json();
};

export const getLatestEmbeddingJob = async (token: string): Promise<EmbeddingJobStatus | null> => {
	const response = await fetch(`${WEBUI_API_BASE_URL}/embedding/jobs/latest`, {
		headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
	});
	if (response.status === 404) return null;
	if (!response.ok) throw new EmbeddingJobApiError(response.status, await response.json().catch(() => null));
	return response.json();
};
