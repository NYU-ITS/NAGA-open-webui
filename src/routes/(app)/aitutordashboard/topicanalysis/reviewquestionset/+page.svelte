<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { TESTING_AI_TUTOR } from '$lib/constants';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';

	let selectedHomework = '';
	let homeworkOptions: string[] = [];

	async function loadQuestionSet() {
		if (!selectedHomework) return;
		try {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/practice?homework_id=${encodeURIComponent(selectedHomework)}`,
				{
					method: 'GET',
					headers: {
						Authorization: `Bearer ${localStorage.token}`
					}
				}
			);

			if (!response.ok) {
				throw new Error('Question set detail fetch failed');
			}

			const data = await response.json();
			if (Array.isArray(data) && data.length > 0) {
				const latest = [...data].sort(
					(a, b) => Number(b?.version_number ?? 0) - Number(a?.version_number ?? 0)
				)[0];
				questionData = {
					id: latest.id,
					version: `Version ${latest.version_number ?? 1} - ${latest.source ?? 'AI generated'}`,
					status: latest.status ?? 'pending',
					date: latest.created_at ?? '',
					questions: [{ markdown: latest.problem_data ?? '' }]
				};
			}

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Loaded practice question set from /practice.');
			}
		} catch (error) {
			if (TESTING_AI_TUTOR) {
				toast.warning('[FAIL][GET]: Practice question set fallback to placeholder data.');
			}
			console.error('Question set detail API failed:', error);
		}
	}

	onMount(async () => {
		console.log('Review Question Set loaded');
		try {
			const response = await fetch(`${AI_TUTOR_API_BASE}/homework`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});
			if (response.ok) {
				const data = await response.json();
				if (Array.isArray(data)) {
					homeworkOptions = data.map((hw) => hw.id);
				}
			}
		} catch (error) {
			console.error('Homework list API failed:', error);
		}

		const queryHomeworkId = $page.url.searchParams.get('homework_id');
		selectedHomework = queryHomeworkId || homeworkOptions[0] || 'Homework 1';
		await loadQuestionSet();
	});

	$: if (selectedHomework) {
		loadQuestionSet();
	}

	// Placeholder fallback when backend has no question set yet.
	// Sample question data in JSON format
	let questionData = {
		id: '',
		version: 'Version 1 - AI generated',
		status: 'pending',
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
		try {
			if (!questionData.id) {
				throw new Error('No practice question set id available for approval');
			}

			fetch(
				`${AI_TUTOR_API_BASE}/practice/${encodeURIComponent(questionData.id)}/status?status=approved`,
				{
					method: 'PATCH',
					headers: {
						Authorization: `Bearer ${localStorage.token}`,
						'Content-Type': 'application/json'
					}
				}
			)
				.then((response) => {
					if (!response.ok) {
						throw new Error('Question set approval failed');
					}

					questionData = { ...questionData, status: 'approved', date: new Date().toISOString() };
					if (TESTING_AI_TUTOR) {
						toast.success('[SUCCESS][PATCH]: approveQuestionSet() updates /practice/{id}/status.');
					}
				})
				.catch((error) => {
					if (TESTING_AI_TUTOR) {
						toast.warning('[FAIL][PATCH]: approveQuestionSet() failed.');
					}
					console.error('Question set approval API failed:', error);
				});
		} catch (error) {
			if (TESTING_AI_TUTOR) {
				toast.warning('[FAIL][PATCH]: approveQuestionSet() failed.');
			}
			console.error('Question set approval API failed:', error);
		}
	}

	function handleEdit() {
		if (TESTING_AI_TUTOR) {
			toast.warning('[MISSING][POST]: editQuestionSet() endpoint not implemented in backend yet.');
		}
		// MISSING: Frontend intends to submit instructor edits for an existing practice question set.
		// MISSING: Expected future backend endpoint (example): PATCH /practice/{practice_id}
		alert('Edit functionality coming soon');
	}

	function handleDownload() {
		// MISSING: Frontend intends to download server-generated question set file by homework/version.
		// MISSING: Expected future backend endpoint (example): GET /practice/{practice_id}/download
		// Current fallback: local download of currently loaded JSON payload.
		try {
			if (TESTING_AI_TUTOR) {
				toast.warning('[MISSING][GET]: downloadQuestionSet() backend endpoint not implemented yet.');
			}

			const dataStr = JSON.stringify(questionData, null, 2);
			const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
			const exportFileDefaultName = `${selectedHomework}_questions.json`;

			const linkElement = document.createElement('a');
			linkElement.setAttribute('href', dataUri);
			linkElement.setAttribute('download', exportFileDefaultName);
			linkElement.click();
		} catch (error) {
			console.error('Question set download fallback failed:', error);
		}
	}

	function handleUpload() {
		// MISSING: Frontend intends to upload instructor-authored question set for standardization and storage.
		// MISSING: Expected future backend endpoint (example): POST /practice/upload
		// Current fallback: no-op with user notice.
		if (TESTING_AI_TUTOR) {
			toast.warning('[MISSING][POST]: uploadQuestionSet() backend endpoint not implemented yet.');
		}
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
