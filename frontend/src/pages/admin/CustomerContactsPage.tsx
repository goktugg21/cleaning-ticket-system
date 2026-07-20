import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import axios from "axios";

import { getApiError } from "../../api/client";
import {
  createCustomerContact,
  deleteCustomerContact,
  getCustomer,
  listCustomerBuildings,
  listCustomerContacts,
  promoteCustomerContact,
  updateCustomerContact,
} from "../../api/admin";
import type {
  Contact,
  ContactCreatePayload,
  CustomerAccessRole,
  CustomerAdmin,
  CustomerBuildingMembership,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { accessRoleLabelKey } from "../../lib/enumLabels";
import { ContactPermissionsPanel } from "./ContactPermissionsPanel";

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
  // A contact may be linked to several buildings; empty = company-wide.
  building_ids: number[];
}

const EMPTY_FORM: ContactFormState = {
  full_name: "",
  email: "",
  phone: "",
  role_label: "",
  notes: "",
  building_ids: [],
};

// Promote-to-user (Sprint 12B). The access-role options mirror the
// backend `CustomerUserBuildingAccess.AccessRole` enum; labels reuse the
// shared `access_role.*` keys via `accessRoleLabelKey`.
const ACCESS_ROLE_OPTIONS: CustomerAccessRole[] = [
  "CUSTOMER_USER",
  "CUSTOMER_LOCATION_MANAGER",
  "CUSTOMER_COMPANY_ADMIN",
];

interface PromoteFormState {
  access_role: CustomerAccessRole;
  building_ids: number[];
  phone: string;
}

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
  const toast = useToast();
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

  // Filter bar — building + free-text search are BOTH server-side
  // (passed through to ?building_id / ?search). "" = All (param
  // omitted, full list returned).
  const [filterBuildingId, setFilterBuildingId] = useState<number | "">("");
  const [searchText, setSearchText] = useState("");

  // Read-only detail panel state. `selected` is the contact currently
  // expanded into the detail view. Editing toggles `editing=true` and
  // pre-populates `form`.
  const [selected, setSelected] = useState<Contact | null>(null);

  // Sprint 2 — in-place permission editor toggle for a LINKED contact's
  // user. Collapsed by default; reset whenever a different contact is
  // selected so the panel never lingers on the wrong user.
  const [permissionsPanelOpen, setPermissionsPanelOpen] = useState(false);

  // Create / edit modal state. `mode` is "create" when adding a new
  // contact and "edit" when modifying `selected`. Mutually exclusive
  // with `selected`-only read-only view.
  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [form, setForm] = useState<ContactFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);
  // #108 Part D — display-only building filters for the two pickers;
  // hidden-but-selected buildings stay selected (never changes what is
  // submitted).
  const [buildingFilter, setBuildingFilter] = useState("");

  // Delete confirmation.
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<Contact | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // Promote-to-user modal (Sprint 12B). Opened over the read-only
  // `selected` detail panel. The backend decides INVITE vs LINK; we only
  // collect the optional access role / building grant / phone. Phone is
  // required (the backend rejects promotion without a valid NL number).
  const [promoting, setPromoting] = useState(false);
  const [promoteForm, setPromoteForm] = useState<PromoteFormState>({
    access_role: "CUSTOMER_USER",
    building_ids: [],
    phone: "",
  });
  const [promoteBusy, setPromoteBusy] = useState(false);
  const [promoteBuildingFilter, setPromoteBuildingFilter] = useState("");
  const [promoteError, setPromoteError] = useState("");
  const [promotePhoneError, setPromotePhoneError] = useState("");
  const [promoteRoleError, setPromoteRoleError] = useState("");
  const promotePhoneRef = useRef<HTMLInputElement>(null);

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  // Build the server-side contacts params from the current filter
  // state. Empty/All filters are omitted so the backend returns the full
  // list. Optional overrides let the filter-change effect pass the
  // new value without racing the not-yet-committed state.
  function contactListParams(overrides?: {
    buildingId?: number | "";
    search?: string;
  }): { building_id?: number; search?: string } {
    const buildingId = overrides?.buildingId ?? filterBuildingId;
    const search = overrides?.search ?? searchText;
    const params: { building_id?: number; search?: string } = {};
    if (buildingId !== "") params.building_id = buildingId;
    if (search.trim() !== "") params.search = search.trim();
    return params;
  }

  // Initial load — fetch the customer (for the page title) and the
  // contacts list in parallel. The buildings list is needed for the
  // create/edit modal's building dropdown AND the filter dropdown.
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

  // Server-side filter refetch. The initial-load effect already fetched
  // once with empty filters, so skip the very first run; thereafter a
  // change to the building filter or search re-fetches the contacts list
  // with the new ?building_id / ?search params. Search is debounced
  // (300ms) so typing doesn't fire a request per keystroke; the building
  // change refetches as soon as the debounce window elapses. All
  // setState happens inside the async closure after an await.
  const didMountContactFilterRef = useRef(false);
  useEffect(() => {
    if (numericId === null) return;
    if (!didMountContactFilterRef.current) {
      didMountContactFilterRef.current = true;
      return;
    }
    const cancelled = { current: false };
    const handle = window.setTimeout(() => {
      listCustomerContacts(numericId, contactListParams())
        .then((rows) => {
          if (!cancelled.current) setContacts(rows);
        })
        .catch((err) => {
          if (!cancelled.current) setLoadError(getApiError(err));
        });
    }, 300);
    return () => {
      cancelled.current = true;
      window.clearTimeout(handle);
    };
    // contactListParams reads the latest filter state; the effect fires
    // on filter/search changes and numericId resets.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericId, filterBuildingId, searchText]);

  function openCreateModal() {
    setMode("create");
    setForm(EMPTY_FORM);
    setBuildingFilter("");
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
      building_ids: [...(contact.linked_building_ids ?? [])],
    });
    setBuildingFilter("");
    setFormError("");
  }

  function toggleFormBuilding(buildingId: number) {
    setForm((prev) => {
      const has = prev.building_ids.includes(buildingId);
      return {
        ...prev,
        building_ids: has
          ? prev.building_ids.filter((b) => b !== buildingId)
          : [...prev.building_ids, buildingId],
      };
    });
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
      // building_ids is the authority for the contact's building links
      // (replace-set on the backend; [] = company-wide). We omit the legacy
      // single `building` so it never silently re-injects an extra link.
      building_ids: form.building_ids,
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

  function openPromoteModal(contact: Contact) {
    setPromoteForm({
      access_role: "CUSTOMER_USER",
      building_ids: [...contact.linked_building_ids],
      phone: contact.phone ?? "",
    });
    setPromoteBuildingFilter("");
    setPromoteError("");
    setPromotePhoneError("");
    setPromoteRoleError("");
    setPromoting(true);
  }

  function closePromoteModal() {
    setPromoting(false);
    setPromoteError("");
    setPromotePhoneError("");
    setPromoteRoleError("");
  }

  function togglePromoteBuilding(buildingId: number) {
    setPromoteForm((prev) => {
      const has = prev.building_ids.includes(buildingId);
      return {
        ...prev,
        building_ids: has
          ? prev.building_ids.filter((b) => b !== buildingId)
          : [...prev.building_ids, buildingId],
      };
    });
  }

  async function handleSubmitPromote(event: FormEvent) {
    event.preventDefault();
    if (numericId === null || !selected) return;
    // Phone is required by the backend; check client-side first for a
    // crisp inline error + focus before the round-trip.
    if (!promoteForm.phone.trim()) {
      setPromotePhoneError(t("customer_contacts.promote_error_phone_required"));
      promotePhoneRef.current?.focus();
      return;
    }
    setPromoteBusy(true);
    setPromoteError("");
    setPromotePhoneError("");
    setPromoteRoleError("");
    // SoT Addendum A.1 — a CUSTOMER_COMPANY_ADMIN promotion is routed to
    // the company-wide membership flag on the backend; it has NO
    // per-building rows, so we omit `building_ids` entirely for that role.
    const isCompanyAdminPromote =
      promoteForm.access_role === "CUSTOMER_COMPANY_ADMIN";
    try {
      const result = await promoteCustomerContact(numericId, selected.id, {
        access_role: promoteForm.access_role,
        // Empty selection => omit so the backend uses its default (the
        // contact's existing building links + legacy anchor). For a
        // company-admin promote, always omit.
        building_ids:
          !isCompanyAdminPromote && promoteForm.building_ids.length > 0
            ? promoteForm.building_ids
            : undefined,
        phone: promoteForm.phone.trim(),
      });
      const updated = result.contact;
      setContacts((prev) =>
        prev
          .map((c) => (c.id === updated.id ? updated : c))
          .sort((a, b) => a.full_name.localeCompare(b.full_name)),
      );
      setSelected(updated);
      setPromoting(false);
      toast.push({
        variant: "success",
        title:
          result.mode === "invited"
            ? t("customer_contacts.promote_toast_invited", {
                email: updated.email,
              })
            : t("customer_contacts.promote_toast_linked", {
                email: updated.email,
              }),
      });
    } catch (err) {
      // The promote endpoint returns `{detail, code}` — map known codes to
      // the relevant field; everything else (403, email/cross-customer
      // guards, …) falls back to a general modal error. Modal stays open.
      const code = axios.isAxiosError(err)
        ? (err.response?.data as { code?: string } | undefined)?.code
        : undefined;
      if (code === "contact_phone_invalid") {
        setPromotePhoneError(
          t("customer_contacts.promote_error_phone_invalid"),
        );
        promotePhoneRef.current?.focus();
      } else if (code === "contact_phone_required") {
        setPromotePhoneError(
          t("customer_contacts.promote_error_phone_required"),
        );
        promotePhoneRef.current?.focus();
      } else if (code === "invalid_access_role") {
        setPromoteRoleError(t("customer_contacts.promote_error_invalid_role"));
      } else {
        setPromoteError(getApiError(err));
      }
    } finally {
      setPromoteBusy(false);
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
          {/* Filter bar — building + free-text search are BOTH server-
              side (?building_id / ?search). */}
          <div
            className="customer-contacts-filter-bar"
            data-testid="customer-contacts-filter-bar"
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
              marginBottom: 14,
              alignItems: "flex-end",
            }}
          >
            <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
              <label
                className="field-label"
                htmlFor="customer-contacts-filter-building"
              >
                {t("customer_contacts.filter_building_label")}
              </label>
              <select
                id="customer-contacts-filter-building"
                className="field-select"
                data-testid="customer-contacts-filter-building"
                value={filterBuildingId === "" ? "" : String(filterBuildingId)}
                onChange={(event) => {
                  const v = event.target.value;
                  setFilterBuildingId(v === "" ? "" : Number(v));
                }}
              >
                <option value="">
                  {t("customer_contacts.filter_building_all")}
                </option>
                {linkedBuildings.map((link) => (
                  <option key={link.id} value={link.building_id}>
                    {link.building_name}
                  </option>
                ))}
              </select>
            </div>

            <div
              className="field"
              style={{ marginBottom: 0, flex: 1, minWidth: 200 }}
            >
              <label
                className="field-label"
                htmlFor="customer-contacts-filter-search"
              >
                {t("customer_contacts.filter_search_label")}
              </label>
              <input
                id="customer-contacts-filter-search"
                className="field-input"
                type="search"
                data-testid="customer-contacts-filter-search"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder={t("customer_contacts.filter_search_placeholder")}
              />
            </div>
          </div>

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
                        onClick={() => {
                          setSelected(contact);
                          setPermissionsPanelOpen(false);
                        }}
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
                    {t("customer_contacts.field_buildings")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-contact-detail-building"
                  >
                    {selected.linked_building_ids.length === 0
                      ? t("customer_contacts.building_company_wide")
                      : selected.linked_building_ids
                          .map(
                            (id) => buildingNameById.get(id) ?? `#${id}`,
                          )
                          .join(", ")}
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

              {/* Promote-to-user (Sprint 12B). A contact that is not yet a
                  user shows the "Make user / Send invitation" CTA; once
                  invited/linked it shows a read-only status badge instead
                  (never offer to promote again). */}
              <div
                style={{
                  marginTop: 16,
                  paddingTop: 16,
                  borderTop: "1px solid var(--border)",
                }}
              >
                {selected.promotion_status === "none" ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      data-testid="customer-contact-promote-button"
                      onClick={() => openPromoteModal(selected)}
                    >
                      {t("customer_contacts.promote_button")}
                    </button>
                    <div className="muted small" style={{ marginTop: 6 }}>
                      {t("customer_contacts.promote_button_hint")}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="detail-kv-row">
                      <span className="detail-kv-label">
                        {t("customer_contacts.field_user_status")}
                      </span>
                      <span className="detail-kv-val">
                        <span
                          className={
                            selected.promotion_status === "linked"
                              ? "badge badge-approved"
                              : "badge badge-waiting_customer_approval"
                          }
                          data-testid="customer-contact-user-status"
                          data-status={selected.promotion_status}
                        >
                          {selected.promotion_status === "linked"
                            ? t("customer_contacts.status_user")
                            : t("customer_contacts.status_invited")}
                        </span>
                      </span>
                    </div>
                    {/* Sprint 2 — a LINKED contact resolves to a real
                        customer user. The "Manage permissions" affordance
                        is now an IN-PLACE toggle that expands the override
                        editor downward under the user entry (no navigation
                        away). The panel reuses the matrix modal verbatim;
                        adding/removing buildings still lives on the full
                        matrix (a secondary link inside the panel). An
                        "invited" contact has no user yet, so nothing is
                        offered. */}
                    {selected.promotion_status === "linked" &&
                      selected.user !== null &&
                      numericId !== null && (
                        <div style={{ marginTop: 12 }}>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            data-testid="contact-permissions-toggle"
                            aria-expanded={permissionsPanelOpen}
                            onClick={() =>
                              setPermissionsPanelOpen((open) => !open)
                            }
                          >
                            {permissionsPanelOpen
                              ? t("customer_contacts.permissions_panel_hide")
                              : t("customer_contacts.manage_permissions_button")}
                          </button>
                          <div
                            className="muted small"
                            style={{ marginTop: 6 }}
                          >
                            {t("customer_contacts.manage_permissions_hint")}
                          </div>
                          {permissionsPanelOpen && (
                            <ContactPermissionsPanel
                              key={selected.user}
                              customerId={numericId}
                              userId={selected.user}
                            />
                          )}
                        </div>
                      )}
                  </>
                )}
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
              <span className="field-label">
                {t("customer_contacts.field_buildings")}
              </span>
              {linkedBuildings.length === 0 ? (
                <div className="muted small">
                  {t("customer_contacts.promote_no_buildings")}
                </div>
              ) : (
                <>
                  {/* #108 Part D — shared multi-select treatment. */}
                  <MultiSelectToolbar
                    selectedCount={form.building_ids.length}
                    onSelectAll={() =>
                      setForm((prev) => ({
                        ...prev,
                        building_ids: linkedBuildings.map(
                          (l) => l.building_id,
                        ),
                      }))
                    }
                    onClearAll={() =>
                      setForm((prev) => ({ ...prev, building_ids: [] }))
                    }
                    disabled={formBusy}
                    filterValue={buildingFilter}
                    onFilterChange={setBuildingFilter}
                    testIdPrefix="customer-contact-input-buildings"
                  />
                  <div
                    className="multi-select-list"
                    data-testid="customer-contact-input-buildings"
                  >
                    {linkedBuildings
                      .filter(
                        (link) =>
                          !buildingFilter.trim() ||
                          link.building_name
                            .toLowerCase()
                            .includes(buildingFilter.trim().toLowerCase()),
                      )
                      .map((link) => (
                        <label key={link.id}>
                          <input
                            type="checkbox"
                            className="checkbox-input"
                            checked={form.building_ids.includes(
                              link.building_id,
                            )}
                            onChange={() =>
                              toggleFormBuilding(link.building_id)
                            }
                            disabled={formBusy}
                            data-testid={`customer-contact-input-building-${link.building_id}`}
                          />
                          <span>{link.building_name}</span>
                        </label>
                      ))}
                  </div>
                </>
              )}
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("customer_contacts.field_building_optional")}
              </div>
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

      {/* Promote-to-user modal (Sprint 12B). Mirrors the create/edit modal
          shell — same overlay + <form>. The email is read-only (the
          invite/link target); the BACKEND decides INVITE vs LINK. */}
      {promoting && selected && (
        <div
          data-testid="customer-contact-promote-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("customer_contacts.promote_modal_title")}
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
            onSubmit={handleSubmitPromote}
            className="card"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>
              {t("customer_contacts.promote_modal_title")}
            </h3>
            <p
              className="muted small"
              style={{ marginTop: 0, marginBottom: 12 }}
            >
              {t("customer_contacts.promote_modal_subtitle")}
            </p>

            {promoteError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-contact-promote-error"
              >
                {promoteError}
              </div>
            )}

            {/* Email — read-only invite/link target. */}
            <div className="field">
              <label className="field-label" htmlFor="promote-email">
                {t("customer_contacts.field_email")}
              </label>
              <input
                id="promote-email"
                className="field-input"
                type="email"
                value={selected.email}
                readOnly
                disabled
                data-testid="customer-contact-promote-email"
              />
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("customer_contacts.promote_email_help")}
              </div>
            </div>

            {/* Access role — default CUSTOMER_USER. */}
            <div className="field">
              <label className="field-label" htmlFor="promote-access-role">
                {t("customer_contacts.promote_field_access_role")}
              </label>
              <select
                id="promote-access-role"
                className="field-select"
                value={promoteForm.access_role}
                onChange={(event) =>
                  setPromoteForm((prev) => ({
                    ...prev,
                    access_role: event.target.value as CustomerAccessRole,
                  }))
                }
                data-testid="customer-contact-promote-access-role"
                disabled={promoteBusy}
              >
                {ACCESS_ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>
                    {t(accessRoleLabelKey(role))}
                  </option>
                ))}
              </select>
              {promoteRoleError && (
                <div
                  className="alert-error login-error"
                  role="alert"
                  data-testid="customer-contact-promote-role-error"
                >
                  {promoteRoleError}
                </div>
              )}
            </div>

            {/* Building grant — pre-filled from the contact's links.
                Empty selection falls back to the backend default.
                SoT Addendum A.1: a CUSTOMER_COMPANY_ADMIN promote is
                company-wide (no per-building rows), so the grid is hidden
                and a company-wide note is shown instead. */}
            {promoteForm.access_role === "CUSTOMER_COMPANY_ADMIN" ? (
              <div
                className="field"
                data-testid="customer-contact-promote-company-admin-note"
              >
                <span className="field-label">
                  {t("customer_contacts.promote_field_buildings")}
                </span>
                <div className="muted small">
                  {t("customer_people.company_admin.all_buildings_caption")}
                </div>
              </div>
            ) : (
              <div className="field">
                <span className="field-label">
                  {t("customer_contacts.promote_field_buildings")}
                </span>
                {linkedBuildings.length === 0 ? (
                  <div className="muted small">
                    {t("customer_contacts.promote_no_buildings")}
                  </div>
                ) : (
                  <>
                    {/* #108 Part D — shared multi-select treatment. */}
                    <MultiSelectToolbar
                      selectedCount={promoteForm.building_ids.length}
                      onSelectAll={() =>
                        setPromoteForm((prev) => ({
                          ...prev,
                          building_ids: linkedBuildings.map(
                            (l) => l.building_id,
                          ),
                        }))
                      }
                      onClearAll={() =>
                        setPromoteForm((prev) => ({
                          ...prev,
                          building_ids: [],
                        }))
                      }
                      disabled={promoteBusy}
                      filterValue={promoteBuildingFilter}
                      onFilterChange={setPromoteBuildingFilter}
                      testIdPrefix="customer-contact-promote-buildings"
                    />
                    <div
                      className="multi-select-list"
                      data-testid="customer-contact-promote-buildings"
                    >
                      {linkedBuildings
                        .filter(
                          (link) =>
                            !promoteBuildingFilter.trim() ||
                            link.building_name
                              .toLowerCase()
                              .includes(
                                promoteBuildingFilter.trim().toLowerCase(),
                              ),
                        )
                        .map((link) => (
                          <label key={link.id}>
                            <input
                              type="checkbox"
                              className="checkbox-input"
                              checked={promoteForm.building_ids.includes(
                                link.building_id,
                              )}
                              onChange={() =>
                                togglePromoteBuilding(link.building_id)
                              }
                              disabled={promoteBusy}
                              data-testid={`customer-contact-promote-building-${link.building_id}`}
                            />
                            <span>{link.building_name}</span>
                          </label>
                        ))}
                    </div>
                  </>
                )}
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_contacts.promote_field_buildings_hint")}
                </div>
              </div>
            )}

            {/* Phone — required (valid NL number). */}
            <div className="field">
              <label className="field-label" htmlFor="promote-phone">
                {t("customer_contacts.field_phone")} *
              </label>
              <input
                id="promote-phone"
                ref={promotePhoneRef}
                className="field-input"
                type="tel"
                value={promoteForm.phone}
                onChange={(event) =>
                  setPromoteForm((prev) => ({
                    ...prev,
                    phone: event.target.value,
                  }))
                }
                data-testid="customer-contact-promote-phone"
                disabled={promoteBusy}
                aria-invalid={promotePhoneError ? true : undefined}
              />
              {promotePhoneError ? (
                <div
                  className="alert-error login-error"
                  role="alert"
                  data-testid="customer-contact-promote-phone-error"
                >
                  {promotePhoneError}
                </div>
              ) : (
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_contacts.promote_field_phone_hint")}
                </div>
              )}
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
                onClick={closePromoteModal}
                disabled={promoteBusy}
                data-testid="customer-contact-promote-cancel"
              >
                {t("customer_contacts.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={promoteBusy}
                data-testid="customer-contact-promote-submit"
              >
                {promoteBusy
                  ? t("admin_form.saving")
                  : t("customer_contacts.promote_submit")}
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
