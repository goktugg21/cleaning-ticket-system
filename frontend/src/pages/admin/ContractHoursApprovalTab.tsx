import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";
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
}: {
  companyId: number | "";
  buildings: { id: number; name: string }[];
  employees: { id: number; name: string }[];
}) {
  const { t } = useTranslation("common");
  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  const [tab, setTab] = useState<Status>("SAVED");
  const [building, setBuilding] = useState<number | "">("");
  const [employee, setEmployee] = useState<number | "">("");

  const [contractRows, setContractRows] = useState<ContractHoursRow[]>([]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const days = useMemo(() => isoWeekDays(week), [week]);
  const monday = toDateString(days[0]);

  const filters = useMemo(
    () => ({
      company: companyId || undefined,
      building: building || undefined,
      employee: employee || undefined,
    }),
    [companyId, building, employee],
  );

  const requestKey = `${monday}:${JSON.stringify(filters)}:${reloadKey}`;
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
      api.get("/timesheets/contract-hours/", {
        params: { ...filters, valid_on: monday },
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
  }, [filters, monday, week.isoYear, week.isoWeek, requestKey]);

  const counts = useMemo(() => {
    const out: Record<Status, number> = { DRAFT: 0, SAVED: 0, APPROVED: 0 };
    for (const row of contractRows) out[row.status] += 1;
    return out;
  }, [contractRows]);

  /** Worked hours bucketed onto weekdays, per building+employee+type. */
  const actualRows = useMemo(() => {
    const byKey = new Map<string, ReviewRow>();
    for (const entry of entries) {
      const key = `a:${entry.building ?? 0}:${entry.employee}:${entry.hour_type}`;
      let row = byKey.get(key);
      if (!row) {
        row = {
          key,
          source: "ACTUAL",
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

  const rows = useMemo(
    () => [...visibleContract, ...actualRows],
    [visibleContract, actualRows],
  );

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
            {rows.map((row) => (
              <tr
                key={row.key}
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
                    <span className="muted-empty">
                      {t("contract_hours.not_approvable")}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={14} className="muted">
                  {t("contract_hours.approval_empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
