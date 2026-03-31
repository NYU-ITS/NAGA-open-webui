<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { AI_TUTOR_API_BASE_URL, TESTING_AI_TUTOR } from '$lib/constants';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';

	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
	const testToast = showAITutorTestToast;

	type QuestionItem = Record<string, unknown>;
	type StudentAssignment = { name: string; topic: string };

	type QuestionSetData = {
		id: string;
		status: 'pending' | 'in_progress' | 'approved';
		generatedTime: string;
		questions: QuestionItem[];
	};

	type ReviewHomework = {
		homeworkId: string;
		practiceId: string | null;
		questionData: QuestionSetData;
		approvedQuestionIndexes: Set<number>;
		questionEditors: string[];
		studentAssignments: StudentAssignment[][];
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

	const fallbackHomeworkOptions = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester'
	];

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
	let homeworkLabelById: Record<string, string> = {};
	let reviewHomeworks: ReviewHomework[] = [];
	let currentHomeworkIndex = 0;

	function getHomeworkLabel(homeworkId: string) {
		return homeworkLabelById[homeworkId] ?? homeworkId;
	}

	function mapPracticeStatus(status: string | null | undefined): QuestionSetData['status'] {
		if (status === 'approved') return 'approved';
		if (status === 'pending' || status === 'rejected') return 'in_progress';
		return 'pending';
	}

	const cloneQuestions = (questions: QuestionItem[]) =>
		questions.map((item) => structuredClone(item));

	const fallbackReviewHomeworks = [
		{
			homeworkId: 'Homework2-MATH-Code-Section-Semester',
			generatedTime: '2026-03-23 09:00:00',
			status: 'in_progress' as const,
			questions: cloneQuestions(fallbackQuestions)
		},
		{
			homeworkId: 'Homework3-MATH-Code-Section-Semester',
			generatedTime: '2026-03-23 09:12:00',
			status: 'in_progress' as const,
			questions: cloneQuestions(
				fallbackQuestions.map((question, index) => ({
					...question,
					id: index + 1,
					question: `${String(question.question)} (Homework3-MATH-Code-Section-Semester)`,
					topic: index === 0 ? 'Integration' : index === 1 ? 'Derivatives' : 'Limits'
				}))
			)
		},
		{
			homeworkId: 'Homework4-MATH-Code-Section-Semester',
			generatedTime: '2026-03-23 09:25:00',
			status: 'in_progress' as const,
			questions: cloneQuestions(
				fallbackQuestions.map((question, index) => ({
					...question,
					id: index + 1,
					question: `${String(question.question)} (Homework4-MATH-Code-Section-Semester)`,
					topic: index === 0 ? 'Sequences' : index === 1 ? 'Optimization' : 'Trigonometry'
				}))
			)
		}
	];

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

	const buildQuestionEditors = (questions: QuestionItem[]) =>
		questions.map((question) => JSON.stringify(question, null, 2));

	const buildStudentAssignments = (questions: QuestionItem[]) => {
		return questions.map((question, index) => {
			const topic = String(question?.topic ?? 'General Practice');
			return fallbackStudents.slice(0, 3).map((name, studentIndex) => ({
				name,
				topic: studentIndex === 0 ? topic : index % 2 === 0 ? topic : `${topic} Review`
			}));
		});
	};

	const createReviewHomework = (
		homeworkId: string,
		questions: QuestionItem[],
		generatedTime = '2026-03-23 09:00:00',
		status: QuestionSetData['status'] = 'pending',
		practiceId: string | null = null
	): ReviewHomework => ({
		homeworkId,
		practiceId,
		questionData: {
			id: homeworkId,
			status,
			generatedTime,
			questions
		},
		approvedQuestionIndexes: new Set<number>(),
		questionEditors: buildQuestionEditors(questions),
		studentAssignments: buildStudentAssignments(questions)
	});

	const updateCurrentHomework = (updater: (homework: ReviewHomework) => ReviewHomework) => {
		const current = reviewHomeworks[currentHomeworkIndex];
		if (!current) return;
		const next = [...reviewHomeworks];
		next[currentHomeworkIndex] = updater(current);
		reviewHomeworks = next;
	};

	const refreshDerivedStatus = (homework: ReviewHomework) => {
		if (
			homework.questionData.questions.length > 0 &&
			homework.approvedQuestionIndexes.size === homework.questionData.questions.length
		) {
			return {
				...homework,
				questionData: { ...homework.questionData, status: 'approved' as const }
			};
		}

		if (homework.questionData.status !== 'pending') {
			return {
				...homework,
				questionData: { ...homework.questionData, status: 'in_progress' as const }
			};
		}

		return homework;
	};

	const parseQuestionEditor = (homework: ReviewHomework, index: number) => {
		try {
			const parsed = JSON.parse(homework.questionEditors[index]);
			if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
				throw new Error(`Question ${index + 1} must be a JSON object`);
			}
			return parsed as QuestionItem;
		} catch {
			throw new Error(`Question ${index + 1} is not valid JSON`);
		}
	};

	async function loadReviewHomework(homeworkId: string) {
		testToast(`Review Question Set fetch: practice homework=${homeworkId}`);
		try {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/practice?homework_id=${encodeURIComponent(homeworkId)}`,
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
				return createReviewHomework(
					homeworkId,
					normalizeQuestionPayload(latest.problem_data),
					latest.generated_time ?? latest.created_at ?? '2026-03-23 09:00:00',
					mapPracticeStatus(latest.status),
					latest.id ?? null
				);
			}

			testToast(`Review Question Set loaded /practice data for homework=${homeworkId}`);

			return null;
		} catch (error) {
			console.error('Question set detail API failed:', error);
			return null;
		}
	}

	function handleCancel() {
		goto('/aitutordashboard/topicanalysis');
	}

	function handleStart() {
		testToast(`Start is triggered | page=aitutordashboard - Review Question Set | homework=${currentReviewHomework?.homeworkId ?? 'none'}`);
		updateCurrentHomework((homework) => {
			if (homework.questionData.status === 'pending') {
				toast.success('Question review started.');
				return {
					...homework,
					questionData: { ...homework.questionData, status: 'in_progress' }
				};
			}
			return homework;
		});
	}

	async function handleSave() {
		testToast(`Save is triggered | page=aitutordashboard - Review Question Set | homework=${currentReviewHomework?.homeworkId ?? 'none'}`);
		try {
			const currentHomework = currentReviewHomework;
			updateCurrentHomework((homework) => {
				const parsedQuestions = homework.questionEditors.map((_, index) =>
					parseQuestionEditor(homework, index)
				);
				return refreshDerivedStatus({
					...homework,
					questionData: { ...homework.questionData, questions: parsedQuestions },
					studentAssignments: buildStudentAssignments(parsedQuestions)
				});
			});
			if (currentHomework?.practiceId) {
				const response = await fetch(
					`${AI_TUTOR_API_BASE}/practice/${encodeURIComponent(currentHomework.practiceId)}/status?status=approved`,
					{
						method: 'PATCH',
						headers: {
							Authorization: `Bearer ${localStorage.token}`
						}
					}
				);
				if (!response.ok) {
					const detail = await response.text();
					throw new Error(detail || 'Failed to approve practice question set.');
				}
				toast.success('Practice question set approved.');
				return;
			}
			toast.success('Question set changes saved locally.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to approve question set');
		}
	}

	function handleApproveQuestion(index: number) {
		testToast(`Approve is triggered | page=aitutordashboard - Review Question Set | question=${index + 1} | homework=${currentReviewHomework?.homeworkId ?? 'none'}`);
		try {
			updateCurrentHomework((homework) => {
				const parsedQuestion = parseQuestionEditor(homework, index);
				const nextQuestions = [...homework.questionData.questions];
				nextQuestions[index] = parsedQuestion;
				const nextApproved = new Set(homework.approvedQuestionIndexes);
				nextApproved.add(index);
				return refreshDerivedStatus({
					...homework,
					questionData: {
						...homework.questionData,
						questions: nextQuestions,
						status: 'in_progress'
					},
					approvedQuestionIndexes: nextApproved,
					studentAssignments: buildStudentAssignments(nextQuestions)
				});
			});
			toast.success(`Question ${index + 1} approved.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to approve question');
		}
	}

	function handleRegenerateQuestion(index: number) {
		testToast(`Regenerate is triggered | page=aitutordashboard - Review Question Set | question=${index + 1} | homework=${currentReviewHomework?.homeworkId ?? 'none'}`);
		try {
			updateCurrentHomework((homework) => {
				const parsedQuestion = parseQuestionEditor(homework, index);
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

				const nextQuestions = [...homework.questionData.questions];
				nextQuestions[index] = nextQuestion;
				const nextEditors = [...homework.questionEditors];
				nextEditors[index] = JSON.stringify(nextQuestion, null, 2);
				return {
					...homework,
					questionData: {
						...homework.questionData,
						questions: nextQuestions,
						status: 'in_progress'
					},
					questionEditors: nextEditors,
					studentAssignments: buildStudentAssignments(nextQuestions)
				};
			});

			toast.success(`Question ${index + 1} regenerated locally.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to regenerate question');
		}
	}

	function goToPreviousHomework() {
		if (currentHomeworkIndex > 0) currentHomeworkIndex -= 1;
	}

	function goToNextHomework() {
		if (currentHomeworkIndex < reviewHomeworks.length - 1) currentHomeworkIndex += 1;
	}

	function selectHomeworkByIndex(index: number) {
		currentHomeworkIndex = index;
	}

	function handleHomeworkSelectChange(event: Event) {
		selectHomeworkByIndex((event.currentTarget as HTMLSelectElement).selectedIndex);
	}

	$: currentReviewHomework = reviewHomeworks[currentHomeworkIndex];
	$: questionData = currentReviewHomework?.questionData ?? {
		id: '',
		status: 'pending',
		generatedTime: '2026-03-23 09:00:00',
		questions: fallbackQuestions
	};
	$: approvedQuestionIndexes = currentReviewHomework?.approvedQuestionIndexes ?? new Set<number>();
	$: questionEditors =
		currentReviewHomework?.questionEditors ?? buildQuestionEditors(fallbackQuestions);
	$: studentAssignments =
		currentReviewHomework?.studentAssignments ?? buildStudentAssignments(fallbackQuestions);

	onMount(async () => {
		testToast('loading aitutordashboard - Review Question Set');
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
				const scopedHomeworks = Array.isArray(data)
					? data.filter((hw) => !groupId || hw.group_id === groupId)
					: [];
				if (scopedHomeworks.length > 0) {
					homeworkOptions = scopedHomeworks.map((hw) => hw.id);
					homeworkLabelById = Object.fromEntries(
						scopedHomeworks.map((hw) => [hw.id, hw.model_id ?? hw.id])
					);
				}
			}
		} catch (error) {
			console.error('Homework list API failed:', error);
		}

		if (homeworkOptions.length === 0) {
			homeworkOptions = fallbackHomeworkOptions;
			homeworkLabelById = Object.fromEntries(
				fallbackHomeworkOptions.map((homeworkId) => [homeworkId, homeworkId])
			);
		}

		const requestedHomeworkId =
			$page.url.searchParams.get('homework_id') ??
			homeworkOptions[0] ??
			'Homework1-MATH-Code-Section-Semester';
		const loadedReviewHomeworks = (
			await Promise.all(homeworkOptions.map((homeworkId) => loadReviewHomework(homeworkId)))
		).filter(
			(homework): homework is ReviewHomework =>
				!!homework &&
				(homework.questionData.status === 'pending' ||
					homework.questionData.status === 'in_progress' ||
					homework.questionData.status === 'approved')
		);

		reviewHomeworks =
			loadedReviewHomeworks.length > 0
				? loadedReviewHomeworks
				: fallbackReviewHomeworks.map((homework) =>
						createReviewHomework(
							homework.homeworkId,
							homework.questions,
							homework.generatedTime,
							homework.status
						)
					);

		const requestedIndex = reviewHomeworks.findIndex(
			(homework) => homework.homeworkId === requestedHomeworkId
		);
		currentHomeworkIndex = requestedIndex >= 0 ? requestedIndex : 0;
	});
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

		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			{JSON_EXPLANATION_PARAGRAPH}
		</p>
	</div>

	<div class="space-y-0">
		<div class="bg-white py-2 dark:bg-gray-900">
			<div class="flex items-end justify-between gap-4">
				<div class="w-full">
					<div class="flex items-center justify-between gap-3">
						<h2 class="text-xl font-semibold text-gray-900 dark:text-gray-100">Questions</h2>
						<div class="flex min-w-0 flex-1 items-center justify-end gap-2 text-sm">
							<div class="relative min-w-0">
								<select
									class="block max-w-[20rem] truncate appearance-none bg-transparent pr-5 text-sm text-gray-700 outline-hidden dark:text-gray-300"
									on:change={handleHomeworkSelectChange}
									value={currentReviewHomework?.homeworkId ?? ''}
									title={currentReviewHomework?.homeworkId ?? ''}
									aria-label="Select review homework"
								>
									{#each reviewHomeworks as homework}
										<option value={homework.homeworkId}>{getHomeworkLabel(homework.homeworkId)}</option>
									{/each}
								</select>
							</div>
							<button
								type="button"
								on:click={goToPreviousHomework}
								disabled={currentHomeworkIndex === 0}
								class="text-sm font-medium text-gray-900 transition hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-30 dark:text-gray-100 dark:hover:text-gray-300"
							>
								Prev
							</button>
							<button
								type="button"
								on:click={goToNextHomework}
								disabled={currentHomeworkIndex >= reviewHomeworks.length - 1}
								class="text-sm font-medium text-gray-900 transition hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-30 dark:text-gray-100 dark:hover:text-gray-300"
							>
								Next
							</button>
						</div>
					</div>
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

		<div class="space-y-6 py-6 rounded-lg border border-gray-200">
			{#each questionEditors as editor, index}
				<div class="bg-white pr-4 pl-4 dark:bg-gray-950">
					<div class="mb-2 flex items-center justify-between gap-3">
						<div class="text-base font-semibold text-gray-800 dark:text-gray-200">
							Q{index + 1}
						</div>
						<!-- <div class="flex items-center">
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
						</div> -->
					</div>

					<textarea
						bind:value={questionEditors[index]}
						rows="14"
						class="w-full rounded-lg border border-gray-200 bg-gray-50 px-4 py-1 font-mono text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-purple-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
					/>
				</div>
			{/each}

			<div class="flex items-center justify-end gap-3 pt-4 pr-4">
				<button
					on:click={handleCancel}
					class="px-6 py-2 text-sm font-semibold text-gray-700 transition hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
				>
					Regenerate
				</button>
				<button
					on:click={handleSave}
					class="rounded-full bg-black px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
				>
					Approve
				</button>
			</div>
		</div>
	</div>
</div>
