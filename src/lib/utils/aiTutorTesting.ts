import { toast } from 'svelte-sonner';
import { TESTING_AI_TUTOR } from '$lib/constants';

export const showAITutorTestToast = (message: string) => {
	if (!TESTING_AI_TUTOR) return;
	toast(`[TEST] ${message}`);
};

