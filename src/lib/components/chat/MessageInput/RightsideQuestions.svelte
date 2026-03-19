<script lang="ts">
	import { showControls, showRightsideQuestions } from '$lib/stores';

	function closePanel() {
		showRightsideQuestions.set(false);
		showControls.set(false);
	}
</script>

<div class="flex h-full w-full flex-col bg-white dark:bg-gray-900">
	<div class="flex items-center justify-between border-b border-gray-200 p-4 dark:border-gray-700">
		<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-200">AI Question Review</h3>
		<button
			on:click={closePanel}
			class="rounded p-1 transition hover:bg-gray-100 dark:hover:bg-gray-800"
			aria-label="Close panel"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke-width="2"
				stroke="currentColor"
				class="h-5 w-5 text-gray-600 dark:text-gray-400"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
			</svg>
		</button>
	</div>

	<div class="flex flex-1 items-center justify-center p-6">
		<div class="max-w-sm text-center">
			<div class="text-sm font-medium text-gray-800 dark:text-gray-200">Practice Questions</div>
			<p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
				This panel is ready for the question review UI.
			</p>
		</div>
	</div>
</div>
