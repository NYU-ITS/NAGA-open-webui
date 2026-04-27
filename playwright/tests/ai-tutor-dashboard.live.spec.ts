import { expect, test, type Page } from '@playwright/test';

const liveEnabled = process.env.PLAYWRIGHT_RUN_LIVE === '1';
const userEmail = process.env.PLAYWRIGHT_USER_EMAIL ?? '';
const userPassword = process.env.PLAYWRIGHT_USER_PASSWORD ?? '';
const homeworkPdfPath = process.env.PLAYWRIGHT_HOMEWORK_PDF_PATH ?? '';

async function login(page: Page) {
	await page.goto('/auth');
	await page.getByRole('textbox', { name: 'Email' }).fill(userEmail);
	await page.getByRole('textbox', { name: 'Password' }).fill(userPassword);
	await page.getByRole('button', { name: /Sign in|Login/i }).click();
}

test.describe('AI Tutor dashboard live workflow bots', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');
	test.skip(!userEmail || !userPassword, 'Provide PLAYWRIGHT_USER_EMAIL and PLAYWRIGHT_USER_PASSWORD.');

	test('Workflow 1 Instructor/Admin: login and upload syllabus/homework PDF', async ({ page }) => {
		test.skip(!homeworkPdfPath, 'Provide PLAYWRIGHT_HOMEWORK_PDF_PATH for upload workflow.');

		await login(page);
		await page.goto('/aitutordashboard/instructorsetup');

		await expect(page.getByText('Follow these 3 steps to analyze and support your students')).toBeVisible();
		await page.locator('input[type="file"]').first().setInputFiles(homeworkPdfPath);
		await expect(page.getByText('Uploaded')).toBeVisible();
	});

	test('Workflow 2 Student: open chat and verify response stream appears', async ({ page }) => {
		await login(page);
		await page.goto('/');

		await page.getByRole('textbox').first().fill('Help me solve this homework problem.');
		await page.getByRole('button', { name: /send/i }).click();
		await expect(page.locator('.chat-assistant')).toBeVisible();
	});

	test('Workflow 3 Analytics: validate aggregate weakness view for a class', async ({ page }) => {
		await login(page);
		await page.goto('/aitutordashboard/topicanalysis');

		await expect(page.getByRole('heading', { name: 'Topic Analysis by Homework' })).toBeVisible();
		await expect(page.getByRole('heading', { name: /Practice Question/i })).toBeVisible();
	});
});
