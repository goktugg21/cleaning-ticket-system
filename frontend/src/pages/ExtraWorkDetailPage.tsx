// Sprint 26C — Extra Work detail page.
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
  ExtraWorkRequestDetail,
  ExtraWorkStatus,
  ExtraWorkUnitType,
  Role,
} from "../api/types";


const STATUS_LABELS: Record<ExtraWorkStatus, string> = {
  REQUESTED: "Requested",
  UNDER_REVIEW: "Under review",
  PRICING_PROPOSED: "Pricing proposed",
  CUSTOMER_APPROVED: "Customer approved",
  CUSTOMER_REJECTED: "Customer rejected",
  CANCELLED: "Cancelled",
};

const CATEGORY_LABELS: Record<string, string> = {
  DEEP_CLEANING: "Deep cleaning",
  WINDOW_CLEANING: "Window cleaning",
  FLOOR_MAINTENANCE: "Floor maintenance",
  SANITARY_SERVICE: "Sanitary service",
  WASTE_REMOVAL: "Waste removal",
  FURNITURE_MOVING: "Furniture moving",
  EVENT_CLEANING: "Event cleaning",
  EMERGENCY_CLEANING: "Emergency cleaning",
  OTHER: "Other",
};

const UNIT_TYPES: { value: ExtraWorkUnitType; label: string }[] = [
  { value: "HOURS", label: "Hours" },
  { value: "SQUARE_METERS", label: "m²" },
  { value: "FIXED", label: "Fixed price" },
  { value: "ITEM", label: "Per item" },
  { value: "OTHER", label: "Other" },
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
  const { t } = useTranslation("common");

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
              Back to Extra Work
            </Link>
            <h2 className="page-title">Extra Work not found</h2>
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
      setOverrideError("Override reason is required.");
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
      setPricingError("Description is required.");
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
    <div>
      <div className="page-header">
        <div>
          <Link to="/extra-work" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            Back to Extra Work
          </Link>
          <h2 className="page-title">{ew.title}</h2>
          <p className="page-sub">
            {STATUS_LABELS[ew.status]} ·{" "}
            {CATEGORY_LABELS[ew.category] ?? ew.category}
            {ew.category === "OTHER" && ew.category_other_text
              ? ` — ${ew.category_other_text}`
              : ""}{" "}
            · {ew.urgency}
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
          <div className="form-section-title">Details</div>
          <div className="form-2col">
            <div>
              <div className="muted small">Building</div>
              <div>{ew.building_name}</div>
            </div>
            <div>
              <div className="muted small">Customer</div>
              <div>{ew.customer_name}</div>
            </div>
          </div>
          <div className="form-2col">
            <div>
              <div className="muted small">Requested at</div>
              <div>{fmtDate(ew.requested_at)}</div>
            </div>
            <div>
              <div className="muted small">Preferred date</div>
              <div>{ew.preferred_date ?? "—"}</div>
            </div>
          </div>
          <div className="field">
            <div className="muted small">Description</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{ew.description}</div>
          </div>
          {ew.customer_visible_note && (
            <div className="field">
              <div className="muted small">Note from provider</div>
              <div style={{ whiteSpace: "pre-wrap" }}>
                {ew.customer_visible_note}
              </div>
            </div>
          )}
          {ew.pricing_note && (
            <div className="field">
              <div className="muted small">Pricing note</div>
              <div style={{ whiteSpace: "pre-wrap" }}>{ew.pricing_note}</div>
            </div>
          )}
          {/* Provider-internal fields — never present on customer
              responses, so the conditional check is a no-op for
              customer users. */}
          {isProvider && ew.manager_note && (
            <div className="field">
              <div className="muted small">Internal manager note (provider only)</div>
              <div style={{ whiteSpace: "pre-wrap" }}>{ew.manager_note}</div>
            </div>
          )}
          {isProvider && ew.internal_cost_note && (
            <div className="field">
              <div className="muted small">Internal cost note (provider only)</div>
              <div style={{ whiteSpace: "pre-wrap" }}>
                {ew.internal_cost_note}
              </div>
            </div>
          )}
          {isProvider && ew.override_at && (
            <div className="alert-warning" style={{ marginTop: 12 }}>
              <strong>Provider override applied.</strong>
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
              {t("customer_contacts.panel_title")}
            </div>
            {customerContacts.length === 0 ? (
              <div
                className="muted small"
                data-testid="extra-work-customer-contacts-empty"
              >
                {t("customer_contacts.panel_empty")}
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

      {/* ----- Pricing line items ----- */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-section">
          <div className="form-section-title">Pricing proposal</div>
          {ew.pricing_line_items.length === 0 && (
            <div className="muted small">
              No pricing line items yet.
            </div>
          )}
          {ew.pricing_line_items.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Unit</th>
                  <th style={{ textAlign: "right" }}>Qty</th>
                  <th style={{ textAlign: "right" }}>Unit price</th>
                  <th style={{ textAlign: "right" }}>VAT %</th>
                  <th style={{ textAlign: "right" }}>Subtotal</th>
                  <th style={{ textAlign: "right" }}>VAT</th>
                  <th style={{ textAlign: "right" }}>Total</th>
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
                    <td>{item.unit_type}</td>
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
                          Remove
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
                <div className="alert-error" style={{ marginTop: 12 }} role="alert">
                  {pricingError}
                </div>
              )}
              <form
                onSubmit={handleAddPricingItem}
                style={{ marginTop: 12 }}
              >
                <div className="form-2col">
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="pricing-description"
                    >
                      Description
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
                      placeholder="e.g. Crew time on Saturday"
                      required
                    />
                  </div>
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="pricing-unit-type"
                    >
                      Unit
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
                      {UNIT_TYPES.map((u) => (
                        <option key={u.value} value={u.value}>
                          {u.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-2col">
                  <div className="field">
                    <label className="field-label" htmlFor="pricing-qty">
                      Quantity
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
                    <label className="field-label" htmlFor="pricing-unit-price">
                      Unit price
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
                      VAT %
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
                      Customer-visible explanation
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
                      placeholder="Shown to the customer alongside this line"
                    />
                  </div>
                </div>
                <div className="field">
                  <label
                    className="field-label"
                    htmlFor="pricing-internal-note"
                  >
                    Internal cost note (provider-only)
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
                    placeholder="Never shown to the customer"
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
                    {pricingBusy ? "Adding…" : "Add pricing line"}
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
          <div className="form-section-title">Workflow</div>

          {/* Customer approve / reject — only when allowed by backend
              and the actor is a customer-side user. Override path
              is below. */}
          {(canApproveAsCustomer || canRejectAsCustomer) && (
            <div style={{ marginBottom: 8 }}>
              <p className="muted small" style={{ marginTop: 0 }}>
                The provider has proposed pricing. Please review the
                lines above and approve or reject.
              </p>
              <div className="status-actions" style={{ display: "flex", gap: 8 }}>
                {canApproveAsCustomer && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={transitionBusy !== null}
                    onClick={() => handleCustomerDecision("CUSTOMER_APPROVED")}
                  >
                    {transitionBusy === "CUSTOMER_APPROVED"
                      ? "Approving…"
                      : "Approve pricing"}
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
                      ? "Rejecting…"
                      : "Reject pricing"}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Provider-side workflow buttons (non-override transitions). */}
          {isProvider && providerWorkflowTargets.length > 0 && (
            <div className="status-actions" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {providerWorkflowTargets.map((target) => (
                <button
                  key={target}
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={transitionBusy !== null}
                  onClick={() => handleTransition(target)}
                >
                  {transitionBusy === target
                    ? "Working…"
                    : `Move to ${STATUS_LABELS[target]}`}
                </button>
              ))}
            </div>
          )}

          {!canApproveAsCustomer &&
            !canRejectAsCustomer &&
            providerWorkflowTargets.length === 0 && (
              <p className="muted small" style={{ margin: 0 }}>
                No further transitions are available to you in this status.
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
                Provider override
              </span>
            </div>
            <div className="alert-warning" style={{ marginBottom: 12 }}>
              <strong>Override the customer decision.</strong> Use only
              when the customer has agreed by phone, email, or another
              out-of-band channel. Every override is recorded in the
              status history with your name, the chosen outcome, and
              the reason you type below.
            </div>

            {overrideDecision === null ? (
              <div style={{ display: "flex", gap: 8 }}>
                {allowed.includes("CUSTOMER_APPROVED") && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setOverrideDecision("CUSTOMER_APPROVED")}
                  >
                    Override → Customer approved
                  </button>
                )}
                {allowed.includes("CUSTOMER_REJECTED") && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setOverrideDecision("CUSTOMER_REJECTED")}
                  >
                    Override → Customer rejected
                  </button>
                )}
              </div>
            ) : (
              <form onSubmit={handleOverrideSubmit}>
                <div className="field">
                  <label
                    className="field-label"
                    htmlFor="override-reason"
                  >
                    Reason for the override (required)
                  </label>
                  <textarea
                    id="override-reason"
                    className="field-textarea"
                    rows={3}
                    value={overrideReason}
                    onChange={(event) => setOverrideReason(event.target.value)}
                    placeholder="e.g. Customer confirmed by phone on 2026-05-15 at 14:00. Their email follow-up is in the ticket thread."
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
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={overrideBusy}
                  >
                    {overrideBusy
                      ? "Submitting…"
                      : `Confirm override → ${STATUS_LABELS[overrideDecision]}`}
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
        Updated {fmtDate(ew.updated_at)}
      </div>
    </div>
  );
}
