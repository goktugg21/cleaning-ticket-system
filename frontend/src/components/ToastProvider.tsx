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
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastVariant = "success" | "error" | "info" | "warning";

/** W-LATE addendum 2 — the rung a warning toast stands on. L1 is the
 *  standard warning tone; L2 is red; L3 dark red. L2 and L3 do NOT
 *  auto-dismiss: `push` gives them a sticky duration unless the caller
 *  says otherwise, because a broken promise is not a four-second fact. */
export type ToastSeverity = "L1" | "L2" | "L3";

export interface ToastInput {
  variant: ToastVariant;
  title: string;
  description?: string;
  /** Override default auto-dismiss. 0 keeps it open until dismissed. */
  durationMs?: number;
  /** Colour the toast by rung and, for L2/L3, keep it until dismissed. */
  severity?: ToastSeverity;
  /**
   * When set, the toast becomes activatable (click / Enter / Space):
   * invoking it runs this handler AND dismisses the toast. Callers that
   * omit it (the default) render a display-only toast, unchanged.
   */
  onClick?: () => void;
}

interface ToastInstance extends ToastInput {
  id: string;
  /** FE-4 (Addendum D §D.12) — how many identical pushes this toast
   *  stands for. Repeats collapse into one card with a count instead of
   *  stacking (the seeded W-LATE ladder pushed the same title three
   *  times and covered a third of the page). */
  count: number;
}

interface ToastContextValue {
  push: (toast: ToastInput) => void;
  dismiss: (id: string) => void;
  clear: () => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/** W-UX F50 — how many ORDINARY toasts stand at once. The rest wait
 *  behind one "+N more" line and surface as these expire or are
 *  dismissed. W-LATE's persistent L2/L3 severity toasts are never
 *  capped: a broken promise is not something to queue. */
const MAX_VISIBLE_PLAIN = 2;

function isSeverityToast(toast: ToastInput): boolean {
  return toast.severity === "L2" || toast.severity === "L3";
}

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
  const { t } = useTranslation("common");
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
      // W-LATE — L2/L3 stay until dismissed; the provider already had a
      // sticky mode (0), so persistence is a default here, not a new
      // mechanism.
      const sticky = input.severity === "L2" || input.severity === "L3";
      const duration =
        input.durationMs ?? (sticky ? 0 : DEFAULT_DURATION[input.variant]);
      // FE-4 — a repeat of a toast already on screen (same variant, same
      // title, same severity) bumps that toast's count and restarts its
      // clock rather than adding a card. The newest description wins.
      let collapsedInto: string | null = null;
      setToasts((prev) => {
        const existing = prev.find(
          (toast) =>
            toast.variant === input.variant &&
            toast.title === input.title &&
            (toast.severity ?? null) === (input.severity ?? null),
        );
        if (existing) {
          collapsedInto = existing.id;
          return prev.map((toast) =>
            toast.id === existing.id
              ? {
                  ...toast,
                  count: toast.count + 1,
                  description: input.description ?? toast.description,
                  onClick: input.onClick ?? toast.onClick,
                }
              : toast,
          );
        }
        return prev;
      });
      const id = collapsedInto ?? nextId();
      if (collapsedInto === null) {
        setToasts((prev) => [...prev, { ...input, id, count: 1 }]);
      }
      const previousTimer = timers.current.get(id);
      if (previousTimer !== undefined) {
        window.clearTimeout(previousTimer);
        timers.current.delete(id);
      }
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

  // F50 — the stack: every severity toast, then the first two ordinary
  // ones, then one line saying how many more are waiting.
  const severityToasts = toasts.filter(isSeverityToast);
  const plainToasts = toasts.filter((toast) => !isSeverityToast(toast));
  const visible = [...severityToasts, ...plainToasts.slice(0, MAX_VISIBLE_PLAIN)];
  const hiddenCount = Math.max(0, plainToasts.length - MAX_VISIBLE_PLAIN);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="region" aria-label="Notifications">
        {visible.map((toast) => {
          const clickable = typeof toast.onClick === "function";
          const activate = () => {
            toast.onClick?.();
            dismiss(toast.id);
          };
          return (
            <div
              key={toast.id}
              className={`toast toast-${toast.variant}${
                clickable ? " toast-clickable" : ""
              }${toast.severity ? ` toast-sev-${toast.severity.toLowerCase()}` : ""}`}
              data-severity={toast.severity}
              role={
                clickable
                  ? "button"
                  : toast.variant === "error"
                    ? "alert"
                    : "status"
              }
              tabIndex={clickable ? 0 : undefined}
              data-testid={`toast-${toast.variant}`}
              data-toast-action={clickable ? "true" : undefined}
              onClick={clickable ? activate : undefined}
              onKeyDown={
                clickable
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        activate();
                      }
                    }
                  : undefined
              }
            >
              <span className="toast-icon" aria-hidden="true">
                {variantIcon(toast.variant)}
              </span>
              <div className="toast-text">
                <div className="toast-title">
                  {toast.title}
                  {toast.count > 1 && (
                    <span className="toast-count" data-testid="toast-count">
                      {" "}
                      ×{toast.count}
                    </span>
                  )}
                </div>
                {toast.description && (
                  <div className="toast-desc">{toast.description}</div>
                )}
              </div>
              <button
                type="button"
                className="toast-close"
                aria-label="Dismiss notification"
                onClick={(event) => {
                  // Don't let the dismiss "X" trigger the toast's own onClick.
                  event.stopPropagation();
                  dismiss(toast.id);
                }}
              >
                <X size={14} strokeWidth={2.4} />
              </button>
            </div>
          );
        })}
        {hiddenCount > 0 && (
          <div className="toast toast-more" role="status" data-testid="toast-more">
            {t("toast.more", { count: hiddenCount })}
          </div>
        )}
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

