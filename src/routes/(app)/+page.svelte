<script lang="ts">
	import { page } from '$app/stores';
	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	import { showControls, showRightsideQuestions } from '$lib/stores';

	$: practicing = $page.url.searchParams.get('practicing');
	$: console.log('[HomePage] route panel state', {
		path: $page.url.pathname,
		search: $page.url.search,
		practicing,
		showControls: $showControls,
		showRightsideQuestions: $showRightsideQuestions
	});

	$: if (practicing) {
		if (!$showRightsideQuestions) {
			console.log('[HomePage] enabling RightsideQuestions from route state');
			showRightsideQuestions.set(true);
		}

		if (!$showControls) {
			console.log('[HomePage] forcing controls open from route state');
			showControls.set(true);
		}
	} else if ($showRightsideQuestions) {
		console.log('[HomePage] clearing RightsideQuestions from route state');
		showRightsideQuestions.set(false);
	}
</script>

<Help />

<Chat />
