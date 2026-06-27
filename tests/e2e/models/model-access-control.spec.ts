import { expect, test } from '@playwright/test';
import { getAuthToken, loginAsAdmin, loginAsUser } from '../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId } from '../fixtures/models';
import { createGroupViaAPI, deleteGroupViaAPI, getCurrentUser } from '../fixtures/users';

test.describe('custom model access control visibility', () => {
  test('private admin-created model is hidden from regular user', async ({ browser, page, request }) => {
    await loginAsAdmin(page);
    const adminToken = await getAuthToken(page);
    const id = uniqueId('e2e-private');
    await createModelViaAPI(request, adminToken, { id, name: `Private ${id}` });

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await loginAsUser(userPage);
    await userPage.goto('/workspace/models');
    await expect(userPage.locator(`#model-item-${id}`)).toHaveCount(0);

    await userContext.close();
    await deleteModelViaAPI(request, adminToken, id);
  });

  test('group-shared model is visible to group member', async ({ browser, page, request }) => {
    await loginAsAdmin(page);
    const adminToken = await getAuthToken(page);

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await loginAsUser(userPage);
    const userToken = await getAuthToken(userPage);
    const user = await getCurrentUser(request, userToken);

    const group = await createGroupViaAPI(request, adminToken, uniqueId('e2e-group'), [user.id]);
    const id = uniqueId('e2e-group-model');
    await createModelViaAPI(request, adminToken, {
      id,
      name: `Group Visible ${id}`,
      access_control: {
        read: { group_ids: [group.id], user_ids: [] },
        write: { group_ids: [], user_ids: [] }
      }
    });

    await userPage.goto('/workspace/models');
    await expect(userPage.locator(`#model-item-${id}`)).toBeVisible();

    await userContext.close();
    await deleteModelViaAPI(request, adminToken, id);
    await deleteGroupViaAPI(request, adminToken, group.id);
  });

  test('regular user without write access cannot edit', async ({ browser, page, request }) => {
    await loginAsAdmin(page);
    const adminToken = await getAuthToken(page);
    const id = uniqueId('e2e-no-write');
    await createModelViaAPI(request, adminToken, { id, name: `No Write ${id}` });

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await loginAsUser(userPage);
    await userPage.goto('/workspace/models');
    await expect(userPage.locator(`#model-item-${id}`)).toHaveCount(0);
    await userPage.goto(`/workspace/models/edit?id=${encodeURIComponent(id)}`);
    await expect(userPage).toHaveURL(/\/workspace\/models/);
    await expect(userPage.getByRole('button', { name: 'Save & Update' })).toHaveCount(0);

    await userContext.close();
    await deleteModelViaAPI(request, adminToken, id);
  });

  test('admin sees admin and regular-user models', async ({ browser, page, request }) => {
    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await loginAsUser(userPage);
    const userToken = await getAuthToken(userPage);
    const userModelId = uniqueId('e2e-user-owned');
    await createModelViaAPI(request, userToken, { id: userModelId, name: `User Owned ${userModelId}` });

    await loginAsAdmin(page);
    const adminToken = await getAuthToken(page);
    const adminModelId = uniqueId('e2e-admin-owned');
    await createModelViaAPI(request, adminToken, { id: adminModelId, name: `Admin Owned ${adminModelId}` });

    await page.goto('/workspace/models');
    await expect(page.locator(`#model-item-${adminModelId}`)).toBeVisible();
    await expect(page.locator(`#model-item-${userModelId}`)).toBeVisible();

    await userContext.close();
    await deleteModelViaAPI(request, adminToken, adminModelId);
    await deleteModelViaAPI(request, adminToken, userModelId);
  });
});
