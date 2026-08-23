/**
 * W23 — the year×week planning grid, read + navigate.
 *
 * One row per contract line of the active revision, one column per ISO
 * week of the year, a filled cell = the linked recurring job has
 * occurrences that week (tinted by the week's dominant status). The
 * row tail counts performances against `frequency_per_year` (W20).
 *
 * THE GRID NEVER EDITS. A cell (or the row name) navigates to the
 * linked recurring job's page, where the calendar's idempotent
 * per-date skip/add/clear actions already live — one owner per fact,
 * and no second planner.
 *
 * Horizontal space law: 52 columns do not fit 1366px, so the grid
 * scrolls INSIDE `.contract-planning-scroll` (its own overflow-x with
 * the scrollbar as the visible affordance) and the page body never
 * scrolls sideways. Styles live in `styles/contract-planning.css` —
 * index.css is another wave's file.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getContractPlanning } from "../../api/contracts";
import type { ContractPlanning } from "../../api/contracts.types";
import "../../styles/contract-planning.css";

/** ISO-8601: the year's last week is the week of 28 December. */
function isoWeeksInYear(year: number): number {
  const dec28 = new Date(Date.UTC(year, 11, 28));
  const day = dec28.getUTCDay() || 7;
  dec28.setUTCDate(dec28.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(dec28.getUTCFullYear(), 0, 1));
  return Math.ceil(
    ((dec28.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7,
  );
}

export function ContractPlanningGrid({ contractId }: { contractId: number }) {
  const { t } = useTranslation("contracts");
  const navigate = useNavigate();
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [planning, setPlanning] = useState<ContractPlanning | null>(null);

  useEffect(() => {
    let cancelled = false;
    getContractPlanning(contractId, year)
      .then((data) => {
        if (!cancelled) setPlanning(data);
      })
      .catch(() => {
        if (!cancelled) setPlanning(null);
      });
    return () => {
      cancelled = true;
    };
  }, [contractId, year]);

  const weekCount = isoWeeksInYear(year);
  const weekNumbers = Array.from({ length: weekCount }, (_, i) => i + 1);

  return (
    <div data-testid="contract-planning-grid">
      <div className="contract-planning-yearbar">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setYear((y) => y - 1)}
          aria-label={t("planning.prev_year")}
          data-testid="contract-planning-prev-year"
        >
          ‹
        </button>
        <span
          className="contract-planning-year"
          data-testid="contract-planning-year"
        >
          {year}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setYear((y) => y + 1)}
          aria-label={t("planning.next_year")}
          data-testid="contract-planning-next-year"
        >
          ›
        </button>
      </div>
      <div className="contract-planning-scroll" data-testid="contract-planning-scroll">
        <table className="contract-planning-table">
          <thead>
            <tr>
              <th className="contract-planning-name-col" />
              {weekNumbers.map((week) => (
                <th key={week} className="contract-planning-week-head">
                  {week}
                </th>
              ))}
              <th className="contract-planning-tail-head">
                {t("planning.tail_head")}
              </th>
            </tr>
          </thead>
          <tbody>
            {(planning?.lines ?? []).map((line) => {
              const byWeek = new Map(line.weeks.map((w) => [w.week, w]));
              const rowJob = line.job_ids[0];
              return (
                <tr key={line.line_id} data-testid={`contract-planning-row-${line.line_id}`}>
                  <th
                    scope="row"
                    className={
                      "contract-planning-name-col" +
                      (rowJob !== undefined
                        ? " contract-planning-name-link"
                        : "")
                    }
                    onClick={
                      rowJob !== undefined
                        ? () => navigate(`/planned-work/${rowJob}`)
                        : undefined
                    }
                  >
                    {line.name}
                  </th>
                  {weekNumbers.map((week) => {
                    const cell = byWeek.get(week);
                    return (
                      <td
                        key={week}
                        className="contract-planning-cell"
                        data-status={cell?.status}
                        data-testid={
                          cell
                            ? `contract-planning-cell-${line.line_id}-${week}`
                            : undefined
                        }
                        title={cell ? `${year} W${week}` : undefined}
                        onClick={
                          cell
                            ? () => navigate(`/planned-work/${cell.job_id}`)
                            : undefined
                        }
                      >
                        {cell ? (cell.count > 1 ? cell.count : "") : ""}
                      </td>
                    );
                  })}
                  <td
                    className="contract-planning-tail"
                    data-testid={`contract-planning-tail-${line.line_id}`}
                  >
                    {line.planned_count}/{line.frequency_per_year ?? "—"}
                  </td>
                </tr>
              );
            })}
            {(planning?.lines ?? []).length === 0 && (
              <tr>
                <th scope="row" className="contract-planning-name-col">
                  —
                </th>
                <td
                  className="contract-planning-cell"
                  colSpan={weekCount + 1}
                />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
