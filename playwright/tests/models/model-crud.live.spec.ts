import { expect, test } from '@playwright/test';
import { loginViaApi, dismissModals, getAuthToken, signInViaApi, ADMIN_EMAIL, ADMIN_PASSWORD } from '../../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId, waitForModelDeletedViaAPI, waitForModelViaAPI, waitForModelCardInWorkspace } from '../../fixtures/models';

test.skip(process.env.PLAYWRIGHT_RUN_LIVE !== '1', 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

let createdId: string | null = null;

test.afterEach(async ({ request }) => {
	if (!createdId) return;
	const id = createdId;
	createdId = null;
	const token = await signInViaApi(request, ADMIN_EMAIL, ADMIN_PASSWORD).catch(() => null);
	if (!token) return;
	await deleteModelViaAPI(request, token, id);
	await waitForModelDeletedViaAPI(request, token, id);
});

test.describe('custom model CRUD', () => {
	test.beforeEach(() => {
		test.setTimeout(180_000);
	});

	test('lists and deletes a custom model', async ({ page, request }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const token = await getAuthToken(page);
		const id = uniqueId('e2e-crud');
		const name = `E2E CRUD ${id}`;
		createdId = id;

		await createModelViaAPI(request, token, { id, name });
		await waitForModelViaAPI(request, token, id, { name });

		await test.step('list model card', async () => {
			const card = await waitForModelCardInWorkspace(page, id, token);
			await dismissModals(page);
			await expect(card).toContainText(name);
		});

		await test.step('delete model through UI', async () => {
			await dismissModals(page);
			const card = page.locator(`#model-item-${id}`);
			await card.getByRole('button').first().click({ force: true });
			await page.getByText('Delete').click({ force: true });
			await page.getByRole('button', { name: /confirm|delete/i }).click({ force: true });
			await expect(page.getByText(`Deleted ${id}`)).toBeVisible();
			await waitForModelDeletedViaAPI(page.request, token, id);
			await page.goto(`/workspace/models?e2e_refresh=${Date.now()}`);
			await expect(card).toHaveCount(0);
		});

		createdId = null;
	});
});
