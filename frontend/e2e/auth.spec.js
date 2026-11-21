import { test, expect } from '@playwright/test';

test('authenticated user sees tickets', async ({ page }) => {
  await page.goto('http://localhost:5173');
  await page.fill('#login-email', 'admin@local');
  await page.fill('#login-password', 'admin12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));
  await expect(page.locator('body')).toContainText(/Ticket/i);
});
