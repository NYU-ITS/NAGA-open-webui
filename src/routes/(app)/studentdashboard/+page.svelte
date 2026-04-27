<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { Tooltip } from 'bits-ui';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { TEMP_HIDE, AI_TUTOR_FRONTEND_TESTING_MODE } from '$lib/constants';
	import { user } from '$lib/stores';
	import { aiTutorAllowedModelIds } from '$lib/stores/aiTutorWorkspaceModels';
	import { fetchAITutorJson } from '$lib/apis/aiTutor';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import { loadWithAITutorSessionCache } from '$lib/utils/aiTutorSessionCache';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';

	const testToast = showAITutorTestToast;
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;
	const STUDENT_DASHBOARD_SESSION_TTL_MS = 5 * 60 * 1000;

	type HomeworkSummaryRow = {
		homework: string;
		homeworkId?: string;
		modelId?: string;
		masteredTopics: string[];
		needMorePractice: string[];
		totalCount: number | null;
		solved: number | null;
		attempted: number | null;
		errors: number | null;
		notStarted: boolean;
	};

	type PracticeAssignmentRow = {
		id: string;
		index: number;
		homeworkId: string;
		modelId?: string;
		homeworkLabel: string;
		topic: string;
		status: string;
		assignmentId?: string;
		practiceProblemId?: string;
		assignedItems?: any[];
	};

	type ConceptRow = {
		name: string;
		testedIn: string[];
		practicedDate: string | null;
		homeworkStatuses: Record<string, string>;
	};

	type TopicPerformance = {
		topic_name: string;
		status: string;
	};

	type StudentDashboardSnapshot = {
		homeworkData: HomeworkSummaryRow[];
		practiceAssignments: PracticeAssignmentRow[];
		conceptsData: ConceptRow[];
		followUpQuestions: { homework: string; status: string }[];
	};

	onMount(() => {
		testToast('loading studentdashboard - Summary');
		console.log('[studentdashboard]-[Summary]-[Loaded]');
	});

	// TODO(student-dashboard-backend): Replace this placeholder summary with student-level
	// analysis data from the AI Tutor backend. Expected shape:
	// - homework_id / homework title
	// - mastered topics
	// - needs-practice topics
	// - total / solved / attempted / error counts
	const placeholderHomeworkData: HomeworkSummaryRow[] = [
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

	let homeworkData: HomeworkSummaryRow[] = placeholderHomeworkData;

	const placeholderPracticeAssignments: PracticeAssignmentRow[] = [
		{
			id: 'practice-1',
			index: 1,
			homeworkId: 'Homework 1',
			homeworkLabel: 'Homework1-MATH-Code-Section-Semester',
			topic: 'Integration, Limit Definition',
			status: 'Ready'
		},
		{
			id: 'practice-2',
			index: 2,
			homeworkId: 'Homework 2',
			homeworkLabel: 'Homework2-MATH-Code-Section-Semester',
			topic: 'Factoring, Complex Numbers',
			status: 'Not Ready'
		},
		{
			id: 'practice-3',
			index: 3,
			homeworkId: 'Homework 3',
			homeworkLabel: 'Homework3-MATH-Code-Section-Semester',
			topic: 'Trigonometric Identities, Inverse Functions',
			status: 'Ready'
		}
	];
	let practiceAssignments: PracticeAssignmentRow[] = placeholderPracticeAssignments;

	function goToConcepts(topic: string) {
		selectedConcepts.add(topic);
		selectedConcepts = selectedConcepts;
	}

	let highlightedConcepts: Set<string> = new Set();
	let highlightTimeout: ReturnType<typeof setTimeout> | null = null;

	function getPracticeTopics(topicList: string) {
		return topicList
			.split(',')
			.map((topic) => topic.trim())
			.filter(Boolean);
	}

	function highlightConceptCards(topicList: string) {
		const topicsToHighlight = getPracticeTopics(topicList).filter((topic) =>
			conceptsData.some((concept) => concept.name === topic)
		);

		if (topicsToHighlight.length === 0) return;

		highlightedConcepts = new Set(topicsToHighlight);

		if (highlightTimeout) clearTimeout(highlightTimeout);
		highlightTimeout = setTimeout(() => {
			highlightedConcepts = new Set();
		}, 1800);
	}

	function buildMasteryModelId(sourceModelId: string) {
		return `mastery-${sourceModelId}`;
	}

	async function startPracticeAssignment(item: PracticeAssignmentRow) {
		testToast(`Start practice is triggered | page=studentdashboard - Summary | assignment=${item.id} | status=${item.status}`);
		if (item.status !== 'Ready') {
			toast.info('This practice set is not assigned to the current student yet.');
			return;
		}

		const assignmentPayload = {
			assignmentId: item.assignmentId ?? item.id,
			practiceProblemId: item.practiceProblemId ?? null,
			homeworkId: item.homeworkId,
			homeworkLabel: item.homeworkLabel,
			assignedItems: item.assignedItems ?? [],
			topic: item.topic,
			modelId: item.modelId ?? null,
			startedAt: new Date().toISOString()
		};
		if (typeof sessionStorage !== 'undefined') {
			sessionStorage.setItem('aiTutorActivePracticeAssignment', JSON.stringify(assignmentPayload));
		}
		if (typeof localStorage !== 'undefined') {
			localStorage.setItem('aiTutorPracticeAssignmentPending', JSON.stringify(assignmentPayload));
			console.log('[studentdashboard]-[StartPractice]-[Persisted]:', {
				assignmentId: assignmentPayload.assignmentId,
				session: true,
				localPending: true
			});
		}

		// Planned Mastery-model flow:
		// once a "Mastery*" workspace model exists for this homework, starting practice
		// should switch the student chat onto that cloned model so the practice session
		// keeps the original homework model behavior while using the generated practice KB.
		if (typeof sessionStorage !== 'undefined' && item.modelId) {
			sessionStorage.selectedModels = JSON.stringify([buildMasteryModelId(item.modelId)]);
		}

		console.log('[studentdashboard]-[Summary]-[PracticeAssignmentNavigate]:', {
			assignmentId: item.id,
			topic: item.topic
		});
		await goto(
			`/?practicing=1&assignment_id=${encodeURIComponent(item.assignmentId ?? item.id)}&practice_problem_id=${encodeURIComponent(item.practiceProblemId ?? '')}`
		);
	}

	async function updateDashboardFilters(
		nextHomework = selectedHomework,
		nextTopic = topicQueryRaw
	) {
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
	$: filteredHomeworkData = (() => {
		// Re-apply workspace model filtering in case it wasn't ready during loader
		const allowedIds = $aiTutorAllowedModelIds;
		const modelFiltered =
			allowedIds.size > 0
				? homeworkData.filter((hw) => !hw.modelId || allowedIds.has(hw.modelId))
				: homeworkData;

		return modelFiltered.filter((hw) => {
			const matchesHomework = selectedHomework === 'All' || hw.homework === selectedHomework;
			const matchesTopic =
				topicQuery === '' ||
				[...hw.masteredTopics, ...hw.needMorePractice].some((topic) =>
					topic.toLowerCase().includes(topicQuery)
				);
			return matchesHomework && matchesTopic;
		});
	})();

	$: availableHomeworkCount = filteredHomeworkData.filter((hw) => !hw.notStarted).length;

	let selectedConcepts: Set<string> = new Set();
	let hoveredLegendStatus: string | null = null;
	let selectedGroupId = '';
	let lastLoadedGroupId = '';
	let studentDashboardRequestId = 0;
	let hasLoadedStudentDashboardOnce = useFrontendTestingData;
	let isDashboardLoading = false;
	let dashboardLoadError: string | null = null;
	let followUpQuestions = [
		{ homework: 'Homework 1', status: 'Not Ready' },
		{ homework: 'Homework 2', status: 'Not Ready' },
		{ homework: 'Homework 3', status: 'Ready' },
		{ homework: 'Homework 4', status: 'Not Ready' },
		{ homework: 'Homework 5', status: 'Not Ready' },
		{ homework: 'Homework 6', status: 'Ready' },
		{ homework: 'Homework 7', status: 'Not Ready' },
		{ homework: 'Homework 8', status: 'Not Ready' }
	];
	const placeholderConceptsData: ConceptRow[] = [
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
			homeworkStatuses: { 'Homework 1': 'Mastered', 'Homework 2': 'Practiced' }
		},
		{
			name: 'Polynomials',
			testedIn: ['Homework 2', 'Homework 3'],
			practicedDate: 'Jan 21',
			homeworkStatuses: { 'Homework 2': 'Mastered', 'Homework 3': 'Mastered' }
		},
		{
			name: 'Factoring',
			testedIn: ['Homework 2', 'Homework 4'],
			practicedDate: null,
			homeworkStatuses: { 'Homework 2': 'Unmastered', 'Homework 4': 'Unmastered' }
		},
		{
			name: 'Complex Numbers',
			testedIn: ['Homework 3', 'Homework 5'],
			practicedDate: null,
			homeworkStatuses: { 'Homework 3': 'Unmastered', 'Homework 5': 'Unmastered' }
		},
		{
			name: 'Trigonometry',
			testedIn: ['Homework 3', 'Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: { 'Homework 3': 'Practiced', 'Homework 4': 'Mastered' }
		},
		{
			name: 'Unit Circle',
			testedIn: ['Homework 4'],
			practicedDate: 'Jan 21',
			homeworkStatuses: { 'Homework 4': 'Mastered' }
		},
		{
			name: 'Trigonometric Identities',
			testedIn: ['Homework 4', 'Homework 5'],
			practicedDate: 'Jan 21',
			homeworkStatuses: { 'Homework 4': 'Practiced', 'Homework 5': 'Mastered' }
		},
		{
			name: 'Inverse Functions',
			testedIn: ['Homework 5'],
			practicedDate: null,
			homeworkStatuses: { 'Homework 5': 'Unmastered' }
		}
	];
	let conceptsData: ConceptRow[] = placeholderConceptsData;

	$: selectedGroupId =
		$page.url.searchParams.get('group_id') ||
		(typeof localStorage !== 'undefined'
			? localStorage.getItem('student_dashboard_last_selected_group_id') || ''
			: '');
	$: filteredConcepts =
		selectedHomework === 'All'
			? conceptsData
			: conceptsData.filter((c) => c.testedIn.includes(selectedHomework));
	let currentPage = 1;
	const itemsPerPage = 9;
	$: totalPages = Math.ceil(filteredConcepts.length / itemsPerPage);
	$: paginatedConcepts = filteredConcepts.slice(
		(currentPage - 1) * itemsPerPage,
		currentPage * itemsPerPage
	);

	function selectConcept(conceptName: string) {
		if (TEMP_HIDE) return;
		if (selectedConcepts.has(conceptName)) selectedConcepts.delete(conceptName);
		else selectedConcepts.add(conceptName);
		selectedConcepts = selectedConcepts;
	}

	function selectAllUnfinished() {
		selectedConcepts.clear();
		filteredConcepts.forEach((concept) => {
			if (
				Object.values(concept.homeworkStatuses).some(
					(status) => normalizeHomeworkStatus(status) === 'Practice Available'
				)
			)
				selectedConcepts.add(concept.name);
		});
		selectedConcepts = selectedConcepts;
	}

	function selectAll() {
		filteredConcepts.forEach((concept) => selectedConcepts.add(concept.name));
		selectedConcepts = selectedConcepts;
	}

	function unselectAll() {
		selectedConcepts.clear();
		selectedConcepts = selectedConcepts;
	}

	function handleGenerate() {
		sessionStorage.setItem(
			'generatedQuestions',
			JSON.stringify({
				concepts: Array.from(selectedConcepts),
				timestamp: new Date().toISOString()
			})
		);
		window.location.href = '/';
	}

	function goToPage(page: number) {
		currentPage = page;
	}

	function previousPage() {
		if (currentPage > 1) currentPage--;
	}

	function nextPage() {
		if (currentPage < totalPages) currentPage++;
	}

	const statusOrder = ['Mastered', 'Practice Available'];

	function normalizeHomeworkStatus(status: string) {
		return status === 'Mastered' ? 'Mastered' : 'Practice Available';
	}

	function getStatusClasses(status: string) {
		if (status === 'Mastered')
			return 'bg-green-100 text-green-700 ring-1 ring-green-200 dark:bg-green-900/40 dark:text-green-300 dark:ring-green-800/60';
		return 'bg-yellow-100 text-yellow-700 ring-1 ring-yellow-200 dark:bg-yellow-900/40 dark:text-yellow-300 dark:ring-yellow-800/60';
	}

	$: readyHomeworkCount = followUpQuestions.filter((item) => item.status === 'Ready').length;

	function formatHomeworkLabel(modelId: string | null | undefined, fallbackId: string) {
		return modelId || fallbackId;
	}

	function formatPracticeTopicList(items: any[] = []) {
		const topics = Array.from(
			new Set(
				items
					.flatMap((item) => (Array.isArray(item?.topics) ? item.topics : []))
					.map((topic) => String(topic).trim())
					.filter(Boolean)
			)
		);

		return topics.join(', ');
	}

	function summarizeHomeworkStatus(hasMastered: boolean, hasNeedsPractice: boolean) {
		if (hasMastered && !hasNeedsPractice) return 'Mastered';
		return 'Practice Available';
	}

	function getStudentDashboardCacheKey(groupId: string, studentId: string) {
		return `student-dashboard:${groupId}:${studentId}`;
	}

	function applyStudentDashboardSnapshot(snapshot: StudentDashboardSnapshot) {
		homeworkData = snapshot.homeworkData;
		practiceAssignments = snapshot.practiceAssignments;
		conceptsData = snapshot.conceptsData;
		followUpQuestions = snapshot.followUpQuestions;
		hasLoadedStudentDashboardOnce = true;
	}

	async function loadStudentDashboardData() {
		const requestId = ++studentDashboardRequestId;

		if (useFrontendTestingData) {
			homeworkData = placeholderHomeworkData;
			practiceAssignments = placeholderPracticeAssignments;
			conceptsData = placeholderConceptsData;
			followUpQuestions = placeholderPracticeAssignments.map((item) => ({
				homework: item.homeworkLabel,
				status: item.status
			}));
			return;
		}

		if (!selectedGroupId || !$user || !localStorage.token) {
			return;
		}

		// Show loading skeleton only on the very first load (cache-miss path).
		// On subsequent refreshes / group changes the cached data stays visible.
		isDashboardLoading = !hasLoadedStudentDashboardOnce;
		dashboardLoadError = null;

		testToast(`Student dashboard sync started | group=${selectedGroupId} | student=${$user.id}`);

		try {
			const snapshot = await loadWithAITutorSessionCache<StudentDashboardSnapshot>({
				key: getStudentDashboardCacheKey(selectedGroupId, $user.id),
				ttlMs: STUDENT_DASHBOARD_SESSION_TTL_MS,
				onCached: (cached) => {
					if (requestId !== studentDashboardRequestId) return;
					applyStudentDashboardSnapshot(cached);
				},
				loader: async () => {
					// Student Dashboard summary sync:
					// - Student access should not depend on the admin-only group detail endpoint.
					// - AI Tutor endpoints below are scoped to the selected group, and assignment/analysis rows are filtered by the current student.
					try {
						const [rawHomeworkRows, practiceRows] = await Promise.all([
							fetchAITutorJson<any[]>('/homework/', {
								token: localStorage.token,
								query: { group_id: selectedGroupId, student_id: $user.id }
							}),
							fetchAITutorJson<any[]>('/practice', {
								token: localStorage.token,
								query: { group_id: selectedGroupId, student_id: $user.id }
							})
						]);

						// Filter homeworks by allowed workspace models (same logic as aitutordashboard)
						// If workspace models haven't loaded yet, defer filtering to the reactive block
						const allowedIds = $aiTutorAllowedModelIds;
						const homeworkRows =
							allowedIds.size > 0
								? rawHomeworkRows.filter((row) => row.model_id && allowedIds.has(row.model_id))
								: rawHomeworkRows;
						console.log('[studentdashboard]-[Summary]-[HomeworkFilter]:', {
							allCount: rawHomeworkRows.length,
							filteredCount: homeworkRows.length,
							allowedIdsSize: allowedIds.size,
							deferred: allowedIds.size === 0,
							excluded:
								allowedIds.size > 0
									? rawHomeworkRows
											.filter((row) => !row.model_id || !allowedIds.has(row.model_id))
											.map((r) => ({ id: r.id, modelId: r.model_id }))
									: []
						});

						const assignments = await fetchAITutorJson<any[]>('/assignment/', {
							token: localStorage.token,
							query: { student_id: $user.id }
						});

					console.log('[studentdashboard]-[Summary]-[RawAssignments]:', {
						groupId: selectedGroupId,
						assignmentCount: assignments.length,
						assignments: assignments.map((assignment) => ({
							id: assignment?.id ?? '',
							homeworkId: assignment?.homework_id ?? '',
							practiceProblemId: assignment?.practice_problem_id ?? '',
							assignedCount: assignment?.assigned_count ?? null,
							assignedItemsCount: Array.isArray(assignment?.assigned_items)
								? assignment.assigned_items.length
								: 0,
							createdAt: assignment?.created_at ?? ''
						}))
					});

					const analysesByHomeworkId = new Map<string, any | null>();
					await Promise.all(
						homeworkRows.map(async (homework) => {
							const analyses = await fetchAITutorJson<any[]>('/analysis/', {
								token: localStorage.token,
								query: { homework_id: homework.id }
							});
							const studentAnalysis =
								analyses.find((analysis) => analysis.student_id === $user.id) ??
								analyses.find((analysis) => analysis.student_email === $user.email) ??
								null;
							analysesByHomeworkId.set(homework.id, studentAnalysis);
						})
					);

					const homeworkLabelById = new Map<string, string>();
					for (const homework of homeworkRows) {
						homeworkLabelById.set(homework.id, formatHomeworkLabel(homework.model_id, homework.id));
					}

					const nextHomeworkData = homeworkRows.map((homework) => {
						const label = homeworkLabelById.get(homework.id) ?? homework.id;
						const analysis = analysesByHomeworkId.get(homework.id);
						const masteredTopics =
							(analysis?.topic_performances as TopicPerformance[] | undefined)
								?.filter((topic: TopicPerformance) => topic.status === 'mastered')
								.map((topic: TopicPerformance) => topic.topic_name) ?? [];
						const needMorePractice =
							(analysis?.topic_performances as TopicPerformance[] | undefined)
								?.filter((topic: TopicPerformance) => topic.status === 'needs_practice')
								.map((topic: TopicPerformance) => topic.topic_name) ?? [];

						return {
							homework: label,
							homeworkId: homework.id,
							modelId: homework.model_id ?? undefined,
							masteredTopics,
							needMorePractice,
							totalCount: analysis?.total_question ?? null,
							solved: analysis?.total_solved ?? null,
							attempted: analysis?.total_attempted ?? null,
							errors: analysis?.total_errors ?? null,
							notStarted: !analysis
						};
					});

					const latestPracticeByHomeworkId = new Map<string, any>();
					for (const practice of practiceRows) {
						const previous = latestPracticeByHomeworkId.get(practice.homework_id);
						if (!previous || Number(practice.version_number ?? 0) >= Number(previous.version_number ?? 0)) {
							latestPracticeByHomeworkId.set(practice.homework_id, practice);
						}
					}

					const nextPracticeAssignments = homeworkRows.map((homework, index) => {
						const assignment = assignments.find((item) => item.homework_id === homework.id);
						const practice = latestPracticeByHomeworkId.get(homework.id);
						const topic = formatPracticeTopicList(
							assignment?.assigned_items ?? practice?.problem_items ?? []
						);
						const hasAssignedItems = Array.isArray(assignment?.assigned_items)
							? assignment.assigned_items.length > 0
							: false;
						const status =
							assignment && ((assignment.assigned_count ?? 0) > 0 || hasAssignedItems)
								? 'Ready'
								: practice?.status === 'approved'
									? 'Awaiting Assignment'
									: 'Not Ready';

						return {
							id: assignment?.id ?? practice?.id ?? `practice-${homework.id}`,
							index: index + 1,
							homeworkId: homework.id,
							modelId: homework.model_id ?? undefined,
							homeworkLabel: homeworkLabelById.get(homework.id) ?? homework.id,
							topic: topic || 'General Practice',
							status,
							assignmentId: assignment?.id,
							practiceProblemId: assignment?.practice_problem_id ?? practice?.id,
							assignedItems: assignment?.assigned_items ?? []
						};
					});

					console.log('[studentdashboard]-[Summary]-[AssignmentSyncDetail]:', {
						groupId: selectedGroupId,
						assignments: nextPracticeAssignments.map((item) => {
							const assignment = assignments.find((entry) => entry.homework_id === item.homeworkId);
							const hasAssignedItems = Array.isArray(assignment?.assigned_items)
								? assignment.assigned_items.length > 0
								: false;
							return {
								homeworkId: item.homeworkId,
								homeworkName: item.homeworkLabel,
								status: item.status,
								assignmentId: item.assignmentId ?? '',
								practiceProblemId: item.practiceProblemId ?? '',
								assignedCount: assignment?.assigned_count ?? null,
								assignedItemsCount: Array.isArray(assignment?.assigned_items)
									? assignment.assigned_items.length
									: 0,
								hasAssignedItems,
								assignmentCreatedAt: assignment?.created_at ?? '',
								topics: item.topic
							};
						})
					});

					const nextFollowUpQuestions = nextPracticeAssignments.map((item) => ({
						homework: item.homeworkLabel,
						status: item.status
					}));

					const conceptMap = new Map<string, ConceptRow>();
					for (const row of nextHomeworkData) {
						const trackedTopics = [
							...row.masteredTopics.map((topic) => ({ topic, mastered: true })),
							...row.needMorePractice.map((topic) => ({ topic, mastered: false }))
						];

						for (const entry of trackedTopics) {
							if (!conceptMap.has(entry.topic)) {
								conceptMap.set(entry.topic, {
									name: entry.topic,
									testedIn: [],
									practicedDate: null,
									homeworkStatuses: {}
								});
							}

							const concept = conceptMap.get(entry.topic)!;
							if (!concept.testedIn.includes(row.homework)) {
								concept.testedIn.push(row.homework);
							}
							concept.homeworkStatuses[row.homework] = entry.mastered
								? 'Mastered'
								: 'Practice Available';
						}
					}

					for (const item of nextPracticeAssignments) {
						if (item.status !== 'Ready') continue;
						for (const topic of getPracticeTopics(item.topic)) {
							if (!conceptMap.has(topic)) continue;
							const concept = conceptMap.get(topic)!;
							concept.practicedDate = new Date().toLocaleDateString(undefined, {
								month: 'short',
								day: 'numeric'
							});
						}
					}

					const nextConceptsData = Array.from(conceptMap.values())
						.map((concept) => ({
							...concept,
							testedIn: [...concept.testedIn].sort(),
							practicedDate: concept.practicedDate,
							homeworkStatuses: Object.fromEntries(
								Object.entries(concept.homeworkStatuses).map(([homework, status]) => [
									homework,
									summarizeHomeworkStatus(status === 'Mastered', status !== 'Mastered')
								])
							)
						}))
						.sort((a, b) => a.name.localeCompare(b.name));

						return {
							homeworkData: nextHomeworkData,
							practiceAssignments: nextPracticeAssignments,
							conceptsData: nextConceptsData,
							followUpQuestions: nextFollowUpQuestions
						};
					} catch (error) {
						// If user doesn't have access to this group, redirect them
						if ((error as any).status === 403) {
							await goto('/studentdashboard');
							return { homeworkData: [], practiceAssignments: [], conceptsData: [], followUpQuestions: [] };
						}
						throw error;
					}
				});

			if (requestId !== studentDashboardRequestId) return;
			applyStudentDashboardSnapshot(snapshot);
			lastLoadedGroupId = selectedGroupId;

			testToast(
				`Student dashboard sync completed | group=${selectedGroupId} | homework=${homeworkData.length} | assignments=${practiceAssignments.length}`
			);
		} catch (error) {
			if (requestId !== studentDashboardRequestId) return; // stale, ignore
			console.error('Student dashboard sync failed:', error);
			// Persist the error so the user can see it and retry — the toast alone
			// disappears too quickly and leaves no actionable UI.
			dashboardLoadError = error instanceof Error ? error.message : 'Failed to load student dashboard data.';
			// Mark as loaded so the loading skeleton clears and the retry UI renders.
			hasLoadedStudentDashboardOnce = true;
		} finally {
			if (requestId === studentDashboardRequestId) {
				isDashboardLoading = false;
			}
		}
	}

	onDestroy(() => {
		if (highlightTimeout) clearTimeout(highlightTimeout);
	});

	$: if (useFrontendTestingData) {
		void loadStudentDashboardData();
	}

	$: if (!useFrontendTestingData && selectedGroupId && $user?.id) {
		void loadStudentDashboardData();
	}

	$: if (!useFrontendTestingData && !selectedGroupId) {
		console.log('[studentdashboard]-[Summary]-[WaitingForGroup]:', {
			lastLoadedGroupId,
			pathname: $page.url.pathname,
			search: $page.url.search
		});
	}
</script>

<div class="flex flex-col space-y-6 py-4 gap-8">
	{#if dashboardLoadError}
		<div class="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
			<svg xmlns="http://www.w3.org/2000/svg" class="mt-0.5 h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="currentColor">
				<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
			</svg>
			<div class="flex flex-1 flex-wrap items-center justify-between gap-2">
				<span>{dashboardLoadError}</span>
				<button
					class="rounded px-2 py-0.5 text-xs font-medium underline underline-offset-2 hover:opacity-80"
					on:click={() => loadStudentDashboardData()}
				>
					Retry
				</button>
			</div>
		</div>
	{/if}

	{#if isDashboardLoading}
		<div class="flex items-center justify-center py-12 text-xs text-gray-400 dark:text-gray-500">
			<svg class="mr-2 h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
			</svg>
			Loading dashboard data…
		</div>
	{/if}

	<div class="space-y-4">
		<div>
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
				Practice Questions
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{readyHomeworkCount}</span>
			</h2>
			<div class="mt-1 text-xs text-gray-900 dark:text-gray-100">
				Select a homework to start practicing. Each set contains topic-mapped questions tailored to your progress.
			</div>
		</div>

		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
				<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
					<thead class="text-xs text-gray-700 uppercase bg-[#EEE6F3] dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
						<tr>
							<th class="min-w-[140px] overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Homework Mastery</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Topic</th>
							<th class="min-w-[120px] overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Action</th>
						</tr>
					</thead>
					<tbody>
							{#each practiceAssignments as item}
								<tr
									class="border-t border-gray-100 bg-white transition hover:bg-gray-50 dark:border-gray-850 dark:bg-gray-900 dark:hover:bg-gray-800 cursor-pointer"
									on:click={() => startPracticeAssignment(item)}
								>
									<td class="min-w-[140px] px-3 py-1.5 font-medium text-gray-900 dark:text-gray-100">{item.homeworkLabel}</td>
									{#if item.status === 'Ready'}
										<td class="px-3 py-1.5">
											{#if getPracticeTopics(item.topic).length > 0}
												{@const topicList = getPracticeTopics(item.topic)}
												<div class="inline-flex max-w-[26rem] items-center gap-1 align-middle">
													<span class="truncate text-sm text-gray-700 dark:text-gray-300">
														{topicList.join(', ')}
													</span>
													<Tooltip.Root openDelay={200}>
														<Tooltip.Trigger
															type="button"
															class="inline-flex items-center text-gray-400 transition-colors hover:text-gray-500 dark:text-gray-500 dark:hover:text-gray-400"
															aria-label="View full topics list"
														>
															<EllipsisHorizontal className="h-4 w-4" />
														</Tooltip.Trigger>
														<Tooltip.Content
															side="top"
															align="start"
															sideOffset={6}
															class="z-50 max-w-[20rem] rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700 shadow-lg dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
														>
															<p class="whitespace-normal break-words leading-relaxed">{topicList.join(', ')}</p>
														</Tooltip.Content>
													</Tooltip.Root>
												</div>
											{:else}
												<span class="text-sm text-gray-400 dark:text-gray-500">—</span>
											{/if}
										</td>
										<td class="px-3 py-1.5">
											<button
												class="inline-flex items-center gap-1 rounded-full border border-[#57068C]/40 px-3 py-1 text-xs font-bold text-[#57068C] transition hover:bg-purple-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
												on:click|stopPropagation={() => startPracticeAssignment(item)}
											>
												Start
											</button>
										</td>
									{:else}
										<td
											colspan="2"
											class="px-3 py-1.5 text-center text-xs text-gray-400 dark:text-gray-500"
										>
											This homework&apos;s analysis has not been available.
										</td>
									{/if}
								</tr>
							{/each}
					</tbody>
				</table>
			</div>
		</div>
	</div>
	<div class="space-y-3">
		<div class="flex flex-wrap items-center justify-between gap-1">
			<div class="flex md:self-center text-lg font-medium px-0.5">
				<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">By Homework</h2>
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
					>{availableHomeworkCount}</span>
			</div>

			<div class="flex gap-6">
			<div class="flex gap-6">
				<div class="relative w-full sm:w-72">
					<input
						value={topicQueryRaw}
						on:input={handleTopicInput}
						class="w-full rounded-full border border-gray-300 bg-white py-1.5 pl-3 pr-9 text-xs text-gray-700 outline-hidden placeholder:text-gray-400 dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200 dark:placeholder:text-gray-500"
						placeholder="Search Topics"
					/>
					<div class="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none text-gray-400 dark:text-gray-500">
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
							<path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
						</svg>
					</div>
				</div>
			</div>
			</div>
		</div>


		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
				<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
					<thead class="text-xs text-gray-700 uppercase bg-[#EEE6F3] dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
						<tr>
							<th class="min-w-[140px] overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Homework</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Mastered Topics</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Need More Practice</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-center font-semibold whitespace-nowrap w-[5rem]">Total</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-center font-semibold whitespace-nowrap w-[5rem]">Solved</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-center font-semibold whitespace-nowrap w-[5rem]">Attempted</th>
							<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-center font-semibold whitespace-nowrap w-[5rem]">Errors</th>
						</tr>
					</thead>
					<tbody>
							{#each filteredHomeworkData as hw}
							<tr
								class="border-t border-gray-100 bg-white transition hover:bg-gray-50 dark:border-gray-850 dark:bg-gray-900 dark:hover:bg-gray-800"
							>
								<td class="min-w-[140px] px-3 py-1.5 font-medium text-gray-900 dark:text-gray-100">
									{hw.homework}
								</td>
								{#if hw.notStarted}
									<td
										colspan="6"
										class="px-3 py-1.5 text-center text-xs text-gray-400 dark:text-gray-500"
									>
										This homework&apos;s analysis has not been available.
									</td>
									{:else}
										<td class="px-3 py-1.5">
											{#if hw.masteredTopics.length > 0}
												<div class="inline-flex max-w-[26rem] items-center gap-1 align-middle">
													<span class="truncate text-sm text-gray-700 dark:text-gray-300">
														{hw.masteredTopics.join(', ')}
													</span>
													<Tooltip.Root openDelay={200}>
														<Tooltip.Trigger
															type="button"
															class="inline-flex items-center text-gray-400 transition-colors hover:text-gray-500 dark:text-gray-500 dark:hover:text-gray-400"
															aria-label="View full topics list"
														>
															<EllipsisHorizontal className="h-4 w-4" />
														</Tooltip.Trigger>
														<Tooltip.Content
															side="top"
															align="start"
															sideOffset={6}
															class="z-50 max-w-[20rem] rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700 shadow-lg dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
														>
															<p class="whitespace-normal break-words leading-relaxed">{hw.masteredTopics.join(', ')}</p>
														</Tooltip.Content>
													</Tooltip.Root>
												</div>
											{:else}
												<span class="text-sm text-gray-400 dark:text-gray-500">—</span>
											{/if}
										</td>
										<td class="px-3 py-1.5">
											{#if hw.needMorePractice.length > 0}
												<div class="inline-flex max-w-[26rem] items-center gap-1 align-middle">
													<span class="truncate text-sm text-gray-700 dark:text-gray-300">
														{hw.needMorePractice.join(', ')}
													</span>
													<Tooltip.Root openDelay={200}>
														<Tooltip.Trigger
															type="button"
															class="inline-flex items-center text-gray-400 transition-colors hover:text-gray-500 dark:text-gray-500 dark:hover:text-gray-400"
															aria-label="View full topics list"
														>
															<EllipsisHorizontal className="h-4 w-4" />
														</Tooltip.Trigger>
														<Tooltip.Content
															side="top"
															align="start"
															sideOffset={6}
															class="z-50 max-w-[20rem] rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700 shadow-lg dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
														>
															<p class="whitespace-normal break-words leading-relaxed">{hw.needMorePractice.join(', ')}</p>
														</Tooltip.Content>
													</Tooltip.Root>
												</div>
											{:else}
												<span class="text-sm text-gray-400 dark:text-gray-500">—</span>
											{/if}
									</td>
									<td class="px-3 py-1.5 text-center text-gray-900 dark:text-gray-100">
										{hw.totalCount}
									</td>
									<td class="px-3 py-1.5 text-center text-gray-900 dark:text-gray-100">
										{hw.solved}
									</td>
									<td class="px-3 py-1.5 text-center text-gray-900 dark:text-gray-100">
										{hw.attempted}
									</td>
									<td class="px-3 py-1.5 text-center text-gray-900 dark:text-gray-100">
										{hw.errors}
									</td>
								{/if}
							</tr>
						{/each}
						{#if filteredHomeworkData.length === 0}
							<tr>
								<td colspan="6" class="px-3 py-12 text-center text-xs text-gray-400 dark:text-gray-500">
									No homework matches the current homework/topic filters.
								</td>
							</tr>
						{/if}
					</tbody>
				</table>
			</div>
		</div>
	</div>

	{#if !TEMP_HIDE}
		<div class="space-y-3">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Follow Up Questions</h2>
			<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
				<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
					<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
						<thead class="text-xs text-gray-700 uppercase bg-[#EEE6F3] dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
							<tr>
								<th class="min-w-[140px] overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Homework</th>
								<th class="overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 text-left font-semibold">Status</th>
							</tr>
						</thead>
						<tbody>
							{#each followUpQuestions as item}
								<tr
									class="border-t border-gray-100 bg-white transition hover:bg-gray-50 dark:border-gray-850 dark:bg-gray-900 dark:hover:bg-gray-800"
								>
									<td class="min-w-[140px] px-3 py-1.5 font-medium text-gray-900 dark:text-gray-100">
										{item.homework}
									</td>
									<td class="px-3 py-1.5">
										<span
											class="inline-flex rounded-full px-2.5 py-1 text-xs font-medium {item.status === 'Ready'
												? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
												: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'}"
										>
											{item.status}
										</span>
									</td>
								</tr>
							{/each}
							{#if followUpQuestions.length === 0}
								<tr>
									<td colspan="2" class="px-3 py-12 text-center text-xs text-gray-400 dark:text-gray-500">
										No follow-up questions available.
									</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			</div>
		</div>
	{/if}

</div>
