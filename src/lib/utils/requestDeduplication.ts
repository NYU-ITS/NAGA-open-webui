/**
 * Request Deduplication Utility
 * Prevents duplicate API calls by tracking in-flight requests
 * Returns the same promise for identical concurrent requests
 */

interface PendingRequest {
	promise: Promise<any>;
	timestamp: number;
}

const pendingRequests = new Map<string, PendingRequest>();
const REQUEST_TIMEOUT = 30000; // 30 seconds - cleanup stale requests

/**
 * Creates a deduplicated fetch request
 * If an identical request is already in-flight, returns the same promise
 */
export async function deduplicatedFetch(
	url: string,
	options: RequestInit = {}
): Promise<Response> {
	const requestKey = `${options.method || 'GET'}:${url}:${JSON.stringify(options.body || {})}`;
	
	// Check if there's already a pending request
	const pending = pendingRequests.get(requestKey);
	if (pending) {
		// Check if request is stale (older than timeout)
		const age = Date.now() - pending.timestamp;
		if (age < REQUEST_TIMEOUT) {
			// Return existing promise
			return pending.promise;
		} else {
			// Remove stale request
			pendingRequests.delete(requestKey);
		}
	}
	
	// Create new request
	const promise = fetch(url, options)
		.then(response => {
			// Remove from pending after completion
			pendingRequests.delete(requestKey);
			return response;
		})
		.catch(error => {
			// Remove from pending on error
			pendingRequests.delete(requestKey);
			throw error;
		});
	
	// Store pending request
	pendingRequests.set(requestKey, {
		promise,
		timestamp: Date.now()
	});
	
	return promise;
}

/**
 * Cleanup stale requests (call periodically)
 */
export function cleanupStaleRequests(): void {
	const now = Date.now();
	for (const [key, request] of pendingRequests.entries()) {
		if (now - request.timestamp > REQUEST_TIMEOUT) {
			pendingRequests.delete(key);
		}
	}
}

// Cleanup stale requests every 10 seconds
if (typeof window !== 'undefined') {
	setInterval(cleanupStaleRequests, 10000);
}

