<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { aiTutorSelectedGroupId } from '$lib/stores';
	import { aiTutorAllowedModelIds } from '$lib/stores/aiTutorWorkspaceModels';
	import { toast } from 'svelte-sonner';
	import {
		AI_TUTOR_API_BASE_URL,
		AI_TUTOR_FRONTEND_TESTING_MODE,
		TESTING_AI_TUTOR
	} from '$lib/constants';
	import { getUsers } from '$lib/apis/users';
	import { getGroupById } from '$lib/apis/groups';
	import { showAITutorTestToast } from '$lib/utils/aiTutorTesting';
	import {
		clearAITutorSessionCacheByGroup,
		loadWithAITutorSessionCache
	} from '$lib/utils/aiTutorSessionCache';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Search from '$lib/components/icons/Search.svelte';
import Tooltip from '$lib/components/common/Tooltip.svelte';

	const AI_TUTOR_API_BASE = AI_TUTOR_API_BASE_URL;
	const useFrontendTestingData = AI_TUTOR_FRONTEND_TESTING_MODE;
	const testToast = showAITutorTestToast;
	const STUDENT_ANALYSIS_SESSION_TTL_MS = 5 * 60 * 1000;
	let lastSyncedGroupId = '';
	const frontendTestingHomeworkModelNames = [
		'Homework1-MATH-Code-Section-Semester',
		'Homework2-MATH-Code-Section-Semester',
		'Homework3-MATH-Code-Section-Semester',
		'Homework4-MATH-Code-Section-Semester'
	];

	type SortField = 'name' | 'accuracy' | null;
	type SortOrder = 'asc' | 'desc' | null;

	type HomeworkOption = {
		id: string;
		label: string;
		group_id?: string | null;
		model_id?: string | null;
		question_uploaded?: boolean;
		topic_mapped?: boolean;
	};

	type StudentRow = {
		id: string;
		studentId: string;
		name: string;
		email: string;
		homeworkId: string;
		avgAccuracy: number | null;
		topicsToImprove: string;
		performanceSummary: string;
		hasAnalysis: boolean;
	};

	let initialized = false;
	let loading = false;
	let hasLoadedOnce = useFrontendTestingData;
	let sortField: SortField = null;
	let sortOrder: SortOrder = null;
	let search = '';
	let selectedHomework = 'All';
	let homeworkOptions: HomeworkOption[] = [];
	let studentData: StudentRow[] = [];
	let homeworkMetaById: Record<string, HomeworkOption> = {};
	const homeworkModelNameCellClass =
		'max-w-[12rem] overflow-hidden whitespace-normal break-words leading-4 [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]';
	let availableUsers = [];
	let selectedGroupUserIds: string[] = [];
	let syncRequestId = 0;

	function getHomeworkModelName(homework: string) {
		// Student analysis rows store the AI Tutor homework id, but the UI should
		// always resolve and display the linked workspace model name when possible.
		return homeworkMetaById[homework]?.label ?? homework;
	}

	async function downloadStudentReport(student: StudentRow) {
		testToast(`Download Report is triggered | page=aitutordashboard - Student Analysis | student=${student.studentId}`);
		if (!student.id || !student.hasAnalysis) {
			toast.error('Analysis not available for download.');
			return;
		}
		try {
			const url = `${AI_TUTOR_API_BASE}/analysis/export/${encodeURIComponent(student.id)}`;
			const res = await fetch(url, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) {
				const text = await res.text().catch(() => 'Download failed');
				throw new Error(text);
			}
			const blob = await res.blob();
			const filename = res.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/)?.[1] || `${student.name}_analysis.pdf`;
			const link = document.createElement('a');
			link.href = URL.createObjectURL(blob);
			link.download = filename;
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(link.href);
			toast.success(`Downloaded report for ${student.name}`);
		} catch (e) {
			console.error('Download report failed:', e);
			toast.error(e instanceof Error ? e.message : 'Download report failed.');
		}
	}
	const frontendTestingHomeworkOptions: HomeworkOption[] = [
		{ id: frontendTestingHomeworkModelNames[0], label: frontendTestingHomeworkModelNames[0], group_id: 'frontend-testing-group', model_id: 'gpt-4o-mini' },
		{ id: frontendTestingHomeworkModelNames[1], label: frontendTestingHomeworkModelNames[1], group_id: 'frontend-testing-group', model_id: 'gpt-4o-mini' },
		{ id: frontendTestingHomeworkModelNames[2], label: frontendTestingHomeworkModelNames[2], group_id: 'frontend-testing-group', model_id: 'claude-3-5-sonnet' },
		{ id: frontendTestingHomeworkModelNames[3], label: frontendTestingHomeworkModelNames[3], group_id: 'frontend-testing-group', model_id: 'claude-3-5-sonnet' }
	];
	const frontendTestingStudentRows: StudentRow[] = [
		{
			id: 'analysis-1',
			studentId: 'student-1',
			name: 'Annie Case',
			email: 'annie@example.edu',
			homeworkId: frontendTestingHomeworkModelNames[0],
			avgAccuracy: 92.3,
			topicsToImprove: 'Limit Definition',
			performanceSummary: 'Attempted 14/15, solved 13, errors 1.'
		},
		{
			id: 'analysis-2',
			studentId: 'student-2',
			name: 'John Smith',
			email: 'john@example.edu',
			homeworkId: frontendTestingHomeworkModelNames[1],
			avgAccuracy: 76.5,
			topicsToImprove: 'Integration by Parts, Factoring',
			performanceSummary: 'Attempted 12/15, solved 10, errors 2.'
		},
		{
			id: 'analysis-3',
			studentId: 'student-3',
			name: 'Mia Wong',
			email: 'mia@example.edu',
			homeworkId: frontendTestingHomeworkModelNames[2],
			avgAccuracy: 84.6,
			topicsToImprove: 'Trigonometric Identities',
			performanceSummary: 'Attempted 13/15, solved 11, errors 2.'
		},
		{
			id: 'analysis-4',
			studentId: 'student-4',
			name: 'Leo Patel',
			email: 'leo@example.edu',
			homeworkId: frontendTestingHomeworkModelNames[3],
			avgAccuracy: 68.8,
			topicsToImprove: 'Trigonometric Identities, Limit Definition',
			performanceSummary: 'Attempted 11/16, solved 9, errors 2.'
		}
	];

$: isFilterActive = selectedHomework !== 'All' || search.trim() !== '';

	// Subscribe to store for group changes - prevents flash of wrong group data
	$: if (initialized && $aiTutorSelectedGroupId !== lastSyncedGroupId) {
		lastSyncedGroupId = $aiTutorSelectedGroupId;
		// Clear group-scoped data when switching away so stale rows don't persist
		homeworkOptions = [];
		homeworkMetaById = {};
		studentData = [];
		selectedGroupUserIds = [];
		if ($aiTutorSelectedGroupId) {
			void syncStudentAnalysisData($aiTutorSelectedGroupId);
		}
	}

	onMount(async () => {
		// Page: AI Tutor Dashboard > Student Analysis
		// Purpose: load user context immediately, then wait for the layout to select the
		// default group before issuing group-scoped homework/member requests.
		testToast(
			`loading aitutordashboard - Student Analysis | group=${$aiTutorSelectedGroupId || 'pending'} | frontend_testing=${String(useFrontendTestingData)}`
		);
		initialized = true;
		console.log('AI Tutor Dashboard - Student Analysis mount', {
			pathname: $page.url.pathname,
			groupId: $aiTutorSelectedGroupId,
			groupIdFromUrl: $page.url.searchParams.get('group_id') || '',
			selectedHomework
		});
		if (useFrontendTestingData) {
			homeworkOptions = frontendTestingHomeworkOptions;
			homeworkMetaById = Object.fromEntries(frontendTestingHomeworkOptions.map((option) => [option.id, option]));
			studentData = frontendTestingStudentRows;
			selectedGroupUserIds = frontendTestingStudentRows.map((row) => row.studentId);
			return;
		}
		document.addEventListener('visibilitychange', handleVisibilityChange);
	});

	onDestroy(() => {
		document.removeEventListener('visibilitychange', handleVisibilityChange);
	});

	function handleVisibilityChange() {
		if (document.visibilityState === 'visible' && !useFrontendTestingData && $aiTutorSelectedGroupId) {
			// When returning to this tab, invalidate cache and force refresh
			// so that changes made on other pages (Instructor Setup / Summary) are visible.
			clearAITutorSessionCacheByGroup($aiTutorSelectedGroupId);
			void syncStudentAnalysisData($aiTutorSelectedGroupId);
		}
	}



	function getStudentAnalysisSessionKey(groupId: string, resource: string) {
		return `student-analysis:${groupId || 'global'}:${resource}`;
	}

	async function syncStudentAnalysisData(groupId: string) {
		if (!initialized || useFrontendTestingData) {
			return;
		}

		if (!groupId) {
			return;
		}

		const requestId = ++syncRequestId;
		loading = !hasLoadedOnce && studentData.length === 0;

		try {
			const [users, groupUserIds, nextHomeworks] = await Promise.all([
				loadUserContext(),
				loadSelectedGroupContext(groupId),
				loadHomeworks(groupId)
			]);

			if (requestId !== syncRequestId) {
				return;
			}

			availableUsers = users;
			selectedGroupUserIds = groupUserIds;
			homeworkOptions = nextHomeworks;
			homeworkMetaById = Object.fromEntries(nextHomeworks.map((option) => [option.id, option]));

			if (
				selectedHomework !== 'All' &&
				!nextHomeworks.some((option) => option.id === selectedHomework)
			) {
				selectedHomework = 'All';
			}

			const analysesByHomeworkId = await loadAllHomeworkAnalyses(groupId, nextHomeworks);
			if (requestId !== syncRequestId) {
				return;
			}

			studentData = buildStudentRowsForHomeworks(nextHomeworks, analysesByHomeworkId, users, groupUserIds);
			hasLoadedOnce = true;
			testToast('Student Analysis loaded all homework analyses');
			console.log('AI Tutor Dashboard - Student Analysis data loaded', {
				groupId,
				selectedHomework,
				homeworks: nextHomeworks.map((homework) => ({
					id: homework.id,
					name: homework.label,
					modelId: homework.model_id ?? ''
				})),
				studentCount: studentData.length,
				groupUserIds
			});
		} catch (error) {
			testToast('Student Analysis failed loading group data');
			console.error('Student Analysis sync failed:', error);
		} finally {
			if (requestId === syncRequestId) {
				loading = false;
			}
		}
	}

	async function loadHomeworks(groupId: string): Promise<HomeworkOption[]> {
		testToast(`Student Analysis fetch: homework list group=${groupId || 'none'}`);
		if (!initialized) {
			return [];
		}

		if (useFrontendTestingData) {
			return frontendTestingHomeworkOptions;
		}

		if (!groupId) {
			return [];
		}

		return loadWithAITutorSessionCache({
			key: getStudentAnalysisSessionKey(groupId, 'homeworks'),
			ttlMs: STUDENT_ANALYSIS_SESSION_TTL_MS,
			loader: async () => {
			// Page: AI Tutor Dashboard > Student Analysis
			// Endpoint: GET /homework/?group_id={group_id}
			// Purpose: fetch every homework for the selected group once, then let the page
			// filter per-homework on the client without re-requesting on every tab switch.
				const response = await fetch(
					`${AI_TUTOR_API_BASE}/homework/?group_id=${encodeURIComponent(groupId)}`,
					{
						method: 'GET',
						headers: {
							Authorization: `Bearer ${localStorage.token}`
						}
					}
				);

				if (!response.ok) {
					throw new Error('Homework fetch failed');
				}

				const data = await response.json();
				const nextOptions = Array.isArray(data)
					? data.map((row, index) => ({
							id: row?.id,
							label: row?.model_id ? row.model_id : `Homework${index + 1}-MATH-Code-Section-Semester`,
							group_id: row?.group_id,
							model_id: row?.model_id,
							question_uploaded: row?.question_uploaded ?? false,
							topic_mapped: row?.topic_mapped ?? false
						}))
					: [];

				const allowedIds = $aiTutorAllowedModelIds;
				const filteredOptions = nextOptions.filter(
					(opt) => opt.model_id && allowedIds.has(opt.model_id)
				);

				testToast('Student Analysis loaded homework list');
				return filteredOptions;
			}
		});
	}

	async function loadUserContext() {
		testToast('Student Analysis fetch: users');
		if (useFrontendTestingData) {
			return [];
		}
		return loadWithAITutorSessionCache({
			key: getStudentAnalysisSessionKey('global', 'users'),
			ttlMs: STUDENT_ANALYSIS_SESSION_TTL_MS,
			loader: async () => {
				const users = await getUsers(localStorage.token);
				return Array.isArray(users) ? users : [];
			}
		}).catch((error) => {
			console.error('User lookup failed:', error);
			return availableUsers;
		});
	}

	async function loadSelectedGroupContext(groupId: string): Promise<string[]> {
		testToast(`Student Analysis fetch: group members group=${groupId || 'none'}`);
		if (useFrontendTestingData) {
			return frontendTestingStudentRows.map((row) => row.studentId);
		}
		if (!initialized || !groupId) {
			return [];
		}

		return loadWithAITutorSessionCache({
			key: getStudentAnalysisSessionKey(groupId, 'group-members'),
			ttlMs: STUDENT_ANALYSIS_SESSION_TTL_MS,
			loader: async () => {
				const group = await getGroupById(localStorage.token, groupId);
				return Array.isArray(group?.user_ids) ? group.user_ids : [];
			}
		}).catch((error) => {
			console.error('Group lookup failed:', error);
			return selectedGroupUserIds;
		});
	}

	function buildGroupRosterRows(homeworkId: string) {
		return selectedGroupUserIds.map((userId) => {
			const matchedUser =
				availableUsers.find((user) => user.id === userId) ||
				availableUsers.find((user) => user.email === userId);

			return {
				id: `roster-${userId}-${homeworkId}`,
				studentId: userId,
				name: matchedUser?.name ?? matchedUser?.email?.split('@')[0] ?? userId,
				email: matchedUser?.email ?? 'Email Unavailable',
				homeworkId,
				avgAccuracy: null,
				topicsToImprove: 'Analysis Unavailable',
				performanceSummary: 'Analysis Unavailable',
				hasAnalysis: false
			};
		});
	}

	async function loadAllHomeworkAnalyses(groupId: string, homeworks: HomeworkOption[]) {
		if (!groupId || homeworks.length === 0) {
			return {} as Record<string, any[]>;
		}

		const analysisCacheKey = getStudentAnalysisSessionKey(
			groupId,
			`analyses:${homeworks
				.map((homework) => homework.id)
				.sort()
				.join(',')}`
		);

		return loadWithAITutorSessionCache({
			key: analysisCacheKey,
			ttlMs: STUDENT_ANALYSIS_SESSION_TTL_MS,
			loader: async () => {
				const analysisEntries = await Promise.all(
					homeworks.map(async (homework) => {
			// Page: AI Tutor Dashboard > Student Analysis
			// Endpoint: GET /analysis/?homework_id={homework_id}
			// Purpose: fetch every homework's analysis once for the current group so
			// switching homework filters or dashboard tabs does not trigger a fresh network call.
						const response = await fetch(
							`${AI_TUTOR_API_BASE}/analysis/?homework_id=${encodeURIComponent(homework.id)}`,
							{
								method: 'GET',
								headers: {
									Authorization: `Bearer ${localStorage.token}`
								}
							}
						);

						if (!response.ok) {
							throw new Error(`Student analysis fetch failed for homework ${homework.id}`);
						}

						const data = await response.json();
						return [homework.id, Array.isArray(data) ? data : []] as const;
					})
				);

				testToast('Student Analysis loaded /analysis data');
				return Object.fromEntries(analysisEntries);
			}
		});
	}

	function buildStudentRowsForHomeworks(
		homeworks: HomeworkOption[],
		analysesByHomeworkId: Record<string, any[]>,
		users: any[],
		groupUserIds: string[]
	) {
		return homeworks.flatMap((homework) => {
			const rosterRows = groupUserIds.map((userId) => {
				const matchedUser =
					users.find((user) => user.id === userId) ||
					users.find((user) => user.email === userId);

				return {
					id: `roster-${userId}-${homework.id}`,
					studentId: userId,
					name: matchedUser?.name ?? matchedUser?.email?.split('@')[0] ?? userId,
					email: matchedUser?.email ?? 'Email Unavailable',
					homeworkId: homework.id,
					avgAccuracy: null,
					topicsToImprove: 'Analysis Unavailable',
					performanceSummary: 'Analysis Unavailable',
					hasAnalysis: false
				};
			});

			const rosterByStudentId = new Map(rosterRows.map((row) => [row.studentId, row]));
			const rawAnalyses = Array.isArray(analysesByHomeworkId[homework.id])
				? analysesByHomeworkId[homework.id]
				: [];

			// Backend /analysis rows do not currently include group_id, so group scoping is enforced
			// here by matching the returned student_id against the selected Open WebUI group's user_ids.
			for (const row of rawAnalyses) {
				const matchedUser =
					users.find((user) => user.id === row?.student_id) ||
					users.find((user) => user.email === row?.student_email);
				const totalQuestion = Number(row?.total_question ?? 0);
				const totalSolved = Number(row?.total_solved ?? 0);
				const avgAccuracy = totalQuestion > 0 ? (totalSolved / totalQuestion) * 100 : 0;
				const weakTopics = Array.isArray(row?.topic_performances)
					? row.topic_performances
							.filter((tp) => tp?.status === 'needs_practice')
							.map((tp) => tp?.topic_name)
							.filter(Boolean)
					: [];
				const studentId = row?.student_id ?? matchedUser?.id ?? 'N/A';

				if (groupUserIds.length > 0 && !groupUserIds.includes(studentId)) {
					continue;
				}

				rosterByStudentId.set(studentId, {
					id: row?.id ?? `${studentId}-${homework.id}`,
					studentId,
					name:
						matchedUser?.name ??
						row?.student_email?.split('@')[0] ??
						row?.student_id ??
						'Unknown Student',
					email: row?.student_email ?? matchedUser?.email ?? 'Email Unavailable',
					homeworkId: row?.homework_id ?? homework.id,
					avgAccuracy: Number(avgAccuracy.toFixed(1)),
					topicsToImprove: weakTopics.length ? weakTopics.join(', ') : 'None',
					performanceSummary: `Attempted ${row?.total_attempted ?? 0}/${totalQuestion}, solved ${totalSolved}, errors ${row?.total_errors ?? 0}.`,
					hasAnalysis: true
				});
			}

			return Array.from(rosterByStudentId.values());
		});
	}

	function removeAllFilters() {
		search = '';
		selectedHomework = 'All';
	}

	function toggleSort(field: SortField) {
		if (sortField === field) {
			if (sortOrder === 'asc') {
				sortOrder = 'desc';
			} else if (sortOrder === 'desc') {
				sortOrder = null;
				sortField = null;
			}
		} else {
			sortField = field;
			sortOrder = 'asc';
		}
	}

	$: filteredAndSortedData = (() => {
		let data = [...studentData];

		if (selectedHomework !== 'All') {
			data = data.filter((student) => student.homeworkId === selectedHomework);
		}

		const query = search.trim().toLowerCase();
		if (query) {
			data = data.filter((student) => {
				return student.name.toLowerCase().includes(query) || student.email.toLowerCase().includes(query);
			});
		}

		if (sortField && sortOrder) {
			data.sort((a, b) => {
				let aValue: string | number;
				let bValue: string | number;

				if (sortField === 'name') {
					aValue = a.name.toLowerCase();
					bValue = b.name.toLowerCase();
				} else if (sortField === 'accuracy') {
					aValue = a.avgAccuracy;
					bValue = b.avgAccuracy;
				} else {
					return 0;
				}

				if (sortOrder === 'asc') {
					return aValue > bValue ? 1 : aValue < bValue ? -1 : 0;
				}

				return aValue < bValue ? 1 : aValue > bValue ? -1 : 0;
			});
		}

		return data;
	})();
	$: selectedHomeworkMeta =
		selectedHomework !== 'All' ? homeworkMetaById[selectedHomework] ?? null : null;
	$: studentAnalysisEmptyMessage = !$aiTutorSelectedGroupId && !useFrontendTestingData
		? 'Loading group selection...'
		: homeworkOptions.length === 0 && !useFrontendTestingData
			? 'No homework uploaded for this group yet.'
			: selectedHomeworkMeta && !selectedHomeworkMeta.question_uploaded && !useFrontendTestingData
				? 'Upload the homework PDF before student analysis can run.'
				: selectedHomeworkMeta && !selectedHomeworkMeta.topic_mapped && !useFrontendTestingData
					? 'Homework processing is still preparing topics.'
					: selectedHomework === 'All' && !useFrontendTestingData
						? 'No student analysis is available for this group yet.'
						: 'No group members are available for the selected homework.';
</script>

<div class="flex flex-col space-y-24 py-4">
	<!-- [Standard Section: Student Analysis] -->
	<div class="space-y-4">
		<!-- Header Row with Title and Selectors -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h2 class="text-2xl font-semibold text-gray-800 dark:text-gray-200">Student Analysis</h2>
			
			<!-- Selector Row -->
			<div class="flex flex-wrap items-center justify-end gap-2">
				<!-- [Selector] Homework -->
			<select
				bind:value={selectedHomework}
				class="rounded-full border border-gray-300 bg-white py-1.5 pl-3 pr-3 text-xs text-gray-700 cursor-pointer focus:outline-none dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200"
			>
				<option value="All">All Homeworks</option>
				{#each homeworkOptions as opt}
					<option value={opt.id}>{opt.label}</option>
				{/each}
			</select>

			<!-- [Selector] Search with X/magnify toggle -->
			<div class="relative w-52">
				<input
					class="w-full rounded-full border border-gray-300 bg-white py-1.5 pl-3 pr-8 text-xs text-gray-700 focus:outline-none dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200 placeholder:text-gray-400 dark:placeholder:text-gray-500"
					bind:value={search}
					placeholder="Search name or email"
				/>
				<div class="absolute inset-y-0 right-0 flex items-center pr-2.5">
					{#if search}
						<button
							type="button"
							on:click={() => (search = '')}
							class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
							aria-label="Clear search"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					{:else}
						<div class="pointer-events-none text-gray-400 dark:text-gray-500">
							<Search className="size-3.5" />
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>

		<!-- Table Card Container -->
		<div class="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
			<div class="scrollbar-hidden relative overflow-x-auto whitespace-nowrap rounded-sm pt-0.5">
				<table class="w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400">
				<thead class="-translate-y-0.5 bg-[#EEE6F3] text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400">
					<tr>
						<th scope="col" class="cursor-pointer select-none px-3 py-1.5" on:click={() => toggleSort('name')}>
							<div class="flex items-center gap-1.5">
								Student
								{#if sortField === 'name'}
									<span class="font-normal">
										{#if sortOrder === 'asc'}<ChevronUp className="size-2" />{:else}<ChevronDown className="size-2" />{/if}
									</span>
								{:else}
									<span class="invisible"><ChevronUp className="size-2" /></span>
								{/if}
							</div>
						</th>
						<th scope="col" class="px-3 py-1.5 select-none">Email</th>
						<th scope="col" class="w-[12rem] px-3 py-1.5 select-none">Homework</th>
						<th scope="col" class="cursor-pointer select-none px-3 py-1.5" on:click={() => toggleSort('accuracy')}>
							<div class="flex items-center gap-1.5">
								AVG Accuracy (%)
								{#if sortField === 'accuracy'}
									<span class="font-normal">
										{#if sortOrder === 'asc'}<ChevronUp className="size-2" />{:else}<ChevronDown className="size-2" />{/if}
									</span>
								{:else}
									<span class="invisible"><ChevronUp className="size-2" /></span>
								{/if}
							</div>
						</th>
						<th scope="col" class="px-3 py-1.5 select-none">Topics to be Improved</th>
						<th scope="col" class="px-3 py-1.5 select-none">Action</th>
					</tr>
				</thead>
				<tbody>
					{#if !$aiTutorSelectedGroupId && !useFrontendTestingData}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="6" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								Loading group selection...
							</td>
						</tr>
					{:else if homeworkOptions.length === 0 && !useFrontendTestingData}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="6" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								No homework uploaded for this group yet.
							</td>
						</tr>
					{:else if filteredAndSortedData.length === 0}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="6" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								{loading && !hasLoadedOnce ? 'Loading student analysis...' : studentAnalysisEmptyMessage}
							</td>
						</tr>
					{:else}
						{#each filteredAndSortedData as student}
							<tr class="border-t border-gray-100 bg-white text-xs dark:border-gray-850 dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition">
								<td class="px-3 py-1 font-medium text-gray-900 dark:text-white">{student.name}</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">{student.email}</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
									<div class={homeworkModelNameCellClass}>{getHomeworkModelName(student.homeworkId)}</div>
								</td>
								{#if !student.hasAnalysis}
									<td colspan="3" class="px-3 py-1 text-center text-gray-400 dark:text-gray-500">
										The analysis of this student&apos;s homework hasn&apos;t been available
									</td>
								{:else}
									<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
										{student.avgAccuracy.toFixed(1)}%
									</td>
									<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
										<Tooltip content={student.topicsToImprove} placement="top">
											<div class="max-w-[16rem] truncate cursor-default">{student.topicsToImprove}</div>
										</Tooltip>
									</td>
									<td class="px-3 py-1 text-gray-700 dark:text-gray-300">
										<!-- [Table Button: icon+name] Download Report -->
										<button
											type="button"
											class="inline-flex items-center gap-1 rounded-full border border-gray-300 px-2.5 py-1 text-xs font-bold text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
											on:click={() => downloadStudentReport(student)}
										>
											<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V4" /></svg>
											Download Report
										</button>
									</td>
								{/if}
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
	</div>
</div>
</div>

<!-- Bottom Spacer -->
<div class="h-[20vh]"></div>

<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
</style>
