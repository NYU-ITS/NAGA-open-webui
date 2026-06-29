<script>
	import { setContext } from 'svelte';
	import { writable } from 'svelte/store';
	import Models from '$lib/components/workspace/Models.svelte';

	const i18n = writable({
		t: (key, values = {}) => key.replace(/{{(\w+)}}/g, (_, name) => values[name] ?? '')
	});
	setContext('i18n', i18n);
</script>

<Models />
