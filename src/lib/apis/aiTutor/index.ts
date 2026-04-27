import { AI_TUTOR_API_BASE_URL } from '$lib/constants';

type QueryValue = string | number | boolean | null | undefined;

type FetchAITutorOptions = {
	token?: string;
	method?: string;
	headers?: Record<string, string>;
	body?: BodyInit | null;
	query?: Record<string, QueryValue>;
};

type PollAITutorJobOptions = {
	intervalMs?: number;
	onStatus?: (data: any) => void | Promise<void>;
};

export const buildAITutorUrl = (
	path: string,
	query: Record<string, QueryValue> = {}
) => {
	const normalizedPath = path.startsWith('/') ? path : `/${path}`;
	const url = new URL(`${AI_TUTOR_API_BASE_URL}${normalizedPath}`, window.location.origin);

	for (const [key, value] of Object.entries(query)) {
		if (value === null || value === undefined || value === '') continue;
		url.searchParams.set(key, String(value));
	}

	return url.toString();
};

export const parseAITutorError = async (response: Response) => {
	try {
		const data = await response.json();
		if (typeof data?.detail === 'string') return data.detail;
		if (typeof data?.message === 'string') return data.message;
		if (Array.isArray(data?.detail)) {
			return data.detail
				.map((item: any) => item?.msg ?? JSON.stringify(item))
				.filter(Boolean)
				.join(', ');
		}
	} catch {
		// Ignore JSON parsing failures and fall back to the HTTP status.
	}

	return `Request failed: ${response.status}`;
};

export const fetchAITutor = async (
	path: string,
	{ token, method = 'GET', headers = {}, body = null, query = {} }: FetchAITutorOptions = {}
) => {
	const response = await fetch(buildAITutorUrl(path, query), {
		method,
		headers: {
			...(token ? { Authorization: `Bearer ${token}` } : {}),
			...headers
		},
		body
	});

	if (!response.ok) {
		const error = new Error(await parseAITutorError(response)) as any;
		error.status = response.status;
		throw error;
	}

	return response;
};

export const fetchAITutorJson = async <T>(
	path: string,
	options: FetchAITutorOptions = {}
): Promise<T> => {
	const response = await fetchAITutor(path, options);
	return response.json() as Promise<T>;
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const pollAITutorJob = async (
	jobId: string,
	token?: string,
	{ intervalMs = 3000, onStatus }: PollAITutorJobOptions = {}
) => {
	while (true) {
		const data = await fetchAITutorJson<any>(`/pipeline/status/${encodeURIComponent(jobId)}`, {
			token
		});

		if (onStatus) {
			await onStatus(data);
		}

		if (data?.status === 'done') return data;
		if (data?.status === 'failed') {
			throw new Error(data?.error || 'Pipeline job failed.');
		}

		await sleep(intervalMs);
	}
};
