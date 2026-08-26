import type { GuideContext, GuideDefinition, GuideStep } from '../types/guide.types';

export const isStepAvailable = (step: GuideStep, context: GuideContext): boolean => {
	const condition = step.condition;

	if (!condition) {
		return true;
	}

	if (condition.requiredRoles && !condition.requiredRoles.includes(context.role)) {
		return false;
	}

	if (condition.requiresCurrentGroup && !context.currentGroup) {
		return false;
	}

	if (condition.requiresAssignedGroups && context.groups.length === 0) {
		return false;
	}

	if (condition.requiresManagedGroups && context.managedGroups.length === 0) {
		return false;
	}

	if (
		condition.requiredPermissions?.some((permission) => !context.permissions.includes(permission))
	) {
		return false;
	}

	if (condition.requiredFeatures?.some((feature) => context.features[feature] !== true)) {
		return false;
	}

	if (
		condition.anyRequiredFeatures &&
		!condition.anyRequiredFeatures.some((feature) => context.features[feature] === true)
	) {
		return false;
	}

	return true;
};

export const getVisibleGuideSteps = (
	guide: GuideDefinition,
	context: GuideContext
): GuideStep[] => {
	return guide.steps.filter((step) => isStepAvailable(step, context));
};
