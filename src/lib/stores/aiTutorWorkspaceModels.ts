import { writable, derived } from 'svelte/store';
import { aiTutorSelectedGroupId } from './index';

export interface WorkspaceModel {
	id: string;
	name: string;
	base_model_id: string | null;
	access_control?: { read?: { group_ids?: string[] } };
	user_id?: string;
}

export const aiTutorWorkspaceModels = writable<WorkspaceModel[]>([]);

export const aiTutorAllowedModelIds = derived(
	[aiTutorWorkspaceModels, aiTutorSelectedGroupId],
	([$models, $groupId]) => {
		if (!$groupId) return new Set<string>();
		const allowed = new Set<string>();
		for (const model of $models) {
			const groupIds = model.access_control?.read?.group_ids ?? [];
			if (groupIds.includes($groupId)) {
				allowed.add(model.id);
				allowed.add(model.name);
			}
		}
		return allowed;
	}
);

export async function loadWorkspaceModels(token: string): Promise<WorkspaceModel[]> {
	try {
		const res = await fetch('/api/models', {
			headers: { Authorization: `Bearer ${token}` }
		});
		if (!res.ok) throw new Error('Models fetch failed');
		const data = await res.json();
		const allModels = (Array.isArray(data?.data) ? data.data : [])
			.map((m: any) => ({
				id: m.id,
				name: m.name ?? m.id,
				base_model_id: m.info?.base_model_id ?? m.base_model_id ?? null,
				access_control: m.access_control ?? m.info?.access_control ?? null,
				user_id: m.user_id
			}));
		const excludedModels: { name: string; reason: string }[] = [];
		const homeworkNamePattern =
			/(homework|hw\s*#\s*\d+|hw[-_]\s*#?\s*\d+|hw\d+)/i;
		const models = allModels.filter((model: WorkspaceModel) => {
			const modelName = model.name ?? model.id;
			if (model.base_model_id == null) {
				excludedModels.push({ name: modelName, reason: 'no base_model_id' });
				return false;
			}
			if (!homeworkNamePattern.test(modelName)) {
				excludedModels.push({
					name: modelName,
					reason: 'name missing homework/hw pattern'
				});
				return false;
			}
			if (modelName.startsWith('Mastery')) {
				excludedModels.push({ name: modelName, reason: 'Mastery prefix' });
				return false;
			}
			return true;
		});
		console.log('[HomeworkFilter]-[GlobalStore]-[WorkspaceModels]:', {
			all: allModels.map((m) => m.name ?? m.id),
			selected: models.map((m) => m.name ?? m.id),
			excluded: excludedModels
		});
		aiTutorWorkspaceModels.set(models);
		return models;
	} catch (e) {
		console.error('Workspace models fetch failed:', e);
		aiTutorWorkspaceModels.set([]);
		return [];
	}
}
