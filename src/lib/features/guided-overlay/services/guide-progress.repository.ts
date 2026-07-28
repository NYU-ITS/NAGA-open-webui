import { browser } from '$app/environment';
import { getUserSettings, updateUserSettings } from '$lib/apis/users';

import { GUIDED_OVERLAY_SETTINGS_KEY } from '../config/guide.constants';
import type { GuideProgress, GuideProgressRepository } from '../types/guide.types';

type GuidedOverlaySettings = Record<string, GuideProgress>;

const LOCAL_STORAGE_KEY = 'guided_overlay_progress';

const getToken = (): string | null => {
	if (!browser) {
		return null;
	}

	return localStorage.getItem('token');
};

const readLocalProgress = (): GuidedOverlaySettings => {
	if (!browser) {
		return {};
	}

	try {
		return JSON.parse(localStorage.getItem(LOCAL_STORAGE_KEY) ?? '{}');
	} catch {
		return {};
	}
};

const writeLocalProgress = (progressByGuide: GuidedOverlaySettings) => {
	if (browser) {
		localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(progressByGuide));
	}
};

const syncLocalProgress = (guideId: string, progress: GuideProgress | null) => {
	const localProgress = readLocalProgress();

	if (progress) {
		writeLocalProgress({
			...localProgress,
			[guideId]: progress
		});
		return;
	}

	if (localProgress[guideId]) {
		delete localProgress[guideId];
		writeLocalProgress(localProgress);
	}
};

export const guideProgressRepository: GuideProgressRepository = {
	async load(_userId: string, guideId: string): Promise<GuideProgress | null> {
		const token = getToken();

		if (!token) {
			return readLocalProgress()[guideId] ?? null;
		}

		try {
			const settings = await getUserSettings(token);
			const serverProgress = settings?.[GUIDED_OVERLAY_SETTINGS_KEY]?.[guideId] ?? null;
			syncLocalProgress(guideId, serverProgress);

			return serverProgress;
		} catch (error) {
			console.warn('[guided-overlay] Falling back to local progress load', error);
			return readLocalProgress()[guideId] ?? null;
		}
	},

	async save(progress: GuideProgress): Promise<void> {
		const token = getToken();
		const localProgress = {
			...readLocalProgress(),
			[progress.guideId]: progress
		};

		writeLocalProgress(localProgress);

		if (!token) {
			return;
		}

		try {
			const settings = (await getUserSettings(token)) ?? {};
			const nextSettings = {
				...settings,
				[GUIDED_OVERLAY_SETTINGS_KEY]: {
					...(settings[GUIDED_OVERLAY_SETTINGS_KEY] ?? {}),
					[progress.guideId]: progress
				}
			};

			await updateUserSettings(token, nextSettings);
		} catch (error) {
			console.warn('[guided-overlay] Progress saved locally but not synced to user settings', error);
		}
	}
};
