<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';

	import {
		getKnowledgeIndexingStatus,
		type KnowledgeIndexingProgress,
		type KnowledgeIndexingStatus
	} from '$lib/apis/knowledge';
	import IndexingStatusBadge from '../IndexingStatusBadge.svelte';

	const i18n = getContext('i18n');

	export let knowledgeId: string;

	let status: KnowledgeIndexingStatus | null = null;
	let loading = true;
	let temporarilyUnavailable = false;
	let hiddenByAuthorization = false;
	let requestInFlight = false;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	$: showImpact =
		!hiddenByAuthorization &&
		!loading &&
		((status === null && temporarilyUnavailable) ||
			(status !== null &&
			(!status.retrieval_available ||
				status.failed_document_count > 0 ||
				status.incompatible_document_count > 0)));

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

	const refreshStatus = async () => {
		if (requestInFlight || destroyed || !knowledgeId) return;
		requestInFlight = true;

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
			if (!destroyed) schedulePolling();
		}
	};

	const handleVisibilityChange = () => {
		if (document.visibilityState === 'hidden') {
			stopPolling();
		} else {
			refreshStatus();
		}
	};

	const progressValue = (progress: KnowledgeIndexingProgress) =>
		progress.processed + progress.failed + progress.incompatible;

	const progressPercent = (progress: KnowledgeIndexingProgress) =>
		progress.total > 0 ? Math.min(100, (progressValue(progress) / progress.total) * 100) : 0;

	const impactMessage = (indexingStatus: KnowledgeIndexingStatus) => {
		if (indexingStatus.retrieval_available && indexingStatus.failed_document_count > 0) {
			return $i18n.t(
				'The latest administrator-wide reindex has failures for documents in this knowledge base.'
			);
		}
		if (indexingStatus.retrieval_available && indexingStatus.incompatible_document_count > 0) {
			return $i18n.t(
				'Some documents contain content incompatible with the current embedding model.'
			);
		}
		if (indexingStatus.display_state === 'failed' || indexingStatus.display_state === 'partial') {
			return $i18n.t(
				'The administrator-wide reindex did not complete, so retrieval remains unavailable for this knowledge base.'
			);
		}
		if (indexingStatus.job_status === 'queued' || indexingStatus.job_status === 'processing') {
			return $i18n.t(
				'Retrieval is temporarily unavailable for this knowledge base while its governing embedding index is being rebuilt.'
			);
		}
		return $i18n.t(
			'Retrieval is currently unavailable because the governing embedding index is not ready.'
		);
	};

	onMount(() => {
		document.addEventListener('visibilitychange', handleVisibilityChange);
		refreshStatus();
	});

	onDestroy(() => {
		destroyed = true;
		stopPolling();
		document.removeEventListener('visibilitychange', handleVisibilityChange);
	});
</script>

{#if showImpact}
	<section
		class="mx-1 my-3 rounded-xl border border-gray-50 p-3 dark:border-gray-850"
		aria-label={$i18n.t('Embedding Impact')}
	>
		{#if status}
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div>
					<h2 class="text-sm font-semibold">{$i18n.t('Embedding Impact')}</h2>
					<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
						{impactMessage(status)}
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

			{#if status.job_id}
				<div class="mt-3 rounded-xl bg-gray-50 p-3 dark:bg-gray-850">
					<div class="flex items-center justify-between gap-2 text-xs">
						<span class="font-medium">
							{$i18n.t('Files from this knowledge base in the current job')}
						</span>
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
						<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Completed')}: {status.collection_progress.processed} · {$i18n.t(
								'Incompatible'
							)}: {status.collection_progress.incompatible} · {$i18n.t('Failed')}: {status
								.collection_progress.failed} · {$i18n.t('Remaining')}: {status
								.collection_progress.pending_or_processing}
						</p>
					{:else}
						<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t(
								'No files from this knowledge base are in the current attempt; retrieval availability still follows the administrator-wide job.'
							)}
						</p>
					{/if}
				</div>
			{/if}

			{#if status.failed_document_count > 0}
				<details class="mt-3 rounded-xl bg-gray-50 px-3 py-2 text-xs dark:bg-gray-850">
					<summary class="cursor-pointer font-medium">
						{$i18n.t('{{count}} documents in this knowledge base failed to reindex', {
							count: status.failed_document_count
						})}
					</summary>
					{#if status.failed_documents?.length}
						<ul class="mt-2 max-h-40 space-y-2 overflow-y-auto">
							{#each status.failed_documents as failure}
								<li class="rounded-lg border border-gray-100 p-2 dark:border-gray-700">
									<div class="break-all font-medium">{failure.file_id}</div>
									<div class="mt-1 text-gray-500 dark:text-gray-400">
										{failure.error_message ??
											$i18n.t('Indexing failed for this document.')}
									</div>
									<div class="mt-0.5 text-gray-500 dark:text-gray-400">
										{$i18n.t('Attempts')}: {failure.attempt_count}
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</details>
			{/if}

			{#if status.incompatible_document_count > 0}
				<details class="mt-3 rounded-xl bg-gray-50 px-3 py-2 text-xs dark:bg-gray-850">
					<summary class="cursor-pointer font-medium">
						{$i18n.t('{{count}} documents are incompatible with the current embedding model', {
							count: status.incompatible_document_count
						})}
					</summary>
					{#if status.incompatible_documents?.length}
						<ul class="mt-2 max-h-40 space-y-2 overflow-y-auto">
							{#each status.incompatible_documents as incompatible}
								<li class="rounded-lg border border-gray-100 p-2 dark:border-gray-700">
									<div class="break-all font-medium">{incompatible.file_id}</div>
									<div class="mt-1 text-gray-500 dark:text-gray-400">
										{$i18n.t('This document is incompatible with the current embedding model.')}
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</details>
			{/if}

			{#if status.job_id}
				<div class="mt-3 text-xs text-gray-500 dark:text-gray-400">
					<p>
						{$i18n.t(
							'Reindex and retry are managed for the full administrator-wide job and cannot target only this knowledge base.'
						)}
					</p>
					<a
						class="mt-1 inline-block font-medium text-gray-700 underline underline-offset-2 dark:text-gray-200"
						href="/workspace/knowledge"
					>
						{$i18n.t('View reindex status')}
					</a>
				</div>
			{/if}
		{:else if temporarilyUnavailable}
			<h2 class="text-sm font-semibold">{$i18n.t('Embedding Impact')}</h2>
			<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('Indexing status is temporarily unavailable.')}
			</p>
		{/if}
	</section>
{/if}
