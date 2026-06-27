import { expect, test } from '@playwright/test';
import { getAuthToken, loginAsAdmin } from '../fixtures/auth';
import { deleteModelViaAPI, uniqueId } from '../fixtures/models';

test.describe('custom model CRUD', () => {
  test('creates, lists, edits, and deletes a custom model', async ({ page, request }) => {
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-crud');
    const name = `E2E CRUD ${id}`;
    const updatedDescription = `Updated description ${id}`;

    await test.step('create model through UI', async () => {
      await page.goto('/workspace/models/create');
      await expect(page.getByPlaceholder('Model Name')).toBeVisible();
      await page.getByPlaceholder('Model Name').fill(name);
      await expect(page.getByPlaceholder('Model ID')).toHaveValue(id);
      await page.getByPlaceholder('Select a base model').fill('gpt-4o-mini');
      await page.keyboard.press('Enter');
      await page.getByPlaceholder('Add a short description about what this model does').fill(`Initial description ${id}`);
      await page.getByPlaceholder(/Write your model system prompt content here/).fill(`System prompt ${id}`);
      await page.getByRole('button', { name: 'Save & Create' }).click();
      await expect(page.getByText('Model created successfully!')).toBeVisible();
      await expect(page).toHaveURL(/\/workspace\/models$/);
    });

    await test.step('list model card', async () => {
      await expect(page.locator(`#model-item-${id}`)).toBeVisible();
      await expect(page.locator(`#model-item-${id}`)).toContainText(name);
    });

    await test.step('edit model through UI', async () => {
      await page.goto(`/workspace/models/edit?id=${encodeURIComponent(id)}`);
      await expect(page.getByPlaceholder('Model Name')).toHaveValue(name);
      await page.getByPlaceholder('Add a short description about what this model does').fill(updatedDescription);
      await page.getByRole('button', { name: 'Save & Update' }).click();
      await expect(page.getByText('Model updated successfully')).toBeVisible();
      await expect(page).toHaveURL(/\/workspace\/models$/);
    });

    await test.step('verify update then delete', async () => {
      const card = page.locator(`#model-item-${id}`);
      await expect(card).toContainText(updatedDescription);
      await card.getByRole('button').first().click();
      await page.getByText('Delete').click();
      await page.getByRole('button', { name: /confirm|delete/i }).click();
      await expect(page.getByText(`Deleted ${id}`)).toBeVisible();
      await expect(card).toHaveCount(0);
    });

    await deleteModelViaAPI(request, token, id);
  });
});
