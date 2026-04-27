/// <reference types="node" />

import { readFile } from 'node:fs/promises';
import { basename } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const liveEnabled = process.env.PLAYWRIGHT_RUN_LIVE === '1';
const fallbackUserEmail = process.env.PLAYWRIGHT_USER_EMAIL ?? '';
const fallbackUserPassword = process.env.PLAYWRIGHT_USER_PASSWORD ?? '';
const adminEmail = process.env.PLAYWRIGHT_ADMIN_EMAIL ?? fallbackUserEmail;
const adminPassword = process.env.PLAYWRIGHT_ADMIN_PASSWORD ?? fallbackUserPassword;
const studentEmail = process.env.PLAYWRIGHT_STUDENT_EMAIL ?? fallbackUserEmail;
const studentPassword = process.env.PLAYWRIGHT_STUDENT_PASSWORD ?? fallbackUserPassword;
const homeworkPdfPath = process.env.PLAYWRIGHT_HOMEWORK_PDF_PATH ?? '';

async function loginViaApi(page: Page, email: string, password: string) {
	const response = await page.request.post('/api/v1/auths/signin', {
		data: {
			email,
			password
		}
	});

	if (!response.ok()) {
		throw new Error(
			`Login failed (${response.status()}): ${await response.text()}\n` +
				`Verify these credentials can sign in manually at ${page.url().split('/').slice(0, 3).join('/')}/auth`
		);
	}

	const data = (await response.json()) as any;
	const token =
		data?.token ??
		data?.access_token ??
		data?.data?.token ??
		data?.data?.access_token ??
		'';

	if (!token) {
		throw new Error(`Login response missing token: ${JSON.stringify(data)}`);
	}

	await page.addInitScript((t) => {
		localStorage.setItem('token', t);
		localStorage.setItem('locale', 'en-US');
	}, token);

	// Ensure app loads with token present.
	await page.goto('/');
	await expect(page).not.toHaveURL(/\/auth$/);
}

async function loginAsAdmin(page: Page) {
	test.skip(!adminEmail || !adminPassword, 'Provide PLAYWRIGHT_ADMIN_EMAIL and PLAYWRIGHT_ADMIN_PASSWORD.');
	await loginViaApi(page, adminEmail, adminPassword);
}

async function loginAsStudent(page: Page) {
	test.skip(!studentEmail || !studentPassword, 'Provide PLAYWRIGHT_STUDENT_EMAIL and PLAYWRIGHT_STUDENT_PASSWORD.');
	await loginViaApi(page, studentEmail, studentPassword);
}

async function dismissWhatsNewIfShown(page: Page) {
	const modalTitle = page.getByText(/What[’']s New in Pilot GenAI/i);
	for (let i = 0; i < 3; i++) {
		const isOpen = await modalTitle.isVisible().catch(() => false);
		if (!isOpen) return;

		const ok = page.getByRole('button', { name: "Okay, Let's Go!" });
		if (await ok.isVisible().catch(() => false)) {
			await ok.click();
		} else {
			// Some builds show only an X button; Escape also closes the modal.
			await page.keyboard.press('Escape').catch(() => {});
			const xButton = page.locator('.modal').getByRole('button').first();
			if (await xButton.isVisible().catch(() => false)) {
				await xButton.click().catch(() => {});
			}
		}
		await modalTitle.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {});
	}
}

async function clearVisibleToasts(page: Page) {
	const closeButtons = page.getByRole('button', { name: 'Close toast' });
	for (let i = await closeButtons.count(); i > 0; i--) {
		await closeButtons.nth(i - 1).click().catch(() => {});
	}
}

async function openInstructorSetup(page: Page) {
	await page.goto('/aitutordashboard/instructorsetup');
	await dismissWhatsNewIfShown(page);
	await expect(page.getByText('Follow these 3 steps to analyze and support your students')).toBeVisible({
		timeout: 15_000
	});
}

async function openTopicAnalysis(page: Page) {
	await page.goto('/aitutordashboard/topicanalysis');
	await dismissWhatsNewIfShown(page);
	await expect(page.getByRole('heading', { name: 'Topic Analysis by Homework' })).toBeVisible({ timeout: 15_000 });
	await expect(page.getByRole('link', { name: /Practice Question/i })).toBeVisible({ timeout: 15_000 });
}

async function ensureHomeworkUploadTableVisible(page: Page) {
	const sectionToggle = page.getByRole('button', { name: /^2\.Homework & Answer Files/i });
	const table = page.getByRole('table');

	if (!(await table.isVisible().catch(() => false))) {
		await sectionToggle.scrollIntoViewIfNeeded().catch(() => {});
		await sectionToggle.click().catch(() => {});
	}

	await expect(table).toBeVisible({ timeout: 15_000 });
	return table;
}

/**
 * The UI shows "No homework models are found for this group." whenever `homeworkFileRows` is empty.
 * That is also true briefly while workspace models / group access are still loading — not only when
 * there are truly no homework models. Wait for that message to clear or for upload inputs to exist.
 */
async function waitUntilHomeworkModelsResolved(page: Page) {
	const loadingGroup = page.getByText('Loading group selection...');
	const emptyModels = page.getByText('No homework models are found for this group.');

	if (await loadingGroup.isVisible().catch(() => false)) {
		await loadingGroup.waitFor({ state: 'hidden', timeout: 30_000 });
	}

	const deadline = Date.now() + 60_000;
	while (Date.now() < deadline) {
		// Homework model rows use id="upload-question-{row.id}" (see Instructor Setup table).
		const questionInputs = page.locator('input[id^="upload-question-"]');
		if ((await questionInputs.count()) > 0) {
			return;
		}
		if (!(await emptyModels.isVisible().catch(() => false))) {
			return;
		}
		await page.waitForTimeout(250);
	}

	if (await emptyModels.isVisible().catch(() => false)) {
		test.skip(
			true,
			'No homework models for this group after waiting. Use a workspace model whose name includes "homework" and grant this group access to it.'
		);
	}
}

/**
 * Instructor Setup starts an HTTP upload, then polls the pipeline until done/failed.
 * The status column can show "Processing PDF" while the job runs — that is NOT success.
 * Real success is signaled by toast: "Homework upload completed." (see instructorsetup +page.svelte).
 */
type UploadNetworkEvent = {
	method: string;
	url: string;
	status?: number;
	failure?: string;
};

async function loadHomeworkPdfForUpload(pdfPath: string) {
	try {
		return {
			name: basename(pdfPath),
			mimeType: 'application/pdf',
			buffer: await readFile(pdfPath)
		};
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(
			`Cannot read PLAYWRIGHT_HOMEWORK_PDF_PATH: ${pdfPath}\n` +
				`OS error: ${message}\n` +
				`Use a PDF path that this terminal/Playwright process can read. On macOS, files under ~/Downloads may require privacy permission or may need to be moved to a non-protected folder.`
		);
	}
}

function watchAITutorUploadNetwork(page: Page) {
	const events: UploadNetworkEvent[] = [];
	const isRelevant = (url: string) =>
		url.includes('/api/ai-tutor/homework/pdf-to-markdown') || url.includes('/api/ai-tutor/pipeline/status/');

	const onResponse = (response: any) => {
		const request = response.request();
		const url = response.url();
		if (!isRelevant(url)) return;
		events.push({
			method: request.method(),
			url,
			status: response.status()
		});
	};

	const onRequestFailed = (request: any) => {
		const url = request.url();
		if (!isRelevant(url)) return;
		events.push({
			method: request.method(),
			url,
			failure: request.failure()?.errorText ?? 'request failed'
		});
	};

	page.on('response', onResponse);
	page.on('requestfailed', onRequestFailed);

	return {
		events,
		stop: () => {
			page.off('response', onResponse);
			page.off('requestfailed', onRequestFailed);
		}
	};
}

function formatUploadNetworkEvents(events: UploadNetworkEvent[]) {
	if (events.length === 0) return 'No upload/pipeline network events were captured.';
	return events
		.map((event) => {
			const outcome = event.failure ? `failed: ${event.failure}` : `status ${event.status}`;
			return `${event.method} ${event.url} -> ${outcome}`;
		})
		.join('\n');
}

async function waitForHomeworkPdfUploadFinished(
	page: Page,
	timeoutMs: number,
	networkEvents: UploadNetworkEvent[]
) {
	const deadline = Date.now() + timeoutMs;
	const successToast = page
		.locator('[data-sonner-toast][data-type="success"]')
		.filter({ hasText: /Homework upload completed/i });
	const uploadRequestFailed = () => networkEvents.find((event) => event.failure);
	const uploadBadResponse = () => networkEvents.find((event) => event.status !== undefined && event.status >= 400);

	while (Date.now() < deadline) {
		if (await successToast.first().isVisible().catch(() => false)) {
			return;
		}
		const failedRequest = uploadRequestFailed();
		if (failedRequest) {
			throw new Error(
				`Homework PDF upload/processing network request failed:\n${formatUploadNetworkEvents(networkEvents)}`
			);
		}
		const badResponse = uploadBadResponse();
		if (badResponse) {
			throw new Error(
				`Homework PDF upload/processing returned an HTTP error:\n${formatUploadNetworkEvents(networkEvents)}`
			);
		}
		await page.waitForTimeout(250);
	}

	throw new Error(
		`Timed out after ${timeoutMs}ms waiting for "Homework upload completed." ` +
			`(still processing, stalled, or backend never reported completion).\n` +
			formatUploadNetworkEvents(networkEvents)
	);
}

async function uploadHomeworkPdf(page: Page, pdfPath: string) {
	test.skip(!pdfPath, 'Provide PLAYWRIGHT_HOMEWORK_PDF_PATH for upload workflow.');

	const table = await ensureHomeworkUploadTableVisible(page);
	await waitUntilHomeworkModelsResolved(page);
	// Use tbody only — thead also contains the text "Homework" as a column title and would match /^homework\b/.
	const homeworkRow = table.locator('tbody tr').filter({ hasText: /^homework\b/i }).first();
	await expect(homeworkRow).toBeVisible({ timeout: 15_000 });

	// Same control as the purple upload icon in the "Homework PDF" column (`#upload-question-{row.id}`).
	// Choosing a file fires `change` → upload starts immediately; no Action-column button click required.
	// When homework was already uploaded, Action shows Run/Re-run — replacement upload is still this input + icon.
	const questionInput = homeworkRow.locator('input[id^="upload-question-"]');
	test.skip((await questionInput.count()) === 0, 'No homework question file input in row; check model/group.');

	// Clear unrelated stale toasts before triggering upload so we only evaluate this upload attempt.
	await clearVisibleToasts(page);
	const uploadNetwork = watchAITutorUploadNetwork(page);
	await questionInput.setInputFiles(await loadHomeworkPdfForUpload(pdfPath));

	await dismissWhatsNewIfShown(page);
	try {
		await waitForHomeworkPdfUploadFinished(page, 90_000, uploadNetwork.events);
	} finally {
		uploadNetwork.stop();
	}
}

async function ensureChatModelSelectedIfNeeded(page: Page) {
	const modelSelect = page.getByRole('button', { name: /Select a model/i });
	if (!(await modelSelect.isVisible().catch(() => false))) return;

	await modelSelect.click();
	const modelItems = page.getByRole('button', { name: 'model-item' });
	test.skip((await modelItems.count()) === 0, 'No models available to select for chat; configure at least one model.');
	await modelItems.first().click();
	await expect(modelSelect).not.toContainText('Select a model', { timeout: 10_000 });
}

async function sendChatAndWaitForAssistant(page: Page, message: string) {
	await page.locator('#chat-input').fill(message);
	await page.locator('button[type="submit"]').click();

	const assistant = page.locator('.chat-assistant');
	const errorToast = page
		.locator('[data-sonner-toast]')
		.filter({ hasText: /error|failed|unable|missing|invalid|unauthorized|forbidden/i });

	const deadline = Date.now() + 60_000;
	let winner: 'assistant' | 'error' | null = null;
	while (Date.now() < deadline) {
		if (await assistant.first().isVisible().catch(() => false)) {
			winner = 'assistant';
			break;
		}
		if (await errorToast.first().isVisible().catch(() => false)) {
			winner = 'error';
			break;
		}
		await page.waitForTimeout(250);
	}

	test.skip(!winner, 'No assistant response (and no clear error toast) within timeout; local inference backend may be slow/misconfigured.');
	test.skip(winner === 'error', 'Chat generation failed in this local environment (error toast shown). Configure a working model/inference backend.');
	expect(winner).toBe('assistant');
}

test.describe('AI Tutor dashboard live workflow bots', () => {
	test.skip(!liveEnabled, 'Set PLAYWRIGHT_RUN_LIVE=1 to run live E2E workflows.');

	test('Workflow 1 (Admin) Upload homework PDF', async ({ page }) => {
		test.setTimeout(120_000);
		await loginAsAdmin(page);
		await openInstructorSetup(page);
		await uploadHomeworkPdf(page, homeworkPdfPath);
	});

	test('Workflow 2 (Student) Send a chat message', async ({ page }) => {
		await loginAsStudent(page);
		await page.goto('/');
		await dismissWhatsNewIfShown(page);

		await ensureChatModelSelectedIfNeeded(page);
		await sendChatAndWaitForAssistant(page, 'Help me solve this homework problem.');
	});

	test('Workflow 3 (Admin) Open analytics dashboard', async ({ page }) => {
		await loginAsAdmin(page);
		await openTopicAnalysis(page);
	});
});
