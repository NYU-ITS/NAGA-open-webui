<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getKnowledgeIndexingStatus,
		type KnowledgeIndexingProgress,
		type KnowledgeIndexingStatus
	} from '$lib/apis/knowledge';
	import { retryEmbeddingJob } from '$lib/apis/embedding';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import IndexingStatusBadge from '../IndexingStatusBadge.svelte';

	const i18n = getContext('i18n');

	export let knowledgeId: string;

	let status: KnowledgeIndexingStatus | null = null;
	let loading = true;
	let temporarilyUnavailable = false;
	let hiddenByAuthorization = false;
	let showRetryConfirm = false;
	let retrying = false;
	let requestInFlight = false;
	let refreshRequested = false;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	const stopPolling = () => {
		if (pollTimer) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
	};

	const hasActiveJob = () =>
		status?.job_status === 'queued' || status?.job_status === 'processing';

	const schedulePolling = () => {
		stopPolling();
		if (
			destroyed ||
			hiddenByAuthorization ||
			document.visibilityState === 'hidden' ||
			(!hasActiveJob() && !temporarilyUnavailable)
		) {
			return;
		}
		pollTimer = setTimeout(() => {
			refreshStatus();
		}, 5000);
	};

	const getHttpStatus = (error: unknown) => {
		if (typeof error !== 'object' || error === null || !('status' in error)) return null;
		return Number((error as { status?: number }).status) || null;
	};

	const refreshStatus = async (showLoading = false) => {
		if (requestInFlight) {
			refreshRequested = true;
			return;
		}
		if (destroyed || !knowledgeId) return;
		requestInFlight = true;
		if (showLoading && !status) loading = true;

		try {
			const nextStatus = await getKnowledgeIndexingStatus(localStorage.token, knowledgeId);
			if (!destroyed) {
				status = nextStatus;
				temporarilyUnavailable = false;
				hiddenByAuthorization = false;
			}
		} catch (error) {
			if (!destroyed) {
				const httpStatus = getHttpStatus(error);
				if (httpStatus === 401 || httpStatus === 403 || httpStatus === 404) {
					status = null;
					temporarilyUnavailable = false;
					hiddenByAuthorization = true;
				} else {
					temporarilyUnavailable = true;
				}
			}
		} finally {
			requestInFlight = false;
			loading = false;
			if (refreshRequested && !destroyed) {
				refreshRequested = false;
				refreshStatus();
			} else if (!destroyed) {
				schedulePolling();
			}
		}
	};

	const handleVisibilityChange = () => {
		if (document.visibilityState === 'hidden') {
			stopPolling();
		} else {
			refreshStatus();
		}
	};

	const retryHandler = async () => {
		if (!status?.job_id || !status.can_retry || retrying) return;
		retrying = true;
		try {
			await retryEmbeddingJob(localStorage.token, status.job_id);
			toast.success($i18n.t('Embedding reindex retry queued.'));
		} catch (error) {
			if (getHttpStatus(error) === 409) {
				toast.warning(
					$i18n.t('The indexing job changed before retry. The latest status has been loaded.')
				);
			} else {
				toast.error(`${error}`);
			}
		} finally {
			retrying = false;
			await refreshStatus();
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
		progress.processed + progress.failed;

	const progressPercent = (progress: KnowledgeIndexingProgress) =>
		progress.total > 0 ? Math.min(100, (progressValue(progress) / progress.total) * 100) : 0;

	onMount(() => {
		document.addEventListener('visibilitychange', handleVisibilityChange);
		refreshStatus(true);
	});

	onDestroy(() => {
		destroyed = true;
		stopPolling();
		document.removeEventListener('visibilitychange', handleVisibilityChange);
	});
</script>

{#if !hiddenByAuthorization}
	<ConfirmDialog
		bind:show={showRetryConfirm}
		title={$i18n.t('Retry embedding reindex?')}
		message={$i18n.t(
			'This retries the backend-defined model-change job scope, including affected documents outside this knowledge base.'
		)}
		confirmLabel={$i18n.t('Retry')}
		on:confirm={retryHandler}
	/>

	<section
		class="mx-1 my-3 rounded-xl border border-gray-50 p-3 dark:border-gray-850"
		aria-label={$i18n.t('Embedding index')}
	>
		{#if loading && !status}
			<div
				class="flex min-h-12 items-center justify-center"
				role="status"
				aria-label={$i18n.t('Loading')}
			>
				<Spinner />
			</div>
		{:else if status}
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div>
					<h2 id="knowledge-indexing-status-title" class="text-sm font-semibold">
						{$i18n.t('Embedding index')}
					</h2>
					<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
						{status.retrieval_available
							? $i18n.t('Available for retrieval')
							: status.display_state === 'unavailable'
								? $i18n.t('Unavailable for retrieval')
								: $i18n.t('Unavailable for retrieval while reindexing is incomplete')}
					</p>
				</div>
				<div role="status" aria-live="polite">
					<IndexingStatusBadge state={status.display_state} />
				</div>
			</div>

			{#if temporarilyUnavailable}
				<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('The latest status could not be loaded. Showing the last known state.')}
				</p>
			{/if}

			<div class="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
				<div>
					<div class="font-medium text-gray-700 dark:text-gray-200">
						{status.target_model ? $i18n.t('Target model') : $i18n.t('Model')}
					</div>
					{#if status.target_model}
						<div class="mt-0.5 text-gray-500 dark:text-gray-400">
							{status.target_model.display_name} · {status.target_model.provider}
						</div>
						<div class="text-gray-500 dark:text-gray-400">
							{$i18n.t('Modalities')}: {status.target_model.modalities.join(', ') ||
								$i18n.t('None')}
						</div>
						{#if status.active_model}
							<div class="mt-1 text-gray-500 dark:text-gray-400">
								{$i18n.t('Active model')}: {status.active_model.display_name}
							</div>
						{/if}
					{:else if status.active_model}
						<div class="mt-0.5 text-gray-500 dark:text-gray-400">
							{status.active_model.display_name} · {status.active_model.provider}
						</div>
						<div class="text-gray-500 dark:text-gray-400">
							{$i18n.t('Modalities')}: {status.active_model.modalities.join(', ') ||
								$i18n.t('None')}
						</div>
					{:else}
						<div class="mt-0.5 text-gray-500 dark:text-gray-400">
							{status.display_state === 'ready'
								? $i18n.t('Legacy model configuration')
								: $i18n.t('Model status unavailable')}
						</div>
					{/if}
				</div>
				<div>
					<div class="font-medium text-gray-700 dark:text-gray-200">
						{$i18n.t('Last successful reindex')}
					</div>
					<div class="mt-0.5 text-gray-500 dark:text-gray-400">
						{formatTime(status.last_successful_indexed_at)}
					</div>
				</div>
				<div>
					<div class="font-medium text-gray-700 dark:text-gray-200">
						{$i18n.t('Status updated')}
					</div>
					<div class="mt-0.5 text-gray-500 dark:text-gray-400">
						{formatTime(status.updated_at)}
					</div>
				</div>
			</div>

			{#if status.job_id}
				<div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
					<div class="rounded-xl bg-gray-50 p-3 dark:bg-gray-850">
						<div class="flex items-center justify-between gap-2 text-xs">
							<span class="font-medium">{$i18n.t('This knowledge base (current attempt)')}</span>
							<span class="text-gray-500 dark:text-gray-400">
								{progressValue(status.collection_progress)}/{status.collection_progress.total}
							</span>
						</div>
						{#if status.collection_progress.total > 0}
							<div
								class="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
								role="progressbar"
								aria-label={$i18n.t('Knowledge base indexing progress')}
								aria-valuemin="0"
								aria-valuemax={status.collection_progress.total}
								aria-valuenow={progressValue(status.collection_progress)}
							>
								<div
									class="h-full bg-gray-900 dark:bg-gray-100"
									style:width={`${progressPercent(status.collection_progress)}%`}
								/>
							</div>
						{:else}
							<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
								{$i18n.t('No files from this knowledge base are in the current indexing attempt.')}
							</p>
						{/if}
						<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Completed')}: {status.collection_progress.processed} · {$i18n.t(
								'Failed'
							)}: {status.collection_progress.failed} · {$i18n.t('Remaining')}: {status
								.collection_progress.pending_or_processing}
						</p>
					</div>

					<div class="rounded-xl bg-gray-50 p-3 dark:bg-gray-850">
						<div class="flex items-center justify-between gap-2 text-xs">
							<span class="font-medium">{$i18n.t('Whole reindex job')}</span>
							<span class="text-gray-500 dark:text-gray-400">
								{progressValue(status.job_progress)}/{status.job_progress.total}
							</span>
						</div>
						{#if status.job_progress.total > 0}
							<div
								class="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
								role="progressbar"
								aria-label={$i18n.t('Whole reindex job progress')}
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
							{$i18n.t('Completed')}: {status.job_progress.processed} · {$i18n.t(
								'Failed'
							)}: {status.job_progress.failed} · {$i18n.t('Remaining')}: {status.job_progress
								.pending_or_processing}
						</p>
					</div>
				</div>
			{:else}
				<p class="mt-3 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('No model-change reindex has run for this knowledge base.')}
				</p>
			{/if}

			{#if status.error_message}
				<p class="mt-3 text-xs text-gray-600 dark:text-gray-300">
					{status.error_message}
				</p>
			{/if}

			{#if status.failed_document_count > 0 || status.job_failed_document_count > 0}
				<details class="mt-3 rounded-xl bg-gray-50 px-3 py-2 text-xs dark:bg-gray-850">
					<summary class="cursor-pointer font-medium">
						{status.failed_document_count > 0
							? $i18n.t('{{count}} failed documents in this knowledge base', {
									count: status.failed_document_count
								})
							: $i18n.t('Failures elsewhere in the reindex job')}
					</summary>
					{#if status.failed_documents?.length}
						<ul class="mt-2 max-h-40 space-y-2 overflow-y-auto">
							{#each status.failed_documents as failure}
								<li class="rounded-lg border border-gray-100 p-2 dark:border-gray-700">
									<div class="break-all font-medium">{failure.file_id}</div>
									<div class="mt-1 text-gray-500 dark:text-gray-400">
										{failure.error_message ?? $i18n.t('Indexing failed for this document.')}
									</div>
									<div class="mt-0.5 text-gray-500 dark:text-gray-400">
										{$i18n.t('Attempts')}: {failure.attempt_count}
									</div>
								</li>
							{/each}
						</ul>
					{:else}
						<p class="mt-2 text-gray-500 dark:text-gray-400">
							{$i18n.t(
								'The whole reindex job has {{count}} failed documents, but none are in this knowledge base for the current attempt.',
								{ count: status.job_failed_document_count }
							)}
						</p>
					{/if}
				</details>
			{/if}

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
						{retrying ? $i18n.t('Retrying…') : $i18n.t('Retry indexing')}
					</button>
				</div>
			{:else if status.retry_eligible}
				<p class="mt-3 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Contact the governing administrator to retry the failed indexing job.')}
				</p>
			{/if}
		{:else if temporarilyUnavailable}
			<div>
				<h2 id="knowledge-indexing-status-title" class="text-sm font-semibold">
					{$i18n.t('Embedding index')}
				</h2>
				<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Indexing status is temporarily unavailable.')}
				</p>
			</div>
		{/if}
	</section>
{/if}
