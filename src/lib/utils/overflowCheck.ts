/**
 * Creates a Svelte action for detecting horizontal overflow in table cells.
 *
 * Usage in a component:
 *   import { makeOverflowCheck } from '$lib/utils/overflowCheck';
 *   let overflowStates: Record<string, boolean> = {};
 *   const overflowCheck = makeOverflowCheck(() => overflowStates, (s) => { overflowStates = s; });
 *
 * Then in template:
 *   <span use:overflowCheck="unique-key">...</span>
 *   {#if overflowStates['unique-key']}<Tooltip>...</Tooltip>{/if}
 */
export function makeOverflowCheck(
	getStates: () => Record<string, boolean>,
	setStates: (s: Record<string, boolean>) => void
) {
	return function overflowCheck(node: HTMLElement, key: string) {
		const check = () => {
			const states = getStates();
			states[key] = node.scrollWidth > node.clientWidth;
			setStates(states);
		};
		const ro = new ResizeObserver(check);
		ro.observe(node);
		check();
		return {
			destroy() {
				ro.disconnect();
			}
		};
	};
}
