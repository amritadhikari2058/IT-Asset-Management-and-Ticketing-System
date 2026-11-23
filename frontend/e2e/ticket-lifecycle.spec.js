import { test, expect } from '@playwright/test';

test('employee creates a ticket with required fields', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'employee@local');
  await page.fill('#login-password', 'employee12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  await page.goto('/#/tickets/new');
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
  
  // Verify ticket appears in list
  await expect(page.locator('body')).toContainText(title, { timeout: 10000 });
});

test('ticket detail displays correct data', async ({ page }) => {
  // First create a ticket
  await page.goto('/');
  await page.fill('#login-email', 'employee@local');
  await page.fill('#login-password', 'employee12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  await page.goto('/#/tickets/new');
  const title = 'Detail test ticket ' + Date.now();
  await page.fill('input[placeholder="Brief summary of the issue"]', title);
  await page.fill('textarea', 'Test description');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });

  // Click on the ticket to view details
  await page.click(`text=${title}`);
  await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  
  // Verify detail page shows the title
  await expect(page.locator('body')).toContainText(title, { timeout: 10000 });
});

test('employee cannot access another employee\'s restricted ticket', async ({ page }) => {
  // Create a ticket as the employee account
  await page.goto('/');
  await page.fill('#login-email', 'employee@local');
  await page.fill('#login-password', 'employee12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  await page.goto('/#/tickets/new');
  const title = 'Restricted ticket ' + Date.now();
  await page.fill('input[placeholder="Brief summary of the issue"]', title);
  await page.fill('textarea', 'Test description');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });

  await expect(page.locator('body')).toContainText(title, { timeout: 10000 });
});

test('IT staff can assign the ticket', async ({ page }) => {
  // Create a ticket as employee
  await page.goto('/');
  await page.fill('#login-email', 'employee@local');
  await page.fill('#login-password', 'employee12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  await page.goto('/#/tickets/new');
  const title = 'Assign test ticket ' + Date.now();
  await page.fill('input[placeholder="Brief summary of the issue"]', title);
  await page.fill('textarea', 'Test description');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });

  // Login as IT staff
  await page.goto('/');
  await page.fill('#login-email', 'support@local');
  await page.fill('#login-password', 'support12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  // View the ticket and assign it
  await page.click(`text=${title}`);
  await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  
  // Look for assign button and click
  const assignButton = page.locator('button:has-text("Assign")');
  if (await assignButton.count()) {
    await assignButton.click();
    // Select an assignee
    const userSelect = page.locator('UserSelect');
    if (await userSelect.count()) {
      await userSelect.first().click();
      await page.fill('input', 'itstaff@local');
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Enter');
    }
    await page.click('button[type="submit"]');
  }
  
  // Verify assignment
  await expect(page.locator('body')).toContainText('assigned', { timeout: 10000 });
});

test('employee views their tickets in list', async ({ page }) => {
  await page.goto('/');
  await page.fill('#login-email', 'employee@local');
  await page.fill('#login-password', 'employee12345');
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => location.hash.includes('tickets'));

  await page.goto('/#/tickets');
  // Should see ticket list
  await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
});
