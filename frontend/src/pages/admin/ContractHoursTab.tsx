import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";
import { EditModeToggle } from "../../components/EditModeToggle";
import { useEditMode } from "../../lib/useEditMode";

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
  status: "DRAFT" | "SAVED" | "APPROVED";
  is_locked: boolean;
  weekly_total: string;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
}

/**
 * Sprint 167 §3 — the Contract hours tab.
 *
 * The counterpart to Entries: Entries records hours WORKED, this
 * records the standing agreement — this worker is contracted for N
 * hours at this building, per weekday, from a date.
 *
 * The whole table is inline-editable behind ONE Edit gate with ONE
 * Save, the pattern the Entries tab already uses, rather than a row of
 * per-row save buttons.
 *
 * **An APPROVED row is not editable**, and the UI says so rather than
 * letting the operator type into a cell the server will refuse: the
 * inputs are disabled and the status chip explains why. Changing an
 * approved agreement is a NEW row from a new valid-from — the same
 * discipline the contract revisions use.
 */
export function ContractHoursTab({
  companyId,
  buildings,
  employees,
  hourTypes,
}: {
  companyId: number | "";
  buildings: { id: number; name: string }[];
  employees: { id: number; name: string }[];
  hourTypes: { id: number; name: string }[];
}) {
  const { t } = useTranslation("common");
  const [rows, setRows] = useState<ContractHoursRow[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [building, setBuilding] = useState<number | "">("");
  const [employee, setEmployee] = useState<number | "">("");
  const [hourType, setHourType] = useState<number | "">("");
  const [validOn, setValidOn] = useState("");

  const filters = useMemo(
    () => ({
      company: companyId || undefined,
      building: building || undefined,
      employee: employee || undefined,
      hour_type: hourType || undefined,
      valid_on: validOn || undefined,
    }),
    [companyId, building, employee, hourType, validOn],
  );

  const requestKey = `${JSON.stringify(filters)}:${reloadKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api
      .get("/timesheets/contract-hours/", { params: filters })
      .then((response) => {
        if (cancelled) return;
        setRows(response.data.results ?? response.data);
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
  }, [filters, requestKey]);

  // Only the rows that MAY be edited are selectable — an approved row
  // is not one of them, so it never enters a selection that a bulk
  // action would then fail on.
  const edit = useEditMode<number>(
    rows.filter((row) => !row.is_locked).map((row) => row.id),
  );

  const cellKey = (id: number, day: Day) => `${id}:${day}`;
  const value = (row: ContractHoursRow, day: Day) =>
    edits[cellKey(row.id, day)] ?? row[day];

  const setCell = (row: ContractHoursRow, day: Day, next: string) =>
    setEdits((current) => ({ ...current, [cellKey(row.id, day)]: next }));

  const rowTotal = (row: ContractHoursRow) =>
    DAYS.reduce((sum, day) => sum + (Number(value(row, day)) || 0), 0);

  const tiles = [
    {
      key: "hours",
      label: t("contract_hours.tile_weekly"),
      value: rows.reduce((sum, row) => sum + rowTotal(row), 0).toFixed(2),
    },
    {
      key: "workers",
      label: t("contract_hours.tile_workers"),
      value: String(new Set(rows.map((r) => r.employee)).size),
    },
    {
      key: "buildings",
      label: t("contract_hours.tile_buildings"),
      value: String(new Set(rows.map((r) => r.building)).size),
    },
    {
      key: "rows",
      label: t("contract_hours.tile_rows"),
      value: String(rows.length),
    },
  ];

  async function save() {
    setBusy(true);
    setError("");
    try {
      const touched = new Set(
        Object.keys(edits).map((key) => Number(key.split(":")[0])),
      );
      for (const id of touched) {
        const row = rows.find((r) => r.id === id);
        if (!row || row.is_locked) continue;
        const payload: Record<string, string> = {};
        for (const day of DAYS) payload[day] = String(value(row, day));
        await api.patch(`/timesheets/contract-hours/${id}/`, payload);
      }
      setEdits({});
      edit.exit();
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const statusTag = (row: ContractHoursRow) =>
    row.status === "APPROVED"
      ? "cell-tag-open"
      : row.status === "SAVED"
        ? "cell-tag-normal"
        : "cell-tag-muted";

  return (
    <div data-testid="contract-hours-tab">
      {error && (
        <div className="alert-error" style={{ marginBottom: 12 }} role="alert">
          {error}
        </div>
      )}

      <div className="hours-tiles-head">
        <span className="hours-tiles-title">{t("contract_hours.title")}</span>
        <EditModeToggle
          editMode={edit.editModeRequested}
          onToggle={edit.toggleMode}
          testId="contract-hours-edit-toggle"
        />
      </div>

      <div
        className="hours-tile-row"
        data-testid="contract-hours-tiles"
        style={{
          gridTemplateColumns: `repeat(${tiles.length}, minmax(0, 1fr))`,
        }}
      >
        {tiles.map((tile) => (
          <div key={tile.key} className="hours-tile">
            <span className="hours-tile-label">{tile.label}</span>
            <span className="hours-tile-value">{tile.value}</span>
          </div>
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
            data-testid="contract-hours-filter-building"
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
            data-testid="contract-hours-filter-employee"
          >
            <option value="">{t("contract_hours.all_employees")}</option>
            {employees.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.hour_type")}</span>
          <select
            className="filter-control"
            value={hourType}
            onChange={(e) =>
              setHourType(e.target.value === "" ? "" : Number(e.target.value))
            }
            data-testid="contract-hours-filter-hour-type"
          >
            <option value="">{t("contract_hours.all_hour_types")}</option>
            {hourTypes.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.valid_on")}</span>
          <input
            className="filter-control"
            type="date"
            value={validOn}
            onChange={(e) => setValidOn(e.target.value)}
            data-testid="contract-hours-filter-valid-on"
          />
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
              <th>{t("building")}</th>
              <th>{t("contract_hours.employee")}</th>
              <th>{t("contract_hours.validity")}</th>
              <th>{t("contract_hours.hour_type")}</th>
              {DAYS.map((day) => (
                <th key={day} className="contract-num">
                  {t(`contract_hours.day_${day}`)}
                </th>
              ))}
              <th className="contract-num">{t("contract_hours.total")}</th>
              <th>{t("status")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} data-testid={`contract-hours-row-${row.id}`}>
                <td>
                  {row.building_name ?? (
                    <span className="muted-empty">
                      {t("contract_hours.no_building")}
                    </span>
                  )}
                </td>
                <td className="td-subject">{row.employee_name}</td>
                <td className="td-date">
                  {row.valid_from} → {row.valid_to ?? "…"}
                </td>
                <td>
                  <span className="cell-tag cell-tag-normal">
                    {row.hour_type_name}
                  </span>
                </td>
                {DAYS.map((day) => (
                  <td key={day} className="contract-num">
                    <input
                      className="field-input hours-week-grid-cell"
                      type="text"
                      inputMode="decimal"
                      value={value(row, day)}
                      onChange={(e) => setCell(row, day, e.target.value)}
                      /* An approved row is not editable — disabled here
                         rather than letting the server refuse a change
                         the operator has already typed. */
                      disabled={!edit.editMode || row.is_locked || busy}
                      aria-label={`${row.employee_name} ${day}`}
                      data-testid={`contract-hours-cell-${row.id}-${day}`}
                    />
                  </td>
                ))}
                <td className="contract-num">
                  <strong>{rowTotal(row).toFixed(2)}</strong>
                </td>
                <td>
                  <span className={`cell-tag ${statusTag(row)}`}>
                    {t(`contract_hours.status_${row.status}`)}
                  </span>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={13} className="muted">
                  {t("contract_hours.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {edit.editMode && (
        <div className="filter-actions" style={{ justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void save()}
            disabled={busy || Object.keys(edits).length === 0}
            data-testid="contract-hours-save"
          >
            {busy ? t("admin_form.saving") : t("hours_week_grid.save")}
          </button>
        </div>
      )}
    </div>
  );
}
