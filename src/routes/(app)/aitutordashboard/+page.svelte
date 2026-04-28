<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { aiTutorSelectedGroupId } from '$lib/stores';
	import { aiTutorAllowedModelIds } from '$lib/stores/aiTutorWorkspaceModels';
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
		clearAITutorSessionCacheByGroup,
		loadWithAITutorSessionCache
	} from '$lib/utils/aiTutorSessionCache';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
import { createColResize } from '$lib/utils/colResize';

	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
let mainTableEl: HTMLTableElement;
const { colWidths: mainColWidths, initColResize: initMainColResize } = createColResize([24, 16, 20, 12, 14, 14]);
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
	const SUMMARY_SESSION_TTL_MS = 5 * 60 * 1000;
	let lastSyncedGroupId = '';

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
	type ConversationCount = { studentCount: number; chatCount: number };

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

	let homeworkRows: HomeworkRow[] = [];
	let availableModels: {
		id: string;
		name: string;
		access_control?: { read?: { group_ids?: string[] } };
		user_id?: string;
	}[] = [];
	let convCountByModelId: Record<string, ConversationCount> = {};
	let uploadingMap: Record<string, boolean> = {};
	let exportingConversationMap: Record<string, boolean> = {};
	let runningAnalysisByHomeworkId: Record<string, boolean> = {};
	type DraftRow = { uid: number; modelId: string };
	let draftRows: DraftRow[] = [];
	let _prevGroupIdForReset = '';
	let _nextDraftUid = 0;
	let originalErrorTypeDefs: { type: string; color: string; description: string }[] = [];
	let draftErrorTypeDefs: { type: string; color: string; description: string }[] = [];
	const dashboardPalette = ['#EE352E', '#00933C', '#B933AD', '#0039A6', '#FF6319', '#996633'];
	const errorTypeColors = dashboardPalette.slice(0, 4);
	let showEditErrorTypeModal = false;
	let showResetDefaultsModal = false;
	let showPromptSection = false;
	let editingErrorTypeIndex: number | null = null;
	let editingErrorTypeIsNew = false;
	let editErrorTypeName = '';
	let editErrorTypeDescription = '';
	const promptDefinitions = [
		{ name: 'pdf_to_markdown', label: 'PDF to Markdown', usedFor: 'Homework and answer PDF ingestion' },
		{ name: 'topic_mapping', label: 'Topic Mapping', usedFor: 'Question topic extraction' },
		{ name: 'generate_answers', label: 'Generate Answers', usedFor: 'Fallback answer key generation' },
		{ name: 'evaluate_question', label: 'Evaluate Question', usedFor: 'Student analysis evaluation' },
		{ name: 'generate_practice_problems', label: 'Generate Practice Problems', usedFor: 'Class-level practice generation' }
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

	// ── Placeholder data ──────────────────────────────────────────────────────
	const placeholderStats: HomeworkStat[] = [
		{ homework: frontendTestingHomeworkModelNames[0], status: false, answerUploaded: false, totalProblems: 15, avgAttempted: 14.2, avgSolved: 12.8, avgErrors: 1.4 },
		{ homework: frontendTestingHomeworkModelNames[1], status: false, answerUploaded: false, totalProblems: 18, avgAttempted: 16.5, avgSolved: 14.9, avgErrors: 1.6 },
		{ homework: frontendTestingHomeworkModelNames[2], status: false, answerUploaded: false, totalProblems: 20, avgAttempted: 18.7, avgSolved: 16.2, avgErrors: 2.5 },
		{ homework: frontendTestingHomeworkModelNames[3], status: false, answerUploaded: false, totalProblems: 16, avgAttempted: 15.1, avgSolved: 13.4, avgErrors: 1.7 },
		{ homework: frontendTestingHomeworkModelNames[4], status: false, answerUploaded: false, totalProblems: 22, avgAttempted: 20.3, avgSolved: 18.1, avgErrors: 2.2 },
		{ homework: frontendTestingHomeworkModelNames[5], status: false, answerUploaded: false, totalProblems: 19, avgAttempted: 17.8, avgSolved: 15.6, avgErrors: 2.2 },
		{ homework: frontendTestingHomeworkModelNames[6], status: false, answerUploaded: false, totalProblems: 17, avgAttempted: 16.2, avgSolved: 14.5, avgErrors: 1.7 },
		{ homework: frontendTestingHomeworkModelNames[7], status: false, answerUploaded: false, totalProblems: 21, avgAttempted: 19.4, avgSolved: 17.2, avgErrors: 2.2 },
		{ homework: frontendTestingHomeworkModelNames[8], status: false, answerUploaded: false, totalProblems: 23, avgAttempted: 21.1, avgSolved: 18.9, avgErrors: 2.2 }
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
	const frontendTestingConversationCounts: Record<string, ConversationCount> = {
		[frontendTestingHomeworkModelNames[0]]: { studentCount: 3, chatCount: 42 },
		[frontendTestingHomeworkModelNames[1]]: { studentCount: 2, chatCount: 27 },
		[frontendTestingHomeworkModelNames[2]]: { studentCount: 1, chatCount: 11 },
		[frontendTestingHomeworkModelNames[3]]: { studentCount: 2, chatCount: 18 }
	};
	const frontendTestingGeneralPrompts = [
		{ id: 'gp-1', name: 'pdf_to_markdown', prompt: 'Convert the uploaded PDF into clean markdown while preserving numbering and math.', is_active: true },
		{ id: 'gp-2', name: 'topic_mapping', prompt: 'Map each question to one or more course topics in JSON.', is_active: true },
		{ id: 'gp-3', name: 'generate_answers', prompt: 'Generate a complete answer key in markdown.', is_active: true },
		{ id: 'gp-4', name: 'evaluate_question', prompt: 'Evaluate whether the student attempted and solved the question.', is_active: true },
		{ id: 'gp-5', name: 'generate_practice_problems', prompt: 'Create new practice problems based on weak topics.', is_active: true }
	];
	const frontendTestingTutorPrompts = [
		{ id: 'tp-1', name: 'evaluate_question', group_id: 'frontend-testing-group', prompt: 'Evaluate with a focus on partial credit and process.', is_active: true }
	];
const frontendTestingAnalysisHistory: AnalysisRecord[] = [
	{ contents: '1,2,3,4,5', startedAt: '10:12:04 AM', completedAt: '10:14:11 AM', failed: false },
	{ contents: '1,2,3,5', startedAt: '2:05:55 PM', completedAt: null, failed: true }
];
const bannerPlaceholderTime = 'TEST-TIME';

	// ── State ─────────────────────────────────────────────────────────────────
	let homeworkStats: HomeworkStat[] = useFrontendTestingData ? placeholderStats : [];
	// $aiTutorSelectedGroupId now comes from store

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
		originalErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
		draftErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
		generalPrompts = frontendTestingGeneralPrompts;
		tutorPrompts = frontendTestingTutorPrompts.map((p) => ({ ...p, group_id: groupId || 'frontend-testing-group' }));
		homeworkStats = placeholderStats.map((stat, i) => ({
			...stat,
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
	let chartWidth = 0;
	const H = 200;
	const padL = 44, padR = 16, padT = 16, padB = 44;
	$: W = chartWidth || 300;

	// Chart tooltip state
	let chartTooltip = {
		visible: false,
		x: 0,
		y: 0,
		align: 'center' as 'left' | 'center' | 'right',
		label: '',
		solved: null as number | null,
		attempted: null as number | null
	};

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
		const slotCount = Math.max(n, 14);
		const px = (i: number) => padL + (slotCount <= 1 ? plotW / 2 : (i / (slotCount - 1)) * plotW);
		const py = (v: number) =>
			yMax === yMin ? padT + plotH / 2 : padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
		const dots = values
			.map((v, i) => (v != null ? { x: px(i), y: py(v), v, label: shortLabel(values, i) } : null))
			.filter(Boolean) as { x: number; y: number; v: number; label: string }[];
		const pathD = dots.map((p, j) => `${j === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
		// y-axis ticks: 0, mid, max
		const yTicks = [yMin, Math.round((yMin + yMax) / 2), Math.round(yMax)];
		// x-axis labels
		const xLabels = values.map((_, i) => ({ x: px(i), label: shortLabel(values, i) }));
		return { pathD, dots, yTicks, yMin, yMax, py, plotH, xLabels };
	}

	function shortLabel(values: (number | null)[], i: number): string {
		const stat = homeworkStats[i];
		if (!stat) return `${i + 1}`;
		const homeworkLabel = getHomeworkModelName(stat.homework);

		// Rule 3: if the name contains a homework number pattern (hw1, homework 2, etc.),
		// prefer to keep that identifier and drop the rest.
		const hwMatch = homeworkLabel.match(/(homework|hw)\s*[_—\-]?\s*(\d+)/i);
		if (hwMatch) {
			const allMatches = homeworkLabel.match(/(homework|hw)\s*[_—\-]?\s*(\d+)/gi);
			if (allMatches && allMatches.length === 1) {
				return hwMatch[0];
			}
		}

		// Rule 1 & 2: show full name when possible; wrap to two lines if needed.
		if (homeworkLabel.length <= 20) return homeworkLabel;

		// Try to split into two lines at a natural breakpoint near the middle.
		const mid = Math.floor(homeworkLabel.length / 2);
		let splitIndex = -1;
		for (let j = mid; j < homeworkLabel.length; j++) {
			if (homeworkLabel[j] === ' ' || homeworkLabel[j] === '-') {
				splitIndex = j;
				break;
			}
		}
		if (splitIndex === -1) {
			for (let j = mid; j >= 0; j--) {
				if (homeworkLabel[j] === ' ' || homeworkLabel[j] === '-') {
					splitIndex = j;
					break;
				}
			}
		}
		if (splitIndex > 0) {
			const line1 = homeworkLabel.slice(0, splitIndex).trim();
			const line2 = homeworkLabel.slice(splitIndex + 1).trim();
			// Only use two lines if each line is reasonably short (won't overlap).
			if (line1.length <= 16 && line2.length <= 16) {
				return `${line1}\n${line2}`;
			}
		}

		// Fallback: natural truncation.
		return `${homeworkLabel.slice(0, 18)}...`;
	}

	function combinedChartPoints(values1: (number | null)[], values2: (number | null)[]) {
		const n = values1.length;
		if (n === 0) return null;
		const nums1 = values1.map((v) => (v != null ? v : NaN));
		const nums2 = values2.map((v) => (v != null ? v : NaN));
		const valid1 = nums1.filter((v) => !isNaN(v));
		const valid2 = nums2.filter((v) => !isNaN(v));
		if (valid1.length === 0 && valid2.length === 0) return null;
		// Combined max/min for both datasets
		const yMax = Math.max(...valid1, ...valid2);
		const yMin = 0;
		const plotW = W - padL - padR;
		const plotH = H - padT - padB;
			const slotCount = Math.max(n, 14);
		const px = (i: number) => padL + (slotCount <= 1 ? plotW / 2 : (i / (slotCount - 1)) * plotW);
		const py = (v: number) =>
			yMax === yMin ? padT + plotH / 2 : padT + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
		const dots1 = values1
			.map((v, i) => (v != null ? { x: px(i), y: py(v), v, label: shortLabel(values1, i) } : null))
			.filter(Boolean) as { x: number; y: number; v: number; label: string }[];
		const dots2 = values2
			.map((v, i) => (v != null ? { x: px(i), y: py(v), v, label: shortLabel(values2, i) } : null))
			.filter(Boolean) as { x: number; y: number; v: number; label: string }[];
		const pathD1 = dots1.map((p, j) => `${j === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
		const pathD2 = dots2.map((p, j) => `${j === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
		const yTicks = [yMin, Math.round((yMin + yMax) / 2), Math.round(yMax)];
		const xLabels = values1.map((_, i) => ({ x: px(i), label: shortLabel(values1, i) }));
		const labelStep = Math.max(1, Math.ceil((xLabels.length * 85) / Math.max(1, plotW)));
		return { pathD1, pathD2, dots1, dots2, yTicks, yMin, yMax, py, plotH, xLabels, labelStep, px, slotCount };
	}

	$: avgSolvedChart = chartPoints(homeworkStats.map((s) => s.avgSolved));
	$: avgAttemptedChart = chartPoints(homeworkStats.map((s) => s.avgAttempted));
	$: combinedChart = combinedChartPoints(homeworkStats.map((s) => s.avgSolved), homeworkStats.map((s) => s.avgAttempted));
	// ── Data fetching ─────────────────────────────────────────────────────────
	onMount(async () => {
		// Page: AI Tutor Dashboard Summary
		// Purpose: load non-group-scoped data immediately, then wait for the layout to
		// write the default group_id into the URL before issuing group-scoped requests.
		testToast(
			`loading aitutordashboard - Summary | group=${$aiTutorSelectedGroupId || 'pending'} | frontend_testing=${String(useFrontendTestingData)}`
		);
		console.log('[aitutordashboard]-[Summary]-[Mount]:', {
			pathname: $page.url.pathname,
			groupId: $aiTutorSelectedGroupId,
			groupIdFromUrl: $page.url.searchParams.get('group_id') || ''
		});
		await loadModels();
		if (useFrontendTestingData) {
			seedDummyDashboard($aiTutorSelectedGroupId);
			await tick();
			updateScrollState();
			return;
		}
	});

	// Reset per-homework action state whenever the selected group changes so that
	// in-progress indicators from a previous group never bleed into the new one.
	$: if ($aiTutorSelectedGroupId !== _prevGroupIdForReset) {
		_prevGroupIdForReset = $aiTutorSelectedGroupId;
		uploadingMap = {};
		exportingConversationMap = {};
		runningAnalysisByHomeworkId = {};
		draftRows = [];
		homeworkRows = [];
		homeworkStats = [];
		convCountByModelId = {};
		// When switching to a non-empty group, trigger data loads.
		if ($aiTutorSelectedGroupId) {
			void loadHomeworkStats($aiTutorSelectedGroupId);
			void loadConversationCounts($aiTutorSelectedGroupId);
			void loadErrorTypes($aiTutorSelectedGroupId);
			void loadPrompts($aiTutorSelectedGroupId);
		}
	}

async function loadHomeworkStats(groupId: string) {
		testToast(`Summary fetch: homework stats group=${groupId || 'none'}`);
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

		const applySummarySnapshot = (snapshot: {
			homeworkStats: HomeworkStat[];
			homeworkRows: HomeworkRow[];
		}) => {
			const allowedIds = $aiTutorAllowedModelIds;
			const allRows = snapshot.homeworkRows;
			const filteredRows = allRows.filter(
				(row) => row.modelId && allowedIds.has(row.modelId)
			);
			const excludedRows = allRows.filter(
				(row) => !row.modelId || !allowedIds.has(row.modelId)
			);
			console.log('[HomeworkFilter]-[Summary]-[ApplySnapshot]:', {
				all: allRows.map((r) => ({ id: r.id, modelId: r.modelId })),
				selected: filteredRows.map((r) => ({ id: r.id, modelId: r.modelId })),
				excluded: excludedRows.map((r) => ({
					id: r.id,
					modelId: r.modelId,
					reason: r.modelId ? 'model not in allowed set for current group' : 'missing modelId'
				}))
			});
			const filteredStats = snapshot.homeworkStats.filter((stat) => {
				const row = snapshot.homeworkRows.find((r) => r.id === stat.homework);
				return row?.modelId && allowedIds.has(row.modelId);
			});
			homeworkStats = filteredStats;
			homeworkRows = filteredRows;
			if (homeworkStats.length > 0 && selectedRunHomeworks.size === 0) {
				selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
				syncRunSelectionFlags();
			}
		};

		try {
			const snapshot = await loadWithAITutorSessionCache({
				key: `summary:${groupId}:homework-stats`,
				ttlMs: SUMMARY_SESSION_TTL_MS,
				onCached: (cached) => { if ($aiTutorSelectedGroupId === groupId) applySummarySnapshot(cached); },
				loader: async () => {
					const uploadStatusMap = new Map<
						string,
						{ status: boolean; answerUploaded: boolean; totalProblems: number | null }
					>();
					const topicMappedByHomeworkId = new Map<string, boolean>();
					const modelIdByHomeworkId = new Map<string, string | null>();
			// Page: AI Tutor Dashboard Summary
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
					const nextHomeworkRows: HomeworkRow[] = Array.isArray(hwData)
						? hwData.map((hw: any) => ({
					id: hw.id,
					modelId: hw.model_id ?? null,
					questionUploaded: hw.question_uploaded ?? false,
					answerUploaded: hw.answer_uploaded ?? false,
					topicMapped: hw.topic_mapped ?? false,
					answerSource: hw.answer_source ?? null,
					questionFileName: hw.question_filename ?? null,
					answerFileName: hw.answer_filename ?? null
						}))
						: [];
					for (const hw of Array.isArray(hwData) ? hwData : []) {
						topicMappedByHomeworkId.set(hw.id, hw.topic_mapped ?? false);
						modelIdByHomeworkId.set(hw.id, hw.model_id ?? null);
						uploadStatusMap.set(hw.id, {
							status: hw.question_uploaded ?? false,
							answerUploaded: hw.answer_uploaded ?? false,
							totalProblems: countHomeworkQuestions(hw.question_data, hw.topic_mapping) || null
						});
					}
					testToast('Summary loaded /homework data');

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
				// Page: AI Tutor Dashboard Summary
				// Endpoint: GET /analysis/?homework_id={homework_id}
				// Purpose: aggregate student analysis rows into homework-level summary metrics.
						const analysisResponse = await fetch(
							`${AI_TUTOR_API_BASE}/analysis/?group_id=${encodeURIComponent(groupId)}&homework_id=${encodeURIComponent(homeworkId)}`,
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
					if (uploadStatusMap.size > 0) testToast('Summary loaded /analysis data');

					const allIds = new Set([...uploadStatusMap.keys(), ...statsMap.keys()]);
					const merged: HomeworkStat[] = Array.from(allIds).map((id) => {
						const upload = uploadStatusMap.get(id);
						const stats = statsMap.get(id);
						return {
							homework: id,
							status: hasAnalysisByHomeworkId.has(id),
							answerUploaded: upload?.answerUploaded ?? false,
							totalProblems: stats?.totalProblems ?? upload?.totalProblems ?? null,
							avgAttempted: stats
								? Number((stats.attemptedSum / Math.max(stats.count, 1)).toFixed(1))
								: null,
							avgSolved: stats
								? Number((stats.solvedSum / Math.max(stats.count, 1)).toFixed(1))
								: null,
							avgErrors: stats
								? Number((stats.errorSum / Math.max(stats.count, 1)).toFixed(1))
								: null
						};
					});
					merged.sort((a, b) => a.homework.localeCompare(b.homework));

					console.log('[aitutordashboard]-[Summary]-[DataLoaded]:', {
						groupId,
						homeworkCount: merged.length,
						homeworks: merged.map((stat) => ({
							id: stat.homework,
							name: stat.homework,
							status: stat.status,
							answerUploaded: stat.answerUploaded
						}))
					});

					return {
						homeworkStats: merged,
						homeworkRows: nextHomeworkRows.map((row) => ({
							...row,
							modelId: modelIdByHomeworkId.get(row.id) ?? row.modelId,
							topicMapped: topicMappedByHomeworkId.get(row.id) ?? row.topicMapped ?? false
						}))
					};
				}
			});
			if ($aiTutorSelectedGroupId !== groupId) return; // stale — group changed while loading
			console.log('[aitutordashboard]-[Summary]-[HomeworkStatsLoaded]: group=' + groupId, { homeworkCount: snapshot.homeworkRows.length, modelIds: snapshot.homeworkRows.map((r) => r.modelId) });
			applySummarySnapshot(snapshot);
		} catch (error) {
			testToast('Summary failed loading /homework data');
			console.error('Homework fetch failed:', error);
		}

		await tick();
		updateScrollState();
	}

// ── Upload helpers ───────────────────────────────────────────────────
async function loadModels() {
	testToast('Summary fetch: models');
	if (useFrontendTestingData) {
		availableModels = frontendTestingModels;
		return;
	}
	try {
		const res = await fetch('/api/models', {
			headers: { Authorization: `Bearer ${localStorage.token}` }
		});
		if (!res.ok) throw new Error('Models fetch failed');
		const data = await res.json();
		const allMappedModels = Array.isArray(data?.data)
			? data.data.map((m: any) => ({
					id: m.id,
					name: m.name ?? m.id,
					base_model_id: m.info?.base_model_id ?? m.base_model_id ?? null,
					access_control: m.access_control ?? m.info?.access_control ?? null,
					user_id: m.user_id
				}))
			: [];
		const excludedModels: { name: string; reason: string }[] = [];
		availableModels = allMappedModels.filter((model) => {
			if (model.base_model_id == null) {
				excludedModels.push({ name: model.name ?? model.id, reason: 'no base_model_id' });
				return false;
			}
			if (!(model.name ?? model.id).toLowerCase().includes('homework')) {
				excludedModels.push({ name: model.name ?? model.id, reason: 'name missing homework' });
				return false;
			}
			if ((model.name ?? model.id).startsWith('Mastery')) {
				excludedModels.push({ name: model.name ?? model.id, reason: 'Mastery prefix' });
				return false;
			}
			const groupIds = model.access_control?.read?.group_ids ?? [];
			if (groupIds.length > 0 && groupIds.includes($aiTutorSelectedGroupId)) {
				return true;
			}
			excludedModels.push({ name: model.name ?? model.id, reason: 'not assigned to current group' });
			return false;
		});
		console.log('[HomeworkFilter]-[Summary]-[LoadModels]:', {
			all: allMappedModels.map((m) => m.name ?? m.id),
			selected: availableModels.map((m) => m.name ?? m.id),
			excluded: excludedModels
		});
	} catch (e) {
		availableModels = [];
		console.error('Models fetch failed:', e);
	}
}

async function loadConversationCounts(groupId: string) {
	testToast(`Summary fetch: conversations group=${groupId || 'none'}`);
	if (useFrontendTestingData) {
		convCountByModelId = groupId ? frontendTestingConversationCounts : {};
		return;
	}
	if (!groupId) return;
	try {
		// Page: AI Tutor Dashboard Summary
		// Endpoint: POST /api/v1/chats/filter/meta
		// Purpose: count Open WebUI conversations for the selected group, then bucket them by model_id/model_name.
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
		const studentsByModel: Record<string, Set<string>> = {};
		const nextCounts: Record<string, ConversationCount> = {};
		if (Array.isArray(data)) {
			for (const chat of data) {
				const modelKey = chat?.meta?.model_name ?? chat?.meta?.model_id ?? '';
				if (!modelKey) continue;
				if (!studentsByModel[modelKey]) studentsByModel[modelKey] = new Set();
				if (chat.user_id) studentsByModel[modelKey].add(chat.user_id);
				nextCounts[modelKey] = {
					studentCount: studentsByModel[modelKey].size,
					chatCount: (nextCounts[modelKey]?.chatCount ?? 0) + 1
				};
			}
		}
		if ($aiTutorSelectedGroupId !== groupId) return; // stale
		convCountByModelId = nextCounts;
	} catch (e) {
		console.error('Conversation count fetch failed:', e);
	}
}

	async function loadErrorTypes(groupId: string) {
		testToast(`Summary fetch: error types group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			originalErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			draftErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			return;
		}
		if (!groupId) return;
		try {
			const freshErrorTypes = await loadWithAITutorSessionCache({
				key: `summary:${groupId}:error-types`,
				ttlMs: SUMMARY_SESSION_TTL_MS,
				onCached: (cached) => {
					if ($aiTutorSelectedGroupId === groupId) {
						originalErrorTypeDefs = cached;
						draftErrorTypeDefs = cached;
					}
				},
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
			if ($aiTutorSelectedGroupId !== groupId) return; // stale
			originalErrorTypeDefs = freshErrorTypes;
			draftErrorTypeDefs = freshErrorTypes;
		} catch (e) {
			console.error('Error types fetch failed:', e);
		}
	}

async function loadPrompts(groupId: string) {
	testToast(`Summary fetch: prompts group=${groupId || 'none'}`);
	if (useFrontendTestingData) {
		generalPrompts = frontendTestingGeneralPrompts;
		tutorPrompts = groupId ? frontendTestingTutorPrompts.map((p) => ({ ...p, group_id: groupId })) : [];
		return;
	}
	try {
		const freshGeneralPrompts = await loadWithAITutorSessionCache({
			key: 'summary:global:general-prompts',
			ttlMs: SUMMARY_SESSION_TTL_MS,
			onCached: (cached) => {
				if ($aiTutorSelectedGroupId === groupId) generalPrompts = cached;
			},
			loader: async () => {
				const generalRes = await fetch(`${AI_TUTOR_API_BASE}/prompts/general`, {
					headers: { Authorization: `Bearer ${localStorage.token}` }
				});
				if (!generalRes.ok) throw new Error('General prompts fetch failed');
				return await generalRes.json();
			}
		});
		if ($aiTutorSelectedGroupId !== groupId) return; // stale
		generalPrompts = freshGeneralPrompts;
	} catch (e) {
		console.error('General prompts fetch failed:', e);
	}

	if (!groupId) {
		return;
	}

	try {
		const freshTutorPrompts = await loadWithAITutorSessionCache({
			key: `summary:${groupId}:tutor-prompts`,
			ttlMs: SUMMARY_SESSION_TTL_MS,
			onCached: (cached) => {
				if ($aiTutorSelectedGroupId === groupId) tutorPrompts = cached;
			},
			loader: async () => {
				const tutorRes = await fetch(
					`${AI_TUTOR_API_BASE}/prompts/tutor?group_id=${encodeURIComponent(groupId)}`,
					{ headers: { Authorization: `Bearer ${localStorage.token}` } }
				);
				if (!tutorRes.ok) throw new Error('Tutor prompts fetch failed');
				return await tutorRes.json();
			}
		});
		if ($aiTutorSelectedGroupId !== groupId) return; // stale
		tutorPrompts = freshTutorPrompts;
	} catch (e) {
		console.error('Tutor prompts fetch failed:', e);
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

function countHomeworkQuestions(questionData: unknown, topicMapping: unknown) {
	if (topicMapping && typeof topicMapping === 'object' && !Array.isArray(topicMapping)) {
		return Object.keys(topicMapping as Record<string, unknown>).length;
	}

	if (typeof questionData === 'string') {
		const boldMatches = Array.from(questionData.matchAll(/^\*\*(\d+)\.\*\*/gm));
		if (boldMatches.length > 0) return boldMatches.length;
		const plainMatches = Array.from(questionData.matchAll(/^(\d+)\.\s+/gm));
		if (plainMatches.length > 0) return plainMatches.length;
	}

	if (Array.isArray(questionData)) return questionData.length;
	if (questionData && typeof questionData === 'object') return 1;

	return 0;
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

	const POLL_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes max polling

	async function pollPipelineJob(jobId: string, intervalMs: number, label: string) {
		const startTime = Date.now();
		while (true) {
			// Timeout guard: if polling exceeds max duration, abort
			if (Date.now() - startTime > POLL_TIMEOUT_MS) {
				throw new Error(`${label} timed out after ${POLL_TIMEOUT_MS / 60000} minutes.`);
			}
			// Shared async job polling helper.
			// Endpoint: GET /pipeline/status/{job_id}
			const res = await fetch(`${AI_TUTOR_API_BASE}/pipeline/status/${encodeURIComponent(jobId)}`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) throw new Error(await parseErrorDetail(res));
			const data = await res.json();
			testToast(`${label} check | job=${jobId} | status=${data?.status ?? 'unknown'} | step=${data?.step ?? 'unknown'}`);
			if (data?.status === 'done') return data;
			if (data?.status === 'failed') throw new Error(data?.error || `${label} failed.`);
			await sleep(intervalMs);
		}
	}

async function ensureConversationsExported(homeworkId: string, modelId: string | null) {
	if (useFrontendTestingData) return true;
	if (!modelId) {
		toast.error('This homework is missing a model ID.');
		return false;
	}

	exportingConversationMap = { ...exportingConversationMap, [homeworkId]: true };
	testToast(`Export conversations is triggered | page=aitutordashboard - Summary | homework=${homeworkId}`);
	try {
		// Page: AI Tutor Dashboard Summary
		// Endpoint: GET /conversation/?homework_id={homework_id}
		// Purpose: check whether Open WebUI conversation history has already been exported into AI Tutor storage.
		const existingRes = await fetch(
			`${AI_TUTOR_API_BASE}/conversation/?homework_id=${encodeURIComponent(homeworkId)}`,
			{ headers: { Authorization: `Bearer ${localStorage.token}` } }
		);
		if (!existingRes.ok) throw new Error(await parseErrorDetail(existingRes));
		const existing = await existingRes.json();
		if (Array.isArray(existing) && existing.length > 0) {
			testToast(`Conversation export check | homework=${homeworkId} | exported=${existing.length}`);
			return true;
		}

		// Page: AI Tutor Dashboard Summary
		// Endpoint: POST /conversation/export?homework_id={homework_id}
		// Purpose: export group-member conversation history for the homework's group_id + model_id.
		const exportRes = await fetch(
			`${AI_TUTOR_API_BASE}/conversation/export?homework_id=${encodeURIComponent(homeworkId)}`,
			{
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			}
		);
		if (!exportRes.ok) throw new Error(await parseErrorDetail(exportRes));
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

async function validateRunPrerequisites(homeworkId: string) {
	const row = homeworkRows.find((item) => item.id === homeworkId);
	if (!row) {
		toast.error('Select a homework before running analysis.');
		return false;
	}
	if (!$aiTutorSelectedGroupId) {
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
	testToast(`Edit prompt is triggered | page=aitutordashboard - Summary | prompt=${def.name}`);
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
	if (!$aiTutorSelectedGroupId || !selectedPromptName) return;
	if (useFrontendTestingData) {
		if (selectedPromptTutorId) {
			tutorPrompts = tutorPrompts.map((prompt) =>
				prompt.id === selectedPromptTutorId ? { ...prompt, prompt: selectedPromptText, is_active: true } : prompt
			);
		} else {
			tutorPrompts = [
				...tutorPrompts,
				{
					id: `tp-${Date.now()}`,
					name: selectedPromptName,
					group_id: $aiTutorSelectedGroupId,
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
					group_id: $aiTutorSelectedGroupId,
					prompt: selectedPromptText
				})
			});
		}
		clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
		await loadPrompts($aiTutorSelectedGroupId);
		showPromptModal = false;
		testToast('Summary saved prompt override');
	} catch (e) {
		testToast('Summary failed saving prompt override');
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
		clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
		await loadPrompts($aiTutorSelectedGroupId);
		showPromptModal = false;
		testToast('Summary reset prompt to default');
	} catch (e) {
		testToast('Summary failed resetting prompt to default');
		console.error('Prompt reset failed:', e);
	}
}

async function persistErrorTypes() {
	if (!$aiTutorSelectedGroupId) return;
	if (useFrontendTestingData) {
		toast.success('Frontend testing error types saved.');
		aiTutorFrontendTestingErrorTypes.set(draftErrorTypeDefs);
		originalErrorTypeDefs = draftErrorTypeDefs;
		justSavedErrorTypes = true;
		if (saveSuccessTimeout) clearTimeout(saveSuccessTimeout);
		saveSuccessTimeout = setTimeout(() => { justSavedErrorTypes = false; }, 2000);
		return;
	}
	try {
		let saved = false;
		if (draftErrorTypeDefs.length === 0) {
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent($aiTutorSelectedGroupId)}`,
				{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			saved = res.ok;
		} else {
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent($aiTutorSelectedGroupId)}`,
				{
					method: 'PUT',
					headers: {
						'Content-Type': 'application/json',
						Authorization: `Bearer ${localStorage.token}`
					},
					body: JSON.stringify(draftErrorTypeDefs.map((d) => ({ name: d.type, description: d.description })))
				}
			);
			saved = res.ok;
		}
		if (saved) {
			clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
			originalErrorTypeDefs = draftErrorTypeDefs;
			justSavedErrorTypes = true;
			if (saveSuccessTimeout) clearTimeout(saveSuccessTimeout);
			saveSuccessTimeout = setTimeout(() => { justSavedErrorTypes = false; }, 2000);
			testToast('Summary saved error types');
		}
	} catch (e) {
		testToast('Summary failed saving error types');
		console.error('Failed to persist error types:', e);
	}
}

function resetErrorTypesToDefault() {
	if (!$aiTutorSelectedGroupId) return;
	// Draft mode: only update draft, require Save to persist
	draftErrorTypeDefs = AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES.map((et, i) => ({
		...et,
		color: errorTypeColors[i % errorTypeColors.length]
	}));
	testToast('Summary reset to defaults (draft) — Save to persist');
}

function openEditErrorType(index: number) {
	editingErrorTypeIndex = index;
	editingErrorTypeIsNew = false;
	editErrorTypeName = draftErrorTypeDefs[index].type;
	editErrorTypeDescription = draftErrorTypeDefs[index].description;
	showEditErrorTypeModal = true;
}

function addErrorType() {
	if (draftErrorTypeDefs.length >= 4) return;
	const color = errorTypeColors[draftErrorTypeDefs.length % errorTypeColors.length];
	const newDef = { type: 'New Error Type', color, description: '' };
	draftErrorTypeDefs = [...draftErrorTypeDefs, newDef];
	editingErrorTypeIndex = draftErrorTypeDefs.length - 1;
	editingErrorTypeIsNew = true;
	editErrorTypeName = newDef.type;
	editErrorTypeDescription = '';
	showEditErrorTypeModal = true;
}

function saveErrorTypeEdit() {
	if (editingErrorTypeIndex === null) return;
	draftErrorTypeDefs[editingErrorTypeIndex] = {
		...draftErrorTypeDefs[editingErrorTypeIndex],
		type: editErrorTypeName,
		description: editErrorTypeDescription
	};
	draftErrorTypeDefs = [...draftErrorTypeDefs];
	closeErrorTypeModal();
	// Draft mode: don't auto-save, user must click Save button
}

function deleteErrorType() {
	if (editingErrorTypeIndex === null) return;
	draftErrorTypeDefs = draftErrorTypeDefs.filter((_, i) => i !== editingErrorTypeIndex);
	closeErrorTypeModal();
	// Draft mode: don't auto-save, user must click Save button
}

function closeErrorTypeModal() {
	showEditErrorTypeModal = false;
	editingErrorTypeIndex = null;
	editingErrorTypeIsNew = false;
}

function confirmResetDefaults() {
	showResetDefaultsModal = false;
	resetErrorTypesToDefault();
}

async function uploadPdf(hwId: string | null, docType: 'question' | 'answer', modelId: string, file: File, draftUid?: number) {
	testToast(`Upload ${docType} PDF is triggered | page=aitutordashboard - Summary | model=${modelId} | target=${hwId ?? `draft-${draftUid ?? 0}`}`);
	if (!$aiTutorSelectedGroupId && !useFrontendTestingData) {
		toast.error('Select a group before uploading PDFs.');
		return;
	}
	if (file.type !== 'application/pdf') {
		toast.error('Please upload a PDF file.');
		return;
	}
	const key = hwId ? `${hwId}-${docType}` : `draft-${draftUid ?? 0}-${docType}`;
	// Guard against double-click / concurrent upload for the same homework+docType
	if (uploadingMap[key]) {
		console.log('[UPLOAD]-[' + key + ']-[Skipped]: already uploading, ignoring duplicate');
		return;
	}
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
			group_id: $aiTutorSelectedGroupId,
			model_id: modelId
		});
		// Page: AI Tutor Dashboard Summary
		// Endpoint: POST /homework/pdf-to-markdown?doc_type={question|answer}&group_id={group_id}&model_id={model_id}
		// Purpose: create or update the homework row identified by group_id + model_id and start PDF processing.
		const res = await fetch(`${AI_TUTOR_API_BASE}/homework/pdf-to-markdown?${params.toString()}`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${localStorage.token}` },
			body: formData
		});
		if (!res.ok) throw new Error(await parseErrorDetail(res));
		const data = await res.json();
		const jobId = data?.job_id;
		if (!jobId) throw new Error('Upload started but no job ID was returned.');
		toast.success(`${docType === 'question' ? 'Homework' : 'Answer'} upload started.`);
		await pollPipelineJob(jobId, 3000, `${docType} upload`);
		toast.success(`${docType === 'question' ? 'Homework' : 'Answer'} upload completed.`);
		if (hwId === null && draftUid !== undefined) draftRows = draftRows.filter(d => d.uid !== draftUid);
		clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
		await loadHomeworkStats($aiTutorSelectedGroupId);
	} catch (e) {
		toast.error(e instanceof Error ? e.message : 'Upload failed.');
		console.error('PDF upload failed:', e);
	} finally {
		uploadingMap = { ...uploadingMap, [key]: false };
	}
}

// ── Upload event handler factory ─────────────────────────────────────
function addDraftRow() {
	draftRows = [...draftRows, { uid: _nextDraftUid++, modelId: availableModels[0]?.id ?? '' }];
	console.log('[aitutordashboard]-[Summary]-[DraftRowAdded]:', draftRows);
}

function makeUploadHandler(hwId: string | null, docType: 'question' | 'answer', modelId: string | null, draftUid?: number) {
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
type AnalysisRecord = { contents: string; startedAt: string; completedAt: string | null; failed: boolean };
let analysisHistory: AnalysisRecord[] = [];
const homeworkModelNameCellClass =
	'max-w-[12rem] overflow-hidden whitespace-normal break-words leading-4 [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]';
$: latestCompletedRun = analysisHistory.find((record) => !!record.completedAt && !record.failed) ?? null;
$: lastRunStatusClass = latestCompletedRun ? 'bg-green-500' : 'bg-yellow-500';

function getHomeworkNumberLabel(homework: string) {
	return homework.match(/^Homework(\d+)/)?.[1] ?? homework;
}

function getHomeworkModelName(homework: string) {
	// Summary rows are keyed by AI Tutor homework_id, but the UI should always
	// display the originating workspace model name when one is available.
	const homeworkRow = homeworkRows.find((row) => row.id === homework);
	const modelId = homeworkRow?.modelId ?? homework;
	const matchingModel = availableModels.find((model) => model.id === modelId);
	return matchingModel?.name ?? modelId;
}

function getConversationCountDisplay(homeworkId: string) {
	const row = homeworkRows.find((r) => r.id === homeworkId);
	if (!row?.modelId) return '0';
	const keys = new Set<string>();
	keys.add(row.modelId);
	const matchedModel = availableModels.find((model) => model.id === row.modelId);
	if (matchedModel?.name) keys.add(matchedModel.name);
	let maxStudentCount = 0;
	let maxChatCount = 0;
	for (const key of keys) {
		const count = convCountByModelId[key];
		if (count && count.studentCount > maxStudentCount) {
			maxStudentCount = count.studentCount;
			maxChatCount = count.chatCount;
		}
	}
	if (maxStudentCount === 0) return '0';
	return `${maxStudentCount} (${maxChatCount} chats)`;
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
	return homeworkStats
		.filter((stat) => selectedRunHomeworks.has(stat.homework))
		.map((stat) => getHomeworkNumberLabel(stat.homework))
		.join(',');
}

$: runHomeworkSummary = getRunHomeworkSummary();

async function runAnalysis() {
	testToast(`Run analysis is triggered | page=aitutordashboard - Summary | selected=${getRunHomeworkSummary()}`);
	const contents = getRunHomeworkSummary();
	if (!contents || contents === 'No homework') return;
	const targetHomeworkId = selectedHwForRun || Array.from(selectedRunHomeworks)[0] || '';
	if (!targetHomeworkId) {
		toast.error('Select a homework before running analysis.');
		return;
	}
	const ready = await validateRunPrerequisites(targetHomeworkId);
	if (!ready) return;
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
		// Page: AI Tutor Dashboard Summary
		// Endpoint: POST /analysis/run?homework_id={homework_id}
		// Purpose: start the analysis pipeline for the selected homework after prerequisite checks pass.
		const res = await fetch(
			`${AI_TUTOR_API_BASE}/analysis/run?group_id=${encodeURIComponent($aiTutorSelectedGroupId)}&homework_id=${encodeURIComponent(targetHomeworkId)}`,
			{ method: 'POST', headers: { Authorization: `Bearer ${localStorage.token}` } }
		);
		if (res.ok) {
			const data = await res.json();
			const jobId = data?.job_id;
			if (!jobId) throw new Error('Analysis started but no job ID was returned.');
			testToast('Summary run analysis request submitted');
			toast.success('Analysis started successfully.');
			await pollPipelineJob(jobId, 10000, 'analysis run');
			toast.success('Analysis completed.');
			analysisHistory = [{ contents, startedAt, completedAt: new Date().toLocaleTimeString(), failed: false }, ...analysisHistory];
			clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
			await loadHomeworkStats($aiTutorSelectedGroupId);
		} else {
			toast.error(await parseErrorDetail(res));
			analysisHistory = [{ contents, startedAt, completedAt: null, failed: true }, ...analysisHistory];
		}
	} catch (e) {
		toast.error(e instanceof Error ? e.message : 'Analysis request failed.');
		console.error('Run analysis failed:', e);
		analysisHistory = [{ contents, startedAt, completedAt: null, failed: true }, ...analysisHistory];
	} finally {
		clearInterval(stepTimer);
		runStep = '';
		runningAnalysis = false;
		runningAnalysisByHomeworkId = { ...runningAnalysisByHomeworkId, [targetHomeworkId]: false };
	}
}
</script>

<div class="flex flex-col space-y-24 py-4">

	<!-- Status Section NOT IN USE -->
	<!-- <div class="rounded-lg bg-gray-100 px-3 py-2 text-xs text-gray-800 dark:bg-gray-800/80 dark:text-gray-300">
		<div class="flex flex-wrap items-center gap-x-6 gap-y-2">
			<div>Students&apos; conversation history are on {bannerPlaceholderTime}</div>
			<div>Configuration updated on {bannerPlaceholderTime}</div>
			<div class="flex items-center gap-2">
				<span>Last Run completed on {bannerPlaceholderTime}</span>
				<span class="h-2 w-2 rounded-full {lastRunStatusClass}"></span>
			</div>
		</div>
	</div> -->

	<!-- [Standard Section: Charts Summary] -->
	<div class="space-y-4">
		<h2 class="text-2xl font-semibold text-gray-800 dark:text-gray-200">Charts Summary</h2>

		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div class="relative">
			<!-- Charts Container -->
			<div class="w-full">
				<div class="w-full flex flex-col">
					<div class="flex items-center gap-4 mb-1">
						<p class="text-xs font-medium text-gray-600 dark:text-gray-300">Average Problems Solved vs Attempted</p>
						<div class="flex items-center gap-3 text-xs">
							<div class="flex items-center gap-1">
								<span class="inline-block w-3 h-0.5 rounded bg-[#7CB9E8]"></span>
								<span class="text-gray-600 dark:text-gray-300">Solved</span>
							</div>
							<div class="flex items-center gap-1">
								<span class="inline-block w-3 h-0.5 rounded bg-[#A792D0]"></span>
								<span class="text-gray-600 dark:text-gray-300">Attempted</span>
							</div>
						</div>
					</div>
						{#if combinedChart}
							<div
								class="relative w-full h-[200px] my-2"
								bind:clientWidth={chartWidth}
								on:mousemove={(e) => {
									if (!combinedChart) return;
									const rect = e.currentTarget.getBoundingClientRect();
									const mouseX = e.clientX - rect.left;
									const mouseY = e.clientY - rect.top;
									const svgX = (mouseX / rect.width) * W;
									const n = homeworkStats.length;
									if (n === 0) return;
									let nearestIndex = -1;
									let minDist = Infinity;
									for (let i = 0; i < n; i++) {
										const slotX = combinedChart.px(i);
										const dist = Math.abs(slotX - svgX);
										if (dist < minDist) {
											minDist = dist;
											nearestIndex = i;
										}
									}
									const slotWidth = (W - padL - padR) / Math.max(1, combinedChart.slotCount - 1);
									if (nearestIndex >= 0 && minDist < slotWidth * 0.6) {
										const stat = homeworkStats[nearestIndex];
										const slotXPixel = (combinedChart.px(nearestIndex) / W) * rect.width;
										const dot1 = combinedChart.dots1.find((d) => Math.abs(d.x - combinedChart.px(nearestIndex)) < 0.5);
										const dot2 = combinedChart.dots2.find((d) => Math.abs(d.x - combinedChart.px(nearestIndex)) < 0.5);
										const tooltipWidth = 160;
										let align = 'center';
										if (slotXPixel < tooltipWidth / 2) align = 'left';
										else if (slotXPixel > rect.width - tooltipWidth / 2) align = 'right';
										chartTooltip = {
											visible: true,
											x: slotXPixel,
											y: mouseY,
											align,
											label: stat ? getHomeworkModelName(stat.homework) : '',
											solved: dot1?.v ?? null,
											attempted: dot2?.v ?? null
										};
									} else {
										chartTooltip.visible = false;
									}
								}}
								on:mouseleave={() => chartTooltip.visible = false}
							>
								{#if chartTooltip.visible}
									<div
										class="absolute z-50 pointer-events-none"
										style:left="{chartTooltip.x}px" style:top="{chartTooltip.y}px" style:transform="{chartTooltip.align === `left` ? `translate(0%, -110%)` : chartTooltip.align === `right` ? `translate(-100%, -110%)` : `translate(-50%, -110%)`}"
									>
										<div class="rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-lg dark:border-gray-700 dark:bg-gray-800 min-w-[10rem]">
											<div class="text-xs font-semibold text-gray-800 dark:text-gray-100 mb-1.5 truncate max-w-[12rem]">{chartTooltip.label}</div>
											<div class="flex items-center gap-2 text-xs mb-0.5">
												<span class="inline-block w-2 h-2 rounded-full bg-[#7CB9E8]"></span>
												<span class="text-gray-600 dark:text-gray-300">Solved: {chartTooltip.solved !== null ? chartTooltip.solved : '-'}</span>
											</div>
											<div class="flex items-center gap-2 text-xs">
												<span class="inline-block w-2 h-2 rounded-full bg-[#A792D0]"></span>
												<span class="text-gray-600 dark:text-gray-300">Attempted: {chartTooltip.attempted !== null ? chartTooltip.attempted : '-'}</span>
											</div>
										</div>
									</div>
								{/if}
								<svg viewBox="0 0 {W} {H}" class="w-full h-full">
								<!-- Plot area background -->
								<rect x={padL} y={padT} width={W - padL - padR} height={H - padT - padB} rx="4" class="text-gray-50 dark:text-gray-850" fill="currentColor" />
								<!-- Horizontal grid lines -->
								{#each combinedChart.yTicks as tick}
									<line x1={padL} y1={combinedChart.py(tick)} x2={W - padR} y2={combinedChart.py(tick)}
										stroke="currentColor" stroke-width="0.5" class="text-gray-200 dark:text-gray-700" />
								{/each}
								<!-- X-axis labels -->
								{#each combinedChart.xLabels as lbl, i}
									{#if i % combinedChart.labelStep === 0}
										<text x={lbl.x} y={H - padB + 14} text-anchor="middle" font-size="9" class="fill-gray-500 dark:fill-gray-400">
											{#each lbl.label.split('\n') as line, lineIndex}
												<tspan x={lbl.x} dy={lineIndex === 0 ? 0 : 11}>{line}</tspan>
											{/each}
										</text>
									{/if}
								{/each}
								<!-- Y-axis labels -->
								{#each combinedChart.yTicks as tick}
									<text x={padL - 8} y={combinedChart.py(tick) + 3} text-anchor="end" font-size="9"
										class="fill-gray-500 dark:fill-gray-400">{tick}</text>
								{/each}
								<!-- Axes -->
								<line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke="currentColor" stroke-width="1.5" class="text-gray-400 dark:text-gray-500" />
								<line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="currentColor" stroke-width="1.5" class="text-gray-400 dark:text-gray-500" />
								<!-- Y-axis label -->
								<text x={14} y={H / 2} text-anchor="middle" font-size="9" font-weight="500" class="fill-gray-500 dark:fill-gray-400"
									transform="rotate(-90, 14, {H / 2})">Problems</text>
								<!-- X-axis label -->
								<text x={(padL + W - padR) / 2} y={H - 4} text-anchor="middle" font-size="9" font-weight="500" class="fill-gray-500 dark:fill-gray-400">Homework</text>
								<!-- Line 1: Solved -->
								<path d={combinedChart.pathD1} fill="none" stroke="#7CB9E8" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />
								<!-- Line 2: Attempted -->
								<path d={combinedChart.pathD2} fill="none" stroke="#A792D0" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />
								<!-- Dots 1 -->
								{#each combinedChart.dots1 as dot}
									<circle cx={dot.x} cy={dot.y} r="4" fill="white" stroke="#7CB9E8" stroke-width="2" />
								{/each}
								<!-- Dots 2 -->
								{#each combinedChart.dots2 as dot}
									<circle cx={dot.x} cy={dot.y} r="4" fill="white" stroke="#A792D0" stroke-width="2" />
								{/each}
								</svg>
							</div>
					{:else}
						<div class="w-full h-[200px] flex items-center justify-center">
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 text-gray-300 dark:text-gray-600">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
							</svg>
						</div>
					{/if}
				</div>
			</div>
		</div>
		</div>
	</div>

	<!-- [Standard Section: Statistics] -->
	<div class="space-y-4">
		<h2 class="text-2xl font-semibold text-gray-800 dark:text-gray-200">Statistics</h2>

		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div class="scrollbar-hidden relative overflow-x-auto rounded-sm pt-0.5">
				<table bind:this={mainTableEl} class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
				<thead class="text-xs text-gray-700 uppercase bg-[#EEE6F3] dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						{#each [
							{ key: 'homework',     label: 'Homework', sortable: true },
							{ key: null,           label: 'Students Interacted', sortable: false },
							{ key: 'totalProblems', label: 'Total Number of Questions', sortable: true },
							{ key: 'avgAttempted',   label: 'Avg Attempted', sortable: true },
							{ key: 'avgSolved',      label: 'Avg Solved', sortable: true },
							{ key: 'avgErrors',      label: 'Avg Errors', sortable: true }
						] as col, i}
							<th scope="col" class="relative overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 select-none {col.sortable ? 'cursor-pointer' : ''}" style="width: {$mainColWidths[i]}%" on:click={col.sortable ? () => setSortKey(col.key) : undefined}>
								<div class="flex gap-1.5 items-center">
									{col.label}
									{#if col.sortable && sortKey === col.key}
										<span class="font-normal">
											{#if sortOrder === 'asc'}<ChevronUp className="size-3" />{:else}<ChevronDown className="size-3" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-3" /></span>
									{/if}
								</div>
								<span role="separator" aria-label="Resize column" class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[#57068C] dark:hover:bg-[#B588FF] z-10" on:mousedown|preventDefault={(e) => initMainColResize(e, mainTableEl, i)} />
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#if sortedStats.length === 0}
						{console.log('[dashboard] Statistics table empty')}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td class="px-3 py-12 text-center text-gray-400 dark:text-gray-500"><span>—</span></td>
							<td class="px-3 py-12 text-center text-gray-400 dark:text-gray-500"><span>—</span></td>
							<td class="px-3 py-12 text-center text-gray-400 dark:text-gray-500"><span>—</span></td>
							<td class="px-3 py-12 text-center text-gray-400 dark:text-gray-500"><span>—</span></td>
							<td class="px-3 py-12 text-center text-gray-400 dark:text-gray-500"><span>—</span></td>
							<td class="px-3 py-12 text-center text-gray-400 dark:text-gray-500"><span>—</span></td>
						</tr>
					{:else}
						{#each sortedStats as stat}
							<tr class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition">
								<td class="px-3 py-1 font-medium text-gray-900 dark:text-white">
									<div class={homeworkModelNameCellClass}>{getHomeworkModelName(stat.homework)}</div>
								</td>
								<td class="px-3 py-1">{getConversationCountDisplay(stat.homework)}</td>
								<td class="px-3 py-1">{stat.totalProblems ?? 'N/A'}</td>
								<td class="px-3 py-1">{stat.avgAttempted != null ? stat.avgAttempted.toFixed(1) : 'N/A'}</td>
								<td class="px-3 py-1">{stat.avgSolved != null ? stat.avgSolved.toFixed(1) : 'N/A'}</td>
								<td class="px-3 py-1">{stat.avgErrors != null ? stat.avgErrors.toFixed(1) : 'N/A'}</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
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
			<div class="text-base font-semibold text-gray-900 dark:text-gray-100">Use default error types?</div>
			<p class="mt-3 text-sm text-gray-500 dark:text-gray-400">
				This will replace the current error types with the default set.
			</p>
			<div class="mt-6 flex justify-end gap-2">
				<button
					class="px-3 py-1.5 text-sm text-gray-600 transition hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
					on:click={() => (showResetDefaultsModal = false)}
				>
					Cancel
				</button>
				<button
					class="px-3 py-1.5 text-sm font-medium text-[#57068C] transition hover:text-[#702B9D] dark:text-purple-400 dark:hover:text-purple-300"
					on:click={confirmResetDefaults}
				>
					Confirm
				</button>
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
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
						<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
					</svg>
				</button>
			</div>

			<hr class="border-gray-100 dark:border-gray-700 mb-5" />

			<div class="mb-4">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Name</label>
				<input
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
					bind:value={editErrorTypeName}
					placeholder="Error type name"
				/>
			</div>

			<div class="mb-6">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Description</label>
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
						on:click={deleteErrorType}
					>Delete</button>
				{:else}
					<div></div>
				{/if}
				<div class="flex gap-2">
					<button
						class="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition"
						on:click={closeErrorTypeModal}
					>Cancel</button>
					<button
						class="px-3 py-1.5 text-sm font-medium text-[#57068C] hover:text-[#702B9D] dark:text-purple-400 dark:hover:text-purple-300 transition"
						on:click={saveErrorTypeEdit}
					>Save</button>
				</div>
			</div>
		</div>
	</div>
{/if}
{#if showPromptModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		on:click|self={() => (showPromptModal = false)}
		role="dialog"
		aria-modal="true"
	>
		<div class="bg-white dark:bg-gray-900 rounded-xl shadow-2xl p-6 w-[760px] max-w-[90vw]">
			<div class="flex justify-between items-center mb-5">
				<div>
					<h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">{selectedPromptLabel}</h3>
					<div class="text-xs text-gray-400 dark:text-gray-500 mt-1">{selectedPromptUsedFor}</div>
				</div>
				<button
					class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
					on:click={() => (showPromptModal = false)}
					aria-label="Close"
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
						<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
					</svg>
				</button>
			</div>

			<hr class="border-gray-100 dark:border-gray-700 mb-5" />

			<div class="mb-4 flex items-center gap-2 text-xs">
				<span class="text-gray-500 dark:text-gray-400">Scope:</span>
				<span class="rounded px-2 py-1 bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
					{selectedPromptScope === 'override' ? 'Class Override' : 'Default'}
				</span>
			</div>

			<div class="mb-6">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Prompt</label>
				<textarea
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none font-mono"
					rows="18"
					bind:value={selectedPromptText}
				></textarea>
			</div>

			<div class="flex justify-between items-center">
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
						class="px-3 py-1.5 text-sm font-medium text-[#57068C] hover:text-[#702B9D] dark:text-purple-400 dark:hover:text-purple-300 transition"
						on:click={savePromptOverride}
					>
						Save as Class Prompt
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

	<!-- Bottom Spacer -->
	<div class="h-[20vh]"></div>
</div>

<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
	.scrollbar-none::-webkit-scrollbar { display: none; }
	.scrollbar-none { -ms-overflow-style: none; scrollbar-width: none; }
</style>
