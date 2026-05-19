/**
 * Sprint 28 Batch 15.1 — global toast queue.
 *
 * Replaces ad-hoc `useSavedBanner` + `alert-error` / `alert-info`
 * divs sprinkled across pages with one queue + one visual. Pages
 * call `useToast()` and push messages; the provider at the AppShell
 * level renders the stack and handles dismiss.
 *
 * Variants: success, error, info, warning. Default auto-dismiss is
 * 4 seconds for success/info, 8 seconds for warning, 0 (sticky) for
 * error (the user has to dismiss errors deliberately).
 *
 * Not exported from a barrel; pages `import { useToast } from
 * "../components/ToastProvider"` directly to keep the dependency
 * graph readable.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastVariant = "success" | "error" | "info" | "warning";

export interface ToastInput {
  variant: ToastVariant;
  title: string;
  description?: string;
  /** Override default auto-dismiss. 0 keeps it open until dismissed. */
  durationMs?: number;
}

interface ToastInstance extends ToastInput {
  id: string;
}

interface ToastContextValue {
  push: (toast: ToastInput) => void;
  dismiss: (id: string) => void;
  clear: () => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION: Record<ToastVariant, number> = {
  success: 4_000,
  info: 4_000,
  warning: 8_000,
  error: 0,
};

function variantIcon(variant: ToastVariant) {
  switch (variant) {
    case "success":
      return <CheckCircle2 size={18} strokeWidth={2.2} />;
    case "error":
      return <XCircle size={18} strokeWidth={2.2} />;
    case "warning":
      return <AlertTriangle size={18} strokeWidth={2.2} />;
    case "info":
    default:
      return <Info size={18} strokeWidth={2.2} />;
  }
}

let toastIdCounter = 0;
function nextId(): string {
  toastIdCounter += 1;
  return `toast-${toastIdCounter}-${Date.now().toString(36)}`;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastInstance[]>([]);
  const timers = useRef<Map<string, number>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const handle = timers.current.get(id);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (input: ToastInput) => {
      const id = nextId();
      const duration = input.durationMs ?? DEFAULT_DURATION[input.variant];
      setToasts((prev) => [...prev, { ...input, id }]);
      if (duration > 0) {
        const handle = window.setTimeout(() => dismiss(id), duration);
        timers.current.set(id, handle);
      }
    },
    [dismiss],
  );

  const clear = useCallback(() => {
    setToasts([]);
    timers.current.forEach((handle) => window.clearTimeout(handle));
    timers.current.clear();
  }, []);

  // Clean up any pending timers on unmount.
  useEffect(() => {
    const timersAtMount = timers.current;
    return () => {
      timersAtMount.forEach((handle) => window.clearTimeout(handle));
      timersAtMount.clear();
    };
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({ push, dismiss, clear }),
    [push, dismiss, clear],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="region" aria-label="Notifications">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast toast-${toast.variant}`}
            role={toast.variant === "error" ? "alert" : "status"}
            data-testid={`toast-${toast.variant}`}
          >
            <span className="toast-icon" aria-hidden="true">
              {variantIcon(toast.variant)}
            </span>
            <div className="toast-text">
              <div className="toast-title">{toast.title}</div>
              {toast.description && (
                <div className="toast-desc">{toast.description}</div>
              )}
            </div>
            <button
              type="button"
              className="toast-close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
            >
              <X size={14} strokeWidth={2.4} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return ctx;
}

