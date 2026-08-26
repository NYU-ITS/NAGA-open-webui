import { browser } from '$app/environment';
import { getGroups } from '$lib/apis/groups';
import { config } from '$lib/stores';
import { get } from 'svelte/store';

import { resolveFeatureFlags, flattenEnabledPermissions } from './feature-context.adapter';
import { normalizeGroups, resolveCurrentGroup, resolveManagedGroups } from './group-context.adapter';
import { getCurrentGuideUser, isGuideSuperAdmin, resolveGuideRole } from './user-context.adapter';
import type { GuideContext, GuideRawGroup } from '../types/guide.types';

export const loadGuideContext = async (): Promise<GuideContext | null> => {
	if (!browser) {
		return null;
	}

	const currentUser = getCurrentGuideUser();
	if (!currentUser?.id) {
		return null;
	}

	if (!['user', 'admin', 'student', 'super_admin'].includes(currentUser.role)) {
		return null;
	}

	const token = localStorage.getItem('token') ?? '';
	const [rawGroups, superAdmin] = await Promise.all([
		token
			? getGroups(token).catch((error) => {
					console.warn('[guided-overlay] Unable to load groups', error);
					return [];
				})
			: Promise.resolve([]),
		isGuideSuperAdmin(currentUser)
	]);
	const groups = normalizeGroups(rawGroups as GuideRawGroup[]);
	const managedGroups = resolveManagedGroups(groups, currentUser, superAdmin);
	const role = resolveGuideRole(currentUser, managedGroups, superAdmin);
	const hasFullAdminAccess = currentUser.role === 'admin' || superAdmin;
	const appConfig = get(config) as Record<string, unknown> | undefined;

	return {
		userId: currentUser.id,
		role,
		groups,
		currentGroup: resolveCurrentGroup(groups),
		managedGroups,
		permissions: flattenEnabledPermissions(currentUser.permissions),
		features: resolveFeatureFlags(appConfig, currentUser.permissions, hasFullAdminAccess)
	};
};
