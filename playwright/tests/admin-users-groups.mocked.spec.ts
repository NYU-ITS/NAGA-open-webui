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
	info?: {
		is_co_admin?: boolean;
		pilot_genai?: {
			terms?: {
				accepted?: boolean;
				required?: boolean;
				version?: number;
				accepted_at?: number;
			};
		};
	};
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

const adminUser: MockUser = {
	id: 'admin-user-1',
	name: 'Admin User',
	email: 'admin@example.com',
	role: 'admin',
	token: 'playwright-token',
	created_at: 1_700_000_000,
	last_active_at: 1_700_000_100,
	profile_image_url: '/user.png',
	info: {
		is_co_admin: false,
		pilot_genai: {
			terms: {
				accepted: true,
				version: 1,
				accepted_at: 1_700_000_000
			}
		}
	}
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

const json = (route: Route, payload: unknown, status = 200) =>
	route.fulfill({
		status,
		contentType: 'application/json',
		body: JSON.stringify(payload)
	});

function buildUser(input: { id: string; name: string; email: string; role: MockUser['role'] }): MockUser {
	return {
		...input,
		created_at: 1_700_000_000,
		last_active_at: 1_700_000_100,
		profile_image_url: '/user.png',
		info: {}
	};
}

async function mockAdminUsersApis(page: Page) {
	const users: MockUser[] = [adminUser];
	const groups: MockGroup[] = [];
	const addUserPayloads: Array<Record<string, unknown>> = [];
	const createGroupPayloads: Array<Record<string, unknown>> = [];
	const updateGroupPayloads: Array<Record<string, unknown>> = [];

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
			return json(route, adminUser);
		}

		if (path === '/api/v1/users/user/settings' && method === 'GET') {
			return json(route, { ui: { version: 'test' } });
		}

		if (path === '/api/v1/users/is-super-admin' && method === 'GET') {
			return json(route, false);
		}

		if (path === '/api/v1/users/default/permissions' && method === 'GET') {
			return json(route, defaultPermissions);
		}

		if (path === '/api/v1/configs/banners' && method === 'GET') {
			return json(route, []);
		}

		if (path === '/api/v1/tools/' && method === 'GET') {
			return json(route, []);
		}

		if (path === '/api/models' && method === 'GET') {
			return json(route, { data: [] });
		}

		if (path === '/api/v1/users/' && method === 'GET') {
			return json(route, users);
		}

		if (path === '/api/v1/groups/' && method === 'GET') {
			return json(route, groups);
		}

		if (path === '/api/v1/auths/add' && method === 'POST') {
			const payload = request.postDataJSON() as Record<string, unknown>;
			addUserPayloads.push(payload);

			const nextUser = buildUser({
				id: `user-${users.length}`,
				name: String(payload.name),
				email: String(payload.email),
				role: (payload.role as MockUser['role']) ?? 'user'
			});

			users.push(nextUser);
			return json(route, nextUser);
		}

		if (path === '/api/v1/groups/create' && method === 'POST') {
			const payload = request.postDataJSON() as Record<string, unknown>;
			createGroupPayloads.push(payload);

			const nextGroup: MockGroup = {
				id: `group-${groups.length + 1}`,
				name: String(payload.name),
				description: String(payload.description ?? ''),
				user_id: adminUser.id,
				user_ids: [],
				permissions: {},
				created_by: adminUser.name,
				created_at: 1_700_000_000,
				updated_at: 1_700_000_000,
				last_active_at: 1_700_000_000
			};

			groups.push(nextGroup);
			return json(route, nextGroup);
		}

		if (/^\/api\/v1\/groups\/id\/[^/]+\/update$/.test(path) && method === 'POST') {
			const payload = request.postDataJSON() as Record<string, unknown>;
			updateGroupPayloads.push(payload);

			const groupId = path.split('/')[5];
			const group = groups.find((entry) => entry.id === groupId);

			if (!group) {
				return json(route, { detail: 'Group not found' }, 404);
			}

			group.name = String(payload.name ?? group.name);
			group.description = String(payload.description ?? group.description);
			group.permissions = (payload.permissions as Record<string, unknown>) ?? group.permissions;
			group.user_ids = Array.isArray(payload.user_ids) ? payload.user_ids.map(String) : group.user_ids;
			group.updated_at = 1_700_000_050;

			return json(route, group);
		}

		if (path.startsWith('/api/v1/')) {
			return json(route, []);
		}

		return json(route, {});
	});

	return { users, groups, addUserPayloads, createGroupPayloads, updateGroupPayloads };
}

async function latestModal(page: Page) {
	await expect(page.locator('.modal')).toHaveCount(1, { timeout: 10_000 });
	return page.locator('.modal').last();
}

async function addUserViaModal(page: Page, input: { name: string; email: string; password: string }) {
	await page.getByRole('button', { name: 'Add User' }).click();
	const modal = await latestModal(page);

	await expect(modal.getByText('Add User')).toBeVisible();
	await modal.getByRole('combobox').selectOption('user');
	await modal.getByPlaceholder('Enter Your Full Name').fill(input.name);
	await modal.getByPlaceholder('Enter Your Email').fill(input.email);
	await modal.getByPlaceholder('Enter Your Password').fill(input.password);
	await modal.getByRole('button', { name: 'Save' }).click();

	await expect(page.locator('.modal')).toHaveCount(0, { timeout: 10_000 });
	await expect(page.getByText(input.email)).toBeVisible({ timeout: 10_000 });
}

test.describe('Admin users and groups (Playwright mocked backend)', () => {
	test.beforeEach(async ({ page }) => {
		await page.addInitScript(() => {
			localStorage.setItem('token', 'playwright-token');
			localStorage.setItem('locale', 'en-US');
			localStorage.setItem('version', 'test');
			sessionStorage.clear();
		});
	});

	test('creates two users, creates a group, and assigns both users to it', async ({ page }) => {
		const mocks = await mockAdminUsersApis(page);

		await page.goto('/admin/users');
		await expect(page.getByRole('button', { name: 'Add User' })).toBeVisible({ timeout: 15_000 });

		await addUserViaModal(page, {
			name: 'test student1',
			email: 'teststudent1@nyu.edu',
			password: 'password'
		});

		await addUserViaModal(page, {
			name: 'test student2',
			email: 'teststudent2@nyu.edu',
			password: 'password'
		});

		await page.getByRole('button', { name: 'Groups' }).click();
		await expect(page.getByText('Organize your users')).toBeVisible({ timeout: 10_000 });

		await page.getByRole('button', { name: 'Create Group' }).first().click();
		{
			const modal = await latestModal(page);
			await expect(modal.getByText('Add User Group')).toBeVisible();
			await modal.getByPlaceholder('Group Name').fill('playwright test group');
			await modal.getByPlaceholder('Group Description').fill('playwright test group');
			await modal.getByRole('button', { name: 'Create' }).click();
		}

		await expect(page.locator('.modal')).toHaveCount(0, { timeout: 10_000 });
		await expect(page.getByText('playwright test group')).toBeVisible({ timeout: 10_000 });

		await page.locator('button', { hasText: 'playwright test group' }).first().click();
		{
			const modal = await latestModal(page);
			await expect(modal.getByText('Edit User Group')).toBeVisible();
			await modal.getByRole('button', { name: /Users \(\d+\)/ }).click();

			const searchInput = modal.getByPlaceholder('Search');

			await searchInput.fill('teststudent1@nyu.edu');
			const firstUserRow = modal.locator('div.flex.flex-row.items-center.gap-3.w-full.text-sm').first();
			await expect(firstUserRow.getByText('test student1')).toBeVisible();
			await firstUserRow.getByRole('button').first().click();

			await searchInput.fill('teststudent2@nyu.edu');
			const secondUserRow = modal.locator('div.flex.flex-row.items-center.gap-3.w-full.text-sm').first();
			await expect(secondUserRow.getByText('test student2')).toBeVisible();
			await secondUserRow.getByRole('button').first().click();

			await modal.getByRole('button', { name: 'Save' }).click();
		}

		await expect(page.locator('.modal')).toHaveCount(0, { timeout: 10_000 });
		await expect(page.locator('button', { hasText: 'playwright test group' }).first()).toContainText('2');

		expect(mocks.addUserPayloads).toEqual([
			{
				name: 'test student1',
				email: 'teststudent1@nyu.edu',
				password: 'password',
				role: 'user'
			},
			{
				name: 'test student2',
				email: 'teststudent2@nyu.edu',
				password: 'password',
				role: 'user'
			}
		]);

		expect(mocks.createGroupPayloads).toEqual([
			{
				name: 'playwright test group',
				description: 'playwright test group'
			}
		]);

		expect(mocks.groups).toHaveLength(1);
		expect(mocks.groups[0]?.name).toBe('playwright test group');
		expect(mocks.updateGroupPayloads).toHaveLength(1);
		expect(mocks.updateGroupPayloads[0]?.name).toBe('playwright test group');
		expect(mocks.updateGroupPayloads[0]?.description).toBe('playwright test group');
		expect(mocks.updateGroupPayloads[0]?.permissions).toEqual({});
		expect(mocks.updateGroupPayloads[0]?.user_ids).toEqual(['user-1', 'user-2']);
	});
});
