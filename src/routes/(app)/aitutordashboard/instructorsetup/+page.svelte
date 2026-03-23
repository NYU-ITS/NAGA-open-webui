<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { AI_TUTOR_DUMMY_ERROR_TYPES, AI_TUTOR_DUMMY_MODE, TESTING_AI_TUTOR } from '$lib/constants';
	import { aiTutorDummyErrorTypes } from '$lib/stores';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';

	// ── Global flag ───────────────────────────────────────────────────────────
	const useOldData = AI_TUTOR_DUMMY_MODE;

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
		questionFileName?: string | null;
		answerFileName?: string | null;
	};

	let homeworkRows: HomeworkRow[] = [];
	let availableModels: { id: string; name: string }[] = [];
	let convCountByModelId: Record<string, number> = {};
let uploadingMap: Record<string, boolean> = {};
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
		{ homework: 'Homework 1', status: false, answerUploaded: false, totalProblems: 15, avgAttempted: 14.2, avgSolved: 12.8, avgErrors: 1.4 },
		{ homework: 'Homework 2', status: false, answerUploaded: false, totalProblems: 18, avgAttempted: 16.5, avgSolved: 14.9, avgErrors: 1.6 },
		{ homework: 'Homework 3', status: false, answerUploaded: false, totalProblems: 20, avgAttempted: 18.7, avgSolved: 16.2, avgErrors: 2.5 },
		{ homework: 'Homework 4', status: false, answerUploaded: false, totalProblems: 16, avgAttempted: 15.1, avgSolved: 13.4, avgErrors: 1.7 },
		{ homework: 'Homework 5', status: false, answerUploaded: false, totalProblems: 22, avgAttempted: 20.3, avgSolved: 18.1, avgErrors: 2.2 },
		{ homework: 'Homework 6', status: false, answerUploaded: false, totalProblems: 19, avgAttempted: 17.8, avgSolved: 15.6, avgErrors: 2.2 },
		{ homework: 'Homework 7', status: false, answerUploaded: false, totalProblems: 17, avgAttempted: 16.2, avgSolved: 14.5, avgErrors: 1.7 },
		{ homework: 'Homework 8', status: false, answerUploaded: false, totalProblems: 21, avgAttempted: 19.4, avgSolved: 17.2, avgErrors: 2.2 },
		{ homework: 'Homework 9', status: false, answerUploaded: false, totalProblems: 23, avgAttempted: 21.1, avgSolved: 18.9, avgErrors: 2.2 }
	];
	const dummyHomeworkRows: HomeworkRow[] = [
		{
			id: 'Homework 1',
			modelId: 'gpt-4o-mini',
			questionUploaded: true,
			answerUploaded: true,
			questionFileName: 'homework_1_questions.pdf',
			answerFileName: 'homework_1_answers.pdf'
		},
		{
			id: 'Homework 2',
			modelId: 'gpt-4o-mini',
			questionUploaded: true,
			answerUploaded: false,
			questionFileName: 'homework_2_questions.pdf',
			answerFileName: null
		},
		{
			id: 'Homework 3',
			modelId: 'claude-3-5-sonnet',
			questionUploaded: true,
			answerUploaded: true,
			questionFileName: 'homework_3_questions.pdf',
			answerFileName: 'homework_3_answers.pdf'
		},
		{
			id: 'Homework 4',
			modelId: 'claude-3-5-sonnet',
			questionUploaded: false,
			answerUploaded: false,
			questionFileName: null,
			answerFileName: null
		}
	];
	const dummyModels = [
		{ id: 'gpt-4o-mini', name: 'GPT-4o mini' },
		{ id: 'claude-3-5-sonnet', name: 'Claude 3.5 Sonnet' },
		{ id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash' }
	];
	const dummyConversationCounts: Record<string, number> = {
		'gpt-4o-mini': 42,
		'claude-3-5-sonnet': 27,
		'gemini-2.0-flash': 11
	};
	const dummyGeneralPrompts = [
		{ id: 'gp-1', name: 'pdf_to_markdown', prompt: 'Convert the uploaded PDF into clean markdown while preserving numbering and math.', is_active: true },
		{ id: 'gp-2', name: 'topic_mapping', prompt: 'Map each question to one or more course topics in JSON.', is_active: true },
		{ id: 'gp-3', name: 'generate_answers', prompt: 'Generate a complete answer key in markdown.', is_active: true },
		{ id: 'gp-4', name: 'evaluate_question', prompt: 'Evaluate whether the student attempted and solved the question.', is_active: true },
		{ id: 'gp-5', name: 'generate_practice_problems', prompt: 'Create new practice problems based on weak topics.', is_active: true }
	];
	const dummyTutorPrompts = [
		{ id: 'tp-1', name: 'evaluate_question', group_id: 'dummy-group', prompt: 'Evaluate with a focus on partial credit and process.', is_active: true }
	];
	const dummyAnalysisHistory: AnalysisRecord[] = [
		{ contents: '1,2,3,4,5', startedAt: '10:12:04 AM', completedAt: '10:14:11 AM', failed: false },
		{ contents: '1,2,3,5', startedAt: '2:05:55 PM', completedAt: null, failed: true }
	];

	// ── State ─────────────────────────────────────────────────────────────────
	let homeworkStats: HomeworkStat[] = useOldData ? placeholderStats : [];
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
		availableModels = dummyModels;
		homeworkRows = dummyHomeworkRows;
		convCountByModelId = dummyConversationCounts;
		errorTypeDefs = $aiTutorDummyErrorTypes;
		generalPrompts = dummyGeneralPrompts;
		tutorPrompts = dummyTutorPrompts.map((p) => ({ ...p, group_id: groupId || 'dummy-group' }));
		homeworkStats = placeholderStats.map((stat, i) => ({
			...stat,
			homework: `Homework ${i + 1}`,
			status: i < 4,
			answerUploaded: i === 0 || i === 2
		}));
		selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
		syncRunSelectionFlags();
		analysisHistory = dummyAnalysisHistory;
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
		await loadModels();
		await loadErrorTypes(selectedGroupId);
		if (useOldData) {
			seedDummyDashboard(selectedGroupId);
			await tick();
			updateScrollState();
			return;
		}
	});

	$: if (!useOldData) {
		void loadHomeworkStats(selectedGroupId);
	}

	$: if (!useOldData) {
		void loadConversationCounts(selectedGroupId);
	}

	$: if (!useOldData) {
		void loadErrorTypes(selectedGroupId);
	}

	$: if (!useOldData) {
		void loadPrompts(selectedGroupId);
	}

async function loadHomeworkStats(groupId: string) {
		if (useOldData) {
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
					questionFileName: hw.question_filename ?? null,
					answerFileName: hw.answer_filename ?? null
				}));
				for (const hw of hwData) {
					uploadStatusMap.set(hw.id, {
						status: hw.question_uploaded ?? false,
						answerUploaded: hw.answer_uploaded ?? false
					});
				}
			}
			if (TESTING_AI_TUTOR) toast.success('[SUCCESS][GET]: Homework list loaded from /homework/.');
		} catch (error) {
			if (TESTING_AI_TUTOR) toast.warning('[FAIL][GET]: Homework list fetch failed.');
			console.error('Homework fetch failed:', error);
		}

		const statsMap = new Map<string, {
			totalProblems: number; attemptedSum: number; solvedSum: number; errorSum: number; count: number;
		}>();

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

		if (TESTING_AI_TUTOR && uploadStatusMap.size > 0) {
			toast.success('[SUCCESS][GET]: Analysis loaded from /analysis/.');
		}

		const allIds = new Set([...uploadStatusMap.keys(), ...statsMap.keys()]);
		const merged: HomeworkStat[] = Array.from(allIds).map((id) => {
			const upload = uploadStatusMap.get(id);
			const stats = statsMap.get(id);
			return {
				homework: id,
				status: upload?.status ?? false,
				answerUploaded: upload?.answerUploaded ?? false,
				totalProblems: stats ? stats.totalProblems : null,
				avgAttempted: stats ? Number((stats.attemptedSum / Math.max(stats.count, 1)).toFixed(1)) : null,
				avgSolved: stats ? Number((stats.solvedSum / Math.max(stats.count, 1)).toFixed(1)) : null,
				avgErrors: stats ? Number((stats.errorSum / Math.max(stats.count, 1)).toFixed(1)) : null
			};
		});
		merged.sort((a, b) => a.homework.localeCompare(b.homework));
		homeworkStats = merged;
		if (homeworkStats.length > 0 && selectedRunHomeworks.size === 0) {
			selectedRunHomeworks = new Set(homeworkStats.map((stat) => stat.homework));
			syncRunSelectionFlags();
		}

		await tick();
		updateScrollState();
	}

// ── Upload helpers ───────────────────────────────────────────────────
async function loadModels() {
	if (useOldData) {
		availableModels = dummyModels;
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
	if (useOldData) {
		convCountByModelId = groupId ? dummyConversationCounts : {};
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
	if (useOldData) {
		errorTypeDefs = $aiTutorDummyErrorTypes;
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
	if (useOldData) {
		generalPrompts = dummyGeneralPrompts;
		tutorPrompts = groupId ? dummyTutorPrompts.map((p) => ({ ...p, group_id: groupId })) : [];
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

function openPromptModal(def: { name: string; label: string; usedFor: string }) {
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
	if (useOldData) {
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
		if (TESTING_AI_TUTOR) toast.success('[SUCCESS][PUT]: Prompt override saved.');
	} catch (e) {
		if (TESTING_AI_TUTOR) toast.warning('[FAIL][PUT]: Prompt override save failed.');
		console.error('Prompt override save failed:', e);
	}
}

async function useDefaultPrompt() {
	if (useOldData) {
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
		if (TESTING_AI_TUTOR) toast.success('[SUCCESS][PUT]: Prompt reset to default.');
	} catch (e) {
		if (TESTING_AI_TUTOR) toast.warning('[FAIL][PUT]: Prompt reset failed.');
		console.error('Prompt reset failed:', e);
	}
}

async function persistErrorTypes() {
	if (!selectedGroupId) return;
	if (useOldData) {
		toast.success('TestData error types saved.');
		aiTutorDummyErrorTypes.set(errorTypeDefs);
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
		if (TESTING_AI_TUTOR && res.ok) toast.success('[SUCCESS][PUT]: Error types saved.');
	} catch (e) {
		if (TESTING_AI_TUTOR) toast.warning('[FAIL][PUT]: Error types save failed.');
		console.error('Failed to persist error types:', e);
	}
}

async function resetErrorTypesToDefault() {
	if (!selectedGroupId) return;
	if (useOldData) {
		errorTypeDefs = AI_TUTOR_DUMMY_ERROR_TYPES;
		aiTutorDummyErrorTypes.set(AI_TUTOR_DUMMY_ERROR_TYPES);
		toast.success('TestData error types reset to defaults.');
		return;
	}
	try {
		await fetch(
			`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(selectedGroupId)}`,
			{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
		);
		await loadErrorTypes(selectedGroupId);
		if (TESTING_AI_TUTOR) toast.success('[SUCCESS][DELETE]: Error types reset to defaults.');
	} catch (e) {
		if (TESTING_AI_TUTOR) toast.warning('[FAIL][DELETE]: Error types delete failed.');
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
	const key = hwId ? `${hwId}-${docType}` : `draft-${draftUid ?? 0}-${docType}`;
	uploadingMap = { ...uploadingMap, [key]: true };
	if (useOldData) {
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
				const newHomeworkId = `Homework ${homeworkRows.length + 1}`;
				homeworkRows = [
					...homeworkRows,
						{
							id: newHomeworkId,
							modelId: draft.modelId,
							questionUploaded: docType === 'question',
							answerUploaded: docType === 'answer',
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
		if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
		toast.success(`${docType === 'question' ? 'Homework' : 'Answer'} PDF uploaded successfully.`);
		if (hwId === null && draftUid !== undefined) draftRows = draftRows.filter(d => d.uid !== draftUid);
		await loadHomeworkStats(selectedGroupId);
	} catch (e) {
		toast.error('Upload failed.');
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

function getHomeworkNumberLabel(homework: string) {
	return homework.replace('Homework ', '');
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

async function runAnalysis() {
	const contents = getRunHomeworkSummary();
	if (!contents || contents === 'No homework') return;
	runningAnalysis = true;
	const startedAt = new Date().toLocaleTimeString();
	const steps = ['Started', 'Collecting conversation history', 'PDF converting', 'Analysing'];
	let stepIdx = 0;
	runStep = steps[0];
	const stepTimer = setInterval(() => {
		stepIdx = (stepIdx + 1) % steps.length;
		runStep = steps[stepIdx];
	}, 1800);
	if (useOldData) {
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
			`${AI_TUTOR_API_BASE}/analysis/run?homework_id=${encodeURIComponent(selectedHwForRun || Array.from(selectedRunHomeworks)[0] || '')}`,
			{ method: 'POST', headers: { Authorization: `Bearer ${localStorage.token}` } }
		);
		if (res.ok) {
			if (TESTING_AI_TUTOR) toast.success('[SUCCESS][POST]: Analysis run triggered.');
			else toast.success('Analysis started successfully.');
			analysisHistory = [{ contents, startedAt, completedAt: new Date().toLocaleTimeString(), failed: false }, ...analysisHistory];
		} else {
			toast.error(`Analysis failed: ${res.status}`);
			analysisHistory = [{ contents, startedAt, completedAt: null, failed: true }, ...analysisHistory];
		}
	} catch (e) {
		toast.error('Analysis request failed.');
		console.error('Run analysis failed:', e);
		analysisHistory = [{ contents, startedAt, completedAt: null, failed: true }, ...analysisHistory];
	} finally {
		clearInterval(stepTimer);
		runStep = '';
		runningAnalysis = false;
	}
}
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Configuration / Before You Start -->
	<div class="space-y-12">
		<div class="space-y-2">


			<div class="flex items-center justify-between gap-3">
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Homework & Answer Files</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">Upload the PDF files here before starting the analysis</div>
				</div>
				<div class="flex items-center gap-2">
					<button
						class="flex items-center gap-1 rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
						on:click={addDraftRow}
						title="Add homework"
					>
						<span>Add</span>
						<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
							<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
						</svg>
					</button>
				</div>
			</div>
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
			<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
				<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						<th class="px-3 py-1.5 select-none">Homework</th>
						<th class="px-3 py-1.5 select-none">Homework PDF</th>
						<th class="px-3 py-1.5 select-none">Answer PDF</th>
						<th class="px-3 py-1.5 select-none">Q Uploaded</th>
						<th class="px-3 py-1.5 select-none">A Uploaded</th>
						<th class="px-3 py-1.5 select-none">Conversations</th>
						<th class="px-3 py-1.5 select-none">Model</th>
					</tr>
				</thead>
				<tbody>
					{#if !selectedGroupId && !useOldData}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								Select a group to manage homeworks.
							</td>
						</tr>
					{:else}
						{#each homeworkRows as row, i}
							<tr class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850">
								<td class="px-3 py-1 text-gray-500 dark:text-gray-400">Homework {i + 1}</td>
								<td class="px-3 py-1">
									<label class="cursor-pointer">
										<input
											type="file"
											accept=".pdf"
											class="hidden"
											on:change={makeUploadHandler(row.id, 'question', row.modelId)}
										/>
										<span class="text-xs font-medium px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 transition">
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
										<span class="text-xs font-medium px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 transition">
											{uploadingMap[`${row.id}-answer`]
												? 'Uploading…'
												: row.answerUploaded
													? (row.answerFileName ?? `homework_${i + 1}_answers.pdf`)
													: 'Upload'}
										</span>
									</label>
								</td>
								<td class="px-3 py-1">
									{#if row.questionUploaded}
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 text-green-600 dark:text-green-400">
											<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
										</svg>
									{/if}
								</td>
								<td class="px-3 py-1">
									{#if row.answerUploaded}
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5 text-green-600 dark:text-green-400">
											<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
										</svg>
									{/if}
								</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
									{convCountByModelId[row.modelId ?? ''] ?? 0}
								</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300 max-w-[200px] truncate" title={row.modelId ?? ''}>
									{row.modelId ?? 'N/A'}
								</td>
							</tr>
						{/each}
				{/if}

				<!-- Draft rows (always rendered, outside group conditional) -->
				{#each draftRows as draft, di (draft.uid)}
					<tr class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850">
						<td class="px-3 py-1 text-gray-500 dark:text-gray-400">{homeworkRows.length + di + 1}</td>
						<td class="px-3 py-1">
							<label class="cursor-pointer">
								<input type="file" accept=".pdf" class="hidden"
									on:change={makeUploadHandler(null, 'question', draft.modelId, draft.uid)}
								/>
								<span class="text-xs font-medium px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 transition">
									{uploadingMap[`draft-${draft.uid}-question`] ? 'Uploading…' : 'Upload'}
								</span>
							</label>
						</td>
						<td class="px-3 py-1">
							<label class="cursor-pointer">
								<input type="file" accept=".pdf" class="hidden"
									on:change={makeUploadHandler(null, 'answer', draft.modelId, draft.uid)}
								/>
								<span class="text-xs font-medium px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 transition">
									{uploadingMap[`draft-${draft.uid}-answer`] ? 'Uploading…' : 'Upload'}
								</span>
							</label>
						</td>
						<td class="px-3 py-1"></td>
						<td class="px-3 py-1"></td>
						<td class="px-3 py-1"></td>
						<td class="px-3 py-1">
							<div class="relative inline-flex items-center">
								<select
									bind:value={draft.modelId}
									style="appearance: none; -webkit-appearance: none;"
									class="bg-transparent text-xs text-gray-700 dark:text-gray-300 outline-none pr-4 max-w-[180px]"
								>
									{#each availableModels as m}
										<option value={m.id}>{m.name}</option>
									{/each}
									{#if availableModels.length === 0}
										<option value="">No models available</option>
									{/if}
								</select>
							</div>
						</td>
					</tr>
				{/each}
				</tbody>
			</table>
		</div>
		</div>

		<div class="space-y-3">
			<div class="flex items-center justify-between gap-3">
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Error Type Configuration</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">You can have at most 4 error types</div>
				</div>
				<div class="flex items-center gap-3">
					<button
						class="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
						on:click={() => {
							showResetDefaultsModal = true;
						}}
					>
						Use default
					</button>
					<div class="flex items-center gap-2">
						{#if errorTypeDefs.length < 4}
							<button
								class="flex items-center gap-1 rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
								on:click={addErrorType}
							>
								<span>Add</span>
								<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
									<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
								</svg>
							</button>
						{/if}
						{#if errorTypeDefs.length > 0}
							<button
								class="flex items-center gap-1 rounded-full border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 transition hover:border-red-300 hover:bg-red-50 dark:border-red-900/70 dark:text-red-300 dark:hover:border-red-800 dark:hover:bg-red-950/40"
								on:click={() => {
									showResetDefaultsModal = true;
								}}
							>
								<span>Delete All</span>
								<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
									<path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
								</svg>
							</button>
						{/if}
					</div>
				</div>
			</div>

			{#if errorTypeDefs.length === 0}
				<div class="rounded-lg border border-gray-200 bg-white px-4 py-6 text-sm text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-500">
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
								<span class="h-3 w-3 rounded-full flex-shrink-0" style="background-color: {def.color};"></span>
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100">{def.type}</div>
							</div>
							<p class="mt-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
								{def.description || 'No description yet.'}
							</p>
						</button>
					{/each}
				</div>
			{/if}
			<div class="flex justify-end pt-2">
				<button
					class="rounded-full bg-black px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800"
					on:click={persistErrorTypes}
				>
					Save
				</button>
			</div>
		</div>

		<div class="space-y-3">
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Prompt Configuration</h2>
					<div class="text-xs text-gray-400 dark:text-gray-500">
						These prompts control how AI Tutor converts homework, analyzes students, and generates practice.
					</div>
				</div>


				<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
					<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
						<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
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
								<tr class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850">
									<td class="px-3 py-1.5 font-medium text-gray-900 dark:text-white">{def.label}</td>
									<td class="px-3 py-1.5 text-gray-700 dark:text-gray-300">{def.usedFor}</td>
									<td class="px-3 py-1.5 text-gray-700 dark:text-gray-300">{promptSummary.scope}</td>
									<td class="px-3 py-1.5">
										<button
											class="text-xs font-medium px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 transition"
											on:click={() => openPromptModal(def)}
										>
											View/Edit
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

		</div>

		<!-- Run Analysis subsection -->
		<div class="space-y-3">
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

			<!-- Analysis history -->
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
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6"
		on:click|self={() => (showPromptModal = false)}
		role="dialog"
		aria-modal="true"
	>
		<div class="flex max-h-[85vh] w-full max-w-[680px] flex-col overflow-hidden rounded-xl bg-white p-5 shadow-2xl dark:bg-gray-900 sm:p-6">
			<div class="mb-4 flex items-start justify-between gap-4">
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

			<hr class="mb-4 border-gray-100 dark:border-gray-700" />

			<div class="mb-4 flex items-center gap-2 text-xs">
				<span class="text-gray-500 dark:text-gray-400">Scope:</span>
				<span class="rounded px-2 py-1 bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
					{selectedPromptScope === 'override' ? 'Class Override' : 'Default'}
				</span>
			</div>

			<div class="mb-5 min-h-0 flex-1 overflow-y-auto pr-1">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Prompt</label>
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


<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
	.scrollbar-none::-webkit-scrollbar { display: none; }
	.scrollbar-none { -ms-overflow-style: none; scrollbar-width: none; }
</style>
