// Sprint 28 Batch 6 — Create Extra Work cart UI.
//
// Replaces the Sprint 26B single-line form with a shopping-cart
// workflow per the 2026-05-15 stakeholder meeting (§4):
//   * Customer composes a request by adding multiple service catalog
//     items to a cart, each with its own quantity, requested date,
//     and optional note.
//   * Submission produces one parent request with N line items.
//   * Backend routes the request based on whether every line has an
//     active CustomerServicePrice (INSTANT) or not (PROPOSAL).
//
// View-first compliance: the form itself is the "Create" surface
// (an add page is intentionally a form). After submission the
// result panel is read-only.
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listServices } from "../api/admin";
import { api, getApiError } from "../api/client";
import { createExtraWork } from "../api/extraWork";
import type {
  Building,
  Customer,
  ExtraWorkCategory,
  ExtraWorkRequestDetail,
  ExtraWorkUrgency,
  PaginatedResponse,
  Service,
} from "../api/types";


interface ParentFormState {
  building: string;
  customer: string;
  title: string;
  description: string;
  category: ExtraWorkCategory;
  category_other_text: string;
  urgency: ExtraWorkUrgency;
  preferred_date: string;
}

interface CartLineState {
  tempId: string;
  serviceId: string;
  quantity: string;
  requestedDate: string;
  customerNote: string;
}

const EMPTY_PARENT: ParentFormState = {
  building: "",
  customer: "",
  title: "",
  description: "",
  category: "DEEP_CLEANING",
  category_other_text: "",
  urgency: "NORMAL",
  preferred_date: "",
};

const CATEGORY_VALUES: ExtraWorkCategory[] = [
  "DEEP_CLEANING",
  "WINDOW_CLEANING",
  "FLOOR_MAINTENANCE",
  "SANITARY_SERVICE",
  "WASTE_REMOVAL",
  "FURNITURE_MOVING",
  "EVENT_CLEANING",
  "EMERGENCY_CLEANING",
  "OTHER",
];

const URGENCY_VALUES: ExtraWorkUrgency[] = ["NORMAL", "HIGH", "URGENT"];

const CATEGORY_I18N_KEY: Record<ExtraWorkCategory, string> = {
  DEEP_CLEANING: "category.deep_cleaning",
  WINDOW_CLEANING: "category.window_cleaning",
  FLOOR_MAINTENANCE: "category.floor_maintenance",
  SANITARY_SERVICE: "category.sanitary_service",
  WASTE_REMOVAL: "category.waste_removal",
  FURNITURE_MOVING: "category.furniture_moving",
  EVENT_CLEANING: "category.event_cleaning",
  EMERGENCY_CLEANING: "category.emergency_cleaning",
  OTHER: "category.other",
};

const URGENCY_I18N_KEY: Record<ExtraWorkUrgency, string> = {
  NORMAL: "urgency.normal",
  HIGH: "urgency.high",
  URGENT: "urgency.urgent",
};

// Sprint 14 helper — match a customer to a building via legacy
// Customer.building OR the M:N linked_building_ids list.
function customerMatchesBuilding(
  customer: Customer,
  buildingId: number,
): boolean {
  return (
    customer.building === buildingId ||
    (customer.linked_building_ids?.includes(buildingId) ?? false)
  );
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function nextTempId(): string {
  // Lightweight client-only id — no crypto needed because this never
  // leaves the browser.
  return `line-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function emptyCartLine(): CartLineState {
  return {
    tempId: nextTempId(),
    serviceId: "",
    quantity: "1",
    requestedDate: todayISO(),
    customerNote: "",
  };
}


export function CreateExtraWorkPage() {
  const { t } = useTranslation(["extra_work", "common"]);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<ParentFormState>(EMPTY_PARENT);
  const [cartLines, setCartLines] = useState<CartLineState[]>([emptyCartLine()]);

  // Post-submit result state — once present, the form is collapsed
  // into a read-only confirmation panel.
  const [result, setResult] = useState<ExtraWorkRequestDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [buildingResponse, customerResponse, servicesResponse] =
          await Promise.all([
            api.get<PaginatedResponse<Building>>("/buildings/", {
              params: { page_size: 200 },
            }),
            api.get<PaginatedResponse<Customer>>("/customers/", {
              params: { page_size: 200 },
            }),
            // Sprint 28 Batch 5 — reuse the catalog helper. Only active
            // services are eligible for the cart.
            listServices({ is_active: true }),
          ]);
        if (cancelled) return;
        setBuildings(buildingResponse.data.results);
        setCustomers(customerResponse.data.results);
        setServices(servicesResponse);

        const firstBuilding = buildingResponse.data.results[0];
        const firstCustomer = firstBuilding
          ? customerResponse.data.results.find((customer) =>
              customerMatchesBuilding(customer, firstBuilding.id),
            )
          : undefined;
        setForm((current) => ({
          ...current,
          building:
            current.building || (firstBuilding ? String(firstBuilding.id) : ""),
          customer:
            current.customer || (firstCustomer ? String(firstCustomer.id) : ""),
        }));
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoadingOptions(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredCustomers = useMemo(() => {
    if (!form.building) return customers;
    const buildingId = Number(form.building);
    return customers.filter((customer) =>
      customerMatchesBuilding(customer, buildingId),
    );
  }, [customers, form.building]);

  const filteredBuildings = useMemo(() => {
    if (!form.customer) return buildings;
    const c = customers.find((x) => String(x.id) === form.customer);
    if (!c) return buildings;
    return buildings.filter((b) => customerMatchesBuilding(c, b.id));
  }, [buildings, customers, form.customer]);

  // Auto-select the only matching customer when there's exactly one.
  useEffect(() => {
    if (!form.building) return;
    if (form.customer) return;
    if (filteredCustomers.length === 1) {
      setForm((current) => ({
        ...current,
        customer: String(filteredCustomers[0].id),
      }));
    }
  }, [form.building, form.customer, filteredCustomers]);

  useEffect(() => {
    if (!form.customer) return;
    const stillValid = filteredCustomers.some(
      (customer) => String(customer.id) === form.customer,
    );
    if (!stillValid) {
      setForm((current) => ({
        ...current,
        customer: filteredCustomers[0]
          ? String(filteredCustomers[0].id)
          : "",
      }));
    }
  }, [filteredCustomers, form.customer]);

  useEffect(() => {
    if (!form.building) return;
    const stillValid = filteredBuildings.some(
      (b) => String(b.id) === form.building,
    );
    if (!stillValid) {
      setForm((current) => ({
        ...current,
        building: filteredBuildings[0]
          ? String(filteredBuildings[0].id)
          : "",
      }));
    }
  }, [filteredBuildings, form.building]);

  function update<K extends keyof ParentFormState>(
    name: K,
    value: ParentFormState[K],
  ) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function addCartLine() {
    setCartLines((current) => [...current, emptyCartLine()]);
  }

  function removeCartLine(tempId: string) {
    setCartLines((current) => current.filter((l) => l.tempId !== tempId));
  }

  function updateCartLine<K extends keyof CartLineState>(
    tempId: string,
    field: K,
    value: CartLineState[K],
  ) {
    setCartLines((current) =>
      current.map((line) =>
        line.tempId === tempId ? { ...line, [field]: value } : line,
      ),
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!form.title.trim()) {
      setError(t("create.error_title_required"));
      return;
    }
    if (!form.description.trim()) {
      setError(t("create.error_description_required"));
      return;
    }
    if (!form.building || !form.customer) {
      setError(t("create.error_building_customer_required"));
      return;
    }
    if (form.category === "OTHER" && !form.category_other_text.trim()) {
      setError(t("create.error_category_other_required"));
      return;
    }

    // Cart validation.
    if (cartLines.length === 0) {
      setError(t("create.error_empty_cart"));
      return;
    }
    const seenServiceIds = new Set<number>();
    for (const line of cartLines) {
      if (!line.serviceId) {
        setError(t("create.error_line_service_required"));
        return;
      }
      const svcId = Number(line.serviceId);
      if (seenServiceIds.has(svcId)) {
        setError(t("create.error_duplicate_service"));
        return;
      }
      seenServiceIds.add(svcId);
      const qtyNum = Number(line.quantity);
      if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
        setError(t("create.error_line_quantity_invalid"));
        return;
      }
      if (!line.requestedDate) {
        setError(t("create.error_line_requested_date_required"));
        return;
      }
      const svc = services.find((s) => s.id === svcId);
      if (svc && !svc.is_active) {
        setError(t("create.error_inactive_service"));
        return;
      }
    }

    setSubmitting(true);
    try {
      const created = await createExtraWork({
        building: Number(form.building),
        customer: Number(form.customer),
        title: form.title.trim(),
        description: form.description.trim(),
        category: form.category,
        category_other_text:
          form.category === "OTHER" ? form.category_other_text.trim() : "",
        urgency: form.urgency,
        preferred_date: form.preferred_date || null,
        line_items: cartLines.map((line) => ({
          service: Number(line.serviceId),
          quantity: line.quantity,
          requested_date: line.requestedDate,
          customer_note: line.customerNote.trim() || undefined,
        })),
      });
      setResult(created);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const noOptions =
    !loadingOptions && (buildings.length === 0 || customers.length === 0);

  // ----- Result panel (read-only confirmation) -----
  if (result) {
    const isInstant = result.routing_decision === "INSTANT";
    return (
      <div data-testid="extra-work-create-result">
        <div className="page-header">
          <div>
            <Link to="/extra-work" className="link-back">
              <ChevronLeft size={14} strokeWidth={2.5} />
              {t("back_to_extra_work")}
            </Link>
            <h2 className="page-title">{t("result.heading")}</h2>
          </div>
        </div>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="form-section">
            <div
              className={isInstant ? "alert-info" : "alert-info"}
              role="status"
              data-testid={
                isInstant
                  ? "extra-work-result-instant"
                  : "extra-work-result-proposal"
              }
            >
              {isInstant
                ? t("result.instant_processing")
                : t("result.proposal_pending")}
            </div>
            <div
              className="status-actions"
              style={{ display: "flex", gap: 8, marginTop: 12 }}
            >
              <Link to="/extra-work" className="btn btn-secondary btn-sm">
                {t("result.back_to_list")}
              </Link>
              <Link
                to={`/extra-work/${result.id}`}
                className="btn btn-primary btn-sm"
                data-testid="extra-work-result-view-link"
              >
                {t("result.view_request")}
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ----- Form -----
  return (
    <div data-testid="extra-work-create-page">
      <div className="page-header">
        <div>
          <Link to="/extra-work" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_extra_work")}
          </Link>
          <h2 className="page-title">{t("create.page_title")}</h2>
          <p className="page-sub">{t("create.page_subtitle")}</p>
        </div>
      </div>

      {loadingOptions && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {noOptions && !error && (
        <div className="alert-error" style={{ marginBottom: 16 }}>
          {t("create.error_no_access")}
        </div>
      )}

      {error && (
        <div
          className="alert-error"
          style={{ marginBottom: 16 }}
          role="alert"
          data-testid="extra-work-create-error"
        >
          {error}
        </div>
      )}

      <form className="create-layout" onSubmit={handleSubmit}>
        <div className="card create-main">
          <div className="form-section">
            <div className="form-section-title">
              {t("create.parent_section_title")}
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-building">
                  {t("create.field_building")}
                </label>
                <select
                  id="ew-building"
                  data-testid="extra-work-create-building"
                  className="field-select"
                  value={form.building}
                  onChange={(event) => update("building", event.target.value)}
                  disabled={filteredBuildings.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("create.field_building_placeholder")}
                  </option>
                  {filteredBuildings.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ew-customer">
                  {t("create.field_customer")}
                </label>
                <select
                  id="ew-customer"
                  data-testid="extra-work-create-customer"
                  className="field-select"
                  value={form.customer}
                  onChange={(event) => update("customer", event.target.value)}
                  disabled={filteredCustomers.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("create.field_customer_placeholder")}
                  </option>
                  {filteredCustomers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title">
              {t("create.what_section_title")}
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-category">
                  {t("create.field_category")}
                </label>
                <select
                  id="ew-category"
                  className="field-select"
                  value={form.category}
                  onChange={(event) =>
                    update("category", event.target.value as ExtraWorkCategory)
                  }
                >
                  {CATEGORY_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {t(CATEGORY_I18N_KEY[value])}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ew-urgency">
                  {t("create.field_urgency")}
                </label>
                <select
                  id="ew-urgency"
                  className="field-select"
                  value={form.urgency}
                  onChange={(event) =>
                    update("urgency", event.target.value as ExtraWorkUrgency)
                  }
                >
                  {URGENCY_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {t(URGENCY_I18N_KEY[value])}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {form.category === "OTHER" && (
              <div className="field">
                <label className="field-label" htmlFor="ew-category-other">
                  {t("create.field_category_other_text")}
                </label>
                <input
                  id="ew-category-other"
                  className="field-input"
                  type="text"
                  maxLength={128}
                  placeholder={t(
                    "create.field_category_other_text_placeholder",
                  )}
                  value={form.category_other_text}
                  onChange={(event) =>
                    update("category_other_text", event.target.value)
                  }
                  required
                />
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="ew-title">
                {t("create.field_title")}
              </label>
              <input
                id="ew-title"
                data-testid="extra-work-create-title"
                className="field-input"
                type="text"
                maxLength={255}
                placeholder={t("create.field_title_placeholder")}
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
                required
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-description">
                {t("create.field_description")}
              </label>
              <textarea
                id="ew-description"
                data-testid="extra-work-create-description"
                className="field-textarea"
                placeholder={t("create.field_description_helper")}
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                required
              />
              <div
                className="muted small"
                style={{ marginTop: 6, lineHeight: 1.4 }}
              >
                {t("create.field_description_helper")}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-preferred-date">
                {t("create.field_preferred_date")}
              </label>
              <input
                id="ew-preferred-date"
                className="field-input"
                type="date"
                value={form.preferred_date}
                onChange={(event) =>
                  update("preferred_date", event.target.value)
                }
              />
            </div>
          </div>

          {/* ----- Cart ----- */}
          <div className="form-section" data-testid="extra-work-create-cart">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <div className="form-section-title" style={{ margin: 0 }}>
                {t("create.cart_section_title")}
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={addCartLine}
                data-testid="extra-work-create-add-line"
              >
                <Plus size={14} strokeWidth={2.2} />
                <span style={{ marginLeft: 6 }}>
                  {t("create.add_line_button")}
                </span>
              </button>
            </div>
            <div className="muted small" style={{ marginBottom: 12 }}>
              {t("create.cart_section_helper")}
            </div>

            {cartLines.length === 0 && (
              <div
                className="muted small"
                data-testid="extra-work-create-cart-empty"
              >
                {t("create.cart_empty")}
              </div>
            )}

            {cartLines.map((line, index) => (
              <div
                key={line.tempId}
                data-testid="extra-work-create-cart-line"
                className="card"
                style={{
                  padding: 12,
                  marginBottom: 10,
                  background: "transparent",
                  border: "1px solid var(--border, #e5e7eb)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 8,
                  }}
                >
                  <div
                    style={{ fontWeight: 600 }}
                    data-testid={`extra-work-create-cart-line-${index}`}
                  >
                    #{index + 1}
                  </div>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => removeCartLine(line.tempId)}
                    data-testid={`extra-work-create-remove-line-${index}`}
                  >
                    <Trash2 size={14} strokeWidth={2.2} />
                    <span style={{ marginLeft: 6 }}>
                      {t("create.remove_line_button")}
                    </span>
                  </button>
                </div>

                <div className="form-2col">
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor={`ew-line-service-${index}`}
                    >
                      {t("create.line_field_service")}
                    </label>
                    <select
                      id={`ew-line-service-${index}`}
                      data-testid={`extra-work-create-line-service-${index}`}
                      className="field-select"
                      value={line.serviceId}
                      onChange={(event) =>
                        updateCartLine(
                          line.tempId,
                          "serviceId",
                          event.target.value,
                        )
                      }
                      required
                    >
                      <option value="" disabled>
                        {t("create.line_field_service_placeholder")}
                      </option>
                      {services.map((svc) => (
                        <option key={svc.id} value={svc.id}>
                          {svc.category_name
                            ? `${svc.category_name} — ${svc.name}`
                            : svc.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor={`ew-line-quantity-${index}`}
                    >
                      {t("create.line_field_quantity")}
                    </label>
                    <input
                      id={`ew-line-quantity-${index}`}
                      data-testid={`extra-work-create-line-quantity-${index}`}
                      className="field-input"
                      type="number"
                      step="0.01"
                      min="0"
                      value={line.quantity}
                      onChange={(event) =>
                        updateCartLine(
                          line.tempId,
                          "quantity",
                          event.target.value,
                        )
                      }
                      required
                    />
                  </div>
                </div>

                <div className="form-2col">
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor={`ew-line-date-${index}`}
                    >
                      {t("create.line_field_requested_date")}
                    </label>
                    <input
                      id={`ew-line-date-${index}`}
                      data-testid={`extra-work-create-line-date-${index}`}
                      className="field-input"
                      type="date"
                      value={line.requestedDate}
                      onChange={(event) =>
                        updateCartLine(
                          line.tempId,
                          "requestedDate",
                          event.target.value,
                        )
                      }
                      required
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor={`ew-line-note-${index}`}
                    >
                      {t("create.line_field_customer_note")}
                    </label>
                    <input
                      id={`ew-line-note-${index}`}
                      data-testid={`extra-work-create-line-note-${index}`}
                      className="field-input"
                      type="text"
                      maxLength={500}
                      placeholder={t(
                        "create.line_field_customer_note_placeholder",
                      )}
                      value={line.customerNote}
                      onChange={(event) =>
                        updateCartLine(
                          line.tempId,
                          "customerNote",
                          event.target.value,
                        )
                      }
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div
            className="form-actions"
            style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}
          >
            <Link to="/extra-work" className="btn btn-secondary btn-sm">
              {t("create.cancel_button")}
            </Link>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              data-testid="extra-work-create-submit"
              disabled={submitting || loadingOptions || noOptions}
            >
              {submitting ? t("create.submitting") : t("create.submit_button")}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
