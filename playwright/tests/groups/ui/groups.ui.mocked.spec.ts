import { expect, test, type Page, type Route } from '@playwright/test';

// Mocked groups UI. Auth and every /api call are faked in the browser, so this
// runs against the dev server with no backend, database, or secrets.

const mockAdmin = {
	id: 'admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token'
};

interface MockGroup {
	id: string;
	name: string;
	description: string;
	user_id: string;
	created_by: string;
	permissions: Record<string, unknown> | null;
	user_ids: string[];
	created_at: number;
	updated_at: number;
}

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });

function makeGroup(name: string, description = 'mocked'): MockGroup {
	const now = Math.floor(Date.now() / 1000);
	return {
		id: `grp-${Math.random().toString(36).slice(2, 10)}`,
		name,
		description,
		user_id: mockAdmin.id,
		created_by: mockAdmin.email,
		permissions: {},
		user_ids: [],
		created_at: now,
		updated_at: now
	};
}

async function installMocks(page: Page, initial: MockGroup[] = []) {
	const store = new Map<string, MockGroup>();
	for (const g of initial) store.set(g.id, g);

	await page.addInitScript((token) => {
		localStorage.setItem('token', token);
		localStorage.setItem('locale', 'en-US');
		localStorage.setItem('version', 'test');
	}, mockAdmin.token);

	await page.route('**/api/**', async (route) => {
		const req = route.request();
		const method = req.method();
		const path = new URL(req.url()).pathname;

		if (path === '/api/config' && method === 'GET') {
			return json(route, {
				name: 'Pilot GenAI',
				version: 'test',
				default_locale: 'en-US',
				features: { enable_websocket: false, enable_direct_connections: false, auth: true }
			});
		}
		if (path === '/api/v1/auths/' && method === 'GET') return json(route, mockAdmin);
		if (path === '/api/v1/users/user/settings' && method === 'GET')
			return json(route, { ui: { version: 'test' } });
		if (path === '/api/v1/users/is-super-admin' && method === 'GET') return json(route, false);
		if (path === '/api/v1/users/default/permissions' && method === 'GET') return json(route, {});
		if (path === '/api/v1/users/groups' && method === 'GET') return json(route, []);
		if (path === '/api/v1/users/' && method === 'GET') return json(route, []);

		if (path === '/api/v1/groups/' && method === 'GET') {
			return json(
				route,
				[...store.values()].sort((a, b) => b.updated_at - a.updated_at)
			);
		}
		if (path === '/api/v1/groups/create' && method === 'POST') {
			const body = req.postDataJSON() ?? {};
			const g = makeGroup(body.name ?? 'group', body.description ?? '');
			if (body.permissions) g.permissions = body.permissions;
			store.set(g.id, g);
			return json(route, g);
		}
		const update = path.match(/^\/api\/v1\/groups\/id\/([^/]+)\/update$/);
		if (update && method === 'POST') {
			const g = store.get(update[1]);
			if (!g) return json(route, null, 400);
			const body = req.postDataJSON() ?? {};
			if (body.name !== undefined) g.name = body.name;
			if (body.description !== undefined) g.description = body.description;
			if (body.permissions !== undefined) g.permissions = body.permissions;
			if (body.user_ids !== undefined) g.user_ids = body.user_ids ?? [];
			g.updated_at = Math.floor(Date.now() / 1000);
			store.set(g.id, g);
			return json(route, g);
		}
		const del = path.match(/^\/api\/v1\/groups\/id\/([^/]+)\/delete$/);
		if (del && method === 'DELETE') {
			store.delete(del[1]);
			return json(route, true);
		}

		if (path.startsWith('/api/v1/')) return json(route, []);
		return json(route, {});
	});
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

test.describe('groups UI (mocked backend)', () => {
	test('list renders seeded groups', async ({ page }) => {
		await installMocks(page, [makeGroup('Seeded Group X')]);
		await gotoGroupsTab(page);
		await expect(page.getByText('Seeded Group X', { exact: true })).toBeVisible();
	});

	test('create a group', async ({ page }) => {
		await installMocks(page);
		await gotoGroupsTab(page);

		const name = 'Mocked Class A';
		await page.getByLabel('Create Group').first().click();
		await page.getByPlaceholder('Group Name').fill(name);
		await page.getByPlaceholder('Group Description').fill('created via mock');
		await page.getByRole('button', { name: 'Create', exact: true }).click();

		await expect(page.getByText(name, { exact: true })).toBeVisible();
	});

	test('search filters the group list by name', async ({ page }) => {
		await installMocks(page, [makeGroup('Alpha Group'), makeGroup('Beta Group')]);
		await gotoGroupsTab(page);
		await expect(page.getByText('Alpha Group', { exact: true })).toBeVisible();

		await page.getByPlaceholder('Search').last().fill('Alpha');
		await expect(page.getByText('Alpha Group', { exact: true })).toBeVisible();
		await expect(page.getByText('Beta Group', { exact: true })).toBeHidden();
	});

	test('searching for a non-existent group shows the empty state', async ({ page }) => {
		await installMocks(page, [makeGroup('Only Group')]);
		await gotoGroupsTab(page);
		await page.getByPlaceholder('Search').last().fill('no-such-group');
		await expect(page.getByText('Organize your users')).toBeVisible();
	});

	test('edit a group name', async ({ page }) => {
		await installMocks(page, [makeGroup('Old Name')]);
		await gotoGroupsTab(page);
		await page.getByText('Old Name', { exact: true }).click();

		const nameInput = page.getByPlaceholder('Group Name');
		await expect(nameInput).toBeVisible();
		await nameInput.fill('New Name');
		await page.getByRole('button', { name: 'Save', exact: true }).click();

		await expect(page.getByText('New Name', { exact: true })).toBeVisible();
		await expect(page.getByText('Old Name', { exact: true })).toBeHidden();
	});

	test('delete a group', async ({ page }) => {
		await installMocks(page, [makeGroup('To Delete')]);
		await gotoGroupsTab(page);
		await page.getByText('To Delete', { exact: true }).click();

		await page.getByRole('button', { name: 'Delete', exact: true }).click();
		await page.getByRole('button', { name: 'Delete', exact: true }).last().click();

		await expect(page.getByText('To Delete', { exact: true })).toBeHidden();
	});

	test('create-group modal opens and can be dismissed', async ({ page }) => {
		await installMocks(page);
		await gotoGroupsTab(page);

		await page.getByLabel('Create Group').first().click();
		await expect(page.getByPlaceholder('Group Name')).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(page.getByPlaceholder('Group Name')).toBeHidden();
	});
});
