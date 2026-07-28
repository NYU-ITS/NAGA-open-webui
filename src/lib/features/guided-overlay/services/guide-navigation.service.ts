import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import { page } from '$app/stores';
import { get } from 'svelte/store';

import { NAVIGATION_TIMEOUT_MS } from '../config/guide.constants';
import type { GuideStep } from '../types/guide.types';

const getTargetUrl = (targetRoute: string, currentUrl: URL): URL => {
	return new URL(targetRoute, currentUrl.origin);
};

const routeMatches = (currentUrl: URL, targetRoute: string): boolean => {
	const targetUrl = getTargetUrl(targetRoute, currentUrl);

	const pathnameMatches =
		targetUrl.pathname === '/'
			? currentUrl.pathname === '/'
			: currentUrl.pathname === targetUrl.pathname ||
				currentUrl.pathname.startsWith(`${targetUrl.pathname}/`);

	if (!pathnameMatches) {
		return false;
	}

	return targetUrl.search ? currentUrl.search === targetUrl.search : true;
};

export const getCurrentPathname = (): string => {
	return get(page).url.pathname;
};

const getCurrentUrl = (): URL => {
	return get(page).url;
};

export const waitForNavigationComplete = async (
	targetRoute: string,
	timeoutMs = NAVIGATION_TIMEOUT_MS
): Promise<void> => {
	if (!browser || routeMatches(getCurrentUrl(), targetRoute)) {
		return;
	}

	await new Promise<void>((resolve) => {
		let unsubscribe = () => {};

		const timeoutId = window.setTimeout(() => {
			unsubscribe();
			resolve();
		}, timeoutMs);

		unsubscribe = page.subscribe(($page) => {
			if (routeMatches($page.url, targetRoute)) {
				window.clearTimeout(timeoutId);
				unsubscribe();
				resolve();
			}
		});
	});
};

export const prepareRouteForStep = async (step: GuideStep): Promise<void> => {
	if (!browser || !step.route) {
		return;
	}

	if (!routeMatches(getCurrentUrl(), step.route)) {
		await goto(step.route);
		await waitForNavigationComplete(step.route);
	}
};
