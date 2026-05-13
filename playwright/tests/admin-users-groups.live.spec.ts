/// <reference types="node" />

import { expect, test, type Page } from '@playwright/test';
import {
	deleteGroupByName,
	deleteUsersByEmail,
	liveEnabled,
	loginAsAdmin,
	uniqueLiveName
} from './live-test-utils';

async function latestModal(page: Page) {
	await expect(page.locator('.modal')).toHaveCount(1, { timeout: 10_000 });
	return page.locator('.modal').last();
}

async function addUserViaModal(
	page: Page,
	input: { name: string; email: string; password: string }
) {
	await page.getByRole('button', { name: 'Add User' }).click();
	const modal = await latestModal(page);

	await expect(modal.getByText('Add User')).toBeVisible();
	await modal.getByRole('combobox').selectOption('user');
	await modal.getByPlaceholder('Enter Your Full Name').fill(input.name);
	await modal.getByPlaceholder('Enter Your Email').fill(input.email);
	await modal.getByPlaceholder('Enter Your Password').fill(input.password);
	await modal.getByRole('button', { name: 'Save' }).click();

	await expect(page.locator('.modal')).toHaveCount(0, { timeout: 15_000 });
	await expect(page.getByText(input.email)).toBeVisible({ timeout: 15_000 });
}

test.describe('Admin users and groups live workflow', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

	test('creates two users, creates a group, and assigns both users to it', async ({
		page
	}, testInfo) => {
		test.setTimeout(90_000);
		const { token } = await loginAsAdmin(page);
		const suffix = uniqueLiveName('pw-live-admin-users-groups', testInfo.workerIndex);
		const emailDomain = process.env.PLAYWRIGHT_LIVE_EMAIL_DOMAIN ?? 'nyu.edu';
		const firstUser = {
			name: `${suffix} student 1`,
			email: `${suffix}.student1@${emailDomain}`,
			password: process.env.PLAYWRIGHT_LIVE_CREATED_USER_PASSWORD ?? 'password'
		};
		const secondUser = {
			name: `${suffix} student 2`,
			email: `${suffix}.student2@${emailDomain}`,
			password: process.env.PLAYWRIGHT_LIVE_CREATED_USER_PASSWORD ?? 'password'
		};
		const groupName = `${suffix} group`;

		try {
			await page.goto('/admin/users');
			await expect(page.getByRole('button', { name: 'Add User' })).toBeVisible({ timeout: 15_000 });

			await addUserViaModal(page, firstUser);
			await addUserViaModal(page, secondUser);

			await page.getByRole('button', { name: 'Groups' }).click();

			await page.getByRole('button', { name: 'Create Group' }).first().click();
			{
				const modal = await latestModal(page);
				await expect(modal.getByText('Add User Group')).toBeVisible();
				await modal.getByPlaceholder('Group Name').fill(groupName);
				await modal.getByPlaceholder('Group Description').fill(groupName);
				await modal.getByRole('button', { name: 'Create' }).click();
			}

			await expect(page.locator('.modal')).toHaveCount(0, { timeout: 15_000 });
			await expect(page.getByText(groupName)).toBeVisible({ timeout: 15_000 });

			await page.locator('button', { hasText: groupName }).first().click();
			{
				const modal = await latestModal(page);
				await expect(modal.getByText('Edit User Group')).toBeVisible();
				await modal.getByRole('button', { name: /Users \(\d+\)/ }).click();

				const searchInput = modal.getByPlaceholder('Search');

				await searchInput.fill(firstUser.email);
				const firstUserRow = modal
					.locator('div.flex.flex-row.items-center.gap-3.w-full.text-sm')
					.first();
				await expect(firstUserRow.getByText(firstUser.name)).toBeVisible();
				await firstUserRow.getByRole('button').first().click();

				await searchInput.fill(secondUser.email);
				const secondUserRow = modal
					.locator('div.flex.flex-row.items-center.gap-3.w-full.text-sm')
					.first();
				await expect(secondUserRow.getByText(secondUser.name)).toBeVisible();
				await secondUserRow.getByRole('button').first().click();

				await modal.getByRole('button', { name: 'Save' }).click();
			}

			await expect(page.locator('.modal')).toHaveCount(0, { timeout: 15_000 });
			await expect(page.locator('button', { hasText: groupName }).first()).toContainText('2');
		} finally {
			await deleteGroupByName(page, token, groupName);
			await deleteUsersByEmail(page, token, [firstUser.email, secondUser.email]);
		}
	});
});
