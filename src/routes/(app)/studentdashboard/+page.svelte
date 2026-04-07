<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { TEMP_HIDE, AI_TUTOR_FRONTEND_TESTING_MODE } from '$lib/constants';
	import { user } from '$lib/stores';
	import { fetchAITutorJson } from '$lib/apis/aiTutor';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';

	const testToast = showAITutorTestToast;
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;

	type HomeworkSummaryRow = {
		homework: string;
		homeworkId?: string;
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

	onMount(() => {
		testToast('loading studentdashboard - Summary');
		console.log('Student Dashboard - Summary loaded');
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

		if (typeof sessionStorage !== 'undefined') {
			sessionStorage.setItem(
				'aiTutorActivePracticeAssignment',
				JSON.stringify({
					assignmentId: item.assignmentId ?? item.id,
					practiceProblemId: item.practiceProblemId ?? null,
					homeworkId: item.homeworkId,
					homeworkLabel: item.homeworkLabel,
					assignedItems: item.assignedItems ?? [],
					topic: item.topic,
					startedAt: new Date().toISOString()
				})
			);
		}

		// Planned Mastery-model flow:
		// once a "Mastery*" workspace model exists for this homework, starting practice
		// should switch the student chat onto that cloned model so the practice session
		// keeps the original homework model behavior while using the generated practice KB.
		if (typeof sessionStorage !== 'undefined' && item.modelId) {
			sessionStorage.selectedModels = JSON.stringify([buildMasteryModelId(item.modelId)]);
		}

		console.log('[PracticeAssignment] navigating to chat with right-side questions trigger', {
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
	$: filteredHomeworkData = homeworkData.filter((hw) => {
		const matchesHomework = selectedHomework === 'All' || hw.homework === selectedHomework;
		const matchesTopic =
			topicQuery === '' ||
			[...hw.masteredTopics, ...hw.needMorePractice].some((topic) =>
				topic.toLowerCase().includes(topicQuery)
			);

		return matchesHomework && matchesTopic;
	});

	let selectedConcepts: Set<string> = new Set();
	let hoveredLegendStatus: string | null = null;
	let selectedGroupId = '';
	let lastLoadedGroupId = '';
	let studentDashboardRequestId = 0;
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
		(typeof sessionStorage !== 'undefined'
			? sessionStorage.getItem('student_dashboard_last_selected_group_id') || ''
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

		testToast(`Student dashboard sync started | group=${selectedGroupId} | student=${$user.id}`);

		try {
			// Student Dashboard summary sync:
			// - Student access should not depend on the admin-only group detail endpoint.
			// - AI Tutor endpoints below are scoped to the selected group, and assignment/analysis rows are filtered by the current student.
			const [homeworkRows, practiceRows] = await Promise.all([
				// Page: Student Dashboard
				// Endpoint: GET /homework/?group_id={group_id}
				// Purpose: load the homework records for the selected group; homework label comes from model_id.
				fetchAITutorJson<any[]>('/homework/', {
					token: localStorage.token,
					query: { group_id: selectedGroupId }
				}),
				// Page: Student Dashboard
				// Endpoint: GET /practice?group_id={group_id}
				// Purpose: load the latest practice generation state for the selected group.
				fetchAITutorJson<any[]>('/practice', {
					token: localStorage.token,
					query: { group_id: selectedGroupId }
				})
			]);

			if (requestId !== studentDashboardRequestId) return;

			// Page: Student Dashboard
			// Endpoint: GET /assignment/?student_id={student_id}
			// Purpose: load practice assignments for the current student after group membership is confirmed.
			const assignments = await fetchAITutorJson<any[]>('/assignment/', {
				token: localStorage.token,
				query: { student_id: $user.id }
			});

			if (requestId !== studentDashboardRequestId) return;

			const analysesByHomeworkId = new Map<string, any | null>();
			await Promise.all(
				homeworkRows.map(async (homework) => {
					// Page: Student Dashboard
					// Endpoint: GET /analysis/?homework_id={homework_id}
					// Purpose: load per-homework analysis rows, then match only the current student by id/email.
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

			if (requestId !== studentDashboardRequestId) return;

			const homeworkLabelById = new Map<string, string>();
			for (const homework of homeworkRows) {
				homeworkLabelById.set(homework.id, formatHomeworkLabel(homework.model_id, homework.id));
			}

			homeworkData = homeworkRows.map((homework) => {
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

			practiceAssignments = homeworkRows.map((homework, index) => {
				const assignment = assignments.find((item) => item.homework_id === homework.id);
				const practice = latestPracticeByHomeworkId.get(homework.id);
				const topic = formatPracticeTopicList(assignment?.assigned_items ?? practice?.problem_items ?? []);
				const status =
					assignment && (assignment.assigned_count ?? 0) > 0
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

			followUpQuestions = practiceAssignments.map((item) => ({
				homework: item.homeworkLabel,
				status: item.status
			}));

			const conceptMap = new Map<string, ConceptRow>();
			for (const row of homeworkData) {
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
					concept.homeworkStatuses[row.homework] = entry.mastered ? 'Mastered' : 'Practice Available';
				}
			}

			for (const item of practiceAssignments) {
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

			conceptsData = Array.from(conceptMap.values())
				.map((concept) => {
					const statuses = Object.values(concept.homeworkStatuses);
					return {
						...concept,
						testedIn: [...concept.testedIn].sort(),
						practicedDate: concept.practicedDate,
						homeworkStatuses: Object.fromEntries(
							Object.entries(concept.homeworkStatuses).map(([homework, status]) => [
								homework,
								summarizeHomeworkStatus(status === 'Mastered', status !== 'Mastered')
							])
						)
					};
				})
				.sort((a, b) => a.name.localeCompare(b.name));
			lastLoadedGroupId = selectedGroupId;

			testToast(
				`Student dashboard sync completed | group=${selectedGroupId} | homework=${homeworkData.length} | assignments=${practiceAssignments.length}`
			);
			toast.success(
				`Student dashboard synced ${homeworkData.length} homework record${homeworkData.length === 1 ? '' : 's'} for the selected group.`
			);
		} catch (error) {
			console.error('Student dashboard sync failed:', error);
			toast.error(error instanceof Error ? error.message : 'Failed to sync student dashboard data.');
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
		console.log('[StudentDashboard] waiting for selected group before syncing', {
			lastLoadedGroupId,
			pathname: $page.url.pathname,
			search: $page.url.search
		});
	}
</script>

<div class="flex flex-col space-y-6 py-4 gap-8">
	<div class="space-y-3">
		<div class="flex items-center text-lg font-medium px-0.5">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Practice Questions</h2>
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
			<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{readyHomeworkCount}</span>
		</div>

		<div class="scrollbar-hidden relative max-w-full overflow-x-auto rounded-sm pt-0.5">
			<table
				class="min-w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400"
			>
				<thead
					class="-translate-y-0.5 bg-gray-50 text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400"
				>
					<tr>
						<th class="px-4 py-2 text-left font-semibold">Homework Mastery</th>
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
							<td class="px-4 py-3 font-medium text-gray-900 dark:text-gray-100"
								>{item.homeworkLabel}</td
							>
							<td class="px-4 py-3">
								<div class="flex flex-wrap gap-2">
									{#each getPracticeTopics(item.topic) as topic}
										<button
											on:click|stopPropagation={() => highlightConceptCards(topic)}
											class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
										>
											{topic}
										</button>
									{/each}
								</div>
							</td>
							<td class="px-4 py-3">
								<span class="text-sm text-gray-700 dark:text-gray-300">{item.status}</span>
							</td>
							<td class="px-4 py-3">
								{#if item.status === 'Ready'}
									<button
										class="text-xs font-medium text-black transition hover:text-gray-700 dark:text-white dark:hover:text-gray-300"
										on:click|stopPropagation={() => startPracticeAssignment(item)}
									>
										Start
									</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
	<div class="space-y-3">
		<div class="flex flex-wrap items-center justify-between gap-1">
			<div class="flex md:self-center text-lg font-medium px-0.5">
				<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">By Homework</h2>
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
					>{filteredHomeworkData.length}</span
				>
			</div>

			<div class="flex gap-6">
				<div class="relative w-full sm:w-72 flex flex-1">
								<div class=" self-center ml-1 mr-3">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-4 h-4"
					>
						<path
							fill-rule="evenodd"
							d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
					<input
						value={topicQueryRaw}
						on:input={handleTopicInput}
						class="w-full bg-transparent px-2 py-1 text-sm text-gray-700 outline-hidden placeholder:text-gray-400 dark:text-gray-300 dark:placeholder:text-gray-500"
						placeholder="Search Topics"
					/>
				</div>
			</div>
		</div>


	<div class="scrollbar-hidden relative max-w-full overflow-x-auto rounded-sm pt-0.5">
		<table
			class="min-w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400"
		>
			<thead
				class="-translate-y-0.5 bg-gray-50 text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400"
			>
				<tr>
					<th class="min-w-[140px] px-4 py-2 text-left font-semibold"> Homework </th>
					<th class="px-4 py-2 text-left font-semibold"> Mastered </th>
					<th class="px-4 py-2 text-left font-semibold"> Need More Practice </th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap"> Total </th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap"> Solved </th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap"> Attempted </th>
					<th class="px-4 py-2 text-center font-semibold whitespace-nowrap"> Errors </th>
				</tr>
			</thead>
			<tbody>
				{#each filteredHomeworkData as hw, index}
					<tr
						class="border-t border-gray-100 bg-white transition hover:bg-gray-50 dark:border-gray-850 dark:bg-gray-900 dark:hover:bg-gray-800"
					>
						<td class="min-w-[140px] px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
							{hw.homework}
						</td>
						{#if hw.notStarted}
							<td
								colspan="6"
								class="px-4 py-3 text-center text-xs text-gray-400 dark:text-gray-500"
							>
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
		</div>

	{#if !TEMP_HIDE}
		<div class="space-y-3">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Follow Up Questions</h2>
			<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
					<thead class="bg-gray-50 dark:bg-gray-800">
						<tr>
							<th
								class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-300"
								>Homework</th
							>
							<th
								class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-300"
								>Status</th
							>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200 bg-white dark:divide-gray-700 dark:bg-gray-900">
						{#each followUpQuestions as item}
							<tr class="transition hover:bg-gray-50 dark:hover:bg-gray-800">
								<td class="px-6 py-4 text-sm font-medium text-gray-900 dark:text-gray-100"
									>{item.homework}</td
								>
								<td class="px-6 py-4 text-sm">
									<span
										class="inline-flex rounded-full px-2.5 py-1 text-xs font-medium {item.status ===
										'Ready'
											? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300'
											: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'}"
									>
										{item.status}
									</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<!-- <div class="sticky top-0 z-10 space-y-4 bg-transparent py-2">
		<div class="flex items-start justify-between gap-4 px-0.5">
			<div class="flex items-start text-lg font-medium">
				<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">By Topics</h2>
				<div class="mx-2.5 flex h-6 w-[1px] self-center bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
					>{filteredConcepts.length}</span
				>
			</div>
			<div class="flex flex-wrap items-start justify-end gap-1.5">
				{#each statusOrder as status}
					<span
						class="inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium {getStatusClasses(
							status
						)}"
						on:mouseenter={() => (hoveredLegendStatus = status)}
						on:mouseleave={() => (hoveredLegendStatus = null)}
					>
						{status}
					</span>
				{/each}
			</div>
		</div>

		<div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
			{#each paginatedConcepts as concept}
				<button
					on:click={() => selectConcept(concept.name)}
					class="flex h-full flex-col items-stretch justify-start rounded-xl border p-5 text-left align-top transition {selectedConcepts.has(
						concept.name
					)
						? 'border-[#57068c]/40 bg-[#57068c]/5 dark:border-[#57068c]/50 dark:bg-[#57068c]/10'
						: highlightedConcepts.has(concept.name)
							? 'border-yellow-300 bg-yellow-50 shadow-[0_0_0_3px_rgba(253,224,71,0.35)] dark:border-yellow-500/70 dark:bg-yellow-500/10'
							: 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-gray-600 dark:hover:bg-gray-800'}"
					disabled={TEMP_HIDE}
				>
					<div class="flex items-start justify-between gap-3">
						<h3 class="select-text text-base font-semibold text-gray-900 dark:text-gray-100">
							{concept.name}
						</h3>
					</div>
					<div class="mt-1 flex flex-1 flex-col">
						<div>
							<div class="text-[11px] font-semibold tracking-wide text-gray-400 dark:text-gray-500">
								{concept.testedIn.length === 1 ? 'In Homework:' : 'In Homeworks:'}
							</div>
							<div class="mt-2 flex flex-wrap gap-1.5">
								{#each concept.testedIn as homework}
									<div class="flex min-w-0 items-start gap-1.5">
										<span
											class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full p-0 text-xs transition-transform duration-150 will-change-transform {getStatusClasses(
												normalizeHomeworkStatus(concept.homeworkStatuses[homework])
											)} {hoveredLegendStatus === normalizeHomeworkStatus(
												concept.homeworkStatuses[homework]
											)
												? 'scale-110'
												: 'scale-100'}"
										>
											{homework.replace('Homework ', '')}
										</span>
									</div>
								{/each}
							</div>
						</div>
						<div
							class="mt-auto flex min-h-[1.5rem] items-start gap-2 pt-3 text-sm text-green-600 dark:text-green-400"
						>
							{#if concept.practicedDate}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="h-4 w-4"
								>
									<path
										fill-rule="evenodd"
										d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
										clip-rule="evenodd"
									/>
								</svg>
								<span>Practiced on {concept.practicedDate}</span>
							{/if}
						</div>
					</div>
				</button>
			{/each}
		</div>

		{#if filteredConcepts.length > 18}
			<div class="flex items-center justify-center gap-2 pt-4">
				<button
					on:click={previousPage}
					disabled={currentPage === 1}
					class="rounded border border-gray-300 px-3 py-1 text-sm transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-800"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="h-4 w-4"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
					</svg>
				</button>
				{#each Array.from({ length: totalPages }, (_, i) => i + 1) as pageNum}
					<button
						on:click={() => goToPage(pageNum)}
						class="rounded border px-3 py-1 text-sm transition {currentPage === pageNum
							? 'border-purple-600 bg-purple-600 text-white'
							: 'border-gray-300 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-800'}"
					>
						{pageNum}
					</button>
				{/each}
				<button
					on:click={nextPage}
					disabled={currentPage === totalPages}
					class="rounded border border-gray-300 px-3 py-1 text-sm transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-800"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="h-4 w-4"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
					</svg>
				</button>
			</div>
		{/if}
	</div> -->
</div>
