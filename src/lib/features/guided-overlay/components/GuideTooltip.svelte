<script lang="ts">
	import { browser } from '$app/environment';
	import { onDestroy, onMount, tick } from 'svelte';
	import type { GuidePlacement } from '../types/guide.types';

	export let rect: DOMRect | null = null;
	export let placement: GuidePlacement = 'bottom';
	export let ariaLabel = 'Guided tour';

	type TooltipPlacement = GuidePlacement | 'viewport-top' | 'viewport-bottom' | 'viewport-center';

	const TOOLTIP_WIDTH = 320;
	const ESTIMATED_TOOLTIP_HEIGHT = 188;
	const MARGIN = 10;
	const GAP = 14;

	let renderedWidth = TOOLTIP_WIDTH;
	let renderedHeight = ESTIMATED_TOOLTIP_HEIGHT;
	let dialogElement: HTMLElement;
	let previouslyFocusedElement: HTMLElement | null = null;

	const FOCUSABLE_SELECTOR = [
		'button:not([disabled])',
		'[href]',
		'input:not([disabled])',
		'select:not([disabled])',
		'textarea:not([disabled])',
		'[tabindex]:not([tabindex="-1"])'
	].join(',');

	const getFocusableElements = (): HTMLElement[] =>
		dialogElement
			? (Array.from(dialogElement.querySelectorAll(FOCUSABLE_SELECTOR)) as HTMLElement[])
			: [];

	const keepFocusInDialog = (event: FocusEvent) => {
		if (dialogElement && event.target instanceof Node && !dialogElement.contains(event.target)) {
			(getFocusableElements()[0] ?? dialogElement).focus();
		}
	};

	const trapKeyboardFocus = (event: KeyboardEvent) => {
		if (event.key !== 'Tab') return;

		const focusableElements = getFocusableElements();
		if (focusableElements.length === 0) {
			event.preventDefault();
			dialogElement.focus();
			return;
		}

		const firstElement = focusableElements[0];
		const lastElement = focusableElements[focusableElements.length - 1];

		if (event.shiftKey && document.activeElement === firstElement) {
			event.preventDefault();
			lastElement.focus();
		} else if (!event.shiftKey && document.activeElement === lastElement) {
			event.preventDefault();
			firstElement.focus();
		}
	};

	onMount(async () => {
		previouslyFocusedElement =
			document.activeElement instanceof HTMLElement ? document.activeElement : null;
		document.addEventListener('focusin', keepFocusInDialog);
		await tick();
		(getFocusableElements()[0] ?? dialogElement).focus();
	});

	onDestroy(() => {
		if (!browser) return;

		document.removeEventListener('focusin', keepFocusInDialog);
		if (previouslyFocusedElement?.isConnected) previouslyFocusedElement.focus();
	});

	const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

	const getPlacementCandidates = (preferredPlacement: GuidePlacement): TooltipPlacement[] => {
		const candidates: TooltipPlacement[] = [preferredPlacement];

		if (preferredPlacement === 'top' || preferredPlacement === 'bottom') {
			candidates.push('right', 'left', preferredPlacement === 'top' ? 'bottom' : 'top');
		} else {
			candidates.push('top', 'bottom', preferredPlacement === 'right' ? 'left' : 'right');
		}

		candidates.push('viewport-top', 'viewport-bottom', 'viewport-center');

		return candidates.filter((candidate, index) => candidates.indexOf(candidate) === index);
	};

	const getOverlapArea = (
		targetRect: DOMRect,
		top: number,
		left: number,
		width: number,
		height: number
	): number => {
		const overlapWidth = Math.max(
			0,
			Math.min(left + width, targetRect.right) - Math.max(left, targetRect.left)
		);
		const overlapHeight = Math.max(
			0,
			Math.min(top + height, targetRect.bottom) - Math.max(top, targetRect.top)
		);

		return overlapWidth * overlapHeight;
	};

	$: tooltipStyle = (() => {
		if (!browser || !rect) {
			return `top: 50%; left: 50%; width: min(${TOOLTIP_WIDTH}px, calc(100vw - ${
				MARGIN * 2
			}px)); max-height: calc(100vh - ${MARGIN * 2}px); transform: translate(-50%, -50%);`;
		}

		const targetRect = rect;
		const width = Math.min(renderedWidth || TOOLTIP_WIDTH, window.innerWidth - MARGIN * 2);
		const height = renderedHeight || ESTIMATED_TOOLTIP_HEIGHT;
		const maxLeft = window.innerWidth - width - MARGIN;
		const maxTop = window.innerHeight - height - MARGIN;

		const getPosition = (candidate: TooltipPlacement) => {
			let top = targetRect.bottom + GAP;
			let left = targetRect.left + targetRect.width / 2 - width / 2;

			if (candidate === 'top') {
				top = targetRect.top - height - GAP;
			} else if (candidate === 'right') {
				top = targetRect.top + targetRect.height / 2 - height / 2;
				left = targetRect.right + GAP;
			} else if (candidate === 'left') {
				top = targetRect.top + targetRect.height / 2 - height / 2;
				left = targetRect.left - width - GAP;
			} else if (candidate === 'viewport-top') {
				top = MARGIN;
				left = window.innerWidth / 2 - width / 2;
			} else if (candidate === 'viewport-bottom') {
				top = window.innerHeight - height - MARGIN;
				left = window.innerWidth / 2 - width / 2;
			} else if (candidate === 'viewport-center') {
				top = window.innerHeight / 2 - height / 2;
				left = window.innerWidth / 2 - width / 2;
			}

			left = clamp(left, MARGIN, Math.max(MARGIN, maxLeft));
			top = clamp(top, MARGIN, Math.max(MARGIN, maxTop));

			return {
				top,
				left,
				overlapArea: getOverlapArea(targetRect, top, left, width, height)
			};
		};

		const positions = getPlacementCandidates(placement).map(getPosition);
		const bestPosition =
			positions.find((position) => position.overlapArea === 0) ??
			positions.reduce((best, position) =>
				position.overlapArea < best.overlapArea ? position : best
			);

		return `top: ${bestPosition.top}px; left: ${bestPosition.left}px; width: min(${TOOLTIP_WIDTH}px, calc(100vw - ${
			MARGIN * 2
		}px)); max-height: calc(100vh - ${MARGIN * 2}px);`;
	})();
</script>

<section
	bind:this={dialogElement}
	bind:clientWidth={renderedWidth}
	bind:clientHeight={renderedHeight}
	class="fixed z-[9999] overflow-y-auto rounded-2xl border border-[rgba(106,0,168,0.32)] bg-white/90 p-3.5 text-gray-900 shadow-[0_20px_54px_rgba(76,0,122,0.18),0_4px_14px_rgba(17,24,39,0.07)] backdrop-blur-xl dark:border-[rgba(216,180,254,0.35)] dark:bg-gray-950/90 dark:text-gray-100"
	style={tooltipStyle}
	role="dialog"
	aria-modal="true"
	aria-label={ariaLabel}
	tabindex="-1"
	on:keydown={trapKeyboardFocus}
>
	<slot />
</section>
