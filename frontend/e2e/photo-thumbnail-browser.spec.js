import { test, expect } from '@playwright/test';

/**
 * Real browser coverage for PhotoThumbnail (native button semantics, name,
 * Space/Enter activation, blob preview lifecycle). A staff photo is uploaded
 * through the real photo endpoint first so the thumbnail actually renders.
 */

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

async function login(page) {
  await page.goto('/');
  await page.fill('#login-email', 'support@local');
  await page.fill('#login-password', 'support12345');
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForFunction(() => location.hash.includes('/tickets'));
}

test('photo thumbnail is a button with a name and Space opens the preview', async ({ page }) => {
  await login(page);

  // Upload a photo for the first employee through the real endpoint so the
  // list renders a thumbnail for it.
  const upload = await page.evaluate(async (bytes) => {
    const list = await fetch('http://127.0.0.1:8000/api/accounts/users/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access')}` },
    }).then((r) => r.json());
    const rows = Array.isArray(list) ? list : list.results;
    const target = rows[0];
    const fd = new FormData();
    fd.append('photo', new File([new Uint8Array(bytes)], 'e2e-avatar.png', { type: 'image/png' }));
    const res = await fetch(`http://127.0.0.1:8000/api/accounts/users/${target.id}/photo/`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${localStorage.getItem('access')}` },
      body: fd,
    });
    return { id: target.id, status: res.status, employee: target.employee_id };
  }, [...PNG]);
  expect(upload.status).toBe(200);

  await page.goto('/#/users');
  const thumb = page.getByRole('button', { name: /^Photo of / }).first();
  await expect(thumb).toBeVisible();

  // Native button semantics: real <button type="button">, not a div role.
  const tagName = await thumb.evaluate((el) => el.tagName.toLowerCase());
  expect(tagName).toBe('button');
  const type = await thumb.getAttribute('type');
  expect(type).toBe('button');

  // The thumbnail itself is decorative; the button carries the accessible name.
  await expect(thumb.locator('img')).toHaveAttribute('alt', '');

  // Keyboard focus + Space activation opens the protected preview modal.
  await thumb.focus();
  await expect(thumb).toBeFocused();
  await page.keyboard.press(' ');
  const modal = page.getByRole('dialog');
  await expect(modal).toBeVisible();
  const src = await modal.locator('img').getAttribute('src');
  expect(src).toMatch(/^blob:/);
  expect(await modal.locator('img').evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);

  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();

  // A second activation still works (no revoked-URL state left behind).
  await thumb.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
});
