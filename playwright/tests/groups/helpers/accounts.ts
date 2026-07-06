import { type APIRequestContext, expect } from '@playwright/test';

// Fixed test accounts. Defaults are provisioned by the setup step against a
// fresh instance; override via env to point at pre-existing accounts.
export interface TestAccount {
	email: string;
	password: string;
	name: string;
}

// The first signup on a fresh instance only becomes admin if its email is in the
// backend's SUPER_ADMIN_EMAILS allow-list (which defaults to ms15138@nyu.edu).
// Default the admin email to the first of that list so no other config is needed.
function superAdminEmail(): string {
	const first = process.env.SUPER_ADMIN_EMAILS?.split(',')[0]?.trim();
	return first || 'ms15138@nyu.edu';
}

const DEFAULT_PASSWORD = 'password123';

export const ADMIN: TestAccount = {
	email: process.env.PLAYWRIGHT_ADMIN_EMAIL?.trim() || superAdminEmail(),
	password: process.env.PLAYWRIGHT_ADMIN_PASSWORD?.trim() || DEFAULT_PASSWORD,
	name: 'Playwright Admin'
};

export const STUDENT: TestAccount = {
	email: process.env.PLAYWRIGHT_STUDENT_EMAIL?.trim() || 'playwright-student@example.com',
	password: process.env.PLAYWRIGHT_STUDENT_PASSWORD?.trim() || DEFAULT_PASSWORD,
	name: 'Playwright Student'
};

interface SigninResult {
	token: string;
	id: string;
	role: string;
	email: string;
}

async function signin(
	request: APIRequestContext,
	email: string,
	password: string
): Promise<SigninResult | null> {
	const res = await request.post('/api/v1/auths/signin', { data: { email, password } });
	if (!res.ok()) return null;
	return res.json();
}

async function ensureAdmin(request: APIRequestContext): Promise<SigninResult> {
	const existing = await signin(request, ADMIN.email, ADMIN.password);
	if (existing) {
		expect(existing.role, `account ${ADMIN.email} exists but is not an admin`).toBe('admin');
		return existing;
	}

	// On a fresh instance the first signup becomes the admin.
	const res = await request.post('/api/v1/auths/signup', {
		data: { name: ADMIN.name, email: ADMIN.email, password: ADMIN.password }
	});
	expect(
		res.ok(),
		`Could not sign in or sign up the admin (${ADMIN.email}). For a fresh instance the admin ` +
			`email must be allow-listed via the backend's SUPER_ADMIN_EMAILS so the first signup ` +
			`becomes admin; otherwise set PLAYWRIGHT_ADMIN_EMAIL / PLAYWRIGHT_ADMIN_PASSWORD to an ` +
			`existing admin. HTTP ${res.status()}: ${await res.text()}`
	).toBeTruthy();

	const created: SigninResult = await res.json();
	expect(created.role, 'first signup was not granted the admin role').toBe('admin');
	return created;
}

async function ensureStudent(request: APIRequestContext, adminToken: string): Promise<void> {
	let student = await signin(request, STUDENT.email, STUDENT.password);

	if (!student) {
		const add = await request.post('/api/v1/auths/add', {
			headers: { authorization: `Bearer ${adminToken}` },
			data: { name: STUDENT.name, email: STUDENT.email, password: STUDENT.password, role: 'user' }
		});
		expect(
			add.ok(),
			`Could not create the student account. HTTP ${add.status()}: ${await add.text()}`
		).toBeTruthy();
		student = await signin(request, STUDENT.email, STUDENT.password);
		expect(student, 'student sign-in failed right after creation').toBeTruthy();
	}

	// Some deployments create the account "pending" until it accepts terms; promote it.
	if (student!.role !== 'user') {
		await request.post('/api/v1/users/terms/accept', {
			headers: { authorization: `Bearer ${student!.token}` },
			data: {}
		});
		student = await signin(request, STUDENT.email, STUDENT.password);
	}

	expect(student, 'student account missing after provisioning').toBeTruthy();
	expect(student!.role, 'student did not become a verified "user" after provisioning').toBe('user');
}

// Ensure one admin and one verified non-admin ("user") account exist, creating
// them if the instance is fresh. Idempotent: re-running just signs in.
export async function ensureTestAccounts(request: APIRequestContext): Promise<void> {
	const admin = await ensureAdmin(request);
	await ensureStudent(request, admin.token);
}
