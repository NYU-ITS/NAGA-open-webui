import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 4173);
const HOST = process.env.PLAYWRIGHT_HOST ?? '127.0.0.1';
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL?.trim() || `http://${HOST}:${PORT}`;

/**
 * Video in the HTML report:
 * - Default `retain-on-failure`: video only kept when a test fails (smaller disk use).
 * - Set PLAYWRIGHT_VIDEO=on to record every run and see video in the report on success too.
 * - Set PLAYWRIGHT_VIDEO=off to disable recording.
 */
function videoModeFromEnv(): 'on' | 'off' | 'retain-on-failure' {
	const raw = (process.env.PLAYWRIGHT_VIDEO ?? '').trim().toLowerCase();
	if (raw === 'on' || raw === 'always' || raw === '1' || raw === 'true') return 'on';
	if (raw === 'off' || raw === '0' || raw === 'false') return 'off';
	return 'retain-on-failure';
}

export default defineConfig({
	testDir: './playwright/tests',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 2 : undefined,
	reporter: [['list'], ['html', { open: 'never' }]],
	use: {
		baseURL: BASE_URL,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
		video: videoModeFromEnv()
	},
	webServer: {
		command: `npm run dev -- --host ${HOST} --port ${PORT}`,
		url: BASE_URL,
		reuseExistingServer: !process.env.CI,
		timeout: 180 * 1000
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] }
		},
		{
			name: 'firefox',
			use: { ...devices['Desktop Firefox'] }
		},
		{
			name: 'webkit',
			use: { ...devices['Desktop Safari'] }
		}
	]
});
