<script lang="ts">
	import { createEventDispatcher, onDestroy, onMount } from 'svelte';

	import GuideBackdrop from './GuideBackdrop.svelte';
	import GuideMascot from './GuideMascot.svelte';
	import GuideTooltip from './GuideTooltip.svelte';
	import { resolveTarget } from '../services/guide-target.service';
	import type { GuideContext, GuideRuntimeStatus, GuideStep } from '../types/guide.types';

	export let targetElement: HTMLElement | undefined;
	export let step: GuideStep;
	export let context: GuideContext;
	export let runtimeStatus: GuideRuntimeStatus = 'showing_step';
	export let currentStepIndex: number;
	export let totalSteps: number;

	const dispatch = createEventDispatcher<{
		next: void;
		back: void;
		skip: void;
		close: void;
		finish: void;
		restart: void;
	}>();

	let rect: DOMRect | null = null;
	let highlightRects: DOMRect[] = [];
	let rectFrameId: number | null = null;
	let rectTimeoutId: number | null = null;
	let resizeObserver: ResizeObserver | null = null;
	let observedTarget: HTMLElement | undefined;

	$: title = typeof step.title === 'function' ? step.title(context) : step.title;
	$: description =
		typeof step.description === 'function' ? step.description(context) : step.description;
	$: descriptionLines = description.split('\n');
	$: pathDescription = descriptionLines[0]?.startsWith('Path:') ? descriptionLines[0] : '';
	$: bodyDescription = pathDescription ? descriptionLines.slice(1).join('\n').trim() : description;
	$: isFirstStep = currentStepIndex === 0;
	$: isLastStep = currentStepIndex === totalSteps - 1;
	$: isSummaryStep = step.summary === true;
	$: isPending = runtimeStatus === 'navigating' || runtimeStatus === 'waiting_for_target';
	$: pendingMessage =
		runtimeStatus === 'navigating'
			? `Taking you to ${title}...`
			: runtimeStatus === 'waiting_for_target'
				? `Looking for ${title}...`
				: '';
	$: nextButtonLabel = isPending
		? 'Please wait'
		: isLastStep
			? 'Finish'
			: (step.actionLabel ?? 'Next');

	const uniqueElements = (elements: HTMLElement[]): HTMLElement[] =>
		elements.filter((element, index) => elements.indexOf(element) === index);

	const getHighlightElements = (): HTMLElement[] => {
		const targetIds = step.highlightTargetIds ?? [];

		if (targetIds.length === 0) {
			return targetElement ? [targetElement] : [];
		}

		return uniqueElements(
			targetIds
				.map((targetId) =>
					targetId === step.targetId && targetElement ? targetElement : resolveTarget(targetId)
				)
				.filter((element): element is HTMLElement => Boolean(element))
		);
	};

	const updateRect = () => {
		rect = targetElement ? targetElement.getBoundingClientRect() : null;
		highlightRects = getHighlightElements().map((element) => element.getBoundingClientRect());
	};

	const scheduleRectUpdate = () => {
		if (typeof window === 'undefined') {
			return;
		}

		if (rectFrameId !== null) {
			window.cancelAnimationFrame(rectFrameId);
		}

		rectFrameId = window.requestAnimationFrame(() => {
			rectFrameId = null;
			updateRect();
		});
	};

	const updateRectAfterLayoutSettles = () => {
		updateRect();
		scheduleRectUpdate();

		if (rectTimeoutId !== null) {
			window.clearTimeout(rectTimeoutId);
		}

		rectTimeoutId = window.setTimeout(() => {
			rectTimeoutId = null;
			updateRect();
		}, 150);
	};

	const observeTargetResize = () => {
		if (observedTarget === targetElement) {
			return;
		}

		resizeObserver?.disconnect();
		observedTarget = targetElement;

		if (!targetElement || typeof ResizeObserver === 'undefined') {
			return;
		}

		resizeObserver = new ResizeObserver(() => {
			scheduleRectUpdate();
		});
		resizeObserver.observe(targetElement);
	};

	const onKeydown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			dispatch('close');
		}
	};

	const advance = () => {
		if (isPending) {
			return;
		}

		if (isLastStep) {
			dispatch('finish');
			return;
		}

		dispatch('next');
	};

	onMount(() => {
		updateRectAfterLayoutSettles();
		observeTargetResize();
		window.addEventListener('resize', scheduleRectUpdate);
		window.addEventListener('scroll', scheduleRectUpdate, true);
		window.addEventListener('keydown', onKeydown);
	});

	onDestroy(() => {
		if (rectFrameId !== null) {
			window.cancelAnimationFrame(rectFrameId);
		}

		if (rectTimeoutId !== null) {
			window.clearTimeout(rectTimeoutId);
		}

		resizeObserver?.disconnect();
		window.removeEventListener('resize', scheduleRectUpdate);
		window.removeEventListener('scroll', scheduleRectUpdate, true);
		window.removeEventListener('keydown', onKeydown);
	});

	$: {
		targetElement;
		observeTargetResize();

		if (targetElement) {
			updateRectAfterLayoutSettles();
		} else {
			rect = null;
			highlightRects = [];
		}
	}
</script>

<GuideBackdrop rect={isSummaryStep ? null : rect} rects={isSummaryStep ? [] : highlightRects} />

<GuideTooltip rect={isSummaryStep ? null : rect} placement={step.placement ?? 'bottom'}>
	<div class="relative pr-6">
		<button
			type="button"
			class="absolute right-0 top-0 flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold text-gray-500 transition hover:bg-[#F3E8FF] hover:text-[#4C007A] disabled:cursor-wait disabled:opacity-45 dark:text-gray-300 dark:hover:bg-[#3B0764] dark:hover:text-white"
			aria-label="Close guided tour"
			disabled={isPending}
			on:click={() => dispatch('close')}
		>
			x
		</button>

		<div class="flex items-start gap-3">
			<div class="guide-mascot-shell shrink-0">
				<GuideMascot className="h-12 w-12 text-[#57068C]" />
			</div>

			<div class="min-w-0">
				<h2 class="text-[14px] font-semibold leading-5 text-gray-950 dark:text-white">
					{title}
				</h2>
				{#if pathDescription}
					<div
						class="mt-2 rounded-lg border border-[#D8B4FE] bg-[#F7EDFF] px-2.5 py-2 text-[11px] font-semibold leading-4 text-[#6A00A8] shadow-sm dark:border-[#7E22CE] dark:bg-[#2E0148]/70 dark:text-[#E9D5FF]"
					>
						{pathDescription}
					</div>
				{/if}
				{#if bodyDescription}
					<p
						class="{pathDescription ? 'mt-2' : 'mt-1'} max-h-32 overflow-y-auto whitespace-pre-line pr-1 text-[12px] leading-4 text-gray-700 dark:text-gray-300"
					>
						{bodyDescription}
					</p>
				{/if}
				{#if pendingMessage}
					<div
						class="mt-2 text-[11px] font-medium leading-4 text-[#6A00A8] dark:text-[#E9D5FF]"
						aria-live="polite"
					>
						{pendingMessage}
					</div>
				{/if}
				<div class="mt-2 text-center text-[12px] leading-4 text-gray-500 dark:text-gray-400">
					Step {currentStepIndex + 1} of {totalSteps}
				</div>
			</div>
		</div>
	</div>

	<div class="mt-4 flex flex-wrap items-center justify-between gap-2.5">
		{#if !isSummaryStep}
			<button
				type="button"
				class="rounded-full px-3 py-1.5 text-xs font-semibold text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 disabled:cursor-wait disabled:opacity-45 dark:text-gray-300 dark:hover:bg-white/10 dark:hover:text-white"
				disabled={isPending}
				on:click={() => dispatch('skip')}
			>
				Skip
			</button>
		{:else}
			<div class="w-12" aria-hidden="true" />
		{/if}

		<div class="flex items-center gap-2">
			<button
				type="button"
				class="rounded-full border border-[#D8B4FE] bg-white/[0.65] px-3 py-1.5 text-xs font-semibold text-[#5B128A] shadow-sm transition hover:border-[#B567E8] hover:bg-[#F3E8FF] disabled:cursor-not-allowed disabled:opacity-45 dark:border-[#7E22CE] dark:bg-white/5 dark:text-[#E9D5FF] dark:hover:bg-[#3B0764]"
				disabled={isFirstStep || isPending}
				on:click={() => dispatch('back')}
			>
				Back
			</button>

			{#if isSummaryStep}
				<button
					type="button"
					class="rounded-full border border-transparent px-3 py-1.5 text-xs font-semibold text-[#6A00A8] transition hover:bg-[#F3E8FF] disabled:cursor-wait disabled:opacity-45 dark:text-[#E9D5FF] dark:hover:bg-[#3B0764]"
					disabled={isPending}
					on:click={() => dispatch('restart')}
				>
					Restart
				</button>
			{/if}

			<button
				type="button"
				class="rounded-full bg-[#6A00A8] px-4 py-1.5 text-xs font-semibold text-white shadow-[0_8px_20px_rgba(106,0,168,0.24)] transition hover:bg-[#58008C] hover:shadow-[0_12px_26px_rgba(106,0,168,0.3)] disabled:cursor-wait disabled:opacity-60 dark:bg-[#A855F7] dark:hover:bg-[#9333EA]"
				disabled={isPending}
				on:click={advance}
			>
				{nextButtonLabel}
			</button>
		</div>
	</div>
</GuideTooltip>

<style>
	@media (max-width: 420px) {
		.guide-mascot-shell {
			display: none;
		}
	}
</style>
