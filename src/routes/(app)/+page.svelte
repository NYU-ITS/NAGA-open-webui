<script lang="ts">
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	// Below are the Tutorial codes
	import { onMount } from 'svelte';
	import { Tour, run, TourTip } from 'svelte-tour';
	// step1, have a Tour Object, TourTip is customizable, and run is the entry function
	import type { TourStep } from 'svelte-tour';

	// Debug localStorage
	function debugStorage() {
		console.group('[Tour Debug] LocalStorage');
		console.log('Current tour state:', JSON.parse(localStorage.getItem('tourProgress') || '{}'));
		console.groupEnd();
	}

	// Initialize tour progress
	const tourSteps: TourStep[] = [
		{ id: 'model-selector', message: 'Select your AI model here' },
		{ id: 'chat-input', message: 'Type your messages here' },
		{ id: 'settings-btn', message: 'Configure settings here' },
		{ id: 'history-panel', message: 'Access conversation history' },
		{ id: 'help-btn', message: 'Get help anytime here' }
	];

	// Completion tracking
	let tourProgress = {
		completed: false,
		steps: tourSteps.reduce((acc, step) => ({ ...acc, [step.id]: false }), {})
	};

	onMount(() => {
		// Load saved progress
		const savedProgress = localStorage.getItem('tourProgress');
		if (savedProgress) {
			tourProgress = JSON.parse(savedProgress);
		}

		debugStorage(); // Initial debug log

		// Run tour if not completed
		if (!tourProgress.completed) {
			setTimeout(
				() =>
					run({
						filter: (step) => !tourProgress.steps[step.id]
					}),
				1000
			);
		}
		//step2, contitionally call run function
		//step3 is to have the Tour
	});

	function handleStepComplete(stepId: string) {
		tourProgress.steps[stepId] = true;

		// Check if all steps are completed
		tourProgress.completed = Object.values(tourProgress.steps).every(Boolean);

		localStorage.setItem('tourProgress', JSON.stringify(tourProgress));
		debugStorage();

		if (tourProgress.completed) {
			console.log('🎉 Tour fully completed!');
		}
	}

	function handleTourComplete() {
		// Final completion handler
		tourProgress.completed = true;
		localStorage.setItem('tourProgress', JSON.stringify(tourProgress));
		debugStorage();
	}
</script>

<Tour {TourTip}></Tour>
<!-- step2, have a TourTip Object -->
<!-- <Tour on:complete={handleTourComplete} on:step-complete={(e) => handleStepComplete(e.detail.id)} /> -->

<!-- Your existing layout -->
<Help />
<Chat />

<style global>
	:global(.tooltip) {
		z-index: 9999 !important; /* Force higher priority */
		background: #2ecc71 !important; /* Change tooltip color */
	}
</style>
