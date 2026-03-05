<script lang="ts">
	import { onMount, onDestroy, tick, afterUpdate } from 'svelte';
	import { fade } from 'svelte/transition';
	import {
		tutorialState,
		dismissTutorial,
		nextTutorialStep,
		SETUP_LLM_STEPS
	} from '$lib/stores/tutorial';

	// ── Derived state ─────────────────────────────────────────────────────────
	$: steps = SETUP_LLM_STEPS;
	$: step = steps[$tutorialState.currentStep] ?? steps[0];
	$: isLast = $tutorialState.currentStep === steps.length - 1;
	// freeInteract: overlay is non-blocking — user can type in inputs / code editor
	$: freeInteract = step?.freeInteract ?? false;
	// selectAll: querySelectorAll is used — every match is spotlighted, any click advances
	$: selectAll = step?.selectAll ?? false;

	// ── Spotlight geometry ────────────────────────────────────────────────────
	const PAD = 8;

	// primaryRect: the one element whose click advances the tutorial.
	// Used for four-rect blocking in normal (non-freeInteract) mode.
	let primaryRect = { top: 0, left: 0, width: 0, height: 0 };

	// allSpotlightRects: all elements to visually highlight (primary + extras).
	// Used for SVG holes (freeInteract) and purple outlines.
	let allSpotlightRects: Array<{ top: number; left: number; width: number; height: number }> = [];

	let hasTarget = false;
	let rafId: number;

	// Viewport size — kept in sync with resize
	let vw = 0;
	let vh = 0;

	// Four-rect blocking geometry — derived from primaryRect
	$: spotTop = primaryRect.top - PAD;
	$: spotLeft = primaryRect.left - PAD;
	$: spotW = primaryRect.width + PAD * 2;
	$: spotH = primaryRect.height + PAD * 2;
	$: topH = Math.max(0, spotTop);
	$: bottomY = spotTop + spotH;
	$: bottomH = Math.max(0, vh - bottomY);
	$: leftW = Math.max(0, spotLeft);
	$: rightX = spotLeft + spotW;
	$: rightW = Math.max(0, vw - rightX);

	// ── Click-listener management ─────────────────────────────────────────────
	// Array-based so multiple elements (e.g. selectAll) can all be wired at once.
	// Any one of them firing advances the tutorial and all listeners are removed.
	let currentListeners: Array<{ el: Element; fn: () => void }> = [];

	function removeClickListeners() {
		for (const { el, fn } of currentListeners) {
			el.removeEventListener('click', fn);
		}
		currentListeners = [];
	}

	function attachClickListeners(els: Element[]) {
		removeClickListeners();
		const advance = () => {
			if (isLast) dismissTutorial();
			else nextTutorialStep();
		};
		for (const el of els) {
			el.addEventListener('click', advance);
			currentListeners.push({ el, fn: advance });
		}
	}

	// ── Window-event advance (advanceOn) ──────────────────────────────────────
	// When a step sets advanceOn, we listen for a custom window event instead of
	// a click — e.g. waiting for a successful API response before proceeding.
	let windowAdvanceListener: { event: string; fn: () => void } | null = null;

	function removeWindowAdvanceListener() {
		if (windowAdvanceListener) {
			window.removeEventListener(windowAdvanceListener.event, windowAdvanceListener.fn);
			windowAdvanceListener = null;
		}
	}

	function attachWindowAdvanceListener(eventName: string) {
		removeWindowAdvanceListener();
		const advance = () => {
			removeWindowAdvanceListener();
			if (isLast) dismissTutorial();
			else nextTutorialStep();
		};
		windowAdvanceListener = { event: eventName, fn: advance };
		window.addEventListener(eventName, advance);
	}

	// ── Target tracking ───────────────────────────────────────────────────────
	$: if ($tutorialState.active && step) {
		tick().then(() => trackTarget());
	}

	function trackTarget() {
		cancelAnimationFrame(rafId);
		removeClickListeners();
		removeWindowAdvanceListener();

		if (!step?.selector) {
			hasTarget = false;
			allSpotlightRects = [];
			return;
		}

		if (step.selectAll) {
			// ── selectAll: highlight every matching element, any click advances ──
			const allEls = Array.from(document.querySelectorAll(step.selector));
			if (allEls.length === 0) {
				hasTarget = false;
				allSpotlightRects = [];
				rafId = requestAnimationFrame(trackTarget);
				return;
			}
			const rects = allEls.map((el) => {
				const r = el.getBoundingClientRect();
				return { top: r.top, left: r.left, width: r.width, height: r.height };
			});
			allSpotlightRects = rects;
			primaryRect = rects[0]; // used for tooltip positioning
			hasTarget = true;
			attachClickListeners(allEls);
		} else {
			// ── single element (normal / freeInteract) ────────────────────────
			const primaryEl = document.querySelector(step.selector);
			if (!primaryEl) {
				hasTarget = false;
				allSpotlightRects = [];
				rafId = requestAnimationFrame(trackTarget);
				return;
			}

			const pr = primaryEl.getBoundingClientRect();
			primaryRect = { top: pr.top, left: pr.left, width: pr.width, height: pr.height };

			// Extra visual spotlights (best-effort — skip missing ones)
			const extraRects = (step.extraSpotlights ?? [])
				.map((sel) => {
					const el = document.querySelector(sel);
					if (!el) return null;
					const r = el.getBoundingClientRect();
					return { top: r.top, left: r.left, width: r.width, height: r.height };
				})
				.filter(
					(r): r is { top: number; left: number; width: number; height: number } => r !== null
				);

			allSpotlightRects = [primaryRect, ...extraRects];
			hasTarget = true;
			if (step.advanceOn) {
				// Element is spotlighted so the user knows what to interact with,
				// but the tutorial only advances when the named window event fires
				// (e.g. after a successful API save response).
				attachWindowAdvanceListener(step.advanceOn);
			} else {
				attachClickListeners([primaryEl]);
			}
		}
	}

	// ── Window events ─────────────────────────────────────────────────────────
	function onResize() {
		vw = window.innerWidth;
		vh = window.innerHeight;
		trackTarget(); // recompute all bounding rects after layout change
	}

	function onKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') dismissTutorial();
	}

	onMount(() => {
		vw = window.innerWidth;
		vh = window.innerHeight;
		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('resize', onResize);
	});

	onDestroy(() => {
		window.removeEventListener('keydown', onKeyDown);
		window.removeEventListener('resize', onResize);
		cancelAnimationFrame(rafId);
		removeClickListeners();
		removeWindowAdvanceListener();
	});

	// ── Tooltip sizing & positioning ──────────────────────────────────────────
	let tooltipEl: HTMLElement;
	let tooltipHeight = 240;

	afterUpdate(() => {
		if (tooltipEl) tooltipHeight = tooltipEl.offsetHeight;
	});

	$: tooltipTop = (() => {
		if (!hasTarget) return '50%';
		// freeInteract: pin to top-right corner so the tooltip never overlaps editor inputs
		if (freeInteract) return '16px';
		const placement = step?.tooltipPlacement ?? 'auto';
		const above = Math.max(8, spotTop - 16 - tooltipHeight);
		const below = primaryRect.top + primaryRect.height + PAD + 16;
		if (placement === 'above') return `${above}px`;
		if (placement === 'below') return `${below}px`;
		return below + tooltipHeight < window.innerHeight ? `${below}px` : `${above}px`;
	})();

	$: tooltipLeft = (() => {
		if (!hasTarget) return '50%';
		// freeInteract: right-aligned, 16 px from screen edge
		if (freeInteract) return `${Math.max(8, window.innerWidth - 360 - 16)}px`;
		const l = primaryRect.left;
		const maxLeft = window.innerWidth - 360;
		return `${Math.min(Math.max(l, 12), maxLeft)}px`;
	})();

	$: tooltipTransform = hasTarget ? 'none' : 'translate(-50%, -50%)';

	// ── Copy-code helper ──────────────────────────────────────────────────────
	let copySuccess = false;
	async function copyCode() {
		if (!step.copyText) return;
		await navigator.clipboard.writeText(step.copyText);
		copySuccess = true;
		setTimeout(() => (copySuccess = false), 2000);
	}
</script>

{#if $tutorialState.active}
	{#if hasTarget}
		{#if freeInteract || selectAll}
			<!--
				SVG mask: punches a transparent hole for every spotlighted element.

				freeInteract — pointer-events-none: entire page stays interactive
				  (user must type in inputs, paste code, etc.)

				selectAll — default SVG pointer-events (visiblePainted): the opaque
				  dim layer blocks clicks outside the holes; only the spotlighted
				  elements (holes) pass clicks through to the underlying DOM.
			-->
			<svg
				class="fixed inset-0 z-[9990] {freeInteract ? 'pointer-events-none' : ''}"
				style="width:{vw}px; height:{vh}px;"
				aria-hidden="true"
			>
				<defs>
					<mask id="tut-spotlight-mask">
						<!-- White = keep dim layer opaque; Black = punch a hole (reveal element) -->
						<rect x="0" y="0" width="100%" height="100%" fill="white" />
						{#each allSpotlightRects as r}
							<rect
								x={r.left - PAD}
								y={r.top - PAD}
								width={r.width + PAD * 2}
								height={r.height + PAD * 2}
								rx="6"
								fill="black"
							/>
						{/each}
					</mask>
				</defs>
				<rect
					x="0"
					y="0"
					width="100%"
					height="100%"
					fill="rgba(0,0,0,0.55)"
					mask="url(#tut-spotlight-mask)"
				/>
			</svg>
		{:else}
			<!--
				Normal mode: four HTML divs around the single primary target.
				They provide both the visual dim and click-blocking outside the spotlight.
			-->
			<!-- top band -->
			<div
				class="fixed z-[9990] bg-black/60 dark:bg-black/70"
				style="top:0; left:0; width:{vw}px; height:{topH}px;"
				aria-hidden="true"
			/>
			<!-- bottom band -->
			<div
				class="fixed z-[9990] bg-black/60 dark:bg-black/70"
				style="top:{bottomY}px; left:0; width:{vw}px; height:{bottomH}px;"
				aria-hidden="true"
			/>
			<!-- left band -->
			<div
				class="fixed z-[9990] bg-black/60 dark:bg-black/70"
				style="top:{spotTop}px; left:0; width:{leftW}px; height:{spotH}px;"
				aria-hidden="true"
			/>
			<!-- right band -->
			<div
				class="fixed z-[9990] bg-black/60 dark:bg-black/70"
				style="top:{spotTop}px; left:{rightX}px; width:{rightW}px; height:{spotH}px;"
				aria-hidden="true"
			/>
		{/if}

		<!--
			Purple outlines — one per spotlighted element.
			Always pointer-events-none so they never intercept clicks.
		-->
		{#each allSpotlightRects as r}
			<div
				class="fixed pointer-events-none rounded-lg z-[9991]"
				style="
					top: {r.top - PAD}px;
					left: {r.left - PAD}px;
					width: {r.width + PAD * 2}px;
					height: {r.height + PAD * 2}px;
					outline: 2px solid rgba(147, 51, 234, 0.8);
					outline-offset: 0px;
				"
			/>
		{/each}
	{:else}
		<!-- No target — simple full-screen dim -->
		<div
			transition:fade={{ duration: 200 }}
			class="fixed inset-0 bg-black/60 dark:bg-black/70 z-[9990]"
			aria-hidden="true"
		/>
	{/if}

	<!-- ── Message tooltip ───────────────────────────────────────────────── -->
	<div
		bind:this={tooltipEl}
		transition:fade={{ duration: 150 }}
		class="fixed z-[9995] w-[340px]"
		style="top: {tooltipTop}; left: {tooltipLeft}; transform: {tooltipTransform};"
	>
		<div
			class="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 p-5"
		>
			<!-- Close button -->
			<button
				on:click={dismissTutorial}
				class="absolute top-3 right-3 p-1.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-800 transition"
				aria-label="Close tutorial"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="w-4 h-4 text-gray-500 dark:text-gray-400"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			</button>

			<!-- Step title -->
			<div
				class="text-xs font-semibold text-purple-600 dark:text-purple-400 mb-1 uppercase tracking-wide pr-6"
			>
				{step.title}
			</div>

			<!-- Message -->
			<p class="text-sm text-gray-800 dark:text-gray-200 leading-relaxed whitespace-pre-line">
				{step.message}
			</p>

			<!-- Copy Code button (step 5 only) -->
			{#if step.copyText}
				<button
					on:click={copyCode}
					class="mt-3 flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg transition"
				>
					{#if copySuccess}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-3.5 h-3.5 text-green-500"
						>
							<path
								fill-rule="evenodd"
								d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
								clip-rule="evenodd"
							/>
						</svg>
						Copied!
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-3.5 h-3.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184"
							/>
						</svg>
						Copy Code
					{/if}
				</button>
			{/if}

			<!-- ── Navigation: centered dots + Next/Done only ───────────────── -->
			<div
				class="flex flex-col items-center gap-2 mt-4 pt-3 border-t border-gray-100 dark:border-gray-800"
			>
				<!-- Step dots — always centered -->
				<div class="flex items-center gap-1.5">
					{#each steps as s}
						<div
							class="w-1.5 h-1.5 rounded-full transition {s.stepIndex ===
							$tutorialState.currentStep
								? 'bg-purple-600'
								: 'bg-gray-300 dark:bg-gray-600'}"
						/>
					{/each}
				</div>

				<!--
					For steps with a target element: no button needed — clicking the
					highlighted element advances the tutorial automatically.
					For welcome / completion screens (no target): show Next or Done.
				-->
				{#if !hasTarget}
					{#if isLast}
						<button
							on:click={dismissTutorial}
							class="px-5 py-1.5 text-xs font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-full transition"
						>
							Done
						</button>
					{:else}
						<button
							on:click={nextTutorialStep}
							class="px-5 py-1.5 text-xs font-medium text-white bg-purple-600 hover:bg-purple-700 rounded-full transition"
						>
							Next
						</button>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/if}
