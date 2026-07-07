import { APIRequestContext, Page, expect } from '@playwright/test';

const missing = [
	['PLAYWRIGHT_ADMIN_EMAIL', process.env.PLAYWRIGHT_ADMIN_EMAIL],
	['PLAYWRIGHT_ADMIN_PASSWORD', process.env.PLAYWRIGHT_ADMIN_PASSWORD],
	['PLAYWRIGHT_STUDENT_EMAIL', process.env.PLAYWRIGHT_STUDENT_EMAIL],
	['PLAYWRIGHT_STUDENT_PASSWORD', process.env.PLAYWRIGHT_STUDENT_PASSWORD]
].filter(([, val]) => !val).map(([name]) => name);

if (missing.length > 0) {
	throw new Error(
		`Live mode requires credential env vars (no fallbacks allowed). Missing: ${missing.join(', ')}`
	);
}

export const ADMIN_EMAIL = process.env.PLAYWRIGHT_ADMIN_EMAIL!;
export const ADMIN_PASSWORD = process.env.PLAYWRIGHT_ADMIN_PASSWORD!;
export const USER_EMAIL = process.env.PLAYWRIGHT_STUDENT_EMAIL!;
export const USER_PASSWORD = process.env.PLAYWRIGHT_STUDENT_PASSWORD!;

export async function loginViaApi(page: Page, email: string, password: string) {
	const response = await page.request.post('/api/v1/auths/signin', {
		data: { email, password }
	});

	if (!response.ok()) {
		throw new Error(
			`Login failed (${response.status()}): ${await response.text()}\n` +
				`Verify these credentials can sign in manually at ${page.url().split('/').slice(0, 3).join('/')}/auth`
		);
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

export async function requireOk(
	response: Awaited<ReturnType<APIRequestContext['get']>>,
	label: string
) {
	if (!response.ok()) {
		throw new Error(`${label} failed: ${response.status()} ${await response.text()}`);
	}
	return response;
}
