import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getGravatarUrl = async (token: string, email: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/gravatar?email=${email}`, {
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
			error = err;
			return null;
		});

	return res;
};

export const executeCode = async (token: string, code: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/code/execute`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			code: code
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);

			error = err;
			if (err.detail) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const formatPythonCode = async (token: string, code: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/code/format`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			code: code
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);

			error = err;
			if (err.detail) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

const PDF_EXPORT_POLL_INTERVAL_MS = 2000;
const PDF_EXPORT_MAX_WAIT_MS = 900000; // 15 minutes

const toExportError = (err: any, fallback: string): string => {
	if (err?.name === 'AbortError') {
		return 'PDF export timed out. Please try again with a shorter conversation.';
	}
	if (typeof err === 'string') {
		return err;
	}
	return err?.detail ?? err?.message ?? fallback;
};

const downloadChatAsPDFSync = async (token: string, title: string, messages: object[]) => {
	// Create an AbortController for timeout handling
	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 minutes timeout

	try {
		const blob = await fetch(`${WEBUI_API_BASE_URL}/utils/pdf`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Authorization: `Bearer ${token}`
			},
			body: JSON.stringify({
				title: title,
				messages: messages
			}),
			signal: controller.signal
		})
			.then(async (res) => {
				if (!res.ok) {
					const errorData = await res.json();
					throw errorData;
				}
				return res.blob();
			});

		clearTimeout(timeoutId);
		return blob;
	} catch (err: any) {
		clearTimeout(timeoutId);
		console.log(err);
		throw toExportError(err, 'Failed to export PDF. Please try again.');
	}
};

/**
 * Export a chat as PDF.
 *
 * Submits the conversation as a background job and polls for the result, so a
 * long export is never bounded by a single request timeout. Deployments that
 * do not expose the job endpoint fall back to the synchronous route.
 */
export const downloadChatAsPDF = async (token: string, title: string, messages: object[]) => {
	const headers = {
		'Content-Type': 'application/json',
		Authorization: `Bearer ${token}`
	};

	let jobId: string;
	try {
		const res = await fetch(`${WEBUI_API_BASE_URL}/utils/pdf/jobs`, {
			method: 'POST',
			headers,
			body: JSON.stringify({ title: title, messages: messages })
		});
		if (!res.ok) {
			throw await res.json();
		}
		jobId = (await res.json()).id;
	} catch (err: any) {
		console.log('PDF export job endpoint unavailable, falling back to direct export', err);
		return downloadChatAsPDFSync(token, title, messages);
	}

	const deadline = Date.now() + PDF_EXPORT_MAX_WAIT_MS;

	while (Date.now() < deadline) {
		await new Promise((resolve) => setTimeout(resolve, PDF_EXPORT_POLL_INTERVAL_MS));

		let job: { status: string; error?: string };
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/utils/pdf/jobs/${jobId}`, { headers });
			if (!res.ok) {
				throw await res.json();
			}
			job = await res.json();
		} catch (err: any) {
			throw toExportError(err, 'Failed to export PDF. Please try again.');
		}

		if (job.status === 'error') {
			throw toExportError(job.error, 'Failed to export PDF. Please try again.');
		}

		if (job.status === 'completed') {
			try {
				const res = await fetch(`${WEBUI_API_BASE_URL}/utils/pdf/jobs/${jobId}/download`, {
					headers
				});
				if (!res.ok) {
					throw await res.json();
				}
				return await res.blob();
			} catch (err: any) {
				throw toExportError(err, 'Failed to download the exported PDF.');
			}
		}
	}

	throw 'PDF export timed out. Please try again with a shorter conversation.';
};

export const getHTMLFromMarkdown = async (token: string, md: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/markdown`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			md: md
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err;
			return null;
		});

	return res.html;
};

export const downloadDatabase = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/db/download`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (response) => {
			if (!response.ok) {
				throw await response.json();
			}
			return response.blob();
		})
		.then((blob) => {
			const url = window.URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'webui.db';
			document.body.appendChild(a);
			a.click();
			window.URL.revokeObjectURL(url);
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}
};

export const downloadLiteLLMConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/litellm/config`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (response) => {
			if (!response.ok) {
				throw await response.json();
			}
			return response.blob();
		})
		.then((blob) => {
			const url = window.URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'config.yaml';
			document.body.appendChild(a);
			a.click();
			window.URL.revokeObjectURL(url);
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}
};
