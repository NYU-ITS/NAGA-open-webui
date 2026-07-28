import { browser } from '$app/environment';

import type { GuideGroup, GuideRawGroup, GuideSessionUser } from '../types/guide.types';

const GROUP_SELECTION_KEYS = ['ai_tutor_last_selected_group_id', 'student_dashboard_last_selected_group_id'];

export const normalizeGroups = (groups: GuideRawGroup[] | null | undefined): GuideGroup[] => {
	return (groups ?? [])
		.filter((group) => Boolean(group?.id && group?.name))
		.map((group) => ({
			id: group.id,
			name: group.name
		}));
};

export const resolveCurrentGroup = (groups: GuideGroup[]): GuideGroup | undefined => {
	if (!browser) {
		return groups.length === 1 ? groups[0] : undefined;
	}

	for (const key of GROUP_SELECTION_KEYS) {
		const selectedGroupId = localStorage.getItem(key);
		const selectedGroup = groups.find((group) => group.id === selectedGroupId);

		if (selectedGroup) {
			return selectedGroup;
		}
	}

	return groups.length === 1 ? groups[0] : undefined;
};

export const resolveManagedGroups = (
	groups: GuideGroup[],
	currentUser: GuideSessionUser,
	isSuperAdmin: boolean
): GuideGroup[] => {
	if (isSuperAdmin || currentUser.role === 'admin' || currentUser.info?.is_co_admin === true) {
		return groups;
	}

	return [];
};
