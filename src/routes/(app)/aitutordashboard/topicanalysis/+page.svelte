<script lang="ts">
	import { onMount } from 'svelte';
	import { Tooltip } from 'bits-ui';
	import { page } from '$app/stores';
	import { aiTutorSelectedGroupId } from '$lib/stores';
	import { aiTutorAllowedModelIds } from '$lib/stores/aiTutorWorkspaceModels';
	import { toast } from 'svelte-sonner';
	import { createNewModel, getModelById, updateModelById } from '$lib/apis/models';
	import {
		addFileToKnowledgeById,
		createNewKnowledge,
		updateKnowledgeById
	} from '$lib/apis/knowledge';
	import {
		AI_TUTOR_API_BASE_URL,
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
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Selector from '$lib/components/common/Selector.svelte';

	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;
	const testToast = showAITutorTestToast;
	const TOPIC_ANALYSIS_SESSION_TTL_MS = 5 * 60 * 1000;
	let lastSyncedGroupId = '';
	const dashboardPalette = ['#EE352E', '#00933C', '#B933AD', '#0039A6', '#FF6319', '#996633'];
	// Error type colors
	const errorTypeColors = ['#B588FF', '#60A5FA', '#5DD299', '#FF9E42'];
	const frontendTestingHomeworkModelNames = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester',
		'Homework4-MATH-Code-Section-Semester'
	];
	const homeworkModelNameCellClass =
		'max-w-[12rem] overflow-hidden whitespace-normal break-words leading-4 [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]';

	// Overflow detection for table cells with truncate
	let overflowStates: Record<string, boolean> = {};
	function overflowCheck(node: HTMLElement, key: string) {
		const check = () => {
			overflowStates[key] = node.scrollWidth > node.clientWidth;
			overflowStates = overflowStates;
		};
		const ro = new ResizeObserver(check);
		ro.observe(node);
		check();
		return {
			destroy() {
				ro.disconnect();
			}
		};
	}

	// Column resize (state resets on refresh)
	let topicTableEl: HTMLTableElement;
	let colWidths = [18, 6, 12, 40]; // percentages
	let resizingCol: number | null = null;
	let resizeStartX = 0;
	let resizeStartWidth = 0;
	let resizeNextStartWidth = 0;

	function initColResize(e: MouseEvent, index: number) {
		resizingCol = index;
		resizeStartX = e.pageX;
		resizeStartWidth = colWidths[index];
		if (index < colWidths.length - 1) {
			resizeNextStartWidth = colWidths[index + 1];
		}
		document.body.style.cursor = 'col-resize';
		document.body.style.userSelect = 'none';
		window.addEventListener('mousemove', handleColResize);
		window.addEventListener('mouseup', stopColResize);
	}

	function handleColResize(e: MouseEvent) {
		if (resizingCol === null || !topicTableEl) return;
		const tableWidth = topicTableEl.offsetWidth;
		const deltaPx = e.pageX - resizeStartX;
		const deltaPct = (deltaPx / tableWidth) * 100;
		const newWidth = Math.max(4, resizeStartWidth + deltaPct);

		// Adjust next column to keep total roughly stable
		if (resizingCol < colWidths.length - 1) {
			const nextNewWidth = Math.max(4, resizeNextStartWidth - deltaPct);
			colWidths[resizingCol + 1] = nextNewWidth;
		}
		colWidths[resizingCol] = newWidth;
		colWidths = [...colWidths];
	}

	function stopColResize() {
		resizingCol = null;
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		window.removeEventListener('mousemove', handleColResize);
		window.removeEventListener('mouseup', stopColResize);
	}

	// Group ID (needed for error-types endpoints)
	let groupId = '';
	$: groupId = $aiTutorSelectedGroupId || '';
	// Subscribe to store for group changes - prevents flash of wrong group data
	$: if (initialized && $aiTutorSelectedGroupId && $aiTutorSelectedGroupId !== lastSyncedGroupId) {
		lastSyncedGroupId = $aiTutorSelectedGroupId;
		void loadTopicAnalysisData();
		void loadPracticeQuestionData();
		void loadErrorTypes();
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
	let hasLoadedTopicAnalysisOnce = useFrontendTestingData;
	let practiceLoading = false;
	let hasLoadedPracticeOnce = useFrontendTestingData;
	let initialized = false;
	let _prevGroupIdForReset = '';
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
			if (!key || !key.startsWith(`${PRACTICE_JOB_STORAGE_PREFIX}:${$aiTutorSelectedGroupId}:`)) continue;
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
		console.log('[aitutordashboard]-[TopicAnalysis]-[JobsRestored]:', {
			groupId: $aiTutorSelectedGroupId,
			jobs: Object.entries(nextJobs).map(([homeworkId, job]) => ({
				homeworkId,
				jobId: job.jobId,
				step: job.step,
				status: job.status,
				startedAt: job.startedAt
			}))
		});
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
		const calledForGroupId = $aiTutorSelectedGroupId; // capture before any await
		testToast(`Topic Analysis fetch: error types group=${calledForGroupId || 'none'}`);
		if (useFrontendTestingData) {
			errorTypeDefs = $aiTutorFrontendTestingErrorTypes;
			return;
		}
		if (!calledForGroupId) return;
		try {
			const freshErrorTypes = await loadWithAITutorSessionCache({
				key: `topic-analysis:${calledForGroupId}:error-types`,
				ttlMs: TOPIC_ANALYSIS_SESSION_TTL_MS,
				onCached: (cached) => {
					if ($aiTutorSelectedGroupId === calledForGroupId) errorTypeDefs = cached;
				},
				loader: async () => {
					const res = await fetch(
						`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(calledForGroupId)}`,
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
			if ($aiTutorSelectedGroupId !== calledForGroupId) return; // stale
			errorTypeDefs = freshErrorTypes;
		} catch (e) {
			testToast('Topic Analysis failed loading error types');
			console.error('Error types fetch failed:', e);
		}
	}

	// Helper: persist current errorTypeDefs to server
	async function loadTopicAnalysisData() {
		const calledForGroupId = $aiTutorSelectedGroupId; // capture before any await
		testToast(`Topic Analysis fetch: analysis group=${calledForGroupId || 'none'}`);
		if (useFrontendTestingData) {
			topicGroupsByHomework = frontendTestingTopicByHomework;
			return;
		}
		if (!calledForGroupId) {
			return;
		}
		topicAnalysisLoading = true;
		try {
			const applyTopicAnalysisSnapshot = (snapshot: {
				homeworkRows: HomeworkPipelineRow[];
				topicGroupsByHomework: any[];
				homeworkIdsWithAnalysis: string[];
			}) => {
				if ($aiTutorSelectedGroupId !== calledForGroupId) return; // stale
				homeworkRows = snapshot.homeworkRows;
				topicGroupsByHomework = snapshot.topicGroupsByHomework;
				homeworkIdsWithAnalysis = new Set(snapshot.homeworkIdsWithAnalysis);
				hasLoadedTopicAnalysisOnce = true;
			};
			topicAnalysisLoading = !hasLoadedTopicAnalysisOnce && topicGroupsByHomework.length === 0;
			const snapshot = await loadWithAITutorSessionCache({
				key: `topic-analysis:${calledForGroupId}:analysis`,
				ttlMs: TOPIC_ANALYSIS_SESSION_TTL_MS,
				onCached: applyTopicAnalysisSnapshot,
				loader: async () => {
			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /homework/?group_id={group_id}
			// Purpose: scope topic analysis to homework that belongs to the selected group.
			const homeworkResponse = await fetch(`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(calledForGroupId)}`, {
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
					const allowedIds = $aiTutorAllowedModelIds;
					const filteredHomeworkRows = nextHomeworkRows.filter(
						(row) => row.modelId && allowedIds.has(row.modelId)
					);
					const homeworkIds = new Set(filteredHomeworkRows.map((row) => row.id));

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
							studentsMastered: Set<string>;
							studentsNotAttempted: Set<string>;
							studentsMixed: Set<string>;
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
								studentsMastered: new Set(),
								studentsNotAttempted: new Set(),
								studentsMixed: new Set(),
								errorTypeCount: new Map()
							});
						}
						const bucket = topicMap.get(topicName)!;
						const details: string = tp?.details ?? '';
						const studentId = row?.student_id ?? row?.student_email ?? 'unknown';

						for (const match of details.matchAll(/Q(\d+):/g)) {
							bucket.questionSet.add(`Q${match[1]}`);
						}

						// Parse per-question status to classify student state
						const statuses: string[] = [];
						for (const match of details.matchAll(/Q\d+:\s*(Solved|Attempted|Not Attempted)/g)) {
							statuses.push(match[1]);
						}
						const allSolved = statuses.length > 0 && statuses.every((s) => s === 'Solved');
						const allNotAttempted = statuses.length > 0 && statuses.every((s) => s === 'Not Attempted');
						const hasError = statuses.some((s) => s === 'Attempted');

						if (allSolved) {
							bucket.studentsMastered.add(studentId);
						} else if (allNotAttempted) {
							bucket.studentsNotAttempted.add(studentId);
						} else if (hasError) {
							bucket.studentsWithError.add(studentId);
							for (const match of details.matchAll(/\(([^)]+)\)/g)) {
								const et = match[1] || 'Others';
								if (et === 'Not Attempted') continue;
								bucket.errorTypeCount.set(et, (bucket.errorTypeCount.get(et) ?? 0) + 1);
							}
						} else {
							bucket.studentsMixed.add(studentId);
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
							studentsMastered: bucket.studentsMastered.size,
							studentsNotAttempted: bucket.studentsNotAttempted.size,
							studentsMixed: bucket.studentsMixed.size,
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
							homeworkRows: filteredHomeworkRows,
							topicGroupsByHomework: nextTopicGroupsByHomework,
							homeworkIdsWithAnalysis: Array.from(nextHomeworkIdsWithAnalysis)
						};
					}

					return {
						homeworkRows: filteredHomeworkRows,
						topicGroupsByHomework: [],
						homeworkIdsWithAnalysis: []
					};
				}
			});
			if ($aiTutorSelectedGroupId !== calledForGroupId) return; // stale — group changed while loading
			applyTopicAnalysisSnapshot(snapshot);
			console.log('[aitutordashboard]-[TopicAnalysis]-[DataLoaded]:', {
				groupId: calledForGroupId,
				homeworks: homeworkRows.map((row) => ({
					id: row.id,
					modelId: row.modelId ?? '',
					questionUploaded: row.questionUploaded,
					answerUploaded: row.answerUploaded,
					topicMapped: row.topicMapped
				})),
				homeworkIdsWithAnalysis: Array.from(homeworkIdsWithAnalysis)
			});
		} catch (error) {
			testToast('Topic Analysis failed loading /analysis data');
			console.error('Topic analysis API failed:', error);
		} finally {
			topicAnalysisLoading = false;
		}
	}

	async function loadPracticeQuestionData() {
		const calledForGroupId = $aiTutorSelectedGroupId; // capture before any await
		testToast(`Topic Analysis fetch: practice group=${calledForGroupId || 'none'}`);
		if (useFrontendTestingData) {
			practiceQuestions = frontendTestingPracticeQuestions;
			return;
		}
		if (!calledForGroupId) {
			return;
		}
		practiceLoading = !hasLoadedPracticeOnce && practiceQuestions.length === 0;
		try {
			const applyPracticeSnapshot = (snapshot: {
				practiceQuestions: any[];
				assignmentSentAtByPracticeId: Record<string, string>;
			}) => {
				if ($aiTutorSelectedGroupId !== calledForGroupId) return; // stale
				practiceQuestions = snapshot.practiceQuestions;
				assignmentSentAtByPracticeId = snapshot.assignmentSentAtByPracticeId;
				hasLoadedPracticeOnce = true;
			};
			const snapshot = await loadWithAITutorSessionCache({
				key: `topic-analysis:${calledForGroupId}:practice`,
				ttlMs: TOPIC_ANALYSIS_SESSION_TTL_MS,
				onCached: applyPracticeSnapshot,
				loader: async () => {
			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /homework/?group_id={group_id}
			// Purpose: build the group-scoped homework list used to label practice question sets.
			const homeworkResponse = await fetch(`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(calledForGroupId)}`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

			// Page: AI Tutor Dashboard > Topic Analysis
			// Endpoint: GET /practice?group_id={group_id}
			// Purpose: load the latest practice generation/review status for the selected group.
			const practiceResponse = await fetch(
				`${AI_TUTOR_API_BASE}/practice?group_id=${encodeURIComponent(calledForGroupId)}`,
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
			if ($aiTutorSelectedGroupId !== calledForGroupId) return; // stale — group changed while loading
			applyPracticeSnapshot(snapshot);
			console.log('[aitutordashboard]-[TopicAnalysis]-[PracticeLoaded]:', {
				groupId: calledForGroupId,
				practiceQuestions: practiceQuestions.map((practice) => ({
					homeworkId: practice.homeworkId ?? '',
					homeworkName: practice.homework ?? '',
					practiceId: practice.practiceId ?? '',
					status: practice.status ?? ''
				}))
			});
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
			`loading aitutordashboard - Topic Analysis | group=${$aiTutorSelectedGroupId || 'pending'} | frontend_testing=${String(useFrontendTestingData)}`
		);
		console.log('[aitutordashboard]-[TopicAnalysis]-[Mount]:', {
			pathname: $page.url.pathname,
			groupId: $aiTutorSelectedGroupId,
			groupIdFromUrl: $page.url.searchParams.get('group_id') || ''
		});
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

	$: if (initialized && !useFrontendTestingData && $aiTutorSelectedGroupId) {
		restorePersistedPracticeJobs();
	}

	$: if (initialized && !useFrontendTestingData && $aiTutorSelectedGroupId) {
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
					clearAITutorSessionCacheByPrefix(`topic-analysis:${$aiTutorSelectedGroupId}:analysis`);
					clearAITutorSessionCacheByPrefix(`topic-analysis:${$aiTutorSelectedGroupId}:practice`);
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

	// Reset per-homework action/error state when the group changes so that
	// failure banners and in-progress indicators from a previous group never bleed into the new one.
	$: if (initialized && $aiTutorSelectedGroupId && $aiTutorSelectedGroupId !== _prevGroupIdForReset) {
		_prevGroupIdForReset = $aiTutorSelectedGroupId;
		failedPracticeGenerationByHomeworkId = {};
		generatingPracticeByHomeworkId = {};
		generatingPracticeJobsByHomeworkId = {};
		sendingPracticeById = {};
		resumedPracticeJobIds = new Set();
	}

	$: if (initialized && !useFrontendTestingData && $aiTutorSelectedGroupId) {
		void loadTopicAnalysisData();
	}

	$: if (initialized && !useFrontendTestingData && $aiTutorSelectedGroupId) {
		void loadPracticeQuestionData();
	}

	$: if (initialized && !useFrontendTestingData && $aiTutorSelectedGroupId) {
		void loadErrorTypes();
	}
	// Keep the last successful instructor snapshot on screen while the layout is
	// still restoring group_id during tab switches. This avoids brief empty states
	// that would otherwise overwrite valid data until the next fetch completes.

	// Global error type definitions — source of truth for names, colors, descriptions
	let errorTypeDefs: { type: string; color: string; description: string }[] = [];

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

	function addErrorType() {
		if (errorTypeDefs.length >= 4) return;
		const color = errorTypeColors[errorTypeDefs.length % errorTypeColors.length];
		const newDef = { type: 'New Error Type', color, description: '' };
		errorTypeDefs = [...errorTypeDefs, newDef];
		// Add modal handling here if needed in future
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

		return [];
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
	$: topicAnalysisEmptyMessage = !$aiTutorSelectedGroupId && !useFrontendTestingData
		? '' // Don't show loading text - wait for store to populate (prevents flash)
		: homeworkRows.length === 0 && !useFrontendTestingData
			? 'No homework uploaded for this group yet.'
			: homeworkRows.length > 0 && homeworkRows.every((row) => !row.questionUploaded) && !useFrontendTestingData
				? 'Upload homework PDFs before topic analysis can be prepared.'
				: homeworkRows.length > 0 && homeworkRows.every((row) => !row.topicMapped) && !useFrontendTestingData
					? 'Homework processing is still preparing topics.'
					: 'No analysis data is available for the current filters. Run analysis first.';
	$: practiceQuestionsEmptyMessage = !$aiTutorSelectedGroupId && !useFrontendTestingData
		? '' // Don't show loading text - wait for store to populate (prevents flash)
		: homeworkRows.length === 0 && !useFrontendTestingData
			? 'No homework uploaded for this group yet.'
			: 'No practice question sets are available yet. Generate practice after analysis is completed.';

</script>

<div class="flex flex-col space-y-24 py-4 overflow-y-scroll">
	<!-- [Standard Section: Topic Analysis by Homework] -->
	<div class="space-y-4">
		<!-- Header Row with Title and Selectors -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h2 class="text-2xl font-semibold text-gray-800 dark:text-gray-200">Topic Analysis by Homework</h2>
			
			<!-- Selector Row -->
			<div class="flex flex-wrap items-center justify-end gap-2">
				<!-- [Selector] Homework -->
			<select
				bind:value={selectedTopicAnalysisHomework}
				class="rounded-full border border-gray-300 bg-white py-1.5 pl-3 pr-3 text-xs text-gray-700 cursor-pointer focus:outline-none dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200"
			>
				<option value="all">All Homeworks</option>
				{#each topicAnalysisHomeworkOptions as opt}
					<option value={opt.id}>{opt.label}</option>
				{/each}
			</select>

				<!-- [Selector] Topic -->
				<Selector
					size="sm"
					triggerClass="w-auto rounded-full border border-gray-300 bg-white py-1.5 pl-3 pr-8 text-xs text-gray-700 cursor-pointer focus:outline-none dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200"
					value={selectedTopicAnalysisTopic}
					placeholder="All Topics"
					searchEnabled={true}
					searchPlaceholder="Search topics"
					items={[
						{ value: 'all', label: 'All Topics' },
						...topicAnalysisTopicOptions.map((t) => ({ value: t, label: t }))
					]}
					on:change={(e) => { selectedTopicAnalysisTopic = e.detail.value; }}
				/>
				</div>
			</div>

		<!-- Table Card Container -->
		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div class="scrollbar-hidden relative overflow-x-auto rounded-sm pt-0.5">
			<table bind:this={topicTableEl} class="w-full min-w-[800px] table-fixed rounded-sm text-left text-sm text-gray-500 dark:text-gray-400">
				<thead class="sticky top-0 text-xs text-gray-700 uppercase bg-[#EEE6F3] dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5 z-10">
					<tr>
											<th scope="col" class="relative overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 select-none" style="width: {colWidths[0]}%">Homework<span class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[#57068C] dark:hover:bg-[#B588FF] z-10" on:mousedown|preventDefault={(e) => initColResize(e, 0)} /></th>
											<th scope="col" class="relative overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 select-none" style="width: {colWidths[1]}%">Questions in Topic<span class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[#57068C] dark:hover:bg-[#B588FF] z-10" on:mousedown|preventDefault={(e) => initColResize(e, 1)} /></th>
											<th scope="col" class="relative overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 select-none" style="width: {colWidths[2]}%">Students with Errors<span class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[#57068C] dark:hover:bg-[#B588FF] z-10" on:mousedown|preventDefault={(e) => initColResize(e, 2)} /></th>
											<th scope="col" class="relative overflow-hidden text-ellipsis whitespace-nowrap px-3 py-1.5 select-none" style="width: {colWidths[3]}%">Error Type Analysis<span class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[#57068C] dark:hover:bg-[#B588FF] z-10" on:mousedown|preventDefault={(e) => initColResize(e, 3)} /></th>
					</tr>
				</thead>
				<tbody>
					{#each filteredTopicGroupsByHomework as homework}
						<!-- Homework Header Row -->
						<tr
							class="bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition cursor-pointer"
							on:click={() => toggleHomework(homework.id)}
						>
							<td colspan="4" class="px-3 py-1.5">
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
											<div class="mt-0.5 flex min-w-0 items-center gap-1.5">
												<span
													use:overflowCheck={`${homework.id}-${topic.topic}`}
													class="overflow-hidden whitespace-nowrap text-gray-500 dark:text-gray-400"
												>
													{topic.questions}
												</span>
												{#if overflowStates[`${homework.id}-${topic.topic}`] && topic.questions}
													<Tooltip.Root openDelay={200}>
														<Tooltip.Trigger
															type="button"
															class="inline-flex flex-shrink-0 items-center cursor-pointer text-[#57068C] transition-colors hover:text-[#3e0470] dark:text-purple-400 dark:hover:text-purple-300 select-none"
															aria-label="View full question list"
														>
															<EllipsisHorizontal className="h-7 w-7" strokeWidth="2.5" />
														</Tooltip.Trigger>
														<Tooltip.Content
															side="bottom"
															align="start"
															sideOffset={4}
															class="z-50 max-w-[20rem] rounded-lg border border-gray-200 bg-white p-3 text-xs text-gray-700 shadow-lg dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
														>
															<div class="mb-2 text-xs font-semibold text-gray-500 dark:text-gray-400">
																Questions in this topic
															</div>
															<div class="flex flex-wrap gap-1">
																{#each topic.questions.split(', ') as q}
																	<span class="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-700 dark:bg-gray-700 dark:text-gray-300">
																		{q}
																	</span>
																{/each}
															</div>
														</Tooltip.Content>
													</Tooltip.Root>
												{/if}
											</div>
										</td>
									<td class="px-3 py-1.5">
										<span class="text-gray-900 dark:text-gray-100">{topic.studentsWithError}</span>
									</td>
									<td class="px-3 py-1.5">
										{#if getTopicDisplayErrorTypes(topic.errorTypes).length === 0}
											{#if errorTypeDefs.length === 0}
												<div class="flex items-center gap-2">
													<span class="text-gray-400 dark:text-gray-500 italic">Please add new error types</span>
													<button
														class="flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 leading-none text-base flex-shrink-0"
														on:click|stopPropagation={addErrorType}
														title="Add error type"
													>+</button>
												</div>
									{:else if topic.studentsMastered > 0 && topic.studentsWithError === 0 && topic.studentsNotAttempted === 0 && topic.studentsMixed === 0}
										<span class="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">
											<span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
											All mastered
										</span>
									{:else if topic.studentsNotAttempted > 0 && topic.studentsWithError === 0 && topic.studentsMastered === 0 && topic.studentsMixed === 0}
										<span class="inline-flex items-center gap-1 rounded-full bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300">
											<span class="w-1.5 h-1.5 rounded-full bg-yellow-500"></span>
											No attempts
										</span>
									{:else if topic.studentsWithError === 0 && (topic.studentsMastered > 0 || topic.studentsNotAttempted > 0 || topic.studentsMixed > 0)}
										<span class="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">
											<span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
											No errors
										</span>
											{:else}
												<span class="text-gray-400 dark:text-gray-500">—</span>
											{/if}
										{:else}
											<!-- Display the full-width color bar plus a readable percentage legend. -->
											<div class="flex items-center gap-2">
												<div class="flex h-3 min-w-0 flex-1 overflow-hidden rounded">
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
</div>

<!-- Bottom Spacer -->
<div class="h-[20vh]"></div>
</div>

<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
</style>
