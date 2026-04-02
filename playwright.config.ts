import { defineConfig } from '@playwright/test';

export default defineConfig({
	testMatch: '**/*.spec.ts',
	webServer: { command: 'bun run build && bun run preview', port: 4173 }
});
