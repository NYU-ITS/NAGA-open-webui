import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

export const BASE_URL =
	process.env.PLAYWRIGHT_GROUPS_BASE_URL?.trim() ||
	process.env.PLAYWRIGHT_BASE_URL?.trim() ||
	'http://localhost:8080';

export interface Credentials {
	email: string;
	password: string;
}

export interface Session {
	token: string;
	id: string;
	email: string;
	role: string;
}

export function adminCredentials(): Credentials {
	const email = process.env.PLAYWRIGHT_ADMIN_EMAIL;
	const password = process.env.PLAYWRIGHT_ADMIN_PASSWORD;
	if (!email || !password) {
		throw new Error(
			'PLAYWRIGHT_ADMIN_EMAIL and PLAYWRIGHT_ADMIN_PASSWORD must be set. See README.md.'
		);
	}
	return { email, password };
}

export function studentCredentials(): Credentials | null {
	const email = process.env.PLAYWRIGHT_STUDENT_EMAIL;
	const password = process.env.PLAYWRIGHT_STUDENT_PASSWORD;
	if (!email || !password) {
		return null;
	}
	return { email, password };
}

export async function signIn(
	request: APIRequestContext,
	{ email, password }: Credentials
): Promise<Session> {
	const res = await request.post('/api/v1/auths/signin', { data: { email, password } });
	expect(
		res.ok(),
		`signin failed for ${email}: HTTP ${res.status()} ${await res.text()}`
	).toBeTruthy();

	const body = await res.json();
	expect(body.token, 'signin response is missing a token').toBeTruthy();
	return { token: body.token, id: body.id, email: body.email, role: body.role };
}

export function authHeaders(token: string): Record<string, string> {
	return { authorization: `Bearer ${token}`, Accept: 'application/json' };
}
