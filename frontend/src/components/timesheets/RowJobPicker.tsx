/**
 * W-HOURS4 Task 1c — "+ link a job (optional)", the per-row job picker
 * of the admin week grid.
 *
 * A row of the week grid is one (person, building) pair the operator
 * asked for. Under the person's name sits one quiet link; clicking it
 * opens a small grouped picker:
 *
 *   **This week**   that person's REAL planned jobs in THAT building
 *                   for THE SELECTED WEEK — what the caller's
 *                   `thisWeek(person, building)` returns, which the
 *                   week dialog reads from `/reports/week-assignments/`
 *                   keyed by the dialog's week, never today's;
 *   **No job — general hours**   the default, and what an untagged row
 *                   saves as;
 *   **Search other work…**   free search across open jobs in the
 *                   buildings the person may enter — the reference
 *                   system's freedom: helping on a job you were never
 *                   put on is still enterable.
 *
 * A chosen job renders as a small removable tag on the row. The row's
 * identity (which hours land where) is the GRID's business: this
 * component only reports the choice through `onChange`; the grid moves
 * the typed cells onto the retagged row.
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

/** How long the search waits after the last keystroke. */
const SEARCH_DEBOUNCE_MS = 250;

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
  /** Free search across the jobs this person may book against. */
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
  const [searchMode, setSearchMode] = useState(false);
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
      // 320 = the popover's max height plus its offset from the link.
      const flipped = below < 320 && box.top > below;
      const width = Math.max(
        280,
        Math.min(400, window.innerWidth - box.left - 16),
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
  }, [open, rect, results, searchMode, onOpenChange]);

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

  // The search, debounced. Everything here happens in the timer's
  // callback, never synchronously in the effect body.
  useEffect(() => {
    if (!open || !searchMode) return;
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
  }, [open, searchMode, query]);

  function close() {
    setOpen(false);
    setSearchMode(false);
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
      data-testid={`${testId}-option-${job.source_type}-${job.source_id ?? "none"}`}
    >
      <span>{job.title}</span>
    </button>
  );

  return (
    <div
      ref={anchorRef}
      style={{ marginTop: 2, fontWeight: 400 }}
      onKeyDown={onKeyDown}
      data-testid={testId}
    >
      {tag !== null ? (
        <span
          className="cell-tag cell-tag-muted"
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
          data-testid={`${testId}-tag`}
        >
          {tagLabel}
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
              maxHeight: 300,
              ...(rect.flipped
                ? { bottom: window.innerHeight - rect.top }
                : { top: rect.top }),
            }}
            data-testid={`${testId}-picker`}
          >
            <div style={GROUP_STYLE}>{t("hours_week_grid.job_group_week")}</div>
            {thisWeek.length === 0 ? (
              <p
                className="muted small"
                style={NOTE_STYLE}
                data-testid={`${testId}-week-empty`}
              >
                {t("hours_week_grid.job_group_week_empty")}
              </p>
            ) : (
              thisWeek.map(option)
            )}
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
            {!searchMode ? (
              <button
                type="button"
                className="chip-multiselect-option"
                onClick={() => setSearchMode(true)}
                data-testid={`${testId}-search-open`}
              >
                <span>{t("hours_week_grid.job_search")}</span>
              </button>
            ) : (
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
                {searching ? (
                  <p className="muted small" style={NOTE_STYLE}>
                    {t("hours_week_grid.job_searching")}
                  </p>
                ) : searchError ? (
                  <p className="form-error" style={NOTE_STYLE}>
                    {t("hours_week_grid.job_search_error")}
                  </p>
                ) : results !== null && results.length === 0 ? (
                  <p
                    className="muted small"
                    style={NOTE_STYLE}
                    data-testid={`${testId}-search-none`}
                  >
                    {t("hours_week_grid.job_search_none")}
                  </p>
                ) : (
                  (results ?? []).map(option)
                )}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
