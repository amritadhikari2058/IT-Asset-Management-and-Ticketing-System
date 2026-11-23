import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';

const { mockPost, mockGet } = vi.hoisted(() => ({
  mockPost: vi.fn(),
  mockGet: vi.fn(),
}));

vi.mock('./api', () => ({
  default: {
    post: mockPost,
    get: mockGet,
  },
}));

import { AuthProvider, useAuth } from './auth';

const capturedAuth = { current: null };
function Probe() {
  capturedAuth.current = useAuth(); // eslint-disable-line immutability
  return null;
}

function mount(getImpl) {
  localStorage.clear();
  mockPost.mockReset();
  mockGet.mockReset();
  mockPost.mockResolvedValue({ data: {} });
  mockGet.mockImplementation(
    getImpl || (() => Promise.resolve({ data: { id: 1, role: 'employee' } })),
  );
  localStorage.setItem('access', 'acc');
  localStorage.setItem('refresh', 'ref');
  return render(<AuthProvider><Probe /></AuthProvider>);
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
});

describe('AuthProvider logout blacklists the refresh token', () => {
  it('calls backend /accounts/logout/ with the refresh token', async () => {
    mount();
    mockPost.mockResolvedValue({ data: { detail: 'Logged out.' } });
    await act(async () => {
      await capturedAuth.current.logout();
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenCalledWith('/accounts/logout/', { refresh: 'ref' });
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('refresh')).toBeNull();
  });

  it('clears tokens locally even when the backend logout fails', async () => {
    mount();
    mockPost.mockRejectedValue(new Error('backend down'));
    await act(async () => {
      await capturedAuth.current.logout();
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('refresh')).toBeNull();
  });

  it('clears tokens without calling the backend when no refresh token exists', async () => {
    mount();
    localStorage.removeItem('refresh');
    await act(async () => {
      await capturedAuth.current.logout();
    });
    expect(mockPost).not.toHaveBeenCalled();
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('refresh')).toBeNull();
  });

  it('drops the React session immediately, before the backend answers', async () => {
    // Security: the access token must not stay usable from the UI while the
    // best-effort blacklist call is still in flight.
    let resolveLogout;
    mount();
    mockPost.mockImplementationOnce(() => new Promise((resolve) => { resolveLogout = resolve; }));
    let pending;
    await act(async () => {
      pending = capturedAuth.current.logout();
    });
    expect(capturedAuth.current.access).toBeNull();
    expect(capturedAuth.current.user).toBeNull();
    expect(capturedAuth.current.profileLoading).toBe(false);
    await act(async () => {
      resolveLogout({ data: {} });
      await pending;
    });
    expect(localStorage.getItem('access')).toBeNull();
  });

  it('clears tokens when the backend never responds', async () => {
    vi.useFakeTimers();
    mount();
    mockPost.mockImplementation(() => new Promise(() => {}));
    let pending;
    act(() => {
      pending = capturedAuth.current.logout();
    });
    expect(capturedAuth.current.access).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    await act(async () => {
      await pending;
    });
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('refresh')).toBeNull();
  });

  it('does not clobber a session created while logout was in flight', async () => {
    let resolveLogout;
    mount();
    mockPost.mockImplementation((url) => {
      if (url === '/accounts/logout/') {
        return new Promise((resolve) => { resolveLogout = resolve; });
      }
      return Promise.resolve({ data: { access: 'acc-2', refresh: 'ref-2' } });
    });
    let pending;
    await act(async () => {
      pending = capturedAuth.current.logout();
    });
    await act(async () => {
      await capturedAuth.current.login('user@example.com', 'pw');
    });
    expect(capturedAuth.current.access).toBe('acc-2');

    await act(async () => {
      resolveLogout({ data: {} });
      await pending;
    });
    expect(localStorage.getItem('access')).toBe('acc-2');
    expect(localStorage.getItem('refresh')).toBe('ref-2');
    expect(capturedAuth.current.access).toBe('acc-2');
  });
});

describe('AuthProvider ignores stale async results', () => {
  it('does not restore the user when /accounts/me/ resolves after logout', async () => {
    let resolveProfile;
    mount(() => new Promise((resolve) => { resolveProfile = resolve; }));
    await act(async () => {
      await capturedAuth.current.logout();
    });
    await act(async () => {
      resolveProfile({ data: { id: 9, role: 'system_admin' } });
    });
    expect(capturedAuth.current.user).toBeNull();
    expect(capturedAuth.current.access).toBeNull();
  });
});

describe('cross-tab session sync', () => {
  it('logs out when another tab removes access from localStorage', async () => {
    mount();
    await act(async () => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'access',
        newValue: null,
        oldValue: 'acc',
      }));
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
    expect(mockPost).toHaveBeenCalledWith('/accounts/logout/', { refresh: 'ref' });
    expect(localStorage.getItem('access')).toBeNull();
    expect(localStorage.getItem('refresh')).toBeNull();
  });

  it('mirrors a cross-tab logout after the shared tokens are already gone', async () => {
    // localStorage is shared by every tab, so a real storage event arrives
    // after the removal is already visible here (no per-tab copy to check).
    mount();
    localStorage.removeItem('access');
    localStorage.removeItem('refresh');
    await act(async () => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'access',
        newValue: null,
        oldValue: 'acc',
      }));
    });
    expect(capturedAuth.current.access).toBeNull();
    expect(capturedAuth.current.user).toBeNull();
    // The tab that logged out already blacklisted the token.
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('does not send a second logout request when the token is already gone', async () => {
    mount();
    await act(async () => {
      await capturedAuth.current.logout();
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
    await act(async () => {
      for (let i = 0; i < 3; i += 1) {
        window.dispatchEvent(new StorageEvent('storage', {
          key: 'access',
          newValue: null,
          oldValue: 'acc',
        }));
      }
    });
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('ignores cross-tab access removal when this tab has no session', async () => {
    localStorage.clear();
    mockPost.mockReset();
    mockGet.mockReset();
    mockGet.mockResolvedValue({ data: {} });
    render(<AuthProvider><Probe /></AuthProvider>);
    await act(async () => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'access',
        newValue: null,
        oldValue: null,
      }));
    });
    expect(mockPost).not.toHaveBeenCalled();
    expect(capturedAuth.current.access).toBeNull();
  });

  it('does not log out when another tab touches an unrelated key', async () => {
    mount();
    await act(async () => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'unrelated',
        newValue: null,
      }));
    });
    expect(mockPost).not.toHaveBeenCalled();
    expect(localStorage.getItem('access')).toBe('acc');
    expect(localStorage.getItem('refresh')).toBe('ref');
  });

  it('invalidates the local session when another tab signs in as a different user', async () => {
    mount();
    await act(async () => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'access',
        newValue: 'other-token',
        oldValue: 'acc',
      }));
    });
    // No backend logout call (the other tab owns its own session).
    expect(mockPost).not.toHaveBeenCalled();
    // Local React state is invalidated so this tab does not show stale data.
    expect(capturedAuth.current.access).toBeNull();
    expect(capturedAuth.current.user).toBeNull();
    expect(capturedAuth.current.profileLoading).toBe(false);
    // The refresh token belonging to the old session is dropped.
    expect(localStorage.getItem('refresh')).toBeNull();
  });
});
