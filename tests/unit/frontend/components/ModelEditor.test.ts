import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import TestWrapper from './TestWrapper.svelte';

// --- Mock $lib/stores ---
vi.mock('$lib/stores', () => ({
	models: writable([
		{ id: 'base-1', name: 'Base Model', owned_by: 'openai', preset: false },
		{ id: 'preset-1', name: 'Preset Model', owned_by: 'openai', preset: true }
	]),
	tools: writable([]),
	functions: writable([]),
	knowledge: writable([]),
	user: writable({ id: 'user-1', email: 'test@test.com', role: 'admin' }),
	config: writable({}),
	settings: writable({}),
	mobile: writable(false),
	WEBUI_NAME: writable('Test UI'),
	_: writable((k: string) => k)
}));

// --- Mock API modules ---
vi.mock('$lib/apis/tools', () => ({ getTools: vi.fn().mockResolvedValue([]) }));
vi.mock('$lib/apis/functions', () => ({ getFunctions: vi.fn().mockResolvedValue([]) }));
vi.mock('$lib/apis/knowledge', () => ({ getKnowledgeBases: vi.fn().mockResolvedValue([]) }));
vi.mock('$lib/apis/users', () => ({
	checkIfSuperAdmin: vi.fn().mockResolvedValue(false),
	getUsers: vi.fn().mockResolvedValue([])
}));
vi.mock('$lib/apis/groups', () => ({ getGroups: vi.fn().mockResolvedValue([]) }));

// --- Mock svelte-sonner ---
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn() }
}));

// --- Mock $app/navigation ---
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

describe('ModelEditor', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		localStorage.setItem('token', 'test-token');
	});

	it('renders name and id input fields', () => {
		render(TestWrapper, { props: { onSubmit: vi.fn() } });

		expect(screen.getByPlaceholderText('Model Name')).toBeTruthy();
		expect(screen.getByPlaceholderText('Model ID')).toBeTruthy();
	});

	it('auto-generates id from name', async () => {
		render(TestWrapper, { props: { onSubmit: vi.fn() } });

		const nameInput = screen.getByPlaceholderText('Model Name');
		await fireEvent.input(nameInput, { target: { value: 'My Model' } });

		const idInput = screen.getByPlaceholderText('Model ID') as HTMLInputElement;
		expect(idInput.value).toBe('my-model');
	});

	it('auto-generates id with special chars stripped', async () => {
		render(TestWrapper, { props: { onSubmit: vi.fn() } });

		const nameInput = screen.getByPlaceholderText('Model Name');
		await fireEvent.input(nameInput, { target: { value: 'GPT-4 (v2)!' } });

		const idInput = screen.getByPlaceholderText('Model ID') as HTMLInputElement;
		expect(idInput.value).toBe('gpt-4-v2');
	});

	it('disables id field in edit mode', () => {
		render(TestWrapper, {
			props: {
				onSubmit: vi.fn(),
				edit: true,
				model: {
					id: 'existing-model',
					name: 'Existing',
					meta: {
						profile_image_url: '/static/flower-violet.png',
						description: '',
						tags: [],
						capabilities: {}
					},
					params: {}
				}
			}
		});

		const idInput = screen.getByPlaceholderText('Model ID') as HTMLInputElement;
		expect(idInput.disabled).toBe(true);
	});

	it('shows toast for empty name but still calls onSubmit (known bug)', async () => {
		const onSubmit = vi.fn();
		render(TestWrapper, { props: { onSubmit } });

		const form = document.querySelector('form');
		if (form) {
			await fireEvent.submit(form);
		}

		const { toast } = await import('svelte-sonner');
		expect(toast.error).toHaveBeenCalled();
		// Known bug: onSubmit still called despite validation failure
		expect(onSubmit).toHaveBeenCalled();
	});

	it('shows toast for empty id but still calls onSubmit (known bug)', async () => {
		const onSubmit = vi.fn();
		render(TestWrapper, { props: { onSubmit } });

		const nameInput = screen.getByPlaceholderText('Model Name');
		await fireEvent.input(nameInput, { target: { value: 'Test' } });

		const idInput = screen.getByPlaceholderText('Model ID');
		await fireEvent.input(idInput, { target: { value: '' } });

		const form = document.querySelector('form');
		if (form) {
			await fireEvent.submit(form);
		}

		const { toast } = await import('svelte-sonner');
		expect(toast.error).toHaveBeenCalled();
		expect(onSubmit).toHaveBeenCalled();
	});

	it('initializes accessControl to PRIVATE for new models', async () => {
		const onSubmit = vi.fn();
		render(TestWrapper, { props: { onSubmit } });

		const nameInput = screen.getByPlaceholderText('Model Name');
		await fireEvent.input(nameInput, { target: { value: 'Test Model' } });

		const form = document.querySelector('form');
		if (form) {
			await fireEvent.submit(form);
		}

		const submittedData = onSubmit.mock.calls[0][0];
		expect(submittedData.access_control).toEqual({
			read: { group_ids: [], user_ids: [] },
			write: { group_ids: [], user_ids: [] }
		});
	});

	it('submits correct payload shape', async () => {
		const onSubmit = vi.fn();
		render(TestWrapper, { props: { onSubmit } });

		const nameInput = screen.getByPlaceholderText('Model Name');
		await fireEvent.input(nameInput, { target: { value: 'My Model' } });

		const form = document.querySelector('form');
		if (form) {
			await fireEvent.submit(form);
		}

		const submittedData = onSubmit.mock.calls[0][0];
		expect(submittedData).toHaveProperty('id');
		expect(submittedData).toHaveProperty('name');
		expect(submittedData).toHaveProperty('meta');
		expect(submittedData).toHaveProperty('params');
		expect(submittedData).toHaveProperty('access_control');
	});
});
