// Sprint 26C — Extra Work detail page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n
// namespace; also renders the new cart `line_items` array and the
// `routing_decision` badge. The pricing-proposal panel, workflow
// transitions, and provider override block are functionally
// unchanged — only the user-visible strings were threaded through
// `t()`.
//
// Role-aware view:
//   * CUSTOMER_USER: details, pricing line items (without
//     internal_cost_note), totals, and the customer approve/reject
//     CTAs when status === PRICING_PROPOSED and the backend's
//     allowed_next_statuses include the corresponding transition.
//   * Provider operators (SUPER_ADMIN / COMPANY_ADMIN /
//     BUILDING_MANAGER): all of the above PLUS the pricing-line-
//     item create form, transition CTAs (UNDER_REVIEW,
//     PRICING_PROPOSED, CANCELLED), and a customer-override block
//     with mandatory reason.
//
// The backend computes pricing totals and gates all transitions.
// The frontend is defense-in-depth only — it renders only what the
// backend's allowed_next_statuses field says.
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listCustomerContacts } from "../api/admin";
import { getApiError } from "../api/client";
import {
  createExtraWorkPricingItem,
  deleteExtraWorkPricingItem,
  getExtraWork,
  transitionExtraWork,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import type {
  Contact,
  ExtraWorkCategory,
  ExtraWorkRequestDetail,
  ExtraWorkStatus,
  ExtraWorkUnitType,
  ExtraWorkUrgency,
  Role,
  ServiceUnitType,
} from "../api/types";


const STATUS_I18N_KEY: Record<ExtraWorkStatus, string> = {
  REQUESTED: "status.requested",
  UNDER_REVIEW: "status.under_review",
  PRICING_PROPOSED: "status.pricing_proposed",
  CUSTOMER_APPROVED: "status.customer_approved",
  CUSTOMER_REJECTED: "status.customer_rejected",
  CANCELLED: "status.cancelled",
};

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

// Sprint 26C ExtraWorkUnitType and Sprint 28 B5 ServiceUnitType
// share the same storage values; one i18n map covers both.
const UNIT_TYPE_I18N_KEY: Record<ExtraWorkUnitType | ServiceUnitType, string> = {
  HOURS: "unit_type.hours",
  SQUARE_METERS: "unit_type.square_meters",
  FIXED: "unit_type.fixed",
  ITEM: "unit_type.item",
  OTHER: "unit_type.other",
};

const UNIT_TYPE_VALUES: ExtraWorkUnitType[] = [
  "HOURS",
  "SQUARE_METERS",
  "FIXED",
  "ITEM",
  "OTHER",
];

const PROVIDER_ROLES: Set<Role> = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
]);


function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, {
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

function fmtMoney(value: string | null | undefined): string {
  if (!value) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toFixed(2);
}


export function ExtraWorkDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();
  const { t } = useTranslation(["extra_work", "common"]);

  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Sprint 28 Batch 4 — read-only Customer Contacts panel. Backend
  // `IsSuperAdminOrCompanyAdminForCompany` gate on the contacts list
  // rejects everyone else with 403; mirror the gate here so
  // BUILDING_MANAGER / CUSTOMER_USER never emit the call.
  const canSeeCustomerContacts =
    me?.role === "SUPER_ADMIN" || me?.role === "COMPANY_ADMIN";
  const [customerContacts, setCustomerContacts] = useState<Contact[]>([]);

  // Pricing-line-item form (provider only).
  const [pricingForm, setPricingForm] = useState({
    description: "",
    unit_type: "FIXED" as ExtraWorkUnitType,
    quantity: "1.00",
    unit_price: "0.00",
    vat_rate: "21.00",
    customer_visible_note: "",
    internal_cost_note: "",
  });
  const [pricingBusy, setPricingBusy] = useState(false);
  const [pricingError, setPricingError] = useState("");

  // Transition buttons (any role; the backend computes
  // allowed_next_statuses per actor).
  const [transitionBusy, setTransitionBusy] = useState<ExtraWorkStatus | null>(
    null,
  );

  // Provider-override block.
  const [overrideDecision, setOverrideDecision] = useState<
    "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED" | null
  >(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideBusy, setOverrideBusy] = useState(false);
  const [overrideError, setOverrideError] = useState("");

  // ----- load -----
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const detail = await getExtraWork(id!);
        if (!cancelled) setEw(detail);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const isProvider = useMemo(
    () => !!me?.role && PROVIDER_ROLES.has(me.role),
    [me?.role],
  );

  // Sprint 28 Batch 4 — fetch contacts when the request loads, but
  // only for admin viewers (mirrors backend gate). Failures collapse
  // silently to the empty-state panel.
  const ewCustomerId = ew?.customer ?? null;
  useEffect(() => {
    const cancelled = { current: false };
    const customerId =
      canSeeCustomerContacts && ewCustomerId ? ewCustomerId : null;
    if (customerId === null) {
      queueMicrotask(() => {
        if (!cancelled.current) setCustomerContacts([]);
      });
    } else {
      listCustomerContacts(customerId)
        .then((list) => {
          if (!cancelled.current) setCustomerContacts(list);
        })
        .catch(() => {
          if (!cancelled.current) setCustomerContacts([]);
        });
    }
    return () => {
      cancelled.current = true;
    };
  }, [canSeeCustomerContacts, ewCustomerId]);

  if (loading) {
    return (
      <div>
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      </div>
    );
  }

  if (error || !ew) {
    return (
      <div>
        <div className="page-header">
          <div>
            <Link to="/extra-work" className="link-back">
              <ChevronLeft size={14} strokeWidth={2.5} />
              {t("back_to_extra_work")}
            </Link>
            <h2 className="page-title">{t("detail.not_found")}</h2>
          </div>
        </div>
        {error && (
          <div className="alert-error" role="alert">
            {error}
          </div>
        )}
      </div>
    );
  }

  const allowed = ew.allowed_next_statuses;
  const canApproveAsCustomer =
    ew.status === "PRICING_PROPOSED" &&
    allowed.includes("CUSTOMER_APPROVED") &&
    !isProvider;
  const canRejectAsCustomer =
    ew.status === "PRICING_PROPOSED" &&
    allowed.includes("CUSTOMER_REJECTED") &&
    !isProvider;
  const providerOverrideAvailable =
    isProvider &&
    ew.status === "PRICING_PROPOSED" &&
    (allowed.includes("CUSTOMER_APPROVED") ||
      allowed.includes("CUSTOMER_REJECTED"));

  // Provider workflow buttons exclude the override targets — those
  // route through the dedicated override block below.
  const providerWorkflowTargets = allowed.filter(
    (s) => s !== "CUSTOMER_APPROVED" && s !== "CUSTOMER_REJECTED",
  );

  async function refresh() {
    if (!id) return;
    try {
      const detail = await getExtraWork(id);
      setEw(detail);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  async function handleTransition(target: ExtraWorkStatus) {
    if (!id) return;
    setError("");
    setTransitionBusy(target);
    try {
      const updated = await transitionExtraWork(id, { to_status: target });
      setEw(updated);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setTransitionBusy(null);
    }
  }

  async function handleCustomerDecision(
    target: "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED",
  ) {
    if (!id) return;
    setError("");
    setTransitionBusy(target);
    try {
      const updated = await transitionExtraWork(id, { to_status: target });
      setEw(updated);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setTransitionBusy(null);
    }
  }

  async function handleOverrideSubmit(event: FormEvent) {
    event.preventDefault();
    if (!id || !overrideDecision) return;
    if (!overrideReason.trim()) {
      setOverrideError(t("detail.override_reason_required"));
      return;
    }
    setOverrideError("");
    setOverrideBusy(true);
    try {
      const updated = await transitionExtraWork(id, {
        to_status: overrideDecision,
        is_override: true,
        override_reason: overrideReason.trim(),
      });
      setEw(updated);
      setOverrideDecision(null);
      setOverrideReason("");
    } catch (err) {
      setOverrideError(getApiError(err));
    } finally {
      setOverrideBusy(false);
    }
  }

  async function handleAddPricingItem(event: FormEvent) {
    event.preventDefault();
    if (!id) return;
    if (!pricingForm.description.trim()) {
      setPricingError(t("detail.pricing_error_description_required"));
      return;
    }
    setPricingError("");
    setPricingBusy(true);
    try {
      await createExtraWorkPricingItem(id, {
        description: pricingForm.description.trim(),
        unit_type: pricingForm.unit_type,
        quantity: pricingForm.quantity,
        unit_price: pricingForm.unit_price,
        vat_rate: pricingForm.vat_rate,
        customer_visible_note: pricingForm.customer_visible_note,
        internal_cost_note: pricingForm.internal_cost_note,
      });
      setPricingForm({
        description: "",
        unit_type: "FIXED",
        quantity: "1.00",
        unit_price: "0.00",
        vat_rate: "21.00",
        customer_visible_note: "",
        internal_cost_note: "",
      });
      await refresh();
    } catch (err) {
      setPricingError(getApiError(err));
    } finally {
      setPricingBusy(false);
    }
  }

  async function handleDeletePricingItem(itemId: number) {
    if (!id) return;
    setPricingError("");
    try {
      await deleteExtraWorkPricingItem(id, itemId);
      await refresh();
    } catch (err) {
      setPricingError(getApiError(err));
    }
  }

  return (
    <div data-testid="extra-work-detail-page">
      <div className="page-header">
        <div>
          <Link to="/extra-work" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_extra_work")}
          </Link>
          <h2 className="page-title">{ew.title}</h2>
          <p className="page-sub">
            {t(STATUS_I18N_KEY[ew.status])} ·{" "}
            {t(CATEGORY_I18N_KEY[ew.category] ?? ew.category)}
            {ew.category === "OTHER" && ew.category_other_text
              ? ` — ${ew.category_other_text}`
              : ""}{" "}
            · {t(URGENCY_I18N_KEY[ew.urgency] ?? ew.urgency)}
          </p>
        </div>
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* ----- Core details ----- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-section">
          <div className="form-section-title">
            {t("detail.details_section_title")}
          </div>
          <div className="form-2col">
            <div>
              <div className="muted small">{t("detail.field_building")}</div>
              <div>{ew.building_name}</div>
            </div>
            <div>
              <div className="muted small">{t("detail.field_customer")}</div>
              <div>{ew.customer_name}</div>
            </div>
          </div>
          <div className="form-2col">
            <div>
              <div className="muted small">
                {t("detail.field_requested_at")}
              </div>
              <div>{fmtDate(ew.requested_at)}</div>
            </div>
            <div>
              <div className="muted small">
                {t("detail.field_preferred_date")}
              </div>
              <div>{ew.preferred_date ?? t("detail.empty_dash")}</div>
            </div>
          </div>
          <div className="field">
            <div className="muted small">{t("detail.field_description")}</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{ew.description}</div>
          </div>
          {ew.customer_visible_note && (
            <div className="field">
              <div className="muted small">
                {t("detail.field_customer_visible_note")}
              </div>
              <div style={{ whiteSpace: "pre-wrap" }}>
                {ew.customer_visible_note}
              </div>
            </div>
          )}
          {ew.pricing_note && (
            <div className="field">
              <div className="muted small">
                {t("detail.field_pricing_note")}
              </div>
              <div style={{ whiteSpace: "pre-wrap" }}>{ew.pricing_note}</div>
            </div>
          )}
          {/* Provider-internal fields — never present on customer
              responses, so the conditional check is a no-op for
              customer users. */}
          {isProvider && ew.manager_note && (
            <div className="field">
              <div className="muted small">
                {t("detail.field_manager_note")}
              </div>
              <div style={{ whiteSpace: "pre-wrap" }}>{ew.manager_note}</div>
            </div>
          )}
          {isProvider && ew.internal_cost_note && (
            <div className="field">
              <div className="muted small">
                {t("detail.field_internal_cost_note")}
              </div>
              <div style={{ whiteSpace: "pre-wrap" }}>
                {ew.internal_cost_note}
              </div>
            </div>
          )}
          {isProvider && ew.override_at && (
            <div className="alert-warning" style={{ marginTop: 12 }}>
              <strong>{t("detail.override_applied")}</strong>
              {ew.override_reason && (
                <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>
                  {ew.override_reason}
                </div>
              )}
              <div className="muted small" style={{ marginTop: 4 }}>
                {fmtDate(ew.override_at)}
              </div>
            </div>
          )}

          {/* Sprint 28 Batch 6 — routing decision badge. */}
          <div className="field">
            <div className="muted small">
              {t("detail.routing_decision_label")}
            </div>
            <div data-testid="extra-work-detail-routing-decision">
              {ew.routing_decision === "INSTANT"
                ? t("detail.routing_decision_instant")
                : t("detail.routing_decision_proposal")}
            </div>
          </div>
        </div>
      </div>

      {/* Sprint 28 Batch 4 — read-only Customer Contacts panel.
          Renders only for SUPER_ADMIN / COMPANY_ADMIN (mirrors the
          backend gate; other roles never see this card). Pure
          informational — full management lives on
          /admin/customers/:id/contacts. */}
      {canSeeCustomerContacts && (
        <div
          className="card"
          data-testid="extra-work-customer-contacts-panel"
          style={{ marginBottom: 16 }}
        >
          <div className="form-section">
            <div className="form-section-title">
              {t("customer_contacts.panel_title", { ns: "common" })}
            </div>
            {customerContacts.length === 0 ? (
              <div
                className="muted small"
                data-testid="extra-work-customer-contacts-empty"
              >
                {t("customer_contacts.panel_empty", { ns: "common" })}
              </div>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  margin: 0,
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                {customerContacts.map((contact) => (
                  <li
                    key={contact.id}
                    data-testid="extra-work-customer-contact-row"
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                    }}
                  >
                    <span style={{ fontWeight: 600 }}>{contact.full_name}</span>
                    {contact.role_label && (
                      <span className="muted small">{contact.role_label}</span>
                    )}
                    {(contact.email || contact.phone) && (
                      <span
                        className="muted small"
                        style={{ display: "flex", gap: 12, flexWrap: "wrap" }}
                      >
                        {contact.email && <span>{contact.email}</span>}
                        {contact.phone && <span>{contact.phone}</span>}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* ----- Cart line items (Sprint 28 Batch 6) ----- */}
      <div
        className="card"
        style={{ marginBottom: 16 }}
        data-testid="extra-work-detail-line-items"
      >
        <div className="form-section">
          <div className="form-section-title">
            {t("detail.line_items_section_title")}
          </div>
          {ew.line_items.length === 0 ? (
            <div
              className="muted small"
              data-testid="extra-work-detail-line-items-empty"
            >
              {t("detail.line_items_empty")}
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("detail.line_column_service")}</th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.line_column_quantity")}
                  </th>
                  <th>{t("detail.line_column_unit")}</th>
                  <th>{t("detail.line_column_requested_date")}</th>
                  <th>{t("detail.line_column_note")}</th>
                </tr>
              </thead>
              <tbody>
                {ew.line_items.map((item) => (
                  <tr
                    key={item.id}
                    data-testid="extra-work-detail-line-item-row"
                  >
                    <td>{item.service_name}</td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.quantity)}
                    </td>
                    <td>
                      {t(
                        UNIT_TYPE_I18N_KEY[item.unit_type] ?? item.unit_type,
                      )}
                    </td>
                    <td>{item.requested_date}</td>
                    <td>{item.customer_note || t("detail.empty_dash")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ----- Pricing line items ----- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-section">
          <div className="form-section-title">
            {t("detail.pricing_section_title")}
          </div>
          {ew.pricing_line_items.length === 0 && (
            <div className="muted small">{t("detail.pricing_empty")}</div>
          )}
          {ew.pricing_line_items.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("detail.pricing_column_description")}</th>
                  <th>{t("detail.pricing_column_unit")}</th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.pricing_column_qty")}
                  </th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.pricing_column_unit_price")}
                  </th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.pricing_column_vat_pct")}
                  </th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.pricing_column_subtotal")}
                  </th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.pricing_column_vat")}
                  </th>
                  <th style={{ textAlign: "right" }}>
                    {t("detail.pricing_column_total")}
                  </th>
                  {isProvider && <th />}
                </tr>
              </thead>
              <tbody>
                {ew.pricing_line_items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <div>{item.description}</div>
                      {item.customer_visible_note && (
                        <div className="muted small">
                          {item.customer_visible_note}
                        </div>
                      )}
                      {isProvider && item.internal_cost_note && (
                        <div
                          className="muted small"
                          style={{ fontStyle: "italic" }}
                        >
                          internal: {item.internal_cost_note}
                        </div>
                      )}
                    </td>
                    <td>
                      {t(
                        UNIT_TYPE_I18N_KEY[item.unit_type] ?? item.unit_type,
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.quantity)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.unit_price)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.vat_rate)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.subtotal)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.vat_amount)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {fmtMoney(item.total)}
                    </td>
                    {isProvider && (
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => handleDeletePricingItem(item.id)}
                        >
                          {t("detail.pricing_remove_button")}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
                <tr>
                  <td colSpan={isProvider ? 5 : 5} />
                  <td style={{ textAlign: "right", fontWeight: 600 }}>
                    {fmtMoney(ew.subtotal_amount)}
                  </td>
                  <td style={{ textAlign: "right", fontWeight: 600 }}>
                    {fmtMoney(ew.vat_amount)}
                  </td>
                  <td style={{ textAlign: "right", fontWeight: 700 }}>
                    {fmtMoney(ew.total_amount)}
                  </td>
                  {isProvider && <td />}
                </tr>
              </tbody>
            </table>
          )}

          {isProvider && (
            <>
              {pricingError && (
                <div
                  className="alert-error"
                  style={{ marginTop: 12 }}
                  role="alert"
                >
                  {pricingError}
                </div>
              )}
              <form onSubmit={handleAddPricingItem} style={{ marginTop: 12 }}>
                <div className="form-2col">
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="pricing-description"
                    >
                      {t("detail.pricing_form_description")}
                    </label>
                    <input
                      id="pricing-description"
                      className="field-input"
                      type="text"
                      value={pricingForm.description}
                      onChange={(event) =>
                        setPricingForm((c) => ({
                          ...c,
                          description: event.target.value,
                        }))
                      }
                      placeholder={t(
                        "detail.pricing_form_description_placeholder",
                      )}
                      required
                    />
                  </div>
                  <div className="field">
                    <label className="field-label" htmlFor="pricing-unit-type">
                      {t("detail.pricing_form_unit")}
                    </label>
                    <select
                      id="pricing-unit-type"
                      className="field-select"
                      value={pricingForm.unit_type}
                      onChange={(event) =>
                        setPricingForm((c) => ({
                          ...c,
                          unit_type: event.target.value as ExtraWorkUnitType,
                        }))
                      }
                    >
                      {UNIT_TYPE_VALUES.map((value) => (
                        <option key={value} value={value}>
                          {t(UNIT_TYPE_I18N_KEY[value])}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-2col">
                  <div className="field">
                    <label className="field-label" htmlFor="pricing-qty">
                      {t("detail.pricing_form_quantity")}
                    </label>
                    <input
                      id="pricing-qty"
                      className="field-input"
                      type="number"
                      step="0.01"
                      min="0"
                      value={pricingForm.quantity}
                      onChange={(event) =>
                        setPricingForm((c) => ({
                          ...c,
                          quantity: event.target.value,
                        }))
                      }
                      required
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="pricing-unit-price"
                    >
                      {t("detail.pricing_form_unit_price")}
                    </label>
                    <input
                      id="pricing-unit-price"
                      className="field-input"
                      type="number"
                      step="0.01"
                      min="0"
                      value={pricingForm.unit_price}
                      onChange={(event) =>
                        setPricingForm((c) => ({
                          ...c,
                          unit_price: event.target.value,
                        }))
                      }
                      required
                    />
                  </div>
                </div>
                <div className="form-2col">
                  <div className="field">
                    <label className="field-label" htmlFor="pricing-vat">
                      {t("detail.pricing_form_vat")}
                    </label>
                    <input
                      id="pricing-vat"
                      className="field-input"
                      type="number"
                      step="0.01"
                      min="0"
                      value={pricingForm.vat_rate}
                      onChange={(event) =>
                        setPricingForm((c) => ({
                          ...c,
                          vat_rate: event.target.value,
                        }))
                      }
                      required
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="pricing-customer-note"
                    >
                      {t("detail.pricing_form_customer_note")}
                    </label>
                    <input
                      id="pricing-customer-note"
                      className="field-input"
                      type="text"
                      value={pricingForm.customer_visible_note}
                      onChange={(event) =>
                        setPricingForm((c) => ({
                          ...c,
                          customer_visible_note: event.target.value,
                        }))
                      }
                      placeholder={t(
                        "detail.pricing_form_customer_note_placeholder",
                      )}
                    />
                  </div>
                </div>
                <div className="field">
                  <label
                    className="field-label"
                    htmlFor="pricing-internal-note"
                  >
                    {t("detail.pricing_form_internal_note")}
                  </label>
                  <input
                    id="pricing-internal-note"
                    className="field-input"
                    type="text"
                    value={pricingForm.internal_cost_note}
                    onChange={(event) =>
                      setPricingForm((c) => ({
                        ...c,
                        internal_cost_note: event.target.value,
                      }))
                    }
                    placeholder={t(
                      "detail.pricing_form_internal_note_placeholder",
                    )}
                  />
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    marginTop: 8,
                  }}
                >
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={pricingBusy}
                  >
                    {pricingBusy
                      ? t("detail.pricing_form_submitting")
                      : t("detail.pricing_form_submit")}
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>

      {/* ----- Workflow / transitions ----- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-section">
          <div className="form-section-title">
            {t("detail.workflow_section_title")}
          </div>

          {/* Customer approve / reject — only when allowed by backend
              and the actor is a customer-side user. Override path
              is below. */}
          {(canApproveAsCustomer || canRejectAsCustomer) && (
            <div style={{ marginBottom: 8 }}>
              <p className="muted small" style={{ marginTop: 0 }}>
                {t("detail.workflow_customer_decision_helper")}
              </p>
              <div
                className="status-actions"
                style={{ display: "flex", gap: 8 }}
              >
                {canApproveAsCustomer && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={transitionBusy !== null}
                    onClick={() => handleCustomerDecision("CUSTOMER_APPROVED")}
                  >
                    {transitionBusy === "CUSTOMER_APPROVED"
                      ? t("detail.workflow_approving")
                      : t("detail.workflow_approve_button")}
                  </button>
                )}
                {canRejectAsCustomer && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={transitionBusy !== null}
                    onClick={() => handleCustomerDecision("CUSTOMER_REJECTED")}
                  >
                    {transitionBusy === "CUSTOMER_REJECTED"
                      ? t("detail.workflow_rejecting")
                      : t("detail.workflow_reject_button")}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Provider-side workflow buttons (non-override transitions). */}
          {isProvider && providerWorkflowTargets.length > 0 && (
            <div
              className="status-actions"
              style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
            >
              {providerWorkflowTargets.map((target) => (
                <button
                  key={target}
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={transitionBusy !== null}
                  onClick={() => handleTransition(target)}
                >
                  {transitionBusy === target
                    ? t("detail.workflow_working")
                    : t("detail.workflow_move_to", {
                        label: t(STATUS_I18N_KEY[target]),
                      })}
                </button>
              ))}
            </div>
          )}

          {!canApproveAsCustomer &&
            !canRejectAsCustomer &&
            providerWorkflowTargets.length === 0 && (
              <p className="muted small" style={{ margin: 0 }}>
                {t("detail.workflow_no_transitions")}
              </p>
            )}
        </div>
      </div>

      {/* ----- Provider override block ----- */}
      {providerOverrideAvailable && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="form-section">
            <div className="form-section-title">
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <AlertTriangle size={16} strokeWidth={2.2} />
                {t("detail.override_section_title")}
              </span>
            </div>
            <div className="alert-warning" style={{ marginBottom: 12 }}>
              <strong>{t("detail.override_warning_title")}</strong>{" "}
              {t("detail.override_warning_body")}
            </div>

            {overrideDecision === null ? (
              <div style={{ display: "flex", gap: 8 }}>
                {allowed.includes("CUSTOMER_APPROVED") && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setOverrideDecision("CUSTOMER_APPROVED")}
                  >
                    {t("detail.override_choose_approve")}
                  </button>
                )}
                {allowed.includes("CUSTOMER_REJECTED") && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setOverrideDecision("CUSTOMER_REJECTED")}
                  >
                    {t("detail.override_choose_reject")}
                  </button>
                )}
              </div>
            ) : (
              <form onSubmit={handleOverrideSubmit}>
                <div className="field">
                  <label className="field-label" htmlFor="override-reason">
                    {t("detail.override_reason_label")}
                  </label>
                  <textarea
                    id="override-reason"
                    className="field-textarea"
                    rows={3}
                    value={overrideReason}
                    onChange={(event) => setOverrideReason(event.target.value)}
                    placeholder={t("detail.override_reason_placeholder")}
                    required
                  />
                </div>
                {overrideError && (
                  <div className="alert-error" role="alert">
                    {overrideError}
                  </div>
                )}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    gap: 8,
                    marginTop: 8,
                  }}
                >
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setOverrideDecision(null);
                      setOverrideReason("");
                      setOverrideError("");
                    }}
                  >
                    {t("detail.override_cancel")}
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={overrideBusy}
                  >
                    {overrideBusy
                      ? t("detail.override_submitting")
                      : t("detail.override_confirm", {
                          label: t(STATUS_I18N_KEY[overrideDecision]),
                        })}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      <div
        className="muted small"
        style={{ textAlign: "right", marginTop: 8 }}
      >
        {t("detail.updated_at", { date: fmtDate(ew.updated_at) })}
      </div>
    </div>
  );
}
