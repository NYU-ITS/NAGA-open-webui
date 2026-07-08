import { expect, test } from '@playwright/test';
import { loginViaApi, dismissModals, getAuthToken, signInViaApi, ADMIN_EMAIL, ADMIN_PASSWORD } from '../../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId, waitForModelViaAPI } from '../../fixtures/models';

test.skip(process.env.PLAYWRIGHT_RUN_LIVE !== '1', 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

const createdIds: string[] = [];

test.afterAll(async ({ request }) => {
	if (createdIds.length === 0) return;
	const token = await signInViaApi(request, ADMIN_EMAIL, ADMIN_PASSWORD).catch(() => null);
	if (!token) return;
	for (const id of createdIds) {
		await deleteModelViaAPI(request, token, id).catch(() => {});
	}
});

test.describe('custom model validation UX', () => {
	test('blocks submission when name is empty', async ({ page }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		await page.goto('/workspace/models/create');
		await dismissModals(page);
		await page.locator('form').evaluate((form) => form.requestSubmit());
		await expect(page).toHaveURL(/\/workspace\/models\/create/);
	});

	test('shows duplicate id error without redirecting', async ({ page, request }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const token = await getAuthToken(page);
		const id = uniqueId('e2e-dupe');
		createdIds.push(id);
		await createModelViaAPI(request, token, { id, name: `Existing ${id}` });
		await waitForModelViaAPI(request, token, id);
		await page.reload();

		await page.goto('/workspace/models/create');
		await dismissModals(page);
		await page.getByPlaceholder('Model Name').fill(`Duplicate ${id}`);
		await page.getByPlaceholder('Model ID').fill(id);
		await page.locator('form').evaluate((form) => form.requestSubmit());
		await expect(page).toHaveURL(/\/workspace\/models\/create/);
	});

	test('base model field prevents submission when empty', async ({ page }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const id = uniqueId('e2e-no-base');
		await page.goto('/workspace/models/create');
		await dismissModals(page);
		await page.getByPlaceholder('Model Name').fill(`No Base ${id}`);
		await page.getByPlaceholder('Add a short description about what this model does').fill('No base selected');
		await page.locator('form').evaluate((form) => form.requestSubmit());
		await expect(page).toHaveURL(/\/workspace\/models\/create/);
	});
});
