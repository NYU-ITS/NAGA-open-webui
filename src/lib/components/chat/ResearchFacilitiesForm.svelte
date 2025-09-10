<script lang="ts">
    import { showFacilitiesForm } from '$lib/stores';
	import { onMount, getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	export let show = false;

	// Form state
	let selectedSponsor = '';
	let userInputs = {};
	let sectionLabels = [];

	// Available sponsors
	const sponsors = ['NSF', 'NIH'];

	// Section labels for each sponsor
	const sponsorSections = {
		NSF: [
			'1. Project Title',
			'2. Research Space and Facilities',
			'3. Core Instrumentation',
			'4. Computing and Data Resources',
			'5a. Internal Facilities (NYU)',
            '5b. External Facilities (Other Institutions)',
            '6. Special Infrastructure'
		],
		NIH: [
			'1. Project Title',
			'2. Research Space and Facilities',
			'3. Core Instrumentation',
			'4. Computing and Data Resources',
			'5a. Internal Facilities (NYU)',
            '5b. External Facilities (Other Institutions)',
            '6. Special Infrastructure',
            '7. Equipment'
		]
	};

	// Initialize userInputs properly
	const initializeInputs = () => {
		const newInputs = {};
		sectionLabels.forEach(label => {
			newInputs[label] = userInputs[label] || '';
		});
		userInputs = newInputs;
	};

	// Watch for agency selection changes
	$: if (selectedSponsor) {
		sectionLabels = sponsorSections[selectedSponsor] || [];
		initializeInputs();
	}

	const closeOverlay = () => {
		showFacilitiesForm.set(false);
		dispatch('close');
	};

	// Simple function to handle text input
	const handleInput = (label, event) => {
		userInputs[label] = event.target.value;
		userInputs = { ...userInputs }; // Trigger reactivity
	};
</script>

<!-- Remove the {#if $showFacilitiesForm} wrapper -->
<div class="flex flex-col h-full bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-850 rounded-xl shadow-lg dark:shadow-lg">
	<!-- Header -->
	<div class="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
		<div class="flex-1">
			<h2 class="text-lg font-semibold text-gray-900 dark:text-white">
				{('Research Facilities Draft Generator')}
			</h2>
			<p class="text-sm text-gray-600 dark:text-gray-400 mt-1">
				{('Generate and customize grant facility sections')}
			</p>
		</div>
		
		<button
			class="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
			on:click={closeOverlay}
			type="button"
			aria-label="Close"
		>
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
				<path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
			</svg>
		</button>
	</div>

	<!-- Main content area - scrollable -->
	<div class="flex-1 min-h-0 overflow-y-auto p-4 space-y-6">
		<!-- Sponsor Selection -->
		<div>
			<label class="block text-sm font-medium text-gray-900 dark:text-white mb-3">
				{('Sponsor Selection')}
			</label>
			<select
				class="w-full rounded-lg py-2.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
				bind:value={selectedSponsor}
				aria-label="Select Sponsor"
			>
				<option value="">{('Choose an sponsor...')}</option>
				{#each sponsors as sponsor}
					<option value={sponsor}>{sponsor}</option>
				{/each}
			</select>
		</div>

		<!-- Form Inputs -->
		{#if selectedSponsor && sectionLabels.length > 0}
			<div>
				<label class="block text-sm font-medium text-gray-900 dark:text-white mb-4">
					{('Section Details')}
				</label>
				
				<div class="space-y-4">
					{#each sectionLabels as label, index}
						<div>
							<label class="block text-xs font-medium mb-2 text-gray-700 dark:text-gray-300">
								{label}
							</label>
							<textarea
								class="w-full rounded-lg py-2.5 px-3 text-sm bg-gray-50 dark:text-gray-500 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none pointer-events-auto"
								rows="3"
								placeholder="Enter details for {label}..."
								value={userInputs[label] || ''}
								on:input={(e) => handleInput(label, e)}
							></textarea>
						</div>
					{/each}
				</div>

				<button
					class="w-full mt-6 px-4 py-3 bg-[#57068C] hover:bg-[#8900E1] text-white dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 rounded-lg font-medium text-sm transition-colors"
					on:click={() => toast.success('Form submitted!')}
				>
					{('Generate')}
				</button>
			</div>
		{/if}
	</div>
</div>