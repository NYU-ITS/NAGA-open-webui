import { expect, test, type Page, type Route } from '@playwright/test';

const mockUser = {
	id: 'user-admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token'
};

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

async function mockModelApis(page: Page) {
	await page.route('**/api/**', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const method = route.request().method();

		if (path === '/api/config' && method === 'GET') {
			return json(route, { name: 'Test', version: 'test', default_locale: 'en-US', features: {} });
		}
		if (path === '/api/v1/auths/' && method === 'GET') {
			return json(route, mockUser);
		}
		if (path === '/api/v1/users/user/settings' && method === 'GET') {
			return json(route, { ui: { version: 'test' } });
		}
		if (path === '/api/v1/users/is-super-admin' && method === 'GET') {
			return json(route, true);
		}
		if ((path === '/api/models' || path === '/api/v1/models/') && method === 'GET') {
			return json(route, []);
		}
		if (path === '/api/models/base' && method === 'GET') {
			return json(route, []);
		}
		if (path === '/api/v1/models/create' && method === 'POST') {
			const body = JSON.parse(route.request().postData() || '{}');
			if (!body.name) {
				return json(route, { detail: 'Name is required' }, 422);
			}
			return json(route, { id: body.id, name: body.name });
		}
		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}
		return json(route, {});
	});
}

test.beforeEach(async ({ page }) => {
	await page.addInitScript(() => {
		localStorage.setItem('token', 'playwright-token');
		localStorage.setItem('locale', 'en-US');
		sessionStorage.clear();
	});
});

test.describe('custom model validation UX (mocked)', () => {
	test('blocks submission when name is empty', async ({ page }) => {
		await mockModelApis(page);
		await page.goto('/workspace/models/create');
		await page.locator('form').evaluate((form) => form.requestSubmit());
		await expect(page).toHaveURL(/\/workspace\/models\/create/);
	});

	test('shows duplicate id error without redirecting', async ({ page }) => {
		await mockModelApis(page);
		await page.goto('/workspace/models/create');
		await page.getByPlaceholder('Model Name').fill('Duplicate Model');
		await page.getByPlaceholder('Model ID').fill('existing-id');
		await page.locator('form').evaluate((form) => form.requestSubmit());
		await expect(page).toHaveURL(/\/workspace\/models\/create/);
	});

	test('base model field prevents submission when empty', async ({ page }) => {
		await mockModelApis(page);
		await page.goto('/workspace/models/create');
		await page.getByPlaceholder('Model Name').fill('No Base Model');
		await page.locator('form').evaluate((form) => form.requestSubmit());
		await expect(page).toHaveURL(/\/workspace\/models\/create/);
	});
});
