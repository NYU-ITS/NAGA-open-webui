<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	export let value: string;
	export let options: Array<{ id: string; label: string }> | string[];
	export let width: string = 'w-40';
	export let label: string = 'Select';

	const dispatch = createEventDispatcher();

	let isOpen = false;

	function getLabel(val: string): string {
		if (Array.isArray(options) && typeof options[0] === 'string') {
			return val;
		}
		const opt = (options as Array<{ id: string; label: string }>).find(o => o.id === val);
		return opt?.label || val;
	}

	function handleSelect(newValue: string) {
		value = newValue;
		isOpen = false;
		dispatch('change', { value: newValue });
	}

	function toggleOpen() {
		isOpen = !isOpen;
	}
</script>

<div class="relative">
	<button
		class="border border-gray-300 rounded-md bg-white px-2.5 py-1.5 text-xs text-gray-700 dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-400 dark:focus:ring-blue-500 cursor-pointer flex items-center justify-between gap-2 {width}"
		on:click={toggleOpen}
	>
		<span class="truncate">{getLabel(value)}</span>
		<ChevronDown className={`size-3 flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
	</button>
	{#if isOpen}
		<div class="absolute top-full left-0 mt-1 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-500 rounded-md shadow-lg z-50 {width} max-h-64 overflow-y-auto">
			{#if Array.isArray(options) && typeof options[0] === 'string'}
				{#each options as option}
					<button
						class="w-full px-3 py-1.5 text-xs text-left hover:bg-gray-100 dark:hover:bg-gray-700 {value === option ? 'bg-blue-50 dark:bg-blue-900/30 font-medium' : ''}"
						on:click={() => handleSelect(option)}
					>
						{option}
					</button>
				{/each}
			{:else}
				{#each options as option}
					<button
						class="w-full px-3 py-1.5 text-xs text-left hover:bg-gray-100 dark:hover:bg-gray-700 {value === option.id ? 'bg-blue-50 dark:bg-blue-900/30 font-medium' : ''}"
						on:click={() => handleSelect(option.id)}
					>
						{option.label}
					</button>
				{/each}
			{/if}
		</div>
	{/if}
</div>
