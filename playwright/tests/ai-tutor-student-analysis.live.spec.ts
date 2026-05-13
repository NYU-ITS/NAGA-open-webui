/// <reference types="node" />

import { expect, test } from '@playwright/test';
import {
	dismissWhatsNewIfShown,
	liveEnabled,
	loginAsAdmin,
	openSidebarIfNeeded
} from './live-test-utils';

test.describe('AI Tutor student analysis live workflow', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

	test('downloads a student report when available', async ({ page }) => {
		test.setTimeout(90_000);
		await loginAsAdmin(page);

		await page.goto('/');
		await dismissWhatsNewIfShown(page);
		const dashboardLink = await openSidebarIfNeeded(page, 'AI Tutor Dashboard - Instructor');
		await dashboardLink.click();
		await page.getByRole('link', { name: 'Student Analysis' }).click();
		await dismissWhatsNewIfShown(page);

		await expect(page.getByRole('heading', { name: 'Student Analysis' })).toBeVisible({
			timeout: 15_000
		});

		const loading = page.getByText(/Loading group selection|Loading student analysis/i);
		await loading.waitFor({ state: 'hidden', timeout: 30_000 }).catch(() => {});

		const noStudentsMessage = page.getByText(
			/No student analysis is available|No group members are available/
		);
		test.skip(
			await noStudentsMessage.isVisible().catch(() => false),
			'No student analysis or group members are available in this live environment.'
		);

		const downloadButtons = page.getByRole('button', { name: 'Download Report' });
		const downloadButtonCount = await downloadButtons.count();
		test.skip(
			downloadButtonCount === 0,
			'No downloadable student reports are available in this live environment.'
		);

		const [download] = await Promise.all([
			page.waitForEvent('download'),
			downloadButtons.first().click()
		]);

		expect(download.suggestedFilename()).toMatch(/\.pdf$/i);
	});
});
