<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { page } from '$app/stores';
	import { aiTutorSelectedGroupId, user } from '$lib/stores';
	import {
		aiTutorWorkspaceModels,
		aiTutorAllowedModelIds
	} from '$lib/stores/aiTutorWorkspaceModels';
	import { toast } from 'svelte-sonner';
	import {
		AI_TUTOR_API_BASE_URL,
		AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES,
		AI_TUTOR_FRONTEND_TESTING_MODE,
		TESTING_AI_TUTOR
	} from '$lib/constants';
	import { aiTutorFrontendTestingErrorTypes } from '$lib/stores';
import { DropdownMenu, Popover } from 'bits-ui';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import {
		clearAITutorSessionCache,
		clearAITutorSessionCacheByPrefix,
		clearAITutorSessionCacheByGroup,
		loadWithAITutorSessionCache,
		writeAITutorSessionCache
	} from '$lib/utils/aiTutorSessionCache';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
import Hourglass from '$lib/components/icons/Hourglass.svelte';
import Dropdown from '$lib/components/common/Dropdown.svelte';
import { flyAndScale } from '$lib/utils/transitions';

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
		latestAnalysisAt?: string | null;
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
		questionUploadedAt?: string | null;
		answerUploadedAt?: string | null;
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
		fileName?: string | null;
	};

	let homeworkRows: HomeworkRow[] = [];
	let availableModels: {
		id: string;
		name: string;
		preset: boolean;
		base_model_id: string | null;
		access_control?: { read?: { group_ids?: string[] } };
		user_id?: string;
	}[] = [];
	type ConversationCount = { studentCount: number; chatCount: number };
	let convCountByModelId: Record<string, ConversationCount> = {};
	let convLatestActivityByModelId: Record<string, number> = {};
	let isRefreshingConversationCounts = false;
	let uploadingMap: Record<string, boolean> = {};
	let pdfProcessingMap: Record<string, boolean> = {};
	let pdfJobStepByKey: Record<string, string> = {};
	let hasLoadedHomework = false;
	let exportingConversationMap: Record<string, boolean> = {};
	let runningAnalysisByHomeworkId: Record<string, boolean> = {};
	let homeworkJobStepByModelId: Record<string, string> = {};
	const ACTIVE_JOB_STORAGE_KEY = 'ai_tutor_instructor_setup_jobs';
	const activeJobIds = new Set<string>();
	// AbortControllers for cancellable async operations (group switch, unmount)
	let loadHomeworkAbortController: AbortController | null = null;
	let loadConversationCountsAbortController: AbortController | null = null;
	const pollAbortControllers = new Map<string, AbortController>();
	const POLL_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes max polling
	type DraftRow = { uid: number; modelId: string };
	let draftRows: DraftRow[] = [];
	let _prevGroupIdForReset = '';
	let _nextDraftUid = 0;
	// 1.1.Error Type Configuration - Draft Mode
	// original: from backend; draft: local modifications
	let originalErrorTypeDefs: { type: string; color: string; description: string }[] = [];
	let draftErrorTypeDefs: { type: string; color: string; description: string }[] = [];
	let hasUnsavedErrorTypeChanges = false;
	let justSavedErrorTypes = false;
	let saveSuccessTimeout: ReturnType<typeof setTimeout> | null = null;
	
	const dashboardPalette = ['#EE352E', '#00933C', '#B933AD', '#0039A6', '#FF6319', '#996633'];
	const errorTypeColors = dashboardPalette.slice(0, 4);
	// B: backend-sourced timestamp — null until loadErrorTypes resolves
	let errorTypesUpdatedAt: string | null = null;
	let showEditErrorTypeModal = false;
	let showResetDefaultsModal = false;
	let resetDefaultsModalMode: 'default' | 'delete' = 'default';
	let showRunConfirmModal = false;
	let pendingRunRow: HomeworkRow | null = null;

	function errorTypesSavedAtKey(gid: string): string {
		return `ai_tutor_error_types_saved_at_${gid}`;
	}

	/** Returns the best available timestamp for when error types were last saved.
	 *  Priority: B (backend updated_at) > A (localStorage fallback). */
	function getEffectiveErrorTypeTimestamp(): string | null {
		if (errorTypesUpdatedAt) return errorTypesUpdatedAt;
		if (!$aiTutorSelectedGroupId || typeof localStorage === 'undefined') return null;
		return localStorage.getItem(errorTypesSavedAtKey($aiTutorSelectedGroupId)) ?? null;
	}

	function normalizeEpochToMs(value: number): number {
		if (!Number.isFinite(value) || value <= 0) return 0;
		return value > 1_000_000_000_000 ? value : value * 1000;
	}

	function parseTimestampToMs(value: unknown): number {
		if (typeof value === 'number') return normalizeEpochToMs(value);
		if (typeof value === 'string' && value) {
			const parsedDate = Date.parse(value);
			if (!Number.isNaN(parsedDate)) return parsedDate;
			const parsedNumber = Number(value);
			if (Number.isFinite(parsedNumber)) return normalizeEpochToMs(parsedNumber);
		}
		return 0;
	}

	function getAnalysisTimestampMs(row: HomeworkRow): number {
		const stat = homeworkStats.find((item) => item.homework === row.id);
		return stat?.latestAnalysisAt ? parseTimestampToMs(stat.latestAnalysisAt) : 0;
	}

	function getHomeworkStaleNote(row: HomeworkRow): string {
		const analysisTs = getAnalysisTimestampMs(row);
		if (!analysisTs) return '';
		const effectiveTs = getEffectiveErrorTypeTimestamp();
		if (!effectiveTs) return '';
		const errorTypeTs = parseTimestampToMs(effectiveTs);
		if (errorTypeTs > analysisTs) {
			return 'Error Type is newer than the analysis';
		}
		return '';
	}

	function getHomeworkFileStaleNotes(row: HomeworkRow): string[] {
		const analysisTs = getAnalysisTimestampMs(row);
		if (!analysisTs) return [];
		const notes: string[] = [];
		const questionTs = parseTimestampToMs(row.questionUploadedAt ?? null);
		if (questionTs > analysisTs) {
			notes.push('Homework PDF is newer than the analysis');
		}
		if (row.answerSource !== 'ai_generated') {
			const answerTs = parseTimestampToMs(row.answerUploadedAt ?? null);
			if (answerTs > analysisTs) {
				notes.push('Answer PDF is newer than the analysis');
			}
		}
		return notes;
	}

	function getRowLatestConversationActivityMs(row: HomeworkRow): number {
		const keys = new Set<string>();
		if (row.modelId) keys.add(row.modelId);
		const matchedModel = availableModels.find((model) => model.id === row.modelId);
		if (matchedModel?.name) keys.add(matchedModel.name);
		let latestMs = 0;
		for (const key of keys) {
			latestMs = Math.max(latestMs, convLatestActivityByModelId[key] ?? 0);
		}
		return latestMs;
	}

	function getStudentInteractionStaleNote(row: HomeworkRow): string {
		const analysisTs = getAnalysisTimestampMs(row);
		if (!analysisTs) return '';
		const latestInteractionTs = getRowLatestConversationActivityMs(row);
		if (latestInteractionTs > analysisTs) {
			return 'Student interaction is newer than the analysis';
		}
		return '';
	}

	function getHomeworkStaleTooltip(row: HomeworkRow): string {
		const notes: string[] = [];
		const fileNotes = getHomeworkFileStaleNotes(row);
		const errorNote = getHomeworkStaleNote(row);
		const studentInteractionNote = getStudentInteractionStaleNote(row);
		if (fileNotes.length > 0) notes.push(...fileNotes);
		if (errorNote) notes.push(errorNote);
		if (studentInteractionNote) notes.push(studentInteractionNote);
		return notes.join('\n');
	}
	let showPromptSection = false;
	let editingErrorTypeIndex: number | null = null;
	let editingErrorTypeIsNew = false;
	let editErrorTypeName = '';
	let editErrorTypeDescription = '';
	let editErrorTypeExample = '';
	let showErrorTypeMenuOpen: Record<number, boolean> = {};
	let isEditingErrorTypes = false;

	// Computed: derive errorTypeDefs from draft for display
	$: errorTypeDefs = draftErrorTypeDefs;
	
	// Track unsaved changes
	$: hasUnsavedErrorTypeChanges = JSON.stringify(originalErrorTypeDefs) !== JSON.stringify(draftErrorTypeDefs);
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
	let promptConfigurationSectionEl: HTMLDivElement | null = null;
	let showAITutorWorkflow = true;
	let showHomeworkAnswerFiles = true;
	let showErrorTypeConfiguration = true;

	async function togglePromptConfigurationSection() {
		showPromptConfiguration = !showPromptConfiguration;
		if (showPromptConfiguration) {
			await tick();
			promptConfigurationSectionEl?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}

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
	const frontendTestingConversationCounts: Record<string, ConversationCount> = {
		[frontendTestingHomeworkModelNames[0]]: { studentCount: 3, chatCount: 42 },
		[frontendTestingHomeworkModelNames[1]]: { studentCount: 2, chatCount: 27 },
		[frontendTestingHomeworkModelNames[2]]: { studentCount: 1, chatCount: 11 },
		[frontendTestingHomeworkModelNames[3]]: { studentCount: 2, chatCount: 18 }
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
	// $aiTutorSelectedGroupId now comes from store

	function getInstructorSetupCacheKey(resource: string, groupId?: string) {
		return ['instructor-setup', groupId || 'global', resource].join(':');
	}

	function invalidateInstructorSetupCache(groupId?: string) {
		clearAITutorSessionCacheByGroup(groupId || $aiTutorSelectedGroupId);
	}

	function buildHomeworkFileRows(
		allowedModels: {
			id: string;
			name: string;
			base_model_id: string | null;
			access_control?: { read?: { group_ids?: string[] } };
		}[],
		rows: HomeworkRow[]
	): HomeworkFileRow[] {
		const rowsByModelId = new Map<string, HomeworkRow>();

		for (const row of rows) {
			if (row.modelId && !rowsByModelId.has(row.modelId)) {
				rowsByModelId.set(row.modelId, row);
			}
		}

		const mergedRows: HomeworkFileRow[] = allowedModels
			.slice()
			.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))
			.map((model) => {
				const matchingRow = rowsByModelId.get(model.id) ?? rowsByModelId.get(model.name);
				if (matchingRow) {
					return {
						...matchingRow,
						displayModelName: model.name ?? model.id,
						isPlaceholder: false
					};
				}

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

		const allModelNames = allowedModels.map((m) => m.name ?? m.id);
		const selectedRows = mergedRows.filter((r) => !r.isPlaceholder);
		const excludedRows = mergedRows.filter((r) => r.isPlaceholder);
		console.log('[HomeworkFilter]-[InstructorSetup]-[BuildRows]:', {
			allModels: allModelNames,
			selected: selectedRows.map((r) => r.displayModelName),
			excluded: excludedRows.map((r) => ({ name: r.displayModelName, reason: 'no homework record yet' }))
		});
		console.log('[aitutordashboard]-[InstructorSetup]-[HomeworkRowsBuilt]:', mergedRows.map((r) => r.modelId));
		return mergedRows;
	}

	$: allowedModelsForGroup = $aiTutorWorkspaceModels.filter((model) => {
		const groupIds = model.access_control?.read?.group_ids ?? [];
		return groupIds.includes($aiTutorSelectedGroupId);
	});

	$: homeworkFileRows = buildHomeworkFileRows(allowedModelsForGroup, homeworkRows);

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

	type HomeworkDocType = 'question' | 'answer';

	function getHomeworkDocProgressKey(homeworkId: string, docType: HomeworkDocType): string {
		return `${homeworkId}-${docType}`;
	}

	function getModelDocProgressKey(modelId: string, docType: HomeworkDocType): string {
		return `model:${modelId}-${docType}`;
	}

	function getRowDocProgressKeys(row: HomeworkRow, docType: HomeworkDocType): string[] {
		const keys = [getHomeworkDocProgressKey(row.id, docType)];
		if (row.modelId) keys.push(getModelDocProgressKey(row.modelId, docType));
		return keys;
	}

	function getPersistedUploadDocType(job: PersistedInstructorJob): HomeworkDocType | null {
		if (job.type === 'question-upload') return 'question';
		if (job.type === 'answer-upload') return 'answer';
		return null;
	}

	function getPersistedUploadProgressKey(job: PersistedInstructorJob): string | null {
		const docType = getPersistedUploadDocType(job);
		if (!docType) return null;
		if (job.homeworkId) return getHomeworkDocProgressKey(job.homeworkId, docType);
		if (job.modelId) return getModelDocProgressKey(job.modelId, docType);
		return null;
	}

	function setBooleanMapValue(
		target: Record<string, boolean>,
		key: string,
		active: boolean
	): Record<string, boolean> {
		const next = { ...target };
		if (active) next[key] = true;
		else delete next[key];
		return next;
	}

	function setStringMapValue(
		target: Record<string, string>,
		key: string,
		value: string | null
	): Record<string, string> {
		const next = { ...target };
		if (value) next[key] = value;
		else delete next[key];
		return next;
	}

	function setDocUploadingByKey(key: string, active: boolean) {
		uploadingMap = setBooleanMapValue(uploadingMap, key, active);
	}

	function setDocProcessingByKey(key: string, active: boolean) {
		pdfProcessingMap = setBooleanMapValue(pdfProcessingMap, key, active);
	}

	function setDocStepByKey(key: string, step: string | null) {
		pdfJobStepByKey = setStringMapValue(pdfJobStepByKey, key, step);
	}

	function setAnalysisProcessingByHomeworkId(homeworkId: string, active: boolean) {
		if (!homeworkId) return;
		runningAnalysisByHomeworkId = setBooleanMapValue(runningAnalysisByHomeworkId, homeworkId, active);
	}

	function getRowDocUploading(row: HomeworkRow, docType: HomeworkDocType): boolean {
		return getRowDocProgressKeys(row, docType).some((key) => Boolean(uploadingMap[key]));
	}

	function getRowDocProcessing(row: HomeworkRow, docType: HomeworkDocType): boolean {
		return getRowDocProgressKeys(row, docType).some((key) => Boolean(pdfProcessingMap[key]));
	}

	function getRowDocStep(row: HomeworkRow, docType: HomeworkDocType): string {
		for (const key of getRowDocProgressKeys(row, docType)) {
			if (pdfJobStepByKey[key]) return pdfJobStepByKey[key];
		}
		return '';
	}

	function isAnalysisProcessing(row: HomeworkRow): boolean {
		return Boolean(
			exportingConversationMap[row.id] ||
				runningAnalysisByHomeworkId[row.id] ||
				homeworkJobStepByModelId[row.modelId ?? '']
		);
	}

	function setJobStep(modelId: string | null, step: string | null) {
		if (!modelId) return;
		homeworkJobStepByModelId = setStringMapValue(
			homeworkJobStepByModelId,
			modelId,
			step
		);
	}

	function markPersistedJobActive(job: PersistedInstructorJob, active: boolean) {
		if (job.type === 'analysis' && job.homeworkId) {
			setAnalysisProcessingByHomeworkId(job.homeworkId, active);
			return;
		}

		if (job.type === 'question-upload' || job.type === 'answer-upload') {
			const key = getPersistedUploadProgressKey(job);
			if (!key) return;
			setDocProcessingByKey(key, active);
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
		originalErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
		draftErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
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
	// Group-change data loading is now handled by the _prevGroupIdForReset reactive block below.

	function handleVisibilityChange() {
		if (document.visibilityState === 'visible' && !useFrontendTestingData && $aiTutorSelectedGroupId) {
			void loadConversationCounts($aiTutorSelectedGroupId);
		}
	}

	// ── Data fetching ─────────────────────────────────────────────────────────
	onMount(async () => {
		// Page: AI Tutor Dashboard > Instructor Setup
		// Purpose: load non-group-scoped data first, then wait for the layout-selected
		// group_id before issuing group-scoped setup requests.
		testToast(
			`loading aitutordashboard - Instructor Setup | group=${$aiTutorSelectedGroupId || 'pending'} | frontend_testing=${String(useFrontendTestingData)}`
		);
		console.log('[aitutordashboard]-[InstructorSetup]-[Mount]:', {
			pathname: $page.url.pathname,
			groupId: $aiTutorSelectedGroupId,
			groupIdFromUrl: $page.url.searchParams.get('group_id') || ''
		});
		document.addEventListener('visibilitychange', handleVisibilityChange);
		await loadModels();
		if (useFrontendTestingData) {
			seedDummyDashboard($aiTutorSelectedGroupId);
			await tick();
			updateScrollState();
		}
	});

	onDestroy(() => {
		document.removeEventListener('visibilitychange', handleVisibilityChange);
		// Cancel any in-flight homework load
		loadHomeworkAbortController?.abort();
		// Cancel any in-flight conversation counts load
		loadConversationCountsAbortController?.abort();
		// Cancel all active poll loops
		for (const [, ctrl] of pollAbortControllers) {
			ctrl.abort();
		}
		pollAbortControllers.clear();
	});

	// Reset per-homework action state whenever the selected group changes so that
	// in-progress indicators from a previous group never bleed into the new one.
	$: if ($aiTutorSelectedGroupId !== _prevGroupIdForReset) {
		_prevGroupIdForReset = $aiTutorSelectedGroupId;
		// Cancel any in-flight load for the previous group
		loadHomeworkAbortController?.abort();
		loadConversationCountsAbortController?.abort();
		// Cancel all active poll loops so they don't mutate state for the wrong group
		for (const [, ctrl] of pollAbortControllers) {
			ctrl.abort();
		}
		pollAbortControllers.clear();
		activeJobIds.clear();
		uploadingMap = {};
		pdfProcessingMap = {};
		pdfJobStepByKey = {};
		exportingConversationMap = {};
		runningAnalysisByHomeworkId = {};
		homeworkJobStepByModelId = {};
		draftRows = [];
		homeworkRows = [];
		homeworkStats = [];
		convCountByModelId = {};
		convLatestActivityByModelId = {};
		hasLoadedHomework = false;
		// When switching to a non-empty group, trigger data loads.
		// When switching to empty/no group, the cleared state above is sufficient.
		if ($aiTutorSelectedGroupId) {
			void loadHomeworkStats($aiTutorSelectedGroupId);
			void loadConversationCounts($aiTutorSelectedGroupId);
			void loadErrorTypes($aiTutorSelectedGroupId);
			void loadPrompts($aiTutorSelectedGroupId);
			void resumePersistedJobs($aiTutorSelectedGroupId);
		}
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

		// Cancel any previous in-flight load for this page
		loadHomeworkAbortController?.abort();
		const controller = new AbortController();
		loadHomeworkAbortController = controller;

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
							headers: { Authorization: `Bearer ${localStorage.token}` },
							signal: controller.signal
						}
					);
					if (!hwResponse.ok) throw new Error('Homework fetch failed');
					const hwData = await hwResponse.json();
					if (Array.isArray(hwData)) {
						// Backend now stores filenames; preserve frontend-known ones as fallback.
						const existingFileNames = new Map(homeworkRows.map(r => [r.id, { q: r.questionFileName, a: r.answerFileName }]));
						const existingTimestamps = new Map(homeworkRows.map(r => [r.id, { q: r.questionUploadedAt, a: r.answerUploadedAt }]));
						fetchedHomeworkRows = hwData.map((hw: any) => ({
							id: hw.id,
							modelId: hw.model_id ?? null,
							questionUploaded: hw.question_uploaded ?? false,
							answerUploaded: hw.answer_uploaded ?? false,
							topicMapped: hw.topic_mapped ?? false,
							answerSource: hw.answer_source ?? null,
							questionFileName: hw.question_pdf_name ?? existingFileNames.get(hw.id)?.q ?? null,
							answerFileName: hw.answer_pdf_name ?? existingFileNames.get(hw.id)?.a ?? null,
							questionUploadedAt: hw.question_uploaded_at ?? existingTimestamps.get(hw.id)?.q ?? null,
							answerUploadedAt: hw.answer_uploaded_at ?? existingTimestamps.get(hw.id)?.a ?? null
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
					const latestAnalysisAtByHomeworkId = new Map<string, string>();

					for (const homeworkId of uploadStatusMap.keys()) {
						// Page: AI Tutor Dashboard > Instructor Setup
						// Endpoint: GET /analysis/?homework_id={homework_id}
						// Purpose: aggregate student analysis rows into homework-level setup metrics.
						const analysisResponse = await fetch(
							`${AI_TUTOR_API_BASE}/analysis/?homework_id=${encodeURIComponent(homeworkId)}`,
							{
								method: 'GET',
								headers: { Authorization: `Bearer ${localStorage.token}` },
								signal: controller.signal
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
								// Track the most recent analysis timestamp per homework (for stale detection)
								if (row?.created_at) {
									const existing = latestAnalysisAtByHomeworkId.get(id);
									if (!existing || row.created_at > existing) {
										latestAnalysisAtByHomeworkId.set(id, row.created_at);
									}
								}
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
							avgErrors: stats ? Number((stats.errorSum / Math.max(stats.count, 1)).toFixed(1)) : null,
							latestAnalysisAt: latestAnalysisAtByHomeworkId.get(id) ?? null
						};
					});
					mergedStats.sort((a, b) => a.homework.localeCompare(b.homework));

					fetchedHomeworkRows = fetchedHomeworkRows.map((row) => ({
						...row,
						modelId: modelIdByHomeworkId.get(row.id) ?? row.modelId,
						topicMapped: topicMappedByHomeworkId.get(row.id) ?? row.topicMapped ?? false
					}));

					console.log('[aitutordashboard]-[InstructorSetup]-[HomeworkLoaded]:', {
						groupId,
						homeworkRows: fetchedHomeworkRows.map((row) => ({
							id: row.id,
							name: row.id,
							modelId: row.modelId ?? '',
							questionUploaded: row.questionUploaded,
							answerUploaded: row.answerUploaded,
							topicMapped: row.topicMapped ?? false
						})),
						homeworkStats: mergedStats.map((stat) => ({
							id: stat.homework,
							name: stat.homework,
							status: stat.status,
							answerUploaded: stat.answerUploaded
						}))
					});

					return {
						homeworkRows: fetchedHomeworkRows,
						homeworkStats: mergedStats
					};
				}
			});

			if ($aiTutorSelectedGroupId !== groupId) return; // stale — group changed while loading
			homeworkRows = cached.homeworkRows;
			homeworkStats = cached.homeworkStats;
			hasLoadedHomework = true;
			console.log('[aitutordashboard]-[InstructorSetup]-[HomeworkStatsLoaded]: group=' + groupId, { homeworkCount: homeworkRows.length, modelIds: homeworkRows.map((r) => r.modelId) });
		} catch (error) {
			if ((error as Error)?.name === 'AbortError') {
				console.log('[aitutordashboard]-[InstructorSetup]-[LoadAborted]: group=' + groupId);
				return;
			}
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
					const allMapped = Array.isArray(data?.data)
						? data.data.map((m: any) => ({
								id: m.id,
								name: m.name ?? m.id,
								preset: m.preset === true,
								base_model_id: m.info?.base_model_id ?? m.base_model_id ?? null,
								access_control: m.access_control ?? m.info?.access_control ?? null,
								user_id: m.user_id
							}))
						: [];
					const excludedModels: { name: string; reason: string }[] = [];
						const homeworkNamePattern = /(homework|hw(?:\s*#\s*|[-_]\s*#?\s*|\s+)?\d+)/i;
					const result = allMapped.filter((model: { id: string; name: string }) => {
						if (!homeworkNamePattern.test(model.name ?? model.id)) {
							excludedModels.push({ name: model.name ?? model.id, reason: 'name missing homework' });
							return false;
						}
						if ((model.name ?? model.id).startsWith('Mastery')) {
							excludedModels.push({ name: model.name ?? model.id, reason: 'Mastery prefix' });
							return false;
						}
						return true;
					});
					console.log('[HomeworkFilter]-[InstructorSetup]-[LoadModels]:', {
						all: allMapped.map((m) => m.name ?? m.id),
						selected: result.map((m) => m.name ?? m.id),
						excluded: excludedModels
					});
					return result;
				}
			});
			availableModels = models;
		} catch (e) {
			console.error('Models fetch failed:', e);
		}
	}

	async function loadConversationCounts(groupId: string) {
		console.log('[aitutordashboard]-[InstructorSetup]-[ConversationCountsRefreshTriggered]: group=' + groupId);
		testToast(`Instructor Setup fetch: conversations group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			convCountByModelId = groupId ? frontendTestingConversationCounts : {};
			return;
		}
		if (!groupId) return;
		// Cancel any previous in-flight request
		loadConversationCountsAbortController?.abort();
		const controller = new AbortController();
		loadConversationCountsAbortController = controller;
		try {
			// Real-time fetch without session cache so the count always matches
			// what the admin panel Conversation History modal shows.
			const res = await fetch('/api/v1/chats/filter/meta', {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${localStorage.token}`,
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({ group_id: groupId, skip: 0, limit: 1000 }),
				signal: controller.signal
			});
				if (!res.ok) throw new Error('Conv count fetch failed');
				const data = await res.json();
				const nextCounts: Record<string, ConversationCount> = {};
				const nextLatestActivityByModelId: Record<string, number> = {};
				const studentsByModel: Record<string, Set<string>> = {};
				if (Array.isArray(data)) {
					for (const chat of data) {
						const chatActivityMs = normalizeEpochToMs(
							Number(chat?.updated_at ?? chat?.created_at ?? 0)
						);
						const modelKeys = [
							chat?.meta?.model_id,
							chat?.meta?.model_name,
							chat?.meta?.base_model_name
						].filter((value) => typeof value === 'string' && value.length > 0);
						for (const modelKey of new Set(modelKeys)) {
							if (!studentsByModel[modelKey]) {
								studentsByModel[modelKey] = new Set();
							}
							studentsByModel[modelKey].add(chat.user_id);
							nextCounts[modelKey] = {
								studentCount: studentsByModel[modelKey].size,
								chatCount: (nextCounts[modelKey]?.chatCount ?? 0) + 1
							};
							nextLatestActivityByModelId[modelKey] = Math.max(
								nextLatestActivityByModelId[modelKey] ?? 0,
								chatActivityMs
							);
						}
					}
				}
				if ($aiTutorSelectedGroupId !== groupId) return; // stale
				convCountByModelId = nextCounts;
				convLatestActivityByModelId = nextLatestActivityByModelId;
				console.log('[aitutordashboard]-[InstructorSetup]-[ConversationCountsRefreshCompleted]:', nextCounts);
		} catch (e) {
			if (e instanceof Error && e.name === 'AbortError') {
				console.log('[aitutordashboard]-[InstructorSetup]-[ConversationCountsAborted]: group=' + groupId);
				return;
			}
			console.error('Conversation count fetch failed:', e);
		} finally {
			isRefreshingConversationCounts = false;
		}
	}

	async function loadErrorTypes(groupId: string) {
		testToast(`Instructor Setup fetch: error types group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			originalErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			draftErrorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			return;
		}
		if (!groupId) return;
		type CachedErrorTypesPayload = { defs: typeof errorTypeDefs; updatedAt: string | null };
		try {
			const cached = await loadWithAITutorSessionCache<CachedErrorTypesPayload>({
				key: getInstructorSetupCacheKey('error-types', groupId),
				ttlMs: CACHE_TTL_MS,
				onCached: (c) => {
					if ($aiTutorSelectedGroupId === groupId) {
						originalErrorTypeDefs = c.defs;
						draftErrorTypeDefs = c.defs;
						errorTypesUpdatedAt = c.updatedAt;
						console.log('[ErrorTypes] Cache hit:', JSON.stringify(c.defs));
					}
				},
				loader: async () => {
					const res = await fetch(
						`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(groupId)}`,
						{ headers: { Authorization: `Bearer ${localStorage.token}` } }
					);
					if (!res.ok) throw new Error('Error types fetch failed');
					const data = await res.json();
					console.log('[ErrorTypes] Backend response:', JSON.stringify(data));
					const errorTypes = Array.isArray(data?.error_types)
						? data.error_types
						: Array.isArray(data)
							? data
							: [];
					const defs = errorTypes.slice(0, 4).map((et: any, i: number) => ({
						type: et.name ?? 'Unknown',
						color: errorTypeColors[i % errorTypeColors.length],
						description: et.description ?? '',
						example: et.example ?? ''
					}));
					// B: backend updated_at — null for legacy rows or default source
					const updatedAt: string | null = data?.updated_at ?? null;
					return { defs, updatedAt };
				}
			});
			if ($aiTutorSelectedGroupId !== groupId) return; // stale
			originalErrorTypeDefs = cached.defs;
			draftErrorTypeDefs = cached.defs;
			// B: prefer backend timestamp; fall back gracefully to null (getEffectiveErrorTypeTimestamp handles A)
			errorTypesUpdatedAt = cached.updatedAt;
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
				onCached: (cached) => {
					if ($aiTutorSelectedGroupId === groupId) {
						generalPrompts = cached.generalPrompts;
						tutorPrompts = cached.tutorPrompts;
					}
				},
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
			if ($aiTutorSelectedGroupId !== groupId) return; // stale
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
				scope: 'Set by User',
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
		onProgress?: (data: any) => void,
		signal?: AbortSignal
	) {
		const startTime = Date.now();
		while (true) {
			if (signal?.aborted) {
				throw new Error('Polling aborted');
			}
			// Timeout guard: if polling exceeds max duration, abort
			if (Date.now() - startTime > POLL_TIMEOUT_MS) {
				throw new Error(`${label} timed out after ${POLL_TIMEOUT_MS / 60000} minutes.`);
			}
			// Shared async job polling helper.
			// Endpoint: GET /pipeline/status/{job_id}
			const res = await fetch(`${AI_TUTOR_API_BASE}/pipeline/status/${encodeURIComponent(jobId)}`, {
				headers: { Authorization: `Bearer ${localStorage.token}` },
				signal
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
		const uploadProgressKey = getPersistedUploadProgressKey(job);
		// Safety net: force-clear step if polling hangs or finally is skipped
		const safetyTimeout = setTimeout(() => {
			console.warn('[AI Tutor][Instructor Setup] safety clear for stuck job step', { jobId: job.jobId, modelId: job.modelId });
			if (job.type === 'analysis') {
				setJobStep(job.modelId, null);
			} else if (uploadProgressKey) {
				setDocStepByKey(uploadProgressKey, null);
				setDocProcessingByKey(uploadProgressKey, false);
			}
			markPersistedJobActive(job, false);
			removePersistedJob(job.jobId);
			activeJobIds.delete(job.jobId);
		}, POLL_TIMEOUT_MS + 5000);
		// Create an AbortController for this poll so group-switch / unmount can cancel it
		const controller = new AbortController();
		pollAbortControllers.set(job.jobId, controller);
		console.info('[AI Tutor][Instructor Setup] monitor job start', {
			jobId: job.jobId,
			type: job.type,
			groupId: job.groupId,
			modelId: job.modelId,
			homeworkId: job.homeworkId
		});
		try {
			await pollPipelineJob(
				job.jobId,
				3000,
				job.type === 'analysis'
					? 'analysis run'
					: job.type === 'question-upload'
						? 'question upload'
						: 'answer upload',
					(data) => {
						console.info('[AI Tutor][Instructor Setup] monitor job progress', {
							jobId: job.jobId,
							type: job.type,
							status: data?.status ?? 'unknown',
							step: data?.step ?? 'unknown'
						});
						if (job.type === 'analysis') {
							// Keep a refresh-safe step message per model so the status column
							// shows which backend step is currently running.
							setJobStep(job.modelId, data?.step ? `Step: ${data.step}` : null);
						} else if (uploadProgressKey) {
							setDocStepByKey(uploadProgressKey, data?.step ? `Step: ${data.step}` : 'Processing PDF');
						}
					},
					controller.signal
				);
			console.info('[AI Tutor][Instructor Setup] monitor job done', {
				jobId: job.jobId,
				type: job.type,
				groupId: job.groupId,
				modelId: job.modelId,
				homeworkId: job.homeworkId
			});

			if (job.type === 'analysis') {
				toast.success('Analysis completed.');
			} else {
				homeworkRows = homeworkRows.map((row) => {
					if (job.homeworkId && row.id !== job.homeworkId && row.modelId !== job.modelId) return row;
					if (!job.homeworkId && row.modelId !== job.modelId) return row;
					if (job.type === 'question-upload') {
						return {
							...row,
							questionUploaded: true,
							questionFileName: job.fileName ?? row.questionFileName,
							questionUploadedAt: new Date().toISOString()
						};
					}
					return {
						...row,
						answerUploaded: true,
						answerSource: 'uploaded',
						answerFileName: job.fileName ?? row.answerFileName,
						answerUploadedAt: new Date().toISOString()
					};
				});
				toast.success(`${job.type === 'question-upload' ? 'Homework' : 'Answer'} upload completed.`);
			}

			if ($aiTutorSelectedGroupId === job.groupId) {
				await loadHomeworkStats(job.groupId);
			}
		} catch (error) {
			console.error('[AI Tutor][Instructor Setup] monitor job failed', {
				jobId: job.jobId,
				type: job.type,
				groupId: job.groupId,
				modelId: job.modelId,
				homeworkId: job.homeworkId,
				error
			});
			toast.error(error instanceof Error ? error.message : 'Background job failed.');
		} finally {
			clearTimeout(safetyTimeout);
			if (job.type === 'analysis') {
				setJobStep(job.modelId, null);
			} else if (uploadProgressKey) {
				setDocStepByKey(uploadProgressKey, null);
				setDocProcessingByKey(uploadProgressKey, false);
			}
			markPersistedJobActive(job, false);
			removePersistedJob(job.jobId);
			activeJobIds.delete(job.jobId);
			pollAbortControllers.delete(job.jobId);
			// Ensure upload spinner is cleared when a background upload job finishes or fails.
			if (uploadProgressKey) {
				setDocUploadingByKey(uploadProgressKey, false);
			}
		}
	}
	async function resumePersistedJobs(groupId: string) {
		const jobs = readPersistedJobs().filter((item) => item.groupId === groupId);
		console.log('[aitutordashboard]-[InstructorSetup]-[JobsRestored]:', {
			groupId,
			jobs: jobs.map((job) => ({
				jobId: job.jobId,
				type: job.type,
				homeworkId: job.homeworkId ?? '',
				modelId: job.modelId,
				fileName: job.fileName ?? ''
			}))
		});
		for (const job of jobs) {
			// Before restoring the spinner, quickly check if the job already finished
			// while the user was on another tab/group. If so, clean it up and skip monitoring.
			try {
				const checkRes = await fetch(
					`${AI_TUTOR_API_BASE}/pipeline/status/${encodeURIComponent(job.jobId)}`,
					{ headers: { Authorization: `Bearer ${localStorage.token}` } }
				);
				if (checkRes.ok) {
					const checkData = await checkRes.json();
						if (checkData?.status === 'done' || checkData?.status === 'failed') {
							console.info('[resumePersistedJobs] job already finished, skipping monitor', {
								jobId: job.jobId,
								status: checkData.status
							});
							removePersistedJob(job.jobId);
							// If it was an upload, clear any stale spinner and refresh data so the UI shows the result
							if (job.type === 'question-upload' || job.type === 'answer-upload') {
								const progressKey = getPersistedUploadProgressKey(job);
								if (progressKey) {
									setDocUploadingByKey(progressKey, false);
									setDocProcessingByKey(progressKey, false);
									setDocStepByKey(progressKey, null);
								}
								if (job.groupId === $aiTutorSelectedGroupId) {
									await loadHomeworkStats(job.groupId);
								}
							}
							continue;
						}
					}
			} catch {
				// Network hiccup — fall through to normal monitoring
			}
			if (job.type === 'question-upload' || job.type === 'answer-upload') {
				const progressKey = getPersistedUploadProgressKey(job);
				if (progressKey) {
					setDocUploadingByKey(progressKey, false);
					setDocProcessingByKey(progressKey, true);
					setDocStepByKey(progressKey, 'Processing PDF');
				}
			}
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
			// Refresh counts immediately so the displayed number matches the exported snapshot.
			void loadConversationCounts($aiTutorSelectedGroupId);
			return true;
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Conversation export failed.');
			return false;
		} finally {
			exportingConversationMap = { ...exportingConversationMap, [homeworkId]: false };
		}
	}

	async function validateRunPrerequisites(row: HomeworkRow) {
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
		if (!$aiTutorSelectedGroupId || !selectedPromptName) return;
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
			clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
			await loadPrompts($aiTutorSelectedGroupId);
			showPromptModal = false;
			testToast('Instructor Setup reset prompt to default');
		} catch (e) {
			testToast('Instructor Setup failed resetting prompt to default');
			console.error('Prompt reset failed:', e);
		}
	}

	async function persistErrorTypes() {
		if (!$aiTutorSelectedGroupId) return;
		if (useFrontendTestingData) {
			toast.success('Frontend testing error types saved.');
			aiTutorFrontendTestingErrorTypes.set(draftErrorTypeDefs);
			originalErrorTypeDefs = draftErrorTypeDefs;
			isEditingErrorTypes = false;
			const ts = new Date().toISOString();
			if (typeof localStorage !== 'undefined')
				localStorage.setItem(errorTypesSavedAtKey($aiTutorSelectedGroupId), ts);
			errorTypesUpdatedAt = ts;
			// Show "Saved" state briefly
			justSavedErrorTypes = true;
			if (saveSuccessTimeout) clearTimeout(saveSuccessTimeout);
			saveSuccessTimeout = setTimeout(() => { justSavedErrorTypes = false; }, 2000);
			return;
		}
		try {
			let savedAt: string | null = null;
			if (draftErrorTypeDefs.length === 0) {
				// Deleting the last type — DELETE reverts to server defaults
				const res = await fetch(
					`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent($aiTutorSelectedGroupId)}`,
					{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
				);
				if (res.ok) {
					savedAt = new Date().toISOString();
					// No server-side updated_at on DELETE (row is removed); record change time in A only
					errorTypesUpdatedAt = null;
				}
			} else {
				const res = await fetch(
					`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent($aiTutorSelectedGroupId)}`,
					{
						method: 'PUT',
						headers: {
							'Content-Type': 'application/json',
							Authorization: `Bearer ${localStorage.token}`
						},
						body: JSON.stringify(
							draftErrorTypeDefs.map((d) => ({ name: d.type, description: d.description, example: d.example }))
						)
					}
				);
				if (res.ok) {
					const data = await res.json();
					console.log('[ErrorTypes] Persist success. Server returned:', JSON.stringify(data.error_types));
					console.log('[ErrorTypes] Sent draft:', JSON.stringify(draftErrorTypeDefs));
					savedAt = data?.updated_at ?? new Date().toISOString();
					errorTypesUpdatedAt = savedAt;
				} else {
					console.warn('[ErrorTypes] Persist failed, status:', res.status);
					toast.error('Failed to save error types. Please try again.');
				}
			}
			if (savedAt !== null) {
				if (typeof localStorage !== 'undefined')
					localStorage.setItem(errorTypesSavedAtKey($aiTutorSelectedGroupId), savedAt);
				clearAITutorSessionCache(getInstructorSetupCacheKey('error-types', $aiTutorSelectedGroupId));
				writeAITutorSessionCache(getInstructorSetupCacheKey('error-types', $aiTutorSelectedGroupId), {
					defs: draftErrorTypeDefs,
					updatedAt: errorTypesUpdatedAt
				});
				console.log('[ErrorTypes] Cache updated with:', JSON.stringify(draftErrorTypeDefs));
				toast.success('Error types saved.');
				// Sync original to match draft after successful save
				originalErrorTypeDefs = draftErrorTypeDefs;
				// Show "Saved" state briefly
				isEditingErrorTypes = false;
				justSavedErrorTypes = true;
				if (saveSuccessTimeout) clearTimeout(saveSuccessTimeout);
				saveSuccessTimeout = setTimeout(() => { justSavedErrorTypes = false; }, 2000);
				testToast('Instructor Setup saved error types');
			}
		} catch (e) {
			testToast('Instructor Setup failed saving error types');
			console.error('Failed to persist error types:', e);
			toast.error('Failed to save error types. Please try again.');
		}
	}

	async function resetErrorTypesToDefault() {
		if (!$aiTutorSelectedGroupId) return;
		// Draft mode: only update draft, require Save to persist
		draftErrorTypeDefs = AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES.map((et, i) => ({
			...et,
			color: errorTypeColors[i % errorTypeColors.length]
		}));
		testToast('Instructor Setup reset to defaults (draft) — Save to persist');
	}

	function deleteAllErrorTypes() {
		// Draft mode: only update draft, require Save to persist
		draftErrorTypeDefs = [];
		testToast('Instructor Setup delete all (draft) — Save to persist');
	}

	function openEditErrorType(index: number) {
		editingErrorTypeIndex = index;
		editingErrorTypeIsNew = false;
		editErrorTypeName = draftErrorTypeDefs[index].type;
		editErrorTypeDescription = draftErrorTypeDefs[index].description;
		editErrorTypeExample = draftErrorTypeDefs[index].example ?? '';
		showEditErrorTypeModal = true;
	}

	function addErrorType() {
		if (draftErrorTypeDefs.length >= 4) return;
		const color = errorTypeColors[draftErrorTypeDefs.length % errorTypeColors.length];
		const newDef = { type: 'New Error Type', color, description: '', example: '' };
		draftErrorTypeDefs = [...draftErrorTypeDefs, newDef];
		editingErrorTypeIndex = draftErrorTypeDefs.length - 1;
		editingErrorTypeIsNew = true;
		editErrorTypeName = newDef.type;
		editErrorTypeDescription = '';
		editErrorTypeExample = '';
		showEditErrorTypeModal = true;
	}

	function saveErrorTypeEdit() {
		if (editingErrorTypeIndex === null) return;
		draftErrorTypeDefs[editingErrorTypeIndex] = {
			...draftErrorTypeDefs[editingErrorTypeIndex],
			type: editErrorTypeName,
			description: editErrorTypeDescription,
			example: editErrorTypeExample
		};
		draftErrorTypeDefs = [...draftErrorTypeDefs];
		closeErrorTypeModal();
		void persistErrorTypes();
	}

	function deleteErrorType() {
		if (editingErrorTypeIndex === null) return;
		draftErrorTypeDefs = draftErrorTypeDefs.filter((_, i) => i !== editingErrorTypeIndex);
		closeErrorTypeModal();
		void persistErrorTypes();
	}

	function closeErrorTypeModal() {
		showEditErrorTypeModal = false;
		editingErrorTypeIndex = null;
		editingErrorTypeIsNew = false;
	}

	function confirmResetDefaults() {
		showResetDefaultsModal = false;
		if (resetDefaultsModalMode === 'delete') {
			deleteAllErrorTypes();
		} else {
			resetErrorTypesToDefault();
		}
	}

	async function uploadPdf(
		hwId: string | null,
		docType: 'question' | 'answer',
		modelId: string,
		file: File,
		draftUid?: number
	) {
		testToast(`Upload ${docType} PDF is triggered | page=aitutordashboard - Instructor Setup | model=${modelId} | target=${hwId ?? `draft-${draftUid ?? 0}`}`);
		if (!$aiTutorSelectedGroupId && !useFrontendTestingData) {
			toast.error('Select a group before uploading PDFs.');
			return;
		}
		if (file.type !== 'application/pdf') {
			toast.error('Please upload a PDF file.');
			return;
		}
		const key = hwId
			? getHomeworkDocProgressKey(hwId, docType)
			: modelId
				? getModelDocProgressKey(modelId, docType)
				: `draft-${draftUid ?? 0}-${docType}`;
		// Guard against double-click / concurrent upload for the same homework+docType
		if (uploadingMap[key] || pdfProcessingMap[key]) {
			console.log('[UPLOAD]-[' + key + ']-[Skipped]: already uploading, ignoring duplicate');
			return;
		}
		setDocUploadingByKey(key, true);
		setDocProcessingByKey(key, false);
		setDocStepByKey(key, null);
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
			setDocUploadingByKey(key, false);
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
			console.info('[AI Tutor][Instructor Setup] upload job created', {
				jobId,
				docType,
				groupId: $aiTutorSelectedGroupId,
				modelId,
				homeworkId: hwId,
				fileName: file.name
			});
			const persistedJob: PersistedInstructorJob = {
				jobId,
				type: docType === 'question' ? 'question-upload' : 'answer-upload',
				groupId: $aiTutorSelectedGroupId,
				modelId,
				homeworkId: hwId,
				fileName: file.name
			};
			clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
			upsertPersistedJob(persistedJob);
			toast.success(`${docType === 'question' ? 'Homework' : 'Answer'} upload started.`);
			// Immediately reflect the file name so the Homework PDF column shows it
			// even while the background pipeline job is still running.
			if (hwId) {
				homeworkRows = homeworkRows.map((row) => {
					if (row.id !== hwId) return row;
					return {
						...row,
						questionFileName: docType === 'question' ? file.name : row.questionFileName,
						answerFileName: docType === 'answer' ? file.name : row.answerFileName
					};
				});
			}
			// Upload is done; reset the spinner immediately so it only covers the HTTP upload,
			// not the entire background pipeline job.
			setDocUploadingByKey(key, false);
			await monitorPersistedJob(persistedJob);
			if (hwId === null && draftUid !== undefined)
				draftRows = draftRows.filter((d) => d.uid !== draftUid);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : 'Upload failed.');
			console.error('PDF upload failed:', e);
			setDocUploadingByKey(key, false);
			setDocProcessingByKey(key, false);
			setDocStepByKey(key, null);
		}
	}

	// ── Upload event handler factory ─────────────────────────────────────
	function addDraftRow() {
		const nextHomeworkNumber = homeworkRows.length + draftRows.length + 1;
		const nextHomeworkModelName = `Homework${nextHomeworkNumber}-MATH-Code-Section-Semester`;
		draftRows = [...draftRows, { uid: _nextDraftUid++, modelId: nextHomeworkModelName }];
		console.log('[aitutordashboard]-[InstructorSetup]-[DraftRowAdded]:', draftRows);
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
		if (getRowDocUploading(row, 'question') || getRowDocUploading(row, 'answer')) {
			return 'Uploading PDF';
		}
		if (
			getRowDocProcessing(row, 'question') ||
			getRowDocProcessing(row, 'answer') ||
			getRowDocStep(row, 'question') ||
			getRowDocStep(row, 'answer') ||
			(row.questionUploaded && !row.topicMapped)
		) {
			return 'Processing PDF';
		}
		if (isAnalysisProcessing(row)) {
			return 'Processing';
		}
		if (!row.questionUploaded) {
			return 'Upload Homework PDF';
		}
		if (Boolean(stat?.status) && row.questionUploaded) {
			return 'Completed';
		}
		if (!row.answerUploaded) {
			return '(Optional)Upload Answer PDF';
		}
		if (getConversationCountForRow(row) === 0) {
			return 'Student interactions needed';
		}
		return 'Ready';
	}

	function isHomeworkActionBusy(row: HomeworkRow) {
		return Boolean(
			getRowDocUploading(row, 'question') ||
				getRowDocUploading(row, 'answer') ||
				getRowDocProcessing(row, 'question') ||
				getRowDocProcessing(row, 'answer') ||
				getRowDocStep(row, 'question') ||
				getRowDocStep(row, 'answer') ||
				isAnalysisProcessing(row)
		);
	}

	function getConversationCountForRow(row: HomeworkRow) {
		const keys = new Set<string>();
		if (row.modelId) keys.add(row.modelId);

		const matchedModel = availableModels.find((model) => model.id === row.modelId);
		if (matchedModel?.name) keys.add(matchedModel.name);

		let maxStudentCount = 0;
		for (const key of keys) {
			maxStudentCount = Math.max(maxStudentCount, convCountByModelId[key]?.studentCount ?? 0);
		}
		return maxStudentCount;
	}

	function getConversationCountDisplay(row: HomeworkRow) {
		const keys = new Set<string>();
		if (row.modelId) keys.add(row.modelId);

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

	type HomeworkActionButton =
		| { kind: 'upload'; label: 'Upload'; docType: HomeworkDocType; disabled?: boolean }
		| { kind: 'run'; label: 'Run'; disabled?: boolean }
		| { kind: 'rerun'; label: 'Re-run'; disabled?: boolean }
		| { kind: 'processing'; label: 'Processing'; disabled: true };

	function getHomeworkActionButtons(row: HomeworkRow): HomeworkActionButton[] {
		const status = getHomeworkAnalysisState(row);
		if (status === 'Uploading PDF' || status === 'Processing PDF' || status === 'Processing') {
			return [{ kind: 'processing', label: 'Processing', disabled: true }];
		}
		if (status === 'Upload Homework PDF') {
			return [{ kind: 'upload', label: 'Upload', docType: 'question' }];
		}
		if (status === '(Optional)Upload Answer PDF') {
			return [
				{ kind: 'upload', label: 'Upload', docType: 'answer' },
				{ kind: 'run', label: 'Run' }
			];
		}
		if (status === 'Completed') {
			return [{ kind: 'rerun', label: 'Re-run' }];
		}
		return [{ kind: 'run', label: 'Run' }];
	}

	function shouldShowStaleInfo(row: HomeworkRow): boolean {
		return getHomeworkAnalysisState(row) === 'Completed' && Boolean(getHomeworkStaleTooltip(row));
	}

	function triggerUploadPicker(row: HomeworkRow, docType: HomeworkDocType) {
		if (!row.id) return;
		const input = document.getElementById(
			`upload-${docType}-${row.id}`
		) as HTMLInputElement | null;
		input?.click();
	}

	async function handleHomeworkRunAction(row: HomeworkRow, rerun = false) {
		if (rerun) {
			pendingRunRow = row;
			showRunConfirmModal = true;
			return;
		}
		setAnalysisProcessingByHomeworkId(row.id, true);
		const ready = await validateRunPrerequisites(row);
		if (!ready) {
			setAnalysisProcessingByHomeworkId(row.id, false);
			return;
		}
		selectedHwForRun = row.id;
		selectedRunHomeworks = new Set([row.id]);
		syncRunSelectionFlags();
		await runAnalysis(row);
	}

	async function confirmRunAnalysis() {
		showRunConfirmModal = false;
		const row = pendingRunRow;
		pendingRunRow = null;
		if (!row) return;
		setAnalysisProcessingByHomeworkId(row.id, true);
		const ready = await validateRunPrerequisites(row);
		if (!ready) {
			setAnalysisProcessingByHomeworkId(row.id, false);
			return;
		}
		selectedHwForRun = row.id;
		selectedRunHomeworks = new Set([row.id]);
		syncRunSelectionFlags();
		await runAnalysis(row);
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
		setAnalysisProcessingByHomeworkId(targetHomeworkId, true);
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
			console.info('[AI Tutor][Instructor Setup] run requested', {
				groupId: $aiTutorSelectedGroupId,
				targetHomeworkId,
				modelId: row?.modelId ?? targetHomeworkId,
				selectedHomeworks: Array.from(selectedRunHomeworks)
			});
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
				console.info('[AI Tutor][Instructor Setup] analysis job created', {
					jobId,
					groupId: $aiTutorSelectedGroupId,
					targetHomeworkId,
					modelId: row?.modelId ?? targetHomeworkId
				});
				const persistedJob: PersistedInstructorJob = {
					jobId,
					type: 'analysis',
					groupId: $aiTutorSelectedGroupId,
					modelId: row?.modelId ?? targetHomeworkId,
					homeworkId: targetHomeworkId
				};
				clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
				upsertPersistedJob(persistedJob);
				testToast('Instructor Setup run analysis request submitted');
				toast.success('Analysis started successfully.');
				await monitorPersistedJob(persistedJob);
				clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
				await loadHomeworkStats($aiTutorSelectedGroupId);
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
			setAnalysisProcessingByHomeworkId(targetHomeworkId, false);
		}
	}
</script>

<div class="flex flex-col space-y-24 pt-4 pb-12">
	<div class="space-y-24">

		<!-- [Visual Guide: AI Tutor Workflow] -->
		<div class="rounded-xl border-2 border-[#57068C]/30 bg-gradient-to-br from-[#57068C]/5 to-transparent p-4 dark:border-purple-500/20 dark:from-purple-500/10">
			<button
				type="button"
				class="w-full flex items-center justify-between gap-2 mb-2"
				on:click={() => showAITutorWorkflow = !showAITutorWorkflow}
			>
				<div class="flex flex-col items-center text-center flex-1">
					<h3 class="text-lg font-bold text-gray-900 dark:text-gray-100">AI Tutor Workflow</h3>
					<p class="mt-0.5 text-xs text-gray-600 dark:text-gray-400">Follow these 3 steps to analyze and support your students</p>
				</div>
				<span class="text-gray-500 dark:text-gray-400">
					{#if showAITutorWorkflow}
						<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" /></svg>
					{:else}
						<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" /></svg>
					{/if}
				</span>
			</button>

			{#if showAITutorWorkflow}
			<!-- Flow Diagram -->
			<div class="flex items-center justify-between px-2 py-2">
				<!-- Step 1 Node -->
				<div class="flex flex-col items-center gap-1.5 min-h-[60px]">
					<div class="flex items-center justify-center w-12 h-12 rounded-full border-3 border-[#57068C] bg-white dark:bg-gray-900">
						<svg class="w-6 h-6 text-[#57068C]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
						</svg>
					</div>
					<p class="text-xs font-semibold text-gray-900 dark:text-gray-100 text-center">Setup</p>
				</div>

				<!-- Arrow 1 -->
				<div class="flex items-center gap-2 flex-1 mx-3">
					<div class="flex-1 h-1 bg-gradient-to-r from-[#57068C]/40 to-[#57068C]/20 dark:from-purple-500/30 dark:to-purple-500/10"></div>
					<svg class="w-5 h-5 text-[#57068C]/50 dark:text-purple-500/40 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
						<path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 10l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
					</svg>
				</div>

				<!-- Step 2 Node -->
				<div class="flex flex-col items-center gap-1.5 min-h-[60px]">
					<div class="flex items-center justify-center w-12 h-12 rounded-full border-3 border-[#57068C] bg-white dark:bg-gray-900">
						<svg class="w-6 h-6 text-[#57068C]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
						</svg>
					</div>
					<p class="text-xs font-semibold text-gray-900 dark:text-gray-100 text-center">Analyze</p>
				</div>

				<!-- Arrow 2 -->
				<div class="flex items-center gap-2 flex-1 mx-3">
					<svg class="w-5 h-5 text-[#57068C]/50 dark:text-purple-500/40 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
						<path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 10l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd" />
					</svg>
					<div class="flex-1 h-1 bg-gradient-to-r from-[#57068C]/20 to-[#57068C]/40 dark:from-purple-500/10 dark:to-purple-500/30"></div>
				</div>

				<!-- Step 3 Node -->
				<div class="flex flex-col items-center gap-1.5">
					<div class="flex items-center justify-center w-12 h-12 rounded-full border-3 border-[#57068C] bg-white dark:bg-gray-900">
						<svg class="w-6 h-6 text-[#57068C]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
						</svg>
					</div>
					<p class="text-xs font-semibold text-gray-900 dark:text-gray-100 text-center">Generate</p>
				</div>
			</div>

			<!-- Details -->
			<div class="flex justify-between gap-4 pt-2 border-t border-gray-200 dark:border-gray-800">
				<!-- Step 1 Details -->
				<div class="space-y-2 pt-2">
					<div class="flex items-center gap-2">
						<div class="w-1 h-4 bg-[#57068C] rounded-full"></div>
						<p class="text-xs font-bold text-gray-900 dark:text-gray-100">STEP 1: SETUP</p>
					</div>
					<ul class="space-y-2 text-sm text-gray-700 dark:text-gray-300">
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>Define error types</span>
						</li>
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span><strong>Upload homework & answers</strong></span>
						</li>
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>Customize prompts (optional)</span>
						</li>
					</ul>
				</div>

				<!-- Step 2 Details -->
				<div class="space-y-2 pt-2">
					<div class="flex items-center gap-2">
						<div class="w-1 h-4 bg-[#57068C] rounded-full"></div>
						<p class="text-xs font-bold text-gray-900 dark:text-gray-100">STEP 2: ANALYZE</p>
					</div>
					<ul class="space-y-2 text-sm text-gray-700 dark:text-gray-300">
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>View summary stats</span>
						</li>
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>Explore topic errors</span>
						</li>
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>Review student performance</span>
						</li>
					</ul>
				</div>

				<!-- Step 3 Details -->
				<div class="space-y-2 pt-2 h-full flex flex-col">
					<div class="flex items-center gap-2">
						<div class="w-1 h-4 bg-[#57068C] rounded-full"></div>
						<p class="text-xs font-bold text-gray-900 dark:text-gray-100">STEP 3: GENERATE</p>
					</div>
					<ul class="space-y-2 text-sm text-gray-700 dark:text-gray-300">
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>Generate practice questions</span>
						</li>
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span><strong>Review & approve</strong></span>
						</li>
						<li class="flex items-start gap-2">
							<span class="text-[#57068C] font-bold flex-shrink-0">→</span>
							<span>Send to students</span>
						</li>
					</ul>
				</div>
			</div>
			{/if}
		</div>

		<!-- [Standard Section: Error Type Configuration] -->
		<div class="space-y-4">
			<button
				type="button"
				class="flex w-full items-start justify-between gap-3 text-left"
				on:click={() => {
					showErrorTypeConfiguration = !showErrorTypeConfiguration;
				}}
			>
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
						1.Error Type Configuration
					</h2>
					<div class="text-xs text-gray-900 dark:text-gray-100">
						You can have at most 4 error types
					</div>
				</div>
				<span class="pt-1 text-gray-500 dark:text-gray-400">
					{#if showErrorTypeConfiguration}
						<ChevronUp className="size-4" />
					{:else}
						<ChevronDown className="size-4" />
					{/if}
				</span>
			</button>

			{#if showErrorTypeConfiguration}
			<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
				{#if hasLoadedHomework && homeworkFileRows.length === 0}
					<div class="flex items-center justify-center min-h-[10rem]">
						<p class="text-sm text-gray-400 dark:text-gray-500 text-center">
							It seems like there's no homework model for this group yet.<br />
							Please prepare your homework model first.
						</p>
					</div>
				{:else}
				<!-- Action Buttons Row -->
				<div class="flex flex-wrap items-center justify-end gap-2 mb-4">
					{#if !isEditingErrorTypes}
						<button
							type="button"
							class="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
							on:click={() => isEditingErrorTypes = true}
						>
							Edit
						</button>
					{:else}
						<!-- [Big Button] Add -->
						<button
							class={`flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
								errorTypeDefs.length < 4
									? 'border-[#57068C] text-[#57068C] hover:border-[#702B9D] hover:bg-purple-50 dark:border-purple-400 dark:text-purple-400 dark:hover:border-purple-300 dark:hover:bg-purple-900/20'
									: 'cursor-not-allowed border-gray-200 text-gray-400 dark:border-gray-700 dark:text-gray-500'
								}`}
							on:click={addErrorType}
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
						<!-- [Big Button] Reset to Default -->
						<button
							type="button"
							class="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
							on:click={() => {
								resetDefaultsModalMode = 'default';
								showResetDefaultsModal = true;
							}}
						>
							Reset to Default
						</button>
						{#if errorTypeDefs.length > 0}
							<!-- [Big Button] Delete All -->
							<button
								type="button"
								class="flex items-center gap-1 rounded-full border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 transition hover:border-red-300 hover:bg-red-50 dark:border-red-900/70 dark:text-red-300 dark:hover:border-red-800 dark:hover:bg-red-950/40"
								on:click={() => {
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
					{/if}
				</div>

				{#if errorTypeDefs.length === 0}
					<div
						class="rounded-lg border border-gray-200 bg-white px-4 py-6 text-sm text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-500"
					>
						No error types defined, please define error types
					</div>
				{:else}
					<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
						{#each errorTypeDefs as def, i}
							<div
								class="flex flex-col w-full px-3 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 transition hover:border-gray-300 hover:bg-gray-50 dark:hover:border-gray-600 dark:hover:bg-gray-800"
							>
								<div class="flex items-center justify-between">
									<div class="flex items-center gap-2 min-w-0 flex-1">
										<span
											class="h-4 w-4 rounded-full flex-shrink-0"
											style="background-color: {def.color};"
										></span>
										<div class="font-semibold text-gray-900 dark:text-gray-100 truncate">{def.type}</div>
									</div>
									<div class="flex items-center gap-0.5 flex-shrink-0">
										<!-- Edit Button (Pencil) -->
										<button
											type="button"
											class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
											on:click={() => openEditErrorType(i)}
										>
											<Pencil className="w-4 h-4" />
										</button>
										<!-- More Button with Dropdown Menu -->
										<Dropdown bind:show={showErrorTypeMenuOpen[i]}>
											<button
												slot="trigger"
												type="button"
												class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
												on:click={() => {
													showErrorTypeMenuOpen[i] = !showErrorTypeMenuOpen[i];
																	showErrorTypeMenuOpen = showErrorTypeMenuOpen;
												}}
											>
												<EllipsisHorizontal className="size-5" />
											</button>
											
											<div slot="content">
												<DropdownMenu.Content
													class="w-full max-w-[160px] rounded-xl px-1 py-1.5 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-sm"
													sideOffset={-2}
													side="bottom"
													align="start"
													transition={flyAndScale}
												>
													<DropdownMenu.Item
														class="flex gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md text-red-600 dark:text-red-400"
														on:click={() => {
															editingErrorTypeIndex = i;
															deleteErrorType();
															showErrorTypeMenuOpen[i] = false;
																						showErrorTypeMenuOpen = showErrorTypeMenuOpen;
														}}
													>
														<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4">
															<path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
														</svg>
														<span>Delete</span>
													</DropdownMenu.Item>
												</DropdownMenu.Content>
											</div>
										</Dropdown>
									</div>
								</div>
								<p class="mt-1 text-xs text-gray-600 dark:text-gray-300 line-clamp-2">
									{def.description || 'No description yet.'}
								</p>
							</div>
						{/each}
					</div>
				{/if}
				<div class="flex flex-wrap items-center justify-end gap-3 pt-4">
					<button
						class="rounded-full px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
						on:click={() => {
							draftErrorTypeDefs = originalErrorTypeDefs;
							isEditingErrorTypes = false;
						}}
					>
						Cancel
					</button>
					<button
						class={`w-20 rounded-full px-3 py-1.5 text-xs font-medium transition ${
							justSavedErrorTypes
								? 'cursor-default bg-gray-200 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
								: hasUnsavedErrorTypeChanges
									? 'bg-[#57068C] text-white hover:bg-[#702B9D]'
									: 'cursor-default bg-gray-200 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
							}}`}
						on:click={persistErrorTypes}
						disabled={!hasUnsavedErrorTypeChanges && !justSavedErrorTypes}
					>
						{justSavedErrorTypes ? 'Saved' : 'Save'}
					</button>
				</div>
				{/if}
			</div>
			{/if}
		</div>

		<!-- [Standard Section: Homework & Answer Files] -->
		<div class="space-y-4">
			<button
				type="button"
				class="flex w-full items-start justify-between gap-3 text-left"
				on:click={() => {
					showHomeworkAnswerFiles = !showHomeworkAnswerFiles;
				}}
			>
				<div>
					<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
						2.Homework & Answer Files
					</h2>
					<div class="text-xs text-gray-900 dark:text-gray-100">
						Upload the PDF files here before starting the analysis. Workspace model name must include "homework".
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
			<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
				<div
					class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5"
				>
					<table
						class="w-full text-sm text-left text-gray-500 dark:text-gray-400 rounded-sm"
					>
						<thead
							class="text-xs text-gray-700 uppercase bg-[#EEE6F3] dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5"
						>
								<tr>
									<th class="w-[16.666%] px-3 py-1.5 select-none">Homework</th>
									<th class="w-[16.666%] px-3 py-1.5 select-none">Homework PDF</th>
									<th class="w-[16.666%] px-3 py-1.5 select-none">(Optional)Answer PDF</th>
									<th class="w-[16.666%] px-3 py-1.5 select-none">Students Interacted</th>
									<th class="w-[16.666%] px-3 py-1.5 select-none">Status</th>
									<th class="w-[16.666%] px-3 py-1.5 select-none">Action</th>
								</tr>
						</thead>
						<tbody>
							{#if !$aiTutorSelectedGroupId && !useFrontendTestingData}
								<tr class="bg-white dark:bg-gray-900 text-xs">
									<td colspan="6" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
										Loading group selection...
									</td>
								</tr>
							{:else}
							{#if homeworkFileRows.length === 0}
								<tr class="bg-white dark:bg-gray-900 text-xs">
									<td colspan="6" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
										No homework models are found for this group.
									</td>
								</tr>
							{:else}
								{#each homeworkFileRows as row, i (row.id)}
									<tr
										class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
									>
										<!-- <td class="px-3 py-1 text-gray-500 dark:text-gray-400">
									<div class={homeworkModelNameCellClass}>{getHomeworkModelName(row.id)}</div>
								</td> -->
										<td
											class="px-3 py-1 font-semibold text-gray-900 dark:text-gray-100"
											title={row.displayModelName}
										>
											<div class={homeworkModelNameCellClass}>{row.displayModelName}</div>
										</td>
										<td class="px-3 py-1">
											<div class="flex items-center gap-1.5">
													<label class="cursor-pointer">
														<input
															id={`upload-question-${row.id}`}
															type="file"
															accept=".pdf"
															class="hidden"
															on:change={makeUploadHandler(row.id, 'question', row.modelId)}
														/>
													<span
														class="inline-flex items-center justify-center rounded-full border border-[#57068C]/40 p-1 text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
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
														</span>
													</label>
													{#if getRowDocUploading(row, 'question')}
														<span class="text-xs text-gray-500 dark:text-gray-400">Uploading PDF</span>
													{:else if getRowDocStep(row, 'question')}
														<span class="text-xs text-gray-500 dark:text-gray-400">{getRowDocStep(row, 'question')}</span>
													{:else if getRowDocProcessing(row, 'question')}
														<span class="text-xs text-gray-500 dark:text-gray-400">Processing PDF</span>
													{:else if row.questionFileName}
														<span class="text-xs {row.questionUploaded ? 'font-bold text-gray-900 dark:text-gray-100' : 'text-gray-500 dark:text-gray-400'}">{row.questionFileName}</span>
													{:else if row.questionUploaded}
														<span class="text-xs font-bold text-gray-900">Uploaded</span>
													{/if}
												</div>
											</td>
											<td class="px-3 py-1">
												<div class="flex items-center gap-1.5">
													<label class="cursor-pointer">
														<input
															id={`upload-answer-${row.id}`}
															type="file"
															accept=".pdf"
															class="hidden"
															on:change={makeUploadHandler(row.id, 'answer', row.modelId)}
													/>
													<span
														class="inline-flex items-center justify-center rounded-full border border-[#57068C]/40 p-1 text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
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
														</span>
													</label>
													{#if getRowDocUploading(row, 'answer')}
														<span class="text-xs text-gray-500 dark:text-gray-400">Uploading PDF</span>
													{:else if getRowDocStep(row, 'answer')}
														<span class="text-xs text-gray-500 dark:text-gray-400">{getRowDocStep(row, 'answer')}</span>
													{:else if getRowDocProcessing(row, 'answer')}
														<span class="text-xs text-gray-500 dark:text-gray-400">Processing PDF</span>
													{:else if row.answerUploaded}
															{#if row.answerSource === 'ai_generated'}
																<span class="text-xs font-bold text-gray-900 dark:text-gray-100">(Auto-Generated)</span>
														{:else if row.answerFileName}
															<span class="text-xs font-bold text-gray-900 dark:text-gray-100">{row.answerFileName}</span>
														{:else}
															<span class="text-xs font-bold text-gray-900">Uploaded</span>
														{/if}
													{/if}
												</div>
											</td>
										<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
											<div class="flex items-center gap-1.5">
												<span>{getConversationCountDisplay(row)}</span>
												<button
													type="button"
													disabled={isRefreshingConversationCounts}
													on:click|stopPropagation={() => {
														isRefreshingConversationCounts = true;
														loadConversationCounts($aiTutorSelectedGroupId);
													}}
													class="text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
													title={isRefreshingConversationCounts ? 'Refreshing...' : 'Refresh conversation counts'}
												>
													{#if isRefreshingConversationCounts}
														<Hourglass className="size-3.5" />
													{:else}
														<ArrowPath className="size-3.5" />
													{/if}
												</button>
											</div>
										</td>
										<td class="px-3 py-1">
												<div class="max-w-[12rem] whitespace-normal break-words leading-4">
															<div class="flex items-center gap-1.5">
																	<div class="text-xs font-medium text-gray-900 dark:text-gray-100">{getHomeworkAnalysisState(row)}</div>
																	
																{#if shouldShowStaleInfo(row)}
																				<Popover.Root>
																					<Popover.Trigger
																						type="button"
																					class="inline-block hover:text-[#57068C] transition-colors"
																				>
																						<svg
																							xmlns="http://www.w3.org/2000/svg"
																							viewBox="0 0 20 20"
																							fill="currentColor"
																							class="h-5 w-5 text-gray-400 dark:text-gray-500"
																						>
																							<path
																								fill-rule="evenodd"
																								d="M18 10A8 8 0 1 1 2 10a8 8 0 0 1 16 0ZM9 9a1 1 0 1 0 0 2v3a1 1 0 1 0 2 0v-3a1 1 0 1 0-2-2Zm1-4a1.25 1.25 0 1 0 0 2.5A1.25 1.25 0 0 0 10 5Z"
																								clip-rule="evenodd"
																							/>
																						</svg>
																					</Popover.Trigger>
																				<Popover.Content
																					side="top"
																					align="start"
																					sideOffset={6}
																					class="z-50 max-w-[16rem] rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700 shadow-lg dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
																				>
																					{#each getHomeworkStaleTooltip(row).split('\n').filter(Boolean) as line}
																						<p class="leading-relaxed">{line}</p>
																					{/each}
																				</Popover.Content>
																			</Popover.Root>
																				{/if}
														</div>
														{#if getHomeworkAnalysisState(row) === 'Processing'}
															<div class="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">
																Estimated 1 minute per student
															</div>
														{/if}
												</div>
												</td>
											<td class="px-3 py-1">
												<div class="flex items-center gap-1.5">
													{#each getHomeworkActionButtons(row) as action}
														{#if action.kind === 'upload'}
															<button
																type="button"
																class="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#57068C]/40 px-3 py-1 text-xs font-bold text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20 disabled:cursor-not-allowed disabled:opacity-50"
																on:click={() => triggerUploadPicker(row, action.docType)}
																disabled={Boolean(action.disabled)}
															>
																{action.label}
															</button>
														{:else if action.kind === 'processing'}
															<button
																type="button"
																class="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-gray-300 px-3 py-1 text-xs font-bold text-gray-500 dark:border-gray-600 dark:text-gray-400"
																disabled
															>
																{action.label}
															</button>
														{:else if action.kind === 'rerun'}
															<button
																type="button"
																class="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#57068C]/40 px-3 py-1 text-xs font-bold text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20 disabled:cursor-not-allowed disabled:opacity-50"
																on:click={() => {
																	void handleHomeworkRunAction(row, true);
																}}
																disabled={Boolean(action.disabled)}
															>
																{action.label}
															</button>
														{:else}
															<button
																type="button"
																class="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#57068C]/40 px-3 py-1 text-xs font-bold text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20 disabled:cursor-not-allowed disabled:opacity-50"
																on:click={() => {
																	void handleHomeworkRunAction(row, false);
																}}
																disabled={Boolean(action.disabled)}
															>
																{action.label}
															</button>
														{/if}
													{/each}
												</div>
											</td>
										</tr>
									{/each}
							{/if}
							{/if}

							<!-- Draft rows (always rendered, outside group conditional) -->
							{#each draftRows as draft, di (draft.uid)}
								<tr
									class="bg-white dark:bg-gray-900 text-xs border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
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
												class="inline-flex items-center justify-center rounded-full border border-[#57068C]/40 p-1 text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
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
												class="inline-flex items-center justify-center rounded-full border border-[#57068C]/40 p-1 text-[#57068C] transition hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
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
			</div>
			{/if}
		</div>

	<!-- (Optional)(Optional)Prompt Configuration Section -->
	<div class="space-y-4" bind:this={promptConfigurationSectionEl}>
		<button
			type="button"
			class="flex w-full items-start justify-between gap-3 text-left"
			on:click={togglePromptConfigurationSection}
		>
					<div>
						<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
							(Optional)Prompt Configuration
						</h2>
						<div class="text-xs text-gray-900 dark:text-gray-100">
							These prompts define how the AI processes homework, extracts topics, evaluates student responses, and generates practice problems. You can customize them to control accuracy, tone, and behavior.
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
		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div
				class="scrollbar-hidden relative max-w-full overflow-x-auto whitespace-nowrap rounded-sm pt-0.5"
			>
					<table
						class="max-w-full w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400"
					>
						<thead
							class="-translate-y-0.5 bg-[#EEE6F3] text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400"
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
									class="border-t border-gray-100 bg-white text-xs dark:border-gray-850 dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
								>
									<td class="px-3 py-1.5 font-medium text-gray-900 dark:text-white">{def.label}</td>
									<td class="px-3 py-1.5 text-gray-700 dark:text-gray-300">{def.usedFor}</td>
									<td class="px-3 py-1.5 text-gray-700 dark:text-gray-300">{promptSummary.scope}</td
									>
									<td class="px-3 py-1.5">
										<!-- in_button_style -->
										<button
											class="inline-flex items-center gap-1 rounded-full border border-[#57068C]/40 px-2.5 py-0.5 text-xs font-bold text-[#57068C] transition hover:bg-purple-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
											on:click={() => openPromptModal(def)}
										>
											<Pencil className="size-3" />
											Edit
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
			</div>
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
						disabled={selectedRunHomeworks.size === 0 || Object.values(runningAnalysisByHomeworkId).some(Boolean)}
						class="rounded-full border border-gray-300 px-3 py-1.5 text-left text-xs font-semibold text-gray-800 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
					>
						<div class="flex items-center gap-2">
							<span>{Object.values(runningAnalysisByHomeworkId).some(Boolean) ? 'Running…' : 'Run'}</span>
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
				{resetDefaultsModalMode === 'delete' ? 'Delete all custom error types?' : 'Revert to default error types?'}
			</div>
			<p class="mt-3 text-sm text-gray-500 dark:text-gray-400">
				{resetDefaultsModalMode === 'delete'
					? 'This will remove all current custom error types from the class configuration. Default error types will be used after refresh.'
					: 'Abandon all customized error types and revert to defaults?'}
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
{#if showRunConfirmModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		on:click|self={() => (showRunConfirmModal = false)}
		role="dialog"
		aria-modal="true"
	>
		<div class="w-[420px] max-w-[90vw] rounded-xl bg-white p-6 shadow-2xl dark:bg-gray-900">
			<div class="text-base font-semibold text-gray-900 dark:text-gray-100">
				Re-run analysis?
			</div>
			<p class="mt-3 text-sm text-gray-500 dark:text-gray-400">
				This will overwrite the existing analysis results. Are you sure?
			</p>
			<div class="mt-6 flex justify-end gap-2">
				<button
					class="px-3 py-1.5 text-sm text-gray-600 transition hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
					on:click={() => (showRunConfirmModal = false)}
				>
					Cancel
				</button>
				<button
					class="px-3 py-1.5 text-sm font-medium text-gray-900 transition hover:text-black dark:text-gray-100 dark:hover:text-white"
					on:click={confirmRunAnalysis}
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
					{selectedPromptScope === 'override' ? 'Set by User' : 'System Default'}
				</span>
			</div>

			<div class="mb-5 min-h-0 flex-1 overflow-y-auto pr-1">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5"
					>Prompt</label
				>
				<textarea
					class="min-h-[280px] w-full rounded-lg border border-gray-300 bg-white px-3 py-2 font-mono text-sm text-gray-900 focus:outline-none focus:ring-1 focus:ring-[#57068C] dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
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
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-[#57068C]"
					bind:value={editErrorTypeName}
					placeholder="Error type name"
				/>
			</div>

			<div class="mb-6">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5"
					>Description</label
				>
				<textarea
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-[#57068C] resize-none"
					rows="7"
					bind:value={editErrorTypeDescription}
					placeholder="Describe this error type..."
				></textarea>
			</div>

			<div class="mb-6">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Example (optional)</label>
				<textarea
					class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-[#57068C] resize-none"
					rows="4"
					bind:value={editErrorTypeExample}
					placeholder="Concrete example for LLM clarity..."
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

<!-- Bottom Spacer -->
<div class="h-[20vh]"></div>

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
