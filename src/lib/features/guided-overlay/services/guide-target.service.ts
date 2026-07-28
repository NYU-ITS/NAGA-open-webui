import { browser } from '$app/environment';

import { DEFAULT_TARGET_TIMEOUT_MS } from '../config/guide.constants';
import { getTargetSelectors } from '../config/target-registry';

export const resolveTarget = (targetId: string): HTMLElement | null => {
	if (!browser) {
		return null;
	}

	const selectors = getTargetSelectors(targetId);
	if (selectors.length === 0) {
		return null;
	}

	let fallbackTarget: HTMLElement | null = null;

	for (const selector of selectors) {
		const candidates = Array.from(document.querySelectorAll(selector)) as HTMLElement[];
		const renderedTargets = candidates.filter(isRenderedTarget);
		const visibleTargets = candidates.filter(isVisibleTarget);

		if (!fallbackTarget && (renderedTargets[0] ?? candidates[0])) {
			fallbackTarget = renderedTargets[0] ?? candidates[0];
		}

		if (targetId === 'sidebar-toggle') {
			const expandedSidebarToggle = visibleTargets.find((element) =>
				element.closest('#sidebar[data-state="true"]')
			);

			if (expandedSidebarToggle) {
				return expandedSidebarToggle;
			}
		}

		if (visibleTargets[0]) {
			return visibleTargets[0];
		}

		if (renderedTargets[0]) {
			return renderedTargets[0];
		}
	}

	return fallbackTarget;
};

const isRenderedTarget = (element: HTMLElement): boolean => {
	const rect = element.getBoundingClientRect();
	const style = window.getComputedStyle(element);

	return (
		rect.width > 0 &&
		rect.height > 0 &&
		style.visibility !== 'hidden' &&
		style.display !== 'none'
	);
};

const isVisibleTarget = (element: HTMLElement): boolean => {
	const rect = element.getBoundingClientRect();

	return (
		isRenderedTarget(element) &&
		rect.bottom > 0 &&
		rect.right > 0 &&
		rect.top < window.innerHeight &&
		rect.left < window.innerWidth
	);
};

export const waitForTarget = async (
	targetId: string,
	timeoutMs = DEFAULT_TARGET_TIMEOUT_MS
): Promise<HTMLElement | null> => {
	const existingTarget = resolveTarget(targetId);

	if (existingTarget) {
		return existingTarget;
	}

	if (!browser) {
		return null;
	}

	return new Promise((resolve) => {
		let done = false;
		let observer: MutationObserver | null = null;
		let timeoutId: number | null = null;

		const finish = (target: HTMLElement | null) => {
			if (done) {
				return;
			}

			done = true;
			observer?.disconnect();

			if (timeoutId !== null) {
				window.clearTimeout(timeoutId);
			}

			resolve(target);
		};

		observer = new MutationObserver(() => {
			const target = resolveTarget(targetId);
			if (target) {
				finish(target);
			}
		});

		timeoutId = window.setTimeout(() => {
			finish(resolveTarget(targetId));
		}, timeoutMs);

		observer.observe(document.body, {
			childList: true,
			subtree: true,
			attributes: true,
			attributeFilter: ['id', 'class', 'data-guide', 'aria-label', 'href']
		});
	});
};

export const scrollTargetIntoView = (element: HTMLElement): void => {
	element.scrollIntoView({
		block: 'center',
		inline: 'center',
		behavior: 'auto'
	});
};

export const getTargetRect = (element: HTMLElement): DOMRect => {
	return element.getBoundingClientRect();
};
