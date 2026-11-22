import { test, expect } from '@playwright/test';

async function signIn(page, email = 'employee@local', password = 'employee123') {
  await page.goto('/');
  await page.fill('#login-email', email);
  await page.fill('#login-password', password);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForFunction(() => location.hash.includes('/tickets'));
}

test('logout clears the local session and returns to sign in', async ({ page }) => {
  await signIn(page, 'admin@local', 'admin12345');
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem('access')))).toBe(true);

  await page.getByRole('button', { name: 'Log out' }).click();
  await expect(page.locator('#login-email')).toBeVisible();
  await expect.poll(() => page.evaluate(() => ({
    access: localStorage.getItem('access'),
    refresh: localStorage.getItem('refresh'),
  }))).toEqual({ access: null, refresh: null });
});

test('a created ticket remains available after reload and API refetch', async ({ page }) => {
  await signIn(page);
  await page.goto('/#/tickets/new');
  const title = `Assignment 5 persistence ${Date.now()}`;

  await page.getByPlaceholder('Brief summary of the issue').fill(title);
  await page.getByPlaceholder(/Steps to reproduce/).fill('Created by the isolated Playwright workflow.');
  const category = page.getByLabel('Ticket category');
  await expect(category.locator('option').nth(1)).toBeAttached();
  await category.selectOption({ index: 1 });
  await page.getByRole('button', { name: 'Create ticket' }).click();
  await page.waitForFunction(() => /^#\/tickets\/\d+$/.test(location.hash));
  await expect(page.locator('body')).toContainText(title);

  await page.reload();
  await expect(page.locator('body')).toContainText(title);
  const record = await page.evaluate(async () => {
    const id = location.hash.match(/^#\/tickets\/(\d+)$/)?.[1];
    const response = await fetch(`http://127.0.0.1:8000/api/tickets/${id}/`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access')}` },
    });
    return { status: response.status, data: await response.json() };
  });

  expect(record.status).toBe(200);
  expect(record.data.title).toBe(title);
});

test('navigation works at desktop and mobile viewport sizes', async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 900 });
  await signIn(page, 'admin@local', 'admin12345');
  await expect(page.locator('.sidebar')).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  const navToggle = page.getByRole('button', { name: 'Open navigation' });
  await expect(navToggle).toBeVisible();
  await navToggle.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'Close navigation' })).toHaveAttribute('aria-expanded', 'true');

  const primaryNav = page.getByRole('navigation', { name: 'Primary' });
  await primaryNav.getByRole('button', { name: /Overview/ }).click();
  await primaryNav.getByRole('link', { name: 'Dashboard' }).click();
  await page.waitForFunction(() => location.hash === '#/dashboard');
});
