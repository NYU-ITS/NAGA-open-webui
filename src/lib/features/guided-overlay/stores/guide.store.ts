import { get, writable } from 'svelte/store';

import type {
	GuideContext,
	GuideDefinition,
	GuideRuntimeState,
	GuideRuntimeStatus,
	GuideStep
} from '../types/guide.types';

export const initialGuideState: GuideRuntimeState = {
	isOpen: false,
	runtimeStatus: 'idle',
	visibleSteps: [],
	currentStepIndex: 0
};

export const guideState = writable<GuideRuntimeState>(initialGuideState);

export const setGuideStatus = (runtimeStatus: GuideRuntimeStatus) => {
	guideState.update((state) => ({
		...state,
		runtimeStatus,
		error: runtimeStatus === 'error' ? state.error : undefined
	}));
};

export const openGuide = (
	guide: GuideDefinition,
	context: GuideContext,
	visibleSteps: GuideStep[],
	currentStepIndex = 0
) => {
	guideState.set({
		isOpen: true,
		runtimeStatus: 'showing_step',
		guide,
		context,
		visibleSteps,
		currentStepIndex,
		currentStep: visibleSteps[currentStepIndex],
		targetElement: undefined
	});
};

export const setCurrentGuideStep = (currentStepIndex: number, targetElement?: HTMLElement) => {
	guideState.update((state) => ({
		...state,
		isOpen: true,
		runtimeStatus: targetElement ? 'showing_step' : state.runtimeStatus,
		currentStepIndex,
		currentStep: state.visibleSteps[currentStepIndex],
		targetElement,
		error: undefined
	}));
};

export const setGuideTarget = (targetElement?: HTMLElement) => {
	guideState.update((state) => ({
		...state,
		targetElement
	}));
};

export const setGuideError = (error: string) => {
	guideState.update((state) => ({
		...state,
		runtimeStatus: 'error',
		error
	}));
};

export const closeGuide = (runtimeStatus: GuideRuntimeStatus = 'idle') => {
	guideState.update((state) => ({
		...state,
		isOpen: false,
		runtimeStatus,
		targetElement: undefined
	}));
};

export const resetGuide = () => {
	guideState.set(initialGuideState);
};

export const getGuideState = (): GuideRuntimeState => get(guideState);
