<script lang="ts">
	export let content = '';
	export let placeholder = '';
	export let value = '';
	export let state = false;
	export let show = false;
	export let className = '';
</script>

<span class={className} data-testid="svelte-stub">
	{#if placeholder}
		<textarea {placeholder} bind:value />
	{/if}
	<slot />
	{#if content}{@html content}{/if}
</span>
