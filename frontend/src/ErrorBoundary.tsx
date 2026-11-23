import { Component, ReactNode, useState, createContext } from 'react';

const ToastCtx = createContext<{ push: (m: string, s?: string) => number } | null>(null);

export function setToastContext(ctx: { push: (m: string, s?: string) => number }) { // eslint-disable-line react/only-export-components
  // no-op, kept for type stability
  Object.assign(ToastCtx, { _ctx: ctx });
}

interface State {
  hasError: boolean;
  error: Error | null;
  info: string | null;
}

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

/** Catches render errors in the subtree so a crashing page never blanks the
 *  whole app. Shows a friendly inline fallback with a "Try again" button that
 *  remounts the boundary's children from scratch. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, info: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: { componentStack?: string }): void {
    this.setState({ info: errorInfo.componentStack ?? null });
    try {
      console.error('[ErrorBoundary] caught render error:', error);
      console.error('[ErrorBoundary] component stack:', errorInfo.componentStack);
      const toastCtx = (ToastCtx as any)._ctx;
      if (toastCtx?.push) {
        toastCtx.push(`Page error: ${error?.message || 'Unknown error'}`, 'error');
      }
    } catch { /* ignore */ }
  }

  reset = () => {
    this.setState({ hasError: false, error: null, info: null });
  };

  render() {
    if (this.state.hasError) {
      const fallback = this.props.fallback ?? (
        <div className="panel panel-pad" role="alert">
          <h2>Something went wrong</h2>
          <p>This page encountered an error and could not render.</p>
          {this.state.error?.message && (
            <p className="muted small">{this.state.error.message}</p>
          )}
          <button type="button" className="btn-primary" onClick={this.reset}>
            Try again
          </button>
        </div>
      );
      return <>{fallback}</>;
    }
    return this.props.children;
  }
}

/** Hook-based variant for function components that prefer not to use a class. */
export function useErrorBoundary() { // eslint-disable-line react/only-export-components
  const [state, setState] = useState<State>({ hasError: false, error: null, info: null });

  const onError = (error: Error, info: { componentStack?: string }) => {
    setState({ hasError: true, error, info: info.componentStack ?? null });
    try {
      console.error('[ErrorBoundary] caught render error:', error);
      console.error('[ErrorBoundary] component stack:', info.componentStack);
    } catch { /* ignore */ }
  };

  const reset = () => setState({ hasError: false, error: null, info: null });

  return { state, onError, reset };
}
