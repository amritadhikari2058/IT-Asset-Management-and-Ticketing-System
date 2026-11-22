# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: ticket-lifecycle.spec.js >> employee cannot access another employee's restricted ticket
- Location: e2e\ticket-lifecycle.spec.js:50:1

# Error details

```
Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:5173/
Call log:
  - navigating to "http://localhost:5173/", waiting until "load"

```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test';
  2   | 
  3   | test('employee creates a ticket with required fields', async ({ page }) => {
  4   |   await page.goto('/');
  5   |   await page.fill('#login-email', 'employee@local');
  6   |   await page.fill('#login-password', 'employee123');
  7   |   await page.click('button[type="submit"]');
  8   |   await page.waitForFunction(() => location.hash.includes('tickets'));
  9   | 
  10  |   await page.goto('/#/tickets/new');
  11  |   const title = 'E2E ticket ' + Date.now();
  12  |   await page.fill('input[placeholder="Brief summary of the issue"]', title);
  13  |   await page.fill('textarea', 'Automated E2E description');
  14  |   
  15  |   // select first category if available
  16  |   const cat = page.locator('select').nth(1);
  17  |   if (await cat.count()) {
  18  |     await cat.selectOption({ index: 1 });
  19  |   }
  20  |   await page.click('button[type="submit"]');
  21  |   await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  22  |   
  23  |   // Verify ticket appears in list
  24  |   await expect(page.locator('body')).toContainText(title, { timeout: 10000 });
  25  | });
  26  | 
  27  | test('ticket detail displays correct data', async ({ page }) => {
  28  |   // First create a ticket
  29  |   await page.goto('/');
  30  |   await page.fill('#login-email', 'employee@local');
  31  |   await page.fill('#login-password', 'employee123');
  32  |   await page.click('button[type="submit"]');
  33  |   await page.waitForFunction(() => location.hash.includes('tickets'));
  34  | 
  35  |   await page.goto('/#/tickets/new');
  36  |   const title = 'Detail test ticket ' + Date.now();
  37  |   await page.fill('input[placeholder="Brief summary of the issue"]', title);
  38  |   await page.fill('textarea', 'Test description');
  39  |   await page.click('button[type="submit"]');
  40  |   await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  41  | 
  42  |   // Click on the ticket to view details
  43  |   await page.click(`text=${title}`);
  44  |   await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  45  |   
  46  |   // Verify detail page shows the title
  47  |   await expect(page.locator('body')).toContainText(title, { timeout: 10000 });
  48  | });
  49  | 
  50  | test('employee cannot access another employee\'s restricted ticket', async ({ page }) => {
  51  |   // Create a ticket as employee1
> 52  |   await page.goto('/');
      |              ^ Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:5173/
  53  |   await page.fill('#login-email', 'employee1@local');
  54  |   await page.fill('#login-password', 'employee123');
  55  |   await page.click('button[type="submit"]');
  56  |   await page.waitForFunction(() => location.hash.includes('tickets'));
  57  | 
  58  |   await page.goto('/#/tickets/new');
  59  |   const title = 'Restricted ticket ' + Date.now();
  60  |   await page.fill('input[placeholder="Brief summary of the issue"]', title);
  61  |   await page.fill('textarea', 'Test description');
  62  |   await page.click('button[type="submit"]');
  63  |   await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  64  | 
  65  |   // Login as employee2 and try to access employee1's ticket
  66  |   await page.goto('/');
  67  |   await page.fill('#login-email', 'employee2@local');
  68  |   await page.fill('#login-password', 'employee123');
  69  |   await page.click('button[type="submit"]');
  70  |   await page.waitForFunction(() => location.hash.includes('tickets'));
  71  | 
  72  |   // Try to access the restricted ticket - should be denied or not visible
  73  |   await page.goto('/#/tickets');
  74  |   // Should not see employee1's ticket in the list
  75  | });
  76  | 
  77  | test('IT staff can assign the ticket', async ({ page }) => {
  78  |   // Create a ticket as employee
  79  |   await page.goto('/');
  80  |   await page.fill('#login-email', 'employee@local');
  81  |   await page.fill('#login-password', 'employee123');
  82  |   await page.click('button[type="submit"]');
  83  |   await page.waitForFunction(() => location.hash.includes('tickets'));
  84  | 
  85  |   await page.goto('/#/tickets/new');
  86  |   const title = 'Assign test ticket ' + Date.now();
  87  |   await page.fill('input[placeholder="Brief summary of the issue"]', title);
  88  |   await page.fill('textarea', 'Test description');
  89  |   await page.click('button[type="submit"]');
  90  |   await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  91  | 
  92  |   // Login as IT staff
  93  |   await page.goto('/');
  94  |   await page.fill('#login-email', 'itstaff@local');
  95  |   await page.fill('#login-password', 'itstaff123');
  96  |   await page.click('button[type="submit"]');
  97  |   await page.waitForFunction(() => location.hash.includes('tickets'));
  98  | 
  99  |   // View the ticket and assign it
  100 |   await page.click(`text=${title}`);
  101 |   await page.waitForFunction(() => location.hash.includes('/tickets/'), { timeout: 10000 });
  102 |   
  103 |   // Look for assign button and click
  104 |   const assignButton = page.locator('button:has-text("Assign")');
  105 |   if (await assignButton.count()) {
  106 |     await assignButton.click();
  107 |     // Select an assignee
  108 |     const userSelect = page.locator('UserSelect');
  109 |     if (await userSelect.count()) {
  110 |       await userSelect.first().click();
  111 |       await page.fill('input', 'itstaff@local');
  112 |       await page.keyboard.press('ArrowDown');
  113 |       await page.keyboard.press('Enter');
  114 |     }
  115 |     await page.click('button[type="submit"]');
  116 |   }
  117 |   
  118 |   // Verify assignment
  119 |   await expect(page.locator('body')).toContainText('assigned', { timeout: 10000 });
  120 | });
  121 | 
  122 | test('employee views their tickets in list', async ({ page }) => {
  123 |   await page.goto('/');
  124 |   await page.fill('#login-email', 'employee@local');
  125 |   await page.fill('#login-password', 'employee123');
  126 |   await page.click('button[type="submit"]');
  127 |   await page.waitForFunction(() => location.hash.includes('tickets'));
  128 | 
  129 |   await page.goto('/#/tickets');
  130 |   // Should see ticket list
  131 |   await expect(page.locator('body')).toContainText(/Ticket/i, { timeout: 10000 });
  132 | });
  133 | 
```