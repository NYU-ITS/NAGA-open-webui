import { getGuideForRole } from '../config/guide-registry';
import { DEFAULT_TARGET_TIMEOUT_MS } from '../config/guide.constants';
import { loadGuideContext } from '../context/guide-context.service';
import { getVisibleGuideSteps } from './guide-condition.service';
import { prepareRouteForStep } from './guide-navigation.service';
import { guideProgressRepository } from './guide-progress.repository';
import { resolveTarget, scrollTargetIntoView, waitForTarget } from './guide-target.service';
import {
	closeGuide,
	getGuideState,
	openGuide,
	setCurrentGuideStep,
	setGuideError,
	setGuideStatus
} from '../stores/guide.store';
import type { GuideProgress, GuideStartOptions, GuideStatus, GuideStep } from '../types/guide.types';

const wait = (timeoutMs: number): Promise<void> =>
	new Promise((resolve) => {
		window.setTimeout(resolve, timeoutMs);
	});

const waitForStableResolvedTarget = async (
	targetId: string,
	targetElement: HTMLElement
): Promise<HTMLElement> => {
	let stableTarget = targetElement;

	for (const delayMs of [50, 150, 300]) {
		await wait(delayMs);
		stableTarget = resolveTarget(targetId) ?? stableTarget;
	}

	return stableTarget;
};

const createProgress = (status: GuideStatus, currentStepId?: string): GuideProgress | null => {
	const state = getGuideState();

	if (!state.guide || !state.context) {
		return null;
	}

	return {
		guideId: state.guide.id,
		guideVersion: state.guide.version,
		role: state.context.role,
		status,
		currentStepId,
		updatedAt: new Date().toISOString()
	};
};

const saveProgress = async (status: GuideStatus, currentStepId?: string): Promise<void> => {
	const progress = createProgress(status, currentStepId);

	if (!progress || !getGuideState().context) {
		return;
	}

	await guideProgressRepository.save(progress);
};

const shouldAutoStart = (
	progress: GuideProgress | null,
	guideVersion: string,
	options: GuideStartOptions
): boolean => {
	if (options.force) {
		return true;
	}

	if (!progress) {
		return true;
	}

	if (progress.guideVersion !== guideVersion) {
		return true;
	}

	return progress.status === 'in_progress';
};

const findStartIndex = (visibleSteps: GuideStep[], progress: GuideProgress | null): number => {
	if (!progress?.currentStepId) {
		return 0;
	}

	const index = visibleSteps.findIndex((step) => step.id === progress.currentStepId);
	return index >= 0 ? index : 0;
};

const shouldSkipMissingTarget = (step: GuideStep): boolean => {
	if (step.targetPolicy) {
		return step.targetPolicy !== 'required';
	}

	return step.skipWhenTargetMissing === true;
};

const isVirtualStep = (step: GuideStep): boolean => !step.targetId;

const runBeforeTargetActions = async (step: GuideStep): Promise<void> => {
	if (!step.beforeTargetActions?.length) {
		return;
	}

	for (const action of step.beforeTargetActions) {
		if (action.skipIfTargetVisible && resolveTarget(action.skipIfTargetVisible)) {
			continue;
		}

		if (action.type === 'click-target') {
			const target = await waitForTarget(action.targetId, DEFAULT_TARGET_TIMEOUT_MS);
			target?.click();
		}

		if (action.waitAfterMs) {
			await wait(action.waitAfterMs);
		}
	}
};

const activateStep = async (stepIndex: number): Promise<void> => {
	const state = getGuideState();
	const step = state.visibleSteps[stepIndex];

	if (!step) {
		await completeGuide();
		return;
	}

	await saveProgress('in_progress', step.id);
	setGuideStatus(step.route ? 'navigating' : 'waiting_for_target');
	setCurrentGuideStep(stepIndex);

	if (isVirtualStep(step)) {
		setGuideStatus('showing_step');
		return;
	}

	const targetId = step.targetId;
	if (!targetId) {
		setGuideError(`Could not find target id for guide step "${step.id}".`);
		return;
	}

	try {
		await prepareRouteForStep(step);
		setGuideStatus('waiting_for_target');
		await runBeforeTargetActions(step);

		let targetElement = await waitForTarget(
			targetId,
			step.targetTimeoutMs ?? DEFAULT_TARGET_TIMEOUT_MS
		);

		if (!targetElement) {
			console.warn(`[guided-overlay] Missing target for step "${step.id}"`);

			if (shouldSkipMissingTarget(step)) {
				await activateStep(stepIndex + 1);
				return;
			}

			setGuideError(`Could not find target for guide step "${step.id}".`);
			return;
		}

		if (step.route) {
			targetElement = await waitForStableResolvedTarget(targetId, targetElement);
		}

		scrollTargetIntoView(targetElement);
		setCurrentGuideStep(stepIndex, targetElement);
	} catch (error) {
		console.warn('[guided-overlay] Failed to activate step', error);
		setGuideError('The guide could not continue to the next step.');
	}
};

export const startGuide = async (options: GuideStartOptions = { source: 'auto' }): Promise<void> => {
	setGuideStatus('loading_context');

	const context = await loadGuideContext();
	if (!context) {
		setGuideStatus('idle');
		return;
	}

	const guide = getGuideForRole(context.role);
	const visibleSteps = getVisibleGuideSteps(guide, context);

	if (visibleSteps.length === 0) {
		setGuideStatus('idle');
		return;
	}

	const progress = await guideProgressRepository.load(context.userId, guide.id);

	if (!shouldAutoStart(progress, guide.version, options)) {
		setGuideStatus('idle');
		return;
	}

	const startIndex = options.force ? 0 : findStartIndex(visibleSteps, progress);
	openGuide(guide, context, visibleSteps, startIndex);
	await activateStep(startIndex);
};

export const nextStep = async (): Promise<void> => {
	const state = getGuideState();
	const nextIndex = state.currentStepIndex + 1;

	if (nextIndex >= state.visibleSteps.length) {
		await completeGuide();
		return;
	}

	await activateStep(nextIndex);
};

export const previousStep = async (): Promise<void> => {
	const state = getGuideState();
	const previousIndex = Math.max(state.currentStepIndex - 1, 0);

	await activateStep(previousIndex);
};

export const completeGuide = async (): Promise<void> => {
	await saveProgress('completed');
	closeGuide('completed');
};

export const skipGuide = async (): Promise<void> => {
	await saveProgress('skipped', getGuideState().currentStep?.id);
	closeGuide('idle');
};

export const dismissGuide = async (): Promise<void> => {
	await saveProgress('dismissed', getGuideState().currentStep?.id);
	closeGuide('idle');
};

export const restartGuide = async (): Promise<void> => {
	await startGuide({
		source: 'manual',
		force: true
	});
};

export const guidedOverlayController = {
	startGuide,
	nextStep,
	previousStep,
	completeGuide,
	skipGuide,
	dismissGuide,
	restartGuide
};
