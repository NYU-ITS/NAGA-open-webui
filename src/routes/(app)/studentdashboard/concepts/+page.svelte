<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';

	onMount(() => {
		console.log('Student Dashboard - Concepts loaded');

		// Check if there's a topic in URL query params
		const urlParams = new URLSearchParams(window.location.search);
		const topicParam = urlParams.get('topic');
		if (topicParam) {
			selectedConcepts.add(topicParam);
			selectedConcepts = selectedConcepts;
		}
	});

	let selectedConcepts: Set<string> = new Set();
	let selectedHomework = 'All'; // This should sync with parent layout

	// Sample concepts data - topics from homework
	const conceptsData = [
		{
			name: 'Linear Algebra',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Differentiation',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Integration',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Limit Definition',
			testedIn: ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Quadratic Equations',
			testedIn: ['Homework 1', 'Homework 2'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Polynomials',
			testedIn: ['Homework 2', 'Homework 3'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Factoring',
			testedIn: ['Homework 2', 'Homework 4'],
			practicedDate: null,
			isFinished: false
		},
		{
			name: 'Complex Numbers',
			testedIn: ['Homework 3', 'Homework 5'],
			practicedDate: null,
			isFinished: false
		},
		{
			name: 'Trigonometry',
			testedIn: ['Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Unit Circle',
			testedIn: ['Homework 4'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Trigonometric Identities',
			testedIn: ['Homework 4', 'Homework 5'],
			practicedDate: 'Jan 21',
			isFinished: true
		},
		{
			name: 'Inverse Functions',
			testedIn: ['Homework 5'],
			practicedDate: null,
			isFinished: false
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
			if (!concept.isFinished) {
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
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Selection Buttons -->
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-1">
			<button
				on:click={selectAllUnfinished}
				class="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-[#57068c] dark:hover:text-white rounded-lg transition"
			>
				Select All Unfinished
			</button>
			<button
				on:click={selectAll}
				class="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-[#57068c] dark:hover:text-white rounded-lg transition"
			>
				Select All
			</button>
			<button
				on:click={unselectAll}
				class="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-[#57068c] dark:hover:text-white rounded-lg transition"
			>
				Unselect All
			</button>
		</div>

		{#if selectedConcepts.size > 0}
			<button
				on:click={handleGenerate}
				class="px-6 py-2 text-sm font-medium text-[#57068c] dark:text-white hover:text-purple-700 dark:hover:text-gray-200 rounded-lg transition"
			>
				Generate ({selectedConcepts.size})
			</button>
		{/if}
	</div>

	<!-- Concept Cards Grid -->
	<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
		{#each paginatedConcepts as concept}
			<button
				on:click={() => selectConcept(concept.name)}
				class="text-left p-4 rounded-lg border transition {selectedConcepts.has(concept.name)
					? 'border-purple-500 bg-purple-50 dark:bg-purple-900/20'
					: 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-600'}"
			>
				<h3 class="text-base font-semibold text-gray-900 dark:text-gray-100 mb-2">
					{concept.name}
				</h3>
				<div class="space-y-1">
					<div class="text-sm text-gray-600 dark:text-gray-400">
						<span class="font-medium">This concept is tested in:</span>
						<span class="ml-1">{concept.testedIn.join(', ')}</span>
					</div>
					{#if concept.isFinished && concept.practicedDate}
						<div class="text-sm mt-2 flex items-center gap-1">
							<span class="font-medium text-green-600 dark:text-green-400">You have practiced in:</span>
							<span class="text-green-600 dark:text-green-400">{concept.practicedDate}</span>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-green-600 dark:text-green-400">
								<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
							</svg>
						</div>
					{/if}
				</div>
			</button>
		{/each}
	</div>

	<!-- Pagination -->
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
</div>
