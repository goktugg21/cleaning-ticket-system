import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createCustomerPrice,
  deleteCustomerPrice,
  getCustomer,
  listCustomerPrices,
  listServices,
  updateCustomerPrice,
} from "../../api/admin";
import type {
  CustomerAdmin,
  CustomerServicePrice,
  CustomerServicePriceCreatePayload,
  Service,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";

/**
 * Sprint 28 Batch 5 — Per-customer contract pricing.
 *
 * Customer-scoped sidebar entry. The page lists every
 * `CustomerServicePrice` row for the URL's customer, grouped by
 * service for readability. View-first per
 * `docs/product/meeting-2026-05-15-system-requirements.md` §3:
 *   - list rows are read-only
 *   - clicking a row opens a read-only detail panel
 *   - Add / Edit / Delete are explicit modal actions
 *
 * Only an active row triggers the instant-ticket path (Batch 7). The
 * page intentionally does NOT resolve "the effective price for service
 * X right now" — that is the backend resolver's job. We just expose
 * the raw rows for the admin to manage.
 *
 * Permission: SUPER_ADMIN + COMPANY_ADMIN reach this route via
 * `AdminRoute` (see `App.tsx`). Backend re-gates with
 * `IsSuperAdminOrCompanyAdminForCustomerProvider` on every list /
 * create / detail call.
 */

interface PriceFormState {
  service: number | "";
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to: string; // empty string = open-ended
  is_active: boolean;
}

function todayISO(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function buildEmptyForm(): PriceFormState {
  return {
    service: "",
    unit_price: "0.00",
    vat_pct: "21.00",
    valid_from: todayISO(),
    valid_to: "",
    is_active: true,
  };
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

function formatDateOnly(value: string, locale: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}

export function CustomerPricingPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation("common");
  const numericId = useMemo(() => {
    if (!id) return null;
    const n = Number(id);
    return Number.isFinite(n) ? n : null;
  }, [id]);

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [prices, setPrices] = useState<CustomerServicePrice[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [selected, setSelected] = useState<CustomerServicePrice | null>(null);

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [form, setForm] = useState<PriceFormState>(buildEmptyForm);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<CustomerServicePrice | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // Initial parallel load — customer (for title), pricing list,
  // service list (for the modal dropdown — filtered to active so
  // admins do not accidentally price a retired service).
  useEffect(() => {
    const cancelled = { current: false };
    async function load(customerId: number) {
      try {
        const [customerData, pricesData, servicesData] = await Promise.all([
          getCustomer(customerId),
          listCustomerPrices(customerId),
          listServices({ is_active: true }),
        ]);
        if (cancelled.current) return;
        setCustomer(customerData);
        setPrices(pricesData);
        setServices(servicesData);
        setLoading(false);
      } catch (err) {
        if (!cancelled.current) {
          setLoadError(getApiError(err));
          setLoading(false);
        }
      }
    }
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled.current) {
          setLoadError(t("customer_pricing.load_error"));
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
    setForm({
      ...buildEmptyForm(),
      service: services.length > 0 ? services[0].id : "",
      vat_pct:
        services.length > 0 ? services[0].default_vat_pct : "21.00",
    });
    setFormError("");
  }

  function openEditModal(price: CustomerServicePrice) {
    setMode("edit");
    setForm({
      service: price.service,
      unit_price: price.unit_price,
      vat_pct: price.vat_pct,
      valid_from: price.valid_from,
      valid_to: price.valid_to ?? "",
      is_active: price.is_active,
    });
    setFormError("");
  }

  function closeFormModal() {
    setMode(null);
    setForm(buildEmptyForm());
    setFormError("");
  }

  async function handleSubmitForm(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    if (form.service === "") {
      setFormError(t("customer_pricing.error_service_required"));
      return;
    }
    const priceNumber = Number(form.unit_price);
    if (!Number.isFinite(priceNumber) || priceNumber < 0) {
      setFormError(t("customer_pricing.error_price_invalid"));
      return;
    }
    const vatNumber = Number(form.vat_pct);
    if (!Number.isFinite(vatNumber) || vatNumber < 0) {
      setFormError(t("customer_pricing.error_vat_invalid"));
      return;
    }
    if (!form.valid_from) {
      setFormError(t("customer_pricing.error_valid_from_required"));
      return;
    }
    // Client-side check matches the backend validator: valid_to (when
    // provided) must be >= valid_from. The backend still owns the
    // hard rule — this only short-circuits the round-trip.
    if (form.valid_to && form.valid_to < form.valid_from) {
      setFormError(t("customer_pricing.error_valid_to_before_valid_from"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    const payload: CustomerServicePriceCreatePayload = {
      service: Number(form.service),
      unit_price: form.unit_price.trim(),
      vat_pct: form.vat_pct.trim(),
      valid_from: form.valid_from,
      valid_to: form.valid_to === "" ? null : form.valid_to,
      is_active: form.is_active,
    };
    try {
      if (mode === "create") {
        const created = await createCustomerPrice(numericId, payload);
        setPrices((prev) => [created, ...prev]);
        closeFormModal();
      } else if (mode === "edit" && selected) {
        const updated = await updateCustomerPrice(
          numericId,
          selected.id,
          payload,
        );
        setPrices((prev) =>
          prev.map((p) => (p.id === updated.id ? updated : p)),
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

  function openDeleteDialog(price: CustomerServicePrice) {
    setDeleteTarget(price);
    deleteDialogRef.current?.open();
  }

  async function handleConfirmDelete() {
    if (numericId === null || !deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteCustomerPrice(numericId, deleteTarget.id);
      setPrices((prev) => prev.filter((p) => p.id !== deleteTarget.id));
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

  const serviceNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const s of services) {
      map.set(s.id, s.name);
    }
    return map;
  }, [services]);

  // Build the service name shown in the table — prefer the embedded
  // `service_name` (always present) but fall back to the dropdown
  // lookup if a stale row references a now-renamed service.
  function resolveServiceName(price: CustomerServicePrice): string {
    if (price.service_name) return price.service_name;
    return serviceNameById.get(price.service) ?? `#${price.service}`;
  }

  const customerName = customer?.name ?? "";

  return (
    <div data-testid="customer-pricing-page">
      <Link
        to={`/admin/customers/${numericId ?? ""}`}
        className="link-back"
        data-testid="customer-pricing-back"
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
              ? `${customerName} · ${t("customer_pricing.page_title")}`
              : t("customer_pricing.page_title")}
          </h2>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="customer-pricing-add-button"
            onClick={openCreateModal}
            disabled={loading || numericId === null || services.length === 0}
            title={
              services.length === 0
                ? t("customer_pricing.no_services_hint")
                : undefined
            }
          >
            {t("customer_pricing.add_button")}
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
        <>
          <div className="card" data-testid="customer-pricing-list">
            {prices.length === 0 ? (
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="customer-pricing-empty"
              >
                <h3 style={{ marginBottom: 8 }}>
                  {t("customer_pricing.empty_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("customer_pricing.empty_description")}
                </p>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("customer_pricing.col_service")}</th>
                      <th>{t("customer_pricing.col_unit_price")}</th>
                      <th>{t("customer_pricing.col_vat_pct")}</th>
                      <th>{t("customer_pricing.col_valid_from")}</th>
                      <th>{t("customer_pricing.col_valid_to")}</th>
                      <th>{t("customer_pricing.col_active")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {prices.map((price) => (
                      <tr
                        key={price.id}
                        data-testid="customer-pricing-row"
                        data-price-id={price.id}
                        onClick={() => setSelected(price)}
                      >
                        <td>{resolveServiceName(price)}</td>
                        <td>{price.unit_price}</td>
                        <td>{price.vat_pct}</td>
                        <td>{formatDateOnly(price.valid_from, dateLocale)}</td>
                        <td>
                          {price.valid_to === null
                            ? t("customer_pricing.valid_to_open_ended")
                            : formatDateOnly(price.valid_to, dateLocale)}
                        </td>
                        <td>
                          {price.is_active
                            ? t("admin.status_active")
                            : t("admin.status_inactive")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {selected && (
            <section
              className="card"
              data-testid="customer-pricing-detail"
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
                    {t("customer_pricing.detail_title")}
                  </div>
                  <h3 className="section-title" style={{ margin: 0 }}>
                    {resolveServiceName(selected)}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-pricing-edit-button"
                    onClick={() => openEditModal(selected)}
                  >
                    {t("customer_pricing.edit_button")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-pricing-delete-button"
                    onClick={() => openDeleteDialog(selected)}
                  >
                    {t("customer_pricing.delete_button")}
                  </button>
                </div>
              </div>

              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_unit_price")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-pricing-detail-unit-price"
                  >
                    {selected.unit_price}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_vat_pct")}
                  </span>
                  <span className="detail-kv-val">{selected.vat_pct}</span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_valid_from")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDateOnly(selected.valid_from, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_valid_to")}
                  </span>
                  <span className="detail-kv-val">
                    {selected.valid_to === null
                      ? t("customer_pricing.valid_to_open_ended")
                      : formatDateOnly(selected.valid_to, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_active")}
                  </span>
                  <span className="detail-kv-val">
                    {selected.is_active
                      ? t("admin.status_active")
                      : t("admin.status_inactive")}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.field_created_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selected.created_at, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.field_updated_at")}
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
          `mode` drives the title + submit handler. */}
      {mode !== null && (
        <div
          data-testid="customer-pricing-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            mode === "create"
              ? t("customer_pricing.add_modal_title")
              : t("customer_pricing.edit_modal_title")
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
              maxWidth: 600,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {mode === "create"
                ? t("customer_pricing.add_modal_title")
                : t("customer_pricing.edit_modal_title")}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-pricing-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="price-service">
                {t("customer_pricing.field_service")} *
              </label>
              <select
                id="price-service"
                className="field-select"
                value={form.service === "" ? "" : String(form.service)}
                onChange={(event) => {
                  const v = event.target.value;
                  setForm((prev) => ({
                    ...prev,
                    service: v === "" ? "" : Number(v),
                  }));
                }}
                data-testid="customer-pricing-input-service"
                required
                disabled={formBusy || mode === "edit"}
              >
                <option value="">
                  {t("customer_pricing.field_service_placeholder")}
                </option>
                {services.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              {mode === "edit" && (
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_pricing.field_service_locked_hint")}
                </div>
              )}
            </div>

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="price-unit-price">
                  {t("customer_pricing.field_unit_price")} *
                </label>
                <input
                  id="price-unit-price"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.unit_price}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      unit_price: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-unit-price"
                  required
                  disabled={formBusy}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="price-vat-pct">
                  {t("customer_pricing.field_vat_pct")} *
                </label>
                <input
                  id="price-vat-pct"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.vat_pct}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      vat_pct: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-vat-pct"
                  required
                  disabled={formBusy}
                />
              </div>
            </div>

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="price-valid-from">
                  {t("customer_pricing.field_valid_from")} *
                </label>
                <input
                  id="price-valid-from"
                  className="field-input"
                  type="date"
                  value={form.valid_from}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      valid_from: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-valid-from"
                  required
                  disabled={formBusy}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="price-valid-to">
                  {t("customer_pricing.field_valid_to")}
                </label>
                <input
                  id="price-valid-to"
                  className="field-input"
                  type="date"
                  value={form.valid_to}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      valid_to: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-valid-to"
                  disabled={formBusy}
                />
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_pricing.field_valid_to_hint")}
                </div>
              </div>
            </div>

            <div className="field">
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="customer-pricing-input-is-active"
                  disabled={formBusy}
                />
                <span>{t("customer_pricing.field_is_active")}</span>
              </label>
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
                data-testid="customer-pricing-modal-cancel"
              >
                {t("customer_pricing.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="customer-pricing-modal-save"
              >
                {formBusy
                  ? t("admin_form.saving")
                  : t("customer_pricing.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("customer_pricing.delete_confirm_title")}
        body={t("customer_pricing.delete_confirm_body")}
        confirmLabel={t("customer_pricing.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
        busy={deleteBusy}
        destructive
      />
    </div>
  );
}
