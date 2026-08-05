import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createManagedUnit,
  deleteManagedUnit,
  listManagedUnits,
  updateManagedUnit,
} from "../../api/admin";
import type { ManagedUnit, ManagedUnitCreatePayload } from "../../api/types";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { useToast } from "../../components/ToastProvider";
import { Toggle } from "../../components/Toggle";

interface UnitFormState {
  label: string;
  is_active: boolean;
}

const EMPTY_UNIT_FORM: UnitFormState = { label: "", is_active: true };

function formatDate(value: string, locale: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(locale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

interface ManagedUnitsTabProps {
  // Sprint 135 — SUPER_ADMIN company disambiguation on create
  // (backend/extra_work/views_catalog.py::_resolve_catalog_create_company
  // 400s `service_company_required` for a SA managing 2+ provider
  // companies who omits `company`). `ServicesAdminPage` renders the ONE
  // shared selector (also used by the Services tab) and passes its
  // resolved state down here — this tab does not render its own control.
  companyRequired?: boolean;
  selectedCompany?: number | "";
}

/**
 * Sprint 123 — "Units" tab of the Service catalog admin page. Manages
 * the per-provider-company `ManagedUnit` catalog that backs the
 * OTHER-unit picker on Service / CustomerCustomPrice forms
 * (`ManagedUnitPicker`). Self-contained (own fetch, own modal, own
 * delete dialog) rather than threaded through `ServicesAdminPage`'s
 * existing Services/Categories state, since it has no cross-tab
 * dependency on either — Sprint 135 is the one exception: the shared
 * company-disambiguation selector, threaded in via props.
 *
 * `company_name` is shown as a list/detail column even though a
 * COMPANY_ADMIN only ever sees their own company's units (every row
 * repeats the same value for them) — a SUPER_ADMIN sees every
 * company's units on this same endpoint, and without it two
 * identically-named units from different companies would be
 * indistinguishable in the table.
 */
export function ManagedUnitsTab({
  companyRequired = false,
  selectedCompany = "",
}: ManagedUnitsTabProps) {
  const { t, i18n } = useTranslation("common");
  // Sprint 139 §2 — success toasts auto-dismiss; the failure list stays.
  const { push: pushToast } = useToast();
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [units, setUnits] = useState<ManagedUnit[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<ManagedUnit | null>(null);

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [form, setForm] = useState<UnitFormState>(EMPTY_UNIT_FORM);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<ManagedUnit | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // Sprint 137 item 7 — list edit mode. DELETE here is a REAL hard
  // delete (backend/extra_work/views_catalog.py::ManagedUnitDetailView
  // .delete), same as the Services list and unlike the customer pricing
  // lists, so the wording says delete. A unit still linked from a
  // Service or CustomerCustomPrice is PROTECTed and returns 400 — the
  // per-row failure report below is how the operator learns WHICH ones.
  const [editMode, setEditMode] = useState(false);
  const [bulkIds, setBulkIds] = useState<number[]>([]);
  const bulkDialogRef = useRef<ConfirmDialogHandle>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkFailures, setBulkFailures] = useState<string[]>([]);
  const [bulkDone, setBulkDone] = useState<number | null>(null);
  // Sprint 139 §1 — off by default (see the load effect).
  const [showInactive, setShowInactive] = useState(false);
  const [toggleBusy, setToggleBusy] = useState(false);

  // Sprint 139 §1 — inactive units are hidden by default, same rule
  // and same toggle shape as the Services list and the customer pricing
  // list. Sprint 139 §4 — the shared company selector filters this list
  // too. Both reuse the endpoint's existing `?is_active=` / `?company=`
  // params (it already supported them; see ManagedUnitListCreateView).
  useEffect(() => {
    let cancelled = false;
    listManagedUnits({
      ...(showInactive ? {} : { is_active: true }),
      ...(selectedCompany === "" ? {} : { company: selectedCompany }),
    })
      .then((data) => {
        if (cancelled) return;
        setUnits(data);
        // Sprint 142 (#127 review carry-over) — clear a stale banner
        // once the list is genuinely fresh again. See
        // `ServicesAdminPage`'s load effect for the full note.
        setLoadError("");
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [showInactive, selectedCompany]);

  function openCreateModal() {
    setMode("create");
    setForm(EMPTY_UNIT_FORM);
    setFormError("");
  }

  function openEditModal(unit: ManagedUnit) {
    setMode("edit");
    setForm({ label: unit.label, is_active: unit.is_active });
    setFormError("");
  }

  function closeModal() {
    setMode(null);
    setForm(EMPTY_UNIT_FORM);
    setFormError("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!form.label.trim()) {
      setFormError(t("managed_units.error_label_required"));
      return;
    }
    if (mode === "create" && companyRequired && selectedCompany === "") {
      setFormError(t("catalog.error_company_required"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    const payload: ManagedUnitCreatePayload = {
      label: form.label.trim(),
      is_active: form.is_active,
      ...(mode === "create" && selectedCompany !== ""
        ? { company: selectedCompany }
        : {}),
    };
    try {
      if (mode === "create") {
        await createManagedUnit(payload);
        // Sprint 140 §3 — the form carries an Active toggle, so a new
        // row may not match the active filters at all.
        await refreshUnits();
        closeModal();
      } else if (mode === "edit" && selected) {
        const updated = await updateManagedUnit(selected.id, payload);
        // Sprint 140 §3 — unticking Active here used to leave the row
        // in a list that claims to hide inactive rows.
        await refreshUnits();
        setSelected(updated);
        closeModal();
      }
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
    }
  }

  /**
   * Sprint 140 §3 — re-read the unit list after ANY mutation, honouring
   * the active archived toggle and company filter. The Services tab got
   * this treatment in Sprint 139; this tab got none of it, so a unit
   * deactivated through the edit modal's Active toggle stayed sitting
   * in a list that claimed to hide inactive rows.
   *
   * Same choice as the Services tab: re-read rather than merge locally.
   * A local merge can drop a row but never bring one back, so
   * reactivating a hidden unit would appear to do nothing.
   */
  async function refreshUnits() {
    // Sprint 141 §1/§2 — NEVER THROWS, same contract and same reasoning
    // as `ServicesAdminPage.refreshCatalogRows`: every caller runs it
    // after a mutation that already committed, so a failed re-read must
    // not wedge a dialog's busy flag or turn a saved row into a form
    // error. Stale list + visible page-level error, never silence.
    try {
      setUnits(
        await listManagedUnits({
          ...(showInactive ? {} : { is_active: true }),
          ...(selectedCompany === "" ? {} : { company: selectedCompany }),
        }),
      );
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }

  /**
   * Sprint 140 §3 — single-row (de)activate, mirroring the Services
   * detail panel. Before this the edit modal's Active toggle was the
   * ONLY way to deactivate a unit, while the list told the operator
   * inactive rows could be "reactivated from their detail panel" — a
   * control that did not exist. Adding it makes the sentence true and
   * makes the two tabs behave identically.
   */
  async function handleToggleUnitActive(unit: ManagedUnit) {
    setToggleBusy(true);
    try {
      const updated = await updateManagedUnit(unit.id, {
        label: unit.label,
        is_active: !unit.is_active,
      });
      // Set BEFORE the re-read (Sprint 141 §2): the detail panel must
      // not depend on a network call that is allowed to fail.
      setSelected(updated);
      await refreshUnits();
    } catch (err) {
      setLoadError(getApiError(err));
    } finally {
      setToggleBusy(false);
    }
  }

  function openDeleteDialog(unit: ManagedUnit) {
    setDeleteTarget(unit);
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
      await deleteManagedUnit(deleteTarget.id);
      await refreshUnits();
      if (selected?.id === deleteTarget.id) {
        setSelected(null);
      }
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      // Most often ProtectedError (`managed_unit_protected`) when the
      // unit is still linked from a Service / CustomerCustomPrice row —
      // the backend's friendly message tells the operator to archive
      // instead; surfaced the same way Category delete does.
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  // ---- Sprint 137 item 7 — bulk delete (units list edit mode) -------
  function exitEditMode() {
    setEditMode(false);
    setBulkIds([]);
  }

  function toggleBulkRow(unitId: number, checked: boolean) {
    setBulkIds((prev) =>
      checked ? [...prev, unitId] : prev.filter((id) => id !== unitId),
    );
  }

  function openBulkDelete() {
    setBulkFailures([]);
    setBulkDone(null);
    bulkDialogRef.current?.open();
  }

  /**
   * Delete every selected unit. No bulk endpoint exists, so this is N
   * sequential DELETEs from the client (see the `## NEXT` entry in the
   * sprint checklist). A PROTECTed unit comes back 400 and is named
   * individually — a partial run is never reported as a clean one.
   */
  async function handleConfirmBulkDelete() {
    setBulkBusy(true);
    const targets = units.filter((u) => bulkIds.includes(u.id));
    const deletedIds: number[] = [];
    const failed: { id: number; label: string }[] = [];

    for (const unit of targets) {
      try {
        await deleteManagedUnit(unit.id);
        deletedIds.push(unit.id);
      } catch {
        failed.push({ id: unit.id, label: unit.label });
      }
    }

    if (deletedIds.length > 0) {
      await refreshUnits();
      if (selected && deletedIds.includes(selected.id)) {
        setSelected(null);
      }
    }
    setBulkIds(failed.map((f) => f.id));
    setBulkFailures(failed.map((f) => f.label));
    setBulkDone(deletedIds.length);
    setBulkBusy(false);
    bulkDialogRef.current?.close();
    if (failed.length === 0 && deletedIds.length > 0) {
      pushToast({
        variant: "success",
        title: t("managed_units.bulk_delete_done", {
          count: deletedIds.length,
        }),
      });
    }
  }

  return (
    <>
      <div className="page-header" style={{ marginTop: 0, marginBottom: 12 }}>
        <div />
        <div className="page-header-actions">
          {/* Sprint 137 item 7 — Edit / Done. */}
          <button
            type="button"
            className={
              showInactive
                ? "btn btn-secondary btn-sm"
                : "btn btn-ghost btn-sm"
            }
            data-testid="services-units-show-inactive-toggle"
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
            className="btn btn-ghost btn-sm"
            data-testid="services-units-edit-mode-toggle"
            aria-pressed={editMode}
            onClick={() => (editMode ? exitEditMode() : setEditMode(true))}
            disabled={loading || units.length === 0}
          >
            {editMode
              ? t("services.list_edit_done")
              : t("services.list_edit_start")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="services-add-unit-button"
            onClick={openCreateModal}
          >
            {t("managed_units.add_button")}
          </button>
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
        <div className="card" data-testid="services-units-list">
          {/* Sprint 139 §1 — same note as the Services list. */}
          {showInactive && (
            <div
              className="alert-info"
              role="status"
              style={{ margin: "12px 16px 0" }}
              data-testid="services-units-inactive-included-note"
            >
              {t("services.inactive_included_note", {
                count: units.filter((u) => !u.is_active).length,
              })}
            </div>
          )}
          {editMode && units.length > 0 && (
            <>
              <div className="list-edit-bar">
                <MultiSelectToolbar
                  selectedCount={bulkIds.length}
                  onSelectAll={() => setBulkIds(units.map((u) => u.id))}
                  onClearAll={() => setBulkIds([])}
                  disabled={bulkBusy}
                  actions={[
                    {
                      key: "delete",
                      label: t("managed_units.bulk_delete_button"),
                      onClick: openBulkDelete,
                      destructive: true,
                    },
                  ]}
                  testIdPrefix="services-units-bulk-delete"
                />
              </div>
              <div
                className="muted small"
                style={{ padding: "8px 16px 0" }}
                data-testid="services-units-bulk-delete-explainer"
              >
                {t("managed_units.bulk_delete_explainer")}
              </div>
            </>
          )}
          {bulkFailures.length > 0 && (
            <div
              className="alert-error"
              role="alert"
              style={{ margin: "12px 16px 0" }}
              data-testid="services-units-bulk-delete-failures"
            >
              {t("managed_units.bulk_delete_partial", {
                done: bulkDone ?? 0,
                failed: bulkFailures.length,
              })}
              <ul className="list-edit-failure-list">
                {bulkFailures.map((label) => (
                  <li key={label}>{label}</li>
                ))}
              </ul>
            </div>
          )}
          <BoundedList
            size="md"
            count={units.length}
            ariaLabel={t("managed_units.list_aria")}
            testIdPrefix="services-units"
            className="table-wrap"
            emptyState={
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="services-units-empty"
              >
                <h3 style={{ marginBottom: 8 }}>
                  {t("managed_units.empty_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("managed_units.empty_description")}
                </p>
              </div>
            }
          >
            <table className="data-table">
              <thead>
                <tr>
                  {editMode && (
                    <th className="list-edit-checkbox-cell">
                      <span className="sr-only">
                        {t("services.list_edit_select_column")}
                      </span>
                    </th>
                  )}
                  <th>{t("managed_units.col_label")}</th>
                  <th>{t("managed_units.col_company")}</th>
                  <th>{t("services.col_active")}</th>
                </tr>
              </thead>
              <tbody>
                {units.map((unit) => (
                  <tr
                    key={unit.id}
                    data-testid="services-unit-row"
                    data-unit-id={unit.id}
                    data-inactive={unit.is_active ? "false" : "true"}
                    className={unit.is_active ? "" : "list-row-archived"}
                    onClick={() => {
                      if (!editMode) {
                        setSelected(unit);
                        return;
                      }
                      toggleBulkRow(unit.id, !bulkIds.includes(unit.id));
                    }}
                  >
                    {editMode && (
                      <td className="list-edit-checkbox-cell">
                        <input
                          type="checkbox"
                          className="checkbox-input"
                          data-testid="services-units-bulk-delete-row"
                          data-unit-id={unit.id}
                          checked={bulkIds.includes(unit.id)}
                          onChange={(event) =>
                            toggleBulkRow(unit.id, event.target.checked)
                          }
                          onClick={(event) => event.stopPropagation()}
                          disabled={bulkBusy}
                          aria-label={unit.label}
                        />
                      </td>
                    )}
                    <td>{unit.label}</td>
                    <td className="muted small">{unit.company_name}</td>
                    <td>
                      {unit.is_active
                        ? t("admin.status_active")
                        : t("admin.status_inactive")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </BoundedList>
        </div>
      )}

      {selected && (
        <section
          className="card"
          data-testid="services-unit-detail"
          style={{ marginTop: 16, padding: "20px 22px" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 12,
              marginBottom: 12,
            }}
          >
            <div>
              <div className="eyebrow" style={{ marginBottom: 4 }}>
                {t("managed_units.detail_title")}
              </div>
              <h3 className="section-title" style={{ margin: 0 }}>
                {selected.label}
              </h3>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {/* Sprint 140 §3 — mirrors the Services detail panel.
                  Without it, the list's "reactivate from their detail
                  panel" note pointed at a control that did not exist. */}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="services-unit-toggle-active-button"
                onClick={() => void handleToggleUnitActive(selected)}
                disabled={toggleBusy}
              >
                {selected.is_active
                  ? t("services.deactivate_button")
                  : t("services.activate_button")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="services-unit-edit-button"
                onClick={() => openEditModal(selected)}
              >
                {t("services.edit_button")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="services-unit-delete-button"
                onClick={() => openDeleteDialog(selected)}
              >
                {t("services.delete_button")}
              </button>
            </div>
          </div>

          <div className="detail-kv-list">
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("managed_units.col_company")}
              </span>
              <span className="detail-kv-val">{selected.company_name}</span>
            </div>
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("services.col_active")}
              </span>
              <span className="detail-kv-val">
                {selected.is_active
                  ? t("admin.status_active")
                  : t("admin.status_inactive")}
              </span>
            </div>
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("services.field_created_at")}
              </span>
              <span className="detail-kv-val">
                {formatDate(selected.created_at, dateLocale)}
              </span>
            </div>
            <div className="detail-kv-row">
              <span className="detail-kv-label">
                {t("services.field_updated_at")}
              </span>
              <span className="detail-kv-val">
                {formatDate(selected.updated_at, dateLocale)}
              </span>
            </div>
          </div>
        </section>
      )}

      {mode !== null && (
        <div
          data-testid="services-unit-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            mode === "create"
              ? t("managed_units.add_modal_title")
              : t("managed_units.edit_modal_title")
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
            className="card"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {mode === "create"
                ? t("managed_units.add_modal_title")
                : t("managed_units.edit_modal_title")}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="services-unit-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="unit-label">
                {t("managed_units.field_label")} *
              </label>
              <input
                id="unit-label"
                className="field-input"
                type="text"
                maxLength={50}
                value={form.label}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, label: event.target.value }))
                }
                placeholder={t("managed_units.field_label_placeholder")}
                data-testid="services-unit-input-label"
                required
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <Toggle
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="services-unit-input-is-active"
                  disabled={formBusy}
                />
                <span>{t("services.field_is_active")}</span>
              </label>
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("managed_units.field_is_active_hint")}
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
                data-testid="services-unit-modal-cancel"
              >
                {t("services.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="services-unit-modal-save"
              >
                {formBusy ? t("admin_form.saving") : t("services.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("managed_units.delete_confirm_title")}
        body={t("managed_units.delete_confirm_body")}
        confirmLabel={t("services.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />

      {/* Sprint 137 item 7 — ONE confirmation for the whole selection.
          Unconditionally rendered, ref-driven (CLAUDE.md §3). */}
      <ConfirmDialog
        ref={bulkDialogRef}
        title={t("managed_units.bulk_delete_confirm_title", {
          count: bulkIds.length,
        })}
        body={t("managed_units.bulk_delete_confirm_body", {
          count: bulkIds.length,
        })}
        confirmLabel={t("managed_units.bulk_delete_button")}
        onConfirm={handleConfirmBulkDelete}
        busy={bulkBusy}
        destructive
      />
    </>
  );
}
