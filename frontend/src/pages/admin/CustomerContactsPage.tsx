import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createCustomerContact,
  deleteCustomerContact,
  getCustomer,
  listCustomerBuildings,
  listCustomerContacts,
  updateCustomerContact,
} from "../../api/admin";
import type {
  Contact,
  ContactCreatePayload,
  CustomerAdmin,
  CustomerBuildingMembership,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";

/**
 * Sprint 28 Batch 4 — Customer Contacts page (per-customer phone book).
 *
 * View-first per `docs/product/meeting-2026-05-15-system-requirements.md`
 * §3. List rows are read-only. Clicking a row opens a read-only detail
 * panel; editing happens only through an explicit "Edit" action that
 * opens a modal. Creating a contact opens a separate modal.
 *
 * IMPORTANT — Contacts are NOT Users (§1 of the same doc):
 *   - No password / role / scope / login fields in any form here.
 *   - Promoting a Contact into a User is an explicit, separate flow
 *     (parked for a future batch).
 *
 * Permission: SUPER_ADMIN + COMPANY_ADMIN reach this route via
 * `AdminRoute` (see `App.tsx`). Backend re-gates with
 * `IsSuperAdminOrCompanyAdminForCompany` on every list/create/detail
 * call; BUILDING_MANAGER / STAFF / CUSTOMER_USER never see this page.
 */

interface ContactFormState {
  full_name: string;
  email: string;
  phone: string;
  role_label: string;
  notes: string;
  building: number | "";
}

const EMPTY_FORM: ContactFormState = {
  full_name: "",
  email: "",
  phone: "",
  role_label: "",
  notes: "",
  building: "",
};

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

export function CustomerContactsPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation("common");
  const numericId = useMemo(() => {
    if (!id) return null;
    const n = Number(id);
    return Number.isFinite(n) ? n : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [linkedBuildings, setLinkedBuildings] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  // Read-only detail panel state. `selected` is the contact currently
  // expanded into the detail view. Editing toggles `editing=true` and
  // pre-populates `form`.
  const [selected, setSelected] = useState<Contact | null>(null);

  // Create / edit modal state. `mode` is "create" when adding a new
  // contact and "edit" when modifying `selected`. Mutually exclusive
  // with `selected`-only read-only view.
  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [form, setForm] = useState<ContactFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  // Delete confirmation.
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<Contact | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  // Initial load — fetch the customer (for the page title) and the
  // contacts list in parallel. The buildings list is needed for the
  // create/edit modal's building dropdown.
  useEffect(() => {
    const cancelled = { current: false };
    async function load(customerId: number) {
      try {
        const [customerData, contactsData, buildingsData] = await Promise.all([
          getCustomer(customerId),
          listCustomerContacts(customerId),
          listCustomerBuildings(customerId),
        ]);
        if (cancelled.current) return;
        setCustomer(customerData);
        setContacts(contactsData);
        setLinkedBuildings(buildingsData.results);
        setLoading(false);
      } catch (err) {
        if (!cancelled.current) {
          setLoadError(getApiError(err));
          setLoading(false);
        }
      }
    }
    if (numericId === null) {
      // Defer the synchronous state update into a microtask to keep
      // the effect body free of cascading-render lint hits. The
      // queueMicrotask call still runs before paint, so the UI
      // converges in the same frame.
      queueMicrotask(() => {
        if (!cancelled.current) {
          setLoadError(t("customer_contacts.load_error"));
          setLoading(false);
        }
      });
    } else {
      load(numericId);
    }
    return () => {
      cancelled.current = true;
    };
  }, [numericId, t]);

  function openCreateModal() {
    setMode("create");
    setForm(EMPTY_FORM);
    setFormError("");
  }

  function openEditModal(contact: Contact) {
    setMode("edit");
    setForm({
      full_name: contact.full_name,
      email: contact.email,
      phone: contact.phone,
      role_label: contact.role_label,
      notes: contact.notes,
      building: contact.building ?? "",
    });
    setFormError("");
  }

  function closeFormModal() {
    setMode(null);
    setForm(EMPTY_FORM);
    setFormError("");
  }

  async function handleSubmitForm(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    if (!form.full_name.trim()) {
      setFormError(t("customer_contacts.error_full_name_required"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    const payload: ContactCreatePayload = {
      full_name: form.full_name.trim(),
      email: form.email.trim(),
      phone: form.phone.trim(),
      role_label: form.role_label.trim(),
      notes: form.notes,
      building: form.building === "" ? null : Number(form.building),
    };
    try {
      if (mode === "create") {
        const created = await createCustomerContact(numericId, payload);
        setContacts((prev) =>
          [...prev, created].sort((a, b) =>
            a.full_name.localeCompare(b.full_name),
          ),
        );
        closeFormModal();
      } else if (mode === "edit" && selected) {
        const updated = await updateCustomerContact(
          numericId,
          selected.id,
          payload,
        );
        setContacts((prev) =>
          prev
            .map((c) => (c.id === updated.id ? updated : c))
            .sort((a, b) => a.full_name.localeCompare(b.full_name)),
        );
        setSelected(updated);
        closeFormModal();
      }
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
    }
  }

  function openDeleteDialog(contact: Contact) {
    setDeleteTarget(contact);
    deleteDialogRef.current?.open();
  }

  async function handleConfirmDelete() {
    if (numericId === null || !deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteCustomerContact(numericId, deleteTarget.id);
      setContacts((prev) => prev.filter((c) => c.id !== deleteTarget.id));
      if (selected?.id === deleteTarget.id) {
        setSelected(null);
      }
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  const buildingNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const link of linkedBuildings) {
      map.set(link.building_id, link.building_name);
    }
    return map;
  }, [linkedBuildings]);

  const customerName = customer?.name ?? "";

  return (
    <div data-testid="customer-contacts-page">
      <Link
        to={`/admin/customers/${numericId ?? ""}`}
        className="link-back"
        data-testid="customer-contacts-back"
      >
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("customer_form.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">
            {customerName
              ? `${customerName} · ${t("customer_contacts.page_title")}`
              : t("customer_contacts.page_title")}
          </h2>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="customer-contacts-add-button"
            onClick={openCreateModal}
            disabled={loading || numericId === null}
          >
            {t("customer_contacts.add_button")}
          </button>
        </div>
      </div>

      {loadError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <>
          <div className="card" data-testid="customer-contacts-list">
            {contacts.length === 0 ? (
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="customer-contacts-empty"
              >
                <h3 style={{ marginBottom: 8 }}>
                  {t("customer_contacts.empty_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("customer_contacts.empty_description")}
                </p>
              </div>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  margin: 0,
                  padding: 0,
                }}
              >
                {contacts.map((contact) => {
                  const isActive = selected?.id === contact.id;
                  const contactLine =
                    contact.email || contact.phone || "";
                  return (
                    <li
                      key={contact.id}
                      data-testid="customer-contact-row"
                      data-contact-id={contact.id}
                    >
                      <button
                        type="button"
                        onClick={() => setSelected(contact)}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          background: isActive
                            ? "var(--surface-2, #f3f4f6)"
                            : "transparent",
                          border: "none",
                          padding: "12px 18px",
                          borderBottom: "1px solid var(--border)",
                          cursor: "pointer",
                          display: "flex",
                          flexDirection: "column",
                          gap: 4,
                        }}
                      >
                        <span style={{ fontWeight: 600 }}>
                          {contact.full_name}
                        </span>
                        <span
                          className="muted small"
                          style={{ display: "flex", gap: 12, flexWrap: "wrap" }}
                        >
                          {contact.role_label && (
                            <span data-testid="customer-contact-row-role">
                              {contact.role_label}
                            </span>
                          )}
                          {contactLine && (
                            <span data-testid="customer-contact-row-contact-line">
                              {contactLine}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {selected && (
            <section
              className="card"
              data-testid="customer-contact-detail"
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
                    {t("customer_contacts.detail_title")}
                  </div>
                  <h3 className="section-title" style={{ margin: 0 }}>
                    {selected.full_name}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-contact-edit-button"
                    onClick={() => openEditModal(selected)}
                  >
                    {t("customer_contacts.edit_button")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-contact-delete-button"
                    onClick={() => openDeleteDialog(selected)}
                  >
                    {t("customer_contacts.delete_button")}
                  </button>
                </div>
              </div>

              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_role_label")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-contact-detail-role"
                  >
                    {selected.role_label || "—"}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_email")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-contact-detail-email"
                  >
                    {selected.email || "—"}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_phone")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-contact-detail-phone"
                  >
                    {selected.phone || "—"}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_building")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-contact-detail-building"
                  >
                    {selected.building === null
                      ? t("customer_contacts.building_company_wide")
                      : buildingNameById.get(selected.building) ??
                        `#${selected.building}`}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_notes")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-contact-detail-notes"
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {selected.notes || "—"}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_created_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selected.created_at, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_contacts.field_updated_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selected.updated_at, dateLocale)}
                  </span>
                </div>
              </div>
            </section>
          )}
        </>
      )}

      {/* Create / edit modal. Single component used for both flows;
          `mode` drives the title + submit handler. The modal is
          deliberately a non-native overlay (mirrors the workflow
          override modal pattern from TicketDetailPage) so the form
          can include a Cancel/Save toolbar without depending on
          `<dialog>` focus quirks. The form contains ONLY contact
          fields — no password, no role enum, no scope inputs. */}
      {mode !== null && (
        <div
          data-testid="customer-contact-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            mode === "create"
              ? t("customer_contacts.add_modal_title")
              : t("customer_contacts.edit_modal_title")
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
            onSubmit={handleSubmitForm}
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
                ? t("customer_contacts.add_modal_title")
                : t("customer_contacts.edit_modal_title")}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-contact-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="contact-full-name">
                {t("customer_contacts.field_full_name")} *
              </label>
              <input
                id="contact-full-name"
                className="field-input"
                type="text"
                value={form.full_name}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, full_name: event.target.value }))
                }
                data-testid="customer-contact-input-full-name"
                required
                disabled={formBusy}
              />
            </div>

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="contact-email">
                  {t("customer_contacts.field_email")}
                </label>
                <input
                  id="contact-email"
                  className="field-input"
                  type="email"
                  value={form.email}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, email: event.target.value }))
                  }
                  data-testid="customer-contact-input-email"
                  disabled={formBusy}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="contact-phone">
                  {t("customer_contacts.field_phone")}
                </label>
                <input
                  id="contact-phone"
                  className="field-input"
                  type="tel"
                  value={form.phone}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, phone: event.target.value }))
                  }
                  data-testid="customer-contact-input-phone"
                  disabled={formBusy}
                />
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="contact-role-label">
                {t("customer_contacts.field_role_label")}
              </label>
              <input
                id="contact-role-label"
                className="field-input"
                type="text"
                value={form.role_label}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    role_label: event.target.value,
                  }))
                }
                placeholder={t("customer_contacts.field_role_label_hint")}
                data-testid="customer-contact-input-role-label"
                disabled={formBusy}
              />
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("customer_contacts.field_role_label_hint")}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="contact-building">
                {t("customer_contacts.field_building")}
              </label>
              <select
                id="contact-building"
                className="field-select"
                value={form.building === "" ? "" : String(form.building)}
                onChange={(event) => {
                  const v = event.target.value;
                  setForm((prev) => ({
                    ...prev,
                    building: v === "" ? "" : Number(v),
                  }));
                }}
                data-testid="customer-contact-input-building"
                disabled={formBusy}
              >
                <option value="">
                  {t("customer_contacts.field_building_optional")}
                </option>
                {linkedBuildings.map((link) => (
                  <option key={link.id} value={link.building_id}>
                    {link.building_name}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="contact-notes">
                {t("customer_contacts.field_notes")}
              </label>
              <textarea
                id="contact-notes"
                className="field-textarea"
                rows={4}
                value={form.notes}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, notes: event.target.value }))
                }
                data-testid="customer-contact-input-notes"
                disabled={formBusy}
              />
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
                onClick={closeFormModal}
                disabled={formBusy}
                data-testid="customer-contact-modal-cancel"
              >
                {t("customer_contacts.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="customer-contact-modal-save"
              >
                {formBusy ? t("admin_form.saving") : t("customer_contacts.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("customer_contacts.delete_confirm_title")}
        body={t("customer_contacts.delete_confirm_body")}
        confirmLabel={t("customer_contacts.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
        busy={deleteBusy}
        destructive
      />
    </div>
  );
}
