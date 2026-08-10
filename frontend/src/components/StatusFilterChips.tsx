/**
 * Sprint 158 §2 — a list opens on what needs attention, not on
 * everything ever created.
 *
 * The owner, correctly: *when you were told to simplify, you should have
 * thought of this.* An operator opening Extra Work or Tickets wants the
 * rows nobody has touched yet.
 *
 * Three properties, and all three matter equally:
 *
 *  1. **A default filter on first load** — the genuinely-untouched
 *     status (`REQUESTED` for extra work, `OPEN` for tickets).
 *  2. **Every other status stays visible, as a chip, with its count.**
 *     Nothing is hidden behind a disclosure: `## NEXT` item 19 and the
 *     owner's standing instruction both forbid it, and a count you can
 *     see is also how you notice there is work in a status you were not
 *     looking at.
 *  3. **The default is VISIBLE and clearable in one click.** A silent
 *     default filter that looks like an empty system is worse than
 *     showing everything — the operator concludes the data is gone. So
 *     the active chip is marked, a line says a filter is on, and "All"
 *     is always one click away.
 *
 * The counts come from the FULL set, not the filtered one, or every
 * chip but the active one would read zero.
 */
import { useTranslation } from "react-i18next";

export interface StatusChip {
  /** "" is the all-statuses chip. */
  value: string;
  label: string;
  count: number;
}

export function StatusFilterChips({
  chips,
  active,
  onChange,
  totalCount,
  testIdPrefix,
}: {
  chips: StatusChip[];
  active: string;
  onChange: (value: string) => void;
  /** How many rows exist in total, for the "showing N of M" line. */
  totalCount: number;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  const activeChip = chips.find((chip) => chip.value === active);
  const isFiltered = active !== "";

  return (
    <div className="status-chip-bar" data-testid={`${testIdPrefix}-chips`}>
      <div className="status-chip-row">
        <button
          type="button"
          className={
            active === ""
              ? "status-chip status-chip-active"
              : "status-chip"
          }
          aria-pressed={active === ""}
          onClick={() => onChange("")}
          data-testid={`${testIdPrefix}-chip-all`}
        >
          <span className="status-chip-label">{t("status_chips.all")}</span>
          {totalCount >= 0 && (
            <span className="status-chip-count">{totalCount}</span>
          )}
        </button>
        {chips.map((chip) => (
          <button
            key={chip.value}
            type="button"
            className={
              chip.value === active
                ? "status-chip status-chip-active"
                : "status-chip"
            }
            aria-pressed={chip.value === active}
            onClick={() => onChange(chip.value)}
            data-testid={`${testIdPrefix}-chip-${chip.value}`}
          >
            <span className="status-chip-label">{chip.label}</span>
            {/* A count of -1 means "this list cannot know" — a
                server-paginated list only holds the page it is looking
                at. No number is better than a wrong one. */}
            {chip.count >= 0 && (
              <span className="status-chip-count">{chip.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* The visible, clearable statement of the default. Without this
          an operator who opens the page on a quiet week sees a short
          list and concludes the system lost their data. */}
      {isFiltered && (
        <div className="status-chip-notice" data-testid={`${testIdPrefix}-notice`}>
          <span>
            {activeChip && activeChip.count >= 0
              ? t("status_chips.filtered_notice", {
                  status: activeChip.label,
                  shown: activeChip.count,
                  total: totalCount,
                })
              : t("status_chips.filtered_notice_simple", {
                  status: activeChip?.label ?? active,
                })}
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onChange("")}
            data-testid={`${testIdPrefix}-clear`}
          >
            {t("status_chips.show_all")}
          </button>
        </div>
      )}
    </div>
  );
}
