/**
 * Shared column-resize factory for Svelte tables.
 *
 * Mirrors the pattern used in topicanalysis/+page.svelte so it can be
 * dropped into any table component with minimal boilerplate.
 *
 * Usage in a Svelte `<script>` block:
 *
 *   import { createColResize } from '$lib/utils/colResize';
 *   let tableEl: HTMLTableElement;
 *   const resize = createColResize([20, 20, 20, 20]);
 *
 * In the template add a resize handle to each `<th>`:
 *
 *   <th class="relative ..." style="width: {$resize.colWidths[0]}%">
 *     Column Name
 *     <span
 *       class="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-[#57068C] dark:hover:bg-[#B588FF] z-10"
 *       on:mousedown|preventDefault={(e) => resize.initColResize(e, tableEl, 0)}
 *     />
 *   </th>
 */

import { writable } from 'svelte/store';

export function createColResize(initialWidths: number[] = []) {
	const colWidths = writable<number[]>([...initialWidths]);
	let resizingCol: number | null = null;
	let resizeStartX = 0;
	let resizeStartWidth = 0;
	let resizeNextStartWidth = 0;
	let boundTable: HTMLTableElement | null = null;

	function initColResize(e: MouseEvent, tableEl: HTMLTableElement, index: number) {
		boundTable = tableEl;
		resizingCol = index;
		resizeStartX = e.pageX;
		colWidths.update((w) => {
			resizeStartWidth = w[index];
			if (index < w.length - 1) {
				resizeNextStartWidth = w[index + 1];
			}
			return w;
		});
		document.body.style.cursor = 'col-resize';
		document.body.style.userSelect = 'none';
		window.addEventListener('mousemove', handleColResize);
		window.addEventListener('mouseup', stopColResize);
	}

	function handleColResize(e: MouseEvent) {
		if (resizingCol === null || !boundTable) return;
		const tableWidth = boundTable.offsetWidth;
		const deltaPx = e.pageX - resizeStartX;
		const deltaPct = (deltaPx / tableWidth) * 100;
		const newWidth = Math.max(4, resizeStartWidth + deltaPct);

		colWidths.update((w) => {
			const next = [...w];
			if (resizingCol !== null && resizingCol < next.length - 1) {
				const nextNewWidth = Math.max(4, resizeNextStartWidth - deltaPct);
				next[resizingCol + 1] = nextNewWidth;
			}
			if (resizingCol !== null) {
				next[resizingCol] = newWidth;
			}
			return next;
		});
	}

	function stopColResize() {
		resizingCol = null;
		document.body.style.cursor = '';
		document.body.style.userSelect = '';
		window.removeEventListener('mousemove', handleColResize);
		window.removeEventListener('mouseup', stopColResize);
	}

	return {
		colWidths,
		initColResize
	};
}
