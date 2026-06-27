<script>
  import { setContext } from 'svelte';
  import { writable } from 'svelte/store';
  import ModelEditor from '$lib/components/workspace/Models/ModelEditor.svelte';

  // Set up i18n context for child components
  const i18n = writable({ t: (key) => key });
  setContext('i18n', i18n);

  // Pass through all props
  export let onSubmit = () => {};
  export let edit = false;
  export let model = undefined;
  export let accessControl = undefined;
</script>

<ModelEditor {onSubmit} {edit} {model} {accessControl} />
