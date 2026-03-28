<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { showControls, showRightsideQuestions } from '$lib/stores';

	type PracticeQuestion = {
		id: string;
		sequence: number;
		homework: string;
		topics: string[];
		question: string;
		completed?: boolean;
	};

	const groupName = 'MATH-I - InstructorName - CourseCode - Section';
	const homeworkOptions = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester',
		'Homework4-MATH-Code-Section-Semester'
	];
	const topicOptions = [
		'Linear Algebra',
		'Differentiation',
		'Integration by Parts',
		'Limit Definition',
		'Factoring',
		'Trigonometric Identities'
	];

	const questions: PracticeQuestion[] = [
		{
			id: 'hq-1',
			sequence: 1,
			homework: 'Homework1-MATH-Code-Section-Semester',
			topics: ['Linear Algebra', 'Differentiation'],
			question: 'Find the eigenvalues of the matrix A and explain how they relate to the transformation.',
			completed: false
		},
		{
			id: 'hq-2',
			sequence: 2,
			homework: 'Homework2-MATH-Code-Section-Semester',
			topics: ['Integration by Parts'],
			question: 'Compute the integral of x cos(x) dx and justify why integration by parts is the right method.',
			completed: true
		},
		{
			id: 'hq-3',
			sequence: 1,
			homework: 'Homework3-MATH-Code-Section-Semester',
			topics: ['Limit Definition', 'Factoring'],
			question: 'Use the limit definition to derive the derivative of f(x)=x^2-4x, simplifying carefully at each step.',
			completed: false
		},
		{
			id: 'hq-4',
			sequence: 3,
			homework: 'Homework4-MATH-Code-Section-Semester',
			topics: ['Trigonometric Identities'],
			question: 'Prove that 1 - cos(2x) = 2sin^2(x) and explain which identity you start from.',
			completed: true
		}
	];

	$: practicing = $page.url.searchParams.get('practicing');
	$: practicingValue = practicing ? String(practicing) : null;
	$: initialHomework =
		practicingValue && homeworkOptions[Number(practicingValue) - 1]
			? homeworkOptions[Number(practicingValue) - 1]
			: homeworkOptions[0];
	$: initialTopics = getTopicsForHomework(initialHomework);

	let selectedHomework = initialHomework;
	let selectedTopics = new Set<string>(topicOptions);
	let started = false;
	let lastPracticing: string | null = null;

	$: if (practicingValue !== lastPracticing) {
		lastPracticing = practicingValue;
		selectedHomework = initialHomework;
		selectedTopics = new Set(initialTopics);
		started = false;
	}

	function resetFilters() {
		started = false;
		selectedHomework = initialHomework;
		selectedTopics = new Set(initialTopics);
	}

	function startSelection() {
		started = true;
	}

	function getTopicsForHomework(homework: string) {
		return topicOptions.filter((topic) =>
			questions.some((question) => question.homework === homework && question.topics.includes(topic))
		);
	}

	function getSelectedHomeworkIndex(homework: string) {
		return Math.max(
			0,
			homeworkOptions.findIndex((option) => option === homework)
		);
	}

	function setSelectedHomework(homework: string) {
		selectedHomework = homework;
		selectedTopics = new Set(getTopicsForHomework(homework));
		started = false;
	}

	function goToPreviousHomework() {
		const nextIndex = getSelectedHomeworkIndex(selectedHomework) - 1;
		if (nextIndex >= 0) {
			setSelectedHomework(homeworkOptions[nextIndex]);
		}
	}

	function goToNextHomework() {
		const nextIndex = getSelectedHomeworkIndex(selectedHomework) + 1;
		if (nextIndex < homeworkOptions.length) {
			setSelectedHomework(homeworkOptions[nextIndex]);
		}
	}

	function handleHomeworkChange(event: Event) {
		setSelectedHomework((event.currentTarget as HTMLSelectElement).value);
	}

	$: filteredQuestions = questions.filter((question) => {
		const matchesHomework = question.homework === selectedHomework;
		const matchesTopic =
			selectedTopics.size === 0 || question.topics.some((topic) => selectedTopics.has(topic));

		return matchesHomework && matchesTopic;
	});

	$: completedCount = filteredQuestions.filter((question) => question.completed).length;

	async function closePanel() {
		if (!window.confirm('Close homework practice questions?')) {
			return;
		}

		const params = new URLSearchParams($page.url.searchParams);
		params.delete('practicing');

		showRightsideQuestions.set(false);
		showControls.set(false);
		await goto(`${$page.url.pathname}${params.toString() ? `?${params.toString()}` : ''}`, {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}
</script>

<div class="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
	<div class="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4 dark:border-gray-700">
		<div>
			<h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">Practice Questions</h3>
			<div class="mt-1 text-xs text-gray-500 dark:text-gray-400">{groupName}</div>
		</div>
		<button
			on:click={closePanel}
			class="rounded p-1 transition hover:bg-gray-100 dark:hover:bg-gray-800"
			aria-label="Close panel"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke-width="2"
				stroke="currentColor"
				class="h-3.5 w-3.5 text-gray-600 dark:text-gray-400"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<div class="flex-1 overflow-y-auto px-5 py-4" style:scrollbar-gutter="stable">
		<div class="space-y-6">
			<section>
				<!-- {started ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'} -->
				<div class="space-y-3 text-gray-900 dark:text-gray-100">
					<div class="flex items-center justify-between gap-3 text-sm">
						<div class="relative min-w-0 flex-1">
							<select
								bind:value={selectedHomework}
								on:change={handleHomeworkChange}
								disabled={started}
								class="block w-full truncate appearance-none bg-transparent pr-5 text-sm text-gray-700 outline-hidden disabled:cursor-default dark:text-gray-300"
								title={selectedHomework}
								aria-label="Select homework practice question set"
							>
								{#each homeworkOptions as homework}
									<option value={homework}>{homework}</option>
								{/each}
							</select>
						</div>
						<div class="ml-auto flex shrink-0 items-center gap-2">
							<button
								type="button"
								class="text-sm font-medium text-gray-900 transition hover:text-gray-700 disabled:text-gray-400 dark:text-gray-100 dark:hover:text-gray-300 dark:disabled:text-gray-500"
								on:click={goToPreviousHomework}
								disabled={started || getSelectedHomeworkIndex(selectedHomework) === 0}
							>
								Prev
							</button>
							<button
								type="button"
								class="text-sm font-medium text-gray-900 transition hover:text-gray-700 disabled:text-gray-400 dark:text-gray-100 dark:hover:text-gray-300 dark:disabled:text-gray-500"
								on:click={goToNextHomework}
								disabled={started || getSelectedHomeworkIndex(selectedHomework) === homeworkOptions.length - 1}
							>
								Next
							</button>
						</div>
					</div>
					<!-- <div class="flex items-center justify-between gap-3 pt-1 text-xs">
						<div class="flex items-center gap-3">
							<button
								type="button"
								class="font-medium text-gray-400 transition hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
								on:click={resetFilters}
							>
								Reset
							</button>
						</div>
						<button
							type="button"
							class="text-sm font-medium {started
								? 'text-gray-400 dark:text-gray-500'
								: 'text-gray-900 hover:text-gray-700 dark:text-gray-100 dark:hover:text-gray-300'} transition"
							on:click={startSelection}
						>
							{started ? 'In Progress' : 'Start'}
						</button>
					</div> -->
				</div>
			</section>
			<!-- {started ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-500'} -->
			<div class="flex items-center text-base font-semibold text-gray-900 dark:text-gray-100">
				Questions
				{#if started}
					<div class="mx-2.5 h-5 w-px bg-gray-200 dark:bg-gray-700"></div>
					<span class="text-base font-medium text-gray-500 dark:text-gray-300">{completedCount}/{filteredQuestions.length}</span>
				{/if}
			</div>
			<section>
				<!-- {!started ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'} -->
				<div class="space-y-3 text-gray-900 dark:text-gray-100">
					{#each filteredQuestions as question}
						<article class="space-y-1">
							<p class="text-sm leading-6 mt-6 mb-1">{question.question}</p>
							<div class="min-h-[1.25rem]">
								{#if started}
									<button
										type="button"
										class="text-left text-sm font-semibold text-gray-600 transition hover:text-gray-800 dark:text-gray-300 dark:hover:text-gray-100"
									>
										{question.completed ? 'Completed!' : 'Go'}
									</button>
								{/if}
							</div>
						</article>
					{/each}

					{#if filteredQuestions.length === 0}
						<div class="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
							No questions match the selected homework and topics.
						</div>
					{/if}
				</div>
			</section>
		</div>
	</div>
</div>
