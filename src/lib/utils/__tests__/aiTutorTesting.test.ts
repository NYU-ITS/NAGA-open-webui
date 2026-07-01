import { describe, expect, it, vi } from 'vitest';

describe('showAITutorTestToast', () => {
	it('logs test toast when TESTING_AI_TUTOR is enabled', async () => {
		vi.doMock('$lib/constants', () => ({
			TESTING_AI_TUTOR: true
		}));
		const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

		const { showAITutorTestToast } = await import('../aiTutorTesting');
		showAITutorTestToast('pipeline loaded');

		expect(logSpy).toHaveBeenCalledWith('[TEST] pipeline loaded');
		vi.resetModules();
	});

	it('does nothing when TESTING_AI_TUTOR is disabled', async () => {
		vi.doMock('$lib/constants', () => ({
			TESTING_AI_TUTOR: false
		}));
		const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

		const { showAITutorTestToast } = await import('../aiTutorTesting');
		showAITutorTestToast('pipeline loaded');

		expect(logSpy).not.toHaveBeenCalled();
		vi.resetModules();
	});
});
