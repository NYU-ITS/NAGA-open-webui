<script lang="ts">
	import { getContext } from 'svelte';

	import type { EmbeddingModelSummary } from '$lib/apis/knowledge';
	import IndexingStatusBadge from './IndexingStatusBadge.svelte';

	const i18n = getContext('i18n');

	type VisibleKnowledgeBase = {
		id: string;
		name: string;
	};

	type ModelPresentation =
		| { kind: 'legacy' }
		| { kind: 'single'; model: EmbeddingModelSummary }
		| { kind: 'mixed' };

	type SharedTimestamp = number | null | 'varies';

	export let knowledgeBases: VisibleKnowledgeBase[] = [];
	export let modelPresentation: ModelPresentation = { kind: 'legacy' };
	export let lastSuccessfulIndexedAt: SharedTimestamp = null;
	export let statusLoadFailed = false;

	const formatLastReindex = (timestamp: SharedTimestamp) => {
		if (timestamp === 'varies') return $i18n.t('Varies');
		if (!timestamp) return $i18n.t('No recorded job');
		return new Intl.DateTimeFormat(undefined, {
			dateStyle: 'medium',
			timeStyle: 'short'
		}).format(new Date(timestamp * 1000));
	};
</script>

<section
	class="rounded-xl border border-gray-50 p-3 dark:border-gray-850"
	aria-label={$i18n.t('Embedding index status')}
>
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div>
			<h2 class="text-sm font-semibold">{$i18n.t('Embedding index')}</h2>
			<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('Available for retrieval')}
			</p>
		</div>
		<IndexingStatusBadge state="ready" />
	</div>

	{#if statusLoadFailed}
		<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('The latest status could not be loaded. Showing the last known state.')}
		</p>
	{/if}

	<div class="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
		<div>
			<div class="font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Model')}</div>
			{#if modelPresentation.kind === 'single'}
				<div class="mt-0.5 text-gray-500 dark:text-gray-400">
					{modelPresentation.model.display_name} · {modelPresentation.model.provider}
				</div>
			{:else if modelPresentation.kind === 'mixed'}
				<div class="mt-0.5 text-gray-500 dark:text-gray-400">
					{$i18n.t('Multiple or legacy model configurations')}
				</div>
			{:else}
				<div class="mt-0.5 text-gray-500 dark:text-gray-400">
					{$i18n.t('Legacy model configuration')}
				</div>
			{/if}
		</div>
		<div>
			<div class="font-medium text-gray-700 dark:text-gray-200">
				{$i18n.t('Last recorded model-change reindex')}
			</div>
			<div class="mt-0.5 text-gray-500 dark:text-gray-400">
				{formatLastReindex(lastSuccessfulIndexedAt)}
			</div>
		</div>
	</div>

	<p class="mt-3 text-xs text-gray-500 dark:text-gray-400">
		{$i18n.t(
			'Included editable knowledge bases: {{count}}. No current durable model-change reindex job is associated with them, and their governing administrators may differ.',
			{ count: knowledgeBases.length }
		)}
	</p>

	<details class="mt-2 text-xs">
		<summary class="cursor-pointer font-medium text-gray-700 dark:text-gray-200">
			{$i18n.t('View included knowledge bases')}
		</summary>
		<ul class="mt-2 max-h-32 space-y-1 overflow-y-auto pl-4 text-gray-500 dark:text-gray-400">
			{#each knowledgeBases as knowledgeBase}
				<li>
					<a class="hover:underline" href={`/workspace/knowledge/${knowledgeBase.id}`}>
						{knowledgeBase.name}
					</a>
				</li>
			{/each}
		</ul>
	</details>
</section>
