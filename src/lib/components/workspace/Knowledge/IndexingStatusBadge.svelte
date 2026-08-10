<script lang="ts">
	import { getContext } from 'svelte';

	import type { KnowledgeIndexingDisplayState } from '$lib/apis/knowledge';
	import Badge from '$lib/components/common/Badge.svelte';

	const i18n = getContext('i18n');

	export let state: KnowledgeIndexingDisplayState;

	const badgeTypes: Record<KnowledgeIndexingDisplayState, string> = {
		ready: 'success',
		queued: 'warning',
		indexing: 'info',
		partial: 'warning',
		failed: 'error',
		unavailable: 'muted'
	};

	const labels: Record<KnowledgeIndexingDisplayState, string> = {
		ready: 'Ready',
		queued: 'Queued',
		indexing: 'Indexing',
		partial: 'Partially failed',
		failed: 'Failed',
		unavailable: 'Unavailable'
	};
</script>

<div>
	<Badge type={badgeTypes[state]} content={$i18n.t(labels[state])} />
</div>
