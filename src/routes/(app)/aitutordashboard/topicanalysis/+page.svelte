<script lang="ts">
	import { onMount } from 'svelte';

	onMount(() => {
		console.log('AI Tutor Dashboard - Topic Analysis loaded');
	});

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
	const topicByHomework = [
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
	const practiceQuestions = [
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
				<div class="flex-shrink-0 px-4 py-3" style="width: 35%;">
					<div class="text-sm font-semibold text-gray-700 dark:text-gray-300">Questions in Topic</div>
					<div class="text-xs text-gray-500 dark:text-gray-400">Q: Total Count (Question Number)</div>
				</div>
				<div class="flex-shrink-0 px-4 py-3" style="width: 20%;">
					<div class="text-sm font-semibold text-gray-700 dark:text-gray-300 text-center">Students with Error</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 text-center whitespace-normal">Q: Number of unique students that made an error</div>
				</div>
				<div class="flex-shrink-0 px-4 py-3" style="width: 41%;">
					<div class="text-sm font-semibold text-gray-700 dark:text-gray-300">Error Type Analysis</div>
					<div class="flex gap-4 mt-1 text-xs flex-wrap">
						<span class="flex items-center gap-1 whitespace-nowrap">
							<span class="w-3 h-3 rounded" style="background-color: #A792D0;"></span>
							Careless Errors
						</span>
						<span class="flex items-center gap-1 whitespace-nowrap">
							<span class="w-3 h-3 rounded" style="background-color: #7CB9E8;"></span>
							Calculation Errors
						</span>
						<span class="flex items-center gap-1 whitespace-nowrap">
							<span class="w-3 h-3 rounded" style="background-color: #90EE90;"></span>
							Notation Errors
						</span>
						<span class="flex items-center gap-1 whitespace-nowrap">
							<span class="w-3 h-3 rounded" style="background-color: #FFB84D;"></span>
							Others
						</span>
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
								<div class="flex-shrink-0 px-4 py-3" style="width: 35%;">
									<div class="text-sm text-gray-900 dark:text-gray-100">{topic.topic}</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
										{topic.questionCount} [{topic.questions}]
									</div>
								</div>
								<div class="flex-shrink-0 px-4 py-3 flex items-center justify-center" style="width: 20%;">
									<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
										{topic.studentsWithError}
									</div>
								</div>
								<div class="flex-shrink-0 px-4 py-3 flex items-center" style="width: 41%;">
									<!-- Stacked Bar Chart -->
									<div class="flex h-6 rounded overflow-hidden w-full max-w-[500px]">
										{#each topic.errorTypes as errorType}
											<div
												class="flex items-center justify-center text-xs text-white font-medium"
												style="width: {errorType.percentage}%; background-color: {errorType.color};"
												title="{errorType.type}: {errorType.count} ({errorType.percentage.toFixed(
													1
												)}%)"
											>
												{#if errorType.percentage > 15}
													{errorType.count} ({errorType.percentage.toFixed(1)}%)
												{/if}
											</div>
										{/each}
									</div>
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
										{:else}
											<span class="w-2 h-2 rounded-full bg-gray-400 flex-shrink-0"></span>
											<span>Not available for review yet</span>
										{/if}
									</div>
									{#if practice.status === 'approved' || practice.status === 'ready'}
										<a
											href="/aitutordashboard/topicanalysis/reviewquestionset"
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
</div>
