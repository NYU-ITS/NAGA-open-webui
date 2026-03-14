<script lang="ts">
	import { onMount } from 'svelte';
	import { showControls, showRightsideQuestions } from '$lib/stores';

	let generatedQuestions = {
		concepts: [],
		homework: null,
		timestamp: null
	};
	const placeholderGeneratedQuestions = {
		homework: 'Homework 1-8',
		concepts: [
			'Linear Algebra',
			'Differentiation',
			'Integration',
			'Limit Definition',
			'Quadratic Equations',
			'Polynomials',
			'Factoring',
			'Complex Numbers',
			'Trigonometry',
			'Unit Circle',
			'Derivatives',
			'Chain Rule'
		],
		timestamp: null
	};

	const sampleQuestions = [
		{
			number: 1,
			question: 'Find critical points of the function f(x) = x^3 - 6x^2 + 9x - 1',
			concepts: ['Differentiation', 'Critical Points']
		},
		{
			number: 2,
			question: 'Evaluate the definite integral from 0 to 2 of x^2 + 2x dx',
			concepts: ['Integration', 'Definite Integrals']
		},
		{
			number: 3,
			question: 'Solve the system of linear equations: 2x + 3y = 7, 4x - y = 5',
			concepts: ['Linear Algebra', 'Systems of Equations']
		},
		{
			number: 4,
			question: 'Calculate lim(x->0) (sin x)/x',
			concepts: ['Limit Definition', 'Trigonometry']
		},
		{
			number: 5,
			question: 'Determine if the series sum of 1/n^2 converges or diverges',
			concepts: ['Integration', 'Series']
		}
	];

	onMount(() => {
		const storedData = sessionStorage.getItem('generatedQuestions');
		console.log('[RightsideQuestions] onMount storedData', storedData);
		if (storedData) {
			const parsed = JSON.parse(storedData);
			console.log('[RightsideQuestions] parsed payload', parsed);
			generatedQuestions =
				parsed?.usePlaceholder || !(parsed?.concepts?.length ?? 0)
					? {
							...placeholderGeneratedQuestions,
							homework: parsed?.homework ?? placeholderGeneratedQuestions.homework,
							timestamp: parsed?.timestamp ?? null
						}
					: parsed;
			sessionStorage.removeItem('generatedQuestions');
			console.log('[RightsideQuestions] final payload', generatedQuestions);
		} else {
			generatedQuestions = placeholderGeneratedQuestions;
			console.log('[RightsideQuestions] using default placeholder payload');
		}
	});

	function closePanel() {
		console.log('[RightsideQuestions] closePanel');
		showRightsideQuestions.set(false);
		showControls.set(false);
	}
</script>

<div class="w-full h-full bg-white dark:bg-gray-900 flex flex-col">
	<div class="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
		<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200">AI Question Review</h3>
		<button
			on:click={closePanel}
			class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition"
			aria-label="Close panel"
		>
			<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-5 h-5 text-gray-600 dark:text-gray-400">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<div class="flex-1 overflow-y-auto p-4 space-y-4">
		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			You are reviewing AI suggested questions based on your conversation history. For more details, please visit the AI Tutor Dashboard located in the right-hand panel.
		</p>

		{#if generatedQuestions.homework}
			<div>
				<h4 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">Homework:</h4>
				<div class="text-sm text-gray-700 dark:text-gray-300">{generatedQuestions.homework}</div>
			</div>
		{/if}

		<div>
			<h4 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">Selected Topics:</h4>
			<div class="flex flex-wrap gap-2">
				{#each generatedQuestions.concepts as concept}
					<span class="px-3 py-1 text-xs font-medium bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 rounded-full">
						{concept}
					</span>
				{/each}
			</div>
		</div>

		<div class="pt-2">
			<h4 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-3">
				Based on the selection, below is the list of questions generated:
			</h4>

			<div class="space-y-3">
				{#each sampleQuestions as q}
					<div class="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
						<div class="flex items-start gap-2">
							<span class="flex-shrink-0 text-sm font-semibold text-gray-700 dark:text-gray-300">
								{q.number}.
							</span>
							<div class="flex-1">
								<p class="text-sm text-gray-900 dark:text-gray-100 mb-2">{q.question}</p>
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

		<div class="pt-2 border-t border-gray-200 dark:border-gray-700">
			<p class="text-xs text-gray-500 dark:text-gray-500 italic">
				Notes: the questions will be created as KB? TBD
			</p>
		</div>
	</div>
</div>
