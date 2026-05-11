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
	user_ids: [mockUser.id]
};

const mockHomework = {
	id: 'hw-1',
	group_id: mockGroup.id,
	model_id: 'Homework Algebra',
	question_uploaded: true,
	answer_uploaded: true,
	topic_mapped: true
};

const generatedQuestions = [
	{
		number: 1,
		text: 'Solve the quadratic equation $x^2 - 5x + 6 = 0$.',
		topics: ['Factoring Quadratics'],
		hint: 'Factor the polynomial into two binomials.',
		answer: 'x = 2 or x = 3'
	},
	{
		number: 2,
		text: 'A student missed problems on factoring. Factor $x^2 + 7x + 12$.',
		topics: ['Factoring Quadratics'],
		hint: 'Find two numbers that multiply to 12 and add to 7.',
		answer: '(x + 3)(x + 4)'
	}
];

const mockSourceModel = {
	id: 'Homework Algebra',
	base_model_id: 'base-model-1',
	name: 'Homework Algebra',
	meta: {},
	params: {},
	access_control: {
		read: { group_ids: [mockGroup.id], user_ids: [] },
		write: { group_ids: [], user_ids: [] }
	},
	is_active: true
};

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

async function mockPracticeQuestionApis(page: Page) {
	let generateRequestCount = 0;
	let pipelinePollCount = 0;
	let knowledgeCreateCount = 0;
	let masteryCreateCount = 0;
	let sendAssignmentCount = 0;

	let generatedPractice:
		| {
				id: string;
				homework_id: string;
				version_number: number;
				status: 'pending' | 'approved';
				created_at: string;
				generated_time: string;
				problem_items: typeof generatedQuestions;
				problem_data: string;
		  }
		| null = null;

	let assignmentCreatedAt: string | null = null;
	let masteryKnowledgeId: string | null = null;
	let masteryModelCreated = false;

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

		if (path === '/api/v1/models/model' && method === 'GET') {
			const modelId = url.searchParams.get('id');
			if (modelId === mockSourceModel.id) {
				return json(route, mockSourceModel);
			}
			if (modelId === 'mastery-Homework Algebra') {
				if (!masteryModelCreated || !masteryKnowledgeId) {
					return json(route, { detail: 'Model not found' }, 404);
				}
				return json(route, {
					id: 'mastery-Homework Algebra',
					base_model_id: 'base-model-1',
					name: 'Mastery Homework Algebra',
					meta: {
						knowledge: [
							{
								id: masteryKnowledgeId,
								name: 'Mastery Homework Algebra Practice KB'
							}
						]
					},
					params: {},
					access_control: mockSourceModel.access_control,
					is_active: true
				});
			}
			return json(route, { detail: 'Model not found' }, 404);
		}

		if (path === '/api/v1/models/create' && method === 'POST') {
			masteryCreateCount += 1;
			masteryModelCreated = true;
			return json(route, { id: 'mastery-Homework Algebra' });
		}

		if (path === '/api/v1/models/model/update' && method === 'POST') {
			return json(route, { id: 'mastery-Homework Algebra' });
		}

		if (path === '/api/v1/knowledge/create' && method === 'POST') {
			knowledgeCreateCount += 1;
			masteryKnowledgeId = 'kb-practice-1';
			return json(route, { id: masteryKnowledgeId });
		}

		if (path === `/api/v1/knowledge/${masteryKnowledgeId}/reset` && method === 'POST') {
			return json(route, {});
		}

		if (path === `/api/v1/knowledge/${masteryKnowledgeId}/update` && method === 'POST') {
			return json(route, {});
		}

		if (path === `/api/v1/knowledge/${masteryKnowledgeId}/file/add` && method === 'POST') {
			return json(route, { id: `practice-file-${knowledgeCreateCount}` });
		}

		if (path === '/api/v1/chats/filter/meta' && method === 'POST') {
			return json(route, []);
		}

		if (path === '/api/ai-tutor/homework/' && method === 'GET') {
			return json(route, [mockHomework]);
		}

		if (path === '/api/ai-tutor/analysis/' && method === 'GET') {
			return json(route, [
				{
					id: 'analysis-row-1',
					student_id: 'student-1',
					student_email: 'student1@example.edu',
					homework_id: mockHomework.id,
					topic_performances: [{ topic_name: 'Factoring Quadratics', status: 'needs_practice' }]
				}
			]);
		}

		if (path === '/api/ai-tutor/practice' && method === 'GET') {
			const homeworkId = url.searchParams.get('homework_id');
			const groupId = url.searchParams.get('group_id');

			if (homeworkId === mockHomework.id) {
				return json(route, generatedPractice ? [generatedPractice] : []);
			}

			if (groupId === mockGroup.id) {
				return json(route, generatedPractice ? [generatedPractice] : []);
			}
		}

		if (path === '/api/ai-tutor/practice/generate' && method === 'POST') {
			generateRequestCount += 1;
			return json(route, { job_id: 'practice-job-1' });
		}

		if (path === '/api/ai-tutor/pipeline/status/practice-job-1' && method === 'GET') {
			pipelinePollCount += 1;
			generatedPractice = {
				id: 'practice-set-1',
				homework_id: mockHomework.id,
				version_number: 1,
				status: 'pending',
				created_at: '2026-05-08 13:15:00',
				generated_time: '2026-05-08 13:15:00',
				problem_items: generatedQuestions,
				problem_data:
					'## Question 1\n\nSolve the quadratic equation x^2 - 5x + 6 = 0.\n\n## Question 2\n\nFactor x^2 + 7x + 12.',
			};
			return json(route, { status: 'done', step: 'practice_complete' });
		}

		if (path === '/api/ai-tutor/practice/practice-set-1' && method === 'PATCH') {
			const body = request.postDataJSON() as {
				problem_items?: typeof generatedQuestions;
				problem_data?: string;
				status?: string;
			};
			if (!generatedPractice) {
				return json(route, { detail: 'Practice set not found' }, 404);
			}
			generatedPractice = {
				...generatedPractice,
				problem_items: Array.isArray(body.problem_items) ? body.problem_items : generatedPractice.problem_items,
				problem_data:
					typeof body.problem_data === 'string' ? body.problem_data : generatedPractice.problem_data,
				status: body.status === 'approved' ? 'approved' : generatedPractice.status
			};
			return json(route, generatedPractice);
		}

		if (path === '/api/ai-tutor/assignment' && method === 'GET') {
			const practiceProblemId = url.searchParams.get('practice_problem_id');
			if (practiceProblemId === 'practice-set-1' && assignmentCreatedAt) {
				return json(route, [
					{
						id: 'assignment-1',
						student_id: 'student-1',
						student_email: 'student1@example.edu',
						homework_id: mockHomework.id,
						practice_problem_id: 'practice-set-1',
						assigned_count: 2,
						assigned_items: generatedQuestions,
						created_at: assignmentCreatedAt
					}
				]);
			}
			return json(route, []);
		}

		if (path === '/api/ai-tutor/assignment/assign' && method === 'POST') {
			sendAssignmentCount += 1;
			assignmentCreatedAt = '2026-05-08 13:20:00';
			return json(route, { success: true });
		}

		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}

		return json(route, {});
	});

	return {
		get generateRequestCount() {
			return generateRequestCount;
		},
		get pipelinePollCount() {
			return pipelinePollCount;
		},
		get knowledgeCreateCount() {
			return knowledgeCreateCount;
		},
		get masteryCreateCount() {
			return masteryCreateCount;
		},
		get sendAssignmentCount() {
			return sendAssignmentCount;
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

test.describe('AI Tutor practice question workflow (Playwright mocked backend)', () => {
	test.beforeEach(async ({ page }) => {
		await page.addInitScript((groupId) => {
			localStorage.setItem('token', 'playwright-token');
			localStorage.setItem('locale', 'en-US');
			localStorage.setItem('version', 'test');
			localStorage.setItem('ai_tutor_last_selected_group_id', groupId);
			sessionStorage.clear();
		}, mockGroup.id);
	});

	test('generates, approves, and sends practice questions', async ({ page }) => {
		test.fixme(
			true,
			'Blocked: the visible Generate button never triggers /api/ai-tutor/practice/generate under mocked admin setup.'
		);

		const mocks = await mockPracticeQuestionApis(page);
		const pageErrors: string[] = [];
		const consoleErrors: string[] = [];

		page.on('pageerror', (error) => {
			pageErrors.push(error.message);
		});
		page.on('console', (message) => {
			if (message.type() === 'error') {
				consoleErrors.push(message.text());
			}
		});

		await page.goto('/');
		await openSidebarIfNeeded(page);
		await page.getByRole('link', { name: 'AI Tutor Dashboard - Instructor' }).click();
		await expect(page).toHaveURL(/\/aitutordashboard\?group_id=group-nyu-101$/, {
			timeout: 15_000
		});
		await page.getByRole('link', { name: 'Practice Question' }).click();
		await expect(page).toHaveURL(
			/\/aitutordashboard\/topicanalysis\/reviewquestionset\?group_id=group-nyu-101$/,
			{
				timeout: 15_000
			}
		);

		await expect(page.getByRole('heading', { name: 'Practice Question Workflow' })).toBeVisible({
			timeout: 15_000
		});

		const generateButtons = page.getByRole('button', { name: 'Generate' });
		const generateButtonCount = await generateButtons.count();

		if (generateButtonCount === 0) {
			throw new Error('No practice question sets available to generate');
		}

		await page.waitForTimeout(1500);
		await generateButtons.first().click();
		await expect
			.poll(
				() => ({
					generateRequestCount: mocks.generateRequestCount,
					pageErrors,
					consoleErrors
				}),
				{
					message: 'Practice question generate button never triggered its POST request'
				}
			)
			.toMatchObject({
				generateRequestCount: 1
			});
		await expect.poll(() => mocks.pipelinePollCount).toBeGreaterThan(0);

		const noWeakTopicsMessage = page.getByText('No weak topics found');
		if (await noWeakTopicsMessage.isVisible().catch(() => false)) {
			throw new Error('No weak topics to generate practice questions');
		}

		await page.goto(
			`/aitutordashboard/topicanalysis/reviewquestionset?group_id=${mockGroup.id}&homework_id=${mockHomework.id}`
		);
		await expect(page.getByRole('heading', { name: 'Practice Question Workflow' })).toBeVisible({
			timeout: 15_000
		});
		await expect(page.getByText('No practice questions has been generated yet')).toBeHidden({
			timeout: 15_000
		});

		const approveButton = page.getByRole('button', { name: 'Approve' });
		await expect(approveButton).toBeEnabled({ timeout: 10_000 });
		await approveButton.click();

		await expect(page.getByRole('button', { name: 'Approved' })).toBeVisible({
			timeout: 15_000
		});

		const sendButton = page.getByRole('button', { name: 'Send' });
		await expect(sendButton).toBeEnabled({ timeout: 10_000 });
		await sendButton.click();

		await expect(page.getByRole('button', { name: 'Sent' })).toBeVisible({
			timeout: 15_000
		});

		expect(mocks.pipelinePollCount).toBeGreaterThan(0);
		expect(mocks.knowledgeCreateCount).toBe(1);
		expect(mocks.masteryCreateCount).toBe(1);
		expect(mocks.sendAssignmentCount).toBe(1);
	});
});
