<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	import GuidedOverlay from './GuidedOverlay.svelte';
	import { GUIDE_START_EVENT } from '../config/guide.constants';
	import { guidedOverlayController } from '../services/guide-controller';
	import { guideState } from '../stores/guide.store';

	const startFromHelpMenu = () => {
		guidedOverlayController.startGuide({
			source: 'help-menu',
			force: true
		});
	};

	onMount(() => {
		guidedOverlayController.startGuide({
			source: 'auto'
		});

		window.addEventListener(GUIDE_START_EVENT, startFromHelpMenu);
	});

	onDestroy(() => {
		window.removeEventListener(GUIDE_START_EVENT, startFromHelpMenu);
	});
</script>

{#if $guideState.isOpen && $guideState.currentStep && $guideState.context}
	<GuidedOverlay
		targetElement={$guideState.targetElement}
		step={$guideState.currentStep}
		context={$guideState.context}
		runtimeStatus={$guideState.runtimeStatus}
		currentStepIndex={$guideState.currentStepIndex}
		totalSteps={$guideState.visibleSteps.length}
		on:next={() => guidedOverlayController.nextStep()}
		on:back={() => guidedOverlayController.previousStep()}
		on:skip={() => guidedOverlayController.skipGuide()}
		on:close={() => guidedOverlayController.dismissGuide()}
		on:finish={() => guidedOverlayController.completeGuide()}
		on:restart={() => guidedOverlayController.restartGuide()}
	/>
{/if}
