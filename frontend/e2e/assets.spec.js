import { test, expect } from '@playwright/test';

const EMAIL = 'admin@local';
const PASS = 'admin12345';

async function login(page) {
  await page.goto('/');
  await page.fill('#login-email', EMAIL);
  await page.fill('#login-password', PASS);
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('assets page loads', async ({ page }) => {
  await page.goto('/#/assets');
  await expect(page.locator('body')).toContainText(/Asset/i, { timeout: 10000 });
});

test('dashboard page loads', async ({ page }) => {
  await page.goto('/#/dashboard');
  await expect(page.locator('body')).toContainText(/Dashboard/i, { timeout: 10000 });
});
