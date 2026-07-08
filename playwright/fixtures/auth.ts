import { APIRequestContext, APIResponse, Page, expect } from '@playwright/test';

const missing = [
	['PLAYWRIGHT_ADMIN_EMAIL', process.env.PLAYWRIGHT_ADMIN_EMAIL],
	['PLAYWRIGHT_ADMIN_PASSWORD', process.env.PLAYWRIGHT_ADMIN_PASSWORD],
	['PLAYWRIGHT_STUDENT_EMAIL', process.env.PLAYWRIGHT_STUDENT_EMAIL],
	['PLAYWRIGHT_STUDENT_PASSWORD', process.env.PLAYWRIGHT_STUDENT_PASSWORD]
].filter(([, val]) => !val).map(([name]) => name);

if (process.env.PLAYWRIGHT_RUN_LIVE === '1' && missing.length > 0) {
	throw new Error(
		`Live mode requires credential env vars (no fallbacks allowed). Missing: ${missing.join(', ')}`
	);
}

export const ADMIN_EMAIL = process.env.PLAYWRIGHT_ADMIN_EMAIL!;
export const ADMIN_PASSWORD = process.env.PLAYWRIGHT_ADMIN_PASSWORD!;
export const USER_EMAIL = process.env.PLAYWRIGHT_STUDENT_EMAIL!;
export const USER_PASSWORD = process.env.PLAYWRIGHT_STUDENT_PASSWORD!;

export async function signInViaApi(request: APIRequestContext, email: string, password: string) {
	const response = await retryApiRequest(
		() => request.post('/api/v1/auths/signin', { data: { email, password } }),
		`signin ${email}`
	);

	if (!response.ok()) {
		throw new Error(`Login failed (${response.status()}): ${await response.text()}`);
	}

	const data = (await response.json()) as any;
	const token =
		data?.token ??
		data?.access_token ??
		data?.data?.token ??
		data?.data?.access_token ??
		'';

	if (!token) {
		throw new Error(`Login response missing token: ${JSON.stringify(data)}`);
	}

	return token;
}

export async function loginViaApi(page: Page, email: string, password: string) {
	let token: string;
	try {
		token = await signInViaApi(page.request, email, password);
	} catch (error) {
		throw new Error(
			`${error instanceof Error ? error.message : String(error)}\n` +
				`Verify these credentials can sign in manually at ${page.url().split('/').slice(0, 3).join('/')}/auth`
		);
	}

	await page.addInitScript((t) => {
		localStorage.setItem('token', t);
		localStorage.setItem('locale', 'en-US');
	}, token);

	await page.goto('/');
	await expect(page).not.toHaveURL(/\/auth$/);
}

export async function dismissModals(page: Page) {
	const modal = page.locator('.modal.fixed');
	for (let i = 0; i < 5; i++) {
		if (!(await modal.isVisible({ timeout: 1000 }).catch(() => false))) break;
		const closeBtn = modal.locator(
			'button:has-text("Close"), button:has-text("Dismiss"), button:has-text("Got it"), button:has-text("OK"), button[aria-label="Close"]'
		);
		if (await closeBtn.first().isVisible({ timeout: 500 }).catch(() => false)) {
			await closeBtn.first().evaluate((btn) => (btn as HTMLButtonElement).click());
		} else {
			await page.evaluate(() => {
				document.querySelectorAll('.modal.fixed').forEach((m) => m.remove());
			});
		}
		await page.waitForTimeout(500);
	}
}

export async function getAuthToken(page: Page) {
	const token = await page.evaluate(() => localStorage.getItem('token'));
	if (!token) throw new Error('Missing localStorage token after login');
	return token;
}

export async function authHeaders(token: string) {
	return {
		authorization: `Bearer ${token}`,
		accept: 'application/json',
		'content-type': 'application/json'
	};
}

const TRANSIENT_STATUS = new Set([408, 429, 500, 502, 503, 504]);
const TRANSIENT_ERROR_RE = /(ECONNRESET|ECONNREFUSED|ETIMEDOUT|EPIPE|socket hang up|network|timeout|Target page, context or browser has been closed)/i;

function sleep(ms: number) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function retryApiRequest(
	operation: () => Promise<APIResponse>,
	label: string,
	options: { attempts?: number; baseDelayMs?: number } = {}
) {
	const attempts = options.attempts ?? 4;
	const baseDelayMs = options.baseDelayMs ?? 500;
	let lastError: unknown;
	let lastResponse: APIResponse | undefined;

	for (let attempt = 1; attempt <= attempts; attempt++) {
		try {
			const response = await operation();
			if (!TRANSIENT_STATUS.has(response.status()) || attempt === attempts) return response;
			lastResponse = response;
		} catch (error) {
			lastError = error;
			if (attempt === attempts || !TRANSIENT_ERROR_RE.test(String(error))) throw error;
		}

		await sleep(baseDelayMs * 2 ** (attempt - 1));
	}

	if (lastResponse) return lastResponse;
	throw lastError ?? new Error(`${label} failed before response`);
}

export async function requireOk(response: APIResponse, label: string) {
	if (!response.ok()) {
		throw new Error(`${label} failed: ${response.status()} ${await response.text()}`);
	}
	return response;
}
