<script lang="ts">
	import { onMount } from 'svelte';

	onMount(() => {
		console.log('AI Tutor Dashboard - Student Analysis loaded');
	});

	type SortField = 'name' | 'accuracy' | null;
	type SortOrder = 'asc' | 'desc' | null;

	let sortField: SortField = null;
	let sortOrder: SortOrder = null;
	let selectedHomework = 'All';
	let selectedStudentName = 'All';
	let selectedStudentEmail = 'All';

	const homeworkOptions = [
		'All',
		'Homework 1',
		'Homework 2',
		'Homework 3',
		'Homework 4',
		'Homework 5',
		'Homework 6',
		'Homework 7',
		'Homework 8',
		'Homework 9'
	];

	// When student name is selected, reset email filter
	function handleStudentNameChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		selectedStudentName = target.value;
		if (selectedStudentName !== 'All') {
			selectedStudentEmail = 'All';
		}
	}

	// When student email is selected, reset name filter
	function handleStudentEmailChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		selectedStudentEmail = target.value;
		if (selectedStudentEmail !== 'All') {
			selectedStudentName = 'All';
		}
	}

	function removeAllFilters() {
		selectedHomework = 'All';
		selectedStudentName = 'All';
		selectedStudentEmail = 'All';
	}

	$: studentNameOptions = ['All', ...studentData.map((s) => s.name)];
	$: studentEmailOptions = ['All', ...studentData.map((s) => s.email)];
	$: isFilterActive =
		selectedHomework !== 'All' || selectedStudentName !== 'All' || selectedStudentEmail !== 'All';

	// Sample data for Student Analysis
	const studentData = [
		{
			name: 'Emma Johnson',
			email: 'emma.johnson@nyu.edu',
			homework: 'Homework 1',
			avgAccuracy: 88.5,
			topicsToImprove: 'Quadratic Equations, Logarithms',
			performanceSummary:
				'Strong overall performance. Shows excellent grasp of linear algebra and calculus fundamentals. Needs minor improvement in logarithmic properties.'
		},
		{
			name: 'Liam Smith',
			email: 'liam.smith@nyu.edu',
			homework: 'Homework 2',
			avgAccuracy: 76.2,
			topicsToImprove: 'Trigonometry, Derivatives',
			performanceSummary:
				'Moderate performance with room for growth. Struggles with trigonometric identities and derivative chain rule applications. Consistent effort shown.'
		},
		{
			name: 'Olivia Brown',
			email: 'olivia.brown@nyu.edu',
			homework: 'Homework 1',
			avgAccuracy: 92.1,
			topicsToImprove: 'None',
			performanceSummary:
				'Outstanding performance across all topics. Demonstrates mastery of concepts and problem-solving skills. Rarely makes computational errors.'
		},
		{
			name: 'Noah Davis',
			email: 'noah.davis@nyu.edu',
			homework: 'Homework 3',
			avgAccuracy: 71.8,
			topicsToImprove: 'Polynomials, Rational Expressions, Calculus',
			performanceSummary:
				'Below average performance requiring attention. Needs fundamental review of algebraic manipulation. Recommended for additional tutoring sessions.'
		},
		{
			name: 'Ava Wilson',
			email: 'ava.wilson@nyu.edu',
			homework: 'Homework 2',
			avgAccuracy: 84.3,
			topicsToImprove: 'Exponentials, Complex Numbers',
			performanceSummary:
				'Good performance with consistent progress. Shows strength in geometry and basic algebra. Could benefit from practice in exponential functions.'
		},
		{
			name: 'Ethan Martinez',
			email: 'ethan.martinez@nyu.edu',
			homework: 'Homework 4',
			avgAccuracy: 79.7,
			topicsToImprove: 'Graphing, Function Transformations',
			performanceSummary:
				'Adequate performance with potential for improvement. Solid computational skills but struggles with visual/graphical interpretation of functions.'
		},
		{
			name: 'Sophia Anderson',
			email: 'sophia.anderson@nyu.edu',
			homework: 'Homework 3',
			avgAccuracy: 86.9,
			topicsToImprove: 'Limits, Continuity',
			performanceSummary:
				'Above average performance showing steady improvement. Excellent work ethic and problem-solving approach. Minor gaps in calculus concepts.'
		},
		{
			name: 'Mason Taylor',
			email: 'mason.taylor@nyu.edu',
			homework: 'Homework 5',
			avgAccuracy: 73.4,
			topicsToImprove: 'All Advanced Topics',
			performanceSummary:
				'Struggling with advanced material. Strong foundation in basic algebra but difficulty transitioning to calculus. Recommend prerequisite review.'
		},
		{
			name: 'Isabella Thomas',
			email: 'isabella.thomas@nyu.edu',
			homework: 'Homework 1',
			avgAccuracy: 90.6,
			topicsToImprove: 'Optimization Problems',
			performanceSummary:
				'Excellent performance with near mastery. Outstanding analytical thinking and attention to detail. Only minor challenges in applied calculus problems.'
		},
		{
			name: 'James Jackson',
			email: 'james.jackson@nyu.edu',
			homework: 'Homework 4',
			avgAccuracy: 81.2,
			topicsToImprove: 'Series and Sequences',
			performanceSummary:
				'Good performance with consistent engagement. Shows particular strength in algebraic manipulation. Needs practice with pattern recognition.'
		},
		{
			name: 'Mia White',
			email: 'mia.white@nyu.edu',
			homework: 'Homework 2',
			avgAccuracy: 77.9,
			topicsToImprove: 'Integration, Applications of Derivatives',
			performanceSummary:
				'Fair performance with gradual improvement trend. Understands concepts but makes frequent computational errors. Would benefit from more practice.'
		},
		{
			name: 'Benjamin Harris',
			email: 'benjamin.harris@nyu.edu',
			homework: 'Homework 5',
			avgAccuracy: 85.7,
			topicsToImprove: 'Partial Fractions',
			performanceSummary:
				'Strong performance across most topics. Demonstrates good problem-solving strategies. Minor difficulties with algebraic decomposition methods.'
		}
	];

	function toggleSort(field: SortField) {
		if (sortField === field) {
			// Cycle through: asc -> desc -> null
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

		// Apply filters
		if (selectedHomework !== 'All') {
			data = data.filter((student) => student.homework === selectedHomework);
		}
		if (selectedStudentName !== 'All') {
			data = data.filter((student) => student.name === selectedStudentName);
		}
		if (selectedStudentEmail !== 'All') {
			data = data.filter((student) => student.email === selectedStudentEmail);
		}

		// Apply sorting
		if (sortField && sortOrder) {
			data.sort((a, b) => {
				let aValue, bValue;

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
				} else {
					return aValue < bValue ? 1 : aValue > bValue ? -1 : 0;
				}
			});
		}

		return data;
	})();
</script>

<div class="flex flex-col space-y-6 py-4">
	<!-- Filter Dropdowns -->
	<div class="flex items-center flex-wrap" style="gap: 32px;">
		<!-- Homework Filter -->
		<div class="flex items-center" style="gap: 8px;">
			<label class="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
				Homework:
			</label>
			<select
				bind:value={selectedHomework}
				class="w-48 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-purple-500"
			>
				{#each homeworkOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>
		</div>

		<!-- Student Name Filter -->
		<div class="flex items-center" style="gap: 8px;">
			<label class="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
				Student Name:
			</label>
			<select
				value={selectedStudentName}
				on:change={handleStudentNameChange}
				class="w-64 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-purple-500"
			>
				{#each studentNameOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>
		</div>

		<!-- Student Email Filter -->
		<div class="flex items-center" style="gap: 8px;">
			<label class="text-sm font-medium text-gray-700 dark:text-gray-300 whitespace-nowrap">
				Student Email:
			</label>
			<select
				value={selectedStudentEmail}
				on:change={handleStudentEmailChange}
				class="w-64 px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-purple-500"
			>
				{#each studentEmailOptions as option}
					<option value={option}>{option}</option>
				{/each}
			</select>
		</div>

		<!-- Remove Filter Button -->
		{#if isFilterActive}
			<button
				on:click={removeAllFilters}
				class="text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-purple-600 dark:hover:text-purple-400 transition whitespace-nowrap"
			>
				Remove Filter
			</button>
		{/if}
	</div>

	<!-- Student Analysis Table -->
	<div class="space-y-3">
		<h2 class="text-xl font-semibold text-gray-800 dark:text-gray-200">Student Analysis</h2>

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
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition"
							on:click={() => toggleSort('name')}
						>
							<div class="flex items-center gap-2">
								<span>Student Name</span>
								{#if sortField === 'name'}
									{#if sortOrder === 'asc'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2"
											stroke="currentColor"
											class="w-4 h-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M4.5 15.75l7.5-7.5 7.5 7.5"
											/>
										</svg>
									{:else if sortOrder === 'desc'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2"
											stroke="currentColor"
											class="w-4 h-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M19.5 8.25l-7.5 7.5-7.5-7.5"
											/>
										</svg>
									{/if}
								{/if}
							</div>
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Email
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition"
							on:click={() => toggleSort('accuracy')}
						>
							<div class="flex items-center gap-2">
								<span>Average Accuracy (%)</span>
								{#if sortField === 'accuracy'}
									{#if sortOrder === 'asc'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2"
											stroke="currentColor"
											class="w-4 h-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M4.5 15.75l7.5-7.5 7.5 7.5"
											/>
										</svg>
									{:else if sortOrder === 'desc'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2"
											stroke="currentColor"
											class="w-4 h-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M19.5 8.25l-7.5 7.5-7.5-7.5"
											/>
										</svg>
									{/if}
								{/if}
							</div>
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Topics to be Improved
						</th>
						<th
							class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
						>
							Performance Summary (AI)
						</th>
					</tr>
				</thead>
				<tbody class="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
					{#each filteredAndSortedData as student}
						<tr class="hover:bg-gray-50 dark:hover:bg-gray-800 transition">
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{student.homework}
							</td>
							<td
								class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100"
							>
								{student.name}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{student.email}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-700 dark:text-gray-300">
								{student.avgAccuracy.toFixed(1)}%
							</td>
							<td class="px-6 py-4 text-sm text-gray-700 dark:text-gray-300 max-w-xs">
								{student.topicsToImprove}
							</td>
							<td class="px-6 py-4 text-sm text-gray-700 dark:text-gray-300 max-w-md">
								{student.performanceSummary}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>
