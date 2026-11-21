import { test, expect } from '@playwright/test';

test('create ticket persists', async ({ page }) => {
  await page.goto('http://localhost:5173');
  await page.fill('#login-email', 'admin@local');
  await page.fill('#login-password', 'admin12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  await page.goto('http://localhost:5173/#/tickets/new');
  const title = 'E2E ticket ' + Date.now();
  await page.fill('input[placeholder="Brief summary of the issue"]', title);
  await page.fill('textarea', 'Automated E2E description');
  // select first category if available
  const cat = page.locator('select').nth(1);
  if (await cat.count()) {
    await cat.selectOption({ index: 1 });
  }
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  await expect(page.locator('body')).toContainText(title, { timeout: 10000 });
});
