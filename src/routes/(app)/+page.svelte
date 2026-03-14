<script lang="ts">
	import { onMount } from 'svelte';
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	import { showControls, showRightsideQuestions } from '$lib/stores';

	onMount(() => {
		const storedData = sessionStorage.getItem('generatedQuestions');
		console.log('[HomePage] onMount generatedQuestions', storedData);
		if (storedData) {
			console.log('[HomePage] enabling RightsideQuestions overlay');
			showControls.set(true);
			showRightsideQuestions.set(true);
		} else {
			console.log('[HomePage] no generatedQuestions payload found');
			showRightsideQuestions.set(false);
		}
	});
</script>

<Help />

<Chat />
