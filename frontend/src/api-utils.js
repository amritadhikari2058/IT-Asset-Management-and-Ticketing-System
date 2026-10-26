import api from './api';

// Django/DRF can answer with an HTML page instead of JSON (e.g. an unhandled
// OperationalError or a DEBUG traceback). Showing that markup in the UI is
// meaningless, so we detect it, keep the raw body in the console for
// debugging, and surface a short human message instead.
const LOOKS_LIKE_HTML = /^\s*<(!doctype|html|head|body|pre|table|div)\b/i;

function isHtmlBody(s) {
  return typeof s === 'string' && LOOKS_LIKE_HTML.test(s);
}

function serverErrorMessage(status) {
  const code = status ? ` (HTTP ${status})` : '';
  return `Server error${code}. The request could not be completed - please try again. If it keeps happening, report it to support.`;
}

function warnRawBody(status, body) {
  try {
    console.warn(`[api] Non-JSON error response (HTTP ${status}); raw body follows for debugging:`, String(body).slice(0, 5000));
  } catch { /* console unavailable */ }
}

/** Flatten a DRF error response to {fields: {name: msg}, global: msg}. */
export function parseApiError(e) {
  const data = e?.response?.data;
  const status = e?.response?.status;
  const out = { fields: {}, global: '' };
  if (!data) {
    out.global = e?.message ? `Request failed: ${e.message}` : 'Request failed.';
    return out;
  }
  if (typeof data === 'string') {
    if (isHtmlBody(data)) {
      warnRawBody(status, data);
      out.global = serverErrorMessage(status);
    } else {
      out.global = data;
    }
    return out;
  }
  for (const [k, v] of Object.entries(data)) {
    let msg = Array.isArray(v) ? v.join(' ') : (typeof v === 'object' ? JSON.stringify(v) : String(v));
    if (isHtmlBody(msg)) {
      warnRawBody(status, msg);
      msg = serverErrorMessage(status);
    }
    if (k === 'detail' || k === 'non_field_errors') out.global = out.global ? `${out.global} ${msg}` : msg;
    else out.fields[k] = msg;
  }
  if (!out.global && Object.keys(out.fields).length === 0) out.global = 'Request failed.';
  if (e?.response?.status === 403 && !out.global) out.global = 'Forbidden: you lack permission for this action.';
  return out;
}

export function fieldMsg(fieldErrors, name) {
  return fieldErrors?.[name] ?? '';
}

/** Paginated GET helper returning {items, count, next, previous}. */
export async function fetchPage(url) {
  const r = await api.get(url);
  const d = r.data;
  if (Array.isArray(d)) return { items: d, count: d.length, next: null, previous: null };
  return { items: d.results ?? [], count: d.count, next: d.next, previous: d.previous };
}

/** Trigger a browser download for a Blob with a filename. */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** Minimal CSV parser honoring quotes/escaped quotes/commas/newlines. */
export function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  const pushField = () => { row.push(field); field = ''; };
  const pushRow = () => { rows.push(row); row = []; };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else quoted = false;
      } else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') pushField();
    else if (ch === '\r') { /* wait for \n */ }
    else if (ch === '\n') { pushField(); pushRow(); }
    else field += ch;
  }
  pushField();
  if (row.length > 1 || (row.length === 1 && row[0] !== '')) pushRow();
  return rows;
}

/** Extract a readable message when an error response arrived as a Blob. */
export async function blobErrorMessage(e, fallback) {
  try {
    const blob = e?.response?.data;
    if (blob instanceof Blob) {
      const text = await blob.text();
      try {
        const p = parseApiError({ ...e, response: { ...e.response, data: JSON.parse(text) } });
        if (p.global) return p.global;
        const fieldMsgs = Object.values(p.fields).filter(Boolean);
        if (fieldMsgs.length) return fieldMsgs.join(' ');
      } catch { /* not JSON; fall through */ }
      // An HTML/debug page in a Blob is just as unreadable as in JSON:
      // log it, return a friendly message.
      if (isHtmlBody(text)) {
        warnRawBody(e?.response?.status, text);
        return serverErrorMessage(e?.response?.status);
      }
      if (text.trim()) return text.trim().slice(0, 500);
    }
  } catch { /* ignore */ }
  return parseApiError(e).global || fallback;
}
