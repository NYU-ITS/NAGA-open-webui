<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { TESTING_AI_TUTOR } from '$lib/constants';

	const AI_TUTOR_API_BASE = 'http://localhost:8000';

	onMount(async () => {
		console.log('AI Tutor Dashboard - Topic Analysis loaded');

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
	});

	// Global error type definitions — source of truth for names, colors, descriptions
	let errorTypeDefs: { type: string; color: string; description: string }[] = [];

	// Available colors for new error types (cycle through these)
	const errorTypeColors = ['#A792D0', '#7CB9E8', '#90EE90', '#EF4444'];

	// Modal state
	let showEditModal = false;
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

	function saveEdit() {
		if (editingIndex === null) return;
		errorTypeDefs[editingIndex] = { ...errorTypeDefs[editingIndex], type: editName, description: editDescription };
		errorTypeDefs = [...errorTypeDefs];
		closeModal();
	}

	function deleteType() {
		if (editingIndex === null) return;
		errorTypeDefs = errorTypeDefs.filter((_, i) => i !== editingIndex);
		closeModal();
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

	// State for expandable homework sections
	let expandedHomework = new Set(['homework1']); // Homework 1 expanded by default

	function toggleHomework(id: string) {
		if (expandedHomework.has(id)) {
			expandedHomework.delete(id);
		} else {
			expandedHomework.add(id);
		}
		expandedHomework = expandedHomework; // Trigger reactivity
	}

	// Sample data for Topic Analysis by Homework
	let topicByHomework = [
		{
			id: 'homework1',
			homework: 'Homework 1',
			topics: [
				{
					topic: 'Linear Algebra',
					questions: 'Q1, Q2, Q3',
					questionCount: 3,
					studentsWithError: 58,
					errorTypes: [
						{ type: 'Careless Errors', count: 10, percentage: 20.6, color: '#A792D0' },
						{ type: 'Calculation Errors', count: 20, percentage: 40.0, color: '#7CB9E8' },
						{ type: 'Notation Errors', count: 15, percentage: 30.0, color: '#90EE90' },
						{ type: 'Others', count: 5, percentage: 10.0, color: '#FFB84D' }
					]
				},
				{
					topic: 'Differentiation',
					questions: 'Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q10',
					questionCount: 8,
					studentsWithError: 47,
					errorTypes: [
						{ type: 'Careless Errors', count: 10, percentage: 21.3, color: '#A792D0' },
						{ type: 'Calculation Errors', count: 20, percentage: 42.6, color: '#7CB9E8' },
						{ type: 'Notation Errors', count: 15, percentage: 31.9, color: '#90EE90' },
						{ type: 'Others', count: 5, percentage: 10.6, color: '#FFB84D' }
					]
				},
				{
					topic: 'Limit Definition',
					questions: 'Q1, Q2, Q3, Q4, Q5',
					questionCount: 5,
					studentsWithError: 40,
					errorTypes: [
						{ type: 'Careless Errors', count: 10, percentage: 25.0, color: '#A792D0' },
						{ type: 'Calculation Errors', count: 20, percentage: 50.0, color: '#7CB9E8' },
						{ type: 'Notation Errors', count: 15, percentage: 37.5, color: '#90EE90' },
						{ type: 'Others', count: 5, percentage: 12.5, color: '#FFB84D' }
					]
				}
			]
		},
		{
			id: 'homework2',
			homework: 'Homework 2',
			topics: [
				{
					topic: 'Quadratic Equations',
					questions: 'Q1, Q3, Q5',
					questionCount: 3,
					studentsWithError: 52,
					errorTypes: [
						{ type: 'Careless Errors', count: 12, percentage: 23.1, color: '#A792D0' },
						{ type: 'Calculation Errors', count: 18, percentage: 34.6, color: '#7CB9E8' },
						{ type: 'Notation Errors', count: 14, percentage: 26.9, color: '#90EE90' },
						{ type: 'Others', count: 8, percentage: 15.4, color: '#FFB84D' }
					]
				}
			]
		},
		{
			id: 'homework3',
			homework: 'Homework 3',
			topics: [
				{
					topic: 'Polynomials',
					questions: 'Q2, Q4, Q6, Q7',
					questionCount: 4,
					studentsWithError: 45,
					errorTypes: [
						{ type: 'Careless Errors', count: 8, percentage: 17.8, color: '#A792D0' },
						{ type: 'Calculation Errors', count: 22, percentage: 48.9, color: '#7CB9E8' },
						{ type: 'Notation Errors', count: 10, percentage: 22.2, color: '#90EE90' },
						{ type: 'Others', count: 5, percentage: 11.1, color: '#FFB84D' }
					]
				}
			]
		},
		{
			id: 'homework4',
			homework: 'Homework 4',
			topics: [
				{
					topic: 'Trigonometry',
					questions: 'Q1, Q2, Q3, Q5, Q8',
					questionCount: 5,
					studentsWithError: 50,
					errorTypes: [
						{ type: 'Careless Errors', count: 15, percentage: 30.0, color: '#A792D0' },
						{ type: 'Calculation Errors', count: 18, percentage: 36.0, color: '#7CB9E8' },
						{ type: 'Notation Errors', count: 12, percentage: 24.0, color: '#90EE90' },
						{ type: 'Others', count: 5, percentage: 10.0, color: '#FFB84D' }
					]
				}
			]
		}
	];

	// Sample data for Practice Question Set
	let practiceQuestions = [
		{
			homework: 'Homework 1',
			status: 'approved',
			date: '2026-01-02 12:23:12'
		},
		{
			homework: 'Homework 2',
			status: 'ready'
		},
		{
			homework: 'Homework 3',
			status: 'not_available'
		},
		{
			homework: 'Homework 4',
			status: 'not_available'
		},
		{
			homework: 'Homework 5',
			status: 'approved',
			date: '2026-01-15 09:45:30'
		},
		{
			homework: 'Homework 6',
			status: 'ready'
		},
		{
			homework: 'Homework 7',
			status: 'not_available'
		}
	];
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Topic Analysis by Homework -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">
			Topic Analysis by Homework
		</h2>

		<div class="rounded border border-[#BDBDBD] dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
			<!-- Table Header -->
			<div class="flex bg-gray-50 dark:bg-gray-800 border-b border-[#BDBDBD] dark:border-gray-700">
				<div class="flex-shrink-0" style="width: 4%;"></div>
				<div class="flex-shrink-0 px-4 py-3" style="width: 15%;">
					<div class="text-sm font-semibold text-gray-700 dark:text-gray-300">Questions in Topic</div>
					<div class="text-xs text-gray-500 dark:text-gray-400">Count (Numbers)</div>
				</div>
				<div class="flex-shrink-0 px-4 py-3" style="width: 11%;">
					<div class="text-sm font-semibold text-gray-700 dark:text-gray-300">Students with Error</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 whitespace-normal">Unique students with error</div>
				</div>
				<div class="flex-shrink-0 px-4 py-3" style="width: 70%;">
					<div class="text-sm font-semibold text-gray-700 dark:text-gray-300">Error Type Analysis</div>
					<div class="flex gap-3 mt-1 text-xs flex-wrap items-center">
						{#if errorTypeDefs.length === 0}
							<span class="text-gray-400 dark:text-gray-500 italic">Please add new error types</span>
						{:else}
							{#each displayErrorTypes as def, i}
								<button
									class="flex items-center gap-1 whitespace-nowrap hover:opacity-75 select-none"
									on:click={() => i < errorTypeDefs.length && openEdit(i)}
									title={i < errorTypeDefs.length ? 'Click to edit' : ''}
									style={i >= errorTypeDefs.length ? 'cursor: default;' : ''}
								>
									<span class="w-3 h-3 rounded flex-shrink-0" style="background-color: {def.color};"></span>
									{def.type}
								</button>
							{/each}
						{/if}
						{#if errorTypeDefs.length < 4}
							<button
								class="flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 leading-none text-base"
								on:click={addErrorType}
								title="Add error type"
							>+</button>
						{/if}
					</div>
				</div>
			</div>

			<!-- Table Body -->
			<div>
				{#each topicByHomework as homework, homeworkIndex}
					<!-- Homework Header Row -->
					<div
						class="flex {expandedHomework.has(homework.id) ? 'border-b border-gray-200 dark:border-gray-800' : homeworkIndex < topicByHomework.length - 1 ? 'border-b border-[#BDBDBD] dark:border-gray-700' : ''} bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition cursor-pointer"
						on:click={() => toggleHomework(homework.id)}
					>
						<div class="w-full px-4 py-3 flex items-center gap-2">
							{#if expandedHomework.has(homework.id)}
								<!-- Down chevron when expanded -->
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="w-4 h-4 flex-shrink-0"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
								</svg>
							{:else}
								<!-- Right chevron when collapsed -->
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="w-4 h-4 flex-shrink-0"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
								</svg>
							{/if}
							<span class="font-semibold text-sm text-gray-900 dark:text-gray-100"
								>{homework.homework}</span
							>
						</div>
					</div>

					<!-- Topics (expanded) -->
					{#if expandedHomework.has(homework.id)}
						{#each homework.topics as topic, topicIndex}
							<div
								class="flex {topicIndex === homework.topics.length - 1 && homeworkIndex < topicByHomework.length - 1 ? 'border-b border-[#BDBDBD] dark:border-gray-700' : topicIndex < homework.topics.length - 1 ? 'border-b border-gray-200 dark:border-gray-800' : ''} hover:bg-gray-50 dark:hover:bg-gray-800 transition"
							>
								<div class="flex-shrink-0" style="width: 4%;"></div>
								<div class="flex-shrink-0 px-4 py-3" style="width: 15%;">
									<div class="text-sm text-gray-900 dark:text-gray-100">{topic.topic}</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
										{topic.questionCount} [{topic.questions}]
									</div>
								</div>
								<div class="flex-shrink-0 px-4 py-3 flex items-center" style="width: 11%;">
									<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
										{topic.studentsWithError}
									</div>
								</div>
								<div class="flex-shrink-0 px-4 py-3" style="width: 70%;">
									{#if getTopicDisplayErrorTypes(topic.errorTypes).length === 0}
										<div class="flex items-center gap-2">
											<span class="text-xs text-gray-400 dark:text-gray-500 italic">
												No error types defined, please define error types
											</span>
											<button
												class="flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 leading-none text-base"
												on:click|stopPropagation={addErrorType}
												title="Add error type"
											>+</button>
										</div>
									{:else}
										<!-- Stacked Bar Chart -->
										<div class="flex h-5 rounded overflow-hidden w-full">
											{#each getTopicDisplayErrorTypes(topic.errorTypes) as errorType}
												<div
													style="width: {errorType.percentage}%; background-color: {errorType.color};"
													title="{errorType.type}: {errorType.percentage}%"
												></div>
											{/each}
										</div>
										<!-- Labels below bar -->
										<div class="flex w-full mt-1">
											{#each getTopicDisplayErrorTypes(topic.errorTypes) as errorType}
												<div class="overflow-hidden" style="width: {errorType.percentage}%;">
													{#if errorType.percentage >= 8}
														<span class="text-xs text-gray-600 dark:text-gray-400 block truncate leading-tight">
															{errorType.percentage}%
														</span>
													{/if}
												</div>
											{/each}
										</div>
									{/if}
								</div>
							</div>
						{/each}
					{/if}
				{/each}
			</div>
		</div>
	</div>

	<!-- Practice Question Set -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Practice Question Set</h2>

		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			Start with an AI-generated question set based on students' weak topics, or upload your own questions. You can download, edit, and re-upload AI-generated content if needed. All uploaded question sets are automatically standardized by the system, with topics added and answers generated if missing, to ensure a consistent format across the platform.
		</p>

		<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
			<table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
				<thead class="bg-gray-50 dark:bg-gray-800">
					<tr>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Homework
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Status
						</th>
					</tr>
				</thead>
				<tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
					{#each practiceQuestions as practice}
						<tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition">
							<td
								class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100"
							>
								{practice.homework}
							</td>
							<td class="px-6 py-4 text-sm text-gray-700 dark:text-gray-300">
								<div class="flex items-center justify-between">
									<div class="flex items-center gap-2">
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
									{#if practice.status === 'approved' || practice.status === 'ready'}
										<a
											href="/aitutordashboard/topicanalysis/reviewquestionset?homework_id={practice.homeworkId ?? ''}"
											class="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline ml-4"
										>
											View
										</a>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
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
