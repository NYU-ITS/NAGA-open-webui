import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import '@testing-library/jest-dom';

// --- Mocks ---

// Force lifecycle callbacks to run in this isolated component harness.
vi.mock('svelte', async (importOriginal) => {
	const actual = await importOriginal<typeof import('svelte')>();
	return { ...actual, onMount: (fn: () => void | Promise<void>) => fn() };
});

// Mock svelte-sonner
vi.mock('svelte-sonner', () => ({
	toast: { error: vi.fn(), success: vi.fn() }
}));

// Mock API modules
vi.mock('$lib/apis/tools', () => ({
	getTools: vi.fn(() => Promise.resolve([]))
}));

vi.mock('$lib/apis/functions', () => ({
	getFunctions: vi.fn(() => Promise.resolve([]))
}));

vi.mock('$lib/apis/knowledge', () => ({
	getKnowledgeBases: vi.fn(() => Promise.resolve([]))
}));

vi.mock('$lib/apis/users', () => ({
	checkIfSuperAdmin: vi.fn(() => Promise.resolve(false)),
	getUsers: vi.fn(() => Promise.resolve([]))
}));

// Mock child components with a compiled Svelte component. Svelte component imports
// must be constructors; functions returning HTML strings trigger "default is not a constructor".
const { stubComponent } = vi.hoisted(() => ({
	stubComponent: async () => ({ default: (await import('./SvelteStub.svelte')).default })
}));
vi.mock('$lib/components/chat/Settings/Advanced/AdvancedParams.svelte', stubComponent);
vi.mock('$lib/components/common/Tags.svelte', stubComponent);
vi.mock('$lib/components/workspace/Models/Knowledge.svelte', stubComponent);
vi.mock('$lib/components/workspace/Models/ToolsSelector.svelte', stubComponent);
vi.mock('$lib/components/workspace/Models/FiltersSelector.svelte', stubComponent);
vi.mock('$lib/components/workspace/Models/ActionsSelector.svelte', stubComponent);
vi.mock('$lib/components/workspace/Models/Capabilities.svelte', stubComponent);
vi.mock('$lib/components/common/Textarea.svelte', stubComponent);
vi.mock('$lib/components/common/AccessControl.svelte', stubComponent);
vi.mock('$lib/components/workspace/common/AccessControl.svelte', stubComponent);

// Mock stores
vi.mock('$lib/stores', () => {
	const { writable } = require('svelte/store');
	return {
		models: writable([
			{ id: 'base-1', name: 'Base Model 1', owned_by: 'openai', preset: false },
			{ id: 'base-2', name: 'Base Model 2', owned_by: 'ollama', preset: false }
		]),
		tools: writable([]),
		functions: writable([]),
		knowledge: writable([]),
		user: writable({ id: 'user-1', email: 'admin@test.com', role: 'admin' })
	};
});

// --- Tests ---

import ModelEditor from './TestWrapper.svelte';
import { toast } from 'svelte-sonner';

describe('ModelEditor.svelte', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		Object.defineProperty(window, 'localStorage', {
			value: { token: 'test-token', getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() },
			configurable: true
		});
	});

	afterEach(() => {
		cleanup();
	});

	it('renders the form after loading', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByPlaceholderText('Model Name')).toBeInTheDocument();
			expect(screen.getByPlaceholderText('Model ID')).toBeInTheDocument();
		});
	});

	it('auto-generates id from name in create mode', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByPlaceholderText('Model Name')).toBeInTheDocument();
		});

		const nameInput = screen.getByPlaceholderText('Model Name');
		const idInput = screen.getByPlaceholderText('Model ID');

		await fireEvent.input(nameInput, { target: { value: 'My Model' } });

		await waitFor(() => {
			expect(idInput).toHaveValue('my-model');
		});
	});

	it('strips special chars from generated id', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByPlaceholderText('Model Name')).toBeInTheDocument();
		});

		const nameInput = screen.getByPlaceholderText('Model Name');
		const idInput = screen.getByPlaceholderText('Model ID');

		await fireEvent.input(nameInput, { target: { value: 'GPT-4 (v2)!' } });

		await waitFor(() => {
			expect(idInput).toHaveValue('gpt-4-v2');
		});
	});

	it('disables id input in edit mode', async () => {
		render(ModelEditor, {
			props: {
				onSubmit: vi.fn(),
				edit: true,
				model: {
					id: 'existing-model',
					name: 'Existing Model',
					meta: { description: null, tags: [], capabilities: {} },
					params: {}
				}
			}
		});

		await waitFor(() => {
			const idInput = screen.getByPlaceholderText('Model ID');
			expect(idInput).toBeDisabled();
			expect(idInput).toHaveValue('existing-model');
		});
	});

	it('renders base model selector in preset mode', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn(), preset: true }
		});

		await waitFor(() => {
			expect(screen.getByText('Base Model (From)')).toBeInTheDocument();
		});
	});

	it('shows save button text based on edit mode', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByText('Save & Create')).toBeInTheDocument();
		});
	});

	it('shows save button text in edit mode', async () => {
		render(ModelEditor, {
			props: {
				onSubmit: vi.fn(),
				edit: true,
				model: {
					id: 'existing-model',
					name: 'Existing Model',
					meta: { description: null, tags: [], capabilities: {} },
					params: {}
				}
			}
		});

		await waitFor(() => {
			expect(screen.getByText('Save & Update')).toBeInTheDocument();
		});
	});

	it('renders back button when onBack is provided', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn(), onBack: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByText('Back')).toBeInTheDocument();
		});
	});

	it('renders description section', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByText('Description')).toBeInTheDocument();
		});
	});

	it('renders system prompt section', async () => {
		render(ModelEditor, {
			props: { onSubmit: vi.fn() }
		});

		await waitFor(() => {
			expect(screen.getByText('System Prompt')).toBeInTheDocument();
		});
	});
});
