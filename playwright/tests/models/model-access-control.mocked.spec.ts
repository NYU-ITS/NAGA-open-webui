import { expect, test, type Page, type Route } from '@playwright/test';

const mockAdmin = {
	id: 'user-admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'admin-token'
};

const mockUser = {
	id: 'user-regular-1',
	name: 'Regular User',
	email: 'user@example.com',
	role: 'user',
	token: 'user-token'
};

const mockModels = [
	{
		id: 'admin-private-model',
		name: 'Private Admin Model',
		user_id: mockAdmin.id,
		access_control: { read: { group_ids: [], user_ids: [] }, write: { group_ids: [], user_ids: [] } }
	}
];

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

async function mockAccessControlApis(page: Page, currentUser: typeof mockAdmin) {
	await page.route('**/api/**', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const method = route.request().method();

		if (path === '/api/config' && method === 'GET') {
			return json(route, { name: 'Test', version: 'test', default_locale: 'en-US', features: {} });
		}
		if (path === '/api/v1/auths/' && method === 'GET') {
			return json(route, currentUser);
		}
		if (path === '/api/v1/auths/signin' && method === 'POST') {
			return json(route, { token: currentUser.token });
		}
		if (path === '/api/v1/users/user/settings' && method === 'GET') {
			return json(route, { ui: { version: 'test' } });
		}
		if (path === '/api/v1/users/is-super-admin' && method === 'GET') {
			return json(route, currentUser.role === 'admin');
		}
		if (path === '/api/v1/models/' && method === 'GET') {
			const visible = currentUser.role === 'admin'
				? mockModels
				: mockModels.filter((m) => m.user_id === currentUser.id);
			return json(route, visible);
		}
		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}
		return json(route, {});
	});
}

test.beforeEach(async ({ page }) => {
	await page.addInitScript(() => {
		localStorage.setItem('token', 'admin-token');
		localStorage.setItem('locale', 'en-US');
		sessionStorage.clear();
	});
});

test.describe('custom model access control (mocked)', () => {
	test('admin sees all models', async ({ page }) => {
		await mockAccessControlApis(page, mockAdmin);
		await page.goto('/workspace/models');
		await expect(page.locator('#model-item-admin-private-model')).toBeVisible();
	});

	test('regular user sees only own models', async ({ page }) => {
		await mockAccessControlApis(page, mockUser);
		await page.goto('/workspace/models');
		await expect(page.locator('#model-item-admin-private-model')).toHaveCount(0);
	});
});
