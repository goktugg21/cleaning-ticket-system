/**
 * W-HOURS4 Task 1c — "+ link a job (optional)", the per-row job picker
 * of the admin week grid.
 *
 * A row of the week grid is one (person, building) pair the operator
 * asked for. Under the person's name sits one quiet link; clicking it
 * opens a small picker with the SEARCH ON TOP (W-HOURS5 Task 7) and,
 * under it:
 *
 *   **No job — general hours**   the default, and what an untagged row
 *                   saves as;
 *   **This week**   that person's REAL planned jobs in THAT building
 *                   for THE SELECTED WEEK — what the caller's
 *                   `thisWeek(person, building)` returns, which the
 *                   week dialog reads from `/reports/week-assignments/`
 *                   keyed by the dialog's week, never today's;
 *   **Other work**  what the free search finds beyond this week, in the
 *                   buildings the person may enter — the reference
 *                   system's freedom: helping on a job you were never
 *                   put on is still enterable.
 *
 * The search filters LIVE, by code and by title: "TCK-373", a bare
 * "373" and "final test" all find TCK-2026-000373 — final test. "This
 * week" matches come first, then other jobs. There is no separate
 * search row any more; the box at the top is the search.
 *
 * A chosen job renders as a small removable tag on the row — clipped
 * with an ellipsis inside the person's cell and carrying the full title
 * as a tooltip (W-HOURS5 Task 5), so a long title never pushes the
 * building column. The row's identity (which hours land where) is the
 * GRID's business: this component only reports the choice through
 * `onChange`; the grid moves the typed cells onto the retagged row.
 *
 * ## Portalled, like `ChipMultiSelect`'s list
 *
 * The grid scrolls sideways inside `.hours-week-table-wrap`
 * (`overflow-x: auto`), which clips anything absolutely positioned
 * inside a cell. So the popover is drawn on `document.body` at the
 * link's viewport rect, flips above when there is no room below, and
 * reports its bottom edge through `onOpenChange` so a containing modal
 * can grow to hold it (`usePickerReserve`). Same shape, same reasons,
 * same CSS classes as the chip list, so the two read as one control
 * family.
 *
 * Escape closes the popover and STOPS there — without the
 * `stopPropagation` the modal's own window listener would close the
 * whole dialog under the operator's hands (the bug ChipMultiSelect
 * found by driving it).
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { HourSourceOption } from "../../api/reports";

/** One job as the grid stores it on a row. */
export interface RowJobSource {
  source_type: string;
  source_id: number | null;
}

const GROUP_STYLE = {
  padding: "6px 8px 2px",
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "var(--text-muted)",
} as const;

const NOTE_STYLE = { margin: 0, padding: "4px 8px 6px" } as const;

/** Task 5 — the tag's label is clipped inside the person cell. */
const TAG_LABEL_STYLE = {
  display: "inline-block",
  maxWidth: "18ch",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  verticalAlign: "bottom",
} as const;

/** How long the search waits after the last keystroke. */
const SEARCH_DEBOUNCE_MS = 250;

/**
 * Task 7 — does this job answer the query?
 *
 * By TITLE (case-insensitive substring — "final test") and by CODE:
 * the digits of the query ("TCK-373" -> "373", "373" -> "373") match
 * the job's id or any run of digits in its title, so the ticket number
 * "TCK-2026-000373" is found by its short form. An empty query matches
 * everything.
 */
function jobMatches(job: HourSourceOption, query: string): boolean {
  const wanted = query.trim().toLowerCase();
  if (wanted === "") return true;
  const title = job.title.toLowerCase();
  if (title.includes(wanted)) return true;
  const digits = wanted.replace(/\D/g, "");
  if (digits === "") return false;
  if (job.source_id !== null && String(job.source_id) === digits) return true;
  // "000373" contains "373"; so does "2026-000373". Match the digit run.
  return title.replace(/\D/g, " ").split(" ").some((run) => run.includes(digits));
}

export function RowJobPicker({
  tag,
  tagLabel,
  thisWeek,
  search,
  onChange,
  onOpenChange,
  disabled,
  ariaLabel,
  testId,
}: {
  /** The row's current job, or `null` for general hours. */
  tag: RowJobSource | null;
  /** What the tag reads as (the caller resolves titles). */
  tagLabel: string;
  /** This person's planned jobs in this row's building this week. */
  thisWeek: HourSourceOption[];
  /** Free search across the jobs this person may book against. The
   *  caller narrows to the person's buildings; this component applies
   *  `jobMatches` on top, so a code the server cannot search by ("TCK-
   *  373") still finds its job among the person's own. */
  search: (query: string) => Promise<HourSourceOption[]>;
  onChange: (next: RowJobSource | null) => void;
  /** Reports the open popover's bottom edge (viewport px); `null` when
   *  it closes. See `usePickerReserve`. */
  onOpenChange?: (listBottom: number | null) => void;
  disabled?: boolean;
  ariaLabel: string;
  testId: string;
}) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HourSourceOption[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<{
    left: number;
    top: number;
    width: number;
    flipped: boolean;
  } | null>(null);

  // Measured in a LAYOUT effect so the popover is in place before the
  // browser paints — the ChipMultiSelect shape. `rect` is deliberately
  // not cleared on close (no synchronous setState in an effect body);
  // a stale rect costs nothing because the popover renders only while
  // `open`.
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const box = anchor.getBoundingClientRect();
      const below = window.innerHeight - box.bottom;
      // 340 = the popover's max height plus its offset from the link.
      const flipped = below < 340 && box.top > below;
      const width = Math.max(
        300,
        Math.min(420, window.innerWidth - box.left - 16),
      );
      setRect({
        left: box.left,
        top: flipped ? box.top - 4 : box.bottom + 4,
        width,
        flipped,
      });
    };
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  // Report where the popover ends once it has been laid out.
  useEffect(() => {
    if (!onOpenChange) return;
    if (!open || !rect) {
      onOpenChange(null);
      return;
    }
    const node = popRef.current;
    onOpenChange(node ? node.getBoundingClientRect().bottom : null);
  }, [open, rect, results, query, onOpenChange]);

  // Close on a click outside, bound only while open.
  useEffect(() => {
    if (!open) return;
    const onDocDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (anchorRef.current?.contains(target)) return;
      if (popRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, [open]);

  // The caller hands `search` over as a fresh arrow on every render of
  // the grid; read through a ref (updated in its own effect, never
  // during render) so a parent re-render does not cancel and restart
  // the search that is in flight.
  const searchRef = useRef(search);
  useEffect(() => {
    searchRef.current = search;
  }, [search]);

  // The "other work" search, debounced. Everything here happens in the
  // timer's callback, never synchronously in the effect body.
  useEffect(() => {
    if (!open) return;
    const wanted = query.trim();
    if (wanted === "") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSearching(true);
      setSearchError(false);
      searchRef
        .current(wanted)
        .then((found) => {
          if (cancelled) return;
          setResults(found);
        })
        .catch(() => {
          if (cancelled) return;
          setResults(null);
          setSearchError(true);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, query]);

  function close() {
    setOpen(false);
    setQuery("");
    setResults(null);
    setSearchError(false);
  }

  function pick(job: HourSourceOption | null) {
    onChange(job ? { source_type: job.source_type, source_id: job.source_id } : null);
    close();
  }

  const isCurrent = (job: HourSourceOption) =>
    tag !== null &&
    tag.source_type === job.source_type &&
    tag.source_id === job.source_id;

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      event.preventDefault();
      close();
    }
  };

  const option = (job: HourSourceOption) => (
    <button
      key={`${job.source_type}:${job.source_id ?? ""}`}
      type="button"
      role="option"
      aria-selected={isCurrent(job)}
      className={`chip-multiselect-option${isCurrent(job) ? " is-selected" : ""}`}
      onClick={() => pick(job)}
      title={job.title}
      data-testid={`${testId}-option-${job.source_type}-${job.source_id ?? "none"}`}
    >
      <span style={TAG_LABEL_STYLE}>{job.title}</span>
    </button>
  );

  // Task 7 — "This week" matches FIRST, then the other work the search
  // found that is not already in this week's list.
  const weekMatches = thisWeek.filter((job) => jobMatches(job, query));
  const weekKeys = new Set(
    thisWeek.map((job) => `${job.source_type}:${job.source_id ?? ""}`),
  );
  const otherMatches = (results ?? []).filter(
    (job) =>
      jobMatches(job, query) &&
      !weekKeys.has(`${job.source_type}:${job.source_id ?? ""}`),
  );
  const hasQuery = query.trim() !== "";

  return (
    <div
      ref={anchorRef}
      style={{ marginTop: 2, fontWeight: 400, maxWidth: "100%" }}
      onKeyDown={onKeyDown}
      data-testid={testId}
    >
      {tag !== null ? (
        <span
          className="cell-tag cell-tag-muted"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            maxWidth: "100%",
          }}
          title={tagLabel}
          data-testid={`${testId}-tag`}
        >
          <span style={TAG_LABEL_STYLE}>{tagLabel}</span>
          <button
            type="button"
            className="chip-multiselect-remove"
            aria-label={t("hours_week_grid.remove_job", { job: tagLabel })}
            onClick={() => onChange(null)}
            disabled={disabled}
            data-testid={`${testId}-remove`}
          >
            &times;
          </button>
        </span>
      ) : (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ padding: "0 2px", fontSize: 11.5, fontWeight: 500 }}
          onClick={() => setOpen(true)}
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={ariaLabel}
          data-testid={`${testId}-link`}
        >
          {t("hours_week_grid.link_job")}
        </button>
      )}

      {open &&
        rect &&
        createPortal(
          <div
            ref={popRef}
            className="chip-multiselect-list chip-multiselect-list-floating"
            role="listbox"
            aria-label={ariaLabel}
            onKeyDown={onKeyDown}
            style={{
              left: rect.left,
              width: rect.width,
              maxHeight: 320,
              ...(rect.flipped
                ? { bottom: window.innerHeight - rect.top }
                : { top: rect.top }),
            }}
            data-testid={`${testId}-picker`}
          >
            {/* Task 7 — the search, on top, live. */}
            <div style={{ padding: "4px 4px 2px" }}>
              <input
                className="field-input"
                type="search"
                autoFocus
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  if (event.target.value.trim() === "") {
                    setResults(null);
                    setSearchError(false);
                  }
                }}
                placeholder={t("hours_week_grid.job_search_placeholder")}
                aria-label={t("hours_week_grid.job_search")}
                data-testid={`${testId}-search`}
              />
            </div>
            <button
              type="button"
              role="option"
              aria-selected={tag === null}
              className={`chip-multiselect-option${tag === null ? " is-selected" : ""}`}
              onClick={() => pick(null)}
              data-testid={`${testId}-general`}
            >
              <span>{t("hours_week_grid.job_general")}</span>
            </button>
            <div style={GROUP_STYLE}>{t("hours_week_grid.job_group_week")}</div>
            {weekMatches.length === 0 ? (
              <p
                className="muted small"
                style={NOTE_STYLE}
                data-testid={`${testId}-week-empty`}
              >
                {hasQuery
                  ? t("hours_week_grid.job_group_week_no_match")
                  : t("hours_week_grid.job_group_week_empty")}
              </p>
            ) : (
              weekMatches.map(option)
            )}
            {hasQuery && (
              <>
                <div style={GROUP_STYLE}>
                  {t("hours_week_grid.job_group_other")}
                </div>
                {searching ? (
                  <p className="muted small" style={NOTE_STYLE}>
                    {t("hours_week_grid.job_searching")}
                  </p>
                ) : searchError ? (
                  <p className="form-error" style={NOTE_STYLE}>
                    {t("hours_week_grid.job_search_error")}
                  </p>
                ) : otherMatches.length === 0 ? (
                  <p
                    className="muted small"
                    style={NOTE_STYLE}
                    data-testid={`${testId}-search-none`}
                  >
                    {t("hours_week_grid.job_search_none")}
                  </p>
                ) : (
                  otherMatches.map(option)
                )}
              </>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
