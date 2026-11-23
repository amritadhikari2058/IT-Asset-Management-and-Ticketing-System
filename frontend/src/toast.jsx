import { createContext, useContext, useCallback, useState, useRef } from 'react';

/** Severity levels for toasts. */
export const ToastSeverity = { // eslint-disable-line react/only-export-components
  info: 'info',
  success: 'success',
  warning: 'warning',
  error: 'error',
};

const ToastCtx = createContext({
  toasts: [],
  push: () => {},
  dismiss: () => {},
  dismissAll: () => {},
  ToastSeverity,
});

/** Provider that owns the toast queue. Wrap the app shell so any component
 *  can push a toast via useToast(). */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(0);

  const push = useCallback((message, severity = ToastSeverity.info, ttlMs = 5000) => {
    const id = ++nextId.current;
    setToasts((prev) => [...prev, { id, message, severity, ttlMs }]);
    return id;
  }, []);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const dismissAll = useCallback(() => setToasts([]), []);

  const value = { toasts, push, dismiss, dismissAll, ToastSeverity };
  return <ToastCtx.Provider value={value}>{children}</ToastCtx.Provider>;
}

/** Hook to push and dismiss toasts. Returns { push, dismiss, ToastSeverity }. */
export function useToast() { // eslint-disable-line react/only-export-components
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}

/** Presentational toast list. Renders each toast as a dismissible alert. */
export function ToastList() {
  const ctx = useContext(ToastCtx);
  if (!ctx) return null;
  const { toasts, dismiss, ToastSeverity } = ctx;
  const tone = {
    [ToastSeverity.error]: 'danger',
    [ToastSeverity.warning]: 'warning',
    [ToastSeverity.success]: 'success',
    [ToastSeverity.info]: 'info',
  };
  if (!toasts.length) return null;
  return (
    <div className="toast-container" role="region" aria-label="Notifications">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast toast--${tone[t.severity] ?? tone.info}`}
          role="alert"
          aria-live="polite"
        >
          <span className="toast-message">{t.message}</span>
          <button
            type="button"
            className="toast-close"
            onClick={() => dismiss(t.id)}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

/** Convenience wrapper: show an error toast for a failed API error. */
export function toastError(message) { // eslint-disable-line react/only-export-components
  return message;
}
