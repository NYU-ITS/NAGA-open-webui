<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	import FileItem from '$lib/components/common/FileItem.svelte';

	export let selectedFileId = null;
	export let files = [];

	export let small = false;
</script>

<div class=" max-h-full flex flex-col w-full">
	{#each files as file}
		<div class="mt-1 px-2">
			<FileItem
				className="w-full"
				colorClassName="{selectedFileId === file.id
					? ' bg-gray-50 dark:bg-gray-850'
					: 'bg-transparent'} hover:bg-gray-50 dark:hover:bg-gray-850 transition"
				{small}
				showProcessingDetails
				item={file}
				name={file?.name ?? file?.meta?.name}
				type="file"
				size={file?.size ?? file?.meta?.size ?? ''}
				loading={file.status === 'uploading' || file.status === 'processing'}
				dismissible
				on:click={() => {
					if (file.status === 'uploading' || file.status === 'processing') {
						return;
					}

					dispatch('click', file.id);
				}}
				on:dismiss={() => {
					if (file.status === 'uploading' || file.status === 'processing') {
						return;
					}

					dispatch('delete', file.id);
				}}
			/>
			{#if file.status === 'error'}
				<div class="mt-1 flex justify-end px-2">
					<button
						class="text-xs font-medium text-gray-600 underline hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
						type="button"
						on:click={() => dispatch('retry', file.id)}
					>
						Retry processing
					</button>
				</div>
			{/if}
			{#if file?.audio_embedding?.repairable || ['queued', 'repairing'].includes(file?.audio_embedding?.status)}
				<div class="mt-1 flex justify-end px-2">
					<button
						class="text-xs font-medium text-amber-700 underline hover:text-amber-900 disabled:cursor-wait disabled:no-underline disabled:opacity-60 dark:text-amber-300"
						type="button"
						disabled={!file.audio_embedding.repairable}
						on:click={() => dispatch('retryAudio', file.id)}
					>
						{file.audio_embedding.repairable ? 'Retry audio' : file.audio_embedding.status === 'queued' ? 'Audio queued…' : 'Repairing audio…'}
					</button>
				</div>
			{/if}
		</div>
	{/each}
</div>
