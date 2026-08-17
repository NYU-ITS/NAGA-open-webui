<script lang="ts">
	import { getContext, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { retryEmbeddingJob } from '$lib/apis/embedding';
	import type { KnowledgeIndexingProgress, KnowledgeIndexingStatus } from '$lib/apis/knowledge';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import IndexingStatusBadge from './IndexingStatusBadge.svelte';

	const i18n = getContext('i18n');

	type GovernedKnowledgeBase = {
		id: string;
		name: string;
		failedDocumentCount: number;
		incompatibleDocumentCount: number;
		currentFileCount: number;
	};

	export let status: KnowledgeIndexingStatus;
	export let knowledgeBases: GovernedKnowledgeBase[] = [];
	export let statusLoadFailed = false;
	export let onRefresh: () => Promise<void> = async () => {};

	let showRetryConfirm = false;
	let retrying = false;

	$: affectedKnowledgeBases = knowledgeBases.filter(
		(knowledgeBase) => knowledgeBase.currentFileCount > 0 && knowledgeBase.failedDocumentCount > 0
	);

	const getHttpStatus = (error: unknown) => {
		if (typeof error !== 'object' || error === null || !('status' in error)) return null;
		return Number((error as { status?: number }).status) || null;
	};

	const getErrorCode = (error: unknown) => {
		if (typeof error !== 'object' || error === null || !('errorCode' in error)) return null;
		const errorCode = (error as { errorCode?: unknown }).errorCode;
		return typeof errorCode === 'string' ? errorCode : null;
	};

	const retryHandler = async () => {
		if (!status.job_id || !status.can_retry || retrying) return;
		const requestedJobId = status.job_id;
		retrying = true;
		try {
			await onRefresh();
			await tick();
			if (status.job_id !== requestedJobId || !status.can_retry) {
				toast.info($i18n.t('Indexing status changed. Review the updated status before retrying.'));
				return;
			}
			await retryEmbeddingJob(localStorage.token, requestedJobId);
			toast.success($i18n.t('Embedding reindex retry queued.'));
		} catch (error) {
			const errorCode = getErrorCode(error);
			if (
				errorCode === 'embedding_job_active_exists' ||
				errorCode === 'embedding_retry_active_exists'
			) {
				toast.info($i18n.t('Indexing is already queued or in progress.'));
			} else if (errorCode === 'embedding_reindex_source_changed') {
				toast.warning(
					$i18n.t('The indexed files changed. Start a fresh reindex by selecting the model again.')
				);
			} else if (getHttpStatus(error) === 409) {
				toast.warning(
					$i18n.t('This retry is no longer available. Review the updated indexing status.')
				);
			} else {
				toast.error(`${error}`);
			}
		} finally {
			retrying = false;
			await onRefresh();
		}
	};

	const formatTime = (timestamp: number | null) => {
		if (!timestamp) return $i18n.t('Not yet');
		return new Intl.DateTimeFormat(undefined, {
			dateStyle: 'medium',
			timeStyle: 'short'
		}).format(new Date(timestamp * 1000));
	};

	const progressValue = (progress: KnowledgeIndexingProgress) =>
		progress.processed + progress.failed + progress.incompatible;

	const progressPercent = (progress: KnowledgeIndexingProgress) =>
		progress.total > 0 ? Math.min(100, (progressValue(progress) / progress.total) * 100) : 0;
</script>

<ConfirmDialog
	bind:show={showRetryConfirm}
	title={$i18n.t(status.retry_kind === 'indexing_operation' ? 'Retry indexing?' : 'Retry failed documents?')}
	message={$i18n.t(
		'This retries every eligible failed document in this administrator-wide model-change job. Retry cannot be limited to one knowledge base and may also affect chat uploads.'
	)}
	confirmLabel={$i18n.t(
		status.retry_kind === 'indexing_operation' ? 'Retry indexing' : 'Retry failed documents'
	)}
	on:confirm={retryHandler}
/>

<section
	class="rounded-xl border border-gray-50 p-3 dark:border-gray-850"
	aria-label={$i18n.t('Embedding reindex for {{model}}', {
		model:
			status.target_model?.display_name ??
			status.active_model?.display_name ??
			$i18n.t('Unknown model')
	})}
>
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div>
			<h2 class="text-sm font-semibold">{$i18n.t('Embedding Reindex')}</h2>
			<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
				{status.job_type === 'retry_failed'
					? $i18n.t(
							"Retrieval status applies across this administrator's governed knowledge bases and chat uploads. This retry processes backend-selected failed files."
						)
					: $i18n.t(
							'This model-change reindex applies to all knowledge bases and chat uploads governed by the administrator.'
						)}
			</p>
			<p
				class={status.job_display_state === 'partial' || status.retrieval_available
					? 'mt-1 text-sm font-medium text-gray-700 dark:text-gray-200'
					: 'mt-0.5 text-xs text-gray-500 dark:text-gray-400'}
			>
				{status.job_display_state === 'partial'
					? $i18n.t('Completed sources are available; failed sources remain unavailable')
					: status.retrieval_available
					? $i18n.t('Available for Retrieval')
					: status.display_state === 'unavailable'
						? $i18n.t('Unavailable for retrieval')
						: $i18n.t('Unavailable for retrieval while reindexing is incomplete')}
			</p>
		</div>
		<div role="status" aria-live="polite">
			<IndexingStatusBadge state={status.job_display_state ?? status.display_state} />
		</div>
	</div>

	{#if statusLoadFailed}
		<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('The latest status could not be loaded. Showing the last known state.')}
		</p>
	{/if}

	<div class="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
		<div>
			<div class="font-medium text-gray-700 dark:text-gray-200">
				{status.target_model ? $i18n.t('Selected Model') : $i18n.t('Model')}
			</div>
			{#if status.target_model}
				<div class="mt-0.5 text-gray-500 dark:text-gray-400">
					{status.target_model.display_name}
				</div>
				<div class="text-gray-500 dark:text-gray-400">
					{$i18n.t('Modalities')}: {status.target_model.modalities.join(', ') || $i18n.t('None')}
				</div>
				{#if status.active_model && status.active_model.id !== status.target_model.id}
					<div class="mt-1 text-gray-500 dark:text-gray-400">
						{$i18n.t('Previous successful model')}: {status.active_model.display_name}
					</div>
				{/if}
				<p class="mt-1 text-gray-500 dark:text-gray-400">
					{$i18n.t('The selected model becomes active after every required file indexes successfully.')}
				</p>
			{:else if status.active_model}
				<div class="mt-0.5 text-gray-500 dark:text-gray-400">
					{status.active_model.display_name}
				</div>
				<div class="text-gray-500 dark:text-gray-400">
					{$i18n.t('Modalities')}: {status.active_model.modalities.join(', ') || $i18n.t('None')}
				</div>
			{:else}
				<div class="mt-0.5 text-gray-500 dark:text-gray-400">
					{$i18n.t('Model status unavailable')}
				</div>
			{/if}
		</div>
		<div>
			<div class="font-medium text-gray-700 dark:text-gray-200">
				{$i18n.t('Last Successful Reindex')}
			</div>
			<div class="mt-0.5 text-gray-500 dark:text-gray-400">
				{formatTime(status.last_successful_indexed_at)}
			</div>
		</div>
		<div>
			<div class="font-medium text-gray-700 dark:text-gray-200">
				{$i18n.t('Status Updated')}
			</div>
			<div class="mt-0.5 text-gray-500 dark:text-gray-400">
				{formatTime(status.updated_at)}
			</div>
		</div>
	</div>

	<div class="mt-3 rounded-xl bg-gray-50 p-3 dark:bg-gray-850">
		<div class="flex items-center justify-between gap-2 text-xs">
			<span class="text-sm font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Reindex Progress')}</span>
			<span class="text-gray-500 dark:text-gray-400">
				{progressValue(status.job_progress)}/{status.job_progress.total}
			</span>
		</div>
		{#if status.job_progress.total > 0}
			<div
				class="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
				role="progressbar"
				aria-label={$i18n.t('Reindex Progress')}
				aria-valuemin="0"
				aria-valuemax={status.job_progress.total}
				aria-valuenow={progressValue(status.job_progress)}
			>
				<div
					class="h-full bg-gray-900 dark:bg-gray-100"
					style:width={`${progressPercent(status.job_progress)}%`}
				/>
			</div>
		{/if}
		<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('Completed')}: {status.job_progress.processed} · {$i18n.t('Incompatible')}: {status
				.job_progress.incompatible} · {$i18n.t('Failed')}: {status.job_progress.failed} · {$i18n.t(
				'Remaining'
			)}: {status.job_progress.pending_or_processing}
		</p>
	</div>

	{#if status.error_message}
		<p class="mt-3 text-xs text-gray-600 dark:text-gray-300">{status.error_message}</p>
	{/if}

	{#if status.job_incompatible_document_count > 0}
		<div class="mt-3 rounded-xl bg-gray-50 px-3 py-2 text-xs dark:bg-gray-850">
			<p class="font-medium">
				{$i18n.t('{{count}} documents are incompatible with the current embedding model', {
					count: status.job_incompatible_document_count
				})}
			</p>
			<p class="mt-1 text-gray-500 dark:text-gray-400">
				{$i18n.t('These documents were skipped successfully and do not count as failures.')}
			</p>
		</div>
	{/if}

	{#if status.job_failed_document_count > 0}
		<div class="mt-3 rounded-xl bg-gray-50 px-3 py-2 text-xs dark:bg-gray-850">
			<p class="font-medium">
				{$i18n.t('{{count}} documents failed in this reindex job', {
					count: status.job_failed_document_count
				})}
			</p>
			{#if status.job_failed_documents?.length > 0}
				<ul class="mt-2 space-y-2">
					{#each status.job_failed_documents as failure}
						<li class="rounded-lg border border-gray-200 bg-white p-2 dark:border-gray-700 dark:bg-gray-900">
							<div class="font-medium">
								{failure.filename ?? failure.file_id}
							</div>
							<div class="mt-1 space-y-0.5 text-gray-500 dark:text-gray-400">
								{#if failure.knowledge_bases.length > 0}
									<div>
										{$i18n.t('Knowledge base')}:
										{#each failure.knowledge_bases as knowledgeBase, index}
											{#if index > 0}, {/if}<a
												class="font-medium underline underline-offset-2"
												href={`/workspace/knowledge/${knowledgeBase.id}`}
											>
												{knowledgeBase.name}
											</a>
										{/each}
									</div>
								{/if}
								{#if failure.source_contexts.includes('chat_upload')}
									<div>
										{$i18n.t('Source')}: {$i18n.t(
											'Direct upload in a chat (not a knowledge base)'
										)}
									</div>
								{/if}
								<div>
									{failure.error_message ?? $i18n.t('Indexing failed for this file.')}
								</div>
							</div>
						</li>
					{/each}
				</ul>
			{:else if affectedKnowledgeBases.length > 0}
				<p class="mt-1 text-gray-500 dark:text-gray-400">
					{$i18n.t('Open an affected knowledge base to view its scoped failure details.')}
				</p>
				<div class="mt-1 flex flex-wrap gap-x-2 gap-y-1">
					{#each affectedKnowledgeBases as knowledgeBase}
						<a
							class="font-medium underline underline-offset-2"
							href={`/workspace/knowledge/${knowledgeBase.id}`}
						>
							{knowledgeBase.name}
						</a>
					{/each}
				</div>
			{:else}
				<p class="mt-1 text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'The failed file is outside the knowledge bases shown here. The governing administrator can view its details.'
					)}
				</p>
			{/if}
		</div>
	{/if}

	<details class="mt-3 text-xs">
		<summary class="cursor-pointer font-medium text-gray-700 dark:text-gray-200">
			{$i18n.t('{{count}} knowledge bases you can edit inherit this reindex status', {
				count: knowledgeBases.length
			})}
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

	{#if status.can_retry}
		<div class="mt-3 flex justify-end">
			<button
				class="rounded-full bg-black px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-gray-900 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-black dark:hover:bg-gray-100"
				type="button"
				disabled={retrying}
				on:click={() => {
					showRetryConfirm = true;
				}}
			>
				{retrying
					? $i18n.t('Retrying…')
					: status.retry_kind === 'indexing_operation'
						? $i18n.t('Retry indexing')
						: $i18n.t('Retry failed documents')}
			</button>
		</div>
	{:else if status.retry_eligible}
		<p class="mt-3 text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('Only the governing administrator can retry this indexing job.')}
		</p>
	{/if}
</section>
