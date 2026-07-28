export { default as GuideHost } from './components/GuideHost.svelte';
export { guidedOverlayController } from './services/guide-controller';
export { guideState } from './stores/guide.store';

export type {
	GuideContext,
	GuideDefinition,
	GuideProgress,
	GuideRole,
	GuideRuntimeState,
	GuideStatus,
	GuideStep
} from './types/guide.types';
