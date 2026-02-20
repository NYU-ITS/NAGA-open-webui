<script lang="ts">
	import { onMount } from 'svelte';

	onMount(() => {
		console.log('Student Dashboard - Summary loaded');
	});

	// Sample data for homework summary
	const homeworkData = [
		{
			homework: 'Homework 1',
			masteredTopics: ['Linear Algebra', 'Differentiation'],
			needMorePractice: ['Integration', 'Limit Definition'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10
		},
		{
			homework: 'Homework 2',
			masteredTopics: ['Quadratic Equations', 'Polynomials'],
			needMorePractice: ['Factoring', 'Complex Numbers'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10
		},
		{
			homework: 'Homework 3',
			masteredTopics: ['Trigonometry', 'Unit Circle'],
			needMorePractice: ['Trigonometric Identities', 'Inverse Functions'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10
		},
		{
			homework: 'Homework 4',
			masteredTopics: ['Derivatives', 'Chain Rule'],
			needMorePractice: ['Product Rule', 'Quotient Rule'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10
		},
		{
			homework: 'Homework 5',
			masteredTopics: ['Integrals', 'Substitution'],
			needMorePractice: ['Integration by Parts', 'Partial Fractions'],
			totalCount: 12,
			solved: 12,
			attempted: 12,
			errors: 10
		}
	];

	function goToConcepts(topic: string) {
		window.location.href = `/studentdashboard/concepts?topic=${encodeURIComponent(topic)}`;
	}
</script>

<div class="flex flex-col space-y-6 py-4">
	<div class="overflow-x-auto">
		<table class="min-w-full border border-gray-200 dark:border-gray-700 rounded-lg">
			<thead class="bg-gray-50 dark:bg-gray-800">
				<tr>
					<th class="px-6 py-3 text-left text-sm font-semibold text-gray-700 dark:text-gray-300 border-b border-r border-gray-200 dark:border-gray-700">
						Homework
					</th>
					<th class="px-6 py-3 text-left text-sm font-semibold text-gray-700 dark:text-gray-300 border-b border-r border-gray-200 dark:border-gray-700">
						Mastered Topics
					</th>
					<th class="px-6 py-3 text-left text-sm font-semibold text-gray-700 dark:text-gray-300 border-b border-r border-gray-200 dark:border-gray-700">
						Need More Practice Topics
					</th>
					<th colspan="4" class="px-6 py-3 text-center text-sm font-semibold text-gray-700 dark:text-gray-300 border-b border-gray-200 dark:border-gray-700">
						Total Number of Problems
					</th>
				</tr>
				<tr>
					<th class="border-b border-r border-gray-200 dark:border-gray-700"></th>
					<th class="border-b border-r border-gray-200 dark:border-gray-700"></th>
					<th class="border-b border-r border-gray-200 dark:border-gray-700"></th>
					<th class="px-6 py-2 text-center text-xs font-medium text-gray-600 dark:text-gray-400 border-b border-r border-gray-200 dark:border-gray-700">
						Total Count
					</th>
					<th class="px-6 py-2 text-center text-xs font-medium text-gray-600 dark:text-gray-400 border-b border-r border-gray-200 dark:border-gray-700">
						Solved
					</th>
					<th class="px-6 py-2 text-center text-xs font-medium text-gray-600 dark:text-gray-400 border-b border-r border-gray-200 dark:border-gray-700">
						Attempted
					</th>
					<th class="px-6 py-2 text-center text-xs font-medium text-gray-600 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
						Errors
					</th>
				</tr>
			</thead>
			<tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
				{#each homeworkData as hw}
					<tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition">
						<td class="px-6 py-4 text-sm font-medium text-gray-900 dark:text-gray-100 border-r border-gray-200 dark:border-gray-700">
							{hw.homework}
						</td>
						<td class="px-6 py-4 border-r border-gray-200 dark:border-gray-700">
							<div class="flex flex-wrap gap-2">
								{#each hw.masteredTopics as topic}
									<button
										on:click={() => goToConcepts(topic)}
										class="px-3 py-1 text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-full border border-gray-300 dark:border-gray-600 hover:bg-gray-200 dark:hover:bg-gray-700 transition cursor-pointer"
									>
										{topic}
									</button>
								{/each}
							</div>
						</td>
						<td class="px-6 py-4 border-r border-gray-200 dark:border-gray-700">
							<div class="flex flex-wrap gap-2">
								{#each hw.needMorePractice as topic}
									<button
										on:click={() => goToConcepts(topic)}
										class="px-3 py-1 text-xs font-medium bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-full border border-gray-300 dark:border-gray-600 hover:bg-gray-200 dark:hover:bg-gray-700 transition cursor-pointer"
									>
										{topic}
									</button>
								{/each}
							</div>
						</td>
						<td class="px-6 py-4 text-sm text-center text-gray-900 dark:text-gray-100 border-r border-gray-200 dark:border-gray-700">
							{hw.totalCount}
						</td>
						<td class="px-6 py-4 text-sm text-center text-gray-900 dark:text-gray-100 border-r border-gray-200 dark:border-gray-700">
							{hw.solved}
						</td>
						<td class="px-6 py-4 text-sm text-center text-gray-900 dark:text-gray-100 border-r border-gray-200 dark:border-gray-700">
							{hw.attempted}
						</td>
						<td class="px-6 py-4 text-sm text-center text-gray-900 dark:text-gray-100">
							{hw.errors}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
