# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: models/model-access-control.mocked.spec.ts >> custom model access control (mocked) >> admin sees all models
- Location: playwright/tests/models/model-access-control.mocked.spec.ts:78:2

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('#model-item-admin-private-model')
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('#model-item-admin-private-model')

```

# Page snapshot

```yaml
- img [ref=e3]
```

# Test source

```ts
  1  | import { expect, test, type Page, type Route } from '@playwright/test';
  2  | 
  3  | const mockAdmin = {
  4  | 	id: 'user-admin-1',
  5  | 	name: 'Admin User',
  6  | 	email: 'admin@example.com',
  7  | 	role: 'admin',
  8  | 	token: 'admin-token'
  9  | };
  10 | 
  11 | const mockUser = {
  12 | 	id: 'user-regular-1',
  13 | 	name: 'Regular User',
  14 | 	email: 'user@example.com',
  15 | 	role: 'user',
  16 | 	token: 'user-token'
  17 | };
  18 | 
  19 | const mockModels = [
  20 | 	{
  21 | 		id: 'admin-private-model',
  22 | 		name: 'Private Admin Model',
  23 | 		user_id: mockAdmin.id,
  24 | 		access_control: { read: { group_ids: [], user_ids: [] }, write: { group_ids: [], user_ids: [] } }
  25 | 	}
  26 | ];
  27 | 
  28 | const json = (route: Route, payload: unknown, status = 200) =>
  29 | 	route.fulfill({
  30 | 		status,
  31 | 		contentType: 'application/json',
  32 | 		body: JSON.stringify(payload)
  33 | 	});
  34 | 
  35 | async function mockAccessControlApis(page: Page, currentUser: typeof mockAdmin) {
  36 | 	await page.route('**/api/**', async (route) => {
  37 | 		const url = new URL(route.request().url());
  38 | 		const path = url.pathname;
  39 | 		const method = route.request().method();
  40 | 
  41 | 		if (path === '/api/config' && method === 'GET') {
  42 | 			return json(route, { name: 'Test', version: 'test', default_locale: 'en-US', features: {} });
  43 | 		}
  44 | 		if (path === '/api/v1/auths/' && method === 'GET') {
  45 | 			return json(route, currentUser);
  46 | 		}
  47 | 		if (path === '/api/v1/auths/signin' && method === 'POST') {
  48 | 			return json(route, { token: currentUser.token });
  49 | 		}
  50 | 		if (path === '/api/v1/users/user/settings' && method === 'GET') {
  51 | 			return json(route, { ui: { version: 'test' } });
  52 | 		}
  53 | 		if (path === '/api/v1/users/is-super-admin' && method === 'GET') {
  54 | 			return json(route, currentUser.role === 'admin');
  55 | 		}
  56 | 		if (path === '/api/v1/models/' && method === 'GET') {
  57 | 			const visible = currentUser.role === 'admin'
  58 | 				? mockModels
  59 | 				: mockModels.filter((m) => m.user_id === currentUser.id);
  60 | 			return json(route, visible);
  61 | 		}
  62 | 		if (path.startsWith('/api/v1/')) {
  63 | 			return json(route, []);
  64 | 		}
  65 | 		return json(route, {});
  66 | 	});
  67 | }
  68 | 
  69 | test.beforeEach(async ({ page }) => {
  70 | 	await page.addInitScript(() => {
  71 | 		localStorage.setItem('token', 'admin-token');
  72 | 		localStorage.setItem('locale', 'en-US');
  73 | 		sessionStorage.clear();
  74 | 	});
  75 | });
  76 | 
  77 | test.describe('custom model access control (mocked)', () => {
  78 | 	test('admin sees all models', async ({ page }) => {
  79 | 		await mockAccessControlApis(page, mockAdmin);
  80 | 		await page.goto('/workspace/models');
> 81 | 		await expect(page.locator('#model-item-admin-private-model')).toBeVisible();
     |                                                                 ^ Error: expect(locator).toBeVisible() failed
  82 | 	});
  83 | 
  84 | 	test('regular user sees only own models', async ({ page }) => {
  85 | 		await mockAccessControlApis(page, mockUser);
  86 | 		await page.goto('/workspace/models');
  87 | 		await expect(page.locator('#model-item-admin-private-model')).toHaveCount(0);
  88 | 	});
  89 | });
  90 | 
```