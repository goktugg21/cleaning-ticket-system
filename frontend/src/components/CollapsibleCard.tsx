// RF-14 — collapsible section card for the Extra Work detail's long
// sections (Requested services / Pricing proposal).
//
// A `.card` whose body mounts/unmounts behind a header toggle. The
// header carries the section title plus a compact meta line (item count
// + key total) so a collapsed card still answers "how much is in here".
// The parent decides the DEFAULT state once (open while the section
// still needs action, collapsed when it is historical); after mount the
// toggle is owned locally — there is no prop-driven resync, so key the
// card by record id when the same route can show different records.
// `headerExtra` renders as a sibling of the toggle button, never inside
// it (interactive-inside-interactive is invalid HTML).
import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export function CollapsibleCard({
  title,
  meta,
  defaultOpen,
  testId,
  headerExtra,
  persistKey,
  children,
}: {
  title: string;
  meta?: ReactNode;
  defaultOpen: boolean;
  testId?: string;
  headerExtra?: ReactNode;
  // RF-17 — optional sessionStorage key: the collapse state survives
  // navigation within the tab session. Omitted = per-mount state only.
  persistKey?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(() => {
    if (persistKey) {
      const stored = sessionStorage.getItem(persistKey);
      if (stored !== null) return stored === "1";
    }
    return defaultOpen;
  });
  const toggle = () =>
    setOpen((o) => {
      const next = !o;
      if (persistKey) sessionStorage.setItem(persistKey, next ? "1" : "0");
      return next;
    });
  return (
    <section
      className={
        open
          ? "card collapsible-card"
          : "card collapsible-card collapsible-card-closed"
      }
      data-testid={testId}
      data-open={open ? "true" : "false"}
    >
      <div className="collapsible-card-head">
        <button
          type="button"
          className="collapsible-card-toggle"
          onClick={toggle}
          aria-expanded={open}
          data-testid={testId ? `${testId}-toggle` : undefined}
        >
          <ChevronDown
            size={16}
            strokeWidth={2.4}
            className="collapsible-card-chevron"
            aria-hidden="true"
          />
          <span className="collapsible-card-title">{title}</span>
          {meta != null && (
            <span className="collapsible-card-meta">{meta}</span>
          )}
        </button>
        {headerExtra}
      </div>
      {open && <div className="collapsible-card-body">{children}</div>}
    </section>
  );
}
