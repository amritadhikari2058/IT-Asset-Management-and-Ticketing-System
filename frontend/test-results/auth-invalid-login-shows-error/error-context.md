# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: auth.spec.js >> invalid login shows error
- Location: e2e\auth.spec.js:8:1

# Error details

```
Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:5173/
Call log:
  - navigating to "http://localhost:5173/", waiting until "load"

```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test('login page loads', async ({ page }) => {
  4  |   await page.goto('/');
  5  |   await expect(page.locator('#login-email')).toBeVisible();
  6  | });
  7  | 
  8  | test('invalid login shows error', async ({ page }) => {
> 9  |   await page.goto('/');
     |              ^ Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:5173/
  10 |   await page.fill('#login-email', 'bad@example.com');
  11 |   await page.fill('#login-password', 'wrong');
  12 |   await page.click('button[type="submit"]');
  13 |   await expect(page.locator('.error-summary')).toBeVisible({ timeout: 5000 });
  14 | });
  15 | 
  16 | test('valid login redirects', async ({ page }) => {
  17 |   await page.goto('/');
  18 |   await page.fill('#login-email', 'admin@local');
  19 |   await page.fill('#login-password', 'admin12345');
  20 |   await page.click('button[type="submit"]');
  21 |   await page.waitForFunction(() => location.hash.includes('tickets'));
  22 |   await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
  23 | });
  24 | 
  25 | test('session persistence after page reload', async ({ page }) => {
  26 |   await page.goto('/');
  27 |   await page.fill('#login-email', 'admin@local');
  28 |   await page.fill('#login-password', 'admin12345');
  29 |   await page.click('button[type="submit"]');
  30 |   await page.waitForFunction(() => location.hash.includes('tickets'));
  31 |   await page.reload();
  32 |   await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
  33 | });
  34 | 
  35 | test('logout clears session', async ({ page }) => {
  36 |   await page.goto('/');
  37 |   await page.fill('#login-email', 'admin@local');
  38 |   await page.fill('#login-password', 'admin12345');
  39 |   await page.click('button[type="submit"]');
  40 |   await page.waitForFunction(() => location.hash.includes('tickets'));
  41 |   await page.click('text=Logout');
  42 |   await page.waitForFunction(() => !location.hash.includes('tickets'));
  43 |   await expect(page.locator('#login-email')).toBeVisible();
  44 | });
  45 | 
  46 | test('protected route access while unauthenticated', async ({ page }) => {
  47 |   await page.goto('/#/tickets');
  48 |   await page.waitForSelector('#login-email', { state: 'visible', timeout: 3000 });
  49 | });
  50 | 
```