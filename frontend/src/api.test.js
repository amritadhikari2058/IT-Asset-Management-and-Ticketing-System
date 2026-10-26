import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockPost, handlers, instance } = vi.hoisted(() => {
  const mockPost = vi.fn();
  const handlers = {};
  const instance = vi.fn(async (cfg) => ({ data: 'retried', config: cfg }));
  instance.interceptors = {
    request: {
      use: vi.fn((fn) => {
        handlers.request = fn;
      }),
    },
    response: {
      use: (ok, err) => {
        handlers.ok = ok;
        handlers.err = err;
      },
    },
  };
  instance.defaults = { baseURL: 'http://x/api' };
  return { mockPost, handlers, instance };
});

vi.mock('axios', () => ({
  default: {
    create: () => instance,
    post: (...args) => mockPost(...args),
  },
}));

import './api';

const err401 = (url = '/tickets/') => ({
  config: { url, headers: {} },
  response: { status: 401 },
});

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  localStorage.setItem('access', 'old-access');
  localStorage.setItem('refresh', 'good-refresh');
});

describe('auth interceptor', () => {
  it('attaches the stored access token to requests', () => {
    const out = handlers.request({ headers: {} });
    expect(out.headers.Authorization).toBe('Bearer old-access');
  });

  it('refreshes once and retries the original request', async () => {
    mockPost.mockResolvedValueOnce({ data: { access: 'new-access' } });
    const res = await handlers.err(err401());
    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenCalledWith(
      'http://x/api/token/refresh/',
      { refresh: 'good-refresh' },
    );
    expect(localStorage.getItem('access')).toBe('new-access');
    expect(instance).toHaveBeenCalledTimes(1);
    expect(instance.mock.calls[0][0].headers.Authorization).toBe(
      'Bearer new-access',
    );
    expect(instance.mock.calls[0][0]._retry).toBe(true);
    expect(res).toEqual({ data: 'retried', config: expect.anything() });
  });

  it('never retries more than once', async () => {
    const err = err401();
    err.config._retry = true;
    await expect(handlers.err(err)).rejects.toBe(err);
    expect(mockPost).not.toHaveBeenCalled();
    expect(localStorage.getItem('access')).toBe('old-access');
  });

  it('shares one refresh across concurrent 401s', async () => {
    let resolvePost;
    mockPost.mockImplementationOnce(
      () => new Promise((resolve) => { resolvePost = resolve; }),
    );
    const p1 = handlers.err(err401('/tickets/'));
    const p2 = handlers.err(err401('/assets/'));
    await Promise.resolve();
    await Promise.resolve();
    expect(mockPost).toHaveBeenCalledTimes(1);
    resolvePost({ data: { access: 'shared-access' } });
    await expect(p1).resolves.toBeTruthy();
    await expect(p2).resolves.toBeTruthy();
    expect(instance).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem('access')).toBe('shared-access');
  });

  it('clears auth and notifies on failed refresh', async () => {
    const seen = [];
    const onExpired = () => seen.push(true);
    window.addEventListener('auth-expired', onExpired);
    mockPost.mockRejectedValueOnce(new Error('refresh gone'));
    const err = err401();
    await expect(handlers.err(err)).rejects.toBe(err);
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('refresh')).toBeNull();
    expect(seen).toEqual([true]);
    window.removeEventListener('auth-expired', onExpired);
  });

  it('clears auth when no refresh token exists', async () => {
    localStorage.removeItem('refresh');
    const err = err401();
    await expect(handlers.err(err)).rejects.toBe(err);
    expect(mockPost).not.toHaveBeenCalled();
    expect(localStorage.getItem('access')).toBeNull();
  });

  it.each([400, 403, 404, 500])('does not refresh on %i', async (code) => {
    const err = { config: { url: '/tickets/', headers: {} }, response: { status: code } };
    await expect(handlers.err(err)).rejects.toBe(err);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it.each([
    '/token/',
    '/token/refresh/',
    '/accounts/password-reset/confirm/',
    '/accounts/verify-email/confirm/?uid=x&token=y',
  ])('does not loop on auth endpoint %s', async (url) => {
    const err = err401(url);
    await expect(handlers.err(err)).rejects.toBe(err);
    expect(mockPost).not.toHaveBeenCalled();
    expect(localStorage.getItem('access')).toBe('old-access');
  });
});
