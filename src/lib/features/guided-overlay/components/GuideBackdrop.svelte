<script lang="ts">
	import { TARGET_HIGHLIGHT_PADDING_PX } from '../config/guide.constants';

	export let rect: DOMRect | null = null;
	export let rects: DOMRect[] = [];

	$: sourceRects = rects.length > 0 ? rects : rect ? [rect] : [];
	$: highlights = sourceRects.map((sourceRect) => ({
		top: Math.max(sourceRect.top - TARGET_HIGHLIGHT_PADDING_PX, 0),
		left: Math.max(sourceRect.left - TARGET_HIGHLIGHT_PADDING_PX, 0),
		width: sourceRect.width + TARGET_HIGHLIGHT_PADDING_PX * 2,
		height: sourceRect.height + TARGET_HIGHLIGHT_PADDING_PX * 2
	}));
</script>

<div class="fixed inset-0 z-[9998] pointer-events-none">
	{#if highlights.length > 0}
		{#each highlights as highlight}
			<div
				class="absolute rounded-2xl border-2 border-[#6A00A8] bg-[#6A00A8]/[0.06] outline outline-2 outline-white/90 shadow-[0_0_0_5px_rgba(106,0,168,0.3),0_16px_42px_rgba(106,0,168,0.3)]"
				style="top: {highlight.top}px; left: {highlight.left}px; width: {highlight.width}px; height: {highlight.height}px;"
			/>
		{/each}
	{:else}
		<div class="absolute inset-0 bg-transparent" />
	{/if}
</div>
