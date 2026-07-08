import { expect, test } from '@playwright/test';
import {
	loginViaApi,
	dismissModals,
	getAuthToken,
	ADMIN_EMAIL,
	ADMIN_PASSWORD,
	USER_EMAIL,
	USER_PASSWORD
} from '../../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId } from '../../fixtures/models';

test.skip(process.env.PLAYWRIGHT_RUN_LIVE !== '1', 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

const createdIds: string[] = [];

test.afterAll(async ({ request }) => {
	if (createdIds.length === 0) return;
	const adminRes = await request.post('/api/v1/auths/signin', {
		data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD }
	});
	if (!adminRes.ok()) return;
	const { token } = await adminRes.json();
	for (const id of createdIds) {
		await deleteModelViaAPI(request, token, id).catch(() => {});
	}
});

test.describe('custom model access control visibility', () => {
	test('private admin-created model is hidden from regular user', async ({ browser, page }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const adminToken = await getAuthToken(page);
		const id = uniqueId('e2e-private');
		createdIds.push(id);
		await createModelViaAPI(page.request, adminToken, { id, name: `Private ${id}` });

		const userContext = await browser.newContext();
		const userPage = await userContext.newPage();
		await loginViaApi(userPage, USER_EMAIL, USER_PASSWORD);
		await userPage.goto('/workspace/models');
		await dismissModals(userPage);
		await expect(userPage.locator(`#model-item-${id}`)).toHaveCount(0);

		await userContext.close();
	});

	test('regular user without write access cannot edit', async ({ browser, page }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const adminToken = await getAuthToken(page);
		const id = uniqueId('e2e-no-write');
		createdIds.push(id);
		await createModelViaAPI(page.request, adminToken, { id, name: `No Write ${id}` });

		const userContext = await browser.newContext();
		const userPage = await userContext.newPage();
		await loginViaApi(userPage, USER_EMAIL, USER_PASSWORD);
		await userPage.goto('/workspace/models');
		await dismissModals(userPage);
		await expect(userPage.locator(`#model-item-${id}`)).toHaveCount(0);
		await userPage.goto(`/workspace/models/edit?id=${encodeURIComponent(id)}`);
		await expect(userPage).toHaveURL(/\/workspace\/models/);
		await expect(userPage.getByRole('button', { name: 'Save & Update' })).toHaveCount(0);

		await userContext.close();
	});
});
