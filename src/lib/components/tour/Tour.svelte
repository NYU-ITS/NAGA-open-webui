<script>
	import { onMount, beforeUpdate, afterUpdate } from 'svelte';
	import { stop, subscribe } from './index';

	export let TourTip;

	let active, items;
	let currentStep = 0;
	let shadowScreen; // Reference to our shadow DOM element
	let highlightBorder; // Add new reference for the border element
	$: atEnd = currentStep === items.length - 1;

	// Create shadow screen and highlight border on mount
	onMount(() => {
		console.log('Mounting shadow screen and highlight border');
		shadowScreen = document.createElement('div');
		shadowScreen.className = 'shadow-screen';
		document.body.appendChild(shadowScreen);

		highlightBorder = document.createElement('div');
		highlightBorder.className = 'highlight-border';
		document.body.appendChild(highlightBorder);

		return () => {
			// Cleanup on unmount
			if (shadowScreen && document.body.contains(shadowScreen)) {
				document.body.removeChild(shadowScreen);
			}
			if (highlightBorder && document.body.contains(highlightBorder)) {
				document.body.removeChild(highlightBorder);
			}
		};
	});

	// Update shadow screen when steps change
	beforeUpdate(() => {
		if (shadowScreen && active && items?.length) {
			updateShadowScreen(items[currentStep]);
		}
	});

	subscribe((store) => {
		({ active, items } = store);
	});

	function onClickNext() {
		if (atEnd) {
			stop();
			active = false; // Explicitly set active to false
			if (shadowScreen) {
				shadowScreen.remove(); // Remove the shadow screen element
			}
			if (highlightBorder) {
				highlightBorder.remove(); // Remove the highlight border element
			}
			return;
		}
		currentStep++;
	}

	function updateShadowScreen(step) {
		if (!shadowScreen || !step || !highlightBorder) return;

		const rect = step.getBoundingClientRect();
		const padding = 2; // Padding around the element

		// Update the highlight border position
		highlightBorder.style.left = `${rect.left - padding}px`;
		highlightBorder.style.top = `${rect.top - padding}px`;
		highlightBorder.style.width = `${rect.width + padding * 2}px`;
		highlightBorder.style.height = `${rect.height + padding * 2}px`;

		// Keep the original clip-path for the shadow
		shadowScreen.style.clipPath = `
      polygon(
        0px 0px,
        0px 100vh,
        100vw 100vh,
        100vw 0px,
        0px 0px,
        
        /* Cutout with rounded corners */
        ${rect.left}px ${rect.top + padding}px,
        ${rect.left + padding}px ${rect.top}px,
        ${rect.right - padding}px ${rect.top}px,
        ${rect.right}px ${rect.top + padding}px,
        ${rect.right}px ${rect.bottom - padding}px,
        ${rect.right - padding}px ${rect.bottom}px,
        ${rect.left + padding}px ${rect.bottom}px,
        ${rect.left}px ${rect.bottom - padding}px,
        ${rect.left}px ${rect.top + padding}px
      )
    `;
	}

	function getTooltipStyle(step) {
		const TOOLTIP_WIDTH = 200; // Match the width from TourTip.svelte
		const rect = step.getBoundingClientRect();
		const itemCenter = rect.left + rect.width / 2;
		let left = itemCenter - TOOLTIP_WIDTH / 2;

		// Boundary checks
		left = Math.max(0, Math.min(left, window.innerWidth - TOOLTIP_WIDTH));

		console.log('Tooltip positioning:', {
			itemCenter,
			left,
			bottom: rect.bottom + 10,
			tooltipWidth: TOOLTIP_WIDTH,
			elementWidth: rect.width
		});

		// Return direct positioning instead of transform
		return `
        left: ${left}px;
        top: ${rect.bottom + 10}px;
    `;
	}
</script>

{#if active && items && items.length}
	<div class="tourtip" style={getTooltipStyle(items[currentStep])}>
		<TourTip {atEnd} message={items[currentStep].getAttribute('data-tour')} {onClickNext} />
	</div>
{/if}

<style>
	/* Global style for the shadow screen */
	:global(.shadow-screen) {
		position: fixed;
		top: 0;
		left: 0;
		width: 100vw;
		height: 100vh;
		background-color: rgba(0, 0, 0, 0.75);
		z-index: 9998;
		pointer-events: none;
		transition: clip-path 0.3s ease-out;
		outline-offset: -2px;
	}

	:global(.highlight-border) {
		position: fixed;
		border: 2px solid #ab82c5;
		border-radius: 5px;
		z-index: 9999;
		pointer-events: none;
		transition: all 0.3s ease-out;
		box-sizing: border-box;
	}

	.tourtip {
		background: #fff;
		border-radius: 4px;
		position: fixed;
		z-index: 9999;
		box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
	}
</style>
