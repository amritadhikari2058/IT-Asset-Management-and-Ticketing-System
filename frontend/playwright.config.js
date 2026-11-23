import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  outputDir: '../../playwright-results',
  workers: 1,
  fullyParallel: false,
  use: { baseURL: 'http://localhost:5173' },
  webServer: [
    {
      command: 'cd ../backend && python manage.py migrate --noinput && python manage.py seed_defaults && python manage.py runserver 127.0.0.1:8000 --noreload',
      url: 'http://127.0.0.1:8000/health/',
      reuseExistingServer: false,
      timeout: 300_000,
      env: {
        DATABASE__NAME: 'test_e2e.sqlite3',
        DEBUG: 'false',
        ALLOWED_HOSTS: '127.0.0.1,localhost',
        SECRET_KEY: 'ci-test-secret-key-do-not-use-in-production',
        EMAIL_BACKEND: 'django.core.mail.backends.locmem.EmailBackend',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
