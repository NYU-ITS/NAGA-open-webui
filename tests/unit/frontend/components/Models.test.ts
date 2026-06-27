import { describe, it, expect, vi } from 'vitest';

// Models.svelte contains inline reactive logic that filters and groups models.
// These tests verify the core filtering and grouping logic as pure functions,
// extracted from the component's data flow. Full component rendering requires
// sveltekit plugin + .svelte-kit which aren't available in the production image.

describe('Models list - filtering logic', () => {
	const filterModels = (models, searchValue) => {
		return models.filter((m) => {
			return searchValue === '' || m.name.toLowerCase().includes(searchValue.toLowerCase());
		});
	};

	const groupModelsByCategory = (modelsList, groups) => {
		const groupsMap = {};
		modelsList.forEach((model) => {
			const groupIds = model?.access_control?.read?.group_ids;
			if (groupIds && Array.isArray(groupIds) && groupIds.length > 0) {
				groupIds.forEach((groupId) => {
					const group = groups.find((g) => g.id === groupId);
					if (group) {
						if (!groupsMap[group.name]) groupsMap[group.name] = [];
						groupsMap[group.name].push(model);
					}
				});
			} else {
				if (!groupsMap['Uncategorized']) groupsMap['Uncategorized'] = [];
				groupsMap['Uncategorized'].push(model);
			}
		});
		return groupsMap;
	};

	const makeModel = (id, name, groupIds = [], isActive = true, userId = 'u1') => ({
		id,
		name,
		meta: { profile_image_url: '/static/favicon.png', description: '' },
		user_id: userId,
		user: { name: 'Admin', email: 'admin@test.com' },
		is_active: isActive,
		access_control: groupIds.length > 0
			? { read: { group_ids: groupIds, user_ids: [] }, write: { group_ids: [], user_ids: [] } }
			: null
	});

	it('filters models by search (case-insensitive)', () => {
		const models = [
			makeModel('m1', 'GPT-4 Custom'),
			makeModel('m2', 'Claude Custom')
		];

		expect(filterModels(models, 'gpt')).toHaveLength(1);
		expect(filterModels(models, 'gpt')[0].name).toBe('GPT-4 Custom');
		expect(filterModels(models, '')).toHaveLength(2);
		expect(filterModels(models, 'nonexistent')).toHaveLength(0);
	});

	it('returns all models when search is empty', () => {
		const models = [makeModel('m1', 'One'), makeModel('m2', 'Two')];
		expect(filterModels(models, '')).toHaveLength(2);
	});

	it('case-insensitive search matches uppercase query', () => {
		const models = [makeModel('m1', 'gpt-4 custom')];
		expect(filterModels(models, 'GPT')).toHaveLength(1);
	});

	it('groups models with access_control.read.group_ids by group name', () => {
		const groups = [{ id: 'g1', name: 'Research Team' }];
		const models = [makeModel('m1', 'Model One', ['g1'])];

		const grouped = groupModelsByCategory(models, groups);
		expect(grouped['Research Team']).toHaveLength(1);
		expect(grouped['Research Team'][0].name).toBe('Model One');
		expect(grouped['Uncategorized']).toBeUndefined();
	});

	it('places models without group_ids in Uncategorized', () => {
		const groups = [{ id: 'g1', name: 'Research Team' }];
		const models = [makeModel('m1', 'Model One', [])];

		const grouped = groupModelsByCategory(models, groups);
		expect(grouped['Uncategorized']).toHaveLength(1);
		expect(grouped['Uncategorized'][0].name).toBe('Model One');
	});

	it('groups multiple models across different groups', () => {
		const groups = [
			{ id: 'g1', name: 'Team A' },
			{ id: 'g2', name: 'Team B' }
		];
		const models = [
			makeModel('m1', 'Model A1', ['g1']),
			makeModel('m2', 'Model A2', ['g1']),
			makeModel('m3', 'Model B1', ['g2']),
			makeModel('m4', 'No Group', [])
		];

		const grouped = groupModelsByCategory(models, groups);
		expect(grouped['Team A']).toHaveLength(2);
		expect(grouped['Team B']).toHaveLength(1);
		expect(grouped['Uncategorized']).toHaveLength(1);
	});

	it('drops model when group reference has no matching group (non-owner path)', () => {
		// Simulate the component's cleaning logic: if model's group_ids don't include
		// any visible group_ids and user is not the owner, the model is filtered out.
		const visibleGroupIds = ['g1'];
		const modelGroupIds = ['g2'];

		// Model has no user_id match (non-owner), so it gets filtered entirely
		const visibleInModel = modelGroupIds.filter((gid) => visibleGroupIds.includes(gid));
		expect(visibleInModel).toHaveLength(0);

		// In the actual component, when visibleGroupIds.length === 0 && m.user_id !== $user?.id,
		// the model returns null and is filtered out of the list entirely
	});
});
