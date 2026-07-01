import { describe, expect, it, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
	aiTutorAllowedModelIds,
	aiTutorWorkspaceModels,
	loadWorkspaceModels,
	type WorkspaceModel
} from '../aiTutorWorkspaceModels';
import { aiTutorSelectedGroupId } from '../index';

describe('aiTutorWorkspaceModels store', () => {
	beforeEach(() => {
		aiTutorWorkspaceModels.set([]);
		aiTutorSelectedGroupId.set('');
		vi.restoreAllMocks();
	});

	it('loads and filters workspace models for homework flow', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			json: async () => ({
				data: [
					{
						id: 'ok-1',
						name: 'Homework Algebra Tutor',
						info: {
							base_model_id: 'base-1'
						},
						access_control: { read: { group_ids: ['group-a'] } }
					},
					{
						id: 'no-base',
						name: 'Homework Missing Base'
					},
					{
						id: 'not-homework',
						name: 'General Purpose Tutor',
						base_model_id: 'base-2'
					},
					{
						id: 'mastery',
						name: 'Mastery Homework Model',
						base_model_id: 'base-3'
					}
				]
			})
		});
		vi.stubGlobal('fetch', fetchMock);
		vi.spyOn(console, 'log').mockImplementation(() => {});

		const models = await loadWorkspaceModels('token-123');

		expect(fetchMock).toHaveBeenCalledWith('/api/models', {
			headers: { Authorization: 'Bearer token-123' }
		});
		expect(models).toHaveLength(1);
		expect(models[0].id).toBe('ok-1');
		expect(get(aiTutorWorkspaceModels)).toEqual(models);
	});

	it('builds allowed model ids set from selected group and model access control', () => {
		const models: WorkspaceModel[] = [
			{
				id: 'm1',
				name: 'Homework Model One',
				base_model_id: 'b1',
				access_control: { read: { group_ids: ['g1'] } }
			},
			{
				id: 'm2',
				name: 'Homework Model Two',
				base_model_id: 'b2',
				access_control: { read: { group_ids: ['g2'] } }
			}
		];

		aiTutorWorkspaceModels.set(models);
		aiTutorSelectedGroupId.set('g1');

		const allowed = get(aiTutorAllowedModelIds);
		expect(allowed.has('m1')).toBe(true);
		expect(allowed.has('Homework Model One')).toBe(true);
		expect(allowed.has('m2')).toBe(false);
		expect(allowed.has('Homework Model Two')).toBe(false);
	});

	it('returns empty state when model loading fails', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
		vi.spyOn(console, 'error').mockImplementation(() => {});

		const models = await loadWorkspaceModels('token-123');

		expect(models).toEqual([]);
		expect(get(aiTutorWorkspaceModels)).toEqual([]);
	});
});
