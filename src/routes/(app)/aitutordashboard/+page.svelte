<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES, AI_TUTOR_FRONTEND_TESTING_MODE, TESTING_AI_TUTOR } from '$lib/constants';
	import { aiTutorFrontendTestingErrorTypes } from '$lib/stores';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';
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

	let homeworkRows: HomeworkRow[] = [];
	let availableModels: { id: string; name: string }[] = [];
	let convCountByModelId: Record<string, number> = {};
	let uploadingMap: Record<string, boolean> = {};
	let exportingConversationMap: Record<string, boolean> = {};
	let runningAnalysisByHomeworkId: Record<string, boolean> = {};
	type DraftRow = { uid: number; modelId: string };
	let draftRows: DraftRow[] = [];
	let _nextDraftUid = 0;
	let errorTypeDefs: { type: string; color: string; description: string }[] = [];
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
	const frontendTestingConversationCounts: Record<string, number> = {
		[frontendTestingHomeworkModelNames[0]]: 42,
		[frontendTestingHomeworkModelNames[1]]: 27,
		[frontendTestingHomeworkModelNames[2]]: 11,
		[frontendTestingHomeworkModelNames[3]]: 18
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
	let selectedGroupId = '';

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
	const W = 300, H = 180, padL = 38, padR = 12, padT = 12, padB = 32;

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
		const name = stat.homework;
		const m = name.match(/\d+/);
		return m ? `HW${m[0]}` : `${i + 1}`;
	}

	$: avgSolvedChart = chartPoints(homeworkStats.map((s) => s.avgSolved));
	$: avgAttemptedChart = chartPoints(homeworkStats.map((s) => s.avgAttempted));
	$: selectedGroupId = $page.url.searchParams.get('group_id') || '';

	// ── Data fetching ─────────────────────────────────────────────────────────
	onMount(async () => {
		testToast(`loading aitutordashboard - Summary | group=${selectedGroupId || 'none'} | frontend_testing=${String(useFrontendTestingData)}`);
		await loadModels();
		await loadErrorTypes(selectedGroupId);
		if (useFrontendTestingData) {
			seedDummyDashboard(selectedGroupId);
			await tick();
			updateScrollState();
			return;
		}
	});

	$: if (!useFrontendTestingData) {
		void loadHomeworkStats(selectedGroupId);
	}

	$: if (!useFrontendTestingData) {
		void loadConversationCounts(selectedGroupId);
	}

	$: if (!useFrontendTestingData) {
		void loadErrorTypes(selectedGroupId);
	}

	$: if (!useFrontendTestingData) {
		void loadPrompts(selectedGroupId);
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
			homeworkStats = [];
			await tick();
			updateScrollState();
			return;
		}

		const uploadStatusMap = new Map<string, { status: boolean; answerUploaded: boolean }>();
		const topicMappedByHomeworkId = new Map<string, boolean>();
		const modelIdByHomeworkId = new Map<string, string | null>();
		try {
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
				homeworkRows = hwData.map((hw: any) => ({
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
			testToast('Summary loaded /homework data');
		} catch (error) {
			testToast('Summary failed loading /homework data');
			console.error('Homework fetch failed:', error);
		}

		const statsMap = new Map<string, {
			totalProblems: number; attemptedSum: number; solvedSum: number; errorSum: number; count: number;
		}>();
		const hasAnalysisByHomeworkId = new Set<string>();

		for (const homeworkId of uploadStatusMap.keys()) {
			try {
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
						const prev = statsMap.get(id) ?? { totalProblems: 0, attemptedSum: 0, solvedSum: 0, errorSum: 0, count: 0 };
						prev.totalProblems = Math.max(prev.totalProblems, Number(row?.total_question ?? 0));
						prev.attemptedSum += Number(row?.total_attempted ?? 0);
						prev.solvedSum += Number(row?.total_solved ?? 0);
						prev.errorSum += Number(row?.total_errors ?? 0);
						prev.count += 1;
						statsMap.set(id, prev);
					}
				}
			} catch (error) {
				console.error('Analysis fetch failed:', error);
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
				totalProblems: stats ? stats.totalProblems : null,
				avgAttempted: stats ? Number((stats.attemptedSum / Math.max(stats.count, 1)).toFixed(1)) : null,
				avgSolved: stats ? Number((stats.solvedSum / Math.max(stats.count, 1)).toFixed(1)) : null,
				avgErrors: stats ? Number((stats.errorSum / Math.max(stats.count, 1)).toFixed(1)) : null
			};
		});
		merged.sort((a, b) => a.homework.localeCompare(b.homework));
		homeworkStats = merged;
		homeworkRows = homeworkRows.map((row) => ({
			...row,
			modelId: modelIdByHomeworkId.get(row.id) ?? row.modelId,
			topicMapped: topicMappedByHomeworkId.get(row.id) ?? row.topicMapped ?? false
		}));
		if (homeworkStats.length > 0 && selectedRunHomeworks.size === 0) {
			selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
			syncRunSelectionFlags();
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
		availableModels = Array.isArray(data?.data)
			? data.data.map((m: any) => ({ id: m.id, name: m.name ?? m.id }))
			: [];

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
	if (!groupId) { convCountByModelId = {}; return; }
	try {
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
		const counts: Record<string, number> = {};
		if (Array.isArray(data)) {
			for (const chat of data) {
				const modelId = chat?.meta?.model_name ?? chat?.meta?.model_id ?? '';
				if (modelId) counts[modelId] = (counts[modelId] ?? 0) + 1;
			}
		}
		convCountByModelId = counts;
	} catch (e) {
		convCountByModelId = {};
		console.error('Conversation count fetch failed:', e);
	}
}

async function loadErrorTypes(groupId: string) {
	testToast(`Summary fetch: error types group=${groupId || 'none'}`);
	if (useFrontendTestingData) {
		errorTypeDefs = $aiTutorFrontendTestingErrorTypes;
		return;
	}
	if (!groupId) {
		errorTypeDefs = [];
		return;
	}
	try {
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
		errorTypeDefs = errorTypes.slice(0, 4).map((et: any, i: number) => ({
			type: et.name ?? 'Unknown',
			color: errorTypeColors[i % errorTypeColors.length],
			description: et.description ?? ''
		}));
	} catch (e) {
		errorTypeDefs = [];
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
		const generalRes = await fetch(`${AI_TUTOR_API_BASE}/prompts/general`, {
			headers: { Authorization: `Bearer ${localStorage.token}` }
		});
		if (!generalRes.ok) throw new Error('General prompts fetch failed');
		generalPrompts = await generalRes.json();
	} catch (e) {
		generalPrompts = [];
		console.error('General prompts fetch failed:', e);
	}

	if (!groupId) {
		tutorPrompts = [];
		return;
	}

	try {
		const tutorRes = await fetch(
			`${AI_TUTOR_API_BASE}/prompts/tutor?group_id=${encodeURIComponent(groupId)}`,
			{ headers: { Authorization: `Bearer ${localStorage.token}` } }
		);
		if (!tutorRes.ok) throw new Error('Tutor prompts fetch failed');
		tutorPrompts = await tutorRes.json();
	} catch (e) {
		tutorPrompts = [];
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

async function pollPipelineJob(jobId: string, intervalMs: number, label: string) {
	while (true) {
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
	if (!selectedGroupId || !selectedPromptName) return;
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
		await loadPrompts(selectedGroupId);
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
		await loadPrompts(selectedGroupId);
		showPromptModal = false;
		testToast('Summary reset prompt to default');
	} catch (e) {
		testToast('Summary failed resetting prompt to default');
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
				body: JSON.stringify(errorTypeDefs.map((d) => ({ name: d.type, description: d.description })))
			}
		);
		if (res.ok) testToast('Summary saved error types');
	} catch (e) {
		testToast('Summary failed saving error types');
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
		await loadErrorTypes(selectedGroupId);
		testToast('Summary reset error types to default');
	} catch (e) {
		testToast('Summary failed resetting error types');
		console.error('Failed to reset error types:', e);
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
	await resetErrorTypesToDefault();
}

async function uploadPdf(hwId: string | null, docType: 'question' | 'answer', modelId: string, file: File, draftUid?: number) {
	testToast(`Upload ${docType} PDF is triggered | page=aitutordashboard - Summary | model=${modelId} | target=${hwId ?? `draft-${draftUid ?? 0}`}`);
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
		await loadHomeworkStats(selectedGroupId);
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
	console.log('[addDraftRow] draftRows now:', draftRows);
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
	// homework name is now homework model name
	return homework;
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
		const res = await fetch(
			`${AI_TUTOR_API_BASE}/analysis/run?homework_id=${encodeURIComponent(targetHomeworkId)}`,
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
			await loadHomeworkStats(selectedGroupId);
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

<div class="flex flex-col space-y-6 py-4">

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

	<!-- Charts Summary Section -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Charts Summary</h2>

		<div class="relative">
			<!-- Scroll Left — only when content overflows and scrolled right -->
			{#if canScrollLeft}
				<button
					class="absolute left-0 top-1/2 -translate-y-1/2 z-10 bg-white dark:bg-gray-800 rounded-full p-2 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition"
					on:click={() => scrollCharts('left')}
					aria-label="Scroll left"
				>
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
					</svg>
				</button>
			{/if}

			<!-- Charts Container -->
			<div
				bind:this={chartsContainer}
				class="flex gap-4 overflow-x-auto scrollbar-none snap-x snap-mandatory {canScrollLeft ? 'pl-10' : ''} {canScrollRight ? 'pr-10' : ''}"
				style="scroll-behavior: smooth;"
				on:scroll={updateScrollState}
			>
				<!-- Chart 1: Avg Solved -->
				<div class="flex-none w-80 h-64 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg snap-start p-3 flex flex-col">
					<p class="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">Average Problems Solved</p>
					{#if avgSolvedChart}
						<svg viewBox="0 0 {W} {H}" class="w-full flex-1" preserveAspectRatio="none">
							<!-- Grid lines -->
							{#each avgSolvedChart.yTicks as tick}
								<line x1={padL} y1={avgSolvedChart.py(tick)} x2={W - padR} y2={avgSolvedChart.py(tick)}
									stroke="currentColor" stroke-width="0.5" class="text-gray-200 dark:text-gray-600" stroke-dasharray="3,3" />
								<text x={padL - 4} y={avgSolvedChart.py(tick) + 4} text-anchor="end" font-size="9"
									class="fill-gray-400 dark:fill-gray-500">{tick}</text>
							{/each}
							<!-- X-axis labels (every other one if many) -->
							{#each avgSolvedChart.xLabels as lbl, i}
								{#if avgSolvedChart.xLabels.length <= 6 || i % 2 === 0}
									<text x={lbl.x} y={H - padB + 14} text-anchor="middle" font-size="9"
										class="fill-gray-400 dark:fill-gray-500">{lbl.label}</text>
								{/if}
							{/each}
							<!-- Axes -->
							<line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke="currentColor" stroke-width="1" class="text-gray-300 dark:text-gray-600" />
							<line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="currentColor" stroke-width="1" class="text-gray-300 dark:text-gray-600" />
							<!-- Line -->
							<path d={avgSolvedChart.pathD} fill="none" stroke="#7CB9E8" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
							<!-- Dots -->
							{#each avgSolvedChart.dots as dot}
								<circle cx={dot.x} cy={dot.y} r="3" fill="#7CB9E8" />
							{/each}
						</svg>
					{:else}
						<div class="flex-1 flex items-center justify-center">
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 text-gray-300 dark:text-gray-600">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
							</svg>
						</div>
					{/if}
				</div>

				<!-- Chart 2: Avg Attempted -->
				<div class="flex-none w-80 h-64 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg snap-start p-3 flex flex-col">
					<p class="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">Average Problems Attempted</p>
					{#if avgAttemptedChart}
						<svg viewBox="0 0 {W} {H}" class="w-full flex-1" preserveAspectRatio="none">
							{#each avgAttemptedChart.yTicks as tick}
								<line x1={padL} y1={avgAttemptedChart.py(tick)} x2={W - padR} y2={avgAttemptedChart.py(tick)}
									stroke="currentColor" stroke-width="0.5" class="text-gray-200 dark:text-gray-600" stroke-dasharray="3,3" />
								<text x={padL - 4} y={avgAttemptedChart.py(tick) + 4} text-anchor="end" font-size="9"
									class="fill-gray-400 dark:fill-gray-500">{tick}</text>
							{/each}
							{#each avgAttemptedChart.xLabels as lbl, i}
								{#if avgAttemptedChart.xLabels.length <= 6 || i % 2 === 0}
									<text x={lbl.x} y={H - padB + 14} text-anchor="middle" font-size="9"
										class="fill-gray-400 dark:fill-gray-500">{lbl.label}</text>
								{/if}
							{/each}
							<line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke="currentColor" stroke-width="1" class="text-gray-300 dark:text-gray-600" />
							<line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="currentColor" stroke-width="1" class="text-gray-300 dark:text-gray-600" />
							<path d={avgAttemptedChart.pathD} fill="none" stroke="#A792D0" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
							{#each avgAttemptedChart.dots as dot}
								<circle cx={dot.x} cy={dot.y} r="3" fill="#A792D0" />
							{/each}
						</svg>
					{:else}
						<div class="flex-1 flex items-center justify-center">
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 text-gray-300 dark:text-gray-600">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
							</svg>
						</div>
					{/if}
				</div>
			</div>

			<!-- Scroll Right — only when content overflows -->
			{#if canScrollRight}
				<button
					class="absolute right-0 top-1/2 -translate-y-1/2 z-10 bg-white dark:bg-gray-800 rounded-full p-2 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition"
					on:click={() => scrollCharts('right')}
					aria-label="Scroll right"
				>
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5">
						<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
					</svg>
				</button>
			{/if}
		</div>
	</div>

	<!-- Statistics Section -->
	<div class="space-y-2">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Statistics</h2>

		<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
			<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
				<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						{#each [
							{ key: 'homework',     label: 'Homework' },
							{ key: 'status',       label: 'Status' },
							{ key: 'answerUploaded', label: 'Answer' },
							{ key: 'totalProblems',  label: 'Total' },
							{ key: 'avgAttempted',   label: 'Avg Attempted' },
							{ key: 'avgSolved',      label: 'Avg Solved' },
							{ key: 'avgErrors',      label: 'Avg Errors' }
						] as col}
							<th scope="col" class="px-3 py-1.5 cursor-pointer select-none {col.key === 'homework' ? 'w-[12rem]' : ''}" on:click={() => setSortKey(col.key)}>
								<div class="flex gap-1.5 items-center">
									{col.label}
									{#if sortKey === col.key}
										<span class="font-normal">
											{#if sortOrder === 'asc'}<ChevronUp className="size-2" />{:else}<ChevronDown className="size-2" />{/if}
										</span>
									{:else}
										<span class="invisible"><ChevronUp className="size-2" /></span>
									{/if}
								</div>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#if sortedStats.length === 0}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								No data available
							</td>
						</tr>
					{:else}
						{#each sortedStats as stat}
							<tr class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs border-t border-gray-100 dark:border-gray-850">
								<td class="px-3 py-1 font-medium text-gray-900 dark:text-white">
									<div class={homeworkModelNameCellClass}>{getHomeworkModelName(stat.homework)}</div>
								</td>
								<td class="px-3 py-1">
									{#if stat.status}
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 text-green-600 dark:text-green-400">
											<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
										</svg>
									{/if}
								</td>
								<td class="px-3 py-1">
									{#if stat.answerUploaded}
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 text-green-600 dark:text-green-400">
											<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
										</svg>
									{/if}
								</td>
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
					class="px-3 py-1.5 text-sm font-medium text-gray-900 transition hover:text-black dark:text-gray-100 dark:hover:text-white"
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
						class="px-3 py-1.5 text-sm font-medium text-gray-900 dark:text-gray-100 hover:text-black dark:hover:text-white transition"
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


<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
	.scrollbar-none::-webkit-scrollbar { display: none; }
	.scrollbar-none { -ms-overflow-style: none; scrollbar-width: none; }
</style>
