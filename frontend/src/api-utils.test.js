import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('./api', () => ({ default: {} }));

import { parseApiError, blobErrorMessage, fieldMsg } from './api-utils';

const HTML_PAGE = `<!DOCTYPE html>
<html lang="en"><head><title>OperationalError at /api/assets/attachments/</title></head>
<body><h1>Traceback (most recent call last)</h1><p>no such table: assets_assetattachment</p></body></html>`;

let warn;
beforeEach(() => {
  warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => warn.mockRestore());

describe('parseApiError with non-JSON (HTML) responses', () => {
  it('turns a Django error page into a friendly message', () => {
    const p = parseApiError({ response: { status: 500, data: HTML_PAGE } });
    expect(p.global).toMatch(/Server error \(HTTP 500\)/);
    expect(p.global).not.toMatch(/<html|Traceback|no such table/i);
    // The raw body still reaches the console for debugging.
    expect(warn).toHaveBeenCalled();
    expect(String(warn.mock.calls[0][1])).toContain('no such table');
  });

  it('keeps ordinary DRF strings untouched', () => {
    const p = parseApiError({ response: { status: 404, data: 'Not found.' } });
    expect(p.global).toBe('Not found.');
    expect(warn).not.toHaveBeenCalled();
  });

  it('maps field errors and details exactly as before', () => {
    const p = parseApiError({
      response: { status: 400, data: { serial_number: ['Already used.'], detail: 'Bad.' } },
    });
    expect(p.fields.serial_number).toBe('Already used.');
    expect(p.global).toBe('Bad.');
    expect(warn).not.toHaveBeenCalled();
  });

  it('replaces an HTML value nested inside a JSON body', () => {
    const p = parseApiError({ response: { status: 500, data: { detail: HTML_PAGE } } });
    expect(p.global).toMatch(/Server error \(HTTP 500\)/);
    expect(p.global).not.toMatch(/Traceback/);
  });

  it('falls back to a generic message when the request never reached the server', () => {
    const p = parseApiError(new Error('Network Error'));
    expect(p.global).toMatch(/Network Error/);
  });
});

describe('blobErrorMessage with non-JSON (HTML) responses', () => {
  it('returns a friendly message for an HTML blob', async () => {
    const e = {
      response: { status: 502, data: new Blob([HTML_PAGE], { type: 'text/html' }) },
    };
    const msg = await blobErrorMessage(e, 'Upload failed.');
    expect(msg).toMatch(/Server error \(HTTP 502\)/);
    expect(msg).not.toMatch(/Traceback/);
    expect(warn).toHaveBeenCalled();
  });

  it('still surfaces JSON blobs as field messages', async () => {
    const e = {
      response: { status: 400, data: new Blob([JSON.stringify({ file: ['Too large.'] })]) },
    };
    const msg = await blobErrorMessage(e, 'Upload failed.');
    expect(msg).toBe('Too large.');
  });

  it('returns the generic message when the error carries nothing readable', async () => {
    // No response, no message: parseApiError still produces its generic text.
    const msg = await blobErrorMessage({}, 'Upload failed.');
    expect(msg).toBe('Request failed.');
  });
});

describe('fieldMsg', () => {
  it('reads a field message and tolerates missing keys', () => {
    expect(fieldMsg({ file: 'Nope.' }, 'file')).toBe('Nope.');
    expect(fieldMsg({ file: 'Nope.' }, 'other')).toBe('');
    expect(fieldMsg(undefined, 'file')).toBe('');
  });
});
