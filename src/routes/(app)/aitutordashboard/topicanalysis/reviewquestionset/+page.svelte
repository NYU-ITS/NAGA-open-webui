<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { createNewModel, getModelById, updateModelById } from '$lib/apis/models/index';
	import {
		addFileToKnowledgeById,
		createNewKnowledge,
		updateKnowledgeById
	} from '$lib/apis/knowledge/index';
	import {
		AI_TUTOR_API_BASE_URL,
		AI_TUTOR_FRONTEND_TESTING_MODE,
		TESTING_AI_TUTOR
	} from '$lib/constants';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import {
		clearAITutorSessionCacheByPrefix,
		loadWithAITutorSessionCache
	} from '$lib/utils/aiTutorSessionCache';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';


	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;
	const testToast = showAITutorTestToast;
	const PRACTICE_QUESTION_SESSION_TTL_MS = 5 * 60 * 1000;
	const LAST_AI_TUTOR_GROUP_STORAGE_KEY = 'ai_tutor_last_selected_group_id';
	const PRACTICE_JOB_STORAGE_PREFIX = 'ai_tutor_active_practice_job';

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
		originalQuestionEditors: string[];
		studentAssignments: StudentAssignment[][];
	};

	const STANDARD_QUESTION_TEMPLATE = {
		number: 6,
		text: '**6.** Compute the difference quotient for the function $f(x) = x^2 - 3x + 2$:  \n(a) Simplify $\\frac{f(a + h) - f(a)}{h}$  \n(b) Evaluate the result when $a = 2$ and $h = 0.1$  \n(c) Rewrite the answer using $\\sqrt{x + 4}$, $\\ln(x)$, or $$\\int_0^1 x^2\\,dx = \\frac{1}{3}$$ when a problem needs radicals, logarithms, or display math.',
		topics: ['Difference Quotient', 'Simplification of Expressions']
	};

	const GUIDE_JSON_EXAMPLE = JSON.stringify(STANDARD_QUESTION_TEMPLATE, null, 2);

	const JSON_EXPLANATION_PARAGRAPH =
		'<span class="font-semibold">Number</span> is the displayed question number, <span class="font-semibold">text</span> is the full prompt students will see, and <span class="font-semibold">topics</span> is the list used for skill tagging. Only the <span class="font-semibold">text</span> property is rendered as Markdown + LaTeX preview, so you can use formats such as <span class="font-semibold">$...$</span> for inline math, <span class="font-semibold">$$...$$</span> for display math, and commands like <span class="font-semibold">\\frac</span>, <span class="font-semibold">\\sqrt</span>, and <span class="font-semibold">\\ln</span> inside the text string.';

	const fallbackStudents = ['Alice Chen', 'Marco Patel', 'Nina Johnson', 'Leo Garcia'];

	let groupId = '';
	let homeworkOptions: string[] = [];
	let homeworkLabelsById: Record<string, string> = {};
	let homeworkRows: {
		id: string;
		modelId: string | null;
		questionUploaded: boolean;
		answerUploaded: boolean;
		topicMapped: boolean;
	}[] = [];
	let homeworkIdsWithAnalysis = new Set<string>();
	let practiceLoading = false;
	let practiceQuestions = [];
	let generatingPracticeByHomeworkId: Record<string, boolean> = {};
	let generatingPracticeJobsByHomeworkId: Record<
		string,
		{ jobId: string; step: string; status: string; startedAt: string }
	> = {};
	let failedPracticeGenerationByHomeworkId: Record<
		string,
		{ message: string; failedAt: string }
	> = {};
	let sendingPracticeById: Record<string, boolean> = {};
	let assignmentSentAtByPracticeId: Record<string, string> = {};
	let resumedPracticeJobIds = new Set<string>();
	let reviewHomeworks: ReviewHomework[] = [];
	let currentHomeworkIndex = 0;
	let selectedHomework = '';
	let expandedGuide = true;
	let editingQuestionIndex: number | null = null;
	let approvingQuestionSet = false;

	function getPersistedGroupId() {
		if (typeof sessionStorage === 'undefined') return '';
		return sessionStorage.getItem(LAST_AI_TUTOR_GROUP_STORAGE_KEY) || '';
	}

	$: groupId = $page.url.searchParams.get('group_id') || getPersistedGroupId();
	$: if ($page.url.searchParams.get('group_id')) {
		if (typeof sessionStorage !== 'undefined') {
			sessionStorage.setItem(
				LAST_AI_TUTOR_GROUP_STORAGE_KEY,
				$page.url.searchParams.get('group_id') || ''
			);
		}
	}

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

		return [];
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
	): ReviewHomework => {
		const approvedIndexes =
			status === 'approved'
				? new Set(questions.map((_, index) => index))
				: new Set<number>();

		return {
			homeworkId,
			practiceId,
			questionData: {
				id: homeworkId,
				status,
				generatedTime,
				questions
			},
			approvedQuestionIndexes: approvedIndexes,
			questionEditors: buildQuestionEditors(questions),
			originalQuestionEditors: buildQuestionEditors(questions),
			studentAssignments: buildStudentAssignments(questions)
		};
	};

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
					normalizeQuestionPayload(
						Array.isArray(latest.problem_items) && latest.problem_items.length > 0
							? latest.problem_items
							: latest.problem_data
					),
					latest.generated_time ?? latest.created_at ?? '2026-03-23 09:00:00',
					(latest.status ?? 'pending') as QuestionSetData['status'],
					latest.id ?? null
				);
			}

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Loaded practice question set from /practice.');
			}

			return null;
		} catch (error) {
			console.error('Question set detail API failed:', error);
			return null;
		}
	}

	function handleCancel() {
		goto('/aitutordashboard/topicanalysis');
	}

	function replaceReviewHomework(nextHomework: ReviewHomework) {
		const existingIndex = reviewHomeworks.findIndex(
			(homework) => homework.homeworkId === nextHomework.homeworkId
		);
		if (existingIndex >= 0) {
			const next = [...reviewHomeworks];
			next[existingIndex] = nextHomework;
			reviewHomeworks = next;
			return;
		}
		reviewHomeworks = [...reviewHomeworks, nextHomework];
	}

	async function refreshReviewHomework(homeworkId: string) {
		const reloadedHomework = await loadReviewHomework(homeworkId);
		if (!reloadedHomework) return;
		replaceReviewHomework(reloadedHomework);
	}

	function handleStart() {
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

	function buildPracticeMarkdownFromQuestions(questions: QuestionItem[]) {
		const lines: string[] = [];
		for (const [index, question] of questions.entries()) {
			const number = question?.number ?? index + 1;
			const text =
				typeof question?.text === 'string'
					? question.text
					: typeof question?.question === 'string'
						? question.question
						: 'Practice question';
			const topics = Array.isArray(question?.topics)
				? question.topics.filter(Boolean).join(', ')
				: question?.topic
					? String(question.topic)
					: '';

			lines.push(`## Question ${number}`);
			if (topics) lines.push(`Topics: ${topics}`);
			lines.push('');
			lines.push(text);
			lines.push('');
		}
		return lines.join('\n').trim();
	}

	async function handleSave() {
		try {
			const currentHomework = currentReviewHomework;
			if (!currentHomework?.practiceId) {
				toast.success('Question set changes saved locally.');
				return;
			}

			const parsedQuestions = currentHomework.questionEditors.map((_, index) =>
				parseQuestionEditor(currentHomework, index)
			);
			const nextStatus =
				parsedQuestions.length > 0 &&
				currentHomework.approvedQuestionIndexes.size === parsedQuestions.length
					? ('approved' as const)
					: ('in_progress' as const);

			approvingQuestionSet = true;
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/practice/${encodeURIComponent(currentHomework.practiceId)}`,
				{
					method: 'PATCH',
					headers: {
						Authorization: `Bearer ${localStorage.token}`,
						'Content-Type': 'application/json'
					},
					body: JSON.stringify({
						problem_items: parsedQuestions,
						problem_data: buildPracticeMarkdownFromQuestions(parsedQuestions),
						status: 'approved'
					})
				}
			);
			if (!response.ok) {
				const detail = await response.text();
				throw new Error(detail || 'Failed to approve practice question set.');
			}

			const approvedPractice = await response.json();
			updateCurrentHomework((homework) =>
				refreshDerivedStatus({
					...homework,
					practiceId: approvedPractice?.id ?? homework.practiceId,
					questionData: {
						...homework.questionData,
						questions: parsedQuestions,
						status:
							(approvedPractice?.status as QuestionSetData['status'] | undefined) ??
							nextStatus
					},
					approvedQuestionIndexes:
						((approvedPractice?.status as QuestionSetData['status'] | undefined) ?? nextStatus) ===
						'approved'
							? new Set(parsedQuestions.map((_, index) => index))
							: homework.approvedQuestionIndexes,
					questionEditors: buildQuestionEditors(parsedQuestions),
					originalQuestionEditors: buildQuestionEditors(parsedQuestions),
					studentAssignments: buildStudentAssignments(parsedQuestions)
				})
			);

			clearAITutorSessionCacheByPrefix(`practice-question:${groupId}:practice`);
			await loadPracticeQuestionData();
			await refreshReviewHomework(currentHomework.homeworkId);
			await syncMasteryWorkspaceModel(currentHomework.homeworkId);
			toast.success('Practice question set approved.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to save question set');
		} finally {
			approvingQuestionSet = false;
		}
	}

	function resetQuestionEditorToCurrent(index: number) {
		updateCurrentHomework((homework) => {
			const nextEditors = [...homework.questionEditors];
			nextEditors[index] = JSON.stringify(homework.questionData.questions[index] ?? {}, null, 2);
			return {
				...homework,
				questionEditors: nextEditors
			};
		});
	}

	function cancelQuestionEdit(index: number) {
		resetQuestionEditorToCurrent(index);
		if (editingQuestionIndex === index) editingQuestionIndex = null;
	}

	function useOriginalQuestion(index: number) {
		updateCurrentHomework((homework) => {
			const nextEditors = [...homework.questionEditors];
			nextEditors[index] = homework.originalQuestionEditors[index] ?? nextEditors[index];
			return {
				...homework,
				questionEditors: nextEditors
			};
		});
	}

	async function saveQuestionEdit(index: number) {
		try {
			const currentHomework = currentReviewHomework;
			if (!currentHomework?.practiceId) {
				throw new Error('This practice set is missing a practice ID.');
			}

			const parsedQuestion = parseQuestionEditor(currentHomework, index);
			const nextQuestions = [...currentHomework.questionData.questions];
			nextQuestions[index] = parsedQuestion;
			const nextEditors = [...currentHomework.questionEditors];
			nextEditors[index] = JSON.stringify(parsedQuestion, null, 2);

			const response = await fetch(
				`${AI_TUTOR_API_BASE}/practice/${encodeURIComponent(currentHomework.practiceId)}`,
				{
					method: 'PATCH',
					headers: {
						Authorization: `Bearer ${localStorage.token}`,
						'Content-Type': 'application/json'
					},
					body: JSON.stringify({
						problem_items: nextQuestions,
						problem_data: buildPracticeMarkdownFromQuestions(nextQuestions)
					})
				}
			);
			if (!response.ok) {
				const detail = await response.text();
				throw new Error(detail || 'Failed to save practice question JSON.');
			}

			updateCurrentHomework((homework) =>
				refreshDerivedStatus({
					...homework,
					questionData: {
						...homework.questionData,
						questions: nextQuestions,
						status: 'in_progress'
					},
					questionEditors: nextEditors,
					originalQuestionEditors: nextEditors,
					studentAssignments: buildStudentAssignments(nextQuestions)
				})
			);
			clearAITutorSessionCacheByPrefix(`practice-question:${groupId}:practice`);
			await loadPracticeQuestionData();
			await refreshReviewHomework(currentHomework.homeworkId);
			await syncMasteryWorkspaceModel(currentHomework.homeworkId);
			if (editingQuestionIndex === index) editingQuestionIndex = null;
			toast.success(`Question ${index + 1} changes saved.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to save question JSON');
		}
	}

	function getEditorRows(editor: string) {
		const lineCount = (editor.match(/\n/g)?.length ?? 0) + 1;
		return Math.min(18, Math.max(8, lineCount + 1));
	}

	function updateQuestionEditor(index: number, value: string) {
		updateCurrentHomework((homework) => {
			const nextEditors = [...homework.questionEditors];
			nextEditors[index] = value;
			return {
				...homework,
				questionEditors: nextEditors
			};
		});
	}

	function handleQuestionEditorInput(index: number, event: Event) {
		updateQuestionEditor(index, (event.currentTarget as HTMLTextAreaElement).value);
	}

	function getQuestionPreviewText(editor: string) {
		try {
			const parsed = JSON.parse(editor);
			return typeof parsed?.text === 'string' ? parsed.text : '';
		} catch {
			return '';
		}
	}

	function handleApproveQuestion(index: number) {
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

	function getHomeworkLabel(homeworkId: string) {
		return homeworkLabelsById[homeworkId] ?? homeworkId;
	}

	function getHomeworkModelName(homeworkId: string) {
		return getHomeworkLabel(homeworkId);
	}

	function getPracticeJobStorageKey(currentGroupId: string, homeworkId: string) {
		return `${PRACTICE_JOB_STORAGE_PREFIX}:${currentGroupId}:${homeworkId}`;
	}

	function persistPracticeJobState(
		homeworkId: string,
		payload: { jobId: string; step: string; status: string; startedAt: string }
	) {
		if (typeof localStorage === 'undefined' || !groupId) return;
		localStorage.setItem(getPracticeJobStorageKey(groupId, homeworkId), JSON.stringify(payload));
	}

	function clearPracticeJobState(homeworkId: string) {
		if (typeof localStorage === 'undefined' || !groupId) return;
		localStorage.removeItem(getPracticeJobStorageKey(groupId, homeworkId));
	}

	function restorePersistedPracticeJobs() {
		if (typeof localStorage === 'undefined' || !groupId) return;
		const nextJobs: Record<string, { jobId: string; step: string; status: string; startedAt: string }> =
			{};
		const nextGeneratingFlags: Record<string, boolean> = { ...generatingPracticeByHomeworkId };

		for (let i = 0; i < localStorage.length; i += 1) {
			const key = localStorage.key(i);
			if (!key || !key.startsWith(`${PRACTICE_JOB_STORAGE_PREFIX}:${groupId}:`)) continue;
			const homeworkId = key.split(':').at(-1);
			if (!homeworkId) continue;
			try {
				const parsed = JSON.parse(localStorage.getItem(key) ?? '');
				if (parsed?.jobId) {
					nextJobs[homeworkId] = {
						jobId: parsed.jobId,
						step: parsed.step ?? 'queued',
						status: parsed.status ?? 'queued',
						startedAt: parsed.startedAt ?? ''
					};
					nextGeneratingFlags[homeworkId] = true;
				}
			} catch {
				localStorage.removeItem(key);
			}
		}

		generatingPracticeJobsByHomeworkId = nextJobs;
		generatingPracticeByHomeworkId = nextGeneratingFlags;
		console.log('AI Tutor Dashboard - Practice Question restored practice jobs', {
			groupId,
			jobs: Object.entries(nextJobs).map(([homeworkId, job]) => ({
				homeworkId,
				jobId: job.jobId,
				step: job.step,
				status: job.status,
				startedAt: job.startedAt
			}))
		});
	}

	function getSelectedHomeworkIndex(homeworkId: string) {
		return reviewHomeworks.findIndex((homework) => homework.homeworkId === homeworkId);
	}

	function goToPreviousHomework() {
		if (currentHomeworkIndex > 0) {
			currentHomeworkIndex -= 1;
			editingQuestionIndex = null;
		}
	}

	function goToNextHomework() {
		if (currentHomeworkIndex < reviewHomeworks.length - 1) {
			currentHomeworkIndex += 1;
			editingQuestionIndex = null;
		}
	}

	function selectHomeworkByIndex(index: number) {
		currentHomeworkIndex = index;
		editingQuestionIndex = null;
	}

	function handleHomeworkChange(event: Event) {
		const homeworkId = (event.currentTarget as HTMLSelectElement).value;
		const index = getSelectedHomeworkIndex(homeworkId);
		if (index >= 0) {
			currentHomeworkIndex = index;
			editingQuestionIndex = null;
		}
	}

	function selectHomeworkByHomeworkId(homeworkId: string) {
		const index = getSelectedHomeworkIndex(homeworkId);
		if (index >= 0) {
			currentHomeworkIndex = index;
			editingQuestionIndex = null;
		}
	}

	function buildMasteryModelId(sourceModelId: string) {
		return `mastery-${sourceModelId}`;
	}

	function buildMasteryModelName(sourceModelName: string) {
		return sourceModelName.startsWith('Mastery ') ? sourceModelName : `Mastery ${sourceModelName}`;
	}

	function getKnowledgeReferenceId(reference: any) {
		return reference?.id ?? reference?.collection_name ?? null;
	}

	function buildPracticeKnowledgeMarkdown(homeworkLabel: string, practiceItems: any[]) {
		const lines = [`# ${homeworkLabel} Mastery Practice Set`, ''];
		for (const [index, item] of practiceItems.entries()) {
			const number = item?.number ?? index + 1;
			const text = item?.text ?? item?.question ?? item?.prompt ?? 'Practice question';
			const topics = Array.isArray(item?.topics)
				? item.topics.filter(Boolean).join(', ')
				: item?.topic ?? '';
			const answer = item?.answer ?? item?.expected_answer ?? '';
			lines.push(`## Question ${number}`);
			if (topics) lines.push(`Topics: ${topics}`);
			lines.push('');
			lines.push(String(text));
			lines.push('');
			if (answer) {
				lines.push('Answer:');
				lines.push(String(answer));
				lines.push('');
			}
		}
		return lines.join('\n');
	}

	function buildPracticeKnowledgeMarkdownFromText(homeworkLabel: string, practiceMarkdown: string) {
		const trimmed = (practiceMarkdown ?? '').trim();
		if (!trimmed) {
			return `# ${homeworkLabel} Mastery Practice Set\n\nPractice content is currently unavailable.`;
		}
		return `# ${homeworkLabel} Mastery Practice Set\n\n${trimmed}`;
	}

	async function syncMasteryWorkspaceModel(homeworkId: string) {
		const homeworkRow = homeworkRows.find((row) => row.id === homeworkId);
		const sourceModelId = homeworkRow?.modelId;
		if (!sourceModelId) return;

		const sourceModel = await getModelById(localStorage.token, sourceModelId);
		const practiceResponse = await fetch(
			`${AI_TUTOR_API_BASE}/practice?homework_id=${encodeURIComponent(homeworkId)}`,
			{
				method: 'GET',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			}
		);
		if (!practiceResponse.ok) {
			throw new Error('Failed to load generated practice content for Mastery model sync.');
		}

		const practiceData = await practiceResponse.json();
		const latestPractice =
			Array.isArray(practiceData) && practiceData.length > 0
				? [...practiceData].sort(
						(a, b) => Number(b?.version_number ?? 0) - Number(a?.version_number ?? 0)
					)[0]
				: null;

		const practiceItems = Array.isArray(latestPractice?.problem_items)
			? latestPractice.problem_items
			: [];
		const practiceMarkdown =
			typeof latestPractice?.problem_data === 'string' ? latestPractice.problem_data : '';
		if (practiceItems.length === 0 && !practiceMarkdown.trim()) {
			throw new Error('Generated practice content is missing question data.');
		}

		const masteryModelId = buildMasteryModelId(sourceModel.id);
		const masteryModelName = buildMasteryModelName(sourceModel.name ?? getHomeworkModelName(homeworkId));
		const knowledgeName = `${masteryModelName} Practice KB`;
		let existingMasteryModel = null;

		try {
			existingMasteryModel = await getModelById(localStorage.token, masteryModelId);
		} catch {
			existingMasteryModel = null;
		}

		// Always overwrite the existing Mastery model in place so the practice-chat
		// experience stays tied to a single predictable workspace model per homework.
		let knowledgeId = getKnowledgeReferenceId(existingMasteryModel?.meta?.knowledge?.[0]);
		if (knowledgeId) {
			await fetch(`/api/v1/knowledge/${encodeURIComponent(knowledgeId)}/reset`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			await updateKnowledgeById(localStorage.token, knowledgeId, {
				name: knowledgeName,
				description: `Generated mastery practice knowledge for ${getHomeworkModelName(homeworkId)}.`,
				access_control: sourceModel.access_control ?? null
			});
		} else {
			const createdKnowledge = await createNewKnowledge(
				localStorage.token,
				knowledgeName,
				`Generated mastery practice knowledge for ${getHomeworkModelName(homeworkId)}.`,
				sourceModel.access_control ?? null
			);
			knowledgeId = createdKnowledge?.id ?? null;
		}

		if (!knowledgeId) {
			throw new Error('Failed to create or load the Mastery knowledge base.');
		}

		const practiceFile = new File(
			[
				practiceItems.length > 0
					? buildPracticeKnowledgeMarkdown(getHomeworkModelName(homeworkId), practiceItems)
					: buildPracticeKnowledgeMarkdownFromText(getHomeworkModelName(homeworkId), practiceMarkdown)
			],
			`${masteryModelId}-practice.md`,
			{ type: 'text/markdown' }
		);
		await addFileToKnowledgeById(localStorage.token, knowledgeId, practiceFile);

		const nextModelPayload = {
			id: masteryModelId,
			base_model_id: sourceModel.base_model_id ?? null,
			name: masteryModelName,
			meta: {
				...sourceModel.meta,
				knowledge: [{ id: knowledgeId, name: knowledgeName }]
			},
			params: sourceModel.params,
			access_control: sourceModel.access_control ?? null,
			is_active: sourceModel.is_active ?? true
		};

		if (existingMasteryModel) {
			await updateModelById(localStorage.token, masteryModelId, nextModelPayload);
		} else {
			await createNewModel(localStorage.token, nextModelPayload);
		}
	}

	$: currentReviewHomework = reviewHomeworks[currentHomeworkIndex];
	$: selectedHomework = currentReviewHomework?.homeworkId ?? '';
	$: questionData = currentReviewHomework?.questionData ?? {
		id: '',
		status: 'pending',
		generatedTime: '2026-03-23 09:00:00',
		questions: []
	};
	$: approvedQuestionIndexes = currentReviewHomework?.approvedQuestionIndexes ?? new Set<number>();
	$: questionEditors = currentReviewHomework?.questionEditors ?? [];
	$: studentAssignments = currentReviewHomework?.studentAssignments ?? [];

	$: practiceQuestionsEmptyMessage = !groupId
		? 'Loading group selection...'
		: homeworkRows.length === 0
			? 'No homework uploaded for this group yet.'
			: 'No practice question sets are available yet. Generate practice after analysis is completed.';

	async function loadHomeworkPipelineData(currentGroupId: string) {
		if (!currentGroupId) return;
		const response = await fetch(
			`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(currentGroupId)}`,
			{
				method: 'GET',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			}
		);
		if (!response.ok) {
			throw new Error('Homework fetch failed');
		}
		const data = await response.json();
		homeworkRows = Array.isArray(data)
			? data.map((hw: any) => ({
					id: hw.id,
					modelId: hw.model_id ?? null,
					questionUploaded: hw.question_uploaded ?? false,
					answerUploaded: hw.answer_uploaded ?? false,
					topicMapped: hw.topic_mapped ?? false
				}))
			: [];
		homeworkOptions = homeworkRows.map((row) => row.id);
		homeworkLabelsById = Object.fromEntries(
			(Array.isArray(data) ? data : []).map((hw: any) => [hw.id, hw.model_id ?? hw.id])
		);
		const nextHomeworkIdsWithAnalysis = new Set<string>();
		await Promise.all(
			homeworkRows.map(async (row) => {
				const analysisResponse = await fetch(
					`${AI_TUTOR_API_BASE}/analysis/?homework_id=${encodeURIComponent(row.id)}`,
					{
						method: 'GET',
						headers: { Authorization: `Bearer ${localStorage.token}` }
					}
				);
				if (!analysisResponse.ok) return;
				const analysisData = await analysisResponse.json();
				if (Array.isArray(analysisData) && analysisData.length > 0) {
					nextHomeworkIdsWithAnalysis.add(row.id);
				}
			})
		);
		homeworkIdsWithAnalysis = nextHomeworkIdsWithAnalysis;
		console.log('AI Tutor Dashboard - Practice Question homework pipeline loaded', {
			groupId: currentGroupId,
			homeworks: homeworkRows.map((row) => ({
				id: row.id,
				name: homeworkLabelsById[row.id] ?? row.id,
				modelId: row.modelId ?? '',
				questionUploaded: row.questionUploaded,
				answerUploaded: row.answerUploaded,
				topicMapped: row.topicMapped
			})),
			homeworkIdsWithAnalysis: Array.from(homeworkIdsWithAnalysis)
		});
	}

	async function loadPracticeQuestionData() {
		if (!groupId) return;
		practiceLoading = true;
		try {
			const applyPracticeSnapshot = (snapshot: {
				practiceQuestions: any[];
				assignmentSentAtByPracticeId: Record<string, string>;
			}) => {
				practiceQuestions = snapshot.practiceQuestions;
				assignmentSentAtByPracticeId = snapshot.assignmentSentAtByPracticeId;
			};
			const snapshot = await loadWithAITutorSessionCache({
				key: `practice-question:${groupId}:practice`,
				ttlMs: PRACTICE_QUESTION_SESSION_TTL_MS,
				onCached: applyPracticeSnapshot,
				loader: async () => {
					const practiceResponse = await fetch(
						`${AI_TUTOR_API_BASE}/practice?group_id=${encodeURIComponent(groupId)}`,
						{
							method: 'GET',
							headers: { Authorization: `Bearer ${localStorage.token}` }
						}
					);
					if (!practiceResponse.ok) {
						throw new Error('Practice question set fetch failed');
					}
					const practiceData = await practiceResponse.json();
					const latestByHomework = new Map<string, any>();
					for (const row of Array.isArray(practiceData) ? practiceData : []) {
						const homeworkId = row?.homework_id ?? 'unknown';
						const prev = latestByHomework.get(homeworkId);
						const prevVersion = Number(prev?.version_number ?? -1);
						const currVersion = Number(row?.version_number ?? -1);
						if (!prev || currVersion >= prevVersion) {
							latestByHomework.set(homeworkId, row);
						}
					}
					const latestPracticeIds = Array.from(latestByHomework.values())
						.map((row) => row?.id)
						.filter(Boolean);
					const nextAssignmentSentAtByPracticeId: Record<string, string> = {};

					await Promise.all(
						latestPracticeIds.map(async (practiceId) => {
							try {
								const assignmentResponse = await fetch(
									`${AI_TUTOR_API_BASE}/assignment?practice_problem_id=${encodeURIComponent(practiceId)}`,
									{
										method: 'GET',
										headers: { Authorization: `Bearer ${localStorage.token}` }
									}
								);
								if (!assignmentResponse.ok) return;
								const assignments = await assignmentResponse.json();
								if (Array.isArray(assignments) && assignments.length > 0) {
									const latestAssignment = [...assignments].sort((a, b) =>
										String(b?.created_at ?? '').localeCompare(String(a?.created_at ?? ''))
									)[0];
									if (latestAssignment?.created_at) {
										nextAssignmentSentAtByPracticeId[practiceId] = latestAssignment.created_at;
									}
								}
							} catch (error) {
								console.error('Assignment status fetch failed:', error);
							}
						})
					);

					const nextPracticeQuestions = homeworkOptions.sort().map((homeworkId) => {
						const latest = latestByHomework.get(homeworkId);
						const homeworkLabel = getHomeworkModelName(homeworkId);
						if (!latest) {
							return { practiceId: null, homework: homeworkLabel, homeworkId, status: 'not_ready' };
						}
						if (latest.status === 'approved') {
							return {
								practiceId: latest.id ?? null,
								homework: homeworkLabel,
								homeworkId,
								status: 'approved',
								date: latest.created_at,
								sentAt: latest.id ? nextAssignmentSentAtByPracticeId[latest.id] ?? null : null
							};
						}
						if (latest.status === 'generating') {
							return { practiceId: latest.id ?? null, homework: homeworkLabel, homeworkId, status: 'generating' };
						}
						if (latest.status === 'pending' || latest.status === 'rejected') {
							return { practiceId: latest.id ?? null, homework: homeworkLabel, homeworkId, status: 'ready' };
						}
						return { practiceId: latest.id ?? null, homework: homeworkLabel, homeworkId, status: 'not_ready' };
					});

					return {
						practiceQuestions: nextPracticeQuestions,
						assignmentSentAtByPracticeId: nextAssignmentSentAtByPracticeId
					};
				}
			});
			applyPracticeSnapshot(snapshot);
			console.log('AI Tutor Dashboard - Practice Question set loaded', {
				groupId,
				practiceQuestions: practiceQuestions.map((practice) => ({
					homeworkId: practice.homeworkId ?? '',
					homeworkName: practice.homework ?? '',
					practiceId: practice.practiceId ?? '',
					status: practice.status ?? ''
				}))
			});
		} catch (error) {
			console.error('Practice question set API failed:', error);
		} finally {
			practiceLoading = false;
		}
	}

	function canGeneratePractice(homeworkId: string) {
		const homeworkRow = homeworkRows.find((row) => row.id === homeworkId);
		return Boolean(
			homeworkRow?.questionUploaded &&
			homeworkRow?.topicMapped &&
			homeworkIdsWithAnalysis.has(homeworkId)
		);
	}

	function getPracticeActionHint(practice: any) {
		if (practice.status === 'not_ready') {
			const homeworkRow = homeworkRows.find((row) => row.id === practice.homeworkId);
			if (!homeworkRow?.questionUploaded) return 'Upload homework PDF';
			if (!homeworkRow?.topicMapped) return 'Wait for topic mapping';
			if (!canGeneratePractice(practice.homeworkId)) return 'Run analysis first';
			return '';
		}
		if (practice.status === 'generating') return 'Generating...';
		return '';
	}

	async function pollPipelineJob(jobId: string, intervalMs = 4000, onUpdate?: (data: any) => void) {
		while (true) {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/pipeline/status/${encodeURIComponent(jobId)}`,
				{
					headers: { Authorization: `Bearer ${localStorage.token}` }
				}
			);
			if (!response.ok) {
				throw new Error(`Pipeline status check failed: ${response.status}`);
			}
			const data = await response.json();
			onUpdate?.(data);
			if (data?.status === 'done') return data;
			if (data?.status === 'failed') {
				throw new Error(data?.error || 'Practice generation failed.');
			}
			await new Promise((resolve) => setTimeout(resolve, intervalMs));
		}
	}

	async function generatePractice(homeworkId: string) {
		if (!canGeneratePractice(homeworkId)) {
			toast.error('Practice generation requires completed analysis data for this homework.');
			return;
		}
		generatingPracticeByHomeworkId = {
			...generatingPracticeByHomeworkId,
			[homeworkId]: true
		};
		failedPracticeGenerationByHomeworkId = Object.fromEntries(
			Object.entries(failedPracticeGenerationByHomeworkId).filter(([id]) => id !== homeworkId)
		);
		testToast(`Generate practice is triggered | page=aitutordashboard - Practice Question | homework=${homeworkId}`);
		try {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/practice/generate?homework_id=${encodeURIComponent(homeworkId)}`,
				{
					method: 'POST',
					headers: { Authorization: `Bearer ${localStorage.token}` }
				}
			);
			if (!response.ok) {
				const detail = await response.text();
				throw new Error(detail || 'Practice generation request failed.');
			}
			const data = await response.json();
			const jobId = data?.job_id;
			if (!jobId) throw new Error('Practice generation started but no job ID was returned.');
			const startedAt = new Date().toISOString();
			generatingPracticeJobsByHomeworkId = {
				...generatingPracticeJobsByHomeworkId,
				[homeworkId]: { jobId, step: 'queued', status: 'queued', startedAt }
			};
			persistPracticeJobState(homeworkId, { jobId, step: 'queued', status: 'queued', startedAt });
			toast.success('Practice generation started.');
			await pollPipelineJob(jobId, 4000, (jobData) => {
				const nextJobState = {
					jobId,
					step: jobData?.step ?? 'unknown',
					status: jobData?.status ?? 'running',
					startedAt
				};
				generatingPracticeJobsByHomeworkId = {
					...generatingPracticeJobsByHomeworkId,
					[homeworkId]: nextJobState
				};
				persistPracticeJobState(homeworkId, nextJobState);
			});
			clearAITutorSessionCacheByPrefix(`practice-question:${groupId}:practice`);
			await loadPracticeQuestionData();
			await refreshReviewHomework(homeworkId);
			await syncMasteryWorkspaceModel(homeworkId);
			clearPracticeJobState(homeworkId);
			generatingPracticeJobsByHomeworkId = Object.fromEntries(
				Object.entries(generatingPracticeJobsByHomeworkId).filter(([id]) => id !== homeworkId)
			);
			toast.success('Practice question set generated.');
		} catch (error) {
			failedPracticeGenerationByHomeworkId = {
				...failedPracticeGenerationByHomeworkId,
				[homeworkId]: {
					message: error instanceof Error ? error.message : 'Practice generation failed.',
					failedAt: new Date().toISOString()
				}
			};
			toast.error(error instanceof Error ? error.message : 'Practice generation failed.');
			console.error('Practice generation failed:', error);
		} finally {
			clearPracticeJobState(homeworkId);
			generatingPracticeJobsByHomeworkId = Object.fromEntries(
				Object.entries(generatingPracticeJobsByHomeworkId).filter(([id]) => id !== homeworkId)
			);
			generatingPracticeByHomeworkId = {
				...generatingPracticeByHomeworkId,
				[homeworkId]: false
			};
		}
	}

	async function sendPracticeToStudents(practice: any) {
		if (!practice?.practiceId) {
			toast.error('This practice set is missing a practice ID.');
			return;
		}
		sendingPracticeById = {
			...sendingPracticeById,
			[practice.practiceId]: true
		};
		testToast(
			`Send is triggered | page=aitutordashboard - Practice Question | practice=${practice.practiceId} | homework=${practice.homeworkId}`
		);
		try {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/assignment/assign?practice_id=${encodeURIComponent(practice.practiceId)}`,
				{
					method: 'POST',
					headers: { Authorization: `Bearer ${localStorage.token}` }
				}
			);
			if (!response.ok) {
				const detail = await response.text();
				throw new Error(detail || 'Failed to send practice to students.');
			}
			clearAITutorSessionCacheByPrefix(`practice-question:${groupId}:practice`);
			await loadPracticeQuestionData();
			toast.success('Practice question set sent to students.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Failed to send practice to students.');
			console.error('Practice assignment failed:', error);
		} finally {
			sendingPracticeById = {
				...sendingPracticeById,
				[practice.practiceId]: false
			};
		}
	}

	onMount(async () => {
		testToast(`loading aitutordashboard - Practice Question | group=${groupId || 'pending'}`);
		console.log('AI Tutor Dashboard - Practice Question mount', {
			pathname: $page.url.pathname,
			groupId,
			groupIdFromUrl: $page.url.searchParams.get('group_id') || '',
			homeworkIdFromUrl: $page.url.searchParams.get('homework_id') || ''
		});
		restorePersistedPracticeJobs();

		if (useFrontendTestingData) return;
		await loadHomeworkPipelineData(groupId);
		await loadPracticeQuestionData();

		const requestedHomeworkId =
			$page.url.searchParams.get('homework_id') ?? homeworkOptions[0] ?? '';
		const loadedReviewHomeworks = (
			await Promise.all(homeworkOptions.map((homeworkId) => loadReviewHomework(homeworkId)))
		).filter(
			(homework): homework is ReviewHomework =>
				!!homework &&
				(homework.questionData.status === 'pending' ||
					homework.questionData.status === 'in_progress' ||
					homework.questionData.status === 'approved')
		);

		reviewHomeworks = loadedReviewHomeworks;

		const requestedIndex = reviewHomeworks.findIndex(
			(homework) => homework.homeworkId === requestedHomeworkId
		);
		currentHomeworkIndex = requestedIndex >= 0 ? requestedIndex : 0;
		console.log('AI Tutor Dashboard - Practice Question review loaded', {
			groupId,
			requestedHomeworkId,
			currentHomeworkIndex,
			reviewHomeworks: reviewHomeworks.map((homework) => ({
				homeworkId: homework.homeworkId,
				homeworkName: homeworkLabelsById[homework.homeworkId] ?? homework.homeworkId,
				practiceId: homework.practiceId ?? '',
				status: homework.questionData.status,
				questionCount: homework.questionData.questions.length
			}))
		});
	});

	$: if (!useFrontendTestingData && groupId) {
		restorePersistedPracticeJobs();
	}

	$: if (!useFrontendTestingData && groupId) {
		for (const [homeworkId, job] of Object.entries(generatingPracticeJobsByHomeworkId)) {
			if (!job?.jobId || !generatingPracticeByHomeworkId[homeworkId]) continue;
			if (resumedPracticeJobIds.has(job.jobId)) continue;
			resumedPracticeJobIds = new Set([...resumedPracticeJobIds, job.jobId]);
			void (async () => {
				try {
					await pollPipelineJob(job.jobId, 4000, (jobData) => {
						const nextJobState = {
							jobId: job.jobId,
							step: jobData?.step ?? 'unknown',
							status: jobData?.status ?? 'running',
							startedAt: job.startedAt
						};
						generatingPracticeJobsByHomeworkId = {
							...generatingPracticeJobsByHomeworkId,
							[homeworkId]: nextJobState
						};
						persistPracticeJobState(homeworkId, nextJobState);
					});
					clearAITutorSessionCacheByPrefix(`practice-question:${groupId}:practice`);
					await loadPracticeQuestionData();
					await refreshReviewHomework(homeworkId);
					await syncMasteryWorkspaceModel(homeworkId);
					clearPracticeJobState(homeworkId);
					resumedPracticeJobIds.delete(job.jobId);
					generatingPracticeJobsByHomeworkId = Object.fromEntries(
						Object.entries(generatingPracticeJobsByHomeworkId).filter(([id]) => id !== homeworkId)
					);
					toast.success('Practice question set generation finished after refresh.');
				} catch (error) {
					clearPracticeJobState(homeworkId);
					resumedPracticeJobIds.delete(job.jobId);
					generatingPracticeJobsByHomeworkId = Object.fromEntries(
						Object.entries(generatingPracticeJobsByHomeworkId).filter(([id]) => id !== homeworkId)
					);
					toast.error(error instanceof Error ? error.message : 'Practice generation failed after refresh.');
				} finally {
					generatingPracticeByHomeworkId = {
						...generatingPracticeByHomeworkId,
						[homeworkId]: false
					};
				}
			})();
		}
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	<div class="space-y-3">
		<div class="flex items-center justify-between gap-4">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Practice Question Set</h2>
		</div>

		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			Start with an AI-generated question set based on students' weak topics, or upload your own questions. You can download, edit, and re-upload AI-generated content if needed. All uploaded question sets are automatically standardized by the system, with topics added and answers generated if missing, to ensure a consistent format across the platform.
		</p>

		<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
			<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
				<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						<th scope="col" class="w-[12rem] px-3 py-1.5">Homework</th>
						<th scope="col" class="px-3 py-1.5">Status</th>
						<th scope="col" class="px-3 py-1.5">Action</th>
					</tr>
				</thead>
				<tbody>
					{#if practiceLoading}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="3" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">Loading practice question sets...</td>
						</tr>
					{:else if practiceQuestions.length === 0}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="3" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">{practiceQuestionsEmptyMessage}</td>
						</tr>
					{:else}
						{#each practiceQuestions as practice}
							<tr class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs border-t border-gray-100 dark:border-gray-850">
								<td class="px-3 py-1.5 font-medium text-gray-900 dark:text-white">
									<div class="max-w-[12rem] overflow-hidden whitespace-normal break-words leading-4 [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]">{getHomeworkModelName(practice.homeworkId ?? practice.homework)}</div>
								</td>
								<td class="px-3 py-1.5">
									<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-gray-700 dark:text-gray-300">
										{#if practice.status === 'approved'}
											<div class="flex items-center gap-2 whitespace-nowrap">
												<span class="w-2 h-2 rounded-full bg-green-500 flex-shrink-0"></span>
												<span>Approved on {practice.date}</span>
											</div>
											{#if practice.sentAt}
												<div class="flex items-center gap-2 whitespace-nowrap">
													<span class="w-2 h-2 rounded-full bg-green-500 flex-shrink-0"></span>
													<span>Sent on {practice.sentAt}</span>
												</div>
											{/if}
										{:else if practice.status === 'ready'}
											<span class="w-2 h-2 rounded-full bg-yellow-500 flex-shrink-0"></span>
											<span>Ready for review</span>
										{:else if practice.status === 'generating' || generatingPracticeByHomeworkId[practice.homeworkId]}
											<div class="flex flex-col gap-1">
												<div class="flex items-center gap-2 whitespace-nowrap">
													<span class="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0"></span>
													<span>Generating</span>
												</div>
												{#if generatingPracticeJobsByHomeworkId[practice.homeworkId]?.step}
													<div class="text-xs text-gray-500 dark:text-gray-400">
														Step: {generatingPracticeJobsByHomeworkId[practice.homeworkId].step}
													</div>
												{/if}
											</div>
										{:else if failedPracticeGenerationByHomeworkId[practice.homeworkId]}
											<div class="flex flex-col gap-1">
												<div class="flex items-center gap-2 whitespace-nowrap">
													<span class="w-2 h-2 rounded-full bg-red-500 flex-shrink-0"></span>
													<span>Last re-generate failed</span>
												</div>
												<div class="max-w-[28rem] whitespace-normal break-words text-xs text-gray-500 dark:text-gray-400">
													{failedPracticeGenerationByHomeworkId[practice.homeworkId].message}
												</div>
											</div>
										{:else}
											<span class="w-2 h-2 rounded-full bg-gray-400 flex-shrink-0"></span>
											<span>Not ready</span>
										{/if}
									</div>
								</td>
								<td class="px-3 py-1.5">
									<div class="flex items-center gap-1">
										{#if practice.status === 'approved' || practice.status === 'ready'}
											{#if practice.status === 'approved'}
												<button
													type="button"
													class="self-center flex w-fit items-center gap-1 whitespace-nowrap rounded-xl px-2 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:text-gray-300 dark:hover:bg-white/5"
													on:click={() => sendPracticeToStudents(practice)}
													disabled={!practice.practiceId || sendingPracticeById[practice.practiceId]}
												>
													{sendingPracticeById[practice.practiceId] ? 'Sending…' : 'Send'}
												</button>
											{/if}
											{#if canGeneratePractice(practice.homeworkId)}
												<button
													type="button"
													class="self-center w-fit whitespace-nowrap rounded-xl px-2 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
													on:click={() => generatePractice(practice.homeworkId)}
													disabled={generatingPracticeByHomeworkId[practice.homeworkId]}
												>
													{generatingPracticeByHomeworkId[practice.homeworkId] ? 'Generating…' : 'Re-generate'}
												</button>
											{/if}
										{:else if practice.status === 'not_ready' && canGeneratePractice(practice.homeworkId)}
											<button
												type="button"
												class="self-center w-fit whitespace-nowrap rounded-xl px-2 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
												on:click={() => generatePractice(practice.homeworkId)}
												disabled={generatingPracticeByHomeworkId[practice.homeworkId]}
											>
												{generatingPracticeByHomeworkId[practice.homeworkId] ? 'Generating…' : 'Generate'}
											</button>
										{:else}
											<div class="self-center text-xs font-normal text-gray-300 dark:text-gray-600">
												{getPracticeActionHint(practice)}
											</div>
										{/if}
									</div>
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
	</div>

	<div class="space-y-3">
		<button
			type="button"
			class="flex w-full items-center justify-between py-2 text-left transition"
			on:click={() => (expandedGuide = !expandedGuide)}
			aria-expanded={expandedGuide}
		>
			<span class="text-xl font-semibold text-gray-800 dark:text-gray-200">Guide</span>
				<span class="pt-1 text-gray-500 dark:text-gray-400">
					{#if expandedGuide}
						<ChevronUp className="size-4" />
					{:else}
						<ChevronDown className="size-4" />
					{/if}
				</span>
		</button>

		{#if expandedGuide}
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

			<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-950">
				<div class="markdown-prose-xs text-xs text-gray-800 dark:text-gray-200">
					<Markdown id="guide-question-preview" content={STANDARD_QUESTION_TEMPLATE.text} />
				</div>
			</div>

			<h4 class="text-base font-semibold text-gray-800 dark:text-gray-200">What Each Item Means</h4>

			<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
				{@html JSON_EXPLANATION_PARAGRAPH}
			</p>
		{/if}
	</div>

	<div class="space-y-0">
		<div class="bg-white py-2 dark:bg-gray-900">
			<div class="flex items-end justify-between gap-4">
				<div class="w-full">
					<div class="flex items-center justify-between gap-3">
						<h2 class="text-xl font-semibold text-gray-900 dark:text-gray-100">Questions</h2>
						<div class="flex items-center justify-between gap-3 text-sm min-w-[26rem]">
							<div class="relative min-w-0 flex-1">
								<select
									bind:value={selectedHomework}
									on:change={handleHomeworkChange}
									class="block w-full truncate appearance-none bg-transparent pr-5 text-sm text-gray-700 outline-hidden dark:text-gray-300"
									title={getHomeworkLabel(selectedHomework)}
									aria-label="Select homework practice question set"
								>
									{#each reviewHomeworks as homework}
										<option value={homework.homeworkId}>{getHomeworkLabel(homework.homeworkId)}</option>
									{/each}
								</select>
							</div>
							<div class="ml-auto flex shrink-0 items-center gap-2">
							<button
								type="button"
								on:click={goToPreviousHomework}
								disabled={currentHomeworkIndex === 0}
								class="text-sm font-medium text-gray-900 transition hover:text-gray-700 disabled:text-gray-400 dark:text-gray-100 dark:hover:text-gray-300 dark:disabled:text-gray-500"
							>
								Prev
							</button>
							<button
								type="button"
								on:click={goToNextHomework}
								disabled={currentHomeworkIndex >= reviewHomeworks.length - 1}
								class="text-sm font-medium text-gray-900 transition hover:text-gray-700 disabled:text-gray-400 dark:text-gray-100 dark:hover:text-gray-300 dark:disabled:text-gray-500"
							>
								Next
							</button>
							</div>
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
						<div class="flex items-center gap-3 text-sm">
							{#if editingQuestionIndex === index}
								<button
									type="button"
									on:click={() => cancelQuestionEdit(index)}
									class="text-gray-600 transition hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
								>
									Cancel
								</button>
								<button
									type="button"
									on:click={() => useOriginalQuestion(index)}
									class="text-gray-600 transition hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
								>
									Reset
								</button>
								<button
									type="button"
									on:click={() => saveQuestionEdit(index)}
									class="font-medium text-gray-900 transition hover:text-gray-700 dark:text-gray-100 dark:hover:text-gray-300"
								>
									Save
								</button>
							{:else}
								<button
									type="button"
									on:click={() => (editingQuestionIndex = index)}
									class="text-xs font-medium text-gray-900 transition hover:text-gray-700 dark:text-gray-100 dark:hover:text-gray-300"
								>
									Edit
								</button>
							{/if}
						</div>
					</div>
					{#if editingQuestionIndex === index}
						<div class="rounded-lg bg-white dark:bg-white">
							<textarea
								value={questionEditors[index]}
								on:input={(event) => handleQuestionEditorInput(index, event)}
								rows={getEditorRows(editor)}
								class="w-full rounded-lg border border-transparent bg-white px-4 py-1 font-mono text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 dark:bg-white dark:text-gray-900"
							/>
						</div>
					{:else}
						<div class="rounded-lg bg-gray-50 dark:bg-gray-900">
							<div
								class="w-full select-none whitespace-pre-wrap rounded-lg border border-transparent bg-gray-50 px-4 py-1 font-mono text-xs leading-relaxed text-gray-800 dark:bg-gray-900 dark:text-gray-200"
							>
								{questionEditors[index]}
							</div>
						</div>
					{/if}
					<div class="mt-3 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-950">
						{#if getQuestionPreviewText(questionEditors[index])}
							<div class="markdown-prose-xs text-xs text-gray-800 dark:text-gray-200">
								<Markdown
									id={`question-preview-${currentReviewHomework?.homeworkId ?? 'homework'}-${index}`}
									content={getQuestionPreviewText(questionEditors[index])}
								/>
							</div>
						{:else}
							<div class="text-xs text-gray-500 dark:text-gray-400">
								Preview unavailable until the JSON contains a valid <span class="font-semibold">text</span> string.
							</div>
						{/if}
					</div>
				</div>
			{/each}

			<div class="flex items-center justify-end gap-3 pt-4 pr-4">
				<button
					on:click={handleSave}
					disabled={questionData.status === 'approved' || approvingQuestionSet}
					class={`rounded-full px-4 py-2 text-sm font-medium text-white transition ${
						questionData.status === 'approved'
							? 'cursor-default bg-green-600'
							: approvingQuestionSet
								? 'cursor-wait bg-gray-600'
								: 'bg-black hover:bg-gray-800'
					}`}
				>
					{questionData.status === 'approved'
						? 'Approved'
						: approvingQuestionSet
							? 'Approving...'
							: 'Approve'}
				</button>
			</div>
		</div>
	</div>
</div>
