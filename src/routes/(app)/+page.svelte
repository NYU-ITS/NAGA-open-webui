<script lang="ts">
	import { onMount } from 'svelte';
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';

	let showQuestionPanel = false;
	let generatedQuestions = {
		concepts: [],
		timestamp: null
	};

	// Sample generated questions
	const sampleQuestions = [
		{
			number: 1,
			question: 'Find critical points of the function f(x) = x³ - 6x² + 9x - 1',
			concepts: ['Differentiation', 'Critical Points']
		},
		{
			number: 2,
			question: 'Evaluate the definite integral ∫₀² (x² + 2x) dx',
			concepts: ['Integration', 'Definite Integrals']
		},
		{
			number: 3,
			question: 'Solve the system of linear equations: 2x + 3y = 7, 4x - y = 5',
			concepts: ['Linear Algebra', 'Systems of Equations']
		},
		{
			number: 4,
			question: 'Calculate lim(x→0) (sin x)/x',
			concepts: ['Limit Definition', 'Trigonometry']
		},
		{
			number: 5,
			question: 'Determine if the series Σ(1/n²) converges or diverges',
			concepts: ['Integration', 'Series']
		}
	];

	onMount(() => {
		// Check if there are generated questions from student dashboard
		const storedData = sessionStorage.getItem('generatedQuestions');
		if (storedData) {
			generatedQuestions = JSON.parse(storedData);
			showQuestionPanel = true;
			// Clear the sessionStorage after reading
			sessionStorage.removeItem('generatedQuestions');
		}
	});

	function closeQuestionPanel() {
		showQuestionPanel = false;
	}
</script>

<Help />

<div class="relative w-full h-full flex">
	<!-- Main Chat Area -->
	<div class="flex-1">
		<Chat />
	</div>

	<!-- Question Review Side Panel -->
	{#if showQuestionPanel}
		<div class="w-96 border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 flex flex-col">
			<!-- Panel Header -->
			<div class="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
				<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200">
					AI Question Review
				</h3>
				<button
					on:click={closeQuestionPanel}
					class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition"
					aria-label="Close panel"
				>
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5 text-gray-600 dark:text-gray-400">
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<!-- Panel Content (Scrollable) -->
			<div class="flex-1 overflow-y-auto p-4 space-y-4">
				<!-- Introduction Text -->
				<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
					You are reviewing AI suggested questions based on your conversation history. For more details, please visit the AI Tutor Dashboard located in the right-hand panel.
				</p>

				<!-- Selected Topics -->
				<div>
					<h4 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
						Selected Topics:
					</h4>
					<div class="flex flex-wrap gap-2">
						{#each generatedQuestions.concepts as concept}
							<span class="px-3 py-1 text-xs font-medium bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 rounded-full">
								{concept}
							</span>
						{/each}
					</div>
				</div>

				<!-- Questions List Header -->
				<div class="pt-2">
					<h4 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-3">
						Based on the selection, below is the list of questions generated:
					</h4>

					<!-- Questions -->
					<div class="space-y-3">
						{#each sampleQuestions as q}
							<div class="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
								<div class="flex items-start gap-2">
									<span class="flex-shrink-0 text-sm font-semibold text-gray-700 dark:text-gray-300">
										{q.number}.
									</span>
									<div class="flex-1">
										<p class="text-sm text-gray-900 dark:text-gray-100 mb-2">
											{q.question}
										</p>
										<div class="flex flex-wrap gap-1">
											{#each q.concepts as concept}
												<span class="px-2 py-0.5 text-xs bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded">
													{concept}
												</span>
											{/each}
										</div>
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>

				<!-- Notes -->
				<div class="pt-2 border-t border-gray-200 dark:border-gray-700">
					<p class="text-xs text-gray-500 dark:text-gray-500 italic">
						Notes: the questions will be created as KB? TBD
					</p>
				</div>
			</div>
		</div>
	{/if}
</div>
