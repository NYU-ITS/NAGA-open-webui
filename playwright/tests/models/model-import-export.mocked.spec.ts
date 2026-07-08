import { expect, test, type Page, type Route } from '@playwright/test';

const mockUser = {
	id: 'user-admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token'
};

const mockModels = [
	{ id: 'model-1', name: 'Export Model 1', base_model_id: 'gpt-4o-mini' },
	{ id: 'model-2', name: 'Export Model 2', base_model_id: 'gpt-4o' }
];

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

async function mockImportExportApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		if (!path.startsWith('/api/')) {
			return route.continue();
		}
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
		if (path === '/api/v1/users/' && method === 'GET') {
			return json(route, [mockUser]);
		}
		if (path === '/api/models' && method === 'GET') {
			return json(route, { data: mockModels });
		}
		if (path === '/api/v1/models/' && method === 'GET') {
			return json(route, mockModels);
		}
		if (path === '/api/models/base' && method === 'GET') {
			return json(route, []);
		}
		if (path === '/api/v1/models/create' && method === 'POST') {
			const body = JSON.parse(route.request().postData() || '{}');
			mockModels.push({ id: body.id, name: body.name, base_model_id: body.base_model_id });
			return json(route, { id: body.id, name: body.name });
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
	await page.addInitScript(() => {
		localStorage.setItem('token', 'playwright-token');
		localStorage.setItem('locale', 'en-US');
		sessionStorage.clear();
	});
});

test.describe('custom model import and export (mocked)', () => {
	test('exports all models from list page', async ({ page }) => {
		await mockImportExportApis(page);
		await page.goto('/workspace/models');
		await expect(page.locator('#splash-screen')).toHaveCount(0, { timeout: 15000 });
		const downloadPromise = page.waitForEvent('download');
		await page.getByRole('button', { name: 'Export Models' }).click({ force: true });
		const download = await downloadPromise;
		expect(download.suggestedFilename()).toMatch(/^models-export-\d+\.json$/);
	});

	test('imports valid JSON as new model', async ({ page }) => {
		await mockImportExportApis(page);
		await page.goto('/workspace/models');
		await expect(page.locator('#splash-screen')).toHaveCount(0, { timeout: 15000 });
		await page.locator('#models-import-input').setInputFiles({
			name: 'models-import-new.json',
			mimeType: 'application/json',
			buffer: Buffer.from(JSON.stringify([{ id: 'imported-1', info: { id: 'imported-1', name: 'Imported Model' } }]))
		});
		await expect(page.locator('#model-item-imported-1')).toBeVisible();
	});

	test('skips entries missing model.info safely', async ({ page }) => {
		await mockImportExportApis(page);
		await page.goto('/workspace/models');
		await expect(page.locator('#splash-screen')).toHaveCount(0, { timeout: 15000 });
		await page.locator('#models-import-input').setInputFiles({
			name: 'models-import-skip.json',
			mimeType: 'application/json',
			buffer: Buffer.from(JSON.stringify([{ id: 'skip-1' }]))
		});
		await expect(page.getByText(/SyntaxError|TypeError|Unhandled/i)).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Export Models' })).toBeVisible();
	});
});
