import { type APIRequestContext, expect } from '@playwright/test';
import { retryApiRequest } from '../../../fixtures/auth';

export { authHeaders } from '../../../fixtures/auth';

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

const IS_LIVE = process.env.PLAYWRIGHT_RUN_LIVE === '1';

// On a live run the accounts come from the ai-tutor-playwright-live-secret in
// OpenShift. Never fall back to hardcoded defaults or sign up against a deployed
// instance: require all four credentials up front and fail fast if any is unset.
const LIVE_CREDENTIAL_VARS = [
	'PLAYWRIGHT_ADMIN_EMAIL',
	'PLAYWRIGHT_ADMIN_PASSWORD',
	'PLAYWRIGHT_STUDENT_EMAIL',
	'PLAYWRIGHT_STUDENT_PASSWORD'
] as const;

function assertLiveCredentials(): void {
	const missing = LIVE_CREDENTIAL_VARS.filter((name) => !process.env[name]?.trim());
	if (missing.length > 0) {
		throw new Error(
			`Live Playwright runs (PLAYWRIGHT_RUN_LIVE=1) require credentials to be provided ` +
				`via the ai-tutor-playwright-live-secret; missing: ${missing.join(', ')}. ` +
				`Hardcoded fallbacks are only allowed for local/fresh instances.`
		);
	}
}

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

let lastSigninFailure = '';

async function signin(
	request: APIRequestContext,
	email: string,
	password: string
): Promise<SigninResult | null> {
	const res = await retryApiRequest(
		() => request.post('/api/v1/auths/signin', { data: { email, password } }),
		`signin ${email}`
	);
	if (!res.ok()) {
		lastSigninFailure = `HTTP ${res.status()} from ${res.url()}: ${await res.text()}`;
		return null;
	}
	return res.json();
}

async function ensureAdmin(request: APIRequestContext): Promise<SigninResult> {
	const existing = await signin(request, ADMIN.email, ADMIN.password);
	if (existing) {
		expect(existing.role, `account ${ADMIN.email} exists but is not an admin`).toBe('admin');
		return existing;
	}

	if (IS_LIVE) {
		throw new Error(
			`Live run: could not sign in as admin (${ADMIN.email}). ${lastSigninFailure}\n` +
				`A 400 means the account or password is wrong. A 5xx means the deployed instance ` +
				`was not serving the request. Signup is disabled for live runs either way.`
		);
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

	if (!student && IS_LIVE) {
		throw new Error(
			`Live run: could not sign in as the student (${STUDENT.email}). ${lastSigninFailure}\n` +
				`Account creation is disabled for live runs.`
		);
	}

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
	if (IS_LIVE) {
		assertLiveCredentials();
	}
	const admin = await ensureAdmin(request);
	await ensureStudent(request, admin.token);
}
