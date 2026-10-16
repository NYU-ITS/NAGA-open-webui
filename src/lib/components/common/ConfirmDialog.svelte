<script lang="ts">
	import { onMount, onDestroy, getContext, createEventDispatcher } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import { fade } from 'svelte/transition';
	import { flyAndScale } from '$lib/utils/transitions';

	export let title = '';
	export let message = '';

	export let cancelLabel = $i18n.t('Cancel');
	export let confirmLabel = $i18n.t('Confirm');

	export let onConfirm = () => {};

	export let input = false;
	export let inputPlaceholder = '';
	export let inputValue = '';

	export let show = false;
	export let requireExplicitChoice = false;

	let modalElement = null;
	let mounted = false;

	const handleKeyDown = (event: KeyboardEvent) => {
		if (requireExplicitChoice) {
			if (event.key === 'Escape') event.preventDefault();
			if (event.key === 'Tab') {
				const buttons = Array.from(modalElement.querySelectorAll('button')) as HTMLButtonElement[];
				const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
				const next = (index + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length;
				event.preventDefault();
				buttons[next]?.focus();
			}
			// Only native button activation can select Cancel or Proceed.
			if (event.key === 'Enter' && !modalElement.contains(document.activeElement)) {
				event.preventDefault();
			}
			return;
		}
		if (event.key === 'Escape') {
			console.log('Escape');
			show = false;
		}

		if (event.key === 'Enter') {
			console.log('Enter');
			confirmHandler();
		}
	};

	const confirmHandler = async () => {
		show = false;
		await onConfirm();
		dispatch('confirm', inputValue);
	};

	onMount(() => {
		mounted = true;
	});

	onDestroy(() => {
		if (!mounted) return;
		window.removeEventListener('keydown', handleKeyDown);
		if (modalElement?.parentNode) {
			modalElement.parentNode.removeChild(modalElement);
			document.body.style.overflow = 'unset';
		}
	});

	$: if (mounted) {
		if (show && modalElement) {
			document.body.appendChild(modalElement);

			window.addEventListener('keydown', handleKeyDown);
			document.body.style.overflow = 'hidden';
			if (requireExplicitChoice) modalElement.querySelector('button')?.focus();
		} else if (modalElement) {
			window.removeEventListener('keydown', handleKeyDown);
			document.body.removeChild(modalElement);

			document.body.style.overflow = 'unset';
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		bind:this={modalElement}
		class=" fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-99999999 overflow-hidden overscroll-contain"
		in:fade={{ duration: 10 }}
		on:mousedown={() => {
			if (!requireExplicitChoice) show = false;
		}}
	>
		<div
			role="dialog"
			aria-modal="true"
			aria-label={title || $i18n.t('Confirm your action')}
			tabindex="-1"
			class=" m-auto rounded-2xl max-w-full w-[32rem] mx-2 bg-gray-50 dark:bg-gray-950 max-h-[100dvh] shadow-3xl"
			in:flyAndScale
			on:mousedown={(e) => {
				e.stopPropagation();
			}}
		>
			<div class="px-[1.75rem] py-6 flex flex-col">
				<div class=" text-lg font-semibold dark:text-gray-200 mb-2.5">
					{#if title !== ''}
						{title}
					{:else}
						{$i18n.t('Confirm your action')}
					{/if}
				</div>

				<slot>
					<div class=" text-sm text-gray-500 flex-1">
						{#if message !== ''}
							{message}
						{:else}
							{$i18n.t('This action cannot be undone. Do you wish to continue?')}
						{/if}

						{#if input}
							<textarea
								bind:value={inputValue}
								placeholder={inputPlaceholder ? inputPlaceholder : $i18n.t('Enter your message')}
								class="w-full mt-2 rounded-lg px-4 py-2 text-sm dark:text-gray-300 dark:bg-gray-900 outline-hidden resize-none"
								rows="3"
								required
							/>
						{/if}
					</div>
				</slot>

				<div class="mt-6 flex justify-between gap-1.5">
					<button
						class="bg-gray-100 hover:bg-gray-200 text-gray-800 dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-white font-medium w-full py-2.5 rounded-lg transition"
						on:click={() => {
							show = false;
							dispatch('cancel');
						}}
						type="button"
					>
						{cancelLabel}
					</button>
					<button
						class="bg-gray-900 hover:bg-gray-850 text-gray-100 dark:bg-gray-100 dark:hover:bg-white dark:text-gray-800 font-medium w-full py-2.5 rounded-lg transition"
						on:click={() => {
							confirmHandler();
						}}
						type="button"
					>
						{confirmLabel}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

<style>
	.modal-content {
		animation: scaleUp 0.1s ease-out forwards;
	}

	@keyframes scaleUp {
		from {
			transform: scale(0.985);
			opacity: 0;
		}
		to {
			transform: scale(1);
			opacity: 1;
		}
	}
</style>
