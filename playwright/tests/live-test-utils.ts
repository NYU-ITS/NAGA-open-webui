/// <reference types="node" />

import { expect, test, type Page } from '@playwright/test';

export const liveEnabled = process.env.PLAYWRIGHT_RUN_LIVE === '1';
export const fallbackUserEmail = process.env.PLAYWRIGHT_USER_EMAIL ?? '';
export const fallbackUserPassword = process.env.PLAYWRIGHT_USER_PASSWORD ?? '';
export const adminEmail = process.env.PLAYWRIGHT_ADMIN_EMAIL ?? fallbackUserEmail;
export const adminPassword = process.env.PLAYWRIGHT_ADMIN_PASSWORD ?? fallbackUserPassword;

export type LiveAuth = {
	token: string;
	user: Record<string, unknown>;
};

type LiveGroup = {
	id: string;
	name?: string;
};

type LiveUser = {
	id: string;
	email?: string;
};

type LiveNamedEntity = {
	id: string;
	name?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
	return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

export function uniqueLiveName(prefix: string, workerIndex = 0) {
	return `${prefix} ${Date.now()} ${workerIndex}`.replace(/\s+/g, '-').toLowerCase();
}

export async function loginViaApi(page: Page, email: string, password: string): Promise<LiveAuth> {
	const response = await page.request.post('/api/v1/auths/signin', {
		data: {
			email,
			password
		}
	});

	if (!response.ok()) {
		throw new Error(
			`Login failed (${response.status()}): ${await response.text()}\n` +
				'Verify PLAYWRIGHT_BASE_URL, PLAYWRIGHT_ADMIN_EMAIL, and PLAYWRIGHT_ADMIN_PASSWORD.'
		);
	}

	const data = (await response.json()) as unknown;
	const record = isRecord(data) ? data : {};
	const nestedData = isRecord(record.data) ? record.data : {};
	const token =
		record.token ?? record.access_token ?? nestedData.token ?? nestedData.access_token ?? '';

	if (typeof token !== 'string' || !token) {
		throw new Error(`Login response missing token: ${JSON.stringify(data)}`);
	}

	await page.addInitScript((t) => {
		localStorage.setItem('token', t);
		localStorage.setItem('locale', 'en-US');
	}, token);

	await page.goto('/');
	await expect(page).not.toHaveURL(/\/auth$/);

	return { token, user: record };
}

export async function loginAsAdmin(page: Page): Promise<LiveAuth> {
	test.skip(
		!adminEmail || !adminPassword,
		'Provide PLAYWRIGHT_ADMIN_EMAIL and PLAYWRIGHT_ADMIN_PASSWORD.'
	);
	return loginViaApi(page, adminEmail, adminPassword);
}

export async function dismissWhatsNewIfShown(page: Page) {
	const modalTitle = page.getByText(/What[’']s New in Pilot GenAI/i);
	for (let i = 0; i < 3; i++) {
		const isOpen = await modalTitle.isVisible().catch(() => false);
		if (!isOpen) return;

		const ok = page.getByRole('button', { name: "Okay, Let's Go!" });
		if (await ok.isVisible().catch(() => false)) {
			await ok.click();
		} else {
			await page.keyboard.press('Escape').catch(() => {});
			const xButton = page.locator('.modal').getByRole('button').first();
			if (await xButton.isVisible().catch(() => false)) {
				await xButton.click().catch(() => {});
			}
		}
		await modalTitle.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {});
	}
}

export async function openSidebarIfNeeded(page: Page, linkName: string | RegExp) {
	const link = page.getByRole('link', { name: linkName });
	if (!(await link.isVisible().catch(() => false))) {
		await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
	}
	await expect(link).toBeVisible({ timeout: 10_000 });
	return link;
}

export async function apiJson<T = unknown>(
	page: Page,
	token: string,
	method: 'GET' | 'POST' | 'DELETE' | 'PATCH',
	path: string,
	data?: unknown
): Promise<T> {
	const response = await page.request.fetch(path, {
		method,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		...(data === undefined ? {} : { data })
	});

	if (!response.ok()) {
		throw new Error(`${method} ${path} failed (${response.status()}): ${await response.text()}`);
	}

	const text = await response.text();
	return text ? (JSON.parse(text) as T) : ({} as T);
}

export async function deleteGroupByName(page: Page, token: string, name: string) {
	try {
		const groups = await apiJson<LiveGroup[]>(page, token, 'GET', '/api/v1/groups/');
		const group = groups.find((entry) => entry?.name === name);
		if (group?.id) {
			await apiJson(
				page,
				token,
				'DELETE',
				`/api/v1/groups/id/${encodeURIComponent(group.id)}/delete`
			);
		}
	} catch {
		// Best-effort live cleanup. The test outcome should describe the workflow, not cleanup drift.
	}
}

export async function deleteUsersByEmail(page: Page, token: string, emails: string[]) {
	try {
		const users = await apiJson<LiveUser[]>(page, token, 'GET', '/api/v1/users/');
		for (const email of emails) {
			const user = users.find((entry) => entry?.email === email);
			if (user?.id) {
				await apiJson(page, token, 'DELETE', `/api/v1/users/${encodeURIComponent(user.id)}`);
			}
		}
	} catch {
		// Best-effort live cleanup.
	}
}

export async function deleteKnowledgeByName(page: Page, token: string, name: string) {
	try {
		const knowledge = await apiJson<LiveNamedEntity[]>(page, token, 'GET', '/api/v1/knowledge/');
		const entry = knowledge.find((item) => item?.name === name);
		if (entry?.id) {
			await apiJson(
				page,
				token,
				'DELETE',
				`/api/v1/knowledge/${encodeURIComponent(entry.id)}/delete`
			);
		}
	} catch {
		// Best-effort live cleanup.
	}
}

export async function deleteModelByName(page: Page, token: string, name: string) {
	try {
		const models = await apiJson<LiveNamedEntity[]>(page, token, 'GET', '/api/v1/models/');
		const model = models.find((entry) => entry?.name === name);
		if (model?.id) {
			await apiJson(
				page,
				token,
				'DELETE',
				`/api/v1/models/model/delete?id=${encodeURIComponent(model.id)}`
			);
		}
	} catch {
		// Best-effort live cleanup.
	}
}

export async function getLiveGroup(page: Page, token: string): Promise<LiveGroup> {
	const groups = await apiJson<LiveGroup[]>(page, token, 'GET', '/api/v1/groups/');
	const requestedId = process.env.PLAYWRIGHT_AI_TUTOR_GROUP_ID ?? '';
	const requestedName =
		process.env.PLAYWRIGHT_AI_TUTOR_GROUP_NAME ?? process.env.PLAYWRIGHT_LIVE_GROUP_NAME ?? '';

	if (requestedId) {
		const group = groups.find((entry) => entry?.id === requestedId);
		test.skip(!group, `No group found for PLAYWRIGHT_AI_TUTOR_GROUP_ID=${requestedId}.`);
		if (!group) throw new Error(`No group found for PLAYWRIGHT_AI_TUTOR_GROUP_ID=${requestedId}.`);
		return group;
	}

	if (requestedName) {
		const group = groups.find((entry) => entry?.name === requestedName);
		test.skip(!group, `No group found for PLAYWRIGHT_AI_TUTOR_GROUP_NAME=${requestedName}.`);
		if (!group)
			throw new Error(`No group found for PLAYWRIGHT_AI_TUTOR_GROUP_NAME=${requestedName}.`);
		return group;
	}

	test.skip(groups.length === 0, 'No groups are available for the admin account.');
	if (!groups[0]) throw new Error('No groups are available for the admin account.');
	return groups[0];
}

export async function selectOptionOrFirst(
	selectLocator: ReturnType<Page['locator']>,
	optionLabel: string,
	missingMessage: string
) {
	const options = selectLocator.locator('option');
	const count = await options.count();
	test.skip(count === 0, missingMessage);

	if (optionLabel) {
		const requested = selectLocator.locator(`option:text-is("${optionLabel}")`);
		test.skip((await requested.count()) === 0, missingMessage);
		await selectLocator.selectOption({ label: optionLabel });
		return optionLabel;
	}

	for (let i = 0; i < count; i++) {
		const option = options.nth(i);
		const value = await option.getAttribute('value');
		const label = (await option.textContent())?.trim() ?? '';
		if (value && label) {
			await selectLocator.selectOption(value);
			return label;
		}
	}

	test.skip(true, missingMessage);
	return '';
}
