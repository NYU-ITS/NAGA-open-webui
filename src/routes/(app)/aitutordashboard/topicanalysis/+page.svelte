<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { createNewModel, getModelById, updateModelById } from '$lib/apis/models';
	import {
		addFileToKnowledgeById,
		createNewKnowledge,
		updateKnowledgeById
	} from '$lib/apis/knowledge';
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
		loadWithAITutorSessionCache
	} from '$lib/utils/aiTutorSessionCache';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;
	const testToast = showAITutorTestToast;
	const TOPIC_ANALYSIS_SESSION_TTL_MS = 5 * 60 * 1000;
	const LAST_AI_TUTOR_GROUP_STORAGE_KEY = 'ai_tutor_last_selected_group_id';
	const dashboardPalette = ['#EE352E', '#00933C', '#B933AD', '#0039A6', '#FF6319', '#996633'];
	const errorTypeColors = dashboardPalette.slice(0, 4);
	const frontendTestingHomeworkModelNames = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester',
		'Homework4-MATH-Code-Section-Semester'
	];
	const homeworkModelNameCellClass =
		'max-w-[12rem] overflow-hidden whitespace-normal break-words leading-4 [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]';

	// Group ID (needed for error-types endpoints)
	let groupId = '';
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
	const frontendTestingTopicByHomework = [
		{
			id: frontendTestingHomeworkModelNames[0],
			homework: frontendTestingHomeworkModelNames[0],
			topics: [
				{
					topic: 'Linear Algebra',
					questions: 'Q1, Q2',
					questionCount: 2,
					studentsWithError: 4,
					errorTypes: [
						{ type: 'Conceptual', count: 4, percentage: 50, color: errorTypeColors[0] },
						{ type: 'Procedural', count: 4, percentage: 50, color: errorTypeColors[1] }
					]
				},
				{
					topic: 'Limit Definition',
					questions: 'Q3',
					questionCount: 1,
					studentsWithError: 3,
					errorTypes: [
						{ type: 'Conceptual', count: 2, percentage: 40, color: errorTypeColors[0] },
						{ type: 'Arithmetic', count: 3, percentage: 60, color: errorTypeColors[2] }
					]
				}
			]
		},
		{
			id: frontendTestingHomeworkModelNames[1],
			homework: frontendTestingHomeworkModelNames[1],
			topics: [
				{
					topic: 'Integration by Parts',
					questions: 'Q1, Q4',
					questionCount: 2,
					studentsWithError: 5,
					errorTypes: [
						{ type: 'Procedural', count: 6, percentage: 60, color: errorTypeColors[1] },
						{ type: 'Communication', count: 4, percentage: 40, color: errorTypeColors[3] }
					]
				},
				{
					topic: 'Factoring',
					questions: 'Q2',
					questionCount: 1,
					studentsWithError: 2,
					errorTypes: [
						{ type: 'Arithmetic', count: 2, percentage: 100, color: errorTypeColors[2] }
					]
				}
			]
		},
		{
			id: frontendTestingHomeworkModelNames[2],
			homework: frontendTestingHomeworkModelNames[2],
			topics: [
				{
					topic: 'Trigonometric Identities',
					questions: 'Q1, Q2',
					questionCount: 2,
					studentsWithError: 4,
					errorTypes: [
						{ type: 'Conceptual', count: 3, percentage: 37.5, color: errorTypeColors[0] },
						{ type: 'Procedural', count: 5, percentage: 62.5, color: errorTypeColors[1] }
					]
				}
			]
		},
		{
			id: frontendTestingHomeworkModelNames[3],
			homework: frontendTestingHomeworkModelNames[3],
			topics: [
				{
					topic: 'Trigonometric Identities',
					questions: 'Q3',
					questionCount: 1,
					studentsWithError: 3,
					errorTypes: [
						{ type: 'Communication', count: 1, percentage: 25, color: errorTypeColors[3] },
						{ type: 'Procedural', count: 3, percentage: 75, color: errorTypeColors[1] }
					]
				}
			]
		}
	];
	const frontendTestingPracticeQuestions = [
		{ homework: frontendTestingHomeworkModelNames[0], homeworkId: frontendTestingHomeworkModelNames[0], status: 'approved', date: 'Mar 12, 2026' },
		{ homework: frontendTestingHomeworkModelNames[1], homeworkId: frontendTestingHomeworkModelNames[1], status: 'ready' },
		{ homework: frontendTestingHomeworkModelNames[2], homeworkId: frontendTestingHomeworkModelNames[2], status: 'generating' },
		{ homework: frontendTestingHomeworkModelNames[3], homeworkId: frontendTestingHomeworkModelNames[3], status: 'not_ready' }
	];
	type HomeworkPipelineRow = {
		id: string;
		modelId: string | null;
		questionUploaded: boolean;
		answerUploaded: boolean;
		topicMapped: boolean;
	};
	let homeworkRows: HomeworkPipelineRow[] = [];
	let topicAnalysisLoading = false;
	let practiceLoading = false;
	let initialized = false;
	let generatingPracticeByHomeworkId: Record<string, boolean> = {};
	let sendingPracticeById: Record<string, boolean> = {};
	let generatingPracticeJobsByHomeworkId: Record<
		string,
		{ jobId: string; step: string; status: string; startedAt: string }
	> = {};
	let failedPracticeGenerationByHomeworkId: Record<
		string,
		{ message: string; failedAt: string }
	> = {};
	let resumedPracticeJobIds = new Set<string>();
	let homeworkIdsWithAnalysis = new Set<string>();
	let assignmentSentAtByPracticeId: Record<string, string> = {};
	const PRACTICE_JOB_STORAGE_PREFIX = 'ai_tutor_active_practice_job';

	function getPracticeJobStorageKey(groupId: string, homeworkId: string) {
		return `${PRACTICE_JOB_STORAGE_PREFIX}:${groupId}:${homeworkId}`;
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
		const nextJobs: Record<string, { jobId: string; step: string; status: string; startedAt: string }> = {};
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
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
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
		const practiceMarkdown = typeof latestPractice?.problem_data === 'string'
			? latestPractice.problem_data
			: '';
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

		// Mastery model sync is always overwrite-in-place: if a Mastery clone already exists,
		// replace its knowledge contents with the newly generated class-level practice set.
		let knowledgeId = getKnowledgeReferenceId(existingMasteryModel?.meta?.knowledge?.[0]);
		if (knowledgeId) {
			await fetch(`/api/v1/knowledge/${encodeURIComponent(knowledgeId)}/reset`, {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
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
					: buildPracticeKnowledgeMarkdownFromText(
							getHomeworkModelName(homeworkId),
							practiceMarkdown
						)
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

	// Helper: load error types from server
	async function loadErrorTypes() {
		testToast(`Topic Analysis fetch: error types group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			errorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			return;
		}
		if (!groupId) return;
		try {
			errorTypeDefs = await loadWithAITutorSessionCache({
				key: `topic-analysis:${groupId}:error-types`,
				ttlMs: TOPIC_ANALYSIS_SESSION_TTL_MS,
				onCached: (cached) => {
					errorTypeDefs = cached;
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
					const nextErrorTypes =
						errorTypes.length > 0
							? errorTypes.slice(0, 4).map((et, i) => ({
									type: et.name ?? 'Unknown',
									color: errorTypeColors[i % errorTypeColors.length],
									description: et.description ?? ''
								}))
							: [];
					testToast('Topic Analysis loaded error types');
					return nextErrorTypes;
				}
			});
		} catch (e) {
			testToast('Topic Analysis failed loading error types');
			console.error('Error types fetch failed:', e);
		}
	}

	// Helper: persist current errorTypeDefs to server
	async function persistErrorTypes() {
		testToast('Save error types is triggered | page=aitutordashboard - Topic Analysis');
		if (useFrontendTestingData) {
			aiTutorFrontendTestingErrorTypes.set(errorTypeDefs);
			toast.success('TestData error types saved.');
			return;
		}
		if (!groupId) return;
		try {
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(groupId)}`,
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
				clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:error-types`);
				testToast('Topic Analysis saved error types');
			}
		} catch (e) {
			testToast('Topic Analysis failed saving error types');
			console.error('Failed to persist error types:', e);
		}
	}

	// Delete all custom error types on server, then reload defaults
	async function deleteAllErrorTypes() {
		testToast('Use default error types is triggered | page=aitutordashboard - Topic Analysis');
		if (useFrontendTestingData) {
			errorTypeDefs = AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES;
			aiTutorFrontendTestingErrorTypes.set(AI_TUTOR_FRONTEND_TESTING_ERROR_TYPES);
			toast.success('TestData error types reset to defaults.');
			return;
		}
		if (!groupId) return;
		try {
			await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(groupId)}`,
				{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			testToast('Topic Analysis reset error types to default');
			clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:error-types`);
			await loadErrorTypes();
		} catch (e) {
			testToast('Topic Analysis failed resetting error types');
			console.error('Failed to delete error types:', e);
		}
	}

	async function loadTopicAnalysisData() {
		testToast(`Topic Analysis fetch: analysis group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			topicGroupsByHomework = frontendTestingTopicByHomework;
			return;
		}
		if (!groupId) {
			return;
		}
		topicAnalysisLoading = true;
		try {
			const applyTopicAnalysisSnapshot = (snapshot: {
				homeworkRows: HomeworkPipelineRow[];
				topicGroupsByHomework: any[];
				homeworkIdsWithAnalysis: string[];
			}) => {
				homeworkRows = snapshot.homeworkRows;
				topicGroupsByHomework = snapshot.topicGroupsByHomework;
				homeworkIdsWithAnalysis = new Set(snapshot.homeworkIdsWithAnalysis);
			};
			const snapshot = await loadWithAITutorSessionCache({
				key: `topic-analysis:${groupId}:analysis`,
				ttlMs: TOPIC_ANALYSIS_SESSION_TTL_MS,
				onCached: applyTopicAnalysisSnapshot,
				loader: async () => {
			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /homework/?group_id={group_id}
			// Purpose: scope topic analysis to homework that belongs to the selected group.
			const homeworkResponse = await fetch(`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(groupId)}`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});
			if (!homeworkResponse.ok) {
				throw new Error('Homework fetch failed');
			}
					const homeworkData = await homeworkResponse.json();
					const nextHomeworkRows = Array.isArray(homeworkData)
				? homeworkData.map((hw) => ({
						id: hw?.id ?? 'unknown',
						modelId: hw?.model_id ?? null,
						questionUploaded: hw?.question_uploaded ?? false,
						answerUploaded: hw?.answer_uploaded ?? false,
						topicMapped: hw?.topic_mapped ?? false
					}))
				: [];
					const homeworkIds = new Set(nextHomeworkRows.map((row) => row.id));

			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /analysis
			// Purpose: load raw analysis rows, then keep only rows whose homework_id belongs to the selected group.
			const topicResponse = await fetch(`${AI_TUTOR_API_BASE}/analysis`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

			if (!topicResponse.ok) {
				throw new Error('Topic analysis fetch failed');
			}

					const topicData = await topicResponse.json();
					if (Array.isArray(topicData)) {
				const nextHomeworkIdsWithAnalysis = new Set<string>();
				const grouped = new Map<
					string,
					Map<
						string,
						{
							questionSet: Set<string>;
							studentsWithError: Set<string>;
							errorTypeCount: Map<string, number>;
						}
					>
				>();

				for (const row of topicData) {
					const homeworkId = row?.homework_id ?? 'unknown';
					if (!homeworkIds.has(homeworkId)) continue;
					nextHomeworkIdsWithAnalysis.add(homeworkId);
					if (!grouped.has(homeworkId)) grouped.set(homeworkId, new Map());
					const topicMap = grouped.get(homeworkId)!;

					for (const tp of row?.topic_performances ?? []) {
						const topicName = tp?.topic_name ?? 'Unknown Topic';
						if (!topicMap.has(topicName)) {
							topicMap.set(topicName, {
								questionSet: new Set(),
								studentsWithError: new Set(),
								errorTypeCount: new Map()
							});
						}
						const bucket = topicMap.get(topicName)!;
						const details: string = tp?.details ?? '';

						for (const match of details.matchAll(/Q(\d+):/g)) {
							bucket.questionSet.add(`Q${match[1]}`);
						}

						for (const match of details.matchAll(/\(([^)]+)\)/g)) {
							const et = match[1] || 'Others';
							bucket.errorTypeCount.set(et, (bucket.errorTypeCount.get(et) ?? 0) + 1);
							bucket.studentsWithError.add(row?.student_id ?? row?.student_email ?? 'unknown');
						}
					}
				}

						const nextTopicGroupsByHomework = Array.from(grouped.entries()).map(([homeworkId, topicMap]) => {
					const topics = Array.from(topicMap.entries()).map(([topic, bucket]) => {
						const totalErrors = Array.from(bucket.errorTypeCount.values()).reduce((a, b) => a + b, 0);
						const errorTypes = Array.from(bucket.errorTypeCount.entries()).map(([type, count]) => ({
							type,
							count,
							percentage: totalErrors > 0 ? Number(((count / totalErrors) * 100).toFixed(1)) : 0,
							color: errorTypeDefs.find((d) => d.type === type)?.color ?? '#FFB84D'
						}));

						return {
							topic,
							questions: Array.from(bucket.questionSet).sort().join(', '),
							questionCount: bucket.questionSet.size,
							studentsWithError: bucket.studentsWithError.size,
							errorTypes
						};
					});

					return {
						id: homeworkId,
						homework: getHomeworkModelName(homeworkId),
						topics
					};
						});
						testToast('Topic Analysis loaded /analysis data');
						return {
							homeworkRows: nextHomeworkRows,
							topicGroupsByHomework: nextTopicGroupsByHomework,
							homeworkIdsWithAnalysis: Array.from(nextHomeworkIdsWithAnalysis)
						};
					}

					return {
						homeworkRows: nextHomeworkRows,
						topicGroupsByHomework: [],
						homeworkIdsWithAnalysis: []
					};
				}
			});
			applyTopicAnalysisSnapshot(snapshot);
		} catch (error) {
			testToast('Topic Analysis failed loading /analysis data');
			console.error('Topic analysis API failed:', error);
		} finally {
			topicAnalysisLoading = false;
		}
	}

	async function loadPracticeQuestionData() {
		testToast(`Topic Analysis fetch: practice group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			practiceQuestions = frontendTestingPracticeQuestions;
			return;
		}
		if (!groupId) {
			return;
		}
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
				key: `topic-analysis:${groupId}:practice`,
				ttlMs: TOPIC_ANALYSIS_SESSION_TTL_MS,
				onCached: applyPracticeSnapshot,
				loader: async () => {
			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /homework/?group_id={group_id}
			// Purpose: build the group-scoped homework list used to label practice question sets.
			const homeworkResponse = await fetch(`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(groupId)}`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /practice?group_id={group_id}
			// Purpose: load the latest practice generation/review status for the selected group.
			const practiceResponse = await fetch(
				`${AI_TUTOR_API_BASE}/practice?group_id=${encodeURIComponent(groupId)}`,
				{
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
				}
			);

			if (!practiceResponse.ok) {
				throw new Error('Practice question set fetch failed');
			}

					const homeworkData = homeworkResponse.ok ? await homeworkResponse.json() : [];
					const practiceData = await practiceResponse.json();
					if (Array.isArray(practiceData)) {
				const latestByHomework = new Map<string, any>();
				for (const row of practiceData) {
					const homeworkId = row?.homework_id ?? 'unknown';
					const prev = latestByHomework.get(homeworkId);
					const prevVersion = Number(prev?.version_number ?? -1);
					const currVersion = Number(row?.version_number ?? -1);
					if (!prev || currVersion >= prevVersion) {
						latestByHomework.set(homeworkId, row);
					}
				}

				const homeworkIds = new Set<string>();
				for (const hw of Array.isArray(homeworkData) ? homeworkData : []) {
					if (hw?.id) homeworkIds.add(hw.id);
				}
				for (const row of practiceData) {
					if (row?.homework_id) homeworkIds.add(row.homework_id);
				}

				const latestPracticeIds = Array.from(latestByHomework.values())
					.map((row) => row?.id)
					.filter(Boolean);
				const nextAssignmentSentAtByPracticeId: Record<string, string> = {};

				await Promise.all(
					latestPracticeIds.map(async (practiceId) => {
						try {
							// Page: AI Tutor Dashboard > Topic Analysis
							// Endpoint: GET /assignment?practice_problem_id={practice_id}
							// Purpose: detect whether this approved practice set has already been sent to students.
							const assignmentResponse = await fetch(
								`${AI_TUTOR_API_BASE}/assignment?practice_problem_id=${encodeURIComponent(practiceId)}`,
								{
									method: 'GET',
									headers: {
										Authorization: `Bearer ${localStorage.token}`
									}
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
						const nextPracticeQuestions = Array.from(homeworkIds).sort().map((homeworkId) => {
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

						testToast('Topic Analysis loaded /practice data');
						return {
							practiceQuestions: nextPracticeQuestions,
							assignmentSentAtByPracticeId: nextAssignmentSentAtByPracticeId
						};
					}

					return {
						practiceQuestions: [],
						assignmentSentAtByPracticeId: {}
					};
				}
			});
			applyPracticeSnapshot(snapshot);
		} catch (error) {
			testToast('Topic Analysis failed loading /practice data');
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

	async function pollPipelineJob(
		jobId: string,
		intervalMs = 4000,
		onUpdate?: (data: any) => void
	) {
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
		testToast(`Generate practice is triggered | page=aitutordashboard - Topic Analysis | homework=${homeworkId}`);

		try {
			// Planned Mastery-model flow:
			// after class-level practice generation succeeds, the instructor flow should clone
			// the source workspace model into a new "Mastery*" workspace model and replace that
			// clone's knowledge base with the generated class practice set.
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
				[homeworkId]: {
					jobId,
					step: 'queued',
					status: 'queued',
					startedAt
				}
			};
			persistPracticeJobState(homeworkId, {
				jobId,
				step: 'queued',
				status: 'queued',
				startedAt
			});
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
			clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:analysis`);
			clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:practice`);
			await loadPracticeQuestionData();
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
			`Send is triggered | page=aitutordashboard - Topic Analysis | practice=${practice.practiceId} | homework=${practice.homeworkId}`
		);

		try {
			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: POST /assignment/assign?practice_id={practice_id}
			// Purpose: distribute an approved practice set to students based on their weak topics.
			// Each student assignment is expected to remain a subset of the class-level practice set.
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/assignment/assign?practice_id=${encodeURIComponent(practice.practiceId)}`,
				{
					method: 'POST',
					headers: {
						Authorization: `Bearer ${localStorage.token}`
					}
				}
			);
			if (!response.ok) {
				const detail = await response.text();
				throw new Error(detail || 'Failed to send practice to students.');
			}
			clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:practice`);
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
		testToast(
			`loading aitutordashboard - Topic Analysis | group=${groupId || 'pending'} | frontend_testing=${String(useFrontendTestingData)}`
		);
		console.log('AI Tutor Dashboard - Topic Analysis loaded');
		initialized = true;
		if (useFrontendTestingData) {
			homeworkRows = frontendTestingTopicByHomework.map((item) => ({
				id: item.id,
				modelId: item.homework,
				questionUploaded: true,
				answerUploaded: true,
				topicMapped: true
			}));
			topicGroupsByHomework = frontendTestingTopicByHomework;
			practiceQuestions = frontendTestingPracticeQuestions;
			errorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			return;
		}
		restorePersistedPracticeJobs();
	});

	$: if (initialized && !useFrontendTestingData && groupId) {
		restorePersistedPracticeJobs();
	}

	$: if (initialized && !useFrontendTestingData && groupId) {
		for (const [homeworkId, job] of Object.entries(generatingPracticeJobsByHomeworkId)) {
			if (!job?.jobId || !generatingPracticeByHomeworkId[homeworkId]) continue;
			if (resumedPracticeJobIds.has(job.jobId)) continue;
			resumedPracticeJobIds = new Set([...resumedPracticeJobIds, job.jobId]);
			generatingPracticeByHomeworkId = {
				...generatingPracticeByHomeworkId,
				[homeworkId]: false
			};
			generatingPracticeByHomeworkId = {
				...generatingPracticeByHomeworkId,
				[homeworkId]: true
			};
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
					clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:analysis`);
					clearAITutorSessionCacheByPrefix(`topic-analysis:${groupId}:practice`);
					await loadPracticeQuestionData();
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

	$: if (initialized && !useFrontendTestingData && groupId) {
		void loadTopicAnalysisData();
	}

	$: if (initialized && !useFrontendTestingData && groupId) {
		void loadPracticeQuestionData();
	}

	$: if (initialized && !useFrontendTestingData && groupId) {
		void loadErrorTypes();
	}
	// Keep the last successful instructor snapshot on screen while the layout is
	// still restoring group_id during tab switches. This avoids brief empty states
	// that would otherwise overwrite valid data until the next fetch completes.

	// Global error type definitions — source of truth for names, colors, descriptions
	let errorTypeDefs: { type: string; color: string; description: string }[] = [];

	// Modal state
	let showEditModal = false;
	let showResetDefaultsModal = false;
	let editingIndex: number | null = null;
	let editingIsNew = false;
	let editName = '';
	let editDescription = '';

	// Reactive: compute uniform display percentages (25% each, Others gets remainder)
	$: displayErrorTypes = (() => {
		const n = errorTypeDefs.length;
		if (n === 0) return [];
		const othersPercent = 100 - n * 25;
		const result: { type: string; color: string; percentage: number }[] = errorTypeDefs.map((def) => ({
			type: def.type,
			color: def.color,
			percentage: 25
		}));
		if (othersPercent > 0) {
			result.push({ type: 'Others', color: '#FFB84D', percentage: othersPercent });
		}
		return result;
	})();

	function openEdit(index: number) {
		editingIndex = index;
		editingIsNew = false;
		editName = errorTypeDefs[index].type;
		editDescription = errorTypeDefs[index].description;
		showEditModal = true;
	}

	async function saveEdit() {
		if (editingIndex === null) return;
		errorTypeDefs[editingIndex] = { ...errorTypeDefs[editingIndex], type: editName, description: editDescription };
		errorTypeDefs = [...errorTypeDefs];
		closeModal();
		await persistErrorTypes();
	}

	async function deleteType() {
		if (editingIndex === null) return;
		errorTypeDefs = errorTypeDefs.filter((_, i) => i !== editingIndex);
		closeModal();
		await persistErrorTypes();
	}

	function addErrorType() {
		if (errorTypeDefs.length >= 4) return;
		const color = errorTypeColors[errorTypeDefs.length % errorTypeColors.length];
		const newDef = { type: 'New Error Type', color, description: '' };
		errorTypeDefs = [...errorTypeDefs, newDef];
		editingIndex = errorTypeDefs.length - 1;
		editingIsNew = true;
		editName = newDef.type;
		editDescription = '';
		showEditModal = true;
	}

	function getTopicDisplayErrorTypes(errorTypes) {
		if (errorTypes?.length) {
			const errorTypeMap = new Map(errorTypes.map((errorType) => [errorType.type, errorType]));
			const orderedDefinedErrorTypes = errorTypeDefs
				.map((definition) => {
					const matchingErrorType = errorTypeMap.get(definition.type);
					if (!matchingErrorType) return null;
					return {
						...matchingErrorType,
						color: definition.color
					};
				})
				.filter(Boolean);
			const fallbackErrorTypes = errorTypes
				.filter((errorType) => !errorTypeDefs.some((definition) => definition.type === errorType.type))
				.map((errorType) => ({
					...errorType,
					color: errorType.color ?? '#FFB84D'
				}));
			return [...orderedDefinedErrorTypes, ...fallbackErrorTypes];
		}

		if (displayErrorTypes.length) {
			return displayErrorTypes;
		}

		return [];
	}

	function closeModal() {
		showEditModal = false;
		editingIndex = null;
		editingIsNew = false;
	}

	async function confirmResetDefaults() {
		showResetDefaultsModal = false;
		await deleteAllErrorTypes();
	}

	// State for expandable homework sections
	let expandedHomework = new Set<string>();
	let selectedTopicAnalysisHomework = 'all';
	let selectedTopicAnalysisTopic = 'all';
	let lastTopicAnalysisFilterKey = '';

	function getHomeworkModelName(homework: string) {
		// homework name is now homework model name
		return homeworkRows.find((row) => row.id === homework)?.modelId ?? homework;
	}

	function toggleHomework(id: string) {
		if (expandedHomework.has(id)) {
			expandedHomework.delete(id);
		} else {
			expandedHomework.add(id);
		}
		expandedHomework = expandedHomework; // Trigger reactivity
	}

	let topicGroupsByHomework = [];
	$: reviewQuestionSetBaseHref = groupId
		? `/aitutordashboard/topicanalysis/reviewquestionset?group_id=${encodeURIComponent(groupId)}`
		: '/aitutordashboard/topicanalysis/reviewquestionset';
	$: topicAnalysisHomeworkOptions = topicGroupsByHomework.map((homework) => ({
		id: homework.id,
		label: getHomeworkModelName(homework.homework)
	}));
	$: topicAnalysisTopicOptions = Array.from(
		new Set(topicGroupsByHomework.flatMap((homework) => homework.topics.map((topic) => topic.topic)))
	).sort();
	$: filteredTopicGroupsByHomework = topicGroupsByHomework
		.filter((homework) =>
			selectedTopicAnalysisHomework === 'all' ? true : homework.id === selectedTopicAnalysisHomework
		)
		.map((homework) => ({
			...homework,
			topics:
				selectedTopicAnalysisTopic === 'all'
					? homework.topics
					: homework.topics.filter((topic) => topic.topic === selectedTopicAnalysisTopic)
		}))
		.filter((homework) => homework.topics.length > 0);
	$: if (
		selectedTopicAnalysisHomework !== 'all' &&
		!topicGroupsByHomework.some((homework) => homework.id === selectedTopicAnalysisHomework)
	) {
		selectedTopicAnalysisHomework = 'all';
	}
	$: if (
		selectedTopicAnalysisTopic !== 'all' &&
		!topicAnalysisTopicOptions.includes(selectedTopicAnalysisTopic)
	) {
		selectedTopicAnalysisTopic = 'all';
	}
	$: {
		const nextFilterKey = `${selectedTopicAnalysisHomework}|${selectedTopicAnalysisTopic}|${filteredTopicGroupsByHomework
			.map((homework) => homework.id)
			.join(',')}`;
		if (nextFilterKey !== lastTopicAnalysisFilterKey) {
			if (filteredTopicGroupsByHomework.length > 0) {
				const visibleHomeworkIds = new Set(filteredTopicGroupsByHomework.map((homework) => homework.id));
				const persistedExpandedHomework = new Set(
					Array.from(expandedHomework).filter((id) => visibleHomeworkIds.has(id))
				);
				if (selectedTopicAnalysisHomework !== 'all' || selectedTopicAnalysisTopic !== 'all') {
					expandedHomework = new Set(filteredTopicGroupsByHomework.map((homework) => homework.id));
				} else if (persistedExpandedHomework.size > 0) {
					expandedHomework = persistedExpandedHomework;
				} else {
					expandedHomework = new Set([filteredTopicGroupsByHomework[0].id]);
				}
			} else if (topicGroupsByHomework.length > 0) {
				expandedHomework = new Set([topicGroupsByHomework[0].id]);
			} else {
				expandedHomework = new Set();
			}
			lastTopicAnalysisFilterKey = nextFilterKey;
		}
	}
	let practiceQuestions = [];
	$: topicAnalysisEmptyMessage = !groupId && !useFrontendTestingData
		? 'Select a group to view topic analysis.'
		: homeworkRows.length === 0 && !useFrontendTestingData
			? 'No homework uploaded for this group yet.'
			: homeworkRows.length > 0 && homeworkRows.every((row) => !row.questionUploaded) && !useFrontendTestingData
				? 'Upload homework PDFs before topic analysis can be prepared.'
				: homeworkRows.length > 0 && homeworkRows.every((row) => !row.topicMapped) && !useFrontendTestingData
					? 'Homework processing is still preparing topics.'
					: 'No analysis data is available for the current filters. Run analysis first.';
	$: practiceQuestionsEmptyMessage = !groupId && !useFrontendTestingData
		? 'Select a group to view practice question sets.'
		: homeworkRows.length === 0 && !useFrontendTestingData
			? 'No homework uploaded for this group yet.'
			: 'No practice question sets are available yet. Generate practice after analysis is completed.';

</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Topic Analysis by Homework -->
	<div class="space-y-3">
		<div class="flex flex-wrap items-center justify-between gap-4">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">
				Topic Analysis by Homework
			</h2>
			<div class="flex flex-wrap items-center gap-3">
				<select
					bind:value={selectedTopicAnalysisHomework}
					class=" bg-white px-3 py-1.5 text-sm text-gray-800 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
				>
					<option value="all">All Homeworks</option>
					{#each topicAnalysisHomeworkOptions as option}
						<option value={option.id}>{option.label}</option>
					{/each}
				</select>
				<select
					bind:value={selectedTopicAnalysisTopic}
					class="bg-white px-3 py-1.5 text-sm text-gray-800 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
				>
					<option value="all">All Topics</option>
					{#each topicAnalysisTopicOptions as topic}
						<option value={topic}>{topic}</option>
					{/each}
				</select>
			</div>
		</div>

		<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
			<table class="w-full table-fixed rounded-sm text-left text-sm text-gray-500 dark:text-gray-400">
				<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						<th scope="col" class="w-[28%] px-3 py-1.5">Homework</th>
						<th scope="col" class="w-[14%] whitespace-nowrap px-3 py-1.5">Questions in Topic</th>
						<th scope="col" class="w-[14%] whitespace-nowrap px-3 py-1.5">Students with Error</th>
						<th scope="col" class="w-[44%] px-3 py-1.5">Error Type Analysis</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredTopicGroupsByHomework as homework}
						<!-- Homework Header Row -->
						<tr
							class="bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition cursor-pointer"
							on:click={() => toggleHomework(homework.id)}
						>
							<td class="px-3 py-1.5">
								<div class="grid grid-cols-[12px_minmax(0,1fr)] items-start gap-2">
									<div class="pt-0.5">
										{#if expandedHomework.has(homework.id)}
											<ChevronDown className="size-3 flex-shrink-0" />
										{:else}
											<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-3 flex-shrink-0">
												<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
											</svg>
										{/if}
									</div>
									<div class={`font-semibold text-xs text-gray-900 dark:text-gray-100 ${homeworkModelNameCellClass}`}>
										{getHomeworkModelName(homework.homework)}
									</div>
								</div>
							</td>
							<td colspan="3"></td>
						</tr>

						<!-- Topics (expanded) -->
						{#if expandedHomework.has(homework.id)}
							{#each homework.topics as topic}
								<tr class="bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition text-xs">
									<td class="px-3 py-1.5">
										<div class="grid grid-cols-[12px_minmax(0,1fr)] items-start gap-2">
											<div></div>
											<div class="min-w-0 text-gray-900 dark:text-gray-100">
												<div class={homeworkModelNameCellClass}>
													{topic.topic}
												</div>
											</div>
										</div>
									</td>
									<td class="px-3 py-1.5">
										<div class="text-gray-900 dark:text-gray-100">{topic.questionCount}</div>
										<div class="mt-0.5 truncate text-gray-500 dark:text-gray-400">
											[{topic.questions}]
										</div>
									</td>
									<td class="px-3 py-1.5">
										<span class="text-gray-900 dark:text-gray-100">{topic.studentsWithError}</span>
									</td>
									<td class="px-3 py-1.5">
										{#if getTopicDisplayErrorTypes(topic.errorTypes).length === 0}
											<div class="flex items-center gap-2">
												<span class="text-gray-400 dark:text-gray-500 italic">Please add new error types</span>
												<button
													class="flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 leading-none text-base flex-shrink-0"
													on:click|stopPropagation={addErrorType}
													title="Add error type"
												>+</button>
											</div>
										{:else}
											<!-- Display the full-width color bar plus a readable percentage legend. -->
											<div class="flex items-center gap-2">
												<div class="flex h-5 min-w-0 flex-1 overflow-hidden rounded">
													{#each getTopicDisplayErrorTypes(topic.errorTypes) as errorType}
														<div
															style="width: {errorType.percentage}%; background-color: {errorType.color};"
															title="{errorType.type}: {errorType.percentage}%"
														></div>
													{/each}
												</div>
												{#if errorTypeDefs.length < 4}
													<button
														class="flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 leading-none text-base flex-shrink-0"
														on:click|stopPropagation={addErrorType}
														title="Add error type"
													>+</button>
												{/if}
											</div>
											<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1">
												{#each getTopicDisplayErrorTypes(topic.errorTypes) as errorType}
													<div class="flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-gray-600 dark:text-gray-400">
														<span
															class="h-2.5 w-2.5 flex-shrink-0 rounded-full"
															style="background-color: {errorType.color};"
														></span>
														<span class="truncate">
															{errorType.type}: {errorType.percentage}%
														</span>
													</div>
												{/each}
											</div>
										{/if}
									</td>
								</tr>
							{/each}
						{/if}
					{/each}
					{#if topicAnalysisLoading}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="4" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">Loading topic analysis...</td>
						</tr>
					{:else if filteredTopicGroupsByHomework.length === 0}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="4" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">{topicAnalysisEmptyMessage}</td>
						</tr>
					{/if}
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
			<!-- <div class="flex items-center gap-3">
				<button
					type="button"
					class="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
					on:click={confirmResetDefaults}
				>
					Use default
				</button>
				<div class="flex items-center gap-2">
				{#if errorTypeDefs.length < 4}
					<button
						class="flex items-center gap-1 rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:border-gray-500 dark:hover:bg-gray-800"
						on:click={addErrorType}
						title="Add error type"
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
						title="Reset error types to defaults"
					>
						<span>Delete All</span>
						<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3 h-3">
							<path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
						</svg>
					</button>
				{/if}
				</div>
			</div> -->
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
						on:click={() => openEdit(i)}
					>
						<div class="flex items-center gap-2">
							<span class="h-4 w-4 rounded-full flex-shrink-0" style="background-color: {def.color};"></span>
							<div class="text-sm font-medium text-gray-900 dark:text-gray-100">{def.type}</div>
						</div>
						<p class="mt-2 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
							{def.description || 'No description yet.'}
						</p>
					</button>
				{/each}
			</div>
		{/if}

	</div>
	<div class="flex justify-end gap-3">
				<!-- <button
				class="rounded-full bg-black px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800"
				on:click={persistErrorTypes}
			>
				Save
			</button> -->

	<a
		href="/aitutordashboard/instructorsetup"
		class="inline-flex w-fit items-center rounded-full border border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-800 transition hover:border-[#57068c] hover:text-[#57068c] dark:border-gray-600 dark:text-gray-200 dark:hover:border-white dark:hover:text-white"
	>
		Configure in Setup &gt;
	</a>

	</div>

	{#if showResetDefaultsModal}
		<div
			class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
			on:click|self={() => {
				showResetDefaultsModal = false;
			}}
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
						on:click={() => {
							showResetDefaultsModal = false;
						}}
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

	<!-- Practice Question Set -->
	<div class="space-y-3">
		<div class="flex items-center justify-between gap-4">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Practice Question Set</h2>
			<a
				href={reviewQuestionSetBaseHref}
				class="inline-flex w-fit items-center rounded-full border border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-800 transition hover:border-[#57068c] hover:text-[#57068c] dark:border-gray-600 dark:text-gray-200 dark:hover:border-white dark:hover:text-white"
			>
				View All
			</a>
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
									<div class={homeworkModelNameCellClass}>{getHomeworkModelName(practice.homework)}</div>
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
											<a
												href={`${reviewQuestionSetBaseHref}${reviewQuestionSetBaseHref.includes('?') ? '&' : '?'}homework_id=${encodeURIComponent(practice.homeworkId ?? '')}`}
												class="self-center w-fit whitespace-nowrap rounded-xl px-2 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-black/5 dark:text-gray-300 dark:hover:bg-white/5"
											>
												View
											</a>
											{#if practice.status === 'approved'}
												<button
													type="button"
													class="self-center flex w-fit items-center gap-1 whitespace-nowrap rounded-xl px-2 py-1.5 text-xs font-semibold text-gray-700 transition hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:text-gray-300 dark:hover:bg-white/5"
													on:click={() => sendPracticeToStudents(practice)}
													disabled={!practice.practiceId || sendingPracticeById[practice.practiceId]}
												>
													{sendingPracticeById[practice.practiceId] ? 'Sending…' : 'Send'}
													<!-- <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-3">
														<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
													</svg> -->
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

	<!-- Error Type Edit Modal -->
	{#if showEditModal}
		<div
			class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
			on:click|self={closeModal}
			role="dialog"
			aria-modal="true"
		>
			<div class="bg-white dark:bg-gray-900 rounded-xl shadow-2xl p-6 w-[520px] max-w-[90vw]">
				<!-- Modal Header -->
				<div class="flex justify-between items-center mb-5">
					<h3 class="text-base font-semibold text-gray-900 dark:text-gray-100">
						{editingIsNew ? 'Add Error Type' : 'Edit Error Type'}
					</h3>
					<button
						class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
						on:click={closeModal}
						aria-label="Close"
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
							<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
						</svg>
					</button>
				</div>

				<hr class="border-gray-100 dark:border-gray-700 mb-5" />

				<!-- Name field -->
				<div class="mb-4">
					<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Name</label>
					<input
						class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
						bind:value={editName}
						placeholder="Error type name"
					/>
				</div>

				<!-- Description field (doubled size) -->
				<div class="mb-6">
					<label class="text-xs font-medium text-gray-600 dark:text-gray-400 block mb-1.5">Description</label>
					<textarea
						class="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
						rows="7"
						bind:value={editDescription}
						placeholder="Describe this error type..."
					></textarea>
				</div>

				<!-- Action Buttons -->
				<div class="flex justify-between items-center">
					{#if !editingIsNew}
						<button
							class="px-3 py-1.5 text-sm text-red-500 hover:text-red-700 dark:hover:text-red-400 transition"
							on:click={deleteType}
						>Delete</button>
					{:else}
						<div></div>
					{/if}
					<div class="flex gap-2">
						<button
							class="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition"
							on:click={closeModal}
						>Cancel</button>
						<button
							class="px-3 py-1.5 text-sm font-medium text-gray-900 dark:text-gray-100 hover:text-black dark:hover:text-white transition"
							on:click={saveEdit}
						>Save</button>
					</div>
				</div>
			</div>
		</div>
	{/if}

</div>

<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
</style>
