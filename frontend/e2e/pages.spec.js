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

test('CMDB page loads', async ({ page }) => {
  await page.goto('/#/cmdb');
  await expect(page.locator('body')).toContainText(/CMDB|Configuration/i, { timeout: 10000 });
});

test('Procurement page loads', async ({ page }) => {
  await page.goto('/#/procurement');
  await expect(page.locator('body')).toContainText(/Procurement|Purchase/i, { timeout: 10000 });
});

test('Licensing page loads', async ({ page }) => {
  await page.goto('/#/licensing');
  await expect(page.locator('body')).toContainText(/License|Licensing/i, { timeout: 10000 });
});

test('Inventory page loads', async ({ page }) => {
  await page.goto('/#/inventory');
  await expect(page.locator('body')).toContainText(/Inventory/i, { timeout: 10000 });
});

test('KB page loads', async ({ page }) => {
  await page.goto('/#/kb');
  await expect(page.locator('body')).toContainText(/Knowledge|KB|Article/i, { timeout: 10000 });
});
