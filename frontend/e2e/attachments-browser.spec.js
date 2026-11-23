import { test, expect } from '@playwright/test';

/**
 * Real browser -> real Django server verification of multipart uploads,
 * protection headers, and the blob-backed image preview on asset details.
 *
 * Unlike a mocked-route test, these flows hit the dev API at
 * http://127.0.0.1:8000/api, so a 201 and the attachment appearing in the
 * list is server-side evidence that the multipart body was accepted.
 */

const STAFF = { email: 'support@local', password: 'support12345' };

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

const uploadButton = (page) => page.getByRole('button', { name: 'Upload', exact: true });

async function login(page, { email, password } = STAFF) {
  await page.goto('/');
  await page.fill('#login-email', email);
  await page.fill('#login-password', password);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForFunction(() => location.hash.includes('/tickets'));
}

async function createTicketViaUi(page) {
  await page.goto('/#/tickets/new');
  const title = `Multipart verification ${Date.now()}`;
  await page.getByPlaceholder('Brief summary of the issue').fill(title);
  await page.getByPlaceholder(/Steps to reproduce/).fill('Created by the browser verification spec.');
  const category = page.getByLabel('Ticket category');
  await expect(category.locator('option').nth(1)).toBeAttached();
  await category.selectOption({ index: 1 });
  await page.getByRole('button', { name: 'Create ticket' }).click();
  await page.waitForFunction(() => /^#\/tickets\/\d+$/.test(location.hash));
  const id = await page.evaluate(() => Number(location.hash.match(/^#\/tickets\/(\d+)$/)[1]));
  return { id, title };
}

async function createAssetViaUi(page) {
  await page.goto('/#/assets/new');
  const tag = `E2E-${Date.now()}`;
  await page.getByPlaceholder('e.g. LT-0001').fill(tag);
  await page.getByPlaceholder('e.g. ThinkPad T14').fill('Browser verification asset');
  const category = page.getByLabel('Asset category');
  await expect(category.locator('option').nth(1)).toBeAttached();
  await category.selectOption({ index: 1 });
  await page.getByRole('button', { name: 'Create asset' }).click();
  await page.waitForFunction(() => /^#\/assets\/\d+$/.test(location.hash));
  const id = await page.evaluate(() => Number(location.hash.match(/^#\/assets\/(\d+)$/)[1]));
  return { id, tag };
}

test('ticket attachment upload sends a real multipart request with auth and a boundary', async ({ page }) => {
  await login(page);
  const { id } = await createTicketViaUi(page);

  const uploads = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().endsWith('/api/tickets/attachments/')) {
      uploads.push(req.headers());
    }
  });

  const fileName = `e2e-note-${Date.now()}.txt`;
  await page.getByLabel('Choose a file to upload').setInputFiles({
    name: fileName,
    mimeType: 'text/plain',
    buffer: Buffer.from('browser multipart verification payload'),
  });
  await uploadButton(page).click();

  await expect(page.getByText(`Uploaded "${fileName}"`)).toBeVisible({ timeout: 20000 });
  await expect(page.getByText(fileName)).toBeVisible();

  expect(uploads).toHaveLength(1);
  const headers = uploads[0];
  // Boundary present; JSON never stamped on the multipart body.
  expect(headers['content-type']).toMatch(/^multipart\/form-data; boundary=.+/);
  expect(headers['content-type']).not.toContain('application/json');
  // Auth header survives the interceptor.
  expect(headers.authorization).toMatch(/^Bearer .+/);

  // Server-side evidence: the API returns the stored attachment.
  const stored = await page.evaluate(async (ticketId) => {
    const res = await fetch(`http://127.0.0.1:8000/api/tickets/attachments/?ticket=${ticketId}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access')}` },
    });
    return { status: res.status, body: await res.json() };
  }, id);
  expect(stored.status).toBe(200);
  const rows = Array.isArray(stored.body) ? stored.body : stored.body.results;
  expect(rows.map((a) => a.original_filename)).toContain(fileName);
});

test('ticket attachment download uses rel=noopener and a protected blob URL', async ({ page }) => {
  await login(page);
  await createTicketViaUi(page);

  const fileName = `e2e-download-${Date.now()}.txt`;
  await page.getByLabel('Choose a file to upload').setInputFiles({
    name: fileName, mimeType: 'text/plain', buffer: Buffer.from('download me'),
  });
  await uploadButton(page).click();
  await expect(page.getByText(`Uploaded "${fileName}"`)).toBeVisible({ timeout: 20000 });

  // Capture the anchor attributes the app creates for the download.
  await page.evaluate(() => {
    window.__anchors = [];
    const original = document.createElement.bind(document);
    document.createElement = (tag, ...rest) => {
      const el = original(tag, ...rest);
      if (String(tag).toLowerCase() === 'a') window.__anchors.push(el);
      return el;
    };
  });

  const row = page.locator('.file-row', { hasText: fileName });
  await expect(row).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await row.getByRole('button', { name: 'Download', exact: true }).click();
  const download = await downloadPromise;

  const anchorInfo = await page.evaluate(() => window.__anchors.map((a) => ({
    rel: a.rel, download: a.download, href: a.href, connected: a.isConnected,
  })));
  expect(anchorInfo.length).toBeGreaterThan(0);
  expect(anchorInfo[0].rel).toBe('noopener');
  expect(anchorInfo[0].href).toMatch(/^blob:/);
  expect(anchorInfo[0].connected).toBe(false);
  expect(download.suggestedFilename()).toBe(fileName);
  // Busy state cleared: the button is usable again.
  await expect(row.getByRole('button', { name: 'Download', exact: true })).toBeEnabled();
});

test('rejected attachment shows the server validation message and recovers', async ({ page }) => {
  await login(page);
  await createTicketViaUi(page);

  await page.getByLabel('Choose a file to upload').setInputFiles({
    name: 'e2e-blocked.exe',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('MZ'),
  });
  await uploadButton(page).click();

  const error = page.locator('.field-error[role="alert"]');
  await expect(error).toBeVisible({ timeout: 20000 });
  await expect(error).toContainText(/blocked|allowed|valid|extension/i);
  await expect(uploadButton(page)).toBeEnabled();
  await expect(uploadButton(page)).toHaveText('Upload');
});

test('asset image attachment upload exposes an accessible preview with a live blob URL', async ({ page }) => {
  await login(page);
  const { id } = await createAssetViaUi(page);

  const uploads = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().endsWith('/api/assets/attachments/')) {
      uploads.push(req.headers());
    }
  });

  const fileName = `e2e-asset-${Date.now()}.png`;
  await page.getByLabel('Choose a file to upload').setInputFiles({ name: fileName, mimeType: 'image/png', buffer: PNG });
  await uploadButton(page).click();
  await expect(page.getByText(`Uploaded "${fileName}"`)).toBeVisible({ timeout: 20000 });

  expect(uploads).toHaveLength(1);
  expect(uploads[0]['content-type']).toMatch(/^multipart\/form-data; boundary=.+/);
  expect(uploads[0].authorization).toMatch(/^Bearer .+/);

  // Attachments are listed with a real name (not "File #1").
  await expect(page.locator('.file-name').first()).not.toHaveText(/^File #/);

  const preview = page.getByRole('button', { name: /^Preview / }).first();
  await expect(preview).toBeVisible();
  await preview.focus();
  await page.keyboard.press('Enter');

  const modal = page.getByRole('dialog');
  await expect(modal).toBeVisible();
  const src = await modal.locator('img').getAttribute('src');
  expect(src).toMatch(/^blob:/);
  // The displayed preview is still resolvable (not revoked while in use).
  expect(await modal.locator('img').evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
  // The preview image has a meaningful accessible description.
  expect(await modal.locator('img').getAttribute('alt')).toBeTruthy();

  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();

  const listed = await page.evaluate(async (assetId) => {
    const res = await fetch(`http://127.0.0.1:8000/api/assets/attachments/?asset=${assetId}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('access')}` },
    });
    return { status: res.status, body: await res.json() };
  }, id);
  expect(listed.status).toBe(200);
  const rows = Array.isArray(listed.body) ? listed.body : listed.body.results;
  expect(rows.length).toBeGreaterThan(0);
});

test('failed attachment download shows an error instead of a stale busy state', async ({ page }) => {
  await login(page);
  await createTicketViaUi(page);

  const fileName = `e2e-fail-${Date.now()}.txt`;
  await page.getByLabel('Choose a file to upload').setInputFiles({
    name: fileName, mimeType: 'text/plain', buffer: Buffer.from('x'),
  });
  await uploadButton(page).click();
  await expect(page.getByText(`Uploaded "${fileName}"`)).toBeVisible({ timeout: 20000 });

  // Simulated transport failure for the download request (failure-path only;
  // the success paths above are real server round-trips).
  await page.route('**/api/tickets/attachments/*/download/', (route) => route.abort('failed'));
  const downloadButton = page.locator('.file-row', { hasText: fileName })
    .getByRole('button', { name: 'Download', exact: true });
  await downloadButton.click();
  await expect(page.locator('.field-error[role="alert"]')).toBeVisible({ timeout: 20000 });
  await expect(downloadButton).toBeEnabled();
  await expect(downloadButton).toHaveText('Download');
});
