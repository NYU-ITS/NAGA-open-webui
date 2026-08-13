<script lang="ts">
	import { getContext } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	const i18n = getContext('i18n');

	export let show = false;
	export let citation;
	export let showPercentage = false;
	export let showRelevance = true;

	type CitationMetadata = {
		file_id?: unknown;
		name?: unknown;
		source?: unknown;
		modality?: unknown;
		content_kind?: unknown;
		page?: unknown;
		page_number?: unknown;
		element_number?: unknown;
		html?: unknown;
	};

	type MergedDocument = {
		source: any;
		document: any;
		metadata?: CitationMetadata;
		distance?: number;
	};

	let mergedDocuments: MergedDocument[] = [];

	const visualContentKinds = new Set(['standalone_image', 'pdf_figure', 'pdf_table']);

	const displayText = (value: unknown) =>
		typeof value === 'string' || typeof value === 'number' ? String(value).trim() : '';

	const positiveInteger = (value: unknown) => {
		const number = typeof value === 'number' ? value : Number(value);
		return Number.isInteger(number) && number > 0 ? number : null;
	};

	const isVisualMetadata = (metadata?: CitationMetadata) =>
		metadata?.modality === 'image' ||
		visualContentKinds.has(displayText(metadata?.content_kind));

	const getPageNumber = (metadata?: CitationMetadata) => {
		const pageNumber = positiveInteger(metadata?.page_number);
		if (pageNumber) {
			return pageNumber;
		}

		const legacyPage = typeof metadata?.page === 'number' ? metadata.page : Number(metadata?.page);
		return Number.isInteger(legacyPage) && legacyPage >= 0 ? legacyPage + 1 : null;
	};

	const getVisualKindLabel = (metadata?: CitationMetadata) => {
		const elementNumber = positiveInteger(metadata?.element_number);
		switch (metadata?.content_kind) {
			case 'pdf_figure':
				return elementNumber ? `Figure ${elementNumber}` : 'Figure';
			case 'pdf_table':
				return elementNumber ? `Table ${elementNumber}` : 'Table';
			case 'standalone_image':
				return 'Standalone image';
			default:
				return 'Image';
		}
	};

	const getSourceLabel = (document: MergedDocument) => {
		const metadata = document.metadata;
		const sourceName =
			displayText(metadata?.name) ||
			displayText(metadata?.source) ||
			displayText(document.source?.name) ||
			displayText(document.source?.filename) ||
			displayText(document.source?.id) ||
			displayText(document.source?.url);

		if (!isVisualMetadata(metadata)) {
			return sourceName;
		}

		const pageNumber = getPageNumber(metadata);
		return [sourceName || 'Image', pageNumber ? `page ${pageNumber}` : '', getVisualKindLabel(metadata)]
			.filter(Boolean)
			.join(' · ');
	};

	const getSourceUrl = (document: MergedDocument) => {
		const fileId = displayText(document.metadata?.file_id);
		if (fileId) {
			const pageNumber = getPageNumber(document.metadata);
			return `${WEBUI_API_BASE_URL}/files/${encodeURIComponent(fileId)}/content${pageNumber ? `#page=${pageNumber}` : ''}`;
		}

		const sourceUrl = displayText(document.source?.url);
		return sourceUrl.startsWith('http://') || sourceUrl.startsWith('https://')
			? sourceUrl
			: '#';
	};

	function calculatePercentage(distance: number) {
		if (distance < 0) return 0;
		if (distance > 1) return 100;
		return Math.round(distance * 10000) / 100;
	}

	function getRelevanceColor(percentage: number) {
		if (percentage >= 80)
			return 'bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200';
		if (percentage >= 60)
			return 'bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200';
		if (percentage >= 40)
			return 'bg-orange-200 dark:bg-orange-800 text-orange-800 dark:text-orange-200';
		return 'bg-red-200 dark:bg-red-800 text-red-800 dark:text-red-200';
	}

	$: if (citation) {
		const documents = Array.isArray(citation.document) ? citation.document : [];
		const metadatas = Array.isArray(citation.metadata) ? citation.metadata : [];
		const distances = Array.isArray(citation.distances) ? citation.distances : [];
		const itemCount = Math.max(documents.length, metadatas.length);

		mergedDocuments = Array.from({ length: itemCount }, (_, i) => {
			const rawDistance = distances[i];
			const distance =
				rawDistance === null || rawDistance === undefined || rawDistance === ''
					? Number.NaN
					: typeof rawDistance === 'number'
						? rawDistance
						: Number(rawDistance);
			return {
				source: citation.source,
				document: documents[i] ?? '',
				metadata: metadatas[i],
				distance: Number.isFinite(distance) ? distance : undefined
			};
		});
		if (
			mergedDocuments.length > 0 &&
			mergedDocuments.every((document) => document.distance !== undefined)
		) {
			mergedDocuments = mergedDocuments.sort(
				(a, b) => (b.distance ?? Infinity) - (a.distance ?? Infinity)
			);
		}
	}
</script>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center capitalize">
				{$i18n.t('Citation')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-6 pb-5 md:space-x-4">
			<div
				class="flex flex-col w-full dark:text-gray-200 overflow-y-scroll max-h-[22rem] scrollbar-hidden"
			>
				{#each mergedDocuments as document, documentIdx}
					<div class="flex flex-col w-full">
						<div class="text-sm font-medium dark:text-gray-300">
							{$i18n.t('Source')}
						</div>

						{#if getSourceLabel(document)}
							<Tooltip
								className="w-fit"
								content={$i18n.t('Open file')}
								placement="top-start"
								tippyOptions={{ duration: [500, 0] }}
							>
								<div class="text-sm dark:text-gray-400 flex items-center gap-2 w-fit">
									<a
										class="hover:text-gray-500 dark:hover:text-gray-100 underline grow"
										href={getSourceUrl(document)}
										target="_blank"
										rel="noopener noreferrer"
									>
										{getSourceLabel(document)}
									</a>
									{#if getPageNumber(document.metadata) && !isVisualMetadata(document.metadata)}
										<span class="text-xs text-gray-600 dark:text-gray-400">
											({$i18n.t('page')}
											{getPageNumber(document.metadata)})
										</span>
									{/if}
								</div>
							</Tooltip>
							{#if showRelevance}
								<div class="text-sm font-medium dark:text-gray-300 mt-2">
									{$i18n.t('Relevance')}
								</div>
								{#if document.distance !== undefined}
									<Tooltip
										className="w-fit"
										content={$i18n.t('Semantic distance to query')}
										placement="top-start"
										tippyOptions={{ duration: [500, 0] }}
									>
										<div class="text-sm my-1 dark:text-gray-400 flex items-center gap-2 w-fit">
											{#if showPercentage}
												{@const percentage = calculatePercentage(document.distance)}
												<span
													class={`px-1 rounded-sm font-medium ${getRelevanceColor(percentage)}`}
												>
													{percentage.toFixed(2)}%
												</span>
												<span class="text-gray-500 dark:text-gray-500">
													({document.distance.toFixed(4)})
												</span>
											{:else}
												<span class="text-gray-500 dark:text-gray-500">
													{document.distance.toFixed(4)}
												</span>
											{/if}
										</div>
									</Tooltip>
								{:else}
									<div class="text-sm dark:text-gray-400">
										{$i18n.t('No distance available')}
									</div>
								{/if}
							{/if}
						{:else}
							<div class="text-sm dark:text-gray-400">
								{$i18n.t('No source available')}
							</div>
						{/if}
					</div>
					<div class="flex flex-col w-full">
						<div class=" text-sm font-medium dark:text-gray-300 mt-2">
							{$i18n.t('Content')}
						</div>
						{#if isVisualMetadata(document.metadata)}
							<div class="text-sm dark:text-gray-400 whitespace-pre-line">
								{getSourceLabel(document)}
							</div>
						{:else if document.metadata?.html}
							<iframe
								class="w-full border-0 h-auto rounded-none"
								sandbox="allow-scripts allow-forms allow-same-origin"
								srcdoc={document.document}
								title={$i18n.t('Content')}
							></iframe>
						{:else}
							<pre class="text-sm dark:text-gray-400 whitespace-pre-line">
                {document.document}
              </pre>
						{/if}
					</div>

					{#if documentIdx !== mergedDocuments.length - 1}
						<hr class="border-gray-100 dark:border-gray-850 my-3" />
					{/if}
				{/each}
			</div>
		</div>
	</div>
</Modal>
