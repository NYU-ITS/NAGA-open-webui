import { expect, test } from '@playwright/test';
import { loginViaApi, dismissModals, getAuthToken, signInViaApi, ADMIN_EMAIL, ADMIN_PASSWORD } from '../../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId, waitForModelViaAPI, attachModelPageDiagnostics } from '../../fixtures/models';

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

test.describe('custom model CRUD', () => {
	test('lists and deletes a custom model', async ({ page, request }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const token = await getAuthToken(page);
		const id = uniqueId('e2e-crud');
		const name = `E2E CRUD ${id}`;
		createdIds.push(id);

		await createModelViaAPI(request, token, { id, name });
		await waitForModelViaAPI(request, token, id);
		await page.reload();

		await test.step('list model card', async () => {
			await page.goto('/workspace/models');
			await dismissModals(page);
			await attachModelPageDiagnostics(page, id, token);
			await expect(page.locator(`#model-item-${id}`)).toBeVisible({ timeout: 15_000 });
			await expect(page.locator(`#model-item-${id}`)).toContainText(name);
		});

		await test.step('delete model through UI', async () => {
			await dismissModals(page);
			const card = page.locator(`#model-item-${id}`);
			await card.getByRole('button').first().click({ force: true });
			await page.getByText('Delete').click({ force: true });
			await page.getByRole('button', { name: /confirm|delete/i }).click({ force: true });
			await expect(page.getByText(`Deleted ${id}`)).toBeVisible();
			await expect(card).toHaveCount(0);
		});

		createdIds.splice(createdIds.indexOf(id), 1);
	});
});
