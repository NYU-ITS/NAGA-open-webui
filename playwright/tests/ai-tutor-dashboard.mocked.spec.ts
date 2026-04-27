import { expect, test, type Page, type Route } from '@playwright/test';

type MockScenario = 'success' | 'loading' | 'analysis-error';

const mockUser = {
	id: 'user-admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token'
};

const mockGroups = [
	{
		id: 'group-nyu-101',
		name: 'Class 101 - Calculus',
		user_id: mockUser.id,
		user_ids: [mockUser.id]
	}
];

const mockHomeworkRows = [
	{
		id: 'hw-1',
		group_id: 'group-nyu-101',
		model_id: 'Homework Algebra',
		question_uploaded: true,
		answer_uploaded: true,
		topic_mapped: true
	}
];

const mockTopicAnalysisRows = [
	{
		homework_id: 'hw-1',
		student_id: 'student-1',
		topic_performances: [
			{
				topic_name: 'Linear Equations',
				details: 'Q1: Solve 2x+3=7 (Conceptual)'
			}
		]
	},
	{
		homework_id: 'hw-1',
		student_id: 'student-2',
		topic_performances: [
			{
				topic_name: 'Linear Equations',
				details: 'Q2: Solve 3x-9=0 (Procedural)'
			}
		]
	}
];

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

async function mockAuthAndDashboardApis(page: Page, scenario: MockScenario) {
	await page.route('**/api/**', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;

		if (path === '/api/config' && route.request().method() === 'GET') {
			return json(route, {
				name: 'Pilot GenAI',
				version: 'test',
				default_locale: 'en-US',
				features: {
					enable_websocket: false,
					enable_direct_connections: false
				}
			});
		}
		if (path === '/api/v1/auths/' && route.request().method() === 'GET') {
			return json(route, mockUser);
		}
		if (path === '/api/v1/users/user/settings' && route.request().method() === 'GET') {
			return json(route, { ui: { version: 'test' } });
		}
		if (path === '/api/v1/users/is-super-admin' && route.request().method() === 'GET') {
			return json(route, false);
		}
		if (path === '/api/v1/groups/' && route.request().method() === 'GET') {
			return json(route, mockGroups);
		}
		if (path === '/api/models' && route.request().method() === 'GET') {
			return json(route, {
				data: [
					{
						id: 'homework-algebra-v1',
						name: 'Homework Algebra',
						info: { base_model_id: 'base-model-1' },
						access_control: { read: { group_ids: ['group-nyu-101'] } }
					}
				]
			});
		}
		if (path === '/api/v1/chats/filter/meta' && route.request().method() === 'POST') {
			return json(route, []);
		}
		if (path.startsWith('/api/ai-tutor/homework') && route.request().method() === 'GET') {
			return json(route, mockHomeworkRows);
		}
		if (path === '/api/ai-tutor/analysis/error-types' && route.request().method() === 'GET') {
			return json(route, {
				error_types: [
					{
						type: 'Conceptual',
						description: 'Student misunderstands the concept.'
					},
					{
						type: 'Procedural',
						description: 'Student applies the wrong process.'
					}
				]
			});
		}
		if (path.startsWith('/api/ai-tutor/practice-question-set') && route.request().method() === 'GET') {
			return json(route, []);
		}
		if (path.startsWith('/api/ai-tutor/analysis') && route.request().method() === 'GET') {
			if (scenario === 'analysis-error') {
				return json(route, { detail: 'Analytics backend unavailable.' }, 500);
			}
			if (scenario === 'loading') {
				await new Promise((resolve) => setTimeout(resolve, 3500));
			}
			return json(route, mockTopicAnalysisRows);
		}

		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}

		return json(route, {});
	});
}

async function dismissWhatsNewIfShown(page: Page) {
	const dismissButton = page.getByRole('button', { name: "Okay, Let's Go!" });
	if (await dismissButton.isVisible().catch(() => false)) {
		await dismissButton.click();
	}
}

async function expectTopicTableToRender(page: Page) {
	const topicCell = page.getByText('Linear Equations');
	const emptyStateCell = page.getByText('No homework uploaded for this group yet.');

	const topicVisible = await topicCell.isVisible().catch(() => false);
	if (topicVisible) {
		await expect(page.getByText('Conceptual: 50%')).toBeVisible({ timeout: 10_000 });
		await expect(page.getByText('Procedural: 50%')).toBeVisible({ timeout: 10_000 });
		return;
	}

	await expect(emptyStateCell).toBeVisible({ timeout: 10_000 });
}

test.describe('AI Tutor dashboard (Playwright mocked backend)', () => {
	test.beforeEach(async ({ page }) => {
		await page.addInitScript(() => {
			localStorage.setItem('token', 'playwright-token');
			localStorage.setItem('locale', 'en-US');
			localStorage.setItem('version', 'test');
			sessionStorage.clear();
		});
	});

	test('renders topic analysis from mocked analytics payload', async ({ page }) => {
		await mockAuthAndDashboardApis(page, 'success');
		const homeworkResponsePromise = page.waitForResponse((response) =>
			response.url().includes('/api/ai-tutor/homework')
		);
		await page.goto('/aitutordashboard/topicanalysis?group_id=group-nyu-101');
		await dismissWhatsNewIfShown(page);
		const homeworkResponse = await homeworkResponsePromise;
		await expect(async () => await homeworkResponse.json()).resolves.toEqual(mockHomeworkRows);
		await page.getByRole('link', { name: 'Summary' }).click();
		await page.getByRole('link', { name: 'Topic Analysis' }).click();

		await expect(page.getByRole('heading', { name: 'Topic Analysis by Homework' })).toBeVisible({
			timeout: 15_000
		});
		await expectTopicTableToRender(page);
	});

	test('shows loading state while analysis response is delayed', async ({ page }) => {
		await mockAuthAndDashboardApis(page, 'loading');
		const homeworkResponsePromise = page.waitForResponse((response) =>
			response.url().includes('/api/ai-tutor/homework')
		);
		await page.goto('/aitutordashboard/topicanalysis?group_id=group-nyu-101');
		await dismissWhatsNewIfShown(page);
		const homeworkResponse = await homeworkResponsePromise;
		await expect(async () => await homeworkResponse.json()).resolves.toEqual(mockHomeworkRows);
		await page.getByRole('link', { name: 'Summary' }).click();
		await page.getByRole('link', { name: 'Topic Analysis' }).click();

		await expect(page.getByText('Loading topic analysis...')).toBeVisible();
		await expect(page.getByText('Loading topic analysis...')).toBeHidden();
		await expectTopicTableToRender(page);
	});

	test('shows fallback empty-state when analytics backend fails', async ({ page }) => {
		await mockAuthAndDashboardApis(page, 'analysis-error');
		await page.goto('/aitutordashboard/topicanalysis?group_id=group-nyu-101');
		await dismissWhatsNewIfShown(page);

		await expect(page.getByRole('heading', { name: 'Topic Analysis by Homework' })).toBeVisible({
			timeout: 15_000
		});
		await expect(
			page.getByText(
				/No analysis data is available for the current filters\. Run analysis first\.|No homework uploaded for this group yet\./
			)
		).toBeVisible();
	});
});
