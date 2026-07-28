import { adminGuide } from '../guides/admin.guide';
import { studentGuide } from '../guides/student.guide';
import { superAdminGuide } from '../guides/super-admin.guide';
import type { GuideDefinition, GuideRole } from '../types/guide.types';

export const guideRegistry: Record<GuideRole, GuideDefinition> = {
	student: studentGuide,
	admin: adminGuide,
	super_admin: superAdminGuide
};

export const getGuideForRole = (role: GuideRole): GuideDefinition => guideRegistry[role];
