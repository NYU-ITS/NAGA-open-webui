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
	const homeworkOptions = ['Homework 1', 'Homework 2', 'Homework 3', 'Homework 4'];
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
			homework: 'Homework 1',
			topics: ['Linear Algebra', 'Differentiation'],
			question: 'Find the eigenvalues of the matrix A and explain how they relate to the transformation.',
			completed: false
		},
		{
			id: 'hq-2',
			sequence: 2,
			homework: 'Homework 2',
			topics: ['Integration by Parts'],
			question: 'Compute the integral of x cos(x) dx and justify why integration by parts is the right method.',
			completed: true
		},
		{
			id: 'hq-3',
			sequence: 1,
			homework: 'Homework 3',
			topics: ['Limit Definition', 'Factoring'],
			question: 'Use the limit definition to derive the derivative of f(x)=x^2-4x, simplifying carefully at each step.',
			completed: false
		},
		{
			id: 'hq-4',
			sequence: 3,
			homework: 'Homework 4',
			topics: ['Trigonometric Identities'],
			question: 'Prove that 1 - cos(2x) = 2sin^2(x) and explain which identity you start from.',
			completed: true
		}
	];

	$: practicing = $page.url.searchParams.get('practicing');
	$: practicingValue = practicing ? String(practicing) : null;
	$: initialHomework = practicingValue
		? homeworkOptions.find((homework) => getHomeworkNumber(homework) === practicingValue)
		: null;
	$: initialTopics = initialHomework ? getTopicsForHomework(initialHomework) : topicOptions;

	let selectedHomeworks = new Set<string>(homeworkOptions);
	let selectedTopics = new Set<string>(topicOptions);
	let started = false;
	let lastPracticing: string | null = null;

	$: if (practicingValue !== lastPracticing) {
		lastPracticing = practicingValue;
		selectedHomeworks = initialHomework ? new Set([initialHomework]) : new Set(homeworkOptions);
		selectedTopics = initialHomework ? new Set(initialTopics) : new Set(topicOptions);
		started = false;
	}

	function toggleSelection(setterTarget: Set<string>, value: string) {
		if (setterTarget.has(value)) {
			setterTarget.delete(value);
		} else {
			setterTarget.add(value);
		}

		if (setterTarget === selectedHomeworks) {
			selectedHomeworks = new Set(setterTarget);
		} else {
			selectedTopics = new Set(setterTarget);
		}
	}

	function resetFilters() {
		started = false;
		selectedHomeworks = initialHomework ? new Set([initialHomework]) : new Set(homeworkOptions);
		selectedTopics = initialHomework ? new Set(initialTopics) : new Set(topicOptions);
	}

	function selectAllFilters() {
		selectedHomeworks = new Set(homeworkOptions);
		selectedTopics = new Set(topicOptions);
	}

	function startSelection() {
		started = true;
	}

	function getHomeworkNumber(homework: string) {
		return homework.replace('Homework ', '');
	}

	function formatTopicList(topics: string[]) {
		if (topics.length === 0) {
			return '';
		}

		if (topics.length === 1) {
			return topics[0];
		}

		if (topics.length === 2) {
			return `${topics[0]} and ${topics[1]}`;
		}

		return `${topics.slice(0, -1).join(', ')}, and ${topics.at(-1)}`;
	}

	function getTopicsForHomework(homework: string) {
		return topicOptions.filter((topic) =>
			questions.some((question) => question.homework === homework && question.topics.includes(topic))
		);
	}

	function getTopicsForSelectedHomeworks(homeworks: Set<string>) {
		return topicOptions.filter((topic) =>
			Array.from(homeworks).some((homework) =>
				questions.some((question) => question.homework === homework && question.topics.includes(topic))
			)
		);
	}

	$: filteredQuestions = questions.filter((question) => {
		const matchesHomework = selectedHomeworks.has(question.homework);
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
				<div class="space-y-3 {started ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'}">
					<h4 class="text-base font-semibold">Select Homework Practice Questions</h4>
					<div class="overflow-x-auto">
						<table class="min-w-full text-left text-sm">
							{#each homeworkOptions as homework}
								<tr class="align-top">
									<td class="w-7 py-1.5 pr-3 align-middle">
										<input
											type="checkbox"
											checked={selectedHomeworks.has(homework)}
											on:change={() => {
												toggleSelection(selectedHomeworks, homework);
												selectedTopics = new Set(getTopicsForSelectedHomeworks(selectedHomeworks));
											}}
											disabled={started}
											class="h-3 w-3 rounded-sm border-gray-300 text-gray-700 focus:ring-gray-500 disabled:cursor-default dark:border-gray-600 dark:bg-gray-900 dark:text-gray-300 dark:focus:ring-gray-400 {started ? 'accent-gray-700 dark:accent-gray-300' : ''}"
										/>
									</td>
									<td class="py-1.5 align-middle">
										<button
											type="button"
											class="text-left text-sm disabled:cursor-default"
											on:click={() => {
												toggleSelection(selectedHomeworks, homework);
												selectedTopics = new Set(getTopicsForSelectedHomeworks(selectedHomeworks));
											}}
											disabled={started}
										>
											<span class="font-semibold {started ? 'text-gray-500 dark:text-gray-400' : 'text-gray-900 dark:text-gray-100'}">{getHomeworkNumber(homework)}</span>
											<span class="mx-2 text-gray-300 dark:text-gray-600">|</span>
											<span>{formatTopicList(getTopicsForHomework(homework))}</span>
										</button>
									</td>
								</tr>
							{/each}
						</table>
					</div>
					<div class="flex items-center justify-between gap-3 pt-1 text-xs">
						<div class="flex items-center gap-3">
							<button
								type="button"
								class="font-medium text-gray-400 transition hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
								on:click={resetFilters}
							>
								Reset
							</button>
							<button
								type="button"
								class="font-medium text-gray-400 transition hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
								on:click={selectAllFilters}
							>
								Select All
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
					</div>
				</div>
			</section>

			<div class="border-t border-gray-200 dark:border-gray-700"></div>

			<div class="flex items-center text-base font-semibold {started ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-500'}">
				Questions
				{#if started}
					<div class="mx-2.5 h-5 w-px bg-gray-200 dark:bg-gray-700"></div>
					<span class="text-base font-medium text-gray-500 dark:text-gray-300">{completedCount}/{filteredQuestions.length}</span>
				{/if}
			</div>
			<section>
				<div class="space-y-3 {!started ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-gray-100'}">
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
