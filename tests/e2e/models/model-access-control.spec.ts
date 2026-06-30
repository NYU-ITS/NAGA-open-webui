import { expect, test } from '@playwright/test';
import { bootstrapAdmin, dismissModals, getAuthToken, loginAsAdmin, loginAsUser } from '../fixtures/auth';
import { createModelViaAPI, deleteModelViaAPI, uniqueId } from '../fixtures/models';

const USER_EMAIL = process.env.E2E_USER_EMAIL || 'e2e-user@example.test';
const USER_PASSWORD = process.env.E2E_USER_PASSWORD || 'changeme-e2e-user';

async function ensureTestUser(request: import('@playwright/test').APIRequestContext): Promise<string | null> {
  const signinRes = await request.post('/api/v1/auths/signin', {
    data: { email: process.env.E2E_ADMIN_EMAIL || 'admin@test.com', password: process.env.E2E_ADMIN_PASSWORD || 'changeme-e2e-admin' }
  });
  if (!signinRes.ok()) return null;
  const { token: adminToken } = await signinRes.json();

  const res = await request.post('/api/v1/auths/add', {
    headers: { authorization: `Bearer ${adminToken}`, 'content-type': 'application/json' },
    data: { name: 'E2E User', email: USER_EMAIL, password: USER_PASSWORD, role: 'admin' }
  });
  if (res.ok()) return (await res.json()).token;

  const text = await res.text();
  if (text.includes('already exists') || text.includes('taken')) {
    const userSignin = await request.post('/api/v1/auths/signin', {
      data: { email: USER_EMAIL, password: USER_PASSWORD }
    });
    if (userSignin.ok()) return (await userSignin.json()).token;
  }
  return null;
}

test.describe('custom model access control visibility', () => {
  test('private admin-created model is hidden from regular user', async ({ browser, page, request }) => {
    await bootstrapAdmin(request);
    await ensureTestUser(request);
    await loginAsAdmin(page);
    const adminToken = await getAuthToken(page);
    const id = uniqueId('e2e-private');
    await createModelViaAPI(request, adminToken, { id, name: `Private ${id}` });

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await loginAsUser(userPage);
    await userPage.goto('/workspace/models');
    await dismissModals(userPage);
    await expect(userPage.locator(`#model-item-${id}`)).toHaveCount(0);

    await userContext.close();
    await deleteModelViaAPI(request, adminToken, id);
  });

  test('regular user without write access cannot edit', async ({ browser, page, request }) => {
    await bootstrapAdmin(request);
    await ensureTestUser(request);
    await loginAsAdmin(page);
    const adminToken = await getAuthToken(page);
    const id = uniqueId('e2e-no-write');
    await createModelViaAPI(request, adminToken, { id, name: `No Write ${id}` });

    const userContext = await browser.newContext();
    const userPage = await userContext.newPage();
    await loginAsUser(userPage);
    await userPage.goto('/workspace/models');
    await dismissModals(userPage);
    await expect(userPage.locator(`#model-item-${id}`)).toHaveCount(0);
    await userPage.goto(`/workspace/models/edit?id=${encodeURIComponent(id)}`);
    await expect(userPage).toHaveURL(/\/workspace\/models/);
    await expect(userPage.getByRole('button', { name: 'Save & Update' })).toHaveCount(0);

    await userContext.close();
    await deleteModelViaAPI(request, adminToken, id);
  });
});
