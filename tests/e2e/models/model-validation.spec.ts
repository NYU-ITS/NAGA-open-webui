import { expect, test } from '@playwright/test';
import { getAuthToken, loginAsAdmin } from '../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId } from '../fixtures/models';

test.describe('custom model validation UX', () => {
  test('blocks blank name and stays on create page', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/workspace/models/create');
    await page.getByRole('button', { name: 'Save & Create' }).click();
    await expect(page.getByText('Model Name is required.')).toBeVisible();
    await expect(page).toHaveURL(/\/workspace\/models\/create/);
  });

  test('blocks blank id and stays on create page', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/workspace/models/create');
    await page.getByPlaceholder('Model Name').fill('E2E Blank Id');
    await page.getByPlaceholder('Model ID').fill('');
    await page.getByRole('button', { name: 'Save & Create' }).click();
    await expect(page.getByText(/Model ID is required|Model ID cannot be empty/)).toBeVisible();
    await expect(page).toHaveURL(/\/workspace\/models\/create/);
  });

  test('shows duplicate id error without redirecting', async ({ page, request }) => {
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-dupe');
    await createModelViaAPI(request, token, { id, name: `Existing ${id}` });

    await page.goto('/workspace/models/create');
    await page.getByPlaceholder('Model Name').fill(`Duplicate ${id}`);
    await page.getByPlaceholder('Model ID').fill(id);
    await page.getByRole('button', { name: 'Save & Create' }).click();
    await expect(page.getByText(new RegExp(`A model with the ID '${id}' already exists`))).toBeVisible();
    await expect(page).toHaveURL(/\/workspace\/models\/create/);

    await deleteModelViaAPI(request, token, id);
  });

  test('base model field remains required for usable creation', async ({ page }) => {
    await loginAsAdmin(page);
    const id = uniqueId('e2e-no-base');
    await page.goto('/workspace/models/create');
    await page.getByPlaceholder('Model Name').fill(`No Base ${id}`);
    await page.getByPlaceholder('Add a short description about what this model does').fill('No base selected');
    await page.getByRole('button', { name: 'Save & Create' }).click();
    await expect(page).toHaveURL(/\/workspace\/models\/create/);
    await expect(page.getByText(/base model|required|error/i)).toBeVisible();
  });
});
