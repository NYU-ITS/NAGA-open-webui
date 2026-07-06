import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 4173);
const HOST = process.env.PLAYWRIGHT_HOST ?? '127.0.0.1';
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL?.trim() || `http://${HOST}:${PORT}`;
const WEB_SERVER_COMMAND =
	process.env.PLAYWRIGHT_WEB_SERVER_COMMAND?.trim() ||
	`npm run dev -- --host ${HOST} --port ${PORT}`;
const SKIP_WEB_SERVER = process.env.PLAYWRIGHT_SKIP_WEB_SERVER === '1';
const CI_RETRIES = Number(process.env.PLAYWRIGHT_RETRIES ?? 2);
const CI_WORKERS = Number(process.env.PLAYWRIGHT_WORKERS ?? 2);

// Groups e2e tests target a live Open WebUI instance (backend + frontend), not the dev server.
// Kept separate from PLAYWRIGHT_BASE_URL so pointing groups at a live app does not redirect
// the ai-tutor tests (which use the dev server / their own base URL).
const GROUPS_BASE_URL =
	process.env.PLAYWRIGHT_GROUPS_BASE_URL?.trim() ||
	process.env.PLAYWRIGHT_BASE_URL?.trim() ||
	'http://localhost:3000';

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
	retries: process.env.CI ? CI_RETRIES : 0,
	workers: process.env.CI ? CI_WORKERS : undefined,
	reporter: [['list'], ['html', { open: 'never' }]],
	use: {
		baseURL: BASE_URL,
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
		video: videoModeFromEnv()
	},
	webServer: SKIP_WEB_SERVER
		? undefined
		: {
				command: WEB_SERVER_COMMAND,
				url: BASE_URL,
				reuseExistingServer: !process.env.CI,
				timeout: 180 * 1000
			},
	projects: [
		{
			name: 'chromium',
			testIgnore: '**/groups/**',
			use: { ...devices['Desktop Chrome'] }
		},
		{
			name: 'firefox',
			testIgnore: '**/groups/**',
			use: { ...devices['Desktop Firefox'] }
		},
		{
			name: 'webkit',
			testIgnore: '**/groups/**',
			use: { ...devices['Desktop Safari'] }
		},
		{
			// Provisions one admin and one non-admin account before the groups tests run.
			name: 'groups-setup',
			testMatch: '**/groups/setup/*.setup.ts',
			use: { baseURL: GROUPS_BASE_URL, extraHTTPHeaders: { Accept: 'application/json' } }
		},
		{
			name: 'groups-api',
			testMatch: '**/groups/api/*.spec.ts',
			dependencies: ['groups-setup'],
			use: { baseURL: GROUPS_BASE_URL, extraHTTPHeaders: { Accept: 'application/json' } }
		},
		{
			name: 'groups-ui',
			testMatch: '**/groups/ui/*.spec.ts',
			dependencies: ['groups-setup'],
			use: {
				...devices['Desktop Chrome'],
				baseURL: GROUPS_BASE_URL,
				extraHTTPHeaders: { Accept: 'application/json' }
			}
		}
	]
});
