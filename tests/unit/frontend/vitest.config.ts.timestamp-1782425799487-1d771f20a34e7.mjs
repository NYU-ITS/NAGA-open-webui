// tests/unit/frontend/vitest.config.ts
import { defineConfig } from "file:///app/node_modules/vitest/dist/config.js";
import { sveltekit } from "file:///app/node_modules/@sveltejs/kit/src/exports/vite/index.js";
import path from "path";
var __vite_injected_original_dirname = "/app/tests/unit/frontend";
var repoRoot = path.resolve(__vite_injected_original_dirname, "../../..");
var vitest_config_default = defineConfig({
  plugins: [sveltekit()],
  root: repoRoot,
  resolve: {
    alias: {
      "$lib": path.resolve(repoRoot, "src/lib")
    }
  },
  define: {
    APP_VERSION: JSON.stringify("0.5.18"),
    APP_BUILD_HASH: JSON.stringify("test-build")
  },
  test: {
    include: [
      "tests/unit/frontend/**/*.{test,spec}.{js,ts}",
      "tests/integration/frontend/**/*.{test,spec}.{js,ts}"
    ],
    environment: "jsdom",
    globals: true,
    setupFiles: [repoRoot + "/src/lib/test/setup.ts"]
  }
});
export {
  vitest_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidGVzdHMvdW5pdC9mcm9udGVuZC92aXRlc3QuY29uZmlnLnRzIl0sCiAgInNvdXJjZXNDb250ZW50IjogWyJjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZGlybmFtZSA9IFwiL2FwcC90ZXN0cy91bml0L2Zyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCIvYXBwL3Rlc3RzL3VuaXQvZnJvbnRlbmQvdml0ZXN0LmNvbmZpZy50c1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vYXBwL3Rlc3RzL3VuaXQvZnJvbnRlbmQvdml0ZXN0LmNvbmZpZy50c1wiO2ltcG9ydCB7IGRlZmluZUNvbmZpZyB9IGZyb20gJ3ZpdGVzdC9jb25maWcnO1xuaW1wb3J0IHsgc3ZlbHRla2l0IH0gZnJvbSAnQHN2ZWx0ZWpzL2tpdC92aXRlJztcbmltcG9ydCBwYXRoIGZyb20gJ3BhdGgnO1xuXG5jb25zdCByZXBvUm9vdCA9IHBhdGgucmVzb2x2ZShfX2Rpcm5hbWUsICcuLi8uLi8uLicpO1xuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuXHRwbHVnaW5zOiBbc3ZlbHRla2l0KCldLFxuXHRyb290OiByZXBvUm9vdCxcblx0cmVzb2x2ZToge1xuXHRcdGFsaWFzOiB7XG5cdFx0XHQnJGxpYic6IHBhdGgucmVzb2x2ZShyZXBvUm9vdCwgJ3NyYy9saWInKVxuXHRcdH1cblx0fSxcblx0ZGVmaW5lOiB7XG5cdFx0QVBQX1ZFUlNJT046IEpTT04uc3RyaW5naWZ5KCcwLjUuMTgnKSxcblx0XHRBUFBfQlVJTERfSEFTSDogSlNPTi5zdHJpbmdpZnkoJ3Rlc3QtYnVpbGQnKVxuXHR9LFxuXHR0ZXN0OiB7XG5cdFx0aW5jbHVkZTogW1xuXHRcdFx0J3Rlc3RzL3VuaXQvZnJvbnRlbmQvKiovKi57dGVzdCxzcGVjfS57anMsdHN9Jyxcblx0XHRcdCd0ZXN0cy9pbnRlZ3JhdGlvbi9mcm9udGVuZC8qKi8qLnt0ZXN0LHNwZWN9Lntqcyx0c30nXG5cdFx0XSxcblx0XHRlbnZpcm9ubWVudDogJ2pzZG9tJyxcblx0XHRnbG9iYWxzOiB0cnVlLFxuXHRcdHNldHVwRmlsZXM6IFtyZXBvUm9vdCArICcvc3JjL2xpYi90ZXN0L3NldHVwLnRzJ11cblx0fVxufSk7XG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQThQLFNBQVMsb0JBQW9CO0FBQzNSLFNBQVMsaUJBQWlCO0FBQzFCLE9BQU8sVUFBVTtBQUZqQixJQUFNLG1DQUFtQztBQUl6QyxJQUFNLFdBQVcsS0FBSyxRQUFRLGtDQUFXLFVBQVU7QUFFbkQsSUFBTyx3QkFBUSxhQUFhO0FBQUEsRUFDM0IsU0FBUyxDQUFDLFVBQVUsQ0FBQztBQUFBLEVBQ3JCLE1BQU07QUFBQSxFQUNOLFNBQVM7QUFBQSxJQUNSLE9BQU87QUFBQSxNQUNOLFFBQVEsS0FBSyxRQUFRLFVBQVUsU0FBUztBQUFBLElBQ3pDO0FBQUEsRUFDRDtBQUFBLEVBQ0EsUUFBUTtBQUFBLElBQ1AsYUFBYSxLQUFLLFVBQVUsUUFBUTtBQUFBLElBQ3BDLGdCQUFnQixLQUFLLFVBQVUsWUFBWTtBQUFBLEVBQzVDO0FBQUEsRUFDQSxNQUFNO0FBQUEsSUFDTCxTQUFTO0FBQUEsTUFDUjtBQUFBLE1BQ0E7QUFBQSxJQUNEO0FBQUEsSUFDQSxhQUFhO0FBQUEsSUFDYixTQUFTO0FBQUEsSUFDVCxZQUFZLENBQUMsV0FBVyx3QkFBd0I7QUFBQSxFQUNqRDtBQUNELENBQUM7IiwKICAibmFtZXMiOiBbXQp9Cg==
