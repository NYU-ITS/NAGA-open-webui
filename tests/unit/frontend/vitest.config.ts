import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';
import path from 'path';

const repoRoot = path.resolve(__dirname, '../../..');

export default defineConfig({
	plugins: [sveltekit()],
	root: repoRoot,
	resolve: {
		alias: {
			'$lib': path.resolve(repoRoot, 'src/lib')
		}
	},
	define: {
		APP_VERSION: JSON.stringify('0.5.18'),
		APP_BUILD_HASH: JSON.stringify('test-build')
	},
	test: {
		include: [
			'tests/unit/frontend/**/*.{test,spec}.{js,ts}',
			'tests/integration/frontend/**/*.{test,spec}.{js,ts}'
		],
		environment: 'jsdom',
		globals: true,
		setupFiles: [repoRoot + '/src/lib/test/setup.ts'],
		server: {
			deps: {
				inline: [/@testing-library/]
			}
		}
	}
});
