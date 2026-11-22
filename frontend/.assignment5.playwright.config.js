import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  outputDir: './.assignment5-playwright-results',
  workers: 1,
  timeout: 30_000,
  use: { baseURL: 'http://localhost:5174' },
});
