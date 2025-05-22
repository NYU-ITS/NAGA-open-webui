<script>
	import GroupSelectionModal from '$lib/components/GroupSelectionModal/GroupSelectionModal.svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';

	onMount(() => {
		// Redirect to auth if not logged in
		if (!$user || !localStorage.token) {
			goto('/auth');
		}
	});
</script>

<svelte:head>
	<title>Select Group</title>
</svelte:head>

{#if $user}
	<GroupSelectionModal />
{/if}