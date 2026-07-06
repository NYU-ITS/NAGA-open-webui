import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { ADMIN, STUDENT } from './accounts';

export const BASE_URL =
	process.env.PLAYWRIGHT_GROUPS_BASE_URL?.trim() ||
	process.env.PLAYWRIGHT_BASE_URL?.trim() ||
	'http://localhost:3000';

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

// Credentials for the accounts provisioned by the setup step (helpers/accounts.ts).
export function adminCredentials(): Credentials {
	return { email: ADMIN.email, password: ADMIN.password };
}

export function studentCredentials(): Credentials {
	return { email: STUDENT.email, password: STUDENT.password };
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
