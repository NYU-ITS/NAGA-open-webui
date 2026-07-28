import { browser } from '$app/environment';
import { checkIfSuperAdmin } from '$lib/apis/users';
import { user } from '$lib/stores';
import { get } from 'svelte/store';

import type { GuideGroup, GuideRole, GuideSessionUser } from '../types/guide.types';

export const getCurrentGuideUser = (): GuideSessionUser | undefined => {
	return get(user) as GuideSessionUser | undefined;
};

export const isGuideSuperAdmin = async (
	currentUser: GuideSessionUser | undefined = getCurrentGuideUser()
): Promise<boolean> => {
	if (!browser || !currentUser?.email) {
		return false;
	}

	const token = localStorage.getItem('token');
	if (!token) {
		return false;
	}

	try {
		return Boolean(await checkIfSuperAdmin(token, currentUser.email));
	} catch (error) {
		console.warn('[guided-overlay] Unable to resolve super admin status', error);
		return false;
	}
};

export const resolveGuideRole = (
	currentUser: GuideSessionUser,
	managedGroups: GuideGroup[],
	isSuperAdmin: boolean
): GuideRole => {
	if (isSuperAdmin) {
		return 'super_admin';
	}

	if (currentUser.role === 'admin' || currentUser.info?.is_co_admin === true || managedGroups.length > 0) {
		return 'admin';
	}

	return 'student';
};
