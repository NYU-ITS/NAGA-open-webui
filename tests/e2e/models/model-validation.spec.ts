import { expect, test } from '@playwright/test';
import { bootstrapAdmin, dismissModals, getAuthToken, loginAsAdmin } from '../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId } from '../fixtures/models';

test.describe('custom model validation UX', () => {
  test('blocks submission when name is empty', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    await page.goto('/workspace/models/create');
    await dismissModals(page);
    await page.locator('form').evaluate((form) => form.requestSubmit());
    await expect(page).toHaveURL(/\/workspace\/models\/create/);
  });

  test('shows duplicate id error without redirecting', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-dupe');
    await createModelViaAPI(request, token, { id, name: `Existing ${id}` });

    await page.goto('/workspace/models/create');
    await dismissModals(page);
    await page.getByPlaceholder('Model Name').fill(`Duplicate ${id}`);
    await page.getByPlaceholder('Model ID').fill(id);
    await page.locator('form').evaluate((form) => form.requestSubmit());
    await expect(page).toHaveURL(/\/workspace\/models\/create/);

    await deleteModelViaAPI(request, token, id);
  });

  test('base model field prevents submission when empty', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    const id = uniqueId('e2e-no-base');
    await page.goto('/workspace/models/create');
    await dismissModals(page);
    await page.getByPlaceholder('Model Name').fill(`No Base ${id}`);
    await page.getByPlaceholder('Add a short description about what this model does').fill('No base selected');
    await page.locator('form').evaluate((form) => form.requestSubmit());
    await expect(page).toHaveURL(/\/workspace\/models\/create/);
  });
});
