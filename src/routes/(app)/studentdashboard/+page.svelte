<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { showControls, showRightsideQuestions } from '$lib/stores';

	onMount(() => {
		console.log('Student Dashboard - Summary loaded');
	});

	// TODO(student-dashboard-backend): Replace this placeholder summary with student-level
	// analysis data from the AI Tutor backend. Expected shape:
	// - homework_id / homework title
	// - mastered topics
	// - needs-practice topics
	// - total / solved / attempted / error counts
	const homeworkData = [
		{
			homework: 'Homework 1',
			masteredTopics: ['Linear Algebra', 'Differentiation'],
			needMorePractice: ['Integration', 'Limit Definition'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10,
			notStarted: false
		},
		{
			homework: 'Homework 2',
			masteredTopics: ['Quadratic Equations', 'Polynomials'],
			needMorePractice: ['Factoring', 'Complex Numbers'],
			totalCount: 12,
			solved: 8,
			attempted: 10,
			errors: 4,
			notStarted: false
		},
		{
			homework: 'Homework 3',
			masteredTopics: ['Trigonometry', 'Unit Circle'],
			needMorePractice: ['Trigonometric Identities', 'Inverse Functions'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10,
			notStarted: false
		},
		{
			homework: 'Homework 4',
			masteredTopics: [],
			needMorePractice: [],
			totalCount: null,
			solved: null,
			attempted: null,
			errors: null,
			notStarted: true
		},
		{
			homework: 'Homework 5',
			masteredTopics: ['Integrals', 'Substitution'],
			needMorePractice: ['Integration by Parts', 'Partial Fractions'],
			totalCount: 12,
			solved: 7,
			attempted: 9,
			errors: 5,
			notStarted: false
		}
	];

	const practiceAssignments = [
		{
			id: 'practice-1',
			index: 1,
			topic: 'Integration, Limit Definition',
			status: 'Ready'
		},
		{
			id: 'practice-2',
			index: 2,
			topic: 'Factoring, Complex Numbers',
			status: 'Not Ready'
		},
		{
			id: 'practice-3',
			index: 3,
			topic: 'Trigonometric Identities, Inverse Functions',
			status: 'Completed'
		}
	];

	function goToConcepts(topic: string) {
		window.location.href = `/studentdashboard/concepts?topic=${encodeURIComponent(topic)}`;
	}

	async function startPracticeAssignment(item) {
		// TODO(student-dashboard-backend): Replace this placeholder entry with the real
		// student assigned-practice / follow-up question workflow once backend support exists.
		console.log('[PracticeAssignment] opening empty right-side questions panel', {
			assignmentId: item.id,
			topic: item.topic
		});
		showControls.set(true);
		showRightsideQuestions.set(true);
		await goto('/');
	}

	async function updateDashboardFilters(nextHomework = selectedHomework, nextTopic = topicQueryRaw) {
		const params = new URLSearchParams($page.url.searchParams);

		if (!nextHomework || nextHomework === 'All') {
			params.delete('homework');
		} else {
			params.set('homework', nextHomework);
		}

		if (!nextTopic || nextTopic.trim() === '') {
			params.delete('topic');
		} else {
			params.set('topic', nextTopic.trim());
		}

		const query = params.toString();
		await goto(`${$page.url.pathname}${query ? `?${query}` : ''}`, {
			keepFocus: true,
			noScroll: true,
			replaceState: true
		});
	}

	function handleTopicInput(event: Event) {
		updateDashboardFilters(selectedHomework, (event.currentTarget as HTMLInputElement).value);
	}

	function handleHomeworkChange(event: Event) {
		updateDashboardFilters((event.currentTarget as HTMLSelectElement).value, topicQueryRaw);
	}

	$: selectedHomework = $page.url.searchParams.get('homework') || 'All';
	$: topicQueryRaw = $page.url.searchParams.get('topic') || '';
	$: topicQuery = topicQueryRaw.trim().toLowerCase();
	$: homeworkOptions = ['All', ...homeworkData.map((hw) => hw.homework)];
	$: filteredHomeworkData = homeworkData.filter((hw) => {
		const matchesHomework = selectedHomework === 'All' || hw.homework === selectedHomework;
		const matchesTopic =
			topicQuery === '' ||
			[...hw.masteredTopics, ...hw.needMorePractice].some((topic) =>
				topic.toLowerCase().includes(topicQuery)
			);

		return matchesHomework && matchesTopic;
	});
</script>

<div class="flex flex-col space-y-6 py-4">
	<div class="flex flex-wrap items-center justify-between gap-4">
		<div class="flex md:self-center text-lg font-medium px-0.5">
			By Homework
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
			<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{filteredHomeworkData.length}</span>
		</div>

		<div class="flex gap-6">
			<div class="relative w-full sm:w-72">
				<input
					value={topicQueryRaw}
					on:input={handleTopicInput}
					class="w-full bg-transparent px-4 py-2 text-sm text-gray-700 outline-hidden placeholder:text-gray-400 dark:text-gray-300 dark:placeholder:text-gray-500"
					placeholder="Search Topics"
				/>
			</div>

			<div class="relative">
				<select
					bind:value={selectedHomework}
					on:change={handleHomeworkChange}
					class="appearance-none bg-transparent py-2 pr-5 text-sm font-medium text-gray-700 outline-hidden dark:text-gray-300"
				>
					{#each homeworkOptions as option}
						<option value={option}>{option}</option>
					{/each}
				</select>
				<div class="pointer-events-none absolute inset-y-0 right-0 flex items-center text-gray-500 dark:text-gray-400">
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
						<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
					</svg>
				</div>
			</div>
		</div>
	</div>

	<div class="scrollbar-hidden relative max-w-full overflow-x-auto rounded-sm pt-0.5">
		<table class="min-w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400">
			<thead class="-translate-y-0.5 bg-gray-50 text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400">
				<tr>
					<th class="px-4 py-2 text-left font-semibold">
						#
					</th>
					<th class="px-4 py-2 text-left font-semibold">
						Mastered
					</th>
					<th class="px-4 py-2 text-left font-semibold">
						Need More Practice
					</th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap">
						Total
					</th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap">
						Solved
					</th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap">
						Attempted
					</th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap">
						Errors
					</th>
				</tr>
			</thead>
			<tbody>
				{#each filteredHomeworkData as hw, index}
					<tr class="border-t border-gray-100 bg-white transition hover:bg-gray-50 dark:border-gray-850 dark:bg-gray-900 dark:hover:bg-gray-800">
						<td class="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
							{index + 1}
						</td>
						{#if hw.notStarted}
							<td colspan="6" class="px-4 py-3 text-center text-xs text-gray-400 dark:text-gray-500">
								This homework&apos;s analysis has not been available.
							</td>
						{:else}
							<td class="px-4 py-3">
								<div class="flex flex-wrap gap-2">
									{#each hw.masteredTopics as topic}
										<button
											on:click={() => goToConcepts(topic)}
											class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
										>
											{topic}
										</button>
									{/each}
								</div>
							</td>
							<td class="px-4 py-3">
								<div class="flex flex-wrap gap-2">
									{#each hw.needMorePractice as topic}
										<button
											on:click={() => goToConcepts(topic)}
											class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
										>
											{topic}
										</button>
									{/each}
								</div>
							</td>
							<td class="px-4 py-3 text-center text-gray-900 dark:text-gray-100">
								{hw.totalCount}
							</td>
							<td class="px-4 py-3 text-center text-gray-900 dark:text-gray-100">
								{hw.solved}
							</td>
							<td class="px-4 py-3 text-center text-gray-900 dark:text-gray-100">
								{hw.attempted}
							</td>
							<td class="px-4 py-3 text-center text-gray-900 dark:text-gray-100">
								{hw.errors}
							</td>
						{/if}
					</tr>
				{/each}
				{#if filteredHomeworkData.length === 0}
					<tr>
						<td colspan="8" class="px-6 py-10 text-center text-sm text-gray-500 dark:text-gray-400">
							No homework matches the current homework/topic filters.
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>

	<div class="space-y-3">
		<div class="flex md:self-center text-lg font-medium px-0.5">
			Practice Questions / Follow Up Questions
		</div>

		<div class="scrollbar-hidden relative max-w-full overflow-x-auto rounded-sm pt-0.5">
			<table class="min-w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400">
				<thead class="-translate-y-0.5 bg-gray-50 text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400">
					<tr>
						<th class="w-[64px] px-4 py-2 text-left font-semibold">#</th>
						<th class="px-4 py-2 text-left font-semibold">Topic</th>
						<th class="px-4 py-2 text-left font-semibold">Status</th>
						<th class="px-4 py-2 text-left font-semibold">Action</th>
					</tr>
				</thead>
				<tbody>
					{#each practiceAssignments as item}
						<tr
							class="border-t border-gray-100 bg-white transition hover:bg-gray-50 dark:border-gray-850 dark:bg-gray-900 dark:hover:bg-gray-800 cursor-pointer"
							on:click={() => startPracticeAssignment(item)}
						>
							<td class="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{item.index}</td>
							<td class="px-4 py-3 text-gray-900 dark:text-gray-100">{item.topic}</td>
							<td class="px-4 py-3">
								<span
									class="rounded-full px-2.5 py-1 text-xs font-medium {item.status === 'Completed'
										? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
										: item.status === 'Ready'
											? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
											: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'}"
								>
									{item.status}
								</span>
							</td>
							<td class="px-4 py-3">
								<button
									class="text-xs font-medium text-black transition hover:text-gray-700 dark:text-white dark:hover:text-gray-300"
									on:click|stopPropagation={() => startPracticeAssignment(item)}
								>
									Start
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>
