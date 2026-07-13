import { expect, test } from '@playwright/test';
import { loginViaApi, dismissModals, getAuthToken, signInViaApi, ADMIN_EMAIL, ADMIN_PASSWORD } from '../../fixtures/auth';
import { cleanupTestModelsViaAPI, createModelViaAPI, deleteModelViaAPI, generateModelPayload, uniqueId, waitForModelViaAPI, waitForModelCardInWorkspace } from '../../fixtures/models';

test.skip(process.env.PLAYWRIGHT_RUN_LIVE !== '1', 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

let createdId: string | null = null;

test.afterEach(async ({ request }) => {
	if (!createdId) return;
	const id = createdId;
	createdId = null;
	const token = await signInViaApi(request, ADMIN_EMAIL, ADMIN_PASSWORD).catch(() => null);
	if (!token) return;
	await deleteModelViaAPI(request, token, id).catch(() => {});
});

test.describe('custom model import and export', () => {
	test.beforeEach(() => {
		test.setTimeout(180_000);
	});

	test('exports all models from list page', async ({ page }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		await page.goto('/workspace/models');
		await dismissModals(page);
		const downloadPromise = page.waitForEvent('download');
		await page.getByRole('button', { name: 'Export Models' }).click({ force: true });
		const download = await downloadPromise;
		expect(download.suggestedFilename()).toMatch(/^models-export-\d+\.json$/);
	});

	test('exports a single model from card menu', async ({ page, request }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const token = await getAuthToken(page);
		await cleanupTestModelsViaAPI(request, token);
		const id = uniqueId('e2e-export-one');
		createdId = id;
		await createModelViaAPI(request, token, { id, name: `Export One ${id}` });
		await waitForModelViaAPI(request, token, id, { name: `Export One ${id}` });

		const card = await waitForModelCardInWorkspace(page, id, token);
		await dismissModals(page);
		await card.getByRole('button').first().click({ force: true });
		const downloadPromise = page.waitForEvent('download');
		await page.getByRole('menuitem', { name: 'Export' }).click({ force: true });
		const download = await downloadPromise;
		expect(download.suggestedFilename()).toMatch(new RegExp(`^${id}-\\d+\\.json$`));
	});

	test('imports valid JSON as new model', async ({ page, request }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const token = await getAuthToken(page);
		await cleanupTestModelsViaAPI(request, token);
		const id = uniqueId('e2e-import-new');
		createdId = id;
		const payload = generateModelPayload({ id, name: `Imported ${id}` });

		await page.goto('/workspace/models');
		await dismissModals(page);

		await page.locator('#models-import-input').setInputFiles({
			name: 'models-import-new.json',
			mimeType: 'application/json',
			buffer: Buffer.from(JSON.stringify([{ id, info: payload }]))
		});
		await waitForModelViaAPI(page.request, token, id, { name: `Imported ${id}` });
		await waitForModelCardInWorkspace(page, id, token);
	});

	test('imports existing id as update instead of duplicate', async ({ page, request }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		const token = await getAuthToken(page);
		await cleanupTestModelsViaAPI(request, token);
		const id = uniqueId('e2e-import-update');
		createdId = id;
		await createModelViaAPI(request, token, { id, name: `Before ${id}` });
		await waitForModelViaAPI(request, token, id, { name: `Before ${id}` });

		const payload = generateModelPayload({
			id,
			name: `After ${id}`,
			meta: {
				profile_image_url: '/static/favicon.png',
				description: `Updated by import ${id}`,
				suggestion_prompts: null,
				tags: [],
				capabilities: { vision: true, citations: true }
			}
		});

		await page.goto('/workspace/models');
		await dismissModals(page);

		await page.locator('#models-import-input').setInputFiles({
			name: 'models-import-update.json',
			mimeType: 'application/json',
			buffer: Buffer.from(JSON.stringify([{ id, info: payload }]))
		});
		await waitForModelViaAPI(page.request, token, id, { name: `After ${id}` });
		const card = await waitForModelCardInWorkspace(page, id, token);

		await expect(card).toContainText(`After ${id}`, { timeout: 15_000 });
		await expect(page.locator(`#model-item-${id}`)).toHaveCount(1);
	});

	test('skips entries missing model.info safely', async ({ page }) => {
		await loginViaApi(page, ADMIN_EMAIL, ADMIN_PASSWORD);
		await page.goto('/workspace/models');
		await dismissModals(page);
		await page.locator('#models-import-input').setInputFiles({
			name: 'models-import-skip.json',
			mimeType: 'application/json',
			buffer: Buffer.from(JSON.stringify([{ id: uniqueId('e2e-skip') }]))
		});
		await expect(page.getByText(/SyntaxError|TypeError|Unhandled/i)).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Export Models' })).toBeVisible({ timeout: 15_000 });
	});
});
