import { ChevronDown } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

/**
 * P-10 A3 — THE PAGE IS THE BOARD; THE ZONES FOLD ABOVE IT.
 *
 * Everything above the week board is a STRIP: one row, full width, a
 * native `<details>` closed by default, a left border in the zone's
 * colour, the count as a pill, the title, one summary sentence and a
 * chevron. Open, the body holds the zone's rows (capped by the caller
 * at eight, with "Show all N"). The open/closed state is remembered per
 * strip in localStorage, so a manager who works from the check strip
 * finds it open tomorrow. A strip with count 0 is not rendered at all
 * (§D.6 rule 13) — the caller decides that, not this component, so a
 * count of 0 never renders a closed empty row by accident.
 *
 * Colours, one each (the mockup's tokens): Not planned yet AMBER ·
 * Waiting for a manager's check TEAL · Waiting for the customer VIOLET
 * · Stuck RED. On hold keeps its grey fold under the board.
 */
export type StripTone = "amber" | "teal" | "violet" | "red";

const STORAGE_PREFIX = "agenda.strip.";

function readOpen(id: string): boolean {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + id) === "1";
  } catch {
    return false;
  }
}

function writeOpen(id: string, open: boolean) {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + id, open ? "1" : "0");
  } catch {
    // A browser that blocks storage simply forgets the fold.
  }
}

export function ZoneStrip({
  id,
  tone,
  count,
  title,
  summary,
  actions,
  children,
  testId,
}: {
  /** The localStorage key suffix; stable across sessions. */
  id: string;
  tone: StripTone;
  count: number;
  title: string;
  summary: string;
  /** Rendered at the top of the open body (Select, Show all). */
  actions?: ReactNode;
  children: ReactNode;
  testId: string;
}) {
  const [open, setOpen] = useState(() => readOpen(id));
  return (
    <details
      className={`wp-strip-zone wp-strip-${tone}`}
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        if (next !== open) {
          setOpen(next);
          writeOpen(id, next);
        }
      }}
      data-testid={testId}
      data-count={count}
      data-open={open ? "1" : "0"}
    >
      <summary className="wp-strip-head" data-testid={`${testId}-toggle`}>
        <span className="wp-strip-pill" data-testid={`${testId}-count`}>
          {count}
        </span>
        <span className="wp-strip-title" data-testid={`${testId}-title`}>
          {title}
        </span>
        <span className="wp-strip-summary" data-testid={`${testId}-summary`}>
          {summary}
        </span>
        <ChevronDown size={16} strokeWidth={2.4} className="wp-strip-chevron" aria-hidden="true" />
      </summary>
      <div className="wp-strip-body">
        {actions && <div className="wp-strip-actions">{actions}</div>}
        {children}
      </div>
    </details>
  );
}
