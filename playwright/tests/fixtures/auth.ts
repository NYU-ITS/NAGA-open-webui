import { APIRequestContext, Page, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const authDir = path.resolve('playwright/tests/.auth');
const userStatePath = path.join(authDir, 'user.json');
const adminStatePath = path.join(authDir, 'admin.json');

function isLiveMode(): boolean {
  if (process.env.PLAYWRIGHT_RUN_LIVE === '1') return true;
  const baseUrl = process.env.PLAYWRIGHT_BASE_URL || '';
  if (!baseUrl) return false;
  try {
    const host = new URL(baseUrl).hostname;
    return host !== 'localhost' && host !== '127.0.0.1';
  } catch {
    return false;
  }
}

const live = isLiveMode();

if (live) {
  const missing = [
    ['PLAYWRIGHT_ADMIN_EMAIL', process.env.PLAYWRIGHT_ADMIN_EMAIL],
    ['PLAYWRIGHT_ADMIN_PASSWORD', process.env.PLAYWRIGHT_ADMIN_PASSWORD],
    ['PLAYWRIGHT_STUDENT_EMAIL', process.env.PLAYWRIGHT_STUDENT_EMAIL],
    ['PLAYWRIGHT_STUDENT_PASSWORD', process.env.PLAYWRIGHT_STUDENT_PASSWORD],
  ].filter(([, val]) => !val).map(([name]) => name);

  if (missing.length > 0) {
    throw new Error(
      `Live mode requires credential env vars (no fallbacks allowed). Missing: ${missing.join(', ')}`
    );
  }
}

export const ADMIN_EMAIL = live
  ? process.env.PLAYWRIGHT_ADMIN_EMAIL!
  : process.env.PLAYWRIGHT_ADMIN_EMAIL || 'admin@test.com';
export const ADMIN_PASSWORD = live
  ? process.env.PLAYWRIGHT_ADMIN_PASSWORD!
  : process.env.PLAYWRIGHT_ADMIN_PASSWORD || 'changeme-e2e-admin';
export const USER_EMAIL = live
  ? process.env.PLAYWRIGHT_STUDENT_EMAIL!
  : process.env.PLAYWRIGHT_STUDENT_EMAIL || 'e2e-user@example.test';
export const USER_PASSWORD = live
  ? process.env.PLAYWRIGHT_STUDENT_PASSWORD!
  : process.env.PLAYWRIGHT_STUDENT_PASSWORD || 'changeme-e2e-user';

export async function bootstrapAdmin(request: APIRequestContext) {
  if (live) return;
  const res = await request.post('/api/v1/auths/signup', {
    data: {
      name: 'E2E Admin',
      email: ADMIN_EMAIL,
      password: ADMIN_PASSWORD,
      profile_image_url: '/static/favicon.png'
    }
  });
  if (!res.ok()) {
    const text = await res.text();
    if (text.includes('already exists') || res.status() === 403) {
      return;
    }
    throw new Error(`Admin signup failed: ${res.status()} ${text}`);
  }
}

export async function loginAsAdmin(page: Page) {
  await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
  await fs.mkdir(authDir, { recursive: true });
  await page.context().storageState({ path: adminStatePath });
}

export async function loginAsUser(page: Page) {
  await login(page, USER_EMAIL, USER_PASSWORD);
  await fs.mkdir(authDir, { recursive: true });
  await page.context().storageState({ path: userStatePath });
}

export async function login(page: Page, email: string, password: string) {
  await page.goto('/auth');

  const signupBtn = page.locator('button[type="submit"]:has-text("Create")');
  const signinBtn = page.locator('button[type="submit"]:has-text("Sign in")');

  const isSignup = await signupBtn.isVisible({ timeout: 3000 }).catch(() => false);

  if (isSignup) {
    const nameInput = page.getByPlaceholder(/name/i);
    if (await nameInput.isVisible({ timeout: 1000 }).catch(() => false)) {
      await nameInput.fill('E2E Admin');
    }
    await page.getByPlaceholder(/email/i).fill(email);
    await page.getByPlaceholder(/password/i).fill(password);
    await signupBtn.evaluate((btn) => (btn as HTMLButtonElement).click());
  } else {
    await page.getByPlaceholder(/email/i).fill(email);
    await page.getByPlaceholder(/password/i).fill(password);
    await signinBtn.evaluate((btn) => (btn as HTMLButtonElement).click());
  }

  await expect(page).not.toHaveURL(/\/auth/);
  await expect.poll(async () => await page.evaluate(() => localStorage.getItem('token'))).toBeTruthy();

  // Dismiss any overlay modals (changelog, release notes, etc.)
  await dismissModals(page);
}

export async function dismissModals(page: Page) {
  const modal = page.locator('.modal.fixed');
  for (let i = 0; i < 5; i++) {
    if (!(await modal.isVisible({ timeout: 1000 }).catch(() => false))) break;
    // Try clicking a close button first
    const closeBtn = modal.locator('button:has-text("Close"), button:has-text("Dismiss"), button:has-text("Got it"), button:has-text("OK"), button[aria-label="Close"]');
    if (await closeBtn.first().isVisible({ timeout: 500 }).catch(() => false)) {
      await closeBtn.first().evaluate((btn) => (btn as HTMLButtonElement).click());
    } else {
      // Click the backdrop to dismiss
      await page.evaluate(() => {
        document.querySelectorAll('.modal.fixed').forEach((m) => m.remove());
      });
    }
    await page.waitForTimeout(500);
  }
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
