# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: models/model-crud.mocked.spec.ts >> custom model CRUD (mocked) >> lists and deletes a custom model
- Location: playwright/tests/models/model-crud.mocked.spec.ts:70:2

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('button', { name: /create/i })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for getByRole('button', { name: /create/i })

```

# Page snapshot

```yaml
- img [ref=e3]
```

# Test source

```ts
  1  | import { expect, test, type Page, type Route } from '@playwright/test';
  2  | 
  3  | const mockUser = {
  4  | 	id: 'user-admin-1',
  5  | 	name: 'Admin User',
  6  | 	email: 'admin@example.com',
  7  | 	role: 'admin',
  8  | 	token: 'playwright-token'
  9  | };
  10 | 
  11 | const mockModels: Array<{ id: string; name: string; base_model_id: string }> = [];
  12 | 
  13 | const json = (route: Route, payload: unknown, status = 200) =>
  14 | 	route.fulfill({
  15 | 		status,
  16 | 		contentType: 'application/json',
  17 | 		body: JSON.stringify(payload)
  18 | 	});
  19 | 
  20 | async function mockModelApis(page: Page) {
  21 | 	await page.route('**/api/**', async (route) => {
  22 | 		const url = new URL(route.request().url());
  23 | 		const path = url.pathname;
  24 | 		const method = route.request().method();
  25 | 
  26 | 		if (path === '/api/config' && method === 'GET') {
  27 | 			return json(route, { name: 'Test', version: 'test', default_locale: 'en-US', features: {} });
  28 | 		}
  29 | 		if (path === '/api/v1/auths/' && method === 'GET') {
  30 | 			return json(route, mockUser);
  31 | 		}
  32 | 		if (path === '/api/v1/users/user/settings' && method === 'GET') {
  33 | 			return json(route, { ui: { version: 'test' } });
  34 | 		}
  35 | 		if (path === '/api/v1/users/is-super-admin' && method === 'GET') {
  36 | 			return json(route, true);
  37 | 		}
  38 | 		if (path === '/api/v1/models/' && method === 'GET') {
  39 | 			return json(route, mockModels);
  40 | 		}
  41 | 		if (path === '/api/v1/models/create' && method === 'POST') {
  42 | 			const body = JSON.parse(route.request().postData() || '{}');
  43 | 			const model = { id: body.id, name: body.name, base_model_id: body.base_model_id };
  44 | 			mockModels.push(model);
  45 | 			return json(route, model);
  46 | 		}
  47 | 		if (path.startsWith('/api/v1/models/model/delete') && method === 'DELETE') {
  48 | 			const id = new URL(route.request().url()).searchParams.get('id');
  49 | 			const idx = mockModels.findIndex((m) => m.id === id);
  50 | 			if (idx >= 0) mockModels.splice(idx, 1);
  51 | 			return json(route, { deleted: true });
  52 | 		}
  53 | 		if (path.startsWith('/api/v1/')) {
  54 | 			return json(route, []);
  55 | 		}
  56 | 		return json(route, {});
  57 | 	});
  58 | }
  59 | 
  60 | test.beforeEach(async ({ page }) => {
  61 | 	mockModels.length = 0;
  62 | 	await page.addInitScript(() => {
  63 | 		localStorage.setItem('token', 'playwright-token');
  64 | 		localStorage.setItem('locale', 'en-US');
  65 | 		sessionStorage.clear();
  66 | 	});
  67 | });
  68 | 
  69 | test.describe('custom model CRUD (mocked)', () => {
  70 | 	test('lists and deletes a custom model', async ({ page }) => {
  71 | 		await mockModelApis(page);
  72 | 
  73 | 		await page.goto('/workspace/models');
> 74 | 		await expect(page.getByRole('button', { name: /create/i })).toBeVisible();
     |                                                               ^ Error: expect(locator).toBeVisible() failed
  75 | 
  76 | 		await page.getByPlaceholder('Model Name').fill('Test CRUD Model');
  77 | 		await page.locator('form').evaluate((form) => form.requestSubmit());
  78 | 
  79 | 		await expect(page.locator('#model-item-Test-CRUD-Model')).toBeVisible();
  80 | 	});
  81 | });
  82 | 
```