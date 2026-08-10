<script lang="ts">
	import Fuse from 'fuse.js';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onMount, onDestroy, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, knowledge } from '$lib/stores';
	import {
		getKnowledgeBases,
		deleteKnowledgeById,
		getKnowledgeBaseList,
		getKnowledgeIndexingStatuses,
		type KnowledgeIndexingStatus
	} from '$lib/apis/knowledge';

	import { goto } from '$app/navigation';

	import DeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import ItemMenu from './Knowledge/ItemMenu.svelte';
	import Badge from '../common/Badge.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import Spinner from '../common/Spinner.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import Tooltip from '../common/Tooltip.svelte';
	import IndexingStatusBadge from './Knowledge/IndexingStatusBadge.svelte';

	let loaded = false;

	let query = '';
	let selectedItem = null;
	let showDeleteConfirm = false;

	let fuse = null;

	let knowledgeBases = [];
	let filteredItems = [];
	let indexingStatuses: Record<string, KnowledgeIndexingStatus> = {};
	let indexingPollTimer: ReturnType<typeof setTimeout> | null = null;
	let indexingStatusRequestInFlight = false;
	let indexingStatusLoadFailed = false;
	let destroyed = false;

	const getHttpStatus = (error: unknown) => {
		if (typeof error !== 'object' || error === null || !('status' in error)) return null;
		return Number((error as { status?: number }).status) || null;
	};

	const hasActiveIndexingJob = () =>
		Object.values(indexingStatuses).some(
			(status) => status.job_status === 'queued' || status.job_status === 'processing'
		);

	const stopIndexingPolling = () => {
		if (indexingPollTimer) {
			clearTimeout(indexingPollTimer);
			indexingPollTimer = null;
		}
	};

	const scheduleIndexingPolling = () => {
		stopIndexingPolling();
		if (
			destroyed ||
			document.visibilityState === 'hidden' ||
			(!hasActiveIndexingJob() && !indexingStatusLoadFailed)
		) {
			return;
		}
		indexingPollTimer = setTimeout(() => {
			refreshIndexingStatuses();
		}, 5000);
	};

	const refreshIndexingStatuses = async () => {
		if (indexingStatusRequestInFlight || destroyed) return;
		indexingStatusRequestInFlight = true;
		try {
			const statuses = await getKnowledgeIndexingStatuses(localStorage.token);
			if (!destroyed) {
				indexingStatuses = Object.fromEntries(
					statuses.map((status) => [status.knowledge_id, status])
				);
				indexingStatusLoadFailed = false;
			}
		} catch (error) {
			// Keep the last durable status on transient request failures.
			if (!destroyed) {
				const httpStatus = getHttpStatus(error);
				if (httpStatus === 401 || httpStatus === 403) {
					indexingStatuses = {};
					indexingStatusLoadFailed = false;
				} else {
					indexingStatusLoadFailed = true;
				}
			}
		} finally {
			indexingStatusRequestInFlight = false;
			if (!destroyed) scheduleIndexingPolling();
		}
	};

	const handleVisibilityChange = () => {
		if (document.visibilityState === 'hidden') {
			stopIndexingPolling();
		} else {
			refreshIndexingStatuses();
		}
	};

	$: if (knowledgeBases) {
		fuse = new Fuse(knowledgeBases, {
			keys: ['name', 'description']
		});
	}

	$: if (fuse) {
		filteredItems = query
			? fuse.search(query).map((e) => {
					return e.item;
				})
			: knowledgeBases;
	}

	const deleteHandler = async (item) => {
		const res = await deleteKnowledgeById(localStorage.token, item.id).catch((e) => {
			toast.error(`${e}`);
		});

		if (res) {
			knowledgeBases = await getKnowledgeBaseList(localStorage.token);
			knowledge.set(await getKnowledgeBases(localStorage.token));
			await refreshIndexingStatuses();
			toast.success($i18n.t('Knowledge deleted successfully.'));
		}
	};

	onMount(() => {
		document.addEventListener('visibilitychange', handleVisibilityChange);
		void (async () => {
			let statusLoadFailed = false;
			const [bases, statuses] = await Promise.all([
				getKnowledgeBaseList(localStorage.token).catch((error) => {
					toast.error(`${error}`);
					return [];
				}),
				getKnowledgeIndexingStatuses(localStorage.token).catch((error) => {
					const httpStatus = getHttpStatus(error);
					statusLoadFailed = httpStatus !== 401 && httpStatus !== 403;
					return null;
				})
			]);
			if (destroyed) return;

			knowledgeBases = bases;
			if (statuses) {
				indexingStatuses = Object.fromEntries(
					statuses.map((status) => [status.knowledge_id, status])
				);
			}
			indexingStatusLoadFailed = statusLoadFailed;
			loaded = true;
			scheduleIndexingPolling();
		})();
	});

	onDestroy(() => {
		destroyed = true;
		stopIndexingPolling();
		document.removeEventListener('visibilitychange', handleVisibilityChange);
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Knowledge')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			deleteHandler(selectedItem);
		}}
	/>

	<div class="flex flex-col gap-1 my-1.5">
		<div class="flex justify-between items-center">
			<div class="flex md:self-center text-xl font-medium px-0.5 items-center">
				{$i18n.t('Knowledge')}
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
					>{filteredItems.length}</span
				>
			</div>
		</div>

		<div class=" flex w-full space-x-2">
			<div class="flex flex-1">
				<div class=" self-center ml-1 mr-3">
					<Search className="size-3.5" />
				</div>
				<input
					class=" w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
					bind:value={query}
					placeholder={$i18n.t('Search Knowledge')}
				/>
			</div>

			<div>
				<button
					class=" px-2 py-2 rounded-xl hover:bg-gray-700/10 dark:hover:bg-gray-100/10 dark:text-gray-300 dark:hover:text-white transition font-medium text-sm flex items-center space-x-1"
					aria-label={$i18n.t('Create Knowledge')}
					on:click={() => {
						goto('/workspace/knowledge/create');
					}}
				>
					<Plus className="size-3.5" />
				</button>
			</div>
		</div>
	</div>

	<div class="mb-5 grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-2">
		{#each filteredItems as item}
			<button
				class=" flex space-x-4 cursor-pointer text-left w-full px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-850 transition rounded-xl"
				on:click={() => {
					if (item?.meta?.document) {
						toast.error(
							$i18n.t(
								'Only collections can be edited, create a new knowledge base to edit/add documents.'
							)
						);
					} else {
						goto(`/workspace/knowledge/${item.id}`);
					}
				}}
			>
				<div class=" w-full">
					<div class="flex items-center justify-between -mt-1">
						<div class="flex items-center gap-1">
							{#if item?.meta?.document}
								<Badge type="muted" content={$i18n.t('Document')} />
							{:else}
								<Badge type="success" content={$i18n.t('Collection')} />
								{#if indexingStatuses[item.id]}
									<IndexingStatusBadge state={indexingStatuses[item.id].display_state} />
								{:else if indexingStatusLoadFailed}
									<Badge type="muted" content={$i18n.t('Status unavailable')} />
								{/if}
							{/if}
						</div>

						<div class=" flex self-center -mr-1 translate-y-1">
							<ItemMenu
								on:delete={() => {
									selectedItem = item;
									showDeleteConfirm = true;
								}}
							/>
						</div>
					</div>

					<div class=" self-center flex-1 px-1 mb-1">
						<div class=" font-semibold line-clamp-1 h-fit">{item.name}</div>

						<div class=" text-xs overflow-hidden text-ellipsis line-clamp-1">
							{item.description}
						</div>

						<div class="mt-3 flex justify-between">
							<div class="text-xs text-gray-600 dark:text-gray-500">
								<Tooltip
									content={item?.user?.email ?? $i18n.t('Deleted User')}
									className="flex shrink-0"
									placement="top-start"
								>
									{$i18n.t('By {{name}}', {
										name: capitalizeFirstLetter(
											item?.user?.name ?? item?.user?.email ?? $i18n.t('Deleted User')
										)
									})}
								</Tooltip>
							</div>
							<div class=" text-xs text-gray-600 dark:text-gray-500 line-clamp-1">
								{$i18n.t('Updated')}
								{dayjs(item.updated_at * 1000).fromNow()}
							</div>
						</div>
					</div>
				</div>
			</button>
		{/each}
	</div>

	<div class=" text-gray-500 text-xs mt-1 mb-2">
		ⓘ {$i18n.t("Use '#' in the prompt input to load and include your knowledge.")}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
