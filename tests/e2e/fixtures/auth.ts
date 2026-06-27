import { APIRequestContext, Page, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const authDir = path.resolve('tests/e2e/.auth');
const userStatePath = path.join(authDir, 'user.json');
const adminStatePath = path.join(authDir, 'admin.json');

export async function loginAsAdmin(page: Page) {
  await login(page, process.env.E2E_ADMIN_EMAIL || 'admin@test.com', process.env.E2E_ADMIN_PASSWORD || 'changeme-e2e-admin');
  await fs.mkdir(authDir, { recursive: true });
  await page.context().storageState({ path: adminStatePath });
}

export async function loginAsUser(page: Page) {
  await login(page, process.env.E2E_USER_EMAIL || 'e2e-user@example.test', process.env.E2E_USER_PASSWORD || 'changeme-e2e-user');
  await fs.mkdir(authDir, { recursive: true });
  await page.context().storageState({ path: userStatePath });
}

export async function login(page: Page, email: string, password: string) {
  await page.goto('/auth');
  await page.getByPlaceholder(/email/i).fill(email);
  await page.getByPlaceholder(/password/i).fill(password);
  await page.getByRole('button', { name: /sign in|log in/i }).click();
  await expect(page).not.toHaveURL(/\/auth/);
  await expect.poll(async () => await page.evaluate(() => localStorage.getItem('token'))).toBeTruthy();
}

export async function getAuthToken(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem('token'));
  if (!token) throw new Error('Missing localStorage token after login');
  return token;
}

export async function authHeaders(token: string) {
  return {
    authorization: `Bearer ${token}`,
    accept: 'application/json',
    'content-type': 'application/json'
  };
}

export async function requireOk(response: Awaited<ReturnType<APIRequestContext['get']>>, label: string) {
  if (!response.ok()) {
    throw new Error(`${label} failed: ${response.status()} ${await response.text()}`);
  }
  return response;
}
