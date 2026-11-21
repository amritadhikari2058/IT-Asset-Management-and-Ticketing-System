import { test, expect } from '@playwright/test';

test('login page loads', async ({ page }) => {
  await page.goto('http://localhost:5173');
  await expect(page.locator('#login-email')).toBeVisible();
});

test('invalid login shows error', async ({ page }) => {
  await page.goto('http://localhost:5173');
  await page.fill('#login-email', 'bad@example.com');
  await page.fill('#login-password', 'wrong');
  await page.click('button[type="submit"]');
  await expect(page.locator('.error-summary')).toBeVisible({ timeout: 5000 });
});

test('valid login redirects', async ({ page }) => {
  await page.goto('http://localhost:5173');
  await page.fill('#login-email', 'admin@local');
  await page.fill('#login-password', 'admin12345');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  const hash = await page.evaluate(() => location.hash);
  console.log('HASH:', hash);
  await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
});
