/// <reference types="node" />

import path from 'node:path';
import { expect, test } from '@playwright/test';
import {
	apiJson,
	deleteGroupByName,
	deleteKnowledgeByName,
	deleteModelByName,
	liveEnabled,
	loginAsAdmin,
	selectOptionOrFirst,
	uniqueLiveName
} from './live-test-utils';

test.describe('Workspace knowledge and models live workflow', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

	test('creates a knowledge base, uploads a pdf, and links it to a new model', async ({
		page
	}, testInfo) => {
		test.setTimeout(120_000);
		const { token } = await loginAsAdmin(page);
		const suffix = uniqueLiveName('pw-live-workspace', testInfo.workerIndex);
		const groupName = `${suffix} group`;
		const knowledgeName = `${suffix} knowledge`;
		const modelName = `${suffix} homework model`;
		const pdfPath =
			process.env.PLAYWRIGHT_KNOWLEDGE_PDF_PATH ??
			path.resolve(process.cwd(), 'playwright/knowledgeStore/test-pdf.pdf');

		try {
			await apiJson(page, token, 'POST', '/api/v1/groups/create', {
				name: groupName,
				description: groupName
			});

			await page.goto('/');
			const workspaceLink = page.getByRole('link', { name: 'Workspace' });
			if (!(await workspaceLink.isVisible().catch(() => false))) {
				await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
			}
			await expect(workspaceLink).toBeVisible({ timeout: 10_000 });
			await workspaceLink.click();
			await page.getByRole('link', { name: 'Knowledge' }).click();

			await page.getByRole('button', { name: 'Create Knowledge' }).click();
			await expect(page.getByText('Create a knowledge base')).toBeVisible({ timeout: 15_000 });

			await page.getByPlaceholder('Name your knowledge base').fill(knowledgeName);
			await page
				.getByPlaceholder('Describe your knowledge base and objectives')
				.fill('playwright live test');

			const knowledgeGroupSelect = page
				.locator('select')
				.filter({ has: page.locator('option[value=""]') })
				.last();
			await selectOptionOrFirst(
				knowledgeGroupSelect,
				groupName,
				'the live-created group does not exist to add to the knowledge base'
			);

			await page.getByRole('button', { name: 'Create Knowledge' }).click();
			await expect(page.locator('input[placeholder="Knowledge Name"]')).toHaveValue(knowledgeName, {
				timeout: 15_000
			});

			await page.getByRole('button', { name: 'Add Content' }).first().click();
			await page.getByText('Upload files').click();
			await page.locator('#files-input').setInputFiles(pdfPath);

			await expect(page.getByText(path.basename(pdfPath))).toBeVisible({ timeout: 30_000 });
			await page.getByRole('button', { name: 'Save' }).first().click();

			await page.getByRole('link', { name: 'Models' }).click();
			await page.locator('a[href="/workspace/models/create"]').click();

			await expect(page.getByPlaceholder('Model Name')).toBeVisible({ timeout: 15_000 });
			await page.getByPlaceholder('Model Name').fill(modelName);
			const selectedBaseModel = await selectOptionOrFirst(
				page.locator('select[placeholder="Select a base model"]'),
				process.env.PLAYWRIGHT_BASE_MODEL_LABEL ?? '',
				'No base model is available to create a workspace model.'
			);
			expect(selectedBaseModel).toBeTruthy();

			await page.getByRole('button', { name: 'Select Knowledge' }).first().click();
			const knowledgeOption = page
				.locator('[data-melt-dropdown-menu-content], [role="menu"]')
				.getByText(knowledgeName, { exact: true });
			await expect(knowledgeOption).toBeVisible({ timeout: 15_000 });
			await knowledgeOption.click();

			const modelGroupSelect = page
				.locator('select')
				.filter({ has: page.locator('option[value=""]') })
				.last();
			await selectOptionOrFirst(
				modelGroupSelect,
				groupName,
				'the live-created group does not exist to link to the workspace model'
			);

			await page.getByRole('button', { name: 'Save & Create' }).click();
			await expect(page.getByText(modelName)).toBeVisible({ timeout: 20_000 });
		} finally {
			await deleteModelByName(page, token, modelName);
			await deleteKnowledgeByName(page, token, knowledgeName);
			await deleteGroupByName(page, token, groupName);
		}
	});
});
