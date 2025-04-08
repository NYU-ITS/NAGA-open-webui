<script lang="ts">
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	// Below are the Tutorial codes
	import { onMount } from 'svelte';
	import { Tour, run, subscribe } from 'svelte-tour';

	import TourTip from '$lib/components/CustomTourTip.svelte';
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

	function getScrimStyle(step) {
    const boundingRect = step.getBoundingClientRect();
    const left = boundingRect.left;
    const right = left + boundingRect.width;
    const top = boundingRect.top;
    const bottom = top + boundingRect.height;
    const { innerHeight, innerWidth } = window;
    return `
      clip-path: polygon(
        0px 0px,
        0px ${innerHeight}px,
        ${left}px ${innerHeight}px,
        ${left}px ${top}px,
        ${right}px ${top}px,
        ${right}px ${bottom}px,
        ${left}px ${bottom}px,
        ${left}px ${innerHeight}px,
        ${innerWidth}px ${innerHeight}px,
        ${innerWidth}px 0px
      );
    `;
  }
	onMount(() => {
		// 1. Load saved progress
		const savedProgress = localStorage.getItem('tourProgress');
		if (savedProgress) {
			tourProgress = JSON.parse(savedProgress);
		}

		debugStorage(); // Initial debug log

		// 2. Subscribe to tour updates for positioning
		const unsubscribe = subscribe(store => {
      if (store.active && store.items?.length) {
        const style = getScrimStyle(items[currentStep]);
        document.documentElement.style.setProperty(
          '--dynamic-clip-path', 
          style.match(/clip-path:\s*(.*?);/)[1]
        );
      }
    });

		// 3. Run tour if not completed
		if (!tourProgress.completed) {
			setTimeout(() => {
				run({
					filter: (step) => !tourProgress.steps[step.id]
				});
			}, 1000);
		}

		return () => unsubscribe(); // Cleanup subscription
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
	/* ===== Scrim (Overlay) ===== */
	/* Violet border for rectangular highlight */
	:global(.scrim) {
		position: relative;
		/* Ensure scrim uses the same clip-path */
		clip-path: var(--dynamic-clip-path);
	}

	:global(.scrim)::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		/* Solid violet border matching clip-path */
		box-shadow:
			0 0 0 3px #8900e1 inset,
			0 0 0 100vmax rgba(51, 51, 51, 0.75);
		/* Inherit clip-path */
		clip-path: inherit;
		pointer-events: none;
	}

	/* Light mode variant */
	:global(.light-mode .scrim) {
		background: rgba(255, 255, 255, 0.85) !important;
	}

	/* ===== Tooltip ===== */
	:global(.tooltip) {
		box-shadow:
			0 2px 4px 0 rgba(0, 0, 0, 0.1),
			0 0 0 1px rgba(0, 0, 0, 0.05) !important;
		border-radius: 8px !important;
		background: white !important;
		z-index: 9999 !important;
	}

	:global(.scrim)::after {
		content: '';
		position: absolute;
		top: var(--clip-top, 0);
		left: var(--clip-left, 0);
		width: var(--clip-width, 0);
		height: var(--clip-height, 0);
		border: 3px solid #8900e1;
		border-radius: 8px;
		pointer-events: none;
		box-sizing: border-box;
	}
</style>
