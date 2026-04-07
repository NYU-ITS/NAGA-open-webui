import { TESTING_AI_TUTOR } from '$lib/constants';

export const showAITutorTestToast = (message: string) => {
	if (!TESTING_AI_TUTOR) return;
	console.log(`[TEST] ${message}`);
};
