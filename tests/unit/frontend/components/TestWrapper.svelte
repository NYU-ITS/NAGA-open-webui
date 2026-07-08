<script>
	import { setContext } from 'svelte';
	import { writable } from 'svelte/store';
	import ModelEditor from '$lib/components/workspace/Models/ModelEditor.svelte';

	const i18n = writable({
		t: (key, values = {}) => key.replace(/{{(\w+)}}/g, (_, name) => values[name] ?? '')
	});
	setContext('i18n', i18n);

	export let onSubmit = () => {};
	export let onBack = null;
	export let edit = false;
	export let clone = false;
	export let preset = true;
	export let model = null;
	export let accessControl = undefined;
</script>

<ModelEditor {onSubmit} {onBack} {edit} {clone} {preset} {model} {accessControl} />
