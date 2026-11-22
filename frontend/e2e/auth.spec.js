import { test, expect } from '@playwright/test';

test('login page loads', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#login-email')).toBeVisible();
});

test('invalid login shows error', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'bad@example.com');
  await page.fill('#login-password', 'wrong');
  await page.click('button[type="submit"]');
  await expect(page.locator('.error-summary')).toBeVisible({ timeout: 5000 });
});

test('valid login redirects', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'admin@local');
  await page.fill('#login-password', 'admin12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));
  await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
});

test('session persistence after page reload', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'admin@local');
  await page.fill('#login-password', 'admin12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));
  await page.reload();
  await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
});

test('logout clears session', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'admin@local');
  await page.fill('#login-password', 'admin12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));
  await page.click('text=Logout');
  await page.waitForFunction(() => !location.hash.includes('tickets'));
  await expect(page.locator('#login-email')).toBeVisible();
});

test('protected route access while unauthenticated', async ({ page }) => {
  await page.goto('/#/tickets');
  await page.waitForSelector('#login-email', { state: 'visible', timeout: 3000 });
});
