import path from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

type MockUser = {
	id: string;
	name: string;
	email: string;
	role: 'admin' | 'user' | 'pending';
	token?: string;
	created_at: number;
	last_active_at: number;
	profile_image_url: string;
	info?: Record<string, unknown>;
};

type MockGroup = {
	id: string;
	name: string;
	description: string;
	user_id: string;
	user_ids: string[];
	permissions: Record<string, unknown>;
	created_by: string;
	created_at: number;
	updated_at: number;
	last_active_at: number;
};

type MockFile = {
	id: string;
	meta: {
		name: string;
		content_type: string;
		size: number;
		processing_status?: 'pending' | 'processing' | 'error' | 'ready';
		processing_error?: string;
		data?: Record<string, unknown>;
	};
	created_at: number;
	updated_at: number;
	data?: {
		content?: string;
	};
};

type MockKnowledge = {
	id: string;
	user_id: string;
	name: string;
	description: string;
	data: {
		file_ids: string[];
	};
	meta: null;
	access_control: {
		read: { group_ids: string[]; user_ids: string[] };
		write: { group_ids: string[]; user_ids: string[] };
	};
	created_at: number;
	updated_at: number;
	user: {
		id: string;
		name: string;
		email: string;
		role: string;
		profile_image_url: string;
	};
	files: MockFile[];
	type: 'collection';
	assign_to_email?: string;
};

type MockWorkspaceModel = {
	id: string;
	base_model_id: string;
	name: string;
	meta: {
		profile_image_url: string;
		description: string | null;
		suggestion_prompts: null;
		tags: Array<{ name: string }>;
		capabilities: {
			vision: boolean;
			usage?: boolean;
			citations: boolean;
		};
		knowledge?: MockKnowledge[];
	};
	params: Record<string, unknown>;
	access_control: {
		read: { group_ids: string[]; user_ids: string[] };
		write: { group_ids: string[]; user_ids: string[] };
	};
	preset?: boolean;
	owned_by?: string;
	created_by?: string;
	user_id?: string;
};

const adminUser: MockUser = {
	id: 'admin-user-knowledge-1',
	name: 'Aman Kumar',
	email: 'sm11538@nyu.edu',
	role: 'admin',
	token: 'playwright-token',
	created_at: 1_700_000_000,
	last_active_at: 1_700_000_100,
	profile_image_url: '/user.png',
	info: {
		pilot_genai: {
			terms: {
				accepted: true,
				version: 1,
				accepted_at: 1_700_000_000
			}
		}
	}
};

const mockGroup: MockGroup = {
	id: '38cf115d-50ee-4ef9-9f9d-ac7c7bb65c78',
	name: 'playwright test group',
	description: 'playwright test group',
	user_id: adminUser.id,
	user_ids: [],
	permissions: {},
	created_by: adminUser.name,
	created_at: 1_700_000_000,
	updated_at: 1_700_000_000,
	last_active_at: 1_700_000_000
};

const defaultPermissions = {
	workspace: {
		models: false,
		knowledge: false,
		prompts: false,
		tools: false
	},
	chat: {
		controls: true,
		file_upload: true,
		delete: true,
		edit: true,
		temporary: true
	},
	features: {
		web_search: true,
		image_generation: true,
		code_interpreter: true
	}
};

const baseModelOption: MockWorkspaceModel = {
	id: 'llm1_sm11538.@gpt-4o/gpt-4o',
	base_model_id: 'llm1_sm11538.@gpt-4o/gpt-4o',
	name: 'GPT 4o',
	meta: {
		profile_image_url: '/static/flower-violet.png',
		description: null,
		suggestion_prompts: null,
		tags: [],
		capabilities: {
			vision: true,
			usage: false,
			citations: true
		}
	},
	params: {},
	access_control: {
		read: { group_ids: [], user_ids: [] },
		write: { group_ids: [], user_ids: [] }
	},
	preset: false,
	owned_by: 'openai',
	created_by: adminUser.email,
	user_id: adminUser.id
};

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

function cloneKnowledgeBase(knowledge: MockKnowledge): MockKnowledge {
	return {
		...knowledge,
		data: { ...knowledge.data, file_ids: [...knowledge.data.file_ids] },
		access_control: {
			read: {
				group_ids: [...knowledge.access_control.read.group_ids],
				user_ids: [...knowledge.access_control.read.user_ids]
			},
			write: {
				group_ids: [...knowledge.access_control.write.group_ids],
				user_ids: [...knowledge.access_control.write.user_ids]
			}
		},
		user: { ...knowledge.user },
		files: knowledge.files.map((file) => ({
			...file,
			meta: { ...file.meta, data: { ...(file.meta.data ?? {}) } },
			data: file.data ? { ...file.data } : undefined
		}))
	};
}

async function mockWorkspaceApis(page: Page) {
	const groups: MockGroup[] = [mockGroup];
	const knowledgeBases: MockKnowledge[] = [];
	const workspaceModels: MockWorkspaceModel[] = [];

	const knowledgeCreatePayloads: Array<Record<string, unknown>> = [];
	const knowledgeUpdatePayloads: Array<Record<string, unknown>> = [];
	const modelCreatePayloads: Array<Record<string, unknown>> = [];
	const uploadRequests: Array<{ knowledgeId: string; filename: string }> = [];

	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		const pathName = url.pathname;
		const method = request.method();

		if (pathName === '/api/config' && method === 'GET') {
			return json(route, {
				name: 'Pilot GenAI',
				version: 'test',
				default_locale: 'en-US',
				features: {
					enable_websocket: false,
					enable_direct_connections: false,
					enable_admin_chat_access: false,
					enable_channels: false
				}
			});
		}

		if (pathName === '/api/v1/auths/' && method === 'GET') {
			return json(route, adminUser);
		}

		if (pathName === '/api/v1/users/user/settings' && method === 'GET') {
			return json(route, { ui: { version: 'test' } });
		}

		if (pathName === '/api/v1/users/is-super-admin' && method === 'GET') {
			return json(route, false);
		}

		if (pathName === '/api/v1/users/default/permissions' && method === 'GET') {
			return json(route, defaultPermissions);
		}

		if (pathName === '/api/v1/users/' && method === 'GET') {
			return json(route, [adminUser]);
		}

		if (pathName === '/api/v1/configs/banners' && method === 'GET') {
			return json(route, []);
		}

		if (pathName === '/api/v1/tools/' && method === 'GET') {
			return json(route, []);
		}

		if (pathName === '/api/v1/functions/' && method === 'GET') {
			return json(route, []);
		}

		if (pathName === '/api/models' && method === 'GET') {
			return json(route, { data: [...workspaceModels, baseModelOption] });
		}

		if (pathName === '/api/v1/models/' && method === 'GET') {
			return json(route, workspaceModels);
		}

		if (pathName === '/api/v1/groups/' && method === 'GET') {
			return json(route, groups);
		}

		if (pathName === '/api/v1/knowledge/' && method === 'GET') {
			return json(route, knowledgeBases.map(cloneKnowledgeBase));
		}

		if (pathName === '/api/v1/knowledge/list' && method === 'GET') {
			return json(
				route,
				knowledgeBases.map((knowledge) => ({
					id: knowledge.id,
					name: knowledge.name,
					description: knowledge.description,
					meta: knowledge.meta,
					user: knowledge.user,
					updated_at: knowledge.updated_at
				}))
			);
		}

		if (pathName === '/api/v1/knowledge/create' && method === 'POST') {
			const payload = request.postDataJSON() as Record<string, unknown>;
			knowledgeCreatePayloads.push(payload);

			const createdKnowledge: MockKnowledge = {
				id: '15e5652b-c256-47ad-8400-33d43a7eb680',
				user_id: adminUser.id,
				name: String(payload.name),
				description: String(payload.description),
				data: { file_ids: [] },
				meta: null,
				access_control: {
					read: {
						group_ids: Array.isArray((payload.access_control as any)?.read?.group_ids)
							? (payload.access_control as any).read.group_ids.map(String)
							: [],
						user_ids: []
					},
					write: {
						group_ids: Array.isArray((payload.access_control as any)?.write?.group_ids)
							? (payload.access_control as any).write.group_ids.map(String)
							: [],
						user_ids: []
					}
				},
				created_at: 1_778_049_048,
				updated_at: 1_778_049_048,
				user: {
					id: adminUser.id,
					name: adminUser.name,
					email: adminUser.email,
					role: adminUser.role,
					profile_image_url: adminUser.profile_image_url
				},
				files: [],
				type: 'collection',
				assign_to_email: payload.assign_to_email ? String(payload.assign_to_email) : undefined
			};

			knowledgeBases.push(createdKnowledge);
			return json(route, cloneKnowledgeBase(createdKnowledge));
		}

		if (/^\/api\/v1\/knowledge\/[^/]+$/.test(pathName) && method === 'GET') {
			const knowledgeId = pathName.split('/')[4];
			const knowledge = knowledgeBases.find((entry) => entry.id === knowledgeId);
			if (!knowledge) {
				return json(route, { detail: 'Knowledge not found' }, 404);
			}
			return json(route, cloneKnowledgeBase(knowledge));
		}

		if (/^\/api\/v1\/knowledge\/[^/]+\/file\/add$/.test(pathName) && method === 'POST') {
			const knowledgeId = pathName.split('/')[4];
			const knowledge = knowledgeBases.find((entry) => entry.id === knowledgeId);
			if (!knowledge) {
				return json(route, { detail: 'Knowledge not found' }, 404);
			}

			const bodyBuffer = request.postDataBuffer() ?? Buffer.from([]);
			const filenameMatch = bodyBuffer.toString('utf8').match(/filename="([^"]+)"/);
			const filename = filenameMatch?.[1] ?? 'uploaded-file';
			uploadRequests.push({ knowledgeId, filename });

			const file: MockFile = {
				id: '79213780-bbd0-4126-8edd-da09ff365841',
				meta: {
					name: filename,
					content_type: 'application/pdf',
					size: 13_264,
					processing_status: 'ready',
					data: {}
				},
				created_at: 1_778_049_130,
				updated_at: 1_778_049_130,
				data: {
					content: ''
				}
			};

			knowledge.files = [file, ...knowledge.files.filter((entry) => entry.id !== file.id)];
			knowledge.data.file_ids = [file.id];
			knowledge.updated_at = 1_778_049_130;
			return json(route, cloneKnowledgeBase(knowledge));
		}

		if (/^\/api\/v1\/knowledge\/[^/]+\/update$/.test(pathName) && method === 'POST') {
			const knowledgeId = pathName.split('/')[4];
			const knowledge = knowledgeBases.find((entry) => entry.id === knowledgeId);
			if (!knowledge) {
				return json(route, { detail: 'Knowledge not found' }, 404);
			}

			const payload = request.postDataJSON() as Record<string, unknown>;
			knowledgeUpdatePayloads.push(payload);

			knowledge.name = String(payload.name ?? knowledge.name);
			knowledge.description = String(payload.description ?? knowledge.description);
			knowledge.access_control = {
				read: {
					group_ids: Array.isArray((payload.access_control as any)?.read?.group_ids)
						? (payload.access_control as any).read.group_ids.map(String)
						: knowledge.access_control.read.group_ids,
					user_ids: []
				},
				write: {
					group_ids: Array.isArray((payload.access_control as any)?.write?.group_ids)
						? (payload.access_control as any).write.group_ids.map(String)
						: knowledge.access_control.write.group_ids,
					user_ids: []
				}
			};

			const nextFileIds = Array.isArray((payload.data as any)?.file_ids)
				? (payload.data as any).file_ids.map(String)
				: knowledge.data.file_ids;

			knowledge.data.file_ids = nextFileIds;
			knowledge.files = knowledge.files.filter((file) => nextFileIds.includes(file.id));
			knowledge.assign_to_email = payload.assign_to_email ? String(payload.assign_to_email) : knowledge.assign_to_email;
			knowledge.updated_at = 1_778_049_177;
			return json(route, cloneKnowledgeBase(knowledge));
		}

		if (pathName === '/api/v1/models/create' && method === 'POST') {
			const payload = request.postDataJSON() as Record<string, unknown>;
			modelCreatePayloads.push(payload);

			const createdModel: MockWorkspaceModel = {
				id: String(payload.id),
				base_model_id: String(payload.base_model_id),
				name: String(payload.name),
				meta: (payload.meta as MockWorkspaceModel['meta']) ?? {
					profile_image_url: '/static/flower-violet.png',
					description: null,
					suggestion_prompts: null,
					tags: [],
					capabilities: {
						vision: true,
						citations: true
					}
				},
				params: (payload.params as Record<string, unknown>) ?? {},
				access_control: (payload.access_control as MockWorkspaceModel['access_control']) ?? {
					read: { group_ids: [], user_ids: [] },
					write: { group_ids: [], user_ids: [] }
				},
				preset: false,
				owned_by: 'openai',
				created_by: adminUser.email,
				user_id: adminUser.id
			};

			workspaceModels.push(createdModel);
			return json(route, createdModel);
		}

		if (pathName.startsWith('/api/v1/')) {
			return json(route, []);
		}

		return json(route, {});
	});

	return {
		groups,
		knowledgeBases,
		workspaceModels,
		knowledgeCreatePayloads,
		knowledgeUpdatePayloads,
		modelCreatePayloads,
		uploadRequests
	};
}

async function selectGroupOrFail(page: Page, selectLocator: ReturnType<Page['locator']>, groupName: string, errorMessage: string) {
	const option = selectLocator.locator(`option:text-is("${groupName}")`);
	if ((await option.count()) === 0) {
		throw new Error(errorMessage);
	}
	await selectLocator.selectOption({ label: groupName });
}

test.describe('Workspace knowledge and models (Playwright mocked backend)', () => {
	test.beforeEach(async ({ page }) => {
		await page.addInitScript(() => {
			localStorage.setItem('token', 'playwright-token');
			localStorage.setItem('locale', 'en-US');
			localStorage.setItem('version', 'test');
			sessionStorage.clear();
		});
	});

	test('creates a knowledge base, uploads a pdf, and links it to a new model', async ({ page }) => {
		const mocks = await mockWorkspaceApis(page);

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

		await page.getByPlaceholder('Name your knowledge base').fill('playwright homework test knowledge');
		await page
			.getByPlaceholder('Describe your knowledge base and objectives')
			.fill('playwright test');

		const knowledgeGroupSelect = page.locator('select').filter({ has: page.locator('option[value=""]') }).last();
		await selectGroupOrFail(
			page,
			knowledgeGroupSelect,
			'playwright test group',
			'the group does not exist to add to knowledge base'
		);

		await page.getByRole('button', { name: 'Create Knowledge' }).click();
		await expect(page.locator('input[placeholder="Knowledge Name"]')).toHaveValue(
			'playwright homework test knowledge',
			{ timeout: 10_000 }
		);

		await page.getByRole('button', { name: 'Add Content' }).first().click();
		await page.getByText('Upload files').click();
		await page.locator('#files-input').setInputFiles(
			path.resolve('/Users/amankumar/Desktop/NYU GenAI/NAGA-open-webui/playwright/knowledgeStore/test-pdf.pdf')
		);

		await expect(page.getByText('test-pdf.pdf')).toBeVisible({ timeout: 10_000 });
		await page.getByRole('button', { name: 'Save' }).first().click();

		await page.getByRole('link', { name: 'Models' }).click();
		await page.locator('a[href="/workspace/models/create"]').click();

		await expect(page.getByPlaceholder('Model Name')).toBeVisible({ timeout: 15_000 });
		await page.getByPlaceholder('Model Name').fill('playwright homework test model');
		await page.locator('select[placeholder="Select a base model"]').selectOption({ label: 'GPT 4o' });

		await page.getByRole('button', { name: 'Select Knowledge' }).first().click();
		const knowledgeOption = page.locator('[data-melt-dropdown-menu-content], [role="menu"]').getByText(
			'playwright homework test knowledge',
			{ exact: true }
		);
		if ((await knowledgeOption.count()) === 0) {
			throw new Error('No knowledge base to link to HW model');
		}
		await knowledgeOption.click();

		const modelGroupSelect = page.locator('select').filter({ has: page.locator('option[value=""]') }).last();
		await selectGroupOrFail(
			page,
			modelGroupSelect,
			'playwright test group',
			'group does not exist to link to HW Model'
		);

		await page.getByRole('button', { name: 'Save & Create' }).click();
		await expect(page.getByText('playwright homework test model')).toBeVisible({ timeout: 10_000 });

		expect(mocks.knowledgeCreatePayloads).toEqual([
			{
				name: 'playwright homework test knowledge',
				description: 'playwright test',
				access_control: {
					read: {
						group_ids: ['38cf115d-50ee-4ef9-9f9d-ac7c7bb65c78'],
						user_ids: []
					},
					write: {
						group_ids: [],
						user_ids: []
					}
				},
				assign_to_email: undefined
			}
		]);

		expect(mocks.uploadRequests).toEqual([
			{
				knowledgeId: '15e5652b-c256-47ad-8400-33d43a7eb680',
				filename: 'test-pdf.pdf'
			}
		]);

		expect(mocks.knowledgeUpdatePayloads).toHaveLength(1);
		expect(mocks.knowledgeUpdatePayloads[0]?.name).toBe('playwright homework test knowledge');
		expect(mocks.knowledgeUpdatePayloads[0]?.description).toBe('playwright test');
		expect(mocks.knowledgeUpdatePayloads[0]?.data).toEqual({
			file_ids: ['79213780-bbd0-4126-8edd-da09ff365841']
		});
		expect(mocks.knowledgeUpdatePayloads[0]?.access_control).toEqual({
			read: {
				group_ids: ['38cf115d-50ee-4ef9-9f9d-ac7c7bb65c78'],
				user_ids: []
			},
			write: {
				group_ids: [],
				user_ids: []
			}
		});

		expect(mocks.modelCreatePayloads).toHaveLength(1);
		expect(mocks.modelCreatePayloads[0]?.id).toBe('playwright-homework-test-model');
		expect(mocks.modelCreatePayloads[0]?.base_model_id).toBe('llm1_sm11538.@gpt-4o/gpt-4o');
		expect(mocks.modelCreatePayloads[0]?.name).toBe('playwright homework test model');
		expect(mocks.modelCreatePayloads[0]?.access_control).toEqual({
			read: {
				group_ids: ['38cf115d-50ee-4ef9-9f9d-ac7c7bb65c78'],
				user_ids: []
			},
			write: {
				group_ids: [],
				user_ids: []
			}
		});
		expect((mocks.modelCreatePayloads[0]?.meta as any)?.knowledge?.[0]?.name).toBe(
			'playwright homework test knowledge'
		);
	});
});
