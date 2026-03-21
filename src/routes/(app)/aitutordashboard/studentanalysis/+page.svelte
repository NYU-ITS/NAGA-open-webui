<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { AI_TUTOR_DUMMY_MODE, TESTING_AI_TUTOR } from '$lib/constants';
	import { getUsers } from '$lib/apis/users';
	import { getGroupById } from '$lib/apis/groups';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Search from '$lib/components/icons/Search.svelte';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';
	const useDummyData = AI_TUTOR_DUMMY_MODE;

	type SortField = 'name' | 'accuracy' | null;
	type SortOrder = 'asc' | 'desc' | null;

	type HomeworkOption = {
		id: string;
		label: string;
		group_id?: string | null;
		model_id?: string | null;
	};

	type StudentRow = {
		id: string;
		studentId: string;
		name: string;
		email: string;
		homeworkId: string;
		avgAccuracy: number;
		topicsToImprove: string;
		performanceSummary: string;
	};

	let initialized = false;
	let loading = false;
	let sortField: SortField = null;
	let sortOrder: SortOrder = null;
	let search = '';
	let selectedHomework = 'All';
	let homeworkOptions: HomeworkOption[] = [];
	let studentData: StudentRow[] = [];
	let availableUsers = [];
	let selectedGroupUserIds: string[] = [];
	const dummyHomeworkOptions: HomeworkOption[] = [
		{ id: 'Homework 1', label: 'Homework 1', group_id: 'dummy-group', model_id: 'gpt-4o-mini' },
		{ id: 'Homework 2', label: 'Homework 2', group_id: 'dummy-group', model_id: 'gpt-4o-mini' },
		{ id: 'Homework 3', label: 'Homework 3', group_id: 'dummy-group', model_id: 'claude-3-5-sonnet' },
		{ id: 'Homework 4', label: 'Homework 4', group_id: 'dummy-group', model_id: 'claude-3-5-sonnet' }
	];
	const dummyStudentRows: StudentRow[] = [
		{
			id: 'analysis-1',
			studentId: 'student-1',
			name: 'Annie Case',
			email: 'annie@example.edu',
			homeworkId: 'Homework 1',
			avgAccuracy: 92.3,
			topicsToImprove: 'Limit Definition',
			performanceSummary: 'Attempted 14/15, solved 13, errors 1.'
		},
		{
			id: 'analysis-2',
			studentId: 'student-2',
			name: 'John Smith',
			email: 'john@example.edu',
			homeworkId: 'Homework 2',
			avgAccuracy: 76.5,
			topicsToImprove: 'Integration by Parts, Factoring',
			performanceSummary: 'Attempted 12/15, solved 10, errors 2.'
		},
		{
			id: 'analysis-3',
			studentId: 'student-3',
			name: 'Mia Wong',
			email: 'mia@example.edu',
			homeworkId: 'Homework 3',
			avgAccuracy: 84.6,
			topicsToImprove: 'Trigonometric Identities',
			performanceSummary: 'Attempted 13/15, solved 11, errors 2.'
		},
		{
			id: 'analysis-4',
			studentId: 'student-4',
			name: 'Leo Patel',
			email: 'leo@example.edu',
			homeworkId: 'Homework 4',
			avgAccuracy: 68.8,
			topicsToImprove: 'Trigonometric Identities, Limit Definition',
			performanceSummary: 'Attempted 11/16, solved 9, errors 2.'
		}
	];

	$: selectedGroupId = $page.url.searchParams.get('group_id') || '';
	$: isFilterActive = selectedHomework !== 'All' || search.trim() !== '';

	onMount(async () => {
		initialized = true;
		console.log('AI Tutor Dashboard - Student Analysis loaded');
		if (useDummyData) {
			homeworkOptions = dummyHomeworkOptions;
			studentData = dummyStudentRows;
			selectedGroupUserIds = dummyStudentRows.map((row) => row.studentId);
			return;
		}
		await loadUserContext();
	});

	$: if (initialized) {
		void loadSelectedGroupContext(selectedGroupId);
	}

	$: if (initialized) {
		void loadHomeworks(selectedGroupId);
	}

	$: if (initialized) {
		void loadAnalyses(selectedHomework === 'All' ? null : selectedHomework);
	}

	async function loadHomeworks(groupId: string) {
		if (!initialized) {
			return;
		}

		if (useDummyData) {
			homeworkOptions = dummyHomeworkOptions;
			if (selectedHomework !== 'All' && !homeworkOptions.some((option) => option.id === selectedHomework)) {
				selectedHomework = 'All';
			}
			return;
		}

		if (!groupId) {
			homeworkOptions = [];
			selectedHomework = 'All';
			studentData = [];
			return;
		}

		try {
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
						label: row?.id ? `Homework ${index + 1}` : 'Untitled Homework',
						group_id: row?.group_id,
						model_id: row?.model_id
					}))
				: [];

			homeworkOptions = nextOptions;

			if (
				selectedHomework !== 'All' &&
				!nextOptions.some((option) => option.id === selectedHomework)
			) {
				selectedHomework = 'All';
			}

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Homework list loaded for selected group.');
			}
		} catch (error) {
			homeworkOptions = [];
			selectedHomework = 'All';
			studentData = [];
			if (TESTING_AI_TUTOR) {
				toast.warning('[FAIL][GET]: Homework list fetch failed.');
			}
			console.error('Homework fetch failed:', error);
		}
	}

	async function loadUserContext() {
		if (useDummyData) {
			availableUsers = [];
			return;
		}
		try {
			availableUsers = await getUsers(localStorage.token);
		} catch (error) {
			availableUsers = [];
			console.error('User lookup failed:', error);
		}
	}

	async function loadSelectedGroupContext(groupId: string) {
		if (useDummyData) {
			selectedGroupUserIds = dummyStudentRows.map((row) => row.studentId);
			return;
		}
		if (!initialized || !groupId) {
			selectedGroupUserIds = [];
			return;
		}

		try {
			const group = await getGroupById(localStorage.token, groupId);
			selectedGroupUserIds = Array.isArray(group?.user_ids) ? group.user_ids : [];
		} catch (error) {
			selectedGroupUserIds = [];
			console.error('Group lookup failed:', error);
		}
	}

	async function loadAnalyses(homeworkId: string | null) {
		if (!initialized) {
			return;
		}

		if (useDummyData) {
			studentData = homeworkId
				? dummyStudentRows.filter((row) => row.homeworkId === homeworkId)
				: dummyStudentRows;
			loading = false;
			return;
		}

		if (!selectedGroupId) {
			studentData = [];
			return;
		}

		if (!homeworkId) {
			studentData = [];
			return;
		}

		loading = true;

		try {
			const response = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/?homework_id=${encodeURIComponent(homeworkId)}`,
				{
					method: 'GET',
					headers: {
						Authorization: `Bearer ${localStorage.token}`
					}
				}
			);

			if (!response.ok) {
				throw new Error('Student analysis fetch failed');
			}

			const data = await response.json();
			// Backend /analysis rows do not currently include group_id, so group scoping is enforced
			// here by matching the returned student_id against the selected Open WebUI group's user_ids.
			studentData = Array.isArray(data)
				? data.map((row) => {
						const matchedUser =
							availableUsers.find((user) => user.id === row?.student_id) ||
							availableUsers.find((user) => user.email === row?.student_email);
						const totalQuestion = Number(row?.total_question ?? 0);
						const totalSolved = Number(row?.total_solved ?? 0);
						const avgAccuracy = totalQuestion > 0 ? (totalSolved / totalQuestion) * 100 : 0;

						const weakTopics = Array.isArray(row?.topic_performances)
							? row.topic_performances
									.filter((tp) => tp?.status === 'needs_practice')
									.map((tp) => tp?.topic_name)
									.filter(Boolean)
							: [];

						return {
							id: row?.id ?? `${row?.student_id ?? row?.student_email ?? 'unknown'}-${homeworkId}`,
							studentId: row?.student_id ?? matchedUser?.id ?? 'N/A',
							name:
								matchedUser?.name ??
								row?.student_email?.split('@')[0] ??
								row?.student_id ??
								'Unknown Student',
							email: row?.student_email ?? 'unknown@email',
							homeworkId: row?.homework_id ?? homeworkId,
							avgAccuracy: Number(avgAccuracy.toFixed(1)),
							topicsToImprove: weakTopics.length ? weakTopics.join(', ') : 'None',
							performanceSummary: `Attempted ${row?.total_attempted ?? 0}/${totalQuestion}, solved ${totalSolved}, errors ${row?.total_errors ?? 0}.`
						};
					}).filter((row) => {
						return selectedGroupUserIds.length === 0 || selectedGroupUserIds.includes(row.studentId);
					})
				: [];

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Student analysis loaded from /analysis.');
			}
		} catch (error) {
			studentData = [];
			if (TESTING_AI_TUTOR) {
				toast.warning('[FAIL][GET]: Student analysis fetch failed.');
			}
			console.error('Student analysis API failed:', error);
		} finally {
			loading = false;
		}
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
</script>

<div class="flex flex-col space-y-6 py-4">
	<div class="space-y-3">
		<div class="flex flex-wrap items-center justify-between gap-4">
			<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Student Analysis RAW</h2>

			<div class="flex flex-wrap items-center gap-6">
				<div class="relative">
					<select
						bind:value={selectedHomework}
						class="w-48 appearance-none bg-transparent py-1 pr-5 text-sm text-gray-900 dark:text-gray-100 outline-hidden"
					>
						<option value="All">All Homeworks</option>
						{#each homeworkOptions as option}
							<option value={option.id}>{option.label}</option>
						{/each}
					</select>
				</div>

				<div class="flex min-w-[18rem] flex-1">
					<div class="self-center ml-1 mr-3 text-gray-500 dark:text-gray-400">
						<Search className="size-3.5" />
					</div>
					<input
						class="w-full bg-transparent py-1 pr-4 text-sm text-gray-900 outline-hidden placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
						bind:value={search}
						placeholder="Search name or email"
					/>
				</div>

				{#if isFilterActive}
					<button
						on:click={removeAllFilters}
						class="whitespace-nowrap text-sm font-medium text-gray-700 transition hover:text-purple-600 dark:text-gray-300 dark:hover:text-purple-400"
					>
						Remove Filter
					</button>
				{/if}
			</div>
		</div>

		<div class="scrollbar-hidden relative max-w-full overflow-x-auto whitespace-nowrap rounded-sm pt-0.5">
			<table class="max-w-full w-full table-auto rounded-sm text-left text-sm text-gray-500 dark:text-gray-400">
				<thead class="-translate-y-0.5 bg-gray-50 text-xs uppercase text-gray-700 dark:bg-gray-850 dark:text-gray-400">
					<tr>
						<th scope="col" class="px-3 py-1.5 select-none">Homework ID</th>
						<th scope="col" class="cursor-pointer select-none px-3 py-1.5" on:click={() => toggleSort('name')}>
							<div class="flex items-center gap-1.5">
								Student Name
								{#if sortField === 'name'}
									<span class="font-normal">
										{#if sortOrder === 'asc'}<ChevronUp className="size-2" />{:else}<ChevronDown className="size-2" />{/if}
									</span>
								{:else}
									<span class="invisible"><ChevronUp className="size-2" /></span>
								{/if}
							</div>
						</th>
						<th scope="col" class="px-3 py-1.5 select-none">Student ID</th>
						<th scope="col" class="px-3 py-1.5 select-none">Email</th>
						<th scope="col" class="cursor-pointer select-none px-3 py-1.5" on:click={() => toggleSort('accuracy')}>
							<div class="flex items-center gap-1.5">
								Average Accuracy (%)
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
						<th scope="col" class="px-3 py-1.5 select-none">Performance Summary (AI)</th>
					</tr>
				</thead>
				<tbody>
					{#if !selectedGroupId && !useDummyData}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								Select a group to view student analysis.
							</td>
						</tr>
					{:else if homeworkOptions.length === 0 && !useDummyData}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								No homework uploaded for this group yet.
							</td>
						</tr>
					{:else if selectedHomework === 'All' && !useDummyData}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								Choose a homework to load student analysis.
							</td>
						</tr>
					{:else if loading}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								Loading student analysis...
							</td>
						</tr>
					{:else if filteredAndSortedData.length === 0}
						<tr class="bg-white text-xs dark:bg-gray-900">
							<td colspan="7" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">
								No data available for the selected homework.
							</td>
						</tr>
					{:else}
						{#each filteredAndSortedData as student}
							<tr class="border-t border-gray-100 bg-white text-xs dark:border-gray-850 dark:bg-gray-900">
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">{student.homeworkId}</td>
								<td class="px-3 py-1 font-medium text-gray-900 dark:text-white">{student.name}</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">{student.studentId}</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">{student.email}</td>
								<td class="px-3 py-1 text-gray-700 dark:text-gray-300">{student.avgAccuracy.toFixed(1)}%</td>
								<td class="max-w-xs whitespace-normal px-3 py-1 text-gray-700 dark:text-gray-300">{student.topicsToImprove}</td>
								<td class="max-w-md whitespace-normal px-3 py-1 text-gray-700 dark:text-gray-300">{student.performanceSummary}</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>
	</div>
</div>

<style>
	.scrollbar-hidden::-webkit-scrollbar { display: none; }
	.scrollbar-hidden { -ms-overflow-style: none; scrollbar-width: none; }
</style>
