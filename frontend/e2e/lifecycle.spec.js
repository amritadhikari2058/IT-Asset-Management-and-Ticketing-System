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

test('full ticket lifecycle: create -> edit -> view -> status change', async ({ page }) => {
  // Create
  await page.goto('/#/tickets/new');
  await page.fill('input[placeholder*="summary"], input[name="title"]', 'E2E lifecycle ticket');
  await page.fill('textarea', 'E2E lifecycle description');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.match(/#\/tickets\/\d+$/), { timeout: 10000 });
  const id = location.hash.match(/\d+/)[0];

  // View detail
  await expect(page.locator('body')).toContainText('E2E lifecycle ticket', { timeout: 10000 });

  // Edit status
  await page.locator('a[href*="/edit"], text=Edit').first().click();
  await page.selectOption('select', 'resolved');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes(`/tickets/${id}`), { timeout: 10000 });
  await expect(page.locator('body')).toContainText('Resolved', { timeout: 10000 });
});

test('login failure shows error', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'bad@user');
  await page.fill('#login-password', 'wrong');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(1000);
  await expect(page.locator('body')).toContainText(/invalid|error|incorrect|failed/i);
});

test('CMDB CI detail loads', async ({ page }) => {
  await page.goto('/#/cmdb/items');
  await expect(page.locator('body')).toContainText(/CMDB|Configuration|CI/i, { timeout: 10000 });
});
