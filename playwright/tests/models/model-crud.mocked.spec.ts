import { expect, test, type Page, type Route } from '@playwright/test';

const mockUser = {
	id: 'user-admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token'
};

const mockModels: Array<{ id: string; name: string; base_model_id: string }> = [];

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
		if (path === '/api/v1/models/' && method === 'GET') {
			return json(route, mockModels);
		}
		if (path === '/api/v1/models/create' && method === 'POST') {
			const body = JSON.parse(route.request().postData() || '{}');
			const model = { id: body.id, name: body.name, base_model_id: body.base_model_id };
			mockModels.push(model);
			return json(route, model);
		}
		if (path.startsWith('/api/v1/models/model/delete') && method === 'DELETE') {
			const id = new URL(route.request().url()).searchParams.get('id');
			const idx = mockModels.findIndex((m) => m.id === id);
			if (idx >= 0) mockModels.splice(idx, 1);
			return json(route, { deleted: true });
		}
		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}
		return json(route, {});
	});
}

test.beforeEach(async ({ page }) => {
	mockModels.length = 0;
	await page.addInitScript(() => {
		localStorage.setItem('token', 'playwright-token');
		localStorage.setItem('locale', 'en-US');
		sessionStorage.clear();
	});
});

test.describe('custom model CRUD (mocked)', () => {
	test('lists and deletes a custom model', async ({ page }) => {
		await mockModelApis(page);

		await page.goto('/workspace/models');
		await expect(page.getByRole('button', { name: /create/i })).toBeVisible();

		await page.getByPlaceholder('Model Name').fill('Test CRUD Model');
		await page.locator('form').evaluate((form) => form.requestSubmit());

		await expect(page.locator('#model-item-Test-CRUD-Model')).toBeVisible();
	});
});
