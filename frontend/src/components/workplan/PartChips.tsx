import { useTranslation } from "react-i18next";

import type { WorkPlanPart } from "../../api/workPlan";
import { formatDay } from "./entryHelpers";

/**
 * W-LATE §3b — the part chips, with their state.
 *
 * One component for every place a card names its parts — the week card,
 * the late card, the day modal — so a part's colour is decided once:
 *
 *     done       strikethrough
 *     last day   orange, today is the last day of its window
 *     missed     red, "niet gedaan op <window end>", and it keeps
 *                rendering forward until it is done or deleted
 *     open       the plain grey pill it always was
 *
 * The STATE is the server's (`tickets/lateness.part_state`), not
 * re-derived here: a chip that computed its own colour from the dates
 * would be a second copy of the rule. Before phase 3 lands, parts carry
 * no window and no state, and the chip is the plain pill.
 */
export function PartChips({
  parts,
  testId,
}: {
  parts: WorkPlanPart[];
  testId: string;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <span
      className="parts-chip-row parts-chip-row-stacked"
      data-testid={`${testId}s`}
    >
      {parts.map((part) => {
        const state = part.state ?? "NONE";
        const cls =
          state === "DONE"
            ? " parts-chip-done"
            : state === "LAST_DAY"
              ? " parts-chip-last-day"
              : state === "MISSED"
                ? " parts-chip-missed"
                : "";
        const end = part.planned_end ?? part.planned_start ?? null;
        return (
          <span
            key={part.id}
            className={`parts-chip${cls}`}
            data-testid={testId}
            data-state={state}
            title={
              part.time_window_label
                ? part.time_window_label
                : undefined
            }
          >
            {part.title}
            {state === "MISSED" && end && (
              <span className="parts-chip-note">
                {t("parts.missed_on", { date: formatDay(end) })}
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}
