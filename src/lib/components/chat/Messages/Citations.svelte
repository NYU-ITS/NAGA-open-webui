<script lang="ts">
	import { getContext } from 'svelte';
	import CitationsModal from './CitationsModal.svelte';
	import Collapsible from '$lib/components/common/Collapsible.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';

	const i18n = getContext('i18n');

	export let id = '';
	export let sources: any[] = [];

	let citations: any[] = [];
	let showPercentage = false;
	let showRelevance = true;

	let showCitationModal = false;
	let selectedCitation: any = null;
	let isCollapsibleOpen = false;

	type CitationMetadata = {
		file_id?: unknown;
		name?: unknown;
		source?: unknown;
		modality?: unknown;
		content_kind?: unknown;
		visual_asset_id?: unknown;
		page_number?: unknown;
		element_number?: unknown;
	};

	const visualContentKinds = new Set(['standalone_image', 'pdf_figure', 'pdf_table']);

	const displayText = (value: unknown) =>
		typeof value === 'string' || typeof value === 'number' ? String(value).trim() : '';

	const positiveInteger = (value: unknown) => {
		const number = typeof value === 'number' ? value : Number(value);
		return Number.isInteger(number) && number > 0 ? number : null;
	};
	const finiteNumber = (value: unknown) => {
		if (value === null || value === undefined || value === '') return undefined;
		const number = typeof value === 'number' ? value : Number(value);
		return Number.isFinite(number) ? number : undefined;
	};

	const isVisualMetadata = (metadata?: CitationMetadata) =>
		metadata?.modality === 'image' ||
		visualContentKinds.has(displayText(metadata?.content_kind));

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

	const normalizeSourceDescriptor = (source: unknown): Record<string, any> => {
		if (typeof source === 'string') {
			return {
				name: source,
				...(source.startsWith('http://') || source.startsWith('https://')
					? { url: source }
					: {})
			};
		}
		return source && typeof source === 'object' && !Array.isArray(source)
			? { ...(source as Record<string, any>) }
			: {};
	};

	const getVisualCitationLabel = (source: any, metadata?: CitationMetadata) => {
		const parentName =
			displayText(metadata?.name) ||
			displayText(metadata?.source) ||
			displayText(source?.name) ||
			displayText(source?.filename) ||
			'Image';
		const pageNumber = positiveInteger(metadata?.page_number);
		return [parentName, pageNumber ? `page ${pageNumber}` : '', getVisualKindLabel(metadata)]
			.filter(Boolean)
			.join(' · ');
	};

	function calculateShowRelevance(sources: any[]) {
		const distances = sources.flatMap((citation) => citation.distances ?? []);
		const inRange = distances.filter((d) => d !== undefined && d >= -1 && d <= 1).length;
		const outOfRange = distances.filter((d) => d !== undefined && (d < -1 || d > 1)).length;

		if (distances.length === 0) {
			return false;
		}

		if (
			(inRange === distances.length - 1 && outOfRange === 1) ||
			(outOfRange === distances.length - 1 && inRange === 1)
		) {
			return false;
		}

		return true;
	}

	function shouldShowPercentage(sources: any[]) {
		const distances = sources.flatMap((citation) => citation.distances ?? []);
		return distances.every((d) => d !== undefined && d >= -1 && d <= 1);
	}

	$: {
		citations = (Array.isArray(sources) ? sources : []).reduce<any[]>(
			(acc, source, sourceIndex) => {
				if (!source || typeof source !== 'object' || Object.keys(source).length === 0) {
					return acc;
				}

				const documents = Array.isArray(source.document)
					? source.document
					: source.document !== undefined
						? [source.document]
						: [];
				const metadatas = Array.isArray(source.metadata)
					? source.metadata
					: source.metadata
						? [source.metadata]
						: [];
				const distances = Array.isArray(source.distances) ? source.distances : [];
				const itemCount = Math.max(documents.length, metadatas.length);
				const sourceDescriptor = normalizeSourceDescriptor(source.source);

				for (let index = 0; index < itemCount; index += 1) {
					const document = documents[index] ?? '';
					const metadata = metadatas[index] as CitationMetadata | undefined;
					const distance = finiteNumber(distances[index]);
					const visual = isVisualMetadata(metadata);

					// Within the same citation there could be multiple documents
					const regularSourceId =
						displayText(metadata?.source) ||
						displayText(sourceDescriptor?.id) ||
						displayText(sourceDescriptor?.url) ||
						displayText(sourceDescriptor?.name) ||
						`source:${sourceIndex}`;
					const id = visual
						? displayText(metadata?.visual_asset_id) ||
							`${displayText(metadata?.file_id) || regularSourceId}:visual:${sourceIndex}:${index}`
						: regularSourceId;
					let _source: Record<string, any> = { ...sourceDescriptor };

					if (visual) {
						_source.name = getVisualCitationLabel(sourceDescriptor, metadata);
					} else if (displayText(metadata?.name)) {
						_source.name = displayText(metadata?.name);
					}

					if (id.startsWith('http://') || id.startsWith('https://')) {
						_source = { ..._source, name: id, url: id };
					}
					if (!displayText(_source.name)) {
						_source.name =
							displayText(metadata?.source) || displayText(sourceDescriptor?.id) || 'Source';
					}

					const existingSource = acc.find((item) => item.id === id);

					if (existingSource) {
						existingSource.document.push(document);
						existingSource.metadata.push(metadata);
						if (distance !== undefined) {
							if (!existingSource.distances) {
								existingSource.distances = Array(
									existingSource.document.length - 1
								).fill(undefined);
							}
							existingSource.distances.push(distance);
						} else if (existingSource.distances) {
							existingSource.distances.push(undefined);
						}
					} else {
						acc.push({
							id: id,
							source: _source,
							document: [document],
							metadata: [metadata],
							distances: distance !== undefined ? [distance] : undefined
						});
					}
				}
				return acc;
			},
			[]
		);

		showRelevance = calculateShowRelevance(citations);
		showPercentage = shouldShowPercentage(citations);
	}
</script>

<CitationsModal
	bind:show={showCitationModal}
	citation={selectedCitation}
	{showPercentage}
	{showRelevance}
/>

{#if citations.length > 0}
	<div class=" py-0.5 -mx-0.5 w-full flex gap-1 items-center flex-wrap">
		{#if citations.length <= 3}
			<div class="flex text-xs font-medium flex-wrap">
				{#each citations as citation, idx}
					<button
						id={`source-${id}-${idx}`}
						class="no-toggle outline-hidden flex dark:text-gray-300 p-1 bg-white dark:bg-gray-900 rounded-xl max-w-96"
						on:click={() => {
							showCitationModal = true;
							selectedCitation = citation;
						}}
					>
						{#if citations.every((c) => c.distances !== undefined)}
							<div class="bg-gray-50 dark:bg-gray-800 rounded-full size-4">
								{idx + 1}
							</div>
						{/if}
						<div
							class="flex-1 mx-1 truncate text-black/60 hover:text-black dark:text-white/60 dark:hover:text-white transition"
						>
							{citation.source.name}
						</div>
					</button>
				{/each}
			</div>
		{:else}
			<Collapsible
				id="collapsible-sources"
				bind:open={isCollapsibleOpen}
				className="w-full max-w-full "
				buttonClassName="w-fit max-w-full"
			>
				<div
					class="flex w-full overflow-auto items-center gap-2 text-gray-500 hover:text-gray-600 dark:hover:text-gray-400 transition cursor-pointer"
				>
					<div
						class="flex-1 flex items-center gap-1 overflow-auto scrollbar-none w-full max-w-full"
					>
						<span class="whitespace-nowrap hidden sm:inline shrink-0"
							>{$i18n.t('References from')}</span
						>
						<div class="flex items-center overflow-auto scrollbar-none w-full max-w-full flex-1">
							<div class="flex text-xs font-medium items-center">
								{#each citations.slice(0, 2) as citation, idx}
									<button
										class="no-toggle outline-hidden flex dark:text-gray-300 p-1 bg-gray-50 hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 transition rounded-xl max-w-96"
										on:click={() => {
											showCitationModal = true;
											selectedCitation = citation;
										}}
										on:pointerup={(e) => {
											e.stopPropagation();
										}}
									>
										{#if citations.every((c) => c.distances !== undefined)}
											<div class="bg-gray-50 dark:bg-gray-800 rounded-full size-4">
												{idx + 1}
											</div>
										{/if}
										<div class="flex-1 mx-1 truncate">
											{citation.source.name}
										</div>
									</button>
								{/each}
							</div>
						</div>
						<div class="flex items-center gap-1 whitespace-nowrap shrink-0">
							<span class="hidden sm:inline">{$i18n.t('and')}</span>
							{citations.length - 2}
							<span>{$i18n.t('more')}</span>
						</div>
					</div>
					<div class="shrink-0">
						{#if isCollapsibleOpen}
							<ChevronUp strokeWidth="3.5" className="size-3.5" />
						{:else}
							<ChevronDown strokeWidth="3.5" className="size-3.5" />
						{/if}
					</div>
				</div>
				<div slot="content">
					<div class="flex text-xs font-medium flex-wrap">
						{#each citations as citation, idx}
							<button
								id={`source-${id}-${idx}`}
								class="no-toggle outline-hidden flex dark:text-gray-300 p-1 bg-gray-50 hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 transition rounded-xl max-w-96"
								on:click={() => {
									showCitationModal = true;
									selectedCitation = citation;
								}}
							>
								{#if citations.every((c) => c.distances !== undefined)}
									<div class="bg-gray-50 dark:bg-gray-800 rounded-full size-4">
										{idx + 1}
									</div>
								{/if}
								<div class="flex-1 mx-1 truncate">
									{citation.source.name}
								</div>
							</button>
						{/each}
					</div>
				</div>
			</Collapsible>
		{/if}
	</div>
{/if}
