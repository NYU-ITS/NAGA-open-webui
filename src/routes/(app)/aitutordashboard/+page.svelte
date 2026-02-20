<script lang="ts">
	import { onMount } from 'svelte';

	let chartsContainer: HTMLElement;

	onMount(() => {
		console.log('AI Tutor Dashboard - Summary loaded');
	});

	// Sample data for Statistics table
	const homeworkStats = [
		{
			homework: 'Homework 1',
			totalProblems: 15,
			avgAttempted: 14.2,
			avgSolved: 12.8,
			avgErrors: 1.4
		},
		{
			homework: 'Homework 2',
			totalProblems: 18,
			avgAttempted: 16.5,
			avgSolved: 14.9,
			avgErrors: 1.6
		},
		{
			homework: 'Homework 3',
			totalProblems: 20,
			avgAttempted: 18.7,
			avgSolved: 16.2,
			avgErrors: 2.5
		},
		{
			homework: 'Homework 4',
			totalProblems: 16,
			avgAttempted: 15.1,
			avgSolved: 13.4,
			avgErrors: 1.7
		},
		{
			homework: 'Homework 5',
			totalProblems: 22,
			avgAttempted: 20.3,
			avgSolved: 18.1,
			avgErrors: 2.2
		},
		{
			homework: 'Homework 6',
			totalProblems: 19,
			avgAttempted: 17.8,
			avgSolved: 15.6,
			avgErrors: 2.2
		},
		{
			homework: 'Homework 7',
			totalProblems: 17,
			avgAttempted: 16.2,
			avgSolved: 14.5,
			avgErrors: 1.7
		},
		{
			homework: 'Homework 8',
			totalProblems: 21,
			avgAttempted: 19.4,
			avgSolved: 17.2,
			avgErrors: 2.2
		},
		{
			homework: 'Homework 9',
			totalProblems: 23,
			avgAttempted: 21.1,
			avgSolved: 18.9,
			avgErrors: 2.2
		}
	];

	// Generate placeholder charts (5 charts, show 3 by default)
	const charts = [
		{ id: 1, title: 'Average Accuracy Trend' },
		{ id: 2, title: 'Problem Completion Rate' },
		{ id: 3, title: 'Common Error Types' },
		{ id: 4, title: 'Time Spent per Problem' },
		{ id: 5, title: 'Topic Mastery Overview' }
	];

	function scrollCharts(direction: 'left' | 'right') {
		if (chartsContainer) {
			const scrollAmount = 400;
			chartsContainer.scrollBy({
				left: direction === 'left' ? -scrollAmount : scrollAmount,
				behavior: 'smooth'
			});
		}
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Charts Summary Section -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Charts Summary</h2>

		<div class="relative">
			<!-- Scroll Left Button -->
			<button
				class="absolute left-0 top-1/2 -translate-y-1/2 z-10 bg-white dark:bg-gray-800 rounded-full p-2 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition"
				on:click={() => scrollCharts('left')}
				aria-label="Scroll left"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="w-6 h-6"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
				</svg>
			</button>

			<!-- Charts Container -->
			<div
				bind:this={chartsContainer}
				class="flex gap-4 overflow-x-auto scrollbar-none snap-x snap-mandatory px-10"
				style="scroll-behavior: smooth;"
			>
				{#each charts as chart}
					<div
						class="flex-none w-80 h-64 bg-gray-200 dark:bg-gray-700 rounded-lg flex items-center justify-center snap-start"
					>
						<div class="text-center">
							<div class="text-gray-500 dark:text-gray-400 mb-2">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="1.5"
									stroke="currentColor"
									class="w-16 h-16 mx-auto"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z"
									/>
								</svg>
							</div>
							<p class="text-sm font-medium text-gray-600 dark:text-gray-300">{chart.title}</p>
						</div>
					</div>
				{/each}
			</div>

			<!-- Scroll Right Button -->
			<button
				class="absolute right-0 top-1/2 -translate-y-1/2 z-10 bg-white dark:bg-gray-800 rounded-full p-2 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition"
				on:click={() => scrollCharts('right')}
				aria-label="Scroll right"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="w-6 h-6"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
				</svg>
			</button>
		</div>
	</div>

	<!-- Statistics Section -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Statistics</h2>

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
							Total Number of Problems
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Average Number of Problems Attempted
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Average Number of Problems Solved
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Average Number of Problems with Errors
						</th>
					</tr>
				</thead>
				<tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
					{#each homeworkStats as stat}
						<tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition">
							<td
								class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100"
							>
								{stat.homework}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{stat.totalProblems}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{stat.avgAttempted.toFixed(1)}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{stat.avgSolved.toFixed(1)}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{stat.avgErrors.toFixed(1)}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>

<style>
	/* Hide scrollbar but keep functionality */
	.scrollbar-none::-webkit-scrollbar {
		display: none;
	}
	.scrollbar-none {
		-ms-overflow-style: none;
		scrollbar-width: none;
	}
</style>
