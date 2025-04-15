<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { register, unregister } from './index';

  export let message: string;
  export let className = '';
  let element: HTMLElement;

  onMount(() => {
    register(element);
  });

  onDestroy(() => {
    unregister(element);
  });
</script>

<div bind:this={element} data-tour={message} class={className}>
  <slot></slot>
</div>