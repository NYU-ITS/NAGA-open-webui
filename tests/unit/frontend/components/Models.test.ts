import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/svelte';
import '@testing-library/jest-dom';

// --- Mocks ---

// Force lifecycle callbacks to run in this isolated component harness.
vi.mock('svelte', async (importOriginal) => {
	const actual = await importOriginal<typeof import('svelte')>();
	return { ...actual, onMount: (fn: () => void | Promise<void>) => fn() };
});

// Mock SvelteKit navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

// Mock svelte-sonner
vi.mock('svelte-sonner', () => ({
	toast: { error: vi.fn(), success: vi.fn() }
}));

// Mock API modules — getModels is imported as getWorkspaceModels in the component
vi.mock('$lib/apis/models', () => ({
	getModels: vi.fn(() => Promise.resolve([])),
	createNewModel: vi.fn(),
	deleteModelById: vi.fn(),
	toggleModelById: vi.fn(),
	updateModelById: vi.fn()
}));

vi.mock('$lib/apis', () => ({
	getModels: vi.fn(() => Promise.resolve([]))
}));

vi.mock('$lib/apis/groups', () => ({
	getGroups: vi.fn(() => Promise.resolve([]))
}));

// Mock Svelte components with a compiled Svelte component. Svelte component imports
// must be constructors; functions returning HTML strings trigger "default is not a constructor".
const { stubComponent } = vi.hoisted(() => ({
	stubComponent: async () => ({ default: (await import('./SvelteStub.svelte')).default })
}));
vi.mock('$lib/components/icons/EllipsisHorizontal.svelte', stubComponent);
vi.mock('$lib/components/icons/GarbageBin.svelte', stubComponent);
vi.mock('$lib/components/icons/Search.svelte', stubComponent);
vi.mock('$lib/components/icons/Plus.svelte', stubComponent);
vi.mock('$lib/components/icons/ChevronRight.svelte', stubComponent);
vi.mock('$lib/components/common/ConfirmDialog.svelte', stubComponent);
vi.mock('$lib/components/common/Tooltip.svelte', stubComponent);
vi.mock('$lib/components/common/Switch.svelte', stubComponent);
vi.mock('$lib/components/common/Spinner.svelte', stubComponent);
vi.mock('$lib/components/workspace/Models/ModelMenu.svelte', stubComponent);

// Mock stores as writable Svelte stores
vi.mock('$lib/stores', () => {
	const { writable } = require('svelte/store');
	return {
		WEBUI_NAME: writable('Open WebUI'),
		config: writable({ features: { enable_community_sharing: false } }),
		mobile: writable(false),
		models: writable([]),
		settings: writable({}),
		user: writable({ id: 'user-1', role: 'admin' })
	};
});

// Mock utils
vi.mock('$lib/utils', () => ({
	capitalizeFirstLetter: (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
}));

// --- Tests ---

import Models from './ModelsWrapper.svelte';
import { getModels as getWorkspaceModels } from '$lib/apis/models';
import { getGroups } from '$lib/apis/groups';
import { user } from '$lib/stores';

const makeModel = (id: string, name: string, groupIds: string[] = [], isActive = true, userId = 'user-1') => ({
	id,
	name,
	meta: { profile_image_url: '/static/favicon.png', description: '' },
	user_id: userId,
	user: { name: 'Admin', email: 'admin@test.com' },
	is_active: isActive,
	access_control: { read: { group_ids: groupIds, user_ids: [] }, write: { group_ids: [], user_ids: [] } }
});

describe('Models.svelte', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		Object.defineProperty(window, 'localStorage', {
			value: { token: 'test-token', getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() },
			configurable: true
		});
		user.set({ id: 'user-1', role: 'admin' });
	});

	afterEach(() => {
		cleanup();
	});

	it('shows spinner while loading', () => {
		(getWorkspaceModels as any).mockReturnValue(new Promise(() => {}));

		render(Models);

		expect(screen.getByTestId('svelte-stub')).toBeInTheDocument();
	});

	it('renders model list after loading', async () => {
		const models = [makeModel('m1', 'GPT-4'), makeModel('m2', 'Claude')];
		(getWorkspaceModels as any).mockResolvedValue(models);
		(getGroups as any).mockResolvedValue([]);

		render(Models);

		await waitFor(() => {
			expect(screen.getByText('GPT-4')).toBeInTheDocument();
			expect(screen.getByText('Claude')).toBeInTheDocument();
		});
	});

	it('renders model count', async () => {
		const models = [makeModel('m1', 'GPT-4'), makeModel('m2', 'Claude')];
		(getWorkspaceModels as any).mockResolvedValue(models);
		(getGroups as any).mockResolvedValue([]);

		render(Models);

		await waitFor(() => {
			expect(screen.getByText('2')).toBeInTheDocument();
		});
	});

	it('groups models by group name', async () => {
		const models = [
			makeModel('m1', 'Model A', ['g1']),
			makeModel('m2', 'Model B', ['g2'])
		];
		const groups = [
			{ id: 'g1', name: 'Research Team' },
			{ id: 'g2', name: 'Engineering' }
		];
		(getWorkspaceModels as any).mockResolvedValue(models);
		(getGroups as any).mockResolvedValue(groups);

		render(Models);

		await waitFor(() => {
			expect(screen.getByText('Research Team')).toBeInTheDocument();
			expect(screen.getByText('Engineering')).toBeInTheDocument();
		});
	});

	it('places models without group_ids in Uncategorized', async () => {
		const models = [makeModel('m1', 'Model A', [])];
		(getWorkspaceModels as any).mockResolvedValue(models);
		(getGroups as any).mockResolvedValue([]);

		render(Models);

		await waitFor(() => {
			expect(screen.getByText('Uncategorized')).toBeInTheDocument();
		});
	});

	it('renders model descriptions', async () => {
		const models = [{
			...makeModel('m1', 'GPT-4'),
			meta: { profile_image_url: '/static/favicon.png', description: 'A powerful model' }
		}];
		(getWorkspaceModels as any).mockResolvedValue(models);
		(getGroups as any).mockResolvedValue([]);

		render(Models);

		await waitFor(() => {
			expect(screen.getAllByText('A powerful model').length).toBeGreaterThan(0);
		});
	});

	it('renders model creator name', async () => {
		const models = [makeModel('m1', 'GPT-4')];
		(getWorkspaceModels as any).mockResolvedValue(models);
		(getGroups as any).mockResolvedValue([]);

		render(Models);

		await waitFor(() => {
			expect(screen.getByText(/By Admin/)).toBeInTheDocument();
		});
	});

	it('shows search input', async () => {
		(getWorkspaceModels as any).mockResolvedValue([]);
		(getGroups as any).mockResolvedValue([]);

		render(Models);

		await waitFor(() => {
			expect(screen.getByPlaceholderText('Search Models')).toBeInTheDocument();
		});
	});
});
