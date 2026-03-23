<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { TESTING_AI_TUTOR } from '$lib/constants';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';

	type QuestionItem = Record<string, unknown>;
	type StudentAssignment = { name: string; topic: string };

	type QuestionSetData = {
		id: string;
		status: 'pending' | 'in_progress' | 'approved';
		generatedTime: string;
		questions: QuestionItem[];
	};

	const STANDARD_QUESTION_TEMPLATE = {
		id: 1,
		question: 'Write the complete question prompt here.',
		topic: 'Topic Name',
		answer: 'Provide the expected final answer here.',
		steps: ['Step 1', 'Step 2'],
		difficulty: 'medium'
	};

	const GUIDE_JSON_EXAMPLE = JSON.stringify(STANDARD_QUESTION_TEMPLATE, null, 2);

	const JSON_EXPLANATION_PARAGRAPH =
		'Id is the question number used for tracking, question is the exact prompt students will see, topic is the skill being practiced, answer is the expected final answer, steps is the solution path, and difficulty is a quick label such as easy, medium, or hard.';

	const fallbackHomeworkOptions = ['Homework 1', 'Homework 2', 'Homework 3'];

	const fallbackQuestions: QuestionItem[] = [
		{
			id: 1,
			question: 'Solve the following quadratic equation: x² + 5x + 6 = 0',
			topic: 'Quadratic Equations',
			answer: 'x = -2 or x = -3',
			steps: ['Factor the equation', 'Set each factor to zero', 'Solve for x'],
			difficulty: 'medium'
		},
		{
			id: 2,
			question: 'Find the derivative of f(x) = 3x² + 2x - 5',
			topic: 'Differentiation',
			answer: "f'(x) = 6x + 2",
			steps: ['Apply power rule to each term', 'Combine the results'],
			difficulty: 'medium'
		},
		{
			id: 3,
			question: 'Calculate the limit: lim(x→0) (sin x)/x',
			topic: 'Limits',
			answer: '1',
			steps: ['Recognize standard limit', 'Apply limit rule'],
			difficulty: 'easy'
		}
	];

	const fallbackStudents = ['Alice Chen', 'Marco Patel', 'Nina Johnson', 'Leo Garcia'];

	let groupId = '';
	let homeworkOptions: string[] = [];
	let selectedHomeworks = new Set<string>();
	let selectedHomeworkLabel = 'Homework 1';
	let approvedQuestionIndexes = new Set<number>();
	let questionEditors: string[] = [];
	let studentAssignments: StudentAssignment[][] = [];

	let questionData: QuestionSetData = {
		id: '',
		status: 'pending',
		generatedTime: '2026-03-23 09:00:00',
		questions: fallbackQuestions
	};

	const cloneQuestions = (questions: QuestionItem[]) =>
		questions.map((item) => structuredClone(item));

	const normalizeQuestionPayload = (payload: unknown): QuestionItem[] => {
		if (Array.isArray(payload)) {
			return payload.map((item, idx) => {
				if (item && typeof item === 'object') return item as QuestionItem;
				return {
					id: idx + 1,
					question: String(item ?? ''),
					topic: 'Unknown',
					answer: '',
					steps: []
				};
			});
		}

		if (payload && typeof payload === 'object') {
			return [payload as QuestionItem];
		}

		if (typeof payload === 'string' && payload.trim()) {
			try {
				return normalizeQuestionPayload(JSON.parse(payload));
			} catch {
				return [
					{
						id: 1,
						question: payload,
						topic: 'Unknown',
						answer: '',
						steps: []
					}
				];
			}
		}

		return cloneQuestions(fallbackQuestions);
	};

	const syncEditorsFromQuestions = () => {
		questionEditors = questionData.questions.map((question) => JSON.stringify(question, null, 2));
	};

	const buildStudentAssignments = () => {
		studentAssignments = questionData.questions.map((question, index) => {
			const topic = String(question?.topic ?? 'General Practice');
			return fallbackStudents.slice(0, 3).map((name, studentIndex) => ({
				name,
				topic: studentIndex === 0 ? topic : index % 2 === 0 ? topic : `${topic} Review`
			}));
		});
	};

	const refreshDerivedStatus = () => {
		if (
			questionData.questions.length > 0 &&
			approvedQuestionIndexes.size === questionData.questions.length
		) {
			questionData = { ...questionData, status: 'approved' };
			return;
		}

		if (questionData.status !== 'pending') {
			questionData = { ...questionData, status: 'in_progress' };
		}
	};

	const parseQuestionEditor = (index: number) => {
		try {
			const parsed = JSON.parse(questionEditors[index]);
			if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
				throw new Error(`Question ${index + 1} must be a JSON object`);
			}
			return parsed as QuestionItem;
		} catch {
			throw new Error(`Question ${index + 1} is not valid JSON`);
		}
	};

	const applyQuestionSet = (questions: QuestionItem[], generatedTime?: string, status?: string) => {
		questionData = {
			...questionData,
			questions,
			generatedTime: generatedTime || '2026-03-23 09:00:00',
			status: (status as QuestionSetData['status']) || 'pending'
		};
		approvedQuestionIndexes = new Set<number>();
		syncEditorsFromQuestions();
		buildStudentAssignments();
	};

	async function loadQuestionSet() {
		const activeHomework = [...selectedHomeworks][0];
		if (!activeHomework) return;

		try {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/practice?homework_id=${encodeURIComponent(activeHomework)}`,
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
					status: (latest.status ?? 'pending') as QuestionSetData['status'],
					generatedTime: latest.generated_time ?? latest.created_at ?? '2026-03-23 09:00:00',
					questions: normalizeQuestionPayload(latest.problem_data)
				};
				syncEditorsFromQuestions();
				buildStudentAssignments();
			} else {
				applyQuestionSet(cloneQuestions(fallbackQuestions));
			}

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Loaded practice question set from /practice.');
			}
		} catch (error) {
			applyQuestionSet(cloneQuestions(fallbackQuestions));
			console.error('Question set detail API failed:', error);
		}
	}

	function toggleHomeworkSelection(homework: string) {
		const next = new Set(selectedHomeworks);
		if (next.has(homework)) {
			next.delete(homework);
		} else {
			next.add(homework);
		}

		if (next.size === 0) {
			next.add(homework);
		}

		selectedHomeworks = next;
		selectedHomeworkLabel = [...selectedHomeworks][0];
	}

	function handleCancel() {
		goto('/aitutordashboard/topicanalysis');
	}

	function handleStart() {
		if (questionData.status === 'pending') {
			questionData = { ...questionData, status: 'in_progress' };
			toast.success('Question review started.');
		}
	}

	function handleSave() {
		try {
			const parsedQuestions = questionEditors.map((_, index) => parseQuestionEditor(index));
			questionData = { ...questionData, questions: parsedQuestions };
			buildStudentAssignments();
			refreshDerivedStatus();
			toast.success('Question set changes saved locally.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to save question set');
		}
	}

	function handleApproveQuestion(index: number) {
		try {
			const parsedQuestion = parseQuestionEditor(index);
			const nextQuestions = [...questionData.questions];
			nextQuestions[index] = parsedQuestion;
			questionData = { ...questionData, questions: nextQuestions, status: 'in_progress' };

			const nextApproved = new Set(approvedQuestionIndexes);
			nextApproved.add(index);
			approvedQuestionIndexes = nextApproved;
			buildStudentAssignments();
			refreshDerivedStatus();
			toast.success(`Question ${index + 1} approved.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to approve question');
		}
	}

	function handleRegenerateQuestion(index: number) {
		try {
			const parsedQuestion = parseQuestionEditor(index);
			const topic = String(parsedQuestion.topic ?? 'General Practice');
			const nextQuestion = {
				...parsedQuestion,
				question: `${String(parsedQuestion.question ?? '')} (Regenerated draft)`,
				steps: [
					'Review weak-topic evidence',
					'Draft a cleaner question',
					'Check final answer and hints'
				],
				difficulty: parsedQuestion.difficulty ?? 'medium',
				topic
			};

			const nextQuestions = [...questionData.questions];
			nextQuestions[index] = nextQuestion;
			questionData = { ...questionData, questions: nextQuestions, status: 'in_progress' };
			questionEditors[index] = JSON.stringify(nextQuestion, null, 2);
			questionEditors = [...questionEditors];
			buildStudentAssignments();

			toast.success(`Question ${index + 1} regenerated locally.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to regenerate question');
		}
	}

	function getHomeworkNumber(homework: string) {
		const match = homework.match(/\d+/);
		return match ? match[0] : homework;
	}

	onMount(async () => {
		groupId = $page.url.searchParams.get('group_id') ?? '';

		try {
			const response = await fetch(`${AI_TUTOR_API_BASE}/homework`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});
			if (response.ok) {
				const data = await response.json();
				if (Array.isArray(data) && data.length > 0) {
					homeworkOptions = data.map((hw) => hw.id);
				}
			}
		} catch (error) {
			console.error('Homework list API failed:', error);
		}

		if (homeworkOptions.length === 0) {
			homeworkOptions = fallbackHomeworkOptions;
		}

		const queryHomeworkId =
			$page.url.searchParams.get('homework_id') ?? homeworkOptions[0] ?? 'Homework 1';
		selectedHomeworks = new Set([queryHomeworkId]);
		selectedHomeworkLabel = queryHomeworkId;
		await loadQuestionSet();
	});

	$: if (selectedHomeworks.size > 0 && selectedHomeworkLabel) {
		loadQuestionSet();
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Guide</h2>
		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			Each question is stored as JSON so the platform can read the same structure every time. Edit
			the values, but keep the field names. Select homework for generating practice questions, click
			<span class="font-semibold">Start</span>, review each JSON block, and use
			<span class="font-semibold">Approve</span> when one question is ready.
		</p>
		<div
			class="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-4"
		>
			<pre
				class="overflow-x-auto text-xs text-gray-800 dark:text-gray-200 font-mono">{GUIDE_JSON_EXAMPLE}</pre>
		</div>

		<h4 class="text-base font-semibold text-gray-800 dark:text-gray-200">What Each Item Means</h4>

		<p
			class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed"
		>
			{JSON_EXPLANATION_PARAGRAPH}
		</p>
	</div>

	<div>
			<div class="space-y-2">
				<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Select Homework for Generating Practice Questions</h2>
				<div class="flex flex-wrap gap-x-6 gap-y-2">
					{#each homeworkOptions as homework}
						<label class="flex items-center gap-3 py-1">
							<input
								type="checkbox"
								checked={selectedHomeworks.has(homework)}
								on:change={() => toggleHomeworkSelection(homework)}
								class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
							/>
							<span class="text-sm text-gray-900 dark:text-gray-100"
								>{getHomeworkNumber(homework)}</span
							>
						</label>
					{/each}
				</div>
			</div>

		<div class="flex flex-wrap items-start justify-end gap-4">
				{#if questionData.status === 'pending'}
					<button
						on:click={handleStart}
						class="rounded-full bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
					>
						Start
					</button>
				{:else if questionData.status === 'in_progress'}
					<div
						class="rounded-full bg-amber-100 px-4 py-2 text-sm font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
					>
						In Progress
					</div>
				{:else}
					<div
						class="rounded-full bg-green-100 px-4 py-2 text-sm font-medium text-green-700 dark:bg-green-500/10 dark:text-green-300"
					>
						Approved
					</div>
				{/if}
			</div>
	</div>

	<div class="space-y-0">
		<div class="bg-white py-2 dark:bg-gray-900">
			<div class="flex items-end justify-between gap-4">
				<div>
					<h2 class="text-xl font-semibold text-gray-900 dark:text-gray-100">Questions</h2>
					<div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
						Generated on {questionData.generatedTime}
						<span class="ml-3"
							>{approvedQuestionIndexes.size}/{questionData.questions.length} approved</span
						>
						{#if groupId}
							<span class="ml-3">Group: {groupId}</span>
						{/if}
					</div>
				</div>
			</div>
		</div>

		<div class="space-y-6 py-2">
			{#each questionEditors as editor, index}
				<div class="bg-white p-4 dark:bg-gray-950">
					<div class="mb-2 flex items-center justify-between gap-3">
						<div class="text-lg font-semibold text-gray-800 dark:text-gray-200">
							Q{index + 1}
						</div>
						<div class="flex items-center gap-2">
							<button
								on:click={() => handleRegenerateQuestion(index)}
								class="rounded-full border border-gray-300 px-3 py-1.5 text-sm text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
							>
								Regenerate
							</button>
							<button
								on:click={() => handleApproveQuestion(index)}
								class={`w-[104px] rounded-full px-3 py-1.5 text-sm transition ${
									approvedQuestionIndexes.has(index)
										? 'bg-green-600 text-white'
										: 'border border-gray-300 text-gray-700 hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800'
								}`}
							>
								{approvedQuestionIndexes.has(index) ? 'Approved!' : 'Approve'}
							</button>
						</div>
					</div>

					<textarea
						bind:value={questionEditors[index]}
						rows="14"
						class="w-full rounded-lg border border-gray-200 bg-gray-50 px-4 py-1 font-mono text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-purple-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
					/>

					<div class="mt-4 px-1 py-1">
						<p class="text-sm text-gray-600 dark:text-gray-300">
							<span class="text-m text-gray-800 dark:text-gray-200">To students:</span>
							{#each studentAssignments[index] ?? [] as assignment, assignmentIndex}
								<span>
									{assignment.name}{assignmentIndex < (studentAssignments[index] ?? []).length - 1 ? ', ' : ''}
								</span>
							{/each}
						</p>
					</div>
				</div>
			{/each}
		</div>
	</div>

	<div class="flex items-center justify-end gap-3 pt-4">
		<button
			on:click={handleCancel}
			class="px-6 py-2 text-sm font-semibold text-gray-700 transition hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
		>
			Cancel
		</button>
		<button
			on:click={handleSave}
			class="rounded-full bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
		>
			Save
		</button>
	</div>
</div>
