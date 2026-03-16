<script lang="ts">
	import { getContext, onMount, createEventDispatcher } from 'svelte';
	import { get } from 'svelte/store';
	import { fade } from 'svelte/transition';
	import { flyAndScale } from '$lib/utils/transitions';
	import { settings, activeCallMode } from '$lib/stores';
	import { updateUserSettings } from '$lib/apis/users';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;

	let selectedMode: 'live_text' | 'transcript_at_end' = 'live_text';
	let makeDefault = false;
	let modalElement = null;
	let mounted = false;
	let prevShow = false;

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			show = false;
			dispatch('cancel');
		}
		if (event.key === 'Enter') {
			startCall();
		}
	};

	const startCall = async () => {
		const modeToStart = selectedMode;
		if (makeDefault) {
			settings.update((s) => ({ ...s, callMode: modeToStart }));
			await updateUserSettings(localStorage.token, { ui: get(settings) });
		}
		activeCallMode.set(modeToStart);
		show = false;
		dispatch('start', { mode: modeToStart });
	};

	const cancel = () => {
		show = false;
		dispatch('cancel');
	};

	onMount(() => {
		mounted = true;
	});

	// Initialize state only when the modal first opens.
	// Uses get() (non-reactive read) so $settings changes never re-trigger this block.
	$: {
		if (show && !prevShow) {
			selectedMode = get(settings).callMode ?? 'live_text';
			makeDefault = false;
		}
		prevShow = show;
	}

	// DOM management - kept separate so $settings is never a dependency here.
	$: if (mounted) {
		if (show && modalElement) {
			document.body.appendChild(modalElement);
			window.addEventListener('keydown', handleKeyDown);
			document.body.style.overflow = 'hidden';
		} else if (modalElement) {
			window.removeEventListener('keydown', handleKeyDown);
			if (document.body.contains(modalElement)) {
				document.body.removeChild(modalElement);
			}
			document.body.style.overflow = 'unset';
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		bind:this={modalElement}
		class="fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-99999999 overflow-hidden overscroll-contain"
		in:fade={{ duration: 10 }}
		on:mousedown={cancel}
	>
		<div
			class="m-auto rounded-2xl max-w-full w-[26rem] mx-2 bg-gray-50 dark:bg-gray-950 max-h-[100dvh] shadow-3xl"
			in:flyAndScale
			on:mousedown={(e) => e.stopPropagation()}
		>
			<div class="px-7 py-6 flex flex-col gap-5">
				<div class="text-lg font-semibold dark:text-gray-200">
					{$i18n.t('Choose Call Mode')}
				</div>

				<!-- Mode selector cards -->
				<div class="flex flex-col gap-2.5">
					<!-- Live Text -->
					<button
						type="button"
						class="flex items-start gap-3.5 rounded-xl border-2 p-4 text-left transition
							{selectedMode === 'live_text'
							? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-900'
							: 'border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 bg-transparent'}"
						on:click={() => (selectedMode = 'live_text')}
					>
						<div
							class="mt-0.5 flex-shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center
								{selectedMode === 'live_text'
								? 'border-gray-900 dark:border-gray-100'
								: 'border-gray-400 dark:border-gray-600'}"
						>
							{#if selectedMode === 'live_text'}
								<div class="w-2 h-2 rounded-full bg-gray-900 dark:bg-gray-100"></div>
							{/if}
						</div>
						<div class="flex flex-col gap-0.5">
							<div class="text-sm font-semibold dark:text-gray-100">
								{$i18n.t('Live Text')}
							</div>
							<div class="text-xs text-gray-500 dark:text-gray-400">
								{$i18n.t('Chat messages appear while the assistant speaks.')}
							</div>
						</div>
					</button>

					<!-- Transcript at End -->
					<button
						type="button"
						class="flex items-start gap-3.5 rounded-xl border-2 p-4 text-left transition
							{selectedMode === 'transcript_at_end'
							? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-900'
							: 'border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 bg-transparent'}"
						on:click={() => (selectedMode = 'transcript_at_end')}
					>
						<div
							class="mt-0.5 flex-shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center
								{selectedMode === 'transcript_at_end'
								? 'border-gray-900 dark:border-gray-100'
								: 'border-gray-400 dark:border-gray-600'}"
						>
							{#if selectedMode === 'transcript_at_end'}
								<div class="w-2 h-2 rounded-full bg-gray-900 dark:bg-gray-100"></div>
							{/if}
						</div>
						<div class="flex flex-col gap-0.5">
							<div class="text-sm font-semibold dark:text-gray-100">
								{$i18n.t('Transcript at End')}
							</div>
							<div class="text-xs text-gray-500 dark:text-gray-400">
								{$i18n.t('Full-screen voice mode. Chat transcript is shown when the call ends.')}
							</div>
						</div>
					</button>
				</div>

				<!-- Make default checkbox -->
				<div class="flex flex-col gap-1.5">
					<label class="flex items-center gap-2.5 cursor-pointer select-none">
						<input
							type="checkbox"
							bind:checked={makeDefault}
							class="w-4 h-4 rounded border-gray-300 dark:border-gray-600 accent-gray-900 dark:accent-gray-100 cursor-pointer"
						/>
						<span class="text-xs text-gray-600 dark:text-gray-400">
							{$i18n.t('Make this my default')}
						</span>
					</label>
					<p class="text-[12px] leading-snug text-gray-500 dark:text-gray-500">
						{$i18n.t('You can change this later in Settings → Interface → Voice')}
					</p>
				</div>

				<!-- Action buttons -->
				<div class="flex gap-2">
					<button
						type="button"
						class="bg-gray-100 hover:bg-gray-200 text-gray-800 dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white font-medium w-full py-2.5 rounded-lg transition text-sm"
						on:click={cancel}
					>
						{$i18n.t('Cancel')}
					</button>
					<button
						type="button"
						class="bg-gray-900 hover:bg-gray-850 text-gray-100 dark:bg-gray-100 dark:hover:bg-white dark:text-gray-800 font-medium w-full py-2.5 rounded-lg transition text-sm"
						on:click={startCall}
					>
						{$i18n.t('Start Call')}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
