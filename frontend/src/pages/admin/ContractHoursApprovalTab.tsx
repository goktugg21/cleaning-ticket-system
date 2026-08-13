import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";
import { listHourSources } from "../../api/reports";
import type { HourSourceOption } from "../../api/reports";
import { hourSourceLabel } from "../../lib/hourSource";
import {
  currentIsoWeek,
  formatIsoWeek,
  isoWeekDays,
  shiftIsoWeek,
  toDateString,
  type IsoWeek,
} from "../../lib/isoWeek";

const DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

type Day = (typeof DAYS)[number];
type Status = "DRAFT" | "SAVED" | "APPROVED";

const STATUSES: Status[] = ["DRAFT", "SAVED", "APPROVED"];

interface ContractHoursRow {
  id: number;
  employee: number;
  employee_name: string;
  building: number | null;
  building_name: string | null;
  hour_type: number;
  hour_type_name: string;
  valid_from: string;
  valid_to: string | null;
  status: Status;
  is_locked: boolean;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
}

interface TimeEntry {
  id: number;
  source_type: string;
  source_id: number | null;
  employee: number;
  employee_name: string;
  building: number | null;
  building_name: string | null;
  hour_type: number;
  hour_type_name: string;
  date: string;
  hours: string;
}

/** One line in the table — either the AGREEMENT or what was WORKED. */
interface ReviewRow {
  key: string;
  source: "CONTRACT" | "ACTUAL";
  /** Sprint 174 §2 — for an ACTUAL row, WHERE the hour came from. The
   *  reviewer groups by it: "eight hours" is one fact, "six from a
   *  ticket and two from the contract" is the one they can act on. */
  sourceType: string;
  /** Sprint 179B §2 — WHICH ticket, not just "a ticket". The grouping
   *  above was by TYPE, so hours on two different tickets sat under one
   *  "Ticket" heading and were told apart only by hour type and
   *  building. The id was already part of the row KEY (`actualRows`);
   *  it simply never reached the row. */
  sourceId: number | null;
  id: number | null;
  employee: number;
  employee_name: string;
  building: number | null;
  building_name: string | null;
  hour_type_name: string;
  status: Status | null;
  days: Record<Day, number>;
  total: number;
}

/**
 * Sprint 167 §4 — the contract-hours approval screen.
 *
 * A week's agreed hours are reviewed here against what was actually
 * worked, and moved between the three states. The transition rules are
 * written down in `timesheets.models.ContractHours` — this screen only
 * offers the moves the server will accept:
 *
 *   DRAFT    -> SAVED     submit for review
 *   SAVED    -> APPROVED  agreed
 *   SAVED    -> DRAFT     send back for a correction
 *   APPROVED -> SAVED     reopen (clears the approval)
 *
 * Two things this screen refuses to fake:
 *
 * 1. **Extra work hours.** We hold no such figure today, so the tile
 *    says so instead of printing a zero that reads like a measurement.
 * 2. **The worked side is not approvable.** Actual rows come from
 *    `TimeEntry` and are shown so the reviewer sees agreed against
 *    worked in one place; they carry no checkbox and no action.
 */
export function ContractHoursApprovalTab({
  companyId,
  buildings,
  employees,
  onGoToContractHours,
}: {
  companyId: number | "";
  buildings: { id: number; name: string }[];
  employees: { id: number; name: string }[];
  /** Sprint 171 §2b — takes the operator to the tab that CREATES
   *  contract hours. With none, this screen is three empty tabs and
   *  nothing on it says the rows come from somewhere else, so it reads
   *  as a page with no function. A link beats describing a path. */
  onGoToContractHours?: () => void;
}) {
  const { t } = useTranslation("common");
  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  // Sprint 169 §3 — NULL means "nobody has chosen yet", and the tab is
  // then DERIVED from where the rows actually are. The screen opened
  // hard-coded on SAVED, which in practice is the state with the fewest
  // rows in it, so a reviewer arrived at an empty tab.
  const [chosenTab, setChosenTab] = useState<Status | null>(null);
  const [building, setBuilding] = useState<number | "">("");
  const [employee, setEmployee] = useState<number | "">("");

  const [contractRows, setContractRows] = useState<ContractHoursRow[]>([]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  /** Sprint 179B §2 — job titles for the per-source headings. */
  const [sourceOptions, setSourceOptions] = useState<HourSourceOption[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const days = useMemo(() => isoWeekDays(week), [week]);
  const monday = toDateString(days[0]);
  const sunday = toDateString(days[6]);

  /** Sprint 179B §2 — loaded once, and non-fatal: without it a heading
   *  falls back to "Ticket #41", which is a label, not a blank. This
   *  screen's own data must never depend on it. */
  useEffect(() => {
    let cancelled = false;
    listHourSources()
      .then((options) => {
        if (!cancelled) setSourceOptions(options);
      })
      .catch(() => {
        /* non-fatal: headings fall back to type + id */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filters = useMemo(
    () => ({
      company: companyId || undefined,
      building: building || undefined,
      employee: employee || undefined,
    }),
    [companyId, building, employee],
  );

  const requestKey = `${monday}:${sunday}:${JSON.stringify(filters)}:${reloadKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;

    // The entries endpoint is paginated and that pagination is a
    // contract with its other callers — so this caller pages through it
    // exhaustively rather than loosening the endpoint (Sprint 135).
    async function loadEntries(): Promise<TimeEntry[]> {
      const collected: TimeEntry[] = [];
      let url: string | null = "/timesheets/entries/";
      let params: Record<string, unknown> | undefined = {
        ...filters,
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        page_size: 200,
      };
      for (let page = 0; page < 25 && url; page += 1) {
        const response = await api.get(url, { params });
        const data = response.data as
          | { results?: TimeEntry[]; next?: string | null }
          | TimeEntry[];
        if (Array.isArray(data)) {
          collected.push(...data);
          break;
        }
        collected.push(...(data.results ?? []));
        url = data.next ? data.next.replace(/^.*\/api/, "") : null;
        params = undefined;
      }
      return collected;
    }

    Promise.all([
      // Sprint 168 §2 — the WEEK, not its Monday. `valid_on: monday`
      // asked "what was agreed on the Monday", which silently dropped
      // an agreement that starts on the Tuesday - and that is exactly
      // what happened: four rows created mid-week were invisible on the
      // approval screen for the week containing that day.
      api.get("/timesheets/contract-hours/", {
        params: {
          ...filters,
          valid_between_start: monday,
          valid_between_end: sunday,
        },
      }),
      loadEntries(),
    ])
      .then(([contract, worked]) => {
        if (cancelled) return;
        setContractRows(contract.data.results ?? contract.data);
        setEntries(worked);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });

    return () => {
      cancelled = true;
    };
  }, [filters, monday, sunday, week.isoYear, week.isoWeek, requestKey]);

  const counts = useMemo(() => {
    const out: Record<Status, number> = { DRAFT: 0, SAVED: 0, APPROVED: 0 };
    for (const row of contractRows) out[row.status] += 1;
    return out;
  }, [contractRows]);

  /** The tab in force: the operator's choice, or — before they make one
   *  — the first state that HAS rows. Derived rather than seeded through
   *  an effect (a setState in an effect body is banned), which also
   *  means the landing tab follows a reload that changes the data. */
  const tab: Status =
    chosenTab ?? STATUSES.find((status) => counts[status] > 0) ?? "DRAFT";
  const setTab = setChosenTab;

  /** Worked hours bucketed onto weekdays, per building+employee+type. */
  const actualRows = useMemo(() => {
    const byKey = new Map<string, ReviewRow>();
    for (const entry of entries) {
      // The SOURCE is part of the key: hours from a ticket and hours
      // from the contract are two facts and must not be summed into
      // one row, which is the same reasoning the worker hour report's
      // grain uses.
      const key = `a:${entry.building ?? 0}:${entry.employee}:${entry.hour_type}:${entry.source_type}:${entry.source_id ?? 0}`;
      let row = byKey.get(key);
      if (!row) {
        row = {
          key,
          source: "ACTUAL",
          sourceType: entry.source_type || "OTHER",
          sourceId: entry.source_id ?? null,
          id: null,
          employee: entry.employee,
          employee_name: entry.employee_name,
          building: entry.building,
          building_name: entry.building_name,
          hour_type_name: entry.hour_type_name,
          status: null,
          days: {
            monday: 0,
            tuesday: 0,
            wednesday: 0,
            thursday: 0,
            friday: 0,
            saturday: 0,
            sunday: 0,
          },
          total: 0,
        };
        byKey.set(key, row);
      }
      // getDay() is 0=Sunday; the grid is Monday-first.
      const index = (new Date(`${entry.date}T00:00:00`).getDay() + 6) % 7;
      const hours = Number(entry.hours) || 0;
      row.days[DAYS[index]] += hours;
      row.total += hours;
    }
    return [...byKey.values()];
  }, [entries]);

  const visibleContract = useMemo(
    () =>
      contractRows
        .filter((row) => row.status === tab)
        .map<ReviewRow>((row) => {
          const values = DAYS.reduce(
            (acc, day) => {
              acc[day] = Number(row[day]) || 0;
              return acc;
            },
            {} as Record<Day, number>,
          );
          return {
            key: `c:${row.id}`,
            source: "CONTRACT",
            sourceType: "CONTRACT",
            // The agreement is not a job: contract hours carry no
            // source pair at all (see §6 of this sprint's report).
            sourceId: null,
            id: row.id,
            employee: row.employee,
            employee_name: row.employee_name,
            building: row.building,
            building_name: row.building_name,
            hour_type_name: row.hour_type_name,
            status: row.status,
            days: values,
            total: DAYS.reduce((sum, day) => sum + values[day], 0),
          };
        }),
    [contractRows, tab],
  );

  /** Sprint 174 §2 — the worked rows, GROUPED BY SOURCE.
   *
   *  "Eight hours this week" is one fact; "six from a ticket and two
   *  from the contract" is the one a reviewer can act on. The order is
   *  the enum's, not the data's, so two weeks with different sources
   *  present still read in the same order. */
  /**
   * Sprint 179B §2 — one group per JOB, not one per KIND of job.
   *
   * Sprint 174 §2 grouped these by `source_type`, so every ticket in the
   * week landed under a single "Ticket" heading: a reviewer looking at
   * six rows could see that six were tickets and not which tickets. The
   * rows were always distinct — `actualRows` keys on `(…, source_type,
   * source_id)` — so this is a heading that said less than the data
   * behind it.
   *
   * The type order is kept as the OUTER order, so the screen still reads
   * contract, extra work, tickets, other; within a type the groups follow
   * the id, which is stable and monotonic.
   */
  const actualBySource = useMemo(() => {
    const order = ["CONTRACT", "EXTRA_WORK", "TICKET", "OTHER"];
    const groups = new Map<string, ReviewRow[]>();
    for (const row of actualRows) {
      const key = `${row.sourceType || "OTHER"}:${row.sourceId ?? ""}`;
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    return [...groups.entries()]
      .map(([key, rows]) => ({
        key,
        sourceType: rows[0].sourceType || "OTHER",
        sourceId: rows[0].sourceId,
        rows,
      }))
      .sort((a, b) => {
        const byType =
          order.indexOf(a.sourceType) - order.indexOf(b.sourceType);
        if (byType !== 0) return byType;
        return (a.sourceId ?? 0) - (b.sourceId ?? 0);
      });
  }, [actualRows]);

  /** The key `actualBySource` groups on, for a row. Written once so the
   *  heading's "is this the first row of its group" test and the group
   *  itself can never disagree. */
  const sourceGroupKey = (row: ReviewRow) =>
    `${row.sourceType || "OTHER"}:${row.sourceId ?? ""}`;

  const rows = useMemo(
    () => [...visibleContract, ...actualRows],
    [visibleContract, actualRows],
  );

  /** Every contract row for one employee in this week, in the tab's
   *  state — what "approve everything for this employee" acts on. */
  const approvableByEmployee = useMemo(() => {
    const groups = new Map<number, { name: string; ids: number[] }>();
    for (const row of visibleContract) {
      if (row.id === null) continue;
      const found = groups.get(row.employee) ?? {
        name: row.employee_name,
        ids: [],
      };
      found.ids.push(row.id);
      groups.set(row.employee, found);
    }
    return [...groups.entries()].map(([employeeId, value]) => ({
      employeeId,
      ...value,
    }));
  }, [visibleContract]);

  const contractedTotal = visibleContract.reduce((sum, r) => sum + r.total, 0);
  const actualTotal = actualRows.reduce((sum, r) => sum + r.total, 0);
  const pairs = new Set(
    rows.map((row) => `${row.building ?? 0}:${row.employee}`),
  ).size;

  /** The move this tab offers, and the one the server will accept. */
  const primary: { to: Status; label: string } | null =
    tab === "DRAFT"
      ? { to: "SAVED", label: t("contract_hours.action_submit") }
      : tab === "SAVED"
        ? { to: "APPROVED", label: t("contract_hours.action_approve") }
        : { to: "SAVED", label: t("contract_hours.action_reopen") };

  const secondary: { to: Status; label: string } | null =
    tab === "SAVED"
      ? { to: "DRAFT", label: t("contract_hours.action_send_back") }
      : null;

  async function move(ids: number[], to: Status) {
    if (ids.length === 0) return;
    setBusy(true);
    setError("");
    try {
      for (const id of ids) {
        await api.post(`/timesheets/contract-hours/${id}/status/`, {
          status: to,
        });
      }
      setSelected([]);
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const tiles = [
    {
      key: "contract",
      label: t("contract_hours.tile_contract_hours"),
      value: contractedTotal.toFixed(2),
    },
    {
      key: "extra",
      label: t("contract_hours.tile_extra_hours"),
      // Not a zero: we hold no such figure, and a zero would read as one.
      value: t("contract_hours.not_held"),
    },
    {
      key: "actual",
      label: t("contract_hours.tile_actual_hours"),
      value: actualTotal.toFixed(2),
    },
    {
      key: "pairs",
      label: t("contract_hours.tile_pairs"),
      value: String(pairs),
    },
  ];

  return (
    <div data-testid="contract-hours-approval-tab">
      {error && (
        <div className="alert-error" style={{ marginBottom: 12 }} role="alert">
          {error}
        </div>
      )}

      <div className="hours-tiles-head">
        <span className="hours-tiles-title">
          {t("contract_hours.approval_title")}
        </span>
        <div
          style={{ display: "flex", alignItems: "center", gap: 8 }}
          data-testid="approval-week-stepper"
        >
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setWeek((current) => shiftIsoWeek(current, -1))}
            data-testid="approval-week-prev"
            aria-label={t("contract_hours.prev_week")}
          >
            <ChevronLeft size={14} strokeWidth={2.5} />
          </button>
          <span
            style={{ fontWeight: 600, minWidth: 130, textAlign: "center" }}
            data-testid="approval-week-label"
          >
            {formatIsoWeek(week)}
          </span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setWeek((current) => shiftIsoWeek(current, 1))}
            data-testid="approval-week-next"
            aria-label={t("contract_hours.next_week")}
          >
            <ChevronRight size={14} strokeWidth={2.5} />
          </button>
        </div>
      </div>

      <div
        className="hours-tile-row"
        data-testid="approval-tiles"
        style={{ gridTemplateColumns: `repeat(${tiles.length}, minmax(0, 1fr))` }}
      >
        {tiles.map((tile) => (
          <div key={tile.key} className="hours-tile">
            <span className="hours-tile-label">{tile.label}</span>
            <span className="hours-tile-value">{tile.value}</span>
          </div>
        ))}
      </div>

      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("contract_hours.approval_title")}
        style={{ marginBottom: 12 }}
        data-testid="approval-status-chips"
      >
        {STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            role="tab"
            aria-selected={tab === status}
            className={`composer-toggle-btn ${tab === status ? "active" : ""}`}
            onClick={() => {
              setTab(status);
              setSelected([]);
            }}
            data-testid={`approval-status-${status}`}
          >
            {t(`contract_hours.status_${status}`)}
            <span className="mywork-chip-count">{counts[status]}</span>
          </button>
        ))}
      </div>

      {/* Sprint 170 §4 — what THIS state means and what moves a row on.
          The three tabs were legible as counts and opaque as a
          mechanism: the operator could see 3/0/1 and still not know
          what would turn a 3 into a 2. */}
      <p className="muted small" data-testid="approval-state-explainer">
        {t(`contract_hours.explain_${tab}`)}
      </p>

      {/* The owner reopened a closed WEEK and expected approval to
          change. It does not, and saying so where he looked is cheaper
          than him testing it again. */}
      <p className="muted small" data-testid="approval-week-lock-note">
        {t("contract_hours.week_lock_note")}
      </p>

      <form className="filter-bar" onSubmit={(event) => event.preventDefault()}>
        <div className="filter-field">
          <span className="filter-label">{t("building")}</span>
          <select
            className="filter-control"
            value={building}
            onChange={(e) =>
              setBuilding(e.target.value === "" ? "" : Number(e.target.value))
            }
            data-testid="approval-filter-building"
          >
            <option value="">{t("contract_hours.all_buildings")}</option>
            {buildings.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.employee")}</span>
          <select
            className="filter-control"
            value={employee}
            onChange={(e) =>
              setEmployee(e.target.value === "" ? "" : Number(e.target.value))
            }
            data-testid="approval-filter-employee"
          >
            <option value="">{t("contract_hours.all_employees")}</option>
            {employees.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void move(selected, primary.to)}
            disabled={busy || selected.length === 0}
            data-testid="approval-bulk-save"
          >
            {t("contract_hours.bulk_action", {
              action: primary.label,
              count: selected.length,
            })}
          </button>
        </div>
      </form>

      {/* Sprint 174 §2 — approve EVERYTHING for one employee this
          week. The reference has exactly this, and without it a
          reviewer with twelve rows for one worker clicks twelve times. */}
      {approvableByEmployee.length > 0 && (
        <div
          className="filter-bar"
          style={{ alignItems: "center" }}
          data-testid="approval-per-employee"
        >
          <span className="muted small">
            {t("contract_hours.per_employee_hint", { action: primary.label })}
          </span>
          {approvableByEmployee.map((group) => (
            <button
              key={group.employeeId}
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => void move(group.ids, primary.to)}
              disabled={busy}
              data-testid={`approval-employee-all-${group.employeeId}`}
            >
              {group.name} ({group.ids.length})
            </button>
          ))}
        </div>
      )}

      {loading && (
        <div className="loading-bar" style={{ margin: 0 }}>
          <div className="loading-bar-fill" />
        </div>
      )}

      <div className="table-wrap admin-list-wrap">
        <table className="data-table data-table-dense hours-week-grid-table">
          <thead>
            <tr>
              <th />
              <th>{t("building")}</th>
              <th>{t("contract_hours.employee")}</th>
              <th>{t("contract_hours.source")}</th>
              <th>{t("contract_hours.hour_type")}</th>
              {DAYS.map((day) => (
                <th key={day} className="contract-num">
                  {t(`contract_hours.day_${day}`)}
                </th>
              ))}
              <th className="contract-num">{t("contract_hours.total")}</th>
              <th>{t("contract_hours.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <Fragment key={row.key}>
              {/* Sprint 169 §3 — the two blocks are LABELLED and
                  counted, inside the one map so the row markup is not
                  copied. Without these headings the eight unchanged
                  "worked" rows sat in the same undifferentiated list as
                  the three the tab actually controls, and switching
                  tabs looked like nothing happened. */}
              {index === 0 && (
                <tr
                  className="contract-group-row"
                  data-testid="approval-section-contract"
                >
                  <td colSpan={14}>
                    <strong>
                      {t("contract_hours.section_contract", {
                        state: t(`contract_hours.status_${tab}`),
                        count: visibleContract.length,
                      })}
                    </strong>
                  </td>
                </tr>
              )}
              {visibleContract.length === 0 && index === 0 && (
                <tr data-testid="approval-empty-state">
                  <td colSpan={14} className="muted">
                    {t("contract_hours.empty_for_state", {
                      state: t(`contract_hours.status_${tab}`),
                    })}{" "}
                    {t(`contract_hours.empty_hint_${tab}`)}
                    {/* Sprint 171 §2b — the link belongs HERE too, not
                        only on the all-empty case. Measured: with time
                        entries present but no contract hours, `rows` is
                        non-empty, so the all-empty branch never fired
                        and the operator got prose with no way out. "No
                        contract hours" is the state that needs the
                        link, whether or not anybody logged hours. */}
                    {contractRows.length === 0 && onGoToContractHours && (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        style={{ marginLeft: 8 }}
                        onClick={onGoToContractHours}
                        data-testid="approval-go-to-contract-hours"
                      >
                        {t("contract_hours.go_create")}
                      </button>
                    )}
                  </td>
                </tr>
              )}
              {/* Sprint 174 §2 — one sub-heading per SOURCE, so the
                  reviewer sees where the week's hours came from rather
                  than one undifferentiated block. */}
              {row.source === "ACTUAL" &&
                actualBySource.some(
                  (group) => group.rows[0]?.key === row.key,
                ) && (
                  <tr
                    className="contract-group-row"
                    data-testid={`approval-source-group-${sourceGroupKey(row)}`}
                  >
                    <td colSpan={14}>
                      {/* Sprint 179B §2 — the JOB, where the kind of job
                          used to be. "Ticket" three times over told a
                          reviewer nothing they could act on. */}
                      <strong>
                        {hourSourceLabel(
                          row.sourceType,
                          row.sourceId,
                          sourceOptions,
                          t,
                          t("hour_source.OTHER"),
                        )}
                      </strong>{" "}
                      <span className="muted small">
                        {t("contract_hours.source_group_count", {
                          count:
                            actualBySource.find(
                              (group) => group.key === sourceGroupKey(row),
                            )?.rows.length ?? 0,
                        })}
                      </span>
                    </td>
                  </tr>
                )}
              {row.source === "ACTUAL" &&
                index === visibleContract.length && (
                  <tr
                    className="contract-group-row"
                    data-testid="approval-section-actual"
                  >
                    <td colSpan={14}>
                      <strong>
                        {t("contract_hours.section_actual", {
                          count: actualRows.length,
                        })}
                      </strong>{" "}
                      <span className="muted small">
                        {t("contract_hours.not_approvable_why")}
                      </span>
                    </td>
                  </tr>
                )}
              <tr
                className={
                  row.source === "ACTUAL" ? "hours-comparison-employee-row" : ""
                }
                data-testid={`approval-row-${row.key}`}
              >
                <td className="td-select">
                  {row.source === "CONTRACT" && row.id !== null && (
                    <input
                      type="checkbox"
                      checked={selected.includes(row.id)}
                      onChange={(event) => {
                        const id = row.id as number;
                        setSelected((current) =>
                          event.target.checked
                            ? [...current, id]
                            : current.filter((value) => value !== id),
                        );
                      }}
                      aria-label={`${row.employee_name} ${row.hour_type_name}`}
                      data-testid={`approval-select-${row.id}`}
                    />
                  )}
                </td>
                <td>
                  {row.building_name ?? (
                    <span className="muted-empty">
                      {t("contract_hours.no_building")}
                    </span>
                  )}
                </td>
                <td className="td-subject">{row.employee_name}</td>
                <td>
                  <span
                    className={`cell-tag ${
                      row.source === "CONTRACT"
                        ? "cell-tag-normal"
                        : "cell-tag-muted"
                    }`}
                  >
                    {t(`contract_hours.source_${row.source}`)}
                  </span>
                </td>
                <td>{row.hour_type_name}</td>
                {DAYS.map((day) => (
                  <td key={day} className="contract-num">
                    {row.days[day].toFixed(2)}
                  </td>
                ))}
                <td className="contract-num">
                  <strong>{row.total.toFixed(2)}</strong>
                </td>
                <td>
                  {row.source === "CONTRACT" && row.id !== null ? (
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => void move([row.id as number], primary.to)}
                        disabled={busy}
                        data-testid={`approval-primary-${row.id}`}
                      >
                        {primary.label}
                      </button>
                      {secondary && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() =>
                            void move([row.id as number], secondary.to)
                          }
                          disabled={busy}
                          data-testid={`approval-secondary-${row.id}`}
                        >
                          {secondary.label}
                        </button>
                      )}
                    </div>
                  ) : (
                    /* Sprint 171 §2a — a DASH, not a sentence.
                       Sprint 170 put the reason on every row, inside
                       the narrow Actions column, so it wrapped into a
                       tall block of words down the right edge and each
                       row grew to several hundred pixels. That one
                       choice is most of why the screen looked broken.
                       The reason is a fact about the SECTION and is
                       said once in its header; repeating it per row was
                       noise with a layout cost. */
                    <span
                      className="muted-empty"
                      title={t("contract_hours.not_approvable_why")}
                    >
                      —
                    </span>
                  )}
                </td>
              </tr>
              </Fragment>
            ))}
            {/* The all-empty case: no contract rows AND no worked rows,
                so neither heading above ever rendered. */}
            {!loading && rows.length === 0 && (
              <tr data-testid="approval-empty-state">
                <td colSpan={14} className="muted">
                  {t("contract_hours.nothing_this_week")}{" "}
                  {onGoToContractHours && (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      style={{ marginLeft: 8 }}
                      onClick={onGoToContractHours}
                      data-testid="approval-go-to-contract-hours"
                    >
                      {t("contract_hours.go_create")}
                    </button>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
