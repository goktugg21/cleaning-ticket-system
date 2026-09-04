import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  addStandardHourTypes,
  createHourType,
  deleteHourType,
  listHourTypes,
  updateHourType,
} from "../../api/timesheets";
import type {
  HourType,
  HourTypeWritePayload,
} from "../../api/timesheets.types";
import { BoundedList } from "../../components/BoundedList";
import { CatalogCompanySelect } from "../../components/CatalogTab";
import { EditModeToggle } from "../../components/EditModeToggle";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";
import {
  hourTypeLabel,
  isStandardHourType,
} from "../../lib/hourTypeLabel";
import { Toggle } from "../../components/Toggle";
import { useCatalogCompanies } from "../../lib/useCatalogCompanies";
import { useEditMode } from "../../lib/useEditMode";

interface HourTypeFormState {
  name: string;
  multiplier: string;
  sort_order: string;
  is_active: boolean;
}

const EMPTY_FORM: HourTypeFormState = {
  name: "",
  multiplier: "1.00",
  sort_order: "0",
  is_active: true,
};

interface HourTypesTabProps {
  /** True when a SUPER_ADMIN must disambiguate (2+ provider companies).
   *  Read only when the host also passes `selectedCompany`. */
  companyRequired?: boolean;
  /** Sprint 186 §3 — OMIT IT and the tab renders its OWN selector.
   *
   *  `undefined` and `""` are deliberately different: `undefined` means
   *  "no host is choosing", `""` means "the host is choosing and has not
   *  resolved a company yet". Defaulting the prop to `""` is what made
   *  the Catalogs page's copy of this tab silently unselectable. */
  selectedCompany?: number | "";
}

/**
 * Sprint 152 — "Uursoorten" tab of the Uren admin page. Manages the
 * per-provider-company `HourType` catalog: the hour kinds and their
 * multipliers that every time entry is filed against.
 *
 * Shaped after `ManagedUnitsTab` (self-contained fetch, own modal, own
 * delete dialog) because it is the same kind of object: a small
 * per-company catalog whose rows are PROTECTed once referenced.
 *
 * ## The company selector (Sprint 186 §3)
 *
 * This tab has two hosts. `HoursAdminPage` renders ONE selector for all
 * of its tabs and passes the resolved company down; `CatalogsAdminPage`
 * renders none, because its other three tabs each carry their own
 * (`CatalogTab`). Mounted there with no props, this tab defaulted
 * `selectedCompany` to `""` and showed no control at all: a SUPER_ADMIN
 * on a multi-company deployment saw every company's rows mixed together
 * and could not add one, because a create with no `company` is rejected
 * outright once more than one provider company exists.
 *
 * So the tab now falls back to owning the choice itself, using the same
 * `CatalogCompanySelect` the other three tabs render. Passing
 * `selectedCompany` still hands the choice back to the host, which is
 * how the Hours page keeps its single shared selector.
 *
 * Two things it does that the units tab does not:
 *   - the "Add standard set" action, which seeds the standard Dutch six
 *     and reports created-vs-skipped rather than a bare count;
 *   - a multiplier-edit warning. Changing a multiplier rewrites the
 *     weighted totals of every OPEN week that uses this type (closed
 *     weeks keep their snapshots). That is a big enough consequence to
 *     say out loud on the form rather than leave to be discovered.
 */
export function HourTypesTab({
  companyRequired = false,
  selectedCompany,
}: HourTypesTabProps) {
  const { t } = useTranslation("common");
  const { push: pushToast } = useToast();

  // Sprint 186 §3 — own the company only when no host is choosing.
  // `enabled` is false on the Hours page, which already fetched the
  // company list for the selector it renders itself.
  const hostControlsCompany = selectedCompany !== undefined;
  const owned = useCatalogCompanies(!hostControlsCompany);
  const company = hostControlsCompany ? selectedCompany : owned.companyId;
  const mustNameCompany = hostControlsCompany
    ? companyRequired
    : owned.companies.length > 1;

  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  // Sprint 155 §4 — this tab has no row selection, only per-row
  // actions, so only the MODE is used here. It is still the shared
  // controller: one implementation of "edit mode is meaningless
  // over an empty list" for every screen (lib/useEditMode.ts).
  const edit = useEditMode(hourTypes.map((h) => h.id));
  const [loadError, setLoadError] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  // Derived `loading` — see `MyHoursPage` for why it is not stored.
  const fetchKey = `${showInactive}|${company}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== fetchKey;

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [editing, setEditing] = useState<HourType | null>(null);
  const [form, setForm] = useState<HourTypeFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<HourType | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const standardDialogRef = useRef<ConfirmDialogHandle>(null);
  const [standardBusy, setStandardBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listHourTypes({
      ...(showInactive ? {} : { is_active: true }),
      ...(company === "" ? {} : { company }),
    })
      .then((rows) => {
        if (cancelled) return;
        setHourTypes(rows);
        setLoadError("");
        setLoadedKey(fetchKey);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoadedKey(fetchKey);
      });
    return () => {
      cancelled = true;
    };
  }, [showInactive, company, fetchKey]);

  /**
   * Re-read after any mutation, honouring the active filters. NEVER
   * THROWS — the mutation already committed, so a failed re-read must
   * not turn a saved row into a form error. Stale list plus a visible
   * page-level message.
   */
  async function refresh() {
    try {
      setHourTypes(
        await listHourTypes({
          ...(showInactive ? {} : { is_active: true }),
          ...(company === "" ? {} : { company }),
        }),
      );
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }

  function openCreate() {
    setMode("create");
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError("");
  }

  function openEdit(hourType: HourType) {
    setMode("edit");
    setEditing(hourType);
    setForm({
      name: hourType.name,
      multiplier: hourType.multiplier,
      sort_order: String(hourType.sort_order),
      is_active: hourType.is_active,
    });
    setFormError("");
  }

  function closeModal() {
    setMode(null);
    setEditing(null);
    setFormError("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) {
      setFormError(t("hour_types.error_name_required"));
      return;
    }
    if (mode === "create" && mustNameCompany && company === "") {
      setFormError(t("catalog.error_company_required"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    const payload: HourTypeWritePayload = {
      name: form.name.trim(),
      multiplier: form.multiplier.trim() || "1.00",
      sort_order: Number(form.sort_order) || 0,
      is_active: form.is_active,
      ...(mode === "create" && company !== ""
        ? { company }
        : {}),
    };
    try {
      if (mode === "create") {
        await createHourType(payload);
      } else if (mode === "edit" && editing) {
        await updateHourType(editing.id, payload);
      }
      await refresh();
      closeModal();
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleToggleActive(hourType: HourType) {
    try {
      await updateHourType(hourType.id, { is_active: !hourType.is_active });
      await refresh();
    } catch (err) {
      setLoadError(getApiError(err));
    }
  }

  function openDeleteDialog(hourType: HourType) {
    setDeleteTarget(hourType);
    deleteDialogRef.current?.open();
  }

  function handleCancelDelete() {
    deleteDialogRef.current?.close();
    setDeleteTarget(null);
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteHourType(deleteTarget.id);
      await refresh();
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      // `hour_type_protected` when entries still reference it — the
      // backend message tells the operator to archive instead.
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleConfirmStandardSet() {
    setStandardBusy(true);
    try {
      const result = await addStandardHourTypes(company);
      await refresh();
      standardDialogRef.current?.close();
      // Created-vs-skipped, not a bare count: "6 added" and "6 already
      // there" are the two outcomes and they need telling apart.
      pushToast({
        variant: "success",
        title: t("hour_types.standard_set_done", {
          created: result.created_count,
          skipped: result.skipped_count,
        }),
      });
    } catch (err) {
      setLoadError(getApiError(err));
      standardDialogRef.current?.close();
    } finally {
      setStandardBusy(false);
    }
  }

  return (
    <>
      <div className="page-header" style={{ marginTop: 0, marginBottom: 12 }}>
        {/* P-15 (P-14's S3 finding) — the page where the multiplier is
            EDITED says what it weighs; the sentence used to live only
            on the Hours page's fold. */}
        <div className="muted small" data-testid="hour-types-subtitle">
          {t("hour_types.desc")}
        </div>
        <div className="page-header-actions">
          {/* Sprint 186 §3 — rendered only when no host is choosing, and
              only on a multi-company deployment (the component decides
              the second half). First in the row because it scopes every
              control after it. */}
          {!hostControlsCompany && (
            <CatalogCompanySelect
              companies={owned.companies}
              companyId={owned.companyId}
              onChange={owned.setCompanyId}
              testId="hour-types-company"
            />
          )}
          <button
            type="button"
            className={
              showInactive ? "btn btn-secondary btn-sm" : "btn btn-ghost btn-sm"
            }
            data-testid="hour-types-show-inactive-toggle"
            aria-pressed={showInactive}
            onClick={() => setShowInactive((current) => !current)}
            disabled={loading}
          >
            {showInactive
              ? t("services.hide_inactive_toggle")
              : t("services.show_inactive_toggle")}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            data-testid="hour-types-standard-set-button"
            onClick={() => standardDialogRef.current?.open()}
            disabled={loading}
          >
            {t("hour_types.standard_set_button")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="hour-types-add-button"
            onClick={openCreate}
          >
            {t("hour_types.add_button")}
          </button>
          {/* Sprint 155 §4 — the intent step this tab was missing.
              "Deactivate" fired straight off the row click with no
              confirm and no mode: one mis-click took an hour type out
              of every picker in the module. Edit / Deactivate / Delete
              now live inside edit mode; outside it the table is a
              clean read-only list.

              Hidden, not disabled, when there is nothing to act on. */}
          {hourTypes.length > 0 && (
            <EditModeToggle
              editMode={edit.editMode}
              onToggle={edit.toggleMode}
              disabled={loading}
              testId="hour-types-edit-mode-toggle"
            />
          )}
        </div>
      </div>

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <div className="card card-detail-pad" data-testid="hour-types-list">
          <BoundedList
            size="md"
            count={hourTypes.length}
            ariaLabel={t("hour_types.list_aria")}
            testIdPrefix="hour-types"
            className="table-wrap"
            emptyState={
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="hour-types-empty"
              >
                <h3 className="empty-title" style={{ marginBottom: 8 }}>
                  {t("hour_types.empty_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("hour_types.empty_description")}
                </p>
              </div>
            }
          >
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("hour_types.col_name")}</th>
                  <th>{t("hour_types.col_multiplier")}</th>
                  <th>{t("hour_types.col_sort_order")}</th>
                  <th>{t("hour_types.col_entry_count")}</th>
                  <th>{t("hour_types.col_company")}</th>
                  <th>{t("services.col_active")}</th>
                  <th>{t("hour_types.col_actions")}</th>
                </tr>
              </thead>
              <tbody>
                {hourTypes.map((hourType) => (
                  <tr
                    key={hourType.id}
                    data-testid="hour-type-row"
                    data-hour-type-id={hourType.id}
                    data-inactive={hourType.is_active ? "false" : "true"}
                    className={hourType.is_active ? "" : "list-row-archived"}
                  >
                    <td>
                      {hourTypeLabel(hourType, t)}
                      {/* The management screen is the one place
                          that shows BOTH: an admin editing these
                          rows must be able to tell a recognised
                          standard row from a custom one. */}
                      {isStandardHourType(hourType) && (
                        <span
                          className="badge badge-normal"
                          style={{ marginLeft: 6 }}
                          data-testid="hour-type-standard-marker"
                        >
                          {t("hour_types.standard_marker")}
                        </span>
                      )}
                    </td>
                    {/* W7 §3 — a real multiplication sign, not the
                        letter x. This column is the ONE thing that
                        separates an hour type from a contract work
                        type: an hour of this kind counts as this many
                        hours, and those weighted hours are what an
                        hourly rate is later applied to. The column
                        header now says "Counts as", so the cell reads
                        as a sentence: Overtime — counts as x1.50. */}
                    <td data-testid="hour-type-multiplier-cell">
                      <strong>{"× "}{hourType.multiplier}</strong>
                    </td>
                    <td className="muted small">{hourType.sort_order}</td>
                    <td className="muted small">{hourType.entry_count}</td>
                    <td className="muted small">{hourType.company_name}</td>
                    <td>
                      {hourType.is_active
                        ? t("admin.status_active")
                        : t("admin.status_inactive")}
                    </td>
                    <td>
                      {/* Sprint 155 §4 — the whole action cell is inside
                          edit mode. An em dash keeps the column from
                          rendering as a blank cell, which reads as a
                          bug rather than as "not now". */}
                      {!edit.editMode && (
                        <span className="muted-empty">—</span>
                      )}
                      {edit.editMode && (
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          data-testid="hour-type-edit-button"
                          onClick={() => openEdit(hourType)}
                        >
                          {t("services.edit_button")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          data-testid="hour-type-toggle-active-button"
                          onClick={() => void handleToggleActive(hourType)}
                        >
                          {hourType.is_active
                            ? t("services.deactivate_button")
                            : t("services.activate_button")}
                        </button>
                        {/* Delete is offered exactly when the type is
                            unused. `TimeEntry.hour_type` is PROTECT, so
                            offering it on a referenced row would be
                            offering an action that always 400s. */}
                        {hourType.entry_count === 0 && (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            data-testid="hour-type-delete-button"
                            onClick={() => openDeleteDialog(hourType)}
                          >
                            {t("services.delete_button")}
                          </button>
                        )}
                      </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </BoundedList>
        </div>
      )}

      {mode !== null && (
        <div
          data-testid="hour-type-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            mode === "create"
              ? t("hour_types.add_modal_title")
              : t("hour_types.edit_modal_title")
          }
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
        >
          <form
            onSubmit={handleSubmit}
            className="card card-detail-pad"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
              {mode === "create"
                ? t("hour_types.add_modal_title")
                : t("hour_types.edit_modal_title")}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="hour-type-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="hour-type-name">
                {t("hour_types.field_name")} *
              </label>
              <input
                id="hour-type-name"
                className="field-input"
                type="text"
                maxLength={128}
                value={form.name}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, name: event.target.value }))
                }
                data-testid="hour-type-input-name"
                required
                disabled={formBusy}
              />
              {/* Sprint 152.3 — the form carries the STORED name, not
                  the translated label, because that is the value being
                  edited. Without this line an English-profile admin
                  opens a row listed as "Overtime", finds "Overwerk" in
                  the input, and reasonably concludes the form is
                  broken. */}
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("hour_types.field_name_standard_hint")}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hour-type-multiplier">
                {t("hour_types.field_multiplier")} *
              </label>
              <input
                id="hour-type-multiplier"
                className="field-input"
                type="number"
                min="0"
                max="9.99"
                step="0.01"
                value={form.multiplier}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    multiplier: event.target.value,
                  }))
                }
                data-testid="hour-type-input-multiplier"
                required
                disabled={formBusy}
              />
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("hour_types.field_multiplier_hint")}
              </div>
              {/* Only on EDIT: a multiplier change rewrites the weighted
                  totals of every OPEN week using this type. Closed weeks
                  keep their snapshots, which is exactly the part an
                  operator would not guess. */}
              {mode === "edit" &&
                editing !== null &&
                form.multiplier.trim() !== editing.multiplier && (
                  <div
                    className="alert-info"
                    role="status"
                    style={{ marginTop: 8 }}
                    data-testid="hour-type-multiplier-warning"
                  >
                    {t("hour_types.multiplier_change_warning")}
                  </div>
                )}
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hour-type-sort-order">
                {t("hour_types.field_sort_order")}
              </label>
              <input
                id="hour-type-sort-order"
                className="field-input"
                type="number"
                min="0"
                step="1"
                value={form.sort_order}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    sort_order: event.target.value,
                  }))
                }
                data-testid="hour-type-input-sort-order"
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Toggle
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="hour-type-input-is-active"
                  disabled={formBusy}
                />
                <span>{t("services.field_is_active")}</span>
              </label>
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("hour_types.field_is_active_hint")}
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeModal}
                disabled={formBusy}
                data-testid="hour-type-modal-cancel"
              >
                {t("services.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="hour-type-modal-save"
              >
                {formBusy ? t("admin_form.saving") : t("services.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("hour_types.delete_confirm_title")}
        body={t("hour_types.delete_confirm_body")}
        confirmLabel={t("services.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />

      <ConfirmDialog
        ref={standardDialogRef}
        title={t("hour_types.standard_set_confirm_title")}
        body={t("hour_types.standard_set_confirm_body")}
        confirmLabel={t("hour_types.standard_set_button")}
        onConfirm={handleConfirmStandardSet}
        busy={standardBusy}
      />
    </>
  );
}
