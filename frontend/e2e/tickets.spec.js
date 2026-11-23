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

test('tickets list loads after login', async ({ page }) => {
  await expect(page.locator('body')).toContainText(/Ticket/i);
});

test('create a ticket and view its detail', async ({ page }) => {
  await page.locator('a[href="#/tickets/new"], text=New ticket, [href*="tickets/new"]').first().click().catch(() => {});
  // Fallback: navigate directly if the new-ticket link isn't surfaced.
  if (!page.url().includes('tickets/new')) {
    await page.goto('/#/tickets/new');
  }
  await page.fill('input[name="title"], input[placeholder*="summary"]', 'E2E smoke ticket');
  await page.fill('textarea', 'E2E description');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('/tickets/') && !location.hash.includes('/new'), { timeout: 10000 });
  await expect(page.locator('body')).toContainText('E2E smoke ticket', { timeout: 10000 });
});

test('edit ticket status', async ({ page }) => {
  await page.goto('/#/tickets/new');
  await page.fill('input[placeholder*="summary"]', 'E2E status ticket');
  await page.fill('textarea', 'status edit description');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.match(/#\/tickets\/\d+$/), { timeout: 10000 });
  const id = location.hash.match(/\d+/)[0];
  await page.locator(`a[href="#/tickets/${id}/edit"], text=Edit`).first().click();
  await page.selectOption('select', 'resolved');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes(`/tickets/${id}`), { timeout: 10000 });
  await expect(page.locator('body')).toContainText('Resolved', { timeout: 10000 });
});
