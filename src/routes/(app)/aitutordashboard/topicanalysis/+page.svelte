<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { AI_TUTOR_DUMMY_ERROR_TYPES, AI_TUTOR_DUMMY_MODE, TESTING_AI_TUTOR } from '$lib/constants';
	import { aiTutorDummyErrorTypes } from '$lib/stores';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';
	const useDummyData = AI_TUTOR_DUMMY_MODE;

	// Group ID (needed for error-types endpoints)
	let groupId = '';
	$: groupId = $page.url.searchParams.get('group_id') || '';
	const dummyTopicByHomework = [
		{
			id: 'Homework 1',
			homework: 'Homework 1',
			topics: [
				{
					topic: 'Linear Algebra',
					questions: 'Q1, Q2',
					questionCount: 2,
					studentsWithError: 4,
					errorTypes: [
						{ type: 'Conceptual', count: 4, percentage: 50, color: '#1D4ED8' },
						{ type: 'Procedural', count: 4, percentage: 50, color: '#0F766E' }
					]
				},
				{
					topic: 'Limit Definition',
					questions: 'Q3',
					questionCount: 1,
					studentsWithError: 3,
					errorTypes: [
						{ type: 'Conceptual', count: 2, percentage: 40, color: '#1D4ED8' },
						{ type: 'Arithmetic', count: 3, percentage: 60, color: '#B45309' }
					]
				}
			]
		},
		{
			id: 'Homework 2',
			homework: 'Homework 2',
			topics: [
				{
					topic: 'Integration by Parts',
					questions: 'Q1, Q4',
					questionCount: 2,
					studentsWithError: 5,
					errorTypes: [
						{ type: 'Procedural', count: 6, percentage: 60, color: '#0F766E' },
						{ type: 'Communication', count: 4, percentage: 40, color: '#B91C1C' }
					]
				},
				{
					topic: 'Factoring',
					questions: 'Q2',
					questionCount: 1,
					studentsWithError: 2,
					errorTypes: [
						{ type: 'Arithmetic', count: 2, percentage: 100, color: '#B45309' }
					]
				}
			]
		},
		{
			id: 'Homework 3',
			homework: 'Homework 3',
			topics: [
				{
					topic: 'Trigonometric Identities',
					questions: 'Q1, Q2',
					questionCount: 2,
					studentsWithError: 4,
					errorTypes: [
						{ type: 'Conceptual', count: 3, percentage: 37.5, color: '#1D4ED8' },
						{ type: 'Procedural', count: 5, percentage: 62.5, color: '#0F766E' }
					]
				}
			]
		},
		{
			id: 'Homework 4',
			homework: 'Homework 4',
			topics: [
				{
					topic: 'Trigonometric Identities',
					questions: 'Q3',
					questionCount: 1,
					studentsWithError: 3,
					errorTypes: [
						{ type: 'Communication', count: 1, percentage: 25, color: '#B91C1C' },
						{ type: 'Procedural', count: 3, percentage: 75, color: '#0F766E' }
					]
				}
			]
		}
	];
	const dummyPracticeQuestions = [
		{ homework: 'Homework 1', homeworkId: 'Homework 1', status: 'approved', date: 'Mar 12, 2026' },
		{ homework: 'Homework 2', homeworkId: 'Homework 2', status: 'ready' },
		{ homework: 'Homework 3', homeworkId: 'Homework 3', status: 'generating' },
		{ homework: 'Homework 4', homeworkId: 'Homework 4', status: 'not_ready' }
	];

	// Helper: load error types from server
	async function loadErrorTypes() {
		if (useDummyData) {
			errorTypeDefs = $aiTutorDummyErrorTypes;
			return;
		}
		if (!groupId) return;
		try {
			const res = await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(groupId)}`,
				{ headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			if (res.ok) {
				const data = await res.json();
				const errorTypes = Array.isArray(data?.error_types)
					? data.error_types
					: Array.isArray(data)
						? data
						: [];
				if (errorTypes.length > 0) {
					errorTypeDefs = errorTypes.slice(0, 4).map((et, i) => ({
						type: et.name ?? 'Unknown',
						color: errorTypeColors[i % errorTypeColors.length],
						description: et.description ?? ''
					}));
				} else {
					errorTypeDefs = [];
				}
				if (TESTING_AI_TUTOR) toast.success('[SUCCESS][GET]: Error types loaded.');
			}
		} catch (e) {
			if (TESTING_AI_TUTOR) toast.warning('[FAIL][GET]: Error types fetch failed.');
			console.error('Error types fetch failed:', e);
		}
	}

	// Helper: persist current errorTypeDefs to server
	async function persistErrorTypes() {
		if (useDummyData) {
			aiTutorDummyErrorTypes.set(errorTypeDefs);
			toast.success('Dummy error types saved.');
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
			if (TESTING_AI_TUTOR && res.ok) toast.success('[SUCCESS][PUT]: Error types saved.');
		} catch (e) {
			if (TESTING_AI_TUTOR) toast.warning('[FAIL][PUT]: Error types save failed.');
			console.error('Failed to persist error types:', e);
		}
	}

	// Delete all custom error types on server, then reload defaults
	async function deleteAllErrorTypes() {
		if (useDummyData) {
			errorTypeDefs = AI_TUTOR_DUMMY_ERROR_TYPES;
			aiTutorDummyErrorTypes.set(AI_TUTOR_DUMMY_ERROR_TYPES);
			toast.success('Dummy error types reset to defaults.');
			return;
		}
		if (!groupId) return;
		try {
			await fetch(
				`${AI_TUTOR_API_BASE}/analysis/error-types?group_id=${encodeURIComponent(groupId)}`,
				{ method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.token}` } }
			);
			if (TESTING_AI_TUTOR) toast.success('[SUCCESS][DELETE]: Error types reset to defaults.');
			await loadErrorTypes();
		} catch (e) {
			if (TESTING_AI_TUTOR) toast.warning('[FAIL][DELETE]: Error types delete failed.');
			console.error('Failed to delete error types:', e);
		}
	}

	onMount(async () => {
		console.log('AI Tutor Dashboard - Topic Analysis loaded');

		if (useDummyData) {
			topicByHomework = dummyTopicByHomework;
			practiceQuestions = dummyPracticeQuestions;
			errorTypeDefs = $aiTutorDummyErrorTypes;
			return;
		}

		try {
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

				topicByHomework = Array.from(grouped.entries()).map(([homeworkId, topicMap]) => {
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
						homework: homeworkId,
						topics
					};
				});
			}

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Topic analysis loaded from /analysis.');
			}
		} catch (error) {
			if (TESTING_AI_TUTOR) {
				toast.warning('[FAIL][GET]: Topic analysis fallback to placeholder data.');
			}
			console.error('Topic analysis API failed:', error);
		}

		try {
			const homeworkResponse = await fetch(`${AI_TUTOR_API_BASE}/homework`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

			const practiceResponse = await fetch(`${AI_TUTOR_API_BASE}/practice`, {
				method: 'GET',
				headers: {
					Authorization: `Bearer ${localStorage.token}`
				}
			});

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

				practiceQuestions = Array.from(homeworkIds).sort().map((homeworkId) => {
					const latest = latestByHomework.get(homeworkId);
					if (!latest) {
						return { homework: homeworkId, homeworkId, status: 'not_ready' };
					}

					if (latest.status === 'approved') {
						return {
							homework: homeworkId,
							homeworkId,
							status: 'approved',
							date: latest.created_at
						};
					}

					if (latest.status === 'generating') {
						return { homework: homeworkId, homeworkId, status: 'generating' };
					}

					if (latest.status === 'pending' || latest.status === 'rejected') {
						return { homework: homeworkId, homeworkId, status: 'ready' };
					}

					return { homework: homeworkId, homeworkId, status: 'not_ready' };
				});
			}

			if (TESTING_AI_TUTOR) {
				toast.success('[SUCCESS][GET]: Practice question status loaded from /practice.');
			}
		} catch (error) {
			if (TESTING_AI_TUTOR) {
				toast.warning('[FAIL][GET]: Practice question status fallback to placeholder data.');
			}
			console.error('Practice question set API failed:', error);
		}

		// Load error types from server (after groupId is set above)
		await loadErrorTypes();
	});

	// Global error type definitions — source of truth for names, colors, descriptions
	let errorTypeDefs: { type: string; color: string; description: string }[] = [];

	// Accessibility-safe colors for error type legend and charts.
	const errorTypeColors = ['#1D4ED8', '#0F766E', '#B45309', '#B91C1C'];

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
			return errorTypes;
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

	function toggleHomework(id: string) {
		if (expandedHomework.has(id)) {
			expandedHomework.delete(id);
		} else {
			expandedHomework.add(id);
		}
		expandedHomework = expandedHomework; // Trigger reactivity
	}

	let topicByHomework = [];
	$: if (topicByHomework.length > 0 && expandedHomework.size === 0) {
		expandedHomework = new Set([topicByHomework[0].id]);
	}

	let practiceQuestions = [];
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Topic Analysis by Homework -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">
			Topic Analysis by Homework
		</h2>

		<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
			<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
				<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						<th scope="col" colspan="2" class="px-3 py-1.5 whitespace-nowrap">Questions in Topic</th>
						<th scope="col" class="px-3 py-1.5 whitespace-nowrap">Students with Error</th>
						<th scope="col" class="px-3 py-1.5 w-full">Error Type Analysis</th>
					</tr>
				</thead>
				<tbody>
					{#each topicByHomework as homework}
						<!-- Homework Header Row -->
						<tr
							class="bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition cursor-pointer"
							on:click={() => toggleHomework(homework.id)}
						>
							<td colspan="4" class="px-3 py-1.5">
								<div class="flex items-center gap-2">
									{#if expandedHomework.has(homework.id)}
										<ChevronDown className="size-3 flex-shrink-0" />
									{:else}
										<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-3 flex-shrink-0">
											<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
										</svg>
									{/if}
									<span class="font-semibold text-xs text-gray-900 dark:text-gray-100">{homework.homework}</span>
								</div>
							</td>
						</tr>

						<!-- Topics (expanded) -->
						{#if expandedHomework.has(homework.id)}
							{#each homework.topics as topic}
								<tr class="bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-800 transition text-xs">
									<td class="px-3 py-1.5 w-8"></td>
									<td class="px-3 py-1.5">
										<div class="text-gray-900 dark:text-gray-100 whitespace-nowrap">{topic.topic}</div>
										<div class="text-gray-500 dark:text-gray-400 mt-0.5 whitespace-nowrap">
											{topic.questionCount} [{topic.questions}]
										</div>
									</td>
									<td class="px-3 py-1.5">
										<span class="text-gray-900 dark:text-gray-100">{topic.studentsWithError}</span>
									</td>
									<td class="px-3 py-1.5 w-full">
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
											<!-- Stacked Bar Chart with + at end -->
											<div class="flex items-center gap-2">
												<div class="flex h-5 rounded overflow-hidden flex-1 min-w-[200px]">
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
											<!-- Labels below bar -->
											<div class="flex w-full mt-1 min-w-[200px]">
												{#each getTopicDisplayErrorTypes(topic.errorTypes) as errorType}
													<div class="overflow-hidden" style="width: {errorType.percentage}%;">
														{#if errorType.percentage >= 8}
															<span class="text-gray-600 dark:text-gray-400 block truncate leading-tight">
																{errorType.percentage}%
															</span>
														{/if}
													</div>
												{/each}
											</div>
										{/if}
									</td>
								</tr>
							{/each}
						{/if}
					{/each}
					{#if topicByHomework.length === 0}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="4" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">No data available</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</div>
	</div>

	<div class="space-y-3">
		<div class="flex items-center justify-between gap-3">
			<div>
				<h4 class="text-base font-semibold text-gray-800 dark:text-gray-200">Error Type Configuration</h4>
				<div class="text-xs text-gray-400 dark:text-gray-500">You can have at most 4 error types</div>
			</div>
			<div class="flex items-center gap-3">
				<button
					class="text-xs font-medium text-gray-500 transition hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
					on:click={() => {
						showResetDefaultsModal = true;
					}}
				>
					Use default
				</button>
				<div class="flex items-center gap-2">
				{#if errorTypeDefs.length < 4}
					<button
						class="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-gray-500 transition hover:bg-black/5 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-gray-200"
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
						class="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-gray-500 transition hover:bg-black/5 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-gray-200"
						on:click={() => {
							showResetDefaultsModal = true;
						}}
						title="Reset error types to defaults"
					>
						<span>Delete</span>
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
						on:click={() => openEdit(i)}
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
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Practice Question Set</h2>

		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			Start with an AI-generated question set based on students' weak topics, or upload your own questions. You can download, edit, and re-upload AI-generated content if needed. All uploaded question sets are automatically standardized by the system, with topics added and answers generated if missing, to ensure a consistent format across the platform.
		</p>

		<div class="scrollbar-hidden relative overflow-x-auto max-w-full rounded-sm pt-0.5">
			<table class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm">
				<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5">
					<tr>
						<th scope="col" class="px-3 py-1.5">Homework</th>
						<th scope="col" class="px-3 py-1.5">Status</th>
						<th scope="col" class="px-3 py-1.5">Action</th>
					</tr>
				</thead>
				<tbody>
					{#if practiceQuestions.length === 0}
						<tr class="bg-white dark:bg-gray-900 text-xs">
							<td colspan="3" class="px-3 py-6 text-center text-gray-400 dark:text-gray-500">No data available</td>
						</tr>
					{:else}
						{#each practiceQuestions as practice}
							<tr class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs border-t border-gray-100 dark:border-gray-850">
								<td class="px-3 py-1.5 font-medium text-gray-900 dark:text-white whitespace-nowrap">{practice.homework}</td>
								<td class="px-3 py-1.5">
									<div class="flex items-center gap-2 text-gray-700 dark:text-gray-300 whitespace-nowrap">
										{#if practice.status === 'approved'}
											<span class="w-2 h-2 rounded-full bg-green-500 flex-shrink-0"></span>
											<span>Approved on {practice.date}</span>
										{:else if practice.status === 'ready'}
											<span class="w-2 h-2 rounded-full bg-yellow-500 flex-shrink-0"></span>
											<span>Ready for review</span>
										{:else if practice.status === 'generating'}
											<span class="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0"></span>
											<span>Generating</span>
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
												href="/aitutordashboard/topicanalysis/reviewquestionset?homework_id={practice.homeworkId ?? ''}"
												class="self-center w-fit text-xs px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 whitespace-nowrap"
											>
												View
											</a>
											<button
												class="self-center w-fit text-xs px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl text-gray-700 dark:text-gray-300 flex items-center gap-1 whitespace-nowrap"
											>
												Send
												<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-3">
													<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
												</svg>
											</button>
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
