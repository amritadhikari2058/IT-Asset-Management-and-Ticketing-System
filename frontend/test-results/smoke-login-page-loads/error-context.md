# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: smoke.spec.js >> login page loads
- Location: e2e\smoke.spec.js:3:1

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
> 4  |   await page.goto('/');
     |              ^ Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:5173/
  5  |   await expect(page.locator('#login-email')).toBeVisible();
  6  | });
  7  | 
  8  | test('invalid login shows error', async ({ page }) => {
  9  |   await page.goto('/');
  10 |   await page.fill('#login-email', 'bad@example.com');
  11 |   await page.fill('#login-password', 'wrong');
  12 |   await page.click('button[type="submit"]');
  13 |   await expect(page.locator('.error-summary')).toBeVisible({ timeout: 5000 });
  14 | });
  15 | 
  16 | test('valid login redirects to tickets', async ({ page }) => {
  17 |   await page.goto('/');
  18 |   await page.fill('#login-email', 'admin@local');
  19 |   await page.fill('#login-password', 'admin12345');
  20 |   await page.click('button[type="submit"]');
  21 |   await page.waitForFunction(() => location.hash.includes('tickets'));
  22 |   await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
  23 | });
  24 | 
```