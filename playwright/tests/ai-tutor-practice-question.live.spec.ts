/// <reference types="node" />

import { expect, test, type Page } from '@playwright/test';
import { dismissWhatsNewIfShown, getLiveGroup, liveEnabled, loginAsAdmin } from './live-test-utils';

async function waitForPracticeGenerationFinished(page: Page) {
	const successToast = page
		.locator('[data-sonner-toast][data-type="success"]')
		.filter({ hasText: /Practice question set generated/i });
	const errorToast = page
		.locator('[data-sonner-toast][data-type="error"]')
		.filter({ hasText: /Practice generation|Pipeline status|failed|error/i });
	const readyStatus = page.getByText(/Ready for review|Approved/i);

	const deadline = Date.now() + 180_000;
	while (Date.now() < deadline) {
		if (
			await successToast
				.first()
				.isVisible()
				.catch(() => false)
		)
			return;
		if (
			await readyStatus
				.first()
				.isVisible()
				.catch(() => false)
		)
			return;
		if (
			await errorToast
				.first()
				.isVisible()
				.catch(() => false)
		) {
			throw new Error((await errorToast.first().textContent()) ?? 'Practice generation failed.');
		}
		await page.waitForTimeout(500);
	}

	throw new Error('Timed out waiting for practice question generation to finish.');
}

test.describe('AI Tutor practice question live workflow', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

	test('generates, approves, and sends practice questions when the group is ready', async ({
		page
	}) => {
		test.setTimeout(240_000);
		const { token } = await loginAsAdmin(page);
		const group = await getLiveGroup(page, token);

		await page.addInitScript((groupId) => {
			localStorage.setItem('ai_tutor_last_selected_group_id', groupId);
		}, group.id);

		await page.goto(
			`/aitutordashboard/topicanalysis/reviewquestionset?group_id=${encodeURIComponent(group.id)}`
		);
		await dismissWhatsNewIfShown(page);

		await expect(page.getByRole('heading', { name: 'Practice Question Workflow' })).toBeVisible({
			timeout: 20_000
		});

		const loading = page.getByText(/Loading practice question sets|Loading group selection/i);
		await loading.waitFor({ state: 'hidden', timeout: 45_000 }).catch(() => {});

		const emptyMessage = page.getByText(
			/No homework uploaded for this group yet|No practice question sets are available yet|No practice questions has been generated yet/
		);
		const exactGenerateButtons = page.getByRole('button', { name: /^Generate$/ });
		const approveButton = page.getByRole('button', { name: /^Approve$/ });

		if ((await exactGenerateButtons.count()) > 0) {
			await exactGenerateButtons.first().click();
			await waitForPracticeGenerationFinished(page);
			await expect(page.getByText('No practice questions has been generated yet')).toBeHidden({
				timeout: 30_000
			});
		} else if (
			await emptyMessage
				.first()
				.isVisible()
				.catch(() => false)
		) {
			test.skip(
				true,
				'No ready homework analysis exists for practice generation in this live environment.'
			);
		}

		await expect(approveButton.or(page.getByRole('button', { name: /^Approved$/ }))).toBeVisible({
			timeout: 30_000
		});

		if (await approveButton.isEnabled().catch(() => false)) {
			await approveButton.click();
			await expect(page.getByRole('button', { name: /^Approved$/ })).toBeVisible({
				timeout: 30_000
			});
		}

		const sendButton = page.getByRole('button', { name: /^Send$/ });
		const sentButton = page.getByRole('button', { name: /^Sent$/ });

		if (await sendButton.isEnabled().catch(() => false)) {
			await sendButton.click();
			await expect(page.getByRole('button', { name: /^Sent$/ })).toBeVisible({ timeout: 30_000 });
		} else {
			await expect(sentButton).toBeVisible({ timeout: 10_000 });
		}
	});
});
