<script lang="ts">
	import { page } from '$app/stores';
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	import { showControls, showRightsideQuestions } from '$lib/stores';

	$: practicing = $page.url.searchParams.get('practicing');

	$: if (practicing) {
		if (!$showRightsideQuestions) {
			showRightsideQuestions.set(true);
		}

		if (!$showControls) {
			showControls.set(true);
		}
	}
</script>

<Help />
<Chat />
