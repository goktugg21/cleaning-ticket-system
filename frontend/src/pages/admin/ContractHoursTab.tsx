import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Plus } from "lucide-react";

import { api, getApiError } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EditModeToggle } from "../../components/EditModeToggle";
import { ContractHoursBulkDialog } from "../../components/timesheets/ContractHoursBulkDialog";
import type { HourType, TimesheetEmployee } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { useEditMode } from "../../lib/useEditMode";
import { workTypeLabel } from "../../lib/workTypeLabel";

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
  work_type: number | null;
  work_type_name: string | null;
  work_type_standard_slot: string | null;
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
  /** The FULL records: the picker in the bulk dialog shows a building's
   *  city and address, and an employee's email, so a name collision is
   *  resolvable. Trimming them to {id,name} here would push that
   *  problem onto the operator. */
  buildings: BuildingAdmin[];
  employees: TimesheetEmployee[];
  hourTypes: HourType[];
}) {
  const { t } = useTranslation("common");
  const [rows, setRows] = useState<ContractHoursRow[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [workTypes, setWorkTypes] = useState<
    { id: number; name: string; standard_slot: string }[]
  >([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [rowToDelete, setRowToDelete] = useState<ContractHoursRow | null>(null);
  const deleteRef = useRef<ConfirmDialogHandle>(null);

  const [building, setBuilding] = useState<number | "">("");
  const [employee, setEmployee] = useState<number | "">("");
  const [hourType, setHourType] = useState<number | "">("");
  const [workTypeFilter, setWorkTypeFilter] = useState<number | "">("");
  const [validOn, setValidOn] = useState("");

  const filters = useMemo(
    () => ({
      company: companyId || undefined,
      building: building || undefined,
      employee: employee || undefined,
      hour_type: hourType || undefined,
      work_type: workTypeFilter || undefined,
      valid_on: validOn || undefined,
    }),
    [companyId, building, employee, hourType, workTypeFilter, validOn],
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

  // The work-type catalog for the column, the filter and the bulk
  // dialog. Its own read, not folded into the rows request: a catalog
  // changes when someone edits the catalog, not when a filter moves.
  useEffect(() => {
    let cancelled = false;
    api
      .get("/timesheets/work-types/", {
        params: { company: companyId || undefined, is_active: true },
      })
      .then((response) => {
        if (cancelled) return;
        const list = response.data.results ?? response.data;
        setWorkTypes(
          (list as { id: number; name: string; standard_slot?: string }[]).map(
            (row) => ({
              id: row.id,
              name: row.name,
              standard_slot: row.standard_slot ?? "",
            }),
          ),
        );
      })
      .catch(() => {
        // A missing catalog is not an error the operator can act on —
        // the picker simply offers "no work type", which is a legal
        // value. Failing the whole tab over it would be worse.
        if (!cancelled) setWorkTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, reloadKey]);

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

  async function remove(row: ContractHoursRow) {
    setBusy(true);
    setError("");
    try {
      await api.delete(`/timesheets/contract-hours/${row.id}/`);
      setRowToDelete(null);
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
        <div>
          <span className="hours-tiles-title">{t("contract_hours.title")}</span>
          {/* Sprint 172 §3 — the counterpart line to the Entries tab's. */}
          <div className="section-head-sub">
            {t("contract_hours.subtitle")}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <EditModeToggle
            editMode={edit.editModeRequested}
            onToggle={edit.toggleMode}
            testId="contract-hours-edit-toggle"
          />
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setBulkOpen(true)}
            data-testid="contract-hours-bulk-open"
          >
            <Plus size={14} strokeWidth={2.5} />
            {t("contract_hours.bulk_open")}
          </button>
        </div>
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

      {/* Sprint 169 §2 — said, not left blank. */}
      {workTypes.length === 0 && (
        <p className="muted small" data-testid="contract-hours-no-work-types">
          {t("work_types.none_yet")}
        </p>
      )}

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
            {employees.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name || person.email}
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
          <span className="filter-label">{t("contract_hours.work_type")}</span>
          <select
            className="filter-control"
            value={workTypeFilter}
            onChange={(e) =>
              setWorkTypeFilter(
                e.target.value === "" ? "" : Number(e.target.value),
              )
            }
            data-testid="contract-hours-filter-work-type"
          >
            <option value="">{t("contract_hours.all_work_types")}</option>
            {workTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {workTypeLabel(type.name, type.standard_slot, t)}
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
              <th>{t("contract_hours.work_type")}</th>
              {DAYS.map((day) => (
                <th key={day} className="contract-num">
                  {t(`contract_hours.day_${day}`)}
                </th>
              ))}
              <th className="contract-num">{t("contract_hours.total")}</th>
              <th>{t("status")}</th>
              <th>{t("contract_hours.actions")}</th>
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
                <td>
                  {row.work_type_name ? (
                    workTypeLabel(
                      row.work_type_name,
                      row.work_type_standard_slot,
                      t,
                    )
                  ) : (
                    <span className="muted-empty">
                      {t("contract_hours.no_work_type")}
                    </span>
                  )}
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
                <td>
                  {/* An APPROVED agreement is not deleted from here.
                      Correcting one writes a NEW row from a date — the
                      validity-window rule — because deleting it would
                      rewrite what last month's comparison said. */}
                  {row.is_locked ? (
                    <span className="muted-empty">
                      {t("contract_hours.locked_hint")}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => {
                        setRowToDelete(row);
                        deleteRef.current?.open();
                      }}
                      disabled={busy}
                      data-testid={`contract-hours-delete-${row.id}`}
                    >
                      {t("contract_hours.delete")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={15} className="muted">
                  {t("contract_hours.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {bulkOpen && (
        <ContractHoursBulkDialog
          employees={employees}
          buildings={buildings}
          hourTypes={hourTypes.filter((type) => type.is_active)}
          workTypes={workTypes}
          companyId={companyId || null}
          onClose={() => setBulkOpen(false)}
          onSaved={() => {
            setBulkOpen(false);
            setReloadKey((n) => n + 1);
          }}
        />
      )}

      {/* Rendered unconditionally and driven entirely through the ref —
          CLAUDE.md's rule for the native dialog, and the reason a
          Sprint 118 page went inert. */}
      <ConfirmDialog
        ref={deleteRef}
        title={t("contract_hours.delete_title")}
        body={t("contract_hours.delete_body", {
          name: rowToDelete?.employee_name ?? "",
        })}
        confirmLabel={t("contract_hours.delete")}
        onConfirm={() => {
          if (rowToDelete) void remove(rowToDelete);
        }}
      />

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
