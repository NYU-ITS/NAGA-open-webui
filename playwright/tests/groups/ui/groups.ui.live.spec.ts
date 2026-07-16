import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { ADMIN, ensureTestAccounts, authHeaders } from '../helpers/accounts';
import {
	getAuthToken,
	loginViaApi,
	requireOk,
	retryApiRequest,
	signInViaApi
} from '../../../fixtures/auth';

// Live groups UI. Mirrors the seven scenarios of groups.ui.mocked.spec.ts but
// runs against a real Open WebUI instance. Gated behind PLAYWRIGHT_RUN_LIVE=1.
// The admin and student accounts come from the ai-tutor-playwright-live-secret
// env vars; ensureTestAccounts only signs them in on live runs and never
// creates accounts against a deployed instance.

const liveEnabled = process.env.PLAYWRIGHT_RUN_LIVE === '1';

// Every group name this spec creates matches this pattern, so cleanup can
// delete by pattern instead of tracking names, which also removes debris
// leaked by earlier failed runs. Timestamped names make collisions with a
// concurrent run vanishingly unlikely.
const E2E_GROUP_RE = /^e2e-(list|ui|search|other|edit|delete)-\d+/;

async function deleteStaleE2eGroups(request: APIRequestContext, token: string) {
	const res = await request.get('/api/v1/groups/', { headers: authHeaders(token) });
	if (!res.ok()) return;
	const groups: Array<{ id: string; name: string }> = await res.json();
	for (const group of groups) {
		if (E2E_GROUP_RE.test(group.name)) {
			await request
				.delete(`/api/v1/groups/id/${group.id}/delete`, { headers: authHeaders(token) })
				.catch(() => {});
		}
	}
}

async function loginAsAdmin(page: Page): Promise<string> {
	await loginViaApi(page, ADMIN.email, ADMIN.password);
	return getAuthToken(page);
}

async function dismissWhatsNewIfShown(page: Page) {
	const button = page.getByRole('button', { name: "Okay, Let's Go!" });
	if (await button.isVisible().catch(() => false)) {
		await button.click();
	}
}

// The Groups panel is gated behind `{#if loaded}` and only renders once onMount
// has awaited both getGroups() and getUserDefaultPermissions(). Against a live
// backend those two round trips routinely exceed the 5s default expect timeout.
const PANEL_LOAD_TIMEOUT = 30_000;

// A mutation is followed by a server round trip plus a list refetch. The live
// backend's group writes are slow and variable (a create POST can take well
// over 30s), so give mutations generous headroom.
const LIST_REFRESH_TIMEOUT = 60_000;

// A UI mutation can be eaten by a backend stall (readiness-probe 503 window),
// which lasts 30s or more; retried flows need to outlast at least one window
// plus the reloads between attempts, which crawl during the same stall.
const MUTATION_RETRY_TIMEOUT = 180_000;

// On WebKit the app intermittently fails to boot: a bootstrap /api/config fetch
// rejects with "TypeError: Load failed", so the root layout treats the backend
// as down and redirects to /error, leaving no Groups tab. A reload re-runs the
// bootstrap and usually succeeds. Every step here is bounded and inside the
// try/catch so a bad boot triggers a reload instead of hanging the whole test
// (an unbounded click on the missing Groups tab would block for the full test
// timeout and never reach the retry).
async function gotoGroupsTab(page: Page) {
	const attempts = 3;
	for (let attempt = 1; attempt <= attempts; attempt++) {
		await page.goto('/admin/users');
		await dismissWhatsNewIfShown(page);
		try {
			await page
				.getByRole('button', { name: 'Groups', exact: true })
				.click({ timeout: PANEL_LOAD_TIMEOUT });
			await expect(page.getByLabel('Create Group').first()).toBeVisible({
				timeout: PANEL_LOAD_TIMEOUT
			});
			return;
		} catch (error) {
			if (attempt === attempts) throw error;
		}
	}
}

// The live backend is read-after-write eventually consistent, so its list
// endpoint can miss groups created moments ago. The panel's single onMount
// fetch does not retry, so wait for the group to be listed server-side before
// loading the UI.
async function waitForGroupListed(request: APIRequestContext, token: string, ...names: string[]) {
	await expect(async () => {
		const res = await request.get('/api/v1/groups/', { headers: authHeaders(token) });
		const listed = ((await res.json()) as Array<{ name: string }>).map((g) => g.name);
		expect(listed).toEqual(expect.arrayContaining(names));
	}).toPass({ timeout: LIST_REFRESH_TIMEOUT });
}

// Raw request.post can transiently fail against the live backend, and the test
// never notices because it does not check the status. Retry on transient errors
// and assert the create succeeded so a real failure surfaces immediately.
async function createGroupViaApi(request: APIRequestContext, token: string, name: string) {
	// The default retry window (~3.5s) is shorter than a backend outage: when
	// the pod stalls and fails its readiness probe, the router serves 503 for
	// 30s or more until the probe recovers. Back off long enough to outlast one
	// full outage window.
	const res = await retryApiRequest(
		() =>
			request.post('/api/v1/groups/create', {
				headers: authHeaders(token),
				data: { name, description: 'x' }
			}),
		`create group ${name}`,
		{ attempts: 7, baseDelayMs: 1000 }
	);
	await requireOk(res, `create group ${name}`);
}

// A UI create fetch can be dropped by a backend stall, so the modal closes
// with an error toast and nothing persists (addGroupHandler swallows the
// rejection). Retry the full submit until the success toast confirms it went
// through, rather than clicking once and blindly polling the API.
// submitHandler clears the fields and closes the modal on every attempt, so
// each retry reopens and refills.
async function createGroupThroughUI(page: Page, name: string) {
	await expect(async () => {
		await page.getByLabel('Create Group').first().click();
		await page.getByPlaceholder('Group Name').fill(name);
		await page.getByPlaceholder('Group Description').fill('live ui test');
		await page.getByRole('button', { name: 'Create', exact: true }).click();
		await expect(page.getByText('Group created successfully')).toBeVisible({
			timeout: PANEL_LOAD_TIMEOUT
		});
	}).toPass({ timeout: MUTATION_RETRY_TIMEOUT });
}

// Renames need the same retry treatment as creates. Each attempt first checks
// the server so a rename that landed late is not retried, and reloads the tab
// so a half-open modal from a failed attempt cannot wedge the next one.
async function renameGroupThroughUI(page: Page, token: string, from: string, to: string) {
	await expect(async () => {
		const res = await page.request.get('/api/v1/groups/', { headers: authHeaders(token) });
		const listed = ((await res.json()) as Array<{ name: string }>).map((g) => g.name);
		if (listed.includes(to)) return;
		await gotoGroupsTab(page);
		await page.getByText(from, { exact: true }).click();
		const input = page.getByPlaceholder('Group Name');
		await expect(input).toBeVisible();
		await input.fill(to);
		await page.getByRole('button', { name: 'Save', exact: true }).click();
		await expect(page.getByText('Group updated successfully')).toBeVisible({
			timeout: PANEL_LOAD_TIMEOUT
		});
	}).toPass({ timeout: MUTATION_RETRY_TIMEOUT });
}

// The Groups panel fetches its list once on mount and never refetches, so if
// that single fetch lands in a backend stall the row set is stale until the
// next load. Assert row visibility by reloading between attempts instead of
// staring at one stale render.
async function expectGroupRowVisible(page: Page, name: string, visible = true) {
	await expect(async () => {
		await gotoGroupsTab(page);
		const row = page.getByText(name, { exact: true });
		if (visible) {
			await expect(row).toBeVisible({ timeout: 10_000 });
		} else {
			await expect(row).toBeHidden({ timeout: 10_000 });
		}
	}).toPass({ timeout: MUTATION_RETRY_TIMEOUT });
}

// Deletes get the same retry-until-toast structure as renames above.
async function deleteGroupThroughUI(page: Page, token: string, name: string) {
	await expect(async () => {
		const res = await page.request.get('/api/v1/groups/', { headers: authHeaders(token) });
		const listed = ((await res.json()) as Array<{ name: string }>).map((g) => g.name);
		if (!listed.includes(name)) return;
		await gotoGroupsTab(page);
		await page.getByText(name, { exact: true }).click();
		await page.getByRole('button', { name: 'Delete', exact: true }).click();
		await page.getByRole('button', { name: 'Delete', exact: true }).last().click();
		await expect(page.getByText('Group deleted successfully')).toBeVisible({
			timeout: PANEL_LOAD_TIMEOUT
		});
	}).toPass({ timeout: MUTATION_RETRY_TIMEOUT });
}

test.describe('groups UI (live backend)', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run the live groups UI workflows.');

	// These tests share one admin account and mutate the same global group list,
	// so they must run one at a time: `mode: 'default'` opts this file out of
	// the config's fullyParallel, and live runs pin workers to 1 so browser
	// projects cannot race each other either. Deliberately not `mode: 'serial'`:
	// serial skips the remaining tests after one failure, while each test here
	// stands alone (beforeEach signs in fresh and cleanup is pattern-based), so
	// the rest should still run.
	test.describe.configure({ mode: 'default' });

	let adminToken = '';

	// Hooks do not inherit the beforeEach timeout. Signing in both accounts, with
	// retries, does not fit the 30s default against a live backend.
	test.beforeAll(async ({ request }) => {
		test.setTimeout(120_000);
		await ensureTestAccounts(request);
		// Failed runs leak e2e-* groups, and every leftover group row makes the
		// Groups panel fire another expensive /api/v1/models/ request on load.
		// Enough debris freezes the single backend pod, fails its readiness
		// probe, and turns the whole run into router 503s, so purge up front.
		const token = await signInViaApi(request, ADMIN.email, ADMIN.password);
		await deleteStaleE2eGroups(request, token);
	});

	// Matches the live models specs: a live run does several full app loads plus
	// retried mutations that each must outlast a backend stall window, which
	// does not fit Playwright's 30s default.
	test.beforeEach(async ({ page }) => {
		test.setTimeout(300_000);
		// The deployed Groups panel mounts a hidden workspace modal per group row
		// and each modal eagerly fetches GET /api/v1/models/, which blocks the
		// single backend worker for ~6s per call. Those calls are what stall the
		// pod, fail its readiness probe, and turn the run into router 503s.
		// Models are irrelevant to every groups scenario here, so stub just that
		// endpoint in the browser; all other requests still hit the live backend.
		await page.route(
			(url) => url.pathname === '/api/v1/models/',
			(route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
		);
		adminToken = await loginAsAdmin(page);
	});

	// Purge after every test, not just afterAll: each leftover e2e-* row makes
	// the next Groups panel load fire another expensive /api/v1/models/ call,
	// so letting rows accumulate across tests rebuilds the very backend stalls
	// that make these tests flaky.
	test.afterEach(async ({ request }) => {
		if (!adminToken) return;
		await deleteStaleE2eGroups(request, adminToken);
	});

	test.afterAll(async ({ request }) => {
		test.setTimeout(120_000);
		if (!adminToken) return;
		await deleteStaleE2eGroups(request, adminToken);
	});

	test('list renders seeded groups', async ({ page }) => {
		const name = `e2e-list-${Date.now()}`;
		await createGroupViaApi(page.request, adminToken, name);
		await waitForGroupListed(page.request, adminToken, name);

		await expectGroupRowVisible(page, name);
	});

	test('create a group', async ({ page }) => {
		const name = `e2e-ui-${Date.now()}`;

		await gotoGroupsTab(page);
		await createGroupThroughUI(page, name);

		// Confirm the mutation actually persisted before reloading: this both
		// absorbs the live backend's read-after-write lag and fails clearly if the
		// create request itself did not go through. Verify through page.request so
		// it shares the browser's session with the UI (the standalone request
		// fixture is a separate session and sees a lagging view).
		await waitForGroupListed(page.request, adminToken, name);
		await expectGroupRowVisible(page, name);
	});

	test('search filters the group list by name', async ({ page }) => {
		const visible = `e2e-search-${Date.now()}`;
		const hidden = `e2e-other-${Date.now()}`;
		for (const name of [visible, hidden]) {
			await createGroupViaApi(page.request, adminToken, name);
		}

		await waitForGroupListed(page.request, adminToken, visible, hidden);

		await gotoGroupsTab(page);
		// Confirm the row is loaded before filtering; the default 5s expect
		// timeout is too short for a live backend (see LIST_REFRESH_TIMEOUT).
		await expect(page.getByText(visible, { exact: true })).toBeVisible({
			timeout: LIST_REFRESH_TIMEOUT
		});

		await page.getByPlaceholder('Search').last().fill(visible);
		await expect(page.getByText(visible, { exact: true })).toBeVisible();
		await expect(page.getByText(hidden, { exact: true })).toBeHidden();
	});

	test('searching for a non-existent group shows the empty state', async ({ page }) => {
		await gotoGroupsTab(page);
		await page.getByPlaceholder('Search').last().fill(`no-such-group-${Date.now()}`);
		await expect(page.getByText('Organize your users')).toBeVisible();
	});

	test('edit a group name', async ({ page }) => {
		const name = `e2e-edit-${Date.now()}`;
		const renamed = `${name}-renamed`;
		await createGroupViaApi(page.request, adminToken, name);

		await waitForGroupListed(page.request, adminToken, name);
		await renameGroupThroughUI(page, adminToken, name, renamed);

		// The list does not re-render in place after an edit, so reload the tab
		// and assert against freshly fetched groups (matches create/delete).
		await expectGroupRowVisible(page, renamed);
		await expect(page.getByText(name, { exact: true })).toBeHidden();
	});

	test('delete a group', async ({ page }) => {
		const name = `e2e-delete-${Date.now()}`;
		await createGroupViaApi(page.request, adminToken, name);

		await waitForGroupListed(page.request, adminToken, name);
		await deleteGroupThroughUI(page, adminToken, name);

		// The list does not re-render in place after a delete, so reload the tab
		// and assert against freshly fetched groups.
		await expectGroupRowVisible(page, name, false);
	});

	test('create-group modal opens and can be dismissed', async ({ page }) => {
		await gotoGroupsTab(page);

		await page.getByLabel('Create Group').first().click();
		await expect(page.getByPlaceholder('Group Name')).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(page.getByPlaceholder('Group Name')).toBeHidden();
	});
});
