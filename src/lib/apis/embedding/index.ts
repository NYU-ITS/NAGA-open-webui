import { WEBUI_API_BASE_URL } from '$lib/constants';

export type RetryEmbeddingJobResponse = {
	job_id: string;
	source_job_id: string;
	job_type: string;
	status: string;
	total_files: number;
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
