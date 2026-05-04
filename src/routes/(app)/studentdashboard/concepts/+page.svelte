<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { TEMP_HIDE } from '$lib/constants';

	onMount(() => {
		console.log('[studentdashboard]-[Concepts]-[Loaded]');

		// Check if there's a topic in URL query params
		const urlParams = new URLSearchParams(window.location.search);
		const topicParam = urlParams.get('topic');
		if (topicParam && !TEMP_HIDE) {
			selectedConcepts.add(topicParam);
			selectedConcepts = selectedConcepts;
		}
	});

	let selectedConcepts: Set<string> = new Set();
	let selectedHomework = 'All'; // This should sync with parent layout
	let hoveredLegendStatus: string | null = null;
	// TODO(student-dashboard-backend): This table is intended for teacher-distributed practice
	// question sets. Replace the placeholder rows with student assignment status once the
	// backend exposes distribution / completion endpoints.
	const followUpQuestions = [
		{ homework: 'Homework 1', status: 'Not Ready' },
		{ homework: 'Homework 2', status: 'Not Completed' },
		{ homework: 'Homework 3', status: 'Completed' },
		{ homework: 'Homework 4', status: 'Not Ready' },
		{ homework: 'Homework 5', status: 'Not Completed' },
		{ homework: 'Homework 6', status: 'Completed' },
		{ homework: 'Homework 7', status: 'Not Ready' },
		{ homework: 'Homework 8', status: 'Not Completed' }
	];

	// TODO(student-dashboard-backend): Replace this static concept catalog with student-scoped
	// concept summaries from the AI Tutor backend. Each concept should eventually include:
	// - concept/topic name
	// - tested homeworks
	// - practice availability / completion status
	// - question-generation or assigned-practice metadata
	const conceptsData = [
		{
			name: 'Linear Algebra',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 1': 'Mastered',
				'Homework 2': 'Practiced',
				'Homework 3': 'Mastered',
				'Homework 4': 'Practiced'
			}
		},
		{
			name: 'Differentiation',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 1': 'Practiced',
				'Homework 2': 'Mastered',
				'Homework 3': 'Practiced',
				'Homework 4': 'Mastered'
			}
		},
		{
			name: 'Integration',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 1': 'Practiced',
				'Homework 2': 'Mastered',
				'Homework 3': 'Practiced',
				'Homework 4': 'Mastered'
			}
		},
		{
			name: 'Limit Definition',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 1': 'Mastered',
				'Homework 2': 'Mastered',
				'Homework 3': 'Practiced',
				'Homework 4': 'Practiced'
			}
		},
		{
			name: 'Quadratic Equations',
			testedIn: ['Homework 1', 'Homework 2'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 1': 'Mastered',
				'Homework 2': 'Practiced'
			}
		},
		{
			name: 'Polynomials',
			testedIn: ['Homework 2', 'Homework 3'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 2': 'Mastered',
				'Homework 3': 'Mastered'
			}
		},
		{
			name: 'Factoring',
			testedIn: ['Homework 2', 'Homework 4'],
			practicedDate: null,
			homeworkStatuses: {
				'Homework 2': 'Unmastered',
				'Homework 4': 'Unmastered'
			}
		},
		{
			name: 'Complex Numbers',
			testedIn: ['Homework 3', 'Homework 5'],
			practicedDate: null,
			homeworkStatuses: {
				'Homework 3': 'Unmastered',
				'Homework 5': 'Unmastered'
			}
		},
		{
			name: 'Trigonometry',
			testedIn: ['Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 3': 'Practiced',
				'Homework 4': 'Mastered'
			}
		},
		{
			name: 'Unit Circle',
			testedIn: ['Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 4': 'Mastered'
			}
		},
		{
			name: 'Trigonometric Identities',
			testedIn: ['Homework 4', 'Homework 5'],
			practicedDate: 'Jan 21',
			homeworkStatuses: {
				'Homework 4': 'Practiced',
				'Homework 5': 'Mastered'
			}
		},
		{
			name: 'Inverse Functions',
			testedIn: ['Homework 5'],
			practicedDate: null,
			homeworkStatuses: {
				'Homework 5': 'Unmastered'
			}
		}
	];

	// Filter by homework
	$: filteredConcepts = selectedHomework === 'All'
		? conceptsData
		: conceptsData.filter(c => c.testedIn.includes(selectedHomework));

	// Pagination
	let currentPage = 1;
	const itemsPerPage = 9;
	$: totalPages = Math.ceil(filteredConcepts.length / itemsPerPage);
	$: paginatedConcepts = filteredConcepts.slice(
		(currentPage - 1) * itemsPerPage,
		currentPage * itemsPerPage
	);

	function selectConcept(conceptName: string) {
		if (TEMP_HIDE) return;

		if (selectedConcepts.has(conceptName)) {
			selectedConcepts.delete(conceptName);
		} else {
			selectedConcepts.add(conceptName);
		}
		selectedConcepts = selectedConcepts;
	}

	function selectAllUnfinished() {
		// Clear current selection first
			selectedConcepts.clear();
		// Then add only unfinished ones
		filteredConcepts.forEach(concept => {
			if (Object.values(concept.homeworkStatuses).includes('Unmastered')) {
				selectedConcepts.add(concept.name);
			}
		});
		selectedConcepts = selectedConcepts;
	}

	function selectAll() {
		filteredConcepts.forEach(concept => {
			selectedConcepts.add(concept.name);
		});
		selectedConcepts = selectedConcepts;
	}

	function unselectAll() {
		selectedConcepts.clear();
		selectedConcepts = selectedConcepts;
	}

	function handleGenerate() {
		// TODO(student-dashboard-backend): Replace sessionStorage-based placeholder generation
		// with a real student practice-question workflow backed by the AI Tutor practice APIs.
		// Create array of selected concept names
		const selectedConceptsArray = Array.from(selectedConcepts);

		// Store selected concepts in sessionStorage for the chat page
		sessionStorage.setItem('generatedQuestions', JSON.stringify({
			concepts: selectedConceptsArray,
			timestamp: new Date().toISOString()
		}));

		// Navigate to new chat
		window.location.href = '/';
	}

	function goToPage(page: number) {
		currentPage = page;
	}

	function previousPage() {
		if (currentPage > 1) {
			currentPage--;
		}
	}

	function nextPage() {
		if (currentPage < totalPages) {
			currentPage++;
		}
	}

	const statusOrder = ['Mastered', 'Practiced', 'Unmastered'];

	function getStatusClasses(status: string) {
		if (status === 'Mastered') {
			return 'bg-green-100 text-green-700 ring-1 ring-green-200 dark:bg-green-900/40 dark:text-green-300 dark:ring-green-800/60';
		}

		if (status === 'Practiced') {
			return 'bg-blue-100 text-blue-700 ring-1 ring-blue-200 dark:bg-blue-900/40 dark:text-blue-300 dark:ring-blue-800/60';
		}

		return 'bg-yellow-100 text-yellow-700 ring-1 ring-yellow-200 dark:bg-yellow-900/40 dark:text-yellow-300 dark:ring-yellow-800/60';
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	{#if !TEMP_HIDE}
		<div class="space-y-3">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Follow Up Questions</h2>

			<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
					<thead class="bg-gray-50 dark:bg-gray-800">
						<tr>
							<th
								class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
							>
								Homework
							</th>
							<th
								class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
							>
								Status
							</th>
						</tr>
					</thead>
					<tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
						{#each followUpQuestions as item}
							<tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition">
								<td class="px-6 py-4 text-sm font-medium text-gray-900 dark:text-gray-100">
									{item.homework}
								</td>
								<td class="px-6 py-4 text-sm">
									<span
										class="inline-flex rounded-full px-2.5 py-1 text-xs font-medium
										{item.status === 'Completed'
											? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
											: item.status === 'Not Completed'
												? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
												: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'}"
									>
										{item.status}
									</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<div class="sticky top-0 z-10 bg-transparent py-2 space-y-4">
		<div class="flex items-start justify-between gap-4 px-0.5">
			<div class="flex items-start text-lg font-medium">
				By Topics
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{filteredConcepts.length}</span>
			</div>
			<div class="flex flex-wrap items-start justify-end gap-1.5">
				{#each statusOrder as status}
					<span
						class="inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium {getStatusClasses(status)}"
						on:mouseenter={() => (hoveredLegendStatus = status)}
						on:mouseleave={() => (hoveredLegendStatus = null)}
					>
						{status}
					</span>
				{/each}
			</div>
		</div>

	{#if !TEMP_HIDE}
		<!-- Selection Buttons -->
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-1">
				<button
					on:click={selectAllUnfinished}
					class="px-4 py-2 text-sm font-medium text-gray-600 transition hover:text-[#57068c] dark:text-gray-400 dark:hover:text-white"
				>
					Select All Unfinished
				</button>
				<button
					on:click={selectAll}
					class="px-4 py-2 text-sm font-medium text-gray-600 transition hover:text-[#57068c] dark:text-gray-400 dark:hover:text-white"
				>
					Select All
				</button>
				<button
					on:click={unselectAll}
					class="px-4 py-2 text-sm font-medium text-gray-600 transition hover:text-[#57068c] dark:text-gray-400 dark:hover:text-white"
				>
					Unselect All
				</button>
			</div>

			{#if selectedConcepts.size > 0}
				<button
					on:click={handleGenerate}
					class="px-6 py-2 text-sm font-medium text-[#57068c] transition hover:text-purple-700 dark:text-white dark:hover:text-gray-200"
				>
					Generate ({selectedConcepts.size})
				</button>
			{/if}
		</div>
	{/if}

	<!-- Concept Cards Grid -->
	<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
		{#each paginatedConcepts as concept}
			<button
				on:click={() => selectConcept(concept.name)}
				class="flex h-full flex-col items-stretch justify-start text-left align-top rounded-xl border p-5 transition {selectedConcepts.has(concept.name)
					? 'border-[#57068c]/40 bg-[#57068c]/5 dark:bg-[#57068c]/10 dark:border-[#57068c]/50'
					: 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-gray-600 dark:hover:bg-gray-800'}"
				disabled={TEMP_HIDE}
			>
				<div class="flex items-start justify-between gap-3">
					<h3 class="select-text text-base font-semibold text-gray-900 dark:text-gray-100">
						{concept.name}
					</h3>
				</div>
				<div class="mt-1 flex flex-1 flex-col">
					<div>
						<div class="text-[11px] font-semibold tracking-wide text-gray-400 dark:text-gray-500">
							{concept.testedIn.length === 1 ? 'In Homework:' : 'In Homeworks:'}
						</div>
						<div class="mt-2 flex flex-wrap gap-1.5">
							{#each concept.testedIn as homework}
								<div class="flex items-start gap-1.5 min-w-0">
									<span
										class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full p-0 text-xs transition-transform duration-150 will-change-transform {getStatusClasses(concept.homeworkStatuses[homework])} {hoveredLegendStatus === concept.homeworkStatuses[homework]
											? 'scale-110'
											: 'scale-100'}"
									>
										{homework.replace('Homework ', '')}
									</span>
								</div>
							{/each}
						</div>
					</div>
					<div class="mt-auto min-h-[1.5rem] pt-3 flex items-start gap-2 text-sm text-green-600 dark:text-green-400">
						{#if concept.practicedDate}
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
								<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
							</svg>
							<span>Practiced on {concept.practicedDate}</span>
						{/if}
					</div>
				</div>
			</button>
		{/each}
	</div>

	<!-- Pagination -->
	{#if filteredConcepts.length > 18}
		<div class="flex items-center justify-center gap-2 pt-4">
			<button
				on:click={previousPage}
				disabled={currentPage === 1}
				class="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition"
			>
				<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4">
					<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
				</svg>
			</button>

			{#each Array.from({ length: totalPages }, (_, i) => i + 1) as pageNum}
				<button
					on:click={() => goToPage(pageNum)}
					class="px-3 py-1 text-sm border rounded transition {currentPage === pageNum
						? 'bg-purple-600 text-white border-purple-600'
						: 'border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800'}"
				>
					{pageNum}
				</button>
			{/each}

			<button
				on:click={nextPage}
				disabled={currentPage === totalPages}
				class="px-3 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition"
			>
				<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4">
					<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
				</svg>
			</button>
		</div>
	{/if}
	</div>
</div>
