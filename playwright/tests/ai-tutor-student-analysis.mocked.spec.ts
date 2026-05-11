import { expect, test, type Page, type Route } from '@playwright/test';

const mockUser = {
	id: 'user-admin-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token'
};

const mockGroup = {
	id: 'group-nyu-101',
	name: 'Class 101 - Calculus',
	user_id: mockUser.id,
	user_ids: ['student-1', 'student-2']
};

const mockUsers = [
	mockUser,
	{
		id: 'student-1',
		name: 'Test Student One',
		email: 'student1@example.edu',
		role: 'user',
		profile_image_url: '/user.png',
		created_at: 1_700_000_000,
		last_active_at: 1_700_000_100
	},
	{
		id: 'student-2',
		name: 'Test Student Two',
		email: 'student2@example.edu',
		role: 'user',
		profile_image_url: '/user.png',
		created_at: 1_700_000_000,
		last_active_at: 1_700_000_100
	}
];

const mockHomeworkRows = [
	{
		id: 'hw-1',
		group_id: mockGroup.id,
		model_id: 'Homework Algebra',
		question_uploaded: true,
		answer_uploaded: true,
		topic_mapped: true
	}
];

const mockAnalysisRows = [
	{
		id: 'analysis-row-1',
		student_id: 'student-1',
		student_email: 'student1@example.edu',
		homework_id: 'hw-1',
		total_attempted: 14,
		total_question: 15,
		total_solved: 13,
		total_errors: 1,
		topic_performances: [
			{
				topic_name: 'Linear Equations',
				status: 'needs_practice'
			}
		]
	},
	{
		id: 'analysis-row-2',
		student_id: 'student-2',
		student_email: 'student2@example.edu',
		homework_id: 'hw-1',
		total_attempted: 15,
		total_question: 15,
		total_solved: 15,
		total_errors: 0,
		topic_performances: []
	}
];

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

async function mockStudentAnalysisApis(page: Page) {
	let exportCallCount = 0;

	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const path = url.pathname;
		const method = request.method();

		if (path === '/api/config' && method === 'GET') {
			return json(route, {
				name: 'Pilot GenAI',
				version: 'test',
				default_locale: 'en-US',
				features: {
					enable_websocket: false,
					enable_direct_connections: false,
					enable_admin_chat_access: false
				}
			});
		}

		if (path === '/api/v1/auths/' && method === 'GET') {
			return json(route, mockUser);
		}

		if (path === '/api/v1/users/user/settings' && method === 'GET') {
			return json(route, { ui: { version: 'test' } });
		}

		if (path === '/api/v1/users/is-super-admin' && method === 'GET') {
			return json(route, false);
		}

		if (path === '/api/v1/groups/' && method === 'GET') {
			return json(route, [mockGroup]);
		}

		if (path === `/api/v1/groups/id/${mockGroup.id}` && method === 'GET') {
			return json(route, mockGroup);
		}

		if (path === '/api/v1/users/' && method === 'GET') {
			return json(route, mockUsers);
		}

		if (path === '/api/models' && method === 'GET') {
			return json(route, {
				data: [
					{
						id: 'homework-algebra-v1',
						name: 'Homework Algebra',
						info: { base_model_id: 'base-model-1' },
						access_control: { read: { group_ids: [mockGroup.id] } }
					}
				]
			});
		}

		if (path === '/api/ai-tutor/homework/' && method === 'GET') {
			return json(route, mockHomeworkRows);
		}

		if (path === '/api/ai-tutor/analysis/' && method === 'GET') {
			return json(route, mockAnalysisRows);
		}

		if (path === '/api/ai-tutor/analysis/export/analysis-row-1' && method === 'GET') {
			exportCallCount += 1;
			return route.fulfill({
				status: 200,
				contentType: 'application/pdf',
				headers: {
					'content-disposition': 'attachment; filename="student-analysis-report.pdf"'
				},
				body: '%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF'
			});
		}

		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}

		return json(route, {});
	});

	return {
		get exportCallCount() {
			return exportCallCount;
		}
	};
}

async function openSidebarIfNeeded(page: Page) {
	const dashboardLink = page.getByRole('link', { name: 'AI Tutor Dashboard - Instructor' });
	if (!(await dashboardLink.isVisible().catch(() => false))) {
		await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
	}
	await expect(dashboardLink).toBeVisible({ timeout: 10_000 });
}

test.describe('AI Tutor student analysis (Playwright mocked backend)', () => {
	test.beforeEach(async ({ page }) => {
		await page.addInitScript(() => {
			localStorage.setItem('token', 'playwright-token');
			localStorage.setItem('locale', 'en-US');
			localStorage.setItem('version', 'test');
			sessionStorage.clear();
		});
	});

	test('downloads a student report when available', async ({ page }) => {
		const mocks = await mockStudentAnalysisApis(page);

		await page.goto('/');
		await openSidebarIfNeeded(page);
		await page.getByRole('link', { name: 'AI Tutor Dashboard - Instructor' }).click();
		await page.getByRole('link', { name: 'Student Analysis' }).click();

		await expect(page.getByRole('heading', { name: 'Student Analysis' })).toBeVisible({
			timeout: 15_000
		});

		const noStudentsMessage = page.getByText(/No student analysis is available|No group members are available/);
		if (await noStudentsMessage.isVisible().catch(() => false)) {
			throw new Error('No students to analyse');
		}

		const downloadButtons = page.getByRole('button', { name: 'Download Report' });
		const downloadButtonCount = await downloadButtons.count();

		if (downloadButtonCount === 0) {
			const studentRows = page.locator('tbody tr');
			if ((await studentRows.count()) > 0) {
				throw new Error('No reports available');
			}
			throw new Error('No students to analyse');
		}

		const [download] = await Promise.all([
			page.waitForEvent('download'),
			downloadButtons.first().click()
		]);

		expect(download.suggestedFilename()).toBe('student-analysis-report.pdf');
		expect(mocks.exportCallCount).toBe(1);
	});
});
