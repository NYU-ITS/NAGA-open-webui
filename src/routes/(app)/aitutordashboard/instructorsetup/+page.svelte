<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import {
		AI_TUTOR_API_BASE_URL,
		AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES,
		AI_TUTOR_FRONTEND_TESTING_MODE,
		TESTING_AI_TUTOR
	} from '$lib/constants';
	import { aiTutorFrontendTestingErrorTypes } from '$lib/stores';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import {
		clearAITutorSessionCacheByPrefix,
		loadWithAITutorSessionCache,
		writeAITutorSessionCache
	} from '$lib/utils/aiTutorSessionCache';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
	const frontendTestingHomeworkModelNames = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester',
		'Homework4-MATH-Code-Section-Semester',
		'Homework5-MATH-Code-Section-Semester',
		'Homework6-MATH-Code-Section-Semester',
		'Homework7-MATH-Code-Section-Semester',
		'Homework8-MATH-Code-Section-Semester',
		'Homework9-MATH-Code-Section-Semester'
	];

	// ── Global flag ───────────────────────────────────────────────────────────
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;
	const testToast = showAITutorTestToast;
	const CACHE_TTL_MS = 5 * 60 * 1000;
	const LAST_AI_TUTOR_GROUP_STORAGE_KEY = 'ai_tutor_last_selected_group_id';

	// ── Types ─────────────────────────────────────────────────────────────────
	type HomeworkStat = {
		homework: string;
		status: boolean;
		answerUploaded: boolean;
		totalProblems: number | null;
		avgAttempted: number | null;
		avgSolved: number | null;
		avgErrors: number | null;
	};

	// ── Homework rows (raw API data) ─────────────────────────────────────────
	type HomeworkRow = {
		id: string;
		modelId: string | null;
		questionUploaded: boolean;
		answerUploaded: boolean;
		topicMapped?: boolean;
		answerSource?: string | null;
		questionFileName?: string | null;
		answerFileName?: string | null;
	};

	type HomeworkFileRow = HomeworkRow & {
		displayModelName: string;
		isPlaceholder: boolean;
	};

	type PersistedInstructorJob = {
		jobId: string;
		type: 'question-upload' | 'answer-upload' | 'analysis';
		groupId: string;
		modelId: string;
		homeworkId: string | null;
	};

	let homeworkRows: HomeworkRow[] = [];
	let availableModels: {
		id: string;
		name: string;
		preset: boolean;
		base_model_id: string | null;
	}[] = [];
	let convCountByModelId: Record<string, number> = {};
	let uploadingMap: Record<string, boolean> = {};
	let exportingConversationMap: Record<string, boolean> = {};
	let runningAnalysisByHomeworkId: Record<string, boolean> = {};
	let homeworkJobStepByModelId: Record<string, string> = {};
	const ACTIVE_JOB_STORAGE_KEY = 'ai_tutor_instructor_setup_jobs';
	const activeJobIds = new Set<string>();
	type DraftRow = { uid: number; modelId: string };
	let draftRows: DraftRow[] = [];
	let _nextDraftUid = 0;
	let errorTypeDefs: { type: string; color: string; description: string }[] = [];
	const dashboardPalette = ['#EE352E', '#00933C', '#B933AD', '#0039A6', '#FF6319', '#996633'];
	const errorTypeColors = dashboardPalette.slice(0, 4);
	let showEditErrorTypeModal = false;
	let showResetDefaultsModal = false;
	let resetDefaultsModalMode: 'default' | 'delete' = 'default';
	let showPromptSection = false;
	let editingErrorTypeIndex: number | null = null;
	let editingErrorTypeIsNew = false;
	let editErrorTypeName = '';
	let editErrorTypeDescription = '';
	const promptDefinitions = [
		{
			name: 'pdf_to_markdown',
			label: 'PDF to Markdown',
			usedFor: 'Homework and answer PDF ingestion'
		},
		{ name: 'topic_mapping', label: 'Topic Mapping', usedFor: 'Question topic extraction' },
		{
			name: 'generate_answers',
			label: 'Generate Answers',
			usedFor: 'Fallback answer key generation'
		},
		{
			name: 'evaluate_question',
			label: 'Evaluate Question',
			usedFor: 'Student analysis evaluation'
		},
		{
			name: 'generate_practice_problems',
			label: 'Generate Practice Problems',
			usedFor: 'Class-level practice generation'
		}
	];
	let generalPrompts: any[] = [];
	let tutorPrompts: any[] = [];
	let showPromptModal = false;
	let selectedPromptName = '';
	let selectedPromptLabel = '';
	let selectedPromptUsedFor = '';
	let selectedPromptText = '';
	let selectedPromptTutorId = '';
	let selectedPromptScope: 'default' | 'override' = 'default';
	let showPromptConfiguration = false;
	let showHomeworkAnswerFiles = true;
	let showErrorTypeConfiguration = true;

	// ── Placeholder data ──────────────────────────────────────────────────────
	const placeholderStats: HomeworkStat[] = [
		{
			homework: frontendTestingHomeworkModelNames[0],
			status: false,
			answerUploaded: false,
			totalProblems: 15,
			avgAttempted: 14.2,
			avgSolved: 12.8,
			avgErrors: 1.4
		},
		{
			homework: frontendTestingHomeworkModelNames[1],
			status: false,
			answerUploaded: false,
			totalProblems: 18,
			avgAttempted: 16.5,
			avgSolved: 14.9,
			avgErrors: 1.6
		},
		{
			homework: frontendTestingHomeworkModelNames[2],
			status: false,
			answerUploaded: false,
			totalProblems: 20,
			avgAttempted: 18.7,
			avgSolved: 16.2,
			avgErrors: 2.5
		},
		{
			homework: frontendTestingHomeworkModelNames[3],
			status: false,
			answerUploaded: false,
			totalProblems: 16,
			avgAttempted: 15.1,
			avgSolved: 13.4,
			avgErrors: 1.7
		},
		{
			homework: frontendTestingHomeworkModelNames[4],
			status: false,
			answerUploaded: false,
			totalProblems: 22,
			avgAttempted: 20.3,
			avgSolved: 18.1,
			avgErrors: 2.2
		},
		{
			homework: frontendTestingHomeworkModelNames[5],
			status: false,
			answerUploaded: false,
			totalProblems: 19,
			avgAttempted: 17.8,
			avgSolved: 15.6,
			avgErrors: 2.2
		},
		{
			homework: frontendTestingHomeworkModelNames[6],
			status: false,
			answerUploaded: false,
			totalProblems: 17,
			avgAttempted: 16.2,
			avgSolved: 14.5,
			avgErrors: 1.7
		},
		{
			homework: frontendTestingHomeworkModelNames[7],
			status: false,
			answerUploaded: false,
			totalProblems: 21,
			avgAttempted: 19.4,
			avgSolved: 17.2,
			avgErrors: 2.2
		},
		{
			homework: frontendTestingHomeworkModelNames[8],
			status: false,
			answerUploaded: false,
			totalProblems: 23,
			avgAttempted: 21.1,
			avgSolved: 18.9,
			avgErrors: 2.2
		}
	];
	const frontendTestingHomeworkRows: HomeworkRow[] = [
		{
			id: frontendTestingHomeworkModelNames[0],
			modelId: frontendTestingHomeworkModelNames[0],
			questionUploaded: true,
			answerUploaded: true,
			topicMapped: true,
			answerSource: 'uploaded',
			questionFileName: 'homework_1_questions.pdf',
			answerFileName: 'homework_1_answers.pdf'
		},
		{
			id: frontendTestingHomeworkModelNames[1],
			modelId: frontendTestingHomeworkModelNames[1],
			questionUploaded: true,
			answerUploaded: false,
			topicMapped: true,
			answerSource: null,
			questionFileName: 'homework_2_questions.pdf',
			answerFileName: null
		},
		{
			id: frontendTestingHomeworkModelNames[2],
			modelId: frontendTestingHomeworkModelNames[2],
			questionUploaded: true,
			answerUploaded: true,
			topicMapped: true,
			answerSource: 'uploaded',
			questionFileName: 'homework_3_questions.pdf',
			answerFileName: 'homework_3_answers.pdf'
		},
		{
			id: frontendTestingHomeworkModelNames[3],
			modelId: frontendTestingHomeworkModelNames[3],
			questionUploaded: false,
			answerUploaded: false,
			topicMapped: false,
			answerSource: null,
			questionFileName: null,
			answerFileName: null
		}
	];
	const frontendTestingModels = frontendTestingHomeworkModelNames.map((name) => ({ id: name, name }));
	const frontendTestingConversationCounts: Record<string, number> = {
		[frontendTestingHomeworkModelNames[0]]: 42,
		[frontendTestingHomeworkModelNames[1]]: 27,
		[frontendTestingHomeworkModelNames[2]]: 11,
		[frontendTestingHomeworkModelNames[3]]: 18
	};
	const frontendTestingGeneralPrompts = [
		{
			id: 'gp-1',
			name: 'pdf_to_markdown',
			prompt: 'Convert the uploaded PDF into clean markdown while preserving numbering and math.',
			is_active: true
		},
		{
			id: 'gp-2',
			name: 'topic_mapping',
			prompt: 'Map each question to one or more course topics in JSON.',
			is_active: true
		},
		{
			id: 'gp-3',
			name: 'generate_answers',
			prompt: 'Generate a complete answer key in markdown.',
			is_active: true
		},
		{
			id: 'gp-4',
			name: 'evaluate_question',
			prompt: 'Evaluate whether the student attempted and solved the question.',
			is_active: true
		},
		{
			id: 'gp-5',
			name: 'generate_practice_problems',
			prompt: 'Create new practice problems based on weak topics.',
			is_active: true
		}
	];
	const frontendTestingTutorPrompts = [
		{
			id: 'tp-1',
			name: 'evaluate_question',
			group_id: 'frontend-testing-group',
			prompt: 'Evaluate with a focus on partial credit and process.',
			is_active: true
		}
	];
	const frontendTestingAnalysisHistory: AnalysisRecord[] = [
		{ contents: '1,2,3,4,5', startedAt: '10:12:04 AM', completedAt: '10:14:11 AM', failed: false },
		{ contents: '1,2,3,5', startedAt: '2:05:55 PM', completedAt: null, failed: true }
	];

	// ── State ─────────────────────────────────────────────────────────────────
	let homeworkStats: HomeworkStat[] = useFrontendTestingData ? placeholderStats : [];
	let selectedGroupId = '';

	function getInstructorSetupCacheKey(resource: string, groupId?: string) {
		return ['instructor-setup', groupId || 'global', resource].join(':');
	}

	function invalidateInstructorSetupCache(groupId?: string) {
		clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('', groupId));
	}

	function buildHomeworkFileRows(
		models: { id: string; name: string; preset: boolean; base_model_id: string | null }[],
		rows: HomeworkRow[]
	): HomeworkFileRow[] {
		// Business rule for AI Tutor:
		// only workspace models should appear in Homework & Answer Files.
		// This relies on the current Open WebUI hierarchy where a base model does
		// not have a more-base parent, and derived workspace models are returned
		// as presets with a non-null base_model_id in their stored model info.
		const workspaceModels = models.filter(
			(model) =>
				model.preset === true &&
				model.base_model_id != null &&
				// Mastery-prefixed workspace models are reserved for student practice chat
				// and should not reappear as instructor homework upload candidates.
				!(model.name ?? model.id).startsWith('Mastery')
		);

		const rowsByModelId = new Map<string, HomeworkRow>();
		const rowsByModelName = new Map<string, HomeworkRow>();
		const usedRowIds = new Set<string>();

		for (const row of rows) {
			if (row.modelId && !rowsByModelId.has(row.modelId)) {
				rowsByModelId.set(row.modelId, row);
			}
		}

		for (const model of models) {
			if (!rowsByModelName.has(model.name)) {
				const row = rows.find((item) => item.modelId === model.name);
				if (row) rowsByModelName.set(model.name, row);
			}
		}

		const mergedRows: HomeworkFileRow[] = workspaceModels
			.slice()
			.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))
			.map((model) => {
				const matchingRow = rowsByModelId.get(model.id) ?? rowsByModelName.get(model.name);
				if (matchingRow) {
					usedRowIds.add(matchingRow.id);
					return {
						...matchingRow,
						displayModelName: model.name ?? model.id,
						isPlaceholder: false
					};
				}

				// Page: AI Tutor Dashboard > Instructor Setup
				// Purpose: show every accessible workspace model even before AI Tutor
				// creates a /homework row for the selected group + model_id pair.
				return {
					id: `model:${model.id}`,
					modelId: model.id,
					questionUploaded: false,
					answerUploaded: false,
					topicMapped: false,
					answerSource: null,
					questionFileName: null,
					answerFileName: null,
					displayModelName: model.name ?? model.id,
					isPlaceholder: true
				};
			});

		for (const row of rows) {
			if (usedRowIds.has(row.id)) continue;
			mergedRows.push({
				...row,
				displayModelName: row.modelId ?? row.id,
				isPlaceholder: false
			});
		}

		return mergedRows;
	}

	$: homeworkFileRows = buildHomeworkFileRows(availableModels, homeworkRows);

	function readPersistedJobs(): PersistedInstructorJob[] {
		if (typeof localStorage === 'undefined') return [];
		try {
			const raw = localStorage.getItem(ACTIVE_JOB_STORAGE_KEY);
			if (!raw) return [];
			const parsed = JSON.parse(raw);
			return Array.isArray(parsed) ? parsed : [];
		} catch {
			return [];
		}
	}

	function writePersistedJobs(jobs: PersistedInstructorJob[]) {
		if (typeof localStorage === 'undefined') return;
		localStorage.setItem(ACTIVE_JOB_STORAGE_KEY, JSON.stringify(jobs));
	}

	function upsertPersistedJob(job: PersistedInstructorJob) {
		const jobs = readPersistedJobs().filter((item) => item.jobId !== job.jobId);
		jobs.push(job);
		writePersistedJobs(jobs);
	}

	function removePersistedJob(jobId: string) {
		writePersistedJobs(readPersistedJobs().filter((item) => item.jobId !== jobId));
	}

	function setUploadIndicator(homeworkId: string | null, docType: 'question' | 'answer', active: boolean) {
		if (!homeworkId) return;
		uploadingMap = { ...uploadingMap, [`${homeworkId}-${docType}`]: active };
	}

	function setJobStep(modelId: string | null, step: string | null) {
		if (!modelId) return;
		const next = { ...homeworkJobStepByModelId };
		if (step) {
			next[modelId] = step;
		} else {
			delete next[modelId];
		}
		homeworkJobStepByModelId = next;
	}

	function markPersistedJobActive(job: PersistedInstructorJob, active: boolean) {
		if (job.type === 'analysis' && job.homeworkId) {
			runningAnalysisByHomeworkId = {
				...runningAnalysisByHomeworkId,
				[job.homeworkId]: active
			};
			return;
		}

		if (job.type === 'question-upload' || job.type === 'answer-upload') {
			setUploadIndicator(job.homeworkId, job.type === 'question-upload' ? 'question' : 'answer', active);
		}
	}

	// Table sort
	let sortKey = 'homework';
	let sortOrder: 'asc' | 'desc' = 'asc';

	function setSortKey(key: string) {
		if (sortKey === key) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortOrder = 'asc';
		}
	}

	$: sortedStats = [...homeworkStats].sort((a, b) => {
		const av = (a as any)[sortKey];
		const bv = (b as any)[sortKey];
		if (av == null && bv == null) return 0;
		if (av == null) return 1;
		if (bv == null) return -1;
		if (av < bv) return sortOrder === 'asc' ? -1 : 1;
		if (av > bv) return sortOrder === 'asc' ? 1 : -1;
		return 0;
	});

	// Charts scroll
	let chartsContainer: HTMLElement;
	let canScrollLeft = false;
	let canScrollRight = false;

	function updateScrollState() {
		if (!chartsContainer) return;
		canScrollLeft = chartsContainer.scrollLeft > 0;
		canScrollRight =
			chartsContainer.scrollLeft + chartsContainer.clientWidth < chartsContainer.scrollWidth - 1;
	}

	function scrollCharts(direction: 'left' | 'right') {
		if (chartsContainer) {
			chartsContainer.scrollBy({ left: direction === 'left' ? -400 : 400, behavior: 'smooth' });
		}
	}

	function seedDummyDashboard(groupId: string) {
		availableModels = frontendTestingModels;
		homeworkRows = frontendTestingHomeworkRows;
		convCountByModelId = frontendTestingConversationCounts;
		errorTypeDefs = $aiTutorFrontendTestingErrorTypes;
		generalPrompts = frontendTestingGeneralPrompts;
		tutorPrompts = frontendTestingTutorPrompts.map((p) => ({ ...p, group_id: groupId || 'frontend-testing-group' }));
		homeworkStats = placeholderStats.map((stat, i) => ({
			...stat,
			homework: stat.homework,
			status: i < 4,
			answerUploaded: i === 0 || i === 2
		}));
		selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
		syncRunSelectionFlags();
		analysisHistory = frontendTestingAnalysisHistory;
		if (!selectedHwForRun && homeworkStats.length > 0) {
			selectedHwForRun = homeworkStats[0].homework;
		}
	}

	// ── SVG chart helpers ─────────────────────────────────────────────────────
	const W = 300,
		H = 180,
		padL = 38,
		padR = 12,
		padT = 12,
		padB = 32;

	function chartPoints(values: (number | null)[]) {
		const n = values.length;
		if (n === 0) return null;
		const nums = values.map((v) => (v != null ? v : NaN));
		const valid = nums.filter((v) => !isNaN(v));
		if (valid.length === 0) return null;
		const yMax = Math.max(...valid);
		const yMin = 0;
		const plotW = W - padL - padR;
		const plotH = H - padT - padB;
		const px = (i: number) => padL + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
		const py = (v: number) =>
			yMax === yMin ? padT + plotH / 2 : padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
		const dots = values
			.map((v, i) => (v != null ? { x: px(i), y: py(v), v, label: shortLabel(values, i) } : null))
			.filter(Boolean) as { x: number; y: number; v: number; label: string }[];
		const pathD = dots
			.map((p, j) => `${j === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
			.join(' ');
		// y-axis ticks: 0, mid, max
		const yTicks = [yMin, Math.round((yMin + yMax) / 2), Math.round(yMax)];
		// x-axis labels
		const xLabels = values.map((_, i) => ({ x: px(i), label: shortLabel(values, i) }));
		return { pathD, dots, yTicks, yMin, yMax, py, plotH, xLabels };
	}

	function shortLabel(values: (number | null)[], i: number): string {
		const stat = homeworkStats[i];
		if (!stat) return `${i + 1}`;
		const name = stat.homework;
		const m = name.match(/\d+/);
		return m ? `HW${m[0]}` : `${i + 1}`;
	}

	$: avgSolvedChart = chartPoints(homeworkStats.map((s) => s.avgSolved));
	$: avgAttemptedChart = chartPoints(homeworkStats.map((s) => s.avgAttempted));
	function getPersistedGroupId() {
		if (typeof sessionStorage === 'undefined') return '';
		return sessionStorage.getItem(LAST_AI_TUTOR_GROUP_STORAGE_KEY) || '';
	}

	$: selectedGroupId = $page.url.searchParams.get('group_id') || getPersistedGroupId();
	$: if ($page.url.searchParams.get('group_id')) {
		if (typeof sessionStorage !== 'undefined') {
			sessionStorage.setItem(
				LAST_AI_TUTOR_GROUP_STORAGE_KEY,
				$page.url.searchParams.get('group_id') || ''
			);
		}
	}

	// ── Data fetching ─────────────────────────────────────────────────────────
	onMount(async () => {
		// Page: AI Tutor Dashboard > Instructor Setup
		// Purpose: load non-group-scoped data first, then wait for the layout-selected
		// group_id before issuing group-scoped setup requests.
		testToast(
			`loading aitutordashboard - Instructor Setup | group=${selectedGroupId || 'pending'} | frontend_testing=${String(useFrontendTestingData)}`
		);
		await loadModels();
		if (useFrontendTestingData) {
			seedDummyDashboard(selectedGroupId);
			await tick();
			updateScrollState();
			return;
		}
	});

	$: if (!useFrontendTestingData && selectedGroupId) {
		void loadHomeworkStats(selectedGroupId);
	}

	$: if (!useFrontendTestingData && selectedGroupId) {
		void loadConversationCounts(selectedGroupId);
	}

	$: if (!useFrontendTestingData && selectedGroupId) {
		void loadErrorTypes(selectedGroupId);
	}

	$: if (!useFrontendTestingData && selectedGroupId) {
		void loadPrompts(selectedGroupId);
	}

	$: if (!useFrontendTestingData && selectedGroupId) {
		void resumePersistedJobs(selectedGroupId);
	}

	async function loadHomeworkStats(groupId: string) {
		testToast(`Instructor Setup fetch: homework stats group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			seedDummyDashboard(groupId);
			await tick();
			updateScrollState();
			return;
		}
		if (!groupId) {
			await tick();
			updateScrollState();
			return;
		}

		type CachedHomeworkStatsPayload = {
			homeworkRows: HomeworkRow[];
			homeworkStats: HomeworkStat[];
		};

		try {
			const cached = await loadWithAITutorSessionCache<CachedHomeworkStatsPayload>({
				key: getInstructorSetupCacheKey('homework-stats', groupId),
				ttlMs: CACHE_TTL_MS,
				loader: async () => {
					const uploadStatusMap = new Map<string, { status: boolean; answerUploaded: boolean }>();
					const topicMappedByHomeworkId = new Map<string, boolean>();
					const modelIdByHomeworkId = new Map<string, string | null>();
					let fetchedHomeworkRows: HomeworkRow[] = [];

					// Page: AI Tutor Dashboard > Instructor Setup
					// Endpoint: GET /homework/?group_id={group_id}
					// Purpose: load homework pipeline rows for the selected instructor group.
					const hwResponse = await fetch(
						`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(groupId)}`,
						{
							method: 'GET',
							headers: { Authorization: `Bearer ${localStorage.token}` }
						}
					);
					if (!hwResponse.ok) throw new Error('Homework fetch failed');
					const hwData = await hwResponse.json();
					if (Array.isArray(hwData)) {
						fetchedHomeworkRows = hwData.map((hw: any) => ({
							id: hw.id,
							modelId: hw.model_id ?? null,
							questionUploaded: hw.question_uploaded ?? false,
							answerUploaded: hw.answer_uploaded ?? false,
							topicMapped: hw.topic_mapped ?? false,
							answerSource: hw.answer_source ?? null,
							questionFileName: hw.question_filename ?? null,
							answerFileName: hw.answer_filename ?? null
						}));
						for (const hw of hwData) {
							topicMappedByHomeworkId.set(hw.id, hw.topic_mapped ?? false);
							modelIdByHomeworkId.set(hw.id, hw.model_id ?? null);
							uploadStatusMap.set(hw.id, {
								status: hw.question_uploaded ?? false,
								answerUploaded: hw.answer_uploaded ?? false
							});
						}
					}
					testToast('Instructor Setup loaded /homework data');

					const statsMap = new Map<
						string,
						{
							totalProblems: number;
							attemptedSum: number;
							solvedSum: number;
							errorSum: number;
							count: number;
						}
					>();
					const hasAnalysisByHomeworkId = new Set<string>();

					for (const homeworkId of uploadStatusMap.keys()) {
						// Page: AI Tutor Dashboard > Instructor Setup
						// Endpoint: GET /analysis/?homework_id={homework_id}
						// Purpose: aggregate student analysis rows into homework-level setup metrics.
						const analysisResponse = await fetch(
							`${AI_TUTOR_API_BASE}/analysis/?homework_id=${encodeURIComponent(homeworkId)}`,
							{
								method: 'GET',
								headers: { Authorization: `Bearer ${localStorage.token}` }
							}
						);
						if (!analysisResponse.ok) throw new Error(`Analysis fetch failed for ${homeworkId}`);
						const analysisData = await analysisResponse.json();
						if (Array.isArray(analysisData)) {
							if (analysisData.length > 0) {
								hasAnalysisByHomeworkId.add(homeworkId);
							}
							for (const row of analysisData) {
								const id = row?.homework_id ?? homeworkId;
								const prev = statsMap.get(id) ?? {
									totalProblems: 0,
									attemptedSum: 0,
									solvedSum: 0,
									errorSum: 0,
									count: 0
								};
								prev.totalProblems = Math.max(prev.totalProblems, Number(row?.total_question ?? 0));
								prev.attemptedSum += Number(row?.total_attempted ?? 0);
								prev.solvedSum += Number(row?.total_solved ?? 0);
								prev.errorSum += Number(row?.total_errors ?? 0);
								prev.count += 1;
								statsMap.set(id, prev);
							}
						}
					}

					if (uploadStatusMap.size > 0) testToast('Instructor Setup loaded /analysis data');

					const allIds = new Set([...uploadStatusMap.keys(), ...statsMap.keys()]);
					const mergedStats: HomeworkStat[] = Array.from(allIds).map((id) => {
						const upload = uploadStatusMap.get(id);
						const stats = statsMap.get(id);
						return {
							homework: id,
							status: hasAnalysisByHomeworkId.has(id),
							answerUploaded: upload?.answerUploaded ?? false,
							totalProblems: stats ? stats.totalProblems : null,
							avgAttempted: stats
								? Number((stats.attemptedSum / Math.max(stats.count, 1)).toFixed(1))
								: null,
							avgSolved: stats ? Number((stats.solvedSum / Math.max(stats.count, 1)).toFixed(1)) : null,
							avgErrors: stats ? Number((stats.errorSum / Math.max(stats.count, 1)).toFixed(1)) : null
						};
					});
					mergedStats.sort((a, b) => a.homework.localeCompare(b.homework));

					fetchedHomeworkRows = fetchedHomeworkRows.map((row) => ({
						...row,
						modelId: modelIdByHomeworkId.get(row.id) ?? row.modelId,
						topicMapped: topicMappedByHomeworkId.get(row.id) ?? row.topicMapped ?? false
					}));

					return {
						homeworkRows: fetchedHomeworkRows,
						homeworkStats: mergedStats
					};
				}
			});

			homeworkRows = cached.homeworkRows;
			homeworkStats = cached.homeworkStats;
		} catch (error) {
			testToast('Instructor Setup failed loading /homework data');
			console.error('Homework fetch failed:', error);
		}

		if (homeworkStats.length > 0 && selectedRunHomeworks.size === 0) {
			selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
			syncRunSelectionFlags();
		}

		await tick();
		updateScrollState();
	}

	// ── Upload helpers ───────────────────────────────────────────────────
	async function loadModels() {
		testToast('Instructor Setup fetch: models');
		if (useFrontendTestingData) {
			availableModels = frontendTestingModels.map((model) => ({
				...model,
				preset: true,
				base_model_id: 'frontend-testing-base-model'
			}));
			return;
		}
		try {
			const models = await loadWithAITutorSessionCache<typeof availableModels>({
				key: getInstructorSetupCacheKey('models'),
				ttlMs: CACHE_TTL_MS,
				loader: async () => {
					const res = await fetch('/api/models', {
						headers: { Authorization: `Bearer ${localStorage.token}` }
					});
					if (!res.ok) throw new Error('Models fetch failed');
					const data = await res.json();
					return Array.isArray(data?.data)
						? data.data
								.map((m: any) => ({
									id: m.id,
									name: m.name ?? m.id,
									preset: m.preset === true,
									base_model_id: m.info?.base_model_id ?? m.base_model_id ?? null
								}))
								.filter((model: { id: string; name: string }) => {
									// Mastery workspace models are generated practice-chat clones and
									// should not be offered back as instructor homework candidates.
									return !(model.name ?? model.id).startsWith('Mastery');
								})
						: [];
				}
			});
			availableModels = models;
		} catch (e) {
			console.error('Models fetch failed:', e);
		}
	}

	async function loadConversationCounts(groupId: string) {
		testToast(`Instructor Setup fetch: conversations group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			convCountByModelId = groupId ? frontendTestingConversationCounts : {};
			return;
		}
		if (!groupId) return;
		try {
			const counts = await loadWithAITutorSessionCache<Record<string, number>>({
				key: getInstructorSetupCacheKey('conversation-counts', groupId),
				ttlMs: CACHE_TTL_MS,
				loader: async () => {
					// Page: AI Tutor Dashboard > Instructor Setup
					// Endpoint: POST /api/v1/chats/filter/meta
					// Purpose: count Open WebUI conversations for the selected group and bucket them by model_id/model_name.
					const res = await fetch('/api/v1/chats/filter/meta', {
						method: 'POST',
						headers: {
							Authorization: `Bearer ${localStorage.token}`,
							'Content-Type': 'application/json'
						},
						body: JSON.stringify({ group_id: groupId, skip: 0, limit: 1000 })
					});
					if (!res.ok) throw new Error('Conv count fetch failed');
					const data = await res.json();
					const nextCounts: Record<string, number> = {};
					if (Array.isArray(data)) {
						for (const chat of data) {
							const modelKeys = [
								chat?.meta?.model_id,
								chat?.meta?.model_name,
								chat?.meta?.base_model_name
							].filter((value) => typeof value === 'string' && value.length > 0);
							for (const modelKey of new Set(modelKeys)) {
								nextCounts[modelKey] = (nextCounts[modelKey] ?? 0) + 1;
							}
						}
					}
					return nextCounts;
				}
			});
			convCountByModelId = counts;
		} catch (e) {
			console.error('Conversation count fetch failed:', e);
		}
	}

	async function loadErrorTypes(groupId: string) {
		testToast(`Instructor Setup fetch: error types group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			errorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			return;
		}
		if (!groupId) return;
		try {
			const cachedErrorTypes = await loadWithAITutorSessionCache<typeof errorTypeDefs>({
				key: getInstructorSetupCacheKey('error-types', groupId),
				ttlMs: CACHE_TTL_MS,
				loader: async () => {
					const res = await fetch(
						`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(groupId)}`,
						{ headers: { Authorization: `Bearer ${localStorage.token}` } }
					);
					if (!res.ok) throw new Error('Error types fetch failed');
					const data = await res.json();
					const errorTypes = Array.isArray(data?.error_types)
						? data.error_types
						: Array.isArray(data)
							? data
							: [];
					return errorTypes.slice(0, 4).map((et: any, i: number) => ({
						type: et.name ?? 'Unknown',
						color: errorTypeColors[i % errorTypeColors.length],
						description: et.description ?? ''
					}));
				}
			});
			errorTypeDefs = cachedErrorTypes;
		} catch (e) {
			console.error('Error types fetch failed:', e);
		}
	}

	async function loadPrompts(groupId: string) {
		testToast(`Instructor Setup fetch: prompts group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			generalPrompts = frontendTestingGeneralPrompts;
			tutorPrompts = groupId ? frontendTestingTutorPrompts.map((p) => ({ ...p, group_id: groupId })) : [];
			return;
		}
		try {
			const prompts = await loadWithAITutorSessionCache<{
				generalPrompts: any[];
				tutorPrompts: any[];
			}>({
				key: getInstructorSetupCacheKey('prompts', groupId),
				ttlMs: CACHE_TTL_MS,
				loader: async () => {
					const generalRes = await fetch(`${AI_TUTOR_API_BASE}/prompts/general`, {
						headers: { Authorization: `Bearer ${localStorage.token}` }
					});
					if (!generalRes.ok) throw new Error('General prompts fetch failed');
					const nextGeneralPrompts = await generalRes.json();

					if (!groupId) {
						return { generalPrompts: nextGeneralPrompts, tutorPrompts: [] };
					}

					// Page: AI Tutor Dashboard > Instructor Setup
					// Endpoint: GET /prompts/tutor?group_id={group_id}
					// Purpose: load class-level tutor prompt overrides for the selected group.
					const tutorRes = await fetch(
						`${AI_TUTOR_API_BASE}/prompts/tutor?group_id=${encodeURIComponent(groupId)}`,
						{ headers: { Authorization: `Bearer ${localStorage.token}` } }
					);
					if (!tutorRes.ok) throw new Error('Tutor prompts fetch failed');
					const nextTutorPrompts = await tutorRes.json();
					return {
						generalPrompts: nextGeneralPrompts,
						tutorPrompts: nextTutorPrompts
					};
				}
			});
			generalPrompts = prompts.generalPrompts;
			tutorPrompts = prompts.tutorPrompts;
		} catch (e) {
			console.error('Prompts fetch failed:', e);
		}
	}

	function getPromptSummary(name: string) {
		const tutorPrompt = tutorPrompts.find((p) => p.name === name && p.is_active !== false);
		const generalPrompt = generalPrompts.find((p) => p.name === name && p.is_active !== false);
		if (tutorPrompt) {
			return {
				scope: 'Class Override',
				prompt: tutorPrompt.prompt ?? '',
				tutorId: tutorPrompt.id ?? '',
				scopeType: 'override' as const
			};
		}
		return {
			scope: 'Default',
			prompt: generalPrompt?.prompt ?? '',
			tutorId: '',
			scopeType: 'default' as const
		};
	}

	function sleep(ms: number) {
		return new Promise((resolve) => setTimeout(resolve, ms));
	}

	async function parseErrorDetail(response: Response) {
		try {
			const data = await response.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {}
		return `Request failed: ${response.status}`;
	}

	async function pollPipelineJob(
		jobId: string,
		intervalMs: number,
		label: string,
		onProgress?: (data: any) => void
	) {
		while (true) {
			// Shared async job polling helper.
			// Endpoint: GET /pipeline/status/{job_id}
			const res = await fetch(`${AI_TUTOR_API_BASE}/pipeline/status/${encodeURIComponent(jobId)}`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) {
				throw new Error(await parseErrorDetail(res));
			}
			const data = await res.json();
			onProgress?.(data);
			testToast(`${label} check | job=${jobId} | status=${data?.status ?? 'unknown'} | step=${data?.step ?? 'unknown'}`);
			if (data?.status === 'done') return data;
			if (data?.status === 'failed') {
				throw new Error(data?.error || `${label} failed.`);
			}
			await sleep(intervalMs);
		}
	}

	async function monitorPersistedJob(job: PersistedInstructorJob) {
		if (activeJobIds.has(job.jobId)) return;
		activeJobIds.add(job.jobId);
		markPersistedJobActive(job, true);
		try {
			await pollPipelineJob(
				job.jobId,
				job.type === 'analysis' ? 10000 : 3000,
				job.type === 'analysis'
					? 'analysis run'
					: job.type === 'question-upload'
						? 'question upload'
						: 'answer upload',
				(data) => {
					// Keep a refresh-safe step message per model so the status column
					// shows which backend step is currently running.
					setJobStep(job.modelId, data?.step ? `Step: ${data.step}` : null);
				}
			);

			if (job.type === 'analysis') {
				toast.success('Analysis completed.');
			} else {
				toast.success(`${job.type === 'question-upload' ? 'Homework' : 'Answer'} upload completed.`);
			}

			if (selectedGroupId === job.groupId) {
				await loadHomeworkStats(job.groupId);
			}
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Background job failed.');
		} finally {
			setJobStep(job.modelId, null);
			markPersistedJobActive(job, false);
			removePersistedJob(job.jobId);
			activeJobIds.delete(job.jobId);
		}
	}

	async function resumePersistedJobs(groupId: string) {
		for (const job of readPersistedJobs().filter((item) => item.groupId === groupId)) {
			void monitorPersistedJob(job);
		}
	}

	async function ensureConversationsExported(homeworkId: string, modelId: string | null) {
		if (useFrontendTestingData) return true;
		if (!modelId) {
			toast.error('This homework is missing a model ID.');
			return false;
		}

		exportingConversationMap = { ...exportingConversationMap, [homeworkId]: true };
		testToast(`Export conversations is triggered | page=aitutordashboard - Instructor Setup | homework=${homeworkId}`);
		try {
			// Page: AI Tutor Dashboard > Instructor Setup
			// Endpoint: GET /conversation/?homework_id={homework_id}
			// Purpose: check whether Open WebUI conversation history has already been exported into AI Tutor storage.
			const existingRes = await fetch(
				`${AI_TUTOR_API_BASE}/conversation/?homework_id=${encodeURIComponent(homeworkId)}`,
				{ headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			if (!existingRes.ok) {
				throw new Error(await parseErrorDetail(existingRes));
			}
			const existing = await existingRes.json();
			if (Array.isArray(existing) && existing.length > 0) {
				testToast(`Conversation export check | homework=${homeworkId} | exported=${existing.length}`);
				return true;
			}

			// Page: AI Tutor Dashboard > Instructor Setup
			// Endpoint: POST /conversation/export?homework_id={homework_id}
			// Purpose: export group-member conversation history for the homework's group_id + model_id.
			const exportRes = await fetch(
				`${AI_TUTOR_API_BASE}/conversation/export?homework_id=${encodeURIComponent(homeworkId)}`,
				{
					method: 'POST',
					headers: { Authorization: `Bearer ${localStorage.token}` }
				}
			);
			if (!exportRes.ok) {
				throw new Error(await parseErrorDetail(exportRes));
			}
			const exportData = await exportRes.json();
			const exportedStudents = Number(exportData?.total_students ?? 0);
			testToast(`Conversation export result | homework=${homeworkId} | students=${exportedStudents}`);
			if (exportedStudents <= 0) {
				toast.error('No student conversations were exported for this homework.');
				return false;
			}
			toast.success(`Conversation history exported for ${exportedStudents} student${exportedStudents === 1 ? '' : 's'}.`);
			return true;
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Conversation export failed.');
			return false;
		} finally {
			exportingConversationMap = { ...exportingConversationMap, [homeworkId]: false };
		}
	}

	async function validateRunPrerequisites(row: HomeworkRow) {
		if (!selectedGroupId) {
			toast.error('Select a group before running analysis.');
			return false;
		}
		if (!row.questionUploaded) {
			toast.error('Run requires a homework PDF upload first.');
			return false;
		}
		if (!row.topicMapped) {
			toast.error('Topic mapping is still missing. Please wait for homework processing to finish.');
			return false;
		}
		return await ensureConversationsExported(row.id, row.modelId);
	}

	function openPromptModal(def: { name: string; label: string; usedFor: string }) {
		testToast(`Edit prompt is triggered | page=aitutordashboard - Instructor Setup | prompt=${def.name}`);
		const summary = getPromptSummary(def.name);
		selectedPromptName = def.name;
		selectedPromptLabel = def.label;
		selectedPromptUsedFor = def.usedFor;
		selectedPromptText = summary.prompt;
		selectedPromptTutorId = summary.tutorId;
		selectedPromptScope = summary.scopeType;
		showPromptModal = true;
	}

	async function savePromptOverride() {
		if (!selectedGroupId || !selectedPromptName) return;
		if (useFrontendTestingData) {
			if (selectedPromptTutorId) {
				tutorPrompts = tutorPrompts.map((prompt) =>
					prompt.id === selectedPromptTutorId
						? { ...prompt, prompt: selectedPromptText, is_active: true }
						: prompt
				);
			} else {
				tutorPrompts = [
					...tutorPrompts,
					{
						id: `tp-${Date.now()}`,
						name: selectedPromptName,
						group_id: selectedGroupId,
						prompt: selectedPromptText,
						is_active: true
					}
				];
			}
			showPromptModal = false;
			toast.success('TestData prompt override saved.');
			return;
		}
		try {
			if (selectedPromptTutorId) {
				await fetch(`${AI_TUTOR_API_BASE}/prompts/tutor/${selectedPromptTutorId}`, {
					method: 'PUT',
					headers: {
						'Content-Type': 'application/json',
						Authorization: `Bearer ${localStorage.token}`
					},
					body: JSON.stringify({ prompt: selectedPromptText, is_active: true })
				});
			} else {
				await fetch(`${AI_TUTOR_API_BASE}/prompts/tutor`, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						Authorization: `Bearer ${localStorage.token}`
					},
					body: JSON.stringify({
						name: selectedPromptName,
						group_id: selectedGroupId,
						prompt: selectedPromptText
					})
				});
			}
			clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('prompts', selectedGroupId));
			await loadPrompts(selectedGroupId);
			showPromptModal = false;
			testToast('Instructor Setup saved prompt override');
		} catch (e) {
			testToast('Instructor Setup failed saving prompt override');
			console.error('Prompt override save failed:', e);
		}
	}

	async function useDefaultPrompt() {
		if (useFrontendTestingData) {
			if (selectedPromptTutorId) {
				tutorPrompts = tutorPrompts.map((prompt) =>
					prompt.id === selectedPromptTutorId ? { ...prompt, is_active: false } : prompt
				);
			}
			showPromptModal = false;
			toast.success('TestData prompt reset to default.');
			return;
		}
		if (!selectedPromptTutorId) {
			showPromptModal = false;
			return;
		}
		try {
			await fetch(`${AI_TUTOR_API_BASE}/prompts/tutor/${selectedPromptTutorId}`, {
				method: 'PUT',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify({ is_active: false })
			});
			clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('prompts', selectedGroupId));
			await loadPrompts(selectedGroupId);
			showPromptModal = false;
			testToast('Instructor Setup reset prompt to default');
		} catch (e) {
			testToast('Instructor Setup failed resetting prompt to default');
			console.error('Prompt reset failed:', e);
		}
	}

	async function persistErrorTypes() {
		if (!selectedGroupId) return;
		if (useFrontendTestingData) {
			toast.success('Frontend testing error types saved.');
			aiTutorFrontendTestingErrorTypes.set(errorTypeDefs);
			return;
		}
		try {
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(selectedGroupId)}`,
				{
					method: 'PUT',
					headers: {
						'Content-Type': 'application/json',
						Authorization: `Bearer ${localStorage.token}`
					},
					body: JSON.stringify(
						errorTypeDefs.map((d) => ({ name: d.type, description: d.description }))
					)
				}
			);
			if (res.ok) {
				writeAITutorSessionCache(getInstructorSetupCacheKey('error-types', selectedGroupId), errorTypeDefs);
				testToast('Instructor Setup saved error types');
			}
		} catch (e) {
			testToast('Instructor Setup failed saving error types');
			console.error('Failed to persist error types:', e);
		}
	}

	async function resetErrorTypesToDefault() {
		if (!selectedGroupId) return;
		if (useFrontendTestingData) {
			errorTypeDefs = AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES;
			aiTutorFrontendTestingErrorTypes.set(AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES);
			toast.success('Frontend testing error types reset to defaults.');
			return;
		}
		try {
			await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(selectedGroupId)}`,
				{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('error-types', selectedGroupId));
			await loadErrorTypes(selectedGroupId);
			testToast('Instructor Setup reset error types to default');
		} catch (e) {
			testToast('Instructor Setup failed resetting error types');
			console.error('Failed to reset error types:', e);
		}
	}

	async function deleteAllErrorTypes() {
		if (!selectedGroupId) return;
		if (useFrontendTestingData) {
			errorTypeDefs = [];
			aiTutorFrontendTestingErrorTypes.set([]);
			toast.success('Frontend testing error types deleted.');
			return;
		}
		try {
			await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(selectedGroupId)}`,
				{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('error-types', selectedGroupId));
			errorTypeDefs = [];
			testToast('Instructor Setup deleted all custom error types');
		} catch (e) {
			testToast('Instructor Setup failed deleting custom error types');
			console.error('Failed to delete all error types:', e);
		}
	}

	function openEditErrorType(index: number) {
		editingErrorTypeIndex = index;
		editingErrorTypeIsNew = false;
		editErrorTypeName = errorTypeDefs[index].type;
		editErrorTypeDescription = errorTypeDefs[index].description;
		showEditErrorTypeModal = true;
	}

	function addErrorType() {
		if (errorTypeDefs.length >= 4) return;
		const color = errorTypeColors[errorTypeDefs.length % errorTypeColors.length];
		const newDef = { type: 'New Error Type', color, description: '' };
		errorTypeDefs = [...errorTypeDefs, newDef];
		editingErrorTypeIndex = errorTypeDefs.length - 1;
		editingErrorTypeIsNew = true;
		editErrorTypeName = newDef.type;
		editErrorTypeDescription = '';
		showEditErrorTypeModal = true;
	}

	async function saveErrorTypeEdit() {
		if (editingErrorTypeIndex === null) return;
		errorTypeDefs[editingErrorTypeIndex] = {
			...errorTypeDefs[editingErrorTypeIndex],
			type: editErrorTypeName,
			description: editErrorTypeDescription
		};
		errorTypeDefs = [...errorTypeDefs];
		closeErrorTypeModal();
		await persistErrorTypes();
	}

	async function deleteErrorType() {
		if (editingErrorTypeIndex === null) return;
		errorTypeDefs = errorTypeDefs.filter((_, i) => i !== editingErrorTypeIndex);
		closeErrorTypeModal();
		await persistErrorTypes();
	}

	function closeErrorTypeModal() {
		showEditErrorTypeModal = false;
		editingErrorTypeIndex = null;
		editingErrorTypeIsNew = false;
	}

	async function confirmResetDefaults() {
		showResetDefaultsModal = false;
		if (resetDefaultsModalMode === 'delete') {
			await deleteAllErrorTypes();
			return;
		}
		await resetErrorTypesToDefault();
	}

	async function uploadPdf(
		hwId: string | null,
		docType: 'question' | 'answer',
		modelId: string,
		file: File,
		draftUid?: number
	) {
		testToast(`Upload ${docType} PDF is triggered | page=aitutordashboard - Instructor Setup | model=${modelId} | target=${hwId ?? `draft-${draftUid ?? 0}`}`);
		if (!selectedGroupId && !useFrontendTestingData) {
			toast.error('Select a group before uploading PDFs.');
			return;
		}
		if (file.type !== 'application/pdf') {
			toast.error('Please upload a PDF file.');
			return;
		}
		const key = hwId ? `${hwId}-${docType}` : `draft-${draftUid ?? 0}-${docType}`;
		uploadingMap = { ...uploadingMap, [key]: true };
		if (useFrontendTestingData) {
			await new Promise((resolve) => setTimeout(resolve, 400));
			if (hwId) {
				homeworkRows = homeworkRows.map((row) =>
					row.id === hwId
						? {
								...row,
								questionUploaded: docType === 'question' ? true : row.questionUploaded,
								answerUploaded: docType === 'answer' ? true : row.answerUploaded,
								questionFileName: docType === 'question' ? file.name : row.questionFileName,
								answerFileName: docType === 'answer' ? file.name : row.answerFileName
							}
						: row
				);
				homeworkStats = homeworkStats.map((stat) =>
					stat.homework === hwId
						? {
								...stat,
								status: docType === 'question' ? true : stat.status,
								answerUploaded: docType === 'answer' ? true : stat.answerUploaded
							}
						: stat
				);
			} else if (draftUid !== undefined) {
				const draft = draftRows.find((d) => d.uid === draftUid);
				if (draft?.modelId) {
					const newHomeworkId = `Homework${homeworkRows.length + 1}-MATH-Code-Section-Semester`;
					homeworkRows = [
						...homeworkRows,
						{
							id: newHomeworkId,
							modelId: draft.modelId,
							questionUploaded: docType === 'question',
							answerUploaded: docType === 'answer',
							topicMapped: docType === 'question',
							answerSource: docType === 'answer' ? 'uploaded' : null,
							questionFileName: docType === 'question' ? file.name : null,
							answerFileName: docType === 'answer' ? file.name : null
						}
					];
					homeworkStats = [
						...homeworkStats,
						{
							homework: newHomeworkId,
							status: docType === 'question',
							answerUploaded: docType === 'answer',
							totalProblems: 14,
							avgAttempted: 11.8,
							avgSolved: 10.4,
							avgErrors: 1.4
						}
					];
					draftRows = draftRows.filter((d) => d.uid !== draftUid);
				}
			}
			uploadingMap = { ...uploadingMap, [key]: false };
			toast.success(`TestData ${docType === 'question' ? 'homework' : 'answer'} PDF uploaded.`);
			await tick();
			updateScrollState();
			return;
		}
		try {
			const formData = new FormData();
			formData.append('file', file);
			const params = new URLSearchParams({
				doc_type: docType,
				group_id: selectedGroupId,
				model_id: modelId
			});
			// Page: AI Tutor Dashboard > Instructor Setup
			// Endpoint: POST /homework/pdf-to-markdown?doc_type={question|answer}&group_id={group_id}&model_id={model_id}
			// Purpose: create or update the homework row identified by group_id + model_id and start PDF processing.
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/homework/pdf-to-markdown?${params.toString()}`,
				{
					method: 'POST',
					headers: { Authorization: `Bearer ${localStorage.token}` },
					body: formData
				}
			);
			if (!res.ok) throw new Error(await parseErrorDetail(res));
			const data = await res.json();
			const jobId = data?.job_id;
			if (!jobId) throw new Error('Upload started but no job ID was returned.');
			const persistedJob: PersistedInstructorJob = {
				jobId,
				type: docType === 'question' ? 'question-upload' : 'answer-upload',
				groupId: selectedGroupId,
				modelId,
				homeworkId: hwId
			};
			clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('homework-stats', selectedGroupId));
			upsertPersistedJob(persistedJob);
			toast.success(`${docType === 'question' ? 'Homework' : 'Answer'} upload started.`);
			await monitorPersistedJob(persistedJob);
			if (hwId === null && draftUid !== undefined)
				draftRows = draftRows.filter((d) => d.uid !== draftUid);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : 'Upload failed.');
			console.error('PDF upload failed:', e);
		} finally {
			uploadingMap = { ...uploadingMap, [key]: false };
		}
	}

	// ── Upload event handler factory ─────────────────────────────────────
	function addDraftRow() {
		const nextHomeworkNumber = homeworkRows.length + draftRows.length + 1;
		const nextHomeworkModelName = `Homework${nextHomeworkNumber}-MATH-Code-Section-Semester`;
		draftRows = [...draftRows, { uid: _nextDraftUid++, modelId: nextHomeworkModelName }];
		console.log('[addDraftRow] draftRows now:', draftRows);
	}

	function makeUploadHandler(
		hwId: string | null,
		docType: 'question' | 'answer',
		modelId: string | null,
		draftUid?: number
	) {
		return (e: Event) => {
			const file = (e.currentTarget as HTMLInputElement).files?.[0];
			if (file && modelId) void uploadPdf(hwId, docType, modelId, file, draftUid);
		};
	}

	// ── Run Analysis ─────────────────────────────────────────────────────
	let selectedHwForRun = '';
	let runAllHomeworks = true;
	let runOnlyUpdatedHomeworks = false;
	let showRunHomeworkDropdown = false;
	let selectedRunHomeworks = new Set<string>();
	let runningAnalysis = false;
	let runStep = '';
	type AnalysisRecord = {
		contents: string;
		startedAt: string;
		completedAt: string | null;
		failed: boolean;
	};
	let analysisHistory: AnalysisRecord[] = [];

	function getHomeworkNumberLabel(homework: string) {
		return homework.match(/^Homework(\d+)/)?.[1] ?? homework;
	}

	const homeworkModelNameCellClass =
		'max-w-[14rem] overflow-hidden whitespace-normal break-words leading-4 [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]';

	function getHomeworkModelName(homework: string) {
		// homework name is now homework model name
		return homework;
	}

	function getHomeworkAnalysisState(row: HomeworkRow) {
		const stat = homeworkStats.find((item) => item.homework === row.id);
		if (uploadingMap[`${row.id}-question`] || uploadingMap[`${row.id}-answer`]) {
			return 'Uploading PDF';
		}
		if (exportingConversationMap[row.id]) {
			return 'Collecting Conversations';
		}
		if (runningAnalysisByHomeworkId[row.id]) {
			return 'Analysis Running';
		}
		if (Boolean(stat?.status) && row.questionUploaded) {
			return 'Analysis Completed';
		}
		if (!row.questionUploaded && !row.answerUploaded) {
			return 'Please Upload Homework & Answer';
		}
		if (!row.questionUploaded) {
			return 'Please Upload Homework';
		}
		if (!row.topicMapped) {
			return 'Preparing Topics';
		}
		if (getConversationCountForRow(row) === 0) {
			return 'No Conversations Found';
		}
		if (row.questionUploaded) {
			return 'Ready for Analysis';
		}
		return '';
	}

	function getHomeworkAnalysisStep(row: HomeworkRow) {
		return homeworkJobStepByModelId[row.modelId ?? ''] ?? '';
	}

	function isHomeworkActionBusy(row: HomeworkRow) {
		return Boolean(
			uploadingMap[`${row.id}-question`] ||
				uploadingMap[`${row.id}-answer`] ||
				exportingConversationMap[row.id] ||
				runningAnalysisByHomeworkId[row.id]
		);
	}

	function getHomeworkActionRequirements(row: HomeworkRow) {
		const missing: string[] = [];
		if (!row.questionUploaded) missing.push('Upload homework PDF');
		if (!row.topicMapped) missing.push('Wait for topic mapping');
		if (getConversationCountForRow(row) === 0) missing.push('Need student conversations');
		return missing;
	}

	function getHomeworkActionHint(row: HomeworkRow) {
		if (isHomeworkActionBusy(row)) {
			return '';
		}

		const actionLabel = getHomeworkPrimaryActionLabel(row);
		if (actionLabel) return '';

		const missing = getHomeworkActionRequirements(row);
		if (missing.length === 0) return '';
		return missing.length === 1 ? missing[0] : `${missing[0]}...`;
	}

	function getConversationCountForRow(row: HomeworkRow) {
		const keys = new Set<string>();
		if (row.modelId) keys.add(row.modelId);

		const matchedModel = availableModels.find((model) => model.id === row.modelId);
		if (matchedModel?.name) keys.add(matchedModel.name);

		let maxCount = 0;
		for (const key of keys) {
			maxCount = Math.max(maxCount, convCountByModelId[key] ?? 0);
		}
		return maxCount;
	}

	function getHomeworkPrimaryActionLabel(row: HomeworkRow) {
		if (isHomeworkActionBusy(row)) {
			return 'In Progress';
		}
		const status = getHomeworkAnalysisState(row);
		if (status === 'Analysis Completed') {
			return 'Re-run';
		}
		if (status === 'Ready for Analysis') {
			return 'Run';
		}
		return '';
	}

	async function handleHomeworkPrimaryAction(row: HomeworkRow) {
		const action = getHomeworkPrimaryActionLabel(row);
		if (action === 'Run' || action === 'Re-run') {
			const ready = await validateRunPrerequisites(row);
			if (!ready) return;
			selectedHwForRun = row.id;
			selectedRunHomeworks = new Set([row.id]);
			syncRunSelectionFlags();
			await runAnalysis(row);
		}
	}

	function getUpdatedHomeworkIds() {
		return homeworkRows
			.filter((row) => row.questionUploaded || row.answerUploaded)
			.map((row) => row.id);
	}

	function syncRunSelectionFlags() {
		const selectedSorted = Array.from(selectedRunHomeworks).sort();
		const allSorted = homeworkStats.map((stat) => stat.homework).sort();
		const updatedSorted = getUpdatedHomeworkIds().sort();
		runAllHomeworks =
			homeworkStats.length > 0 && JSON.stringify(selectedSorted) === JSON.stringify(allSorted);
		runOnlyUpdatedHomeworks =
			selectedSorted.length > 0 && JSON.stringify(selectedSorted) === JSON.stringify(updatedSorted);
	}

	$: if (homeworkStats.length > 0 && selectedRunHomeworks.size === 0) {
		selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
		syncRunSelectionFlags();
	}

	function toggleRunHomework(homework: string) {
		if (selectedRunHomeworks.has(homework)) {
			selectedRunHomeworks.delete(homework);
		} else {
			selectedRunHomeworks.add(homework);
		}
		selectedRunHomeworks = new Set(selectedRunHomeworks);
		syncRunSelectionFlags();
	}

	function setRunAllHomeworks(checked: boolean) {
		runAllHomeworks = checked;
		if (checked) {
			selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
			syncRunSelectionFlags();
		} else {
			syncRunSelectionFlags();
		}
	}

	function setRunOnlyUpdated(checked: boolean) {
		runOnlyUpdatedHomeworks = checked;
		if (checked) {
			selectedRunHomeworks = new Set(getUpdatedHomeworkIds());
			syncRunSelectionFlags();
		} else {
			syncRunSelectionFlags();
		}
	}

	function handleRunAllChange(event: Event) {
		setRunAllHomeworks((event.currentTarget as HTMLInputElement).checked);
	}

	function handleRunOnlyUpdatedChange(event: Event) {
		setRunOnlyUpdated((event.currentTarget as HTMLInputElement).checked);
	}

	function getRunHomeworkSummary() {
		if (selectedRunHomeworks.size === 0) return 'No homework';
		return Array.from(selectedRunHomeworks)
			.sort((a, b) => {
				const aNum = Number((a.match(/\d+/) ?? ['0'])[0]);
				const bNum = Number((b.match(/\d+/) ?? ['0'])[0]);
				return aNum - bNum || a.localeCompare(b);
			})
			.map((homework) => getHomeworkNumberLabel(homework))
			.join(',');
	}

	$: runHomeworkSummary = getRunHomeworkSummary();

	async function runAnalysis(row?: HomeworkRow) {
		testToast(`Run analysis is triggered | page=aitutordashboard - Instructor Setup | selected=${getRunHomeworkSummary()}`);
		const contents = getRunHomeworkSummary();
		if (!contents || contents === 'No homework') return;
		const targetHomeworkId = row?.id ?? selectedHwForRun ?? Array.from(selectedRunHomeworks)[0] ?? '';
		if (!targetHomeworkId) {
			toast.error('Select a homework before running analysis.');
			return;
		}
		runningAnalysis = true;
		runningAnalysisByHomeworkId = { ...runningAnalysisByHomeworkId, [targetHomeworkId]: true };
		const startedAt = new Date().toLocaleTimeString();
		const steps = ['Started', 'Collecting conversation history', 'PDF converting', 'Analysing'];
		let stepIdx = 0;
		runStep = steps[0];
		const stepTimer = setInterval(() => {
			stepIdx = (stepIdx + 1) % steps.length;
			runStep = steps[stepIdx];
		}, 1800);
		if (useFrontendTestingData) {
			await new Promise((resolve) => setTimeout(resolve, 900));
			clearInterval(stepTimer);
			runStep = '';
			runningAnalysis = false;
			analysisHistory = [
				{
					contents,
					startedAt,
					completedAt: new Date().toLocaleTimeString(),
					failed: false
				},
				...analysisHistory
			];
			toast.success('TestData analysis run completed.');
			return;
		}
		try {
			// Page: AI Tutor Dashboard > Instructor Setup
			// Endpoint: POST /analysis/run?homework_id={homework_id}
			// Purpose: start the analysis pipeline for the selected homework after prerequisite checks pass.
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/run?homework_id=${encodeURIComponent(targetHomeworkId)}`,
				{ method: 'POST', headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			if (res.ok) {
				const data = await res.json();
				const jobId = data?.job_id;
				if (!jobId) throw new Error('Analysis started but no job ID was returned.');
				const persistedJob: PersistedInstructorJob = {
					jobId,
					type: 'analysis',
					groupId: selectedGroupId,
					modelId: row?.modelId ?? targetHomeworkId,
					homeworkId: targetHomeworkId
				};
				clearAITutorSessionCacheByPrefix(getInstructorSetupCacheKey('homework-stats', selectedGroupId));
				upsertPersistedJob(persistedJob);
				testToast('Instructor Setup run analysis request submitted');
				toast.success('Analysis started successfully.');
				await monitorPersistedJob(persistedJob);
				analysisHistory = [
					{ contents, startedAt, completedAt: new Date().toLocaleTimeString(), failed: false },
					...analysisHistory
				];
			} else {
				toast.error(await parseErrorDetail(res));
				analysisHistory = [
					{ contents, startedAt, completedAt: null, failed: true },
					...analysisHistory
				];
			}
		} catch (e) {
			toast.error(e instanceof Error ? e.message : 'Analysis request failed.');
			console.error('Run analysis failed:', e);
			analysisHistory = [
				{ contents, startedAt, completedAt: null, failed: true },
				...analysisHistory
			];
		} finally {
			clearInterval(stepTimer);
			runStep = '';
			runningAnalysis = false;
			runningAnalysisByHomeworkId = { ...runningAnalysisByHomeworkId, [targetHomeworkId]: false };
		}
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	<div class="space-y-12">


		<div class="space-y-3">
			<button
				type="button"
				class="flex w-full items-start justify-between gap-3 text-left"
				on:click={() => {
					showErrorTypeConfiguration = !showErrorTypeConfiguration;
				}}
			>
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">
						Error Type Configuration
					</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">
						You can have at most 4 error types
					</div>
				</div>
				<div class="flex flex-col items-end gap-1">
					<span class="pt-1 text-gray-500 dark:text-gray-400">
						{#if showErrorTypeConfiguration}
							<ChevronUp className="size-4" />
						{:else}
							<ChevronDown className="size-4" />
						{/if}
					</span>
					{#if showErrorTypeConfiguration}
					<div class="flex flex-wrap items-center justify-end gap-2">
						<button
							class={`flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
								errorTypeDefs.length < 4
									? 'border-gray-300 text-gray-700 hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800'
									: 'cursor-not-allowed border-gray-200 text-gray-400 dark:border-gray-700 dark:text-gray-500'
							}`}
							on:click|stopPropagation={addErrorType}
							disabled={errorTypeDefs.length >= 4}
						>
							<span>Add</span>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="2"
								stroke="currentColor"
								class="w-3 h-3"
							>
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
							</svg>
						</button>
						<button
							type="button"
							class="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
							on:click|stopPropagation={() => {
								resetDefaultsModalMode = 'default';
								void confirmResetDefaults();
							}}
						>
							Use default
						</button>
						{#if errorTypeDefs.length > 0}
							<button
								type="button"
								class="flex items-center gap-1 rounded-full border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 transition hover:border-red-300 hover:bg-red-50 dark:border-red-900/70 dark:text-red-300 dark:hover:border-red-800 dark:hover:bg-red-950/40"
								on:click|stopPropagation={() => {
									resetDefaultsModalMode = 'delete';
									showResetDefaultsModal = true;
								}}
							>
								<span>Delete All</span>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="w-3 h-3"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
									/>
								</svg>
							</button>
						{/if}
					</div>
					{/if}
				</div>
			</button>

			{#if showErrorTypeConfiguration}
				{#if errorTypeDefs.length === 0}
					<div
						class="rounded-lg border border-gray-200 bg-white px-4 py-6 text-sm text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-500"
					>
						No error types defined, please define error types
					</div>
				{:else}
					<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
						{#each errorTypeDefs as def, i}
							<button
								type="button"
								class="rounded-lg border border-gray-200 bg-white p-4 text-left transition hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-gray-600 dark:hover:bg-gray-800"
								on:click={() => openEditErrorType(i)}
							>
								<div class="flex items-center gap-2">
									<span
										class="h-4 w-4 rounded-full flex-shrink-0"
										style="background-color: {def.color};"
									></span>
									<div class="text-sm font-medium text-gray-900 dark:text-gray-100">{def.type}</div>
								</div>
								<p class="mt-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
									{def.description || 'No description yet.'}
								</p>
							</button>
						{/each}
					</div>
				{/if}
				<div class="flex flex-wrap items-center justify-end gap-3 pt-2">
					<button
						class="rounded-full bg-black px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800"
						on:click={persistErrorTypes}
					>
						Save
					</button>
				</div>
			{/if}
		</div>

		<div class="space-y-2">
			<button
				type="button"
				class="flex w-full items-start justify-between gap-3 text-left"
				on:click={() => {
					showHomeworkAnswerFiles = !showHomeworkAnswerFiles;
				}}
			>
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">
						Homework & Answer Files
					</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">
						Upload the PDF files here before starting the analysis
					</div>
				</div>
				<span class="pt-1 text-gray-500 dark:text-gray-400">
					{#if showHomeworkAnswerFiles}
						<ChevronUp className="size-4" />
					{:else}
						<ChevronDown className="size-4" />
					{/if}
				</span>
			</button>
			{#if showHomeworkAnswerFiles}
				<div
					class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5"
				>
					<table
						class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm"
					>
						<thead
							class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5"
						>
							<tr>
								<th class="w-[12rem] px-3 py-1.5 select-none">Homework</th>
								<th class="px-3 py-1.5 select-none">Homework PDF</th>
								<th class="px-3 py-1.5 select-none">Answer PDF</th>
								<th class="px-3 py-1.5 select-none">Total Conversations</th>
								<th class="px-3 py-1.5 select-none">Status</th>
								<th class="px-3 py-1.5 select-none">Action</th>
							</tr>
						</thead>
						<tbody>
							{#if !selectedGroupId && !useFrontendTestingData}
								<tr class="bg-white dark:bg-gray-900 text-xs">
									<td colspan="6" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
										Loading group selection...
									</td>
								</tr>
							{:else}
								{#each homeworkFileRows as row, i (row.id)}
									<tr
										class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850"
									>
										<!-- <td class="px-3 py-1 text-gray-500 dark:text-gray-400">
									<div class={homeworkModelNameCellClass}>{getHomeworkModelName(row.id)}</div>
								</td> -->
										<td
											class="px-3 py-1 text-gray-700 dark:text-gray-300"
											title={row.displayModelName}
										>
											<div class={homeworkModelNameCellClass}>{row.displayModelName}</div>
										</td>
										<td class="px-3 py-1">
											<label class="cursor-pointer">
												<input
													type="file"
													accept=".pdf"
													class="hidden"
													on:change={makeUploadHandler(row.id, 'question', row.modelId)}
												/>
												<span
													class="inline-flex items-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														fill="none"
														viewBox="0 0 24 24"
														stroke-width="1.8"
														stroke="currentColor"
														class="h-3.5 w-3.5"
													>
														<path
															stroke-linecap="round"
															stroke-linejoin="round"
															d="M12 16.5V4.5m0 0 4.5 4.5M12 4.5 7.5 9M4.5 19.5h15"
														/>
													</svg>
													{uploadingMap[`${row.id}-question`]
														? 'Uploading…'
														: row.questionUploaded
															? (row.questionFileName ?? `homework_${i + 1}_questions.pdf`)
															: 'Upload'}
												</span>
											</label>
										</td>
										<td class="px-3 py-1">
											<label class="cursor-pointer">
												<input
													type="file"
													accept=".pdf"
													class="hidden"
													on:change={makeUploadHandler(row.id, 'answer', row.modelId)}
												/>
												<span
													class="inline-flex items-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														fill="none"
														viewBox="0 0 24 24"
														stroke-width="1.8"
														stroke="currentColor"
														class="h-3.5 w-3.5"
													>
														<path
															stroke-linecap="round"
															stroke-linejoin="round"
															d="M12 16.5V4.5m0 0 4.5 4.5M12 4.5 7.5 9M4.5 19.5h15"
														/>
													</svg>
													{uploadingMap[`${row.id}-answer`]
														? 'Uploading…'
														: row.answerUploaded
															? (row.answerFileName ?? `homework_${i + 1}_answers.pdf`)
															: 'Upload'}
												</span>
											</label>
										</td>
										<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
											{getConversationCountForRow(row)}
										</td>
										<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
											<div class="max-w-[12rem] whitespace-normal break-words leading-4">
												<div>{getHomeworkAnalysisState(row)}</div>
												{#if getHomeworkAnalysisStep(row)}
													<div class="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">
														{getHomeworkAnalysisStep(row)}
													</div>
												{/if}
											</div>
										</td>
										<td class="px-3 py-1">
											{#if getHomeworkPrimaryActionLabel(row)}
												<!-- in_button_style -->
												<button
													type="button"
													class="rounded-lg p-1 text-xs font-medium text-black transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50 dark:text-white dark:hover:bg-gray-850"
													on:click={() => handleHomeworkPrimaryAction(row)}
													disabled={isHomeworkActionBusy(row)}
												>
													{getHomeworkPrimaryActionLabel(row)}
												</button>
											{:else if getHomeworkActionHint(row)}
												<div class="text-xs font-normal text-gray-400 dark:text-gray-500">
													{getHomeworkActionHint(row)}
												</div>
											{/if}
										</td>
									</tr>
								{/each}
							{/if}

							<!-- Draft rows (always rendered, outside group conditional) -->
							{#each draftRows as draft, di (draft.uid)}
								<tr
									class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850"
								>
									<td class="px-3 py-1 text-gray-500 dark:text-gray-400">
										<div class={homeworkModelNameCellClass}>{draft.modelId}</div>
									</td>
									<td class="px-3 py-1">
										<label class="cursor-pointer">
											<input
												type="file"
												accept=".pdf"
												class="hidden"
												on:change={makeUploadHandler(null, 'question', draft.modelId, draft.uid)}
											/>
											<span
												class="inline-flex items-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="1.8"
													stroke="currentColor"
													class="h-3.5 w-3.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M12 16.5V4.5m0 0 4.5 4.5M12 4.5 7.5 9M4.5 19.5h15"
													/>
												</svg>
												{uploadingMap[`draft-${draft.uid}-question`] ? 'Uploading…' : 'Upload'}
											</span>
										</label>
									</td>
									<td class="px-3 py-1">
										<label class="cursor-pointer">
											<input
												type="file"
												accept=".pdf"
												class="hidden"
												on:change={makeUploadHandler(null, 'answer', draft.modelId, draft.uid)}
											/>
											<span
												class="inline-flex items-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="1.8"
													stroke="currentColor"
													class="h-3.5 w-3.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M12 16.5V4.5m0 0 4.5 4.5M12 4.5 7.5 9M4.5 19.5h15"
													/>
												</svg>
												{uploadingMap[`draft-${draft.uid}-answer`] ? 'Uploading…' : 'Upload'}
											</span>
										</label>
									</td>
									<td class="px-3 py-1"></td>
									<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
										Please Upload Homework & Answer
									</td>
									<td class="px-3 py-1"></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

				<div class="space-y-3">
			<button
				type="button"
				class="flex w-full items-start justify-between gap-3 text-left"
				on:click={() => {
					showPromptConfiguration = !showPromptConfiguration;
				}}
			>
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">
						Prompt Configuration
					</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">
						These prompts control how AI Tutor converts homework, analyzes students, and generates
						practice.
					</div>
				</div>
				<span class="pt-1 text-gray-500 dark:text-gray-400">
					{#if showPromptConfiguration}
						<ChevronUp className="size-4" />
					{:else}
						<ChevronDown className="size-4" />
					{/if}
				</span>
			</button>

			{#if showPromptConfiguration}
				<div
					class="scrollbar-hidden relative max-w-full overflow-x-auto whitespace-nowrap rounded-sm pt-0.5"
				>
					<table
						class="max-w-full w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400"
					>
						<thead
							class="-translate-y-0.5 bg-gray-50 text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400"
						>
							<tr>
								<th class="px-3 py-1.5 select-none">Prompt</th>
								<th class="px-3 py-1.5 select-none">Used For</th>
								<th class="px-3 py-1.5 select-none">Scope</th>
								<th class="px-3 py-1.5 select-none">Action</th>
							</tr>
						</thead>
						<tbody>
							{#each promptDefinitions as def}
								{@const promptSummary = getPromptSummary(def.name)}
								<tr
									class="border-t border-gray-100 bg-white text-xs dark:border-gray-850 dark:bg-gray-900"
								>
									<td class="px-3 py-1.5 font-medium text-gray-900 dark:text-white">{def.label}</td>
									<td class="px-3 py-1.5 text-gray-700 dark:text-gray-300">{def.usedFor}</td>
									<td class="px-3 py-1.5 text-gray-700 dark:text-gray-300">{promptSummary.scope}</td
									>
									<td class="px-3 py-1.5">
										<!-- in_button_style -->
										<button
											class="rounded-lg p-1 text-xs font-medium text-black transition hover:bg-gray-100 dark:text-white dark:hover:bg-gray-850"
											on:click={() => openPromptModal(def)}
										>
											Edit
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<!-- Run Analysis subsection & Analysis history -->
		<!-- <div class="space-y-3">
			<div class="flex items-center justify-between gap-4">
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Run Analysis</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">Select a homework and run the full analysis pipeline</div>
				</div>
				<div class="flex items-center gap-4 shrink-0">
					<label class="flex items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
						<input
							type="checkbox"
							checked={runAllHomeworks}
							on:change={handleRunAllChange}
							class="h-3 w-3 rounded-sm border-gray-300 text-gray-700 focus:ring-gray-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-300 dark:focus:ring-gray-400"
						/>
						<span>All</span>
					</label>
					<label class="flex items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
						<input
							type="checkbox"
							checked={runOnlyUpdatedHomeworks}
							on:change={handleRunOnlyUpdatedChange}
							class="h-3 w-3 rounded-sm border-gray-300 text-gray-700 focus:ring-gray-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-300 dark:focus:ring-gray-400"
						/>
						<span>Only Updated Homeworks</span>
					</label>
					<div class="relative">
						<button
							type="button"
							class="flex items-center gap-2 bg-transparent text-xs text-gray-700 dark:text-gray-300"
							on:click={() => {
								showRunHomeworkDropdown = !showRunHomeworkDropdown;
							}}
						>
							<span>Selected: {runHomeworkSummary}</span>
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="h-3 w-3">
								<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
							</svg>
						</button>
						{#if showRunHomeworkDropdown}
							<div class="absolute right-0 top-full z-10 mt-2 min-w-[10rem] rounded-lg border border-gray-200 bg-white p-3 shadow-lg dark:border-gray-700 dark:bg-gray-900">
								<div class="space-y-2">
									{#each homeworkStats as stat}
										<label class="flex items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
											<input
												type="checkbox"
												checked={selectedRunHomeworks.has(stat.homework)}
												on:change={() => toggleRunHomework(stat.homework)}
												class="h-3 w-3 rounded-sm border-gray-300 text-gray-700 focus:ring-gray-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-300 dark:focus:ring-gray-400"
											/>
											<span>{getHomeworkNumberLabel(stat.homework)}</span>
										</label>
									{/each}
								</div>
							</div>
						{/if}
					</div>
					<button
						on:click={runAnalysis}
						disabled={selectedRunHomeworks.size === 0 || runningAnalysis}
						class="rounded-full border border-gray-300 px-3 py-1.5 text-left text-xs font-semibold text-gray-800 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
					>
						<div class="flex items-center gap-2">
							<span>{runningAnalysis ? 'Running…' : 'Run'}</span>
						</div>
						{#if runStep}
							<div class="mt-1.5 text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1">
								<span class="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse shrink-0"></span>
								{runStep}…
							</div>
						{/if}
					</button>
				</div>
			</div>

			{#if analysisHistory.length > 0}
				<table class="w-full text-xs text-left text-gray-500 dark:text-gray-400">
					<thead>
						<tr class="text-gray-400 dark:text-gray-500 border-b border-gray-100 dark:border-gray-800">
							<th class="pr-4 py-1 font-normal">Homeworks in this Run</th>
							<th class="pr-4 py-1 font-normal">Started</th>
							<th class="py-1 font-normal">Completed</th>
						</tr>
					</thead>
					<tbody>
						{#each analysisHistory as rec}
							<tr class="border-b border-gray-50 dark:border-gray-800/60">
								<td class="pr-4 py-1 text-gray-700 dark:text-gray-300">{rec.contents}</td>
								<td class="pr-4 py-1">{rec.startedAt}</td>
								<td class="py-1">
									{#if rec.failed}
										<span class="text-red-400 dark:text-red-500">Failed</span>
									{:else if rec.completedAt}
										<span class="text-green-600 dark:text-green-400">{rec.completedAt}</span>
									{:else}
										<span class="text-gray-400">—</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div> -->
	</div>
</div>
{#if showResetDefaultsModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		on:click|self={() => (showResetDefaultsModal = false)}
		role="dialog"
		aria-modal="true"
	>
		<div class="w-[420px] max-w-[90vw] rounded-xl bg-white p-6 shadow-2xl dark:bg-gray-900">
			<div class="text-base font-semibold text-gray-900 dark:text-gray-100">
				{resetDefaultsModalMode === 'delete' ? 'Delete all custom error types?' : 'Use default error types?'}
			</div>
			<p class="mt-3 text-sm text-gray-500 dark:text-gray-400">
				{resetDefaultsModalMode === 'delete'
					? 'This will remove all current custom error types from the class configuration. Default error types will be used after refresh.'
					: 'This will replace the current error types with the default set.'}
			</p>
			<div class="mt-6 flex justify-end gap-2">
				<button
					class="px-3 py-1.5 text-sm text-gray-600 transition hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
					on:click={() => (showResetDefaultsModal = false)}
				>
					Cancel
				</button>
				<button
					class="px-3 py-1.5 text-sm font-medium text-gray-900 transition hover:text-black dark:text-gray-100 dark:hover:text-white"
					on:click={confirmResetDefaults}
				>
					Confirm
				</button>
			</div>
		</div>
	</div>
{/if}
{#if showPromptModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6"
		on:click|self={() => (showPromptModal = false)}
		role="dialog"
		aria-modal="true"
	>
		<div
			class="flex max-h-[85vh] w-full max-w-[680px] flex-col overflow-hidden rounded-xl bg-white p-5 shadow-2xl dark:bg-gray-900 sm:p-6"
		>
			<div class="mb-4 flex items-start justify-between gap-4">
				<div>
					<h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">
						{selectedPromptLabel}
					</h3>
					<div class="text-xs text-gray-400 dark:text-gray-500 mt-1">{selectedPromptUsedFor}</div>
				</div>
				<button
					class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
					on:click={() => (showPromptModal = false)}
					aria-label="Close"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-5 h-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						/>
					</svg>
				</button>
			</div>

			<hr class="mb-4 border-gray-100 dark:border-gray-700" />

			<div class="mb-4 flex items-center gap-2 text-xs">
				<span class="text-gray-500 dark:text-gray-400">Scope:</span>
				<span
					class="rounded px-2 py-1 bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
				>
					{selectedPromptScope === 'override' ? 'Class Override' : 'Default'}
				</span>
			</div>

			<div class="mb-5 min-h-0 flex-1 overflow-y-auto pr-1">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5"
					>Prompt</label
				>
				<textarea
					class="min-h-[280px] w-full rounded-lg border border-gray-300 bg-white px-3 py-2 font-mono text-sm text-gray-900 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
					rows="12"
					bind:value={selectedPromptText}
				></textarea>
			</div>

			<div class="flex flex-wrap items-center justify-between gap-3">
				<button
					class="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition"
					on:click={useDefaultPrompt}
				>
					Use Default
				</button>
				<div class="flex gap-2">
					<button
						class="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition"
						on:click={() => (showPromptModal = false)}
					>
						Cancel
					</button>
					<button
						class="px-3 py-1.5 text-sm font-medium text-gray-900 dark:text-gray-100 hover:text-black dark:hover:text-white transition"
						on:click={savePromptOverride}
					>
						Save as Class Prompt
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
{#if showEditErrorTypeModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		on:click|self={closeErrorTypeModal}
		role="dialog"
		aria-modal="true"
	>
		<div class="bg-white dark:bg-gray-900 rounded-xl shadow-2xl p-6 w-[520px] max-w-[90vw]">
			<div class="flex justify-between items-center mb-5">
				<h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">
					{editingErrorTypeIsNew ? 'Add Error Type' : 'Edit Error Type'}
				</h3>
				<button
					class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
					on:click={closeErrorTypeModal}
					aria-label="Close"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-5 h-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						/>
					</svg>
				</button>
			</div>

			<hr class="border-gray-100 dark:border-gray-700 mb-5" />

			<div class="mb-4">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Name</label
				>
				<input
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
					bind:value={editErrorTypeName}
					placeholder="Error type name"
				/>
			</div>

			<div class="mb-6">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5"
					>Description</label
				>
				<textarea
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
					rows="7"
					bind:value={editErrorTypeDescription}
					placeholder="Describe this error type..."
				></textarea>
			</div>

			<div class="flex justify-between items-center">
				{#if !editingErrorTypeIsNew}
					<button
						class="px-3 py-1.5 text-sm text-red-500 hover:text-red-700 dark:hover:text-red-400 transition"
						on:click={deleteErrorType}>Delete</button
					>
				{:else}
					<div></div>
				{/if}
				<div class="flex gap-2">
					<button
						class="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition"
						on:click={closeErrorTypeModal}>Cancel</button
					>
					<button
						class="px-3 py-1.5 text-sm font-medium text-gray-900 dark:text-gray-100 hover:text-black dark:hover:text-white transition"
						on:click={saveErrorTypeEdit}>Save</button
					>
				</div>
			</div>
		</div>
	</div>
{/if}

<style>
	.scrollbar-hidden::-webkit-scrollbar {
		display: none;
	}
	.scrollbar-hidden {
		-ms-overflow-style: none;
		scrollbar-width: none;
	}
	.scrollbar-none::-webkit-scrollbar {
		display: none;
	}
	.scrollbar-none {
		-ms-overflow-style: none;
		scrollbar-width: none;
	}
</style>
