import { expect, test } from '@playwright/test';
import { bootstrapAdmin, dismissModals, getAuthToken, loginAsAdmin } from '../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, generateModelPayload, uniqueId } from '../fixtures/models';

test.describe('custom model import and export', () => {
  test('exports all models from list page', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    await page.goto('/workspace/models');
    await dismissModals(page);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export Models' }).click({ force: true });
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^models-export-\d+\.json$/);
  });

  test('exports a single model from card menu', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-export-one');
    await createModelViaAPI(request, token, { id, name: `Export One ${id}` });

    await page.goto('/workspace/models');
    await dismissModals(page);
    const card = page.locator(`#model-item-${id}`);
    await expect(card).toBeVisible();
    await card.getByRole('button').first().click({ force: true });
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('menuitem', { name: 'Export' }).click({ force: true });
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(new RegExp(`^${id}-\\d+\\.json$`));

    await deleteModelViaAPI(request, token, id);
  });

  test('imports valid JSON as new model', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-import-new');
    const payload = generateModelPayload({ id, name: `Imported ${id}` });

    await page.goto('/workspace/models');
    await dismissModals(page);
    await page.getByRole('button', { name: 'Import Models' }).click({ force: true });
    await page.locator('#models-import-input').setInputFiles({
      name: 'models-import-new.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify([{ id, info: payload }]))
    });

    await expect(page.locator(`#model-item-${id}`)).toBeVisible();
    await deleteModelViaAPI(request, token, id);
  });

  test('imports existing id as update instead of duplicate', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-import-update');
    await createModelViaAPI(request, token, { id, name: `Before ${id}` });
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
    await page.getByRole('button', { name: 'Import Models' }).click({ force: true });
    await page.locator('#models-import-input').setInputFiles({
      name: 'models-import-update.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify([{ id, info: payload }]))
    });

    await expect(page.locator(`#model-item-${id}`)).toContainText(`After ${id}`);
    await expect(page.locator(`#model-item-${id}`)).toHaveCount(1);
    await deleteModelViaAPI(request, token, id);
  });

  test('skips entries missing model.info safely', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    await page.goto('/workspace/models');
    await dismissModals(page);
    await page.getByRole('button', { name: 'Import Models' }).click({ force: true });
    await page.locator('#models-import-input').setInputFiles({
      name: 'models-import-skip.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify([{ id: uniqueId('e2e-skip') }]))
    });
    await expect(page.getByText(/SyntaxError|TypeError|Unhandled/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Export Models' })).toBeVisible();
  });
});
