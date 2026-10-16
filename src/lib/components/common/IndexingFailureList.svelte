<script lang="ts">
	import { getContext } from 'svelte';
	import type { KnowledgeIndexingFailure } from '$lib/apis/knowledge';

	const i18n = getContext('i18n');
	export let failures: KnowledgeIndexingFailure[] = [];
	export let showChatUploads = false;

	const nextAction = (code: string | null) => {
		switch (code) {
			case 'file_missing':
			case 'embedding_file_not_found':
				return $i18n.t('Upload the file again, or remove its reference if it is no longer needed.');
			case 'storage_read_failed':
				return $i18n.t('Restore access to the original upload, then retry.');
			case 'credentials_missing':
			case 'embedding_credentials_missing':
			case 'admin_model_resolution_failed':
				return $i18n.t('Check the embedding model and API credentials in Documents settings, then retry.');
			case 'empty_content':
			case 'extraction_failed':
			case 'embedding_image_invalid':
			case 'embedding_image_format_unsupported':
			case 'video_validation_failed':
			case 'video_duration_exceeded':
				return $i18n.t('Replace the upload with a readable file in a supported format.');
			default:
				return $i18n.t('Retry failed files. If the failure persists, check the source file and embedding service.');
		}
	};
</script>

<ul class="mt-2 max-h-72 space-y-2 overflow-y-auto text-xs">
	{#each failures as failure (failure.file_id)}
		<li class="rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-900">
			<div class="break-all font-medium">{failure.filename ?? failure.file_id}</div>
			{#if failure.knowledge_bases.length > 0}
				<div class="mt-1 text-gray-500 dark:text-gray-400">
					{$i18n.t('Knowledge collection')}:
					{#each failure.knowledge_bases as collection, index}
						{#if index > 0}, {/if}<a
							class="underline underline-offset-2"
							href={`/workspace/knowledge/${encodeURIComponent(collection.id)}`}
						>{collection.name}</a>
					{/each}
				</div>
			{/if}
			{#if showChatUploads && failure.source_contexts.includes('chat_upload')}
				<div class="mt-1 text-gray-500 dark:text-gray-400">{$i18n.t('Chat upload')}</div>
			{/if}
			<p class="mt-2">{failure.error_message ?? $i18n.t('Indexing failed for this file.')}</p>
			<p class="mt-1 text-gray-500 dark:text-gray-400">{nextAction(failure.error_code)}</p>
		</li>
	{/each}
</ul>
