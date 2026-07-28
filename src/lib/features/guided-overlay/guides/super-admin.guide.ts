import { GUIDE_VERSION, SUPER_ADMIN_GUIDE_ID } from '../config/guide.constants';
import type { GuideDefinition } from '../types/guide.types';

export const superAdminGuide: GuideDefinition = {
	id: SUPER_ADMIN_GUIDE_ID,
	version: GUIDE_VERSION,
	role: 'super_admin',
	steps: [
		{
			id: 'super-admin-welcome',
			targetId: 'admin-panel',
			title: 'Hello, Super Admin',
			description:
				'You have platform-level access to manage groups, users, modules, models, policies, and system settings.',
			placement: 'right',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'super-admin-platform-navigation',
			targetId: 'platform-navigation',
			title: 'Platform Navigation',
			description: 'Use the Admin area to review platform-wide configuration and user access.',
			placement: 'right',
			targetPolicy: 'optional',
			skipWhenTargetMissing: true
		},
		{
			id: 'super-admin-help',
			targetId: 'help-menu',
			title: 'Help and Guided Tour',
			description: 'You can reopen this guide from the Help menu at any time.',
			placement: 'top',
			targetPolicy: 'optional'
		}
	]
};
