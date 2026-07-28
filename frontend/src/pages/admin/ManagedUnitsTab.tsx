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

  useEffect(() => {
    let cancelled = false;
    listManagedUnits()
      .then((data) => {
        if (cancelled) return;
        setUnits(data);
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
  }, []);

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
        const created = await createManagedUnit(payload);
        setUnits((prev) =>
          [...prev, created].sort((a, b) => a.label.localeCompare(b.label)),
        );
        closeModal();
      } else if (mode === "edit" && selected) {
        const updated = await updateManagedUnit(selected.id, payload);
        setUnits((prev) =>
          prev
            .map((u) => (u.id === updated.id ? updated : u))
            .sort((a, b) => a.label.localeCompare(b.label)),
        );
        setSelected(updated);
        closeModal();
      }
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
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
      setUnits((prev) => prev.filter((u) => u.id !== deleteTarget.id));
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

  return (
    <>
      <div className="page-header" style={{ marginTop: 0, marginBottom: 12 }}>
        <div />
        <div className="page-header-actions">
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
                    onClick={() => setSelected(unit)}
                  >
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
    </>
  );
}
