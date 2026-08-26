export type GuideRole = 'student' | 'admin' | 'super_admin';

export type GuideStatus = 'not_started' | 'in_progress' | 'completed' | 'skipped' | 'dismissed';

export type GuideRuntimeStatus =
	| 'idle'
	| 'loading_context'
	| 'navigating'
	| 'waiting_for_target'
	| 'showing_step'
	| 'completed'
	| 'error';

export type GuidePlacement = 'top' | 'right' | 'bottom' | 'left';

export type GuideTargetPolicy = 'required' | 'optional' | 'deferred';

export type GuideStartSource = 'auto' | 'help-menu' | 'manual';

export interface GuideGroup {
	id: string;
	name: string;
}

export interface GuideContext {
	userId: string;
	role: GuideRole;
	groups: GuideGroup[];
	currentGroup?: GuideGroup;
	managedGroups: GuideGroup[];
	permissions: string[];
	features: Record<string, boolean>;
}

export interface GuideCondition {
	requiredPermissions?: string[];
	requiredFeatures?: string[];
	anyRequiredFeatures?: string[];
	requiredRoles?: GuideRole[];
	requiresCurrentGroup?: boolean;
	requiresAssignedGroups?: boolean;
	requiresManagedGroups?: boolean;
}

export interface GuideStepAction {
	type: 'click-target';
	targetId: string;
	skipIfTargetVisible?: string;
	waitAfterMs?: number;
}

export interface GuideStep {
	id: string;
	targetId?: string;
	highlightTargetIds?: string[];
	route?: string;
	title: string | ((context: GuideContext) => string);
	description: string | ((context: GuideContext) => string);
	summary?: boolean;
	actionLabel?: string;
	beforeTargetActions?: GuideStepAction[];
	placement?: GuidePlacement;
	condition?: GuideCondition;
	targetTimeoutMs?: number;
	targetPolicy?: GuideTargetPolicy;
	skipWhenTargetMissing?: boolean;
}

export interface GuideDefinition {
	id: string;
	version: string;
	role: GuideRole;
	steps: GuideStep[];
}

export interface GuideProgress {
	guideId: string;
	guideVersion: string;
	role: GuideRole;
	status: GuideStatus;
	currentStepId?: string;
	updatedAt: string;
}

export interface GuideStartOptions {
	source?: GuideStartSource;
	force?: boolean;
}

export interface GuideRuntimeState {
	isOpen: boolean;
	runtimeStatus: GuideRuntimeStatus;
	guide?: GuideDefinition;
	context?: GuideContext;
	visibleSteps: GuideStep[];
	currentStepIndex: number;
	currentStep?: GuideStep;
	targetElement?: HTMLElement;
	error?: string;
}

export interface GuideSessionUser {
	id: string;
	email: string;
	name?: string;
	role: string;
	profile_image_url?: string;
	permissions?: Record<string, unknown>;
	info?: Record<string, unknown>;
}

export interface GuideRawGroup {
	id: string;
	name: string;
	user_id?: string;
	created_by?: string;
	user_ids?: string[];
	permissions?: Record<string, unknown>;
	meta?: Record<string, unknown>;
	data?: Record<string, unknown>;
}

export interface GuideProgressRepository {
	load(userId: string, guideId: string): Promise<GuideProgress | null>;
	save(progress: GuideProgress): Promise<void>;
}
