<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		console.log('Review Question Set loaded');
	});

	let selectedHomework = 'Homework 1';

	const homeworkOptions = [
		'Homework 1',
		'Homework 2',
		'Homework 3',
		'Homework 4',
		'Homework 5',
		'Homework 6',
		'Homework 7'
	];

	// Sample question data in JSON format
	const questionData = {
		version: 'Version 1 - AI generated',
		status: 'approved',
		date: '2026-01-02 12:23:12',
		questions: [
			{
				id: 1,
				question: 'Solve the following quadratic equation: x² + 5x + 6 = 0',
				topic: 'Quadratic Equations',
				answer: 'x = -2 or x = -3',
				steps: ['Factor the equation', 'Set each factor to zero', 'Solve for x']
			},
			{
				id: 2,
				question: 'Find the derivative of f(x) = 3x² + 2x - 5',
				topic: 'Differentiation',
				answer: "f'(x) = 6x + 2",
				steps: ['Apply power rule to each term', 'Combine the results']
			},
			{
				id: 3,
				question: 'Calculate the limit: lim(x→0) (sin x)/x',
				topic: 'Limits',
				answer: '1',
				steps: ['Recognize standard limit', 'Apply limit rule']
			}
		]
	};

	function handleBack() {
		goto('/aitutordashboard/topicanalysis');
	}

	function handleApprove() {
		// Handle approval logic
		alert('Question set approved!');
	}

	function handleEdit() {
		alert('Edit functionality coming soon');
	}

	function handleDownload() {
		const dataStr = JSON.stringify(questionData, null, 2);
		const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
		const exportFileDefaultName = `${selectedHomework}_questions.json`;

		const linkElement = document.createElement('a');
		linkElement.setAttribute('href', dataUri);
		linkElement.setAttribute('download', exportFileDefaultName);
		linkElement.click();
	}

	function handleUpload() {
		alert('Upload functionality coming soon');
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Header with Course Title -->

	<!-- Guide Section -->
	<div class="space-y-2">
		<h3 class="text-m font-semibold text-gray-800 dark:text-gray-200">Guide</h3>
		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			Start with an AI-generated question set based on students' weak topics, or upload your own questions.
			You can download, edit, and re-upload AI-generated content if needed. All uploaded question sets are
			automatically standardized by the system, with topics added and answers generated if missing, to ensure
			a consistent format across the platform.
		</p>
	</div>

	<!-- Homework Selection Dropdown -->
	<div class="flex items-center gap-3">
		<label class="text-sm font-medium text-gray-700 dark:text-gray-300">
			Select Homework:
		</label>
		<select
			bind:value={selectedHomework}
			class="px-6 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-purple-500 text-left"
		>
			{#each homeworkOptions as option}
				<option value={option}>{option}</option>
			{/each}
		</select>
	</div>

	<!-- Version Status Banner and Question Display -->
	<div class="space-y-0">
		<div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-t-lg p-4 border-b-0">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-3">
					<h3 class="text-m font-semibold text-gray-800 dark:text-gray-200">
						{questionData.version}
					</h3>
					{#if questionData.status === 'approved'}
						<div class="flex items-center gap-2">
							<span class="w-2 h-2 rounded-full bg-green-500"></span>
							<span class="text-sm text-gray-600 dark:text-gray-400">
								Approved on {questionData.date}
							</span>
						</div>
					{/if}
				</div>
				<div class="flex items-center gap-2">
					<button
						on:click={handleEdit}
						class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition"
					>
						Edit
					</button>
					<button
						on:click={handleDownload}
						class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition"
					>
						Download
					</button>
					<button
						on:click={handleUpload}
						class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition"
					>
						Upload Question Set
					</button>
				</div>
			</div>
		</div>

		<!-- Question Display in JSON Format -->
		<div class="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-b-lg p-4 overflow-x-auto">
			<pre class="text-sm text-gray-800 dark:text-gray-200 font-mono">{JSON.stringify(questionData.questions, null, 2)}</pre>
		</div>
	</div>

	<!-- Action Buttons -->
	<div class="flex items-center justify-end gap-3 pt-4">
		<button
			on:click={handleBack}
			class="px-6 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition"
		>
			Back
		</button>
		<button
			on:click={handleApprove}
			class="px-6 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition"
		>
			Approve
		</button>
	</div>
</div>
