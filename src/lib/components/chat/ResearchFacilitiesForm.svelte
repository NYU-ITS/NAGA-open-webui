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
	let expandedSections = {}; // Track which sections are expanded

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
		const newExpanded = {};
		sectionLabels.forEach(label => {
			newInputs[label] = userInputs[label] || '';
			newExpanded[label] = expandedSections[label] || false;
		});
		userInputs = newInputs;
		expandedSections = newExpanded;
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

	// Toggle expanded state for a section
	const toggleExpanded = (label) => {
		expandedSections[label] = !expandedSections[label];
		expandedSections = { ...expandedSections }; // Trigger reactivity
	};

	// Handle keyboard navigation for expand buttons
	const handleExpandKeydown = (event, label) => {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			toggleExpanded(label);
		}
	};

	// Enhanced form submission
	const handleSubmit = () => {
		// Validate form
		if (!selectedSponsor) {
			toast.error('Please select a sponsor before generating.');
			// Focus on sponsor selection
			const sponsorSelect = document.querySelector('select[aria-label="Select Sponsor"]');
			sponsorSelect?.focus();
			return;
		}

		// Check if any required fields are filled (at least one)
		const hasContent = Object.values(userInputs).some(value => value.trim().length > 0);
		if (!hasContent) {
			toast.error('Please fill in at least one section before generating.');
			return;
		}

		toast.success('Form submitted successfully!');
		// Add your form submission logic here
	};
</script>

<style>
	/* Enhanced scrollbar styles for better visibility */
	.custom-scrollbar {
		scrollbar-width: thin;
		scrollbar-color: #9ca3af #f3f4f6;
	}
	
	.dark .custom-scrollbar {
		scrollbar-color: #6b7280 #374151;
	}

	/* Webkit browsers (Chrome, Safari, Edge) */
	.custom-scrollbar::-webkit-scrollbar {
		width: 8px;
		height: 8px;
	}

	.custom-scrollbar::-webkit-scrollbar-track {
		background: #f3f4f6;
		border-radius: 4px;
	}

	.dark .custom-scrollbar::-webkit-scrollbar-track {
		background: #374151;
	}

	.custom-scrollbar::-webkit-scrollbar-thumb {
		background: #9ca3af;
		border-radius: 4px;
		border: 1px solid #f3f4f6;
	}

	.dark .custom-scrollbar::-webkit-scrollbar-thumb {
		background: #6b7280;
		border-color: #374151;
	}

	.custom-scrollbar::-webkit-scrollbar-thumb:hover {
		background: #6b7280;
	}

	.dark .custom-scrollbar::-webkit-scrollbar-thumb:hover {
		background: #9ca3af;
	}

	/* Textarea focus styles for better accessibility */
	.textarea-enhanced:focus {
		outline: 2px solid #3b82f6;
		outline-offset: 2px;
	}

	/* Animation for expand/collapse */
	.expand-button {
		transition: transform 0.2s ease-in-out;
	}

	.expand-button.expanded {
		transform: rotate(180deg);
	}
</style>

<!-- Remove the {#if $showFacilitiesForm} wrapper -->
<div class="flex flex-col h-full bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-850 rounded-xl shadow-lg dark:shadow-lg">
	<!-- Header -->
	<div class="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
		<div class="flex-1">
			<h1 class="text-lg font-semibold text-gray-900 dark:text-white">
				{('Research Facilities Draft Generator')}
			</h1>
			<p class="text-sm text-gray-600 dark:text-gray-400 mt-1">
				<b>Description</b><br>
This tool assists in developing professional Facilities & Other Resources sections for grant proposals. Users should complete only those sections that are applicable to their research; any sections left blank will be omitted from the final document. LLM will generate responses in accordance with the NSF Proposal & Award Policies & Procedures Guide (PAPPG).
<br><br>
<b>Disclaimer</b><br>
The AI-generated text is intended as a drafting aid and may contain inaccuracies or incomplete information. All content must be carefully reviewed, verified, and revised by the researcher to ensure accuracy, compliance with the PAPPG, and adherence to institutional policies. Researchers are solely responsible for the final submitted materials.
			</p>
		</div>
		
		<button
			class="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
			on:click={closeOverlay}
			type="button"
			aria-label="Close research facilities form"
		>
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5" aria-hidden="true">
				<path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
			</svg>
		</button>
	</div>

	<!-- Main content area - scrollable -->
	<div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-4 space-y-6">
		<!-- Sponsor Selection -->
		<div>
			<label for="sponsor-select" class="block text-sm font-medium text-gray-900 dark:text-white mb-3">
				{('Sponsor Selection')} <span class="text-red-500" aria-label="required">*</span>
			</label>
			<select
				id="sponsor-select"
				class="w-full rounded-lg py-2.5 px-3 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
				bind:value={selectedSponsor}
				aria-label="Select Sponsor"
				aria-describedby="sponsor-help"
				required
			>
				<option value="">{('Choose a sponsor...')}</option>
				{#each sponsors as sponsor}
					<option value={sponsor}>{sponsor}</option>
				{/each}
			</select>
		</div>

		<!-- Form Inputs -->
		{#if selectedSponsor && sectionLabels.length > 0}
			<div>
				<fieldset>
					<legend class="block text-sm font-medium text-gray-900 dark:text-white mb-4">
						{('Section Details')}
					</legend>
					
					<div class="space-y-6">
						{#each sectionLabels as label, index}
							<div class="relative">
								<label for="section-{index}" class="block text-s font-medium mb-2 text-gray-700 dark:text-gray-300">
									{label}
								</label>
								<textarea
									id="section-{index}"
									class="textarea-enhanced textarea-auto-resize w-full rounded-lg py-2.5 px-3 text-sm text-gray-700 bg-gray-50 dark:text-gray-300 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 outline-none focus:border-blue resize-vertical pointer-events-auto custom-scrollbar placeholder-gray-600 dark:placeholder-gray-400"
									rows="4"
									placeholder="Enter details for {label}..."
									value={userInputs[label] || ''}
									on:input={(e) => handleInput(label, e)}
									aria-describedby="section-{index}-help"
								></textarea>
							</div>
						{/each}
					</div>

					<button
						type="button"
						class="w-full mt-6 px-4 py-3 bg-[#57068C] hover:bg-[#8900E1] text-white dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100 dark:disabled:bg-gray-600 rounded-lg font-medium text-sm"
						on:click={handleSubmit}
						aria-describedby="generate-help"
					>
						{('Generate')}
					</button>

				</fieldset>
			</div>
		{/if}
	</div>
</div>