import { useTranslation } from "react-i18next";

import type { WorkPlanCounts } from "../../api/workPlan";
import { CHIPS, STRIP_KEYS } from "./chips";
import type { ChipKey } from "./chips";

/**
 * Sprint 183 §4 — the summary strip.
 *
 * The reference opens the page with a row of counted chips —
 * `Total 32 · ! Overdue 31 · New 1 · In progress 0 · Completed 0` — and
 * the count is the point: it is the first thing that tells an operator
 * whether this week needs them.
 *
 * Three things kept from ours, deliberately:
 *
 *   1. Every number is the SERVER's, over the whole scope. Counting in
 *      the browser would count whatever the browser had fetched, and a
 *      bounded list makes that a lie that looks authoritative.
 *   2. The chip FILTERS when clicked. The reference's chips appear to be
 *      read-only badges with a separate Status dropdown beside them;
 *      that is two controls for one question, and this app already
 *      settled the question — `.status-tile` on the ticket list and the
 *      Extra Work list is a count you can click. Ours is that control.
 *   3. Zero-count chips stay. A chip that vanishes when it hits zero
 *      makes the strip's own shape change under the reader, and "0
 *      overdue" is information somebody came here for.
 *
 * One chip is not a bucket: OVERDUE is a warning, and it is tinted only
 * while it is non-zero and not itself the active filter.
 */
export function WorkPlanStrip({
  counts,
  active,
  onChange,
}: {
  counts: WorkPlanCounts | null;
  active: ChipKey;
  onChange: (key: ChipKey) => void;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <div className="wp-strip" data-testid="agenda-chips">
      {CHIPS.filter((chip) => STRIP_KEYS.includes(chip.key)).map((chip) => {
        const value = counts ? chip.count(counts) : -1;
        const isActive = chip.key === active;
        const warn = chip.warn && value > 0;
        return (
          <button
            key={chip.label}
            type="button"
            aria-pressed={isActive}
            className={[
              "status-tile",
              isActive ? "status-tile-active" : "",
              warn ? "status-tile-warn" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            // The active chip clears; every other chip selects. One
            // control, and the × says which of the two this click is.
            onClick={() => onChange(isActive ? "" : chip.key)}
            data-testid={`agenda-chip-${chip.key || "total"}`}
          >
            <span className="status-tile-label">
              {t(`agenda.${chip.label}`)}
              {isActive && chip.key !== "" && (
                <span className="status-tile-clear" aria-hidden="true">
                  ×
                </span>
              )}
            </span>
            {/* -1 is "no answer yet" and renders an em dash, never a 0
                that the reader would act on. */}
            <span className="status-tile-count">{value >= 0 ? value : "—"}</span>
          </button>
        );
      })}
    </div>
  );
}
