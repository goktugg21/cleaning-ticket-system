/**
 * Sprint 117 — shared bounded-list primitive.
 *
 * Wraps a list rendered from a SERVER collection in a scroll container
 * capped at one of three named heights (sm/md/lg), mapping onto the
 * existing app-wide scroll scale (.multi-select-list 260 / .multi-select-
 * list-tall 320 / .ew-table-scroll 420 — see index.css). Presentation
 * only: the caller owns all data/selection/filtering state and supplies
 * the rendered children (e.g. `<ul>...</ul>` or a `<table>`); this
 * component only supplies the scroll box, the overflow-only item count,
 * and the empty state.
 *
 * See CLAUDE.md #8 ("Do not render a list from a SERVER collection
 * without a bound") — this is the primitive that rule points at.
 */
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export type BoundedListSize = "sm" | "md" | "lg";

export interface BoundedListProps {
  /** Named height from the app-wide scroll scale — do not add new sizes. */
  size: BoundedListSize;
  /** The number of rows/rendered items — drives the empty state and the
   * overflow-count badge. Independent of `children`'s own DOM shape (a
   * `<table>` counts its body rows, not its header). */
  count: number;
  /** Rendered when `count === 0`. When omitted and `count === 0`, nothing
   * renders (the caller's own empty-state card copy still shows above). */
  emptyState?: ReactNode;
  /** Accessible name for the scrollable region — caller-supplied because
   * only the caller knows what the list actually contains. */
  ariaLabel: string;
  testIdPrefix: string;
  /** Extra class(es) layered onto the scroll container (e.g. "table-wrap"
   * for a <table> child that also needs its own horizontal-scroll rule). */
  className?: string;
  children: ReactNode;
}

const SIZE_CLASS: Record<BoundedListSize, string> = {
  sm: "bounded-list-sm",
  md: "bounded-list-md",
  lg: "bounded-list-lg",
};

export function BoundedList({
  size,
  count,
  emptyState,
  ariaLabel,
  testIdPrefix,
  className,
  children,
}: BoundedListProps) {
  const { t } = useTranslation("common");
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // ResizeObserver's callback always fires at least once after observe()
    // (the initial size IS the first "change" reported), and it fires
    // asynchronously — never synchronously within this effect's own body —
    // so measuring here never trips the synchronous-setState-in-effect
    // lint rule. Re-created when `count` changes (a new row can flip the
    // overflow state without the element's own size otherwise changing).
    const observer = new ResizeObserver(() => {
      setIsOverflowing(el.scrollHeight > el.clientHeight);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [count]);

  if (count === 0) {
    return emptyState !== undefined ? <>{emptyState}</> : null;
  }

  return (
    <div
      className="bounded-list-wrap"
      data-testid={`${testIdPrefix}-bounded-list`}
    >
      <div
        ref={scrollRef}
        className={`bounded-list ${SIZE_CLASS[size]}${className ? ` ${className}` : ""}`}
        role="region"
        aria-label={ariaLabel}
        tabIndex={0}
        data-testid={`${testIdPrefix}-bounded-list-scroll`}
      >
        {children}
      </div>
      {isOverflowing && (
        <div
          className="bounded-list-count"
          data-testid={`${testIdPrefix}-bounded-list-count`}
        >
          {t("bounded_list.count", { count })}
        </div>
      )}
    </div>
  );
}
