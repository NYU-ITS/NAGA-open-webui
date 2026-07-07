import { expect, test } from '@playwright/test';
import { bootstrapAdmin, dismissModals, getAuthToken, loginAsAdmin } from '../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId } from '../fixtures/models';

test.describe('custom model CRUD', () => {
  test('lists and deletes a custom model', async ({ page, request }) => {
    await bootstrapAdmin(request);
    await loginAsAdmin(page);
    const token = await getAuthToken(page);
    const id = uniqueId('e2e-crud');
    const name = `E2E CRUD ${id}`;

    await createModelViaAPI(request, token, { id, name });

    await test.step('list model card', async () => {
      await page.goto('/workspace/models');
      await dismissModals(page);
      await expect(page.locator(`#model-item-${id}`)).toBeVisible();
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

    await deleteModelViaAPI(request, token, id);
  });
});
