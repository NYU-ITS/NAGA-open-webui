import { expect, test, type Page } from '@playwright/test';
import { ADMIN, ensureTestAccounts, authHeaders } from '../helpers/accounts';

// Live groups UI. Runs against a real Open WebUI instance. Gated behind
// PLAYWRIGHT_RUN_LIVE=1 (mirrors ai-tutor-dashboard.live.spec.ts). The admin and
// non-admin accounts are provisioned once by ensureTestAccounts.

const liveEnabled = process.env.PLAYWRIGHT_RUN_LIVE === '1';
const createdNames: string[] = [];

async function loginAsAdmin(page: Page): Promise<string> {
	const res = await page.request.post('/api/v1/auths/signin', {
		data: { email: ADMIN.email, password: ADMIN.password }
	});
	if (!res.ok()) {
		throw new Error(`admin login failed (${res.status()}): ${await res.text()}`);
	}
	const token = (await res.json()).token as string;
	await page.addInitScript((t) => {
		localStorage.setItem('token', t);
		localStorage.setItem('locale', 'en-US');
	}, token);
	await page.goto('/');
	await expect(page).not.toHaveURL(/\/auth$/);
	return token;
}

async function dismissWhatsNewIfShown(page: Page) {
	const button = page.getByRole('button', { name: "Okay, Let's Go!" });
	if (await button.isVisible().catch(() => false)) {
		await button.click();
	}
}

async function gotoGroupsTab(page: Page) {
	await page.goto('/admin/users');
	await dismissWhatsNewIfShown(page);
	await page.getByRole('button', { name: 'Groups', exact: true }).click();
	await expect(page.getByLabel('Create Group').first()).toBeVisible();
}

test.describe('groups UI (live backend)', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run the live groups UI workflows.');

	let adminToken = '';

	test.beforeAll(async ({ request }) => {
		await ensureTestAccounts(request);
	});

	test.beforeEach(async ({ page }) => {
		adminToken = await loginAsAdmin(page);
	});

	test.afterAll(async ({ request }) => {
		if (!adminToken) return;
		const res = await request.get('/api/v1/groups/', { headers: authHeaders(adminToken) });
		if (!res.ok()) return;
		const groups: Array<{ id: string; name: string }> = await res.json();
		for (const group of groups) {
			if (createdNames.includes(group.name)) {
				await request
					.delete(`/api/v1/groups/id/${group.id}/delete`, { headers: authHeaders(adminToken) })
					.catch(() => {});
			}
		}
	});

	test('admin can create a group through the UI', async ({ page }) => {
		const name = `e2e-ui-${Date.now()}`;
		createdNames.push(name);

		await gotoGroupsTab(page);
		await page.getByLabel('Create Group').first().click();
		await page.getByPlaceholder('Group Name').fill(name);
		await page.getByPlaceholder('Group Description').fill('live ui test');
		await page.getByRole('button', { name: 'Create', exact: true }).click();

		await expect(page.getByText(name, { exact: true })).toBeVisible();
	});

	test('search filters the group list by name', async ({ page, request }) => {
		const visible = `e2e-search-${Date.now()}`;
		const hidden = `e2e-other-${Date.now()}`;
		createdNames.push(visible, hidden);
		for (const name of [visible, hidden]) {
			await request.post('/api/v1/groups/create', {
				headers: authHeaders(adminToken),
				data: { name, description: 'x' }
			});
		}

		await gotoGroupsTab(page);
		await page.getByPlaceholder('Search').last().fill(visible);
		await expect(page.getByText(visible, { exact: true })).toBeVisible();
		await expect(page.getByText(hidden, { exact: true })).toBeHidden();
	});

	test('admin can edit a group name through the UI', async ({ page, request }) => {
		const name = `e2e-edit-${Date.now()}`;
		const renamed = `${name}-renamed`;
		createdNames.push(name, renamed);
		await request.post('/api/v1/groups/create', {
			headers: authHeaders(adminToken),
			data: { name, description: 'x' }
		});

		await gotoGroupsTab(page);
		await page.getByText(name, { exact: true }).click();
		const input = page.getByPlaceholder('Group Name');
		await expect(input).toBeVisible();
		await input.fill(renamed);
		await page.getByRole('button', { name: 'Save', exact: true }).click();

		await expect(page.getByText(renamed, { exact: true })).toBeVisible();
	});

	test('admin can delete a group through the UI', async ({ page, request }) => {
		const name = `e2e-delete-${Date.now()}`;
		createdNames.push(name);
		await request.post('/api/v1/groups/create', {
			headers: authHeaders(adminToken),
			data: { name, description: 'x' }
		});

		await gotoGroupsTab(page);
		await page.getByText(name, { exact: true }).click();
		await page.getByRole('button', { name: 'Delete', exact: true }).click();
		await page.getByRole('button', { name: 'Delete', exact: true }).last().click();

		await expect(page.getByText(name, { exact: true })).toBeHidden();
	});
});
