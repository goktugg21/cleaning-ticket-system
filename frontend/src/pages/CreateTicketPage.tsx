import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  ChevronLeft,
  CircleCheck,
  Clock,
  Info,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import type { Building, Customer, PaginatedResponse } from "../api/types";

interface CreateTicketForm {
  title: string;
  description: string;
  room_label: string;
  type: string;
  priority: string;
  building: string;
  customer: string;
}

type TicketTypeValue =
  | "REPORT"
  | "COMPLAINT"
  | "REQUEST"
  | "SUGGESTION"
  | "QUOTE_REQUEST";

type PriorityValue = "NORMAL" | "HIGH" | "URGENT";

interface PriorityCard {
  value: PriorityValue;
  labelKey: string;
  helperKey: string;
  icon: typeof Info;
}

const TICKET_TYPE_VALUES: TicketTypeValue[] = [
  "REPORT",
  "COMPLAINT",
  "REQUEST",
  "SUGGESTION",
  "QUOTE_REQUEST",
];

const TICKET_TYPE_KEYS: Record<TicketTypeValue, string> = {
  REPORT: "type_report",
  COMPLAINT: "type_complaint",
  REQUEST: "type_request",
  SUGGESTION: "type_suggestion",
  QUOTE_REQUEST: "type_quote_request",
};

const PRIORITY_CARDS: PriorityCard[] = [
  {
    value: "NORMAL",
    labelKey: "priority_normal_label",
    helperKey: "priority_normal_helper",
    icon: CircleCheck,
  },
  {
    value: "HIGH",
    labelKey: "priority_high_label",
    helperKey: "priority_high_helper",
    icon: TriangleAlert,
  },
  {
    value: "URGENT",
    labelKey: "priority_urgent_label",
    helperKey: "priority_urgent_helper",
    icon: AlertTriangle,
  },
];

const EMPTY_FORM: CreateTicketForm = {
  title: "",
  description: "",
  room_label: "",
  type: "REPORT",
  priority: "NORMAL",
  building: "",
  customer: "",
};

export function CreateTicketPage() {
  const navigate = useNavigate();
  const { t } = useTranslation(["create_ticket", "common"]);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<CreateTicketForm>(EMPTY_FORM);
  const [stagedAttachment, setStagedAttachment] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadOptions() {
      try {
        const [buildingResponse, customerResponse] = await Promise.all([
          api.get<PaginatedResponse<Building>>("/buildings/", {
            params: { page_size: 200 },
          }),
          api.get<PaginatedResponse<Customer>>("/customers/", {
            params: { page_size: 200 },
          }),
        ]);

        if (cancelled) return;

        setBuildings(buildingResponse.data.results);
        setCustomers(customerResponse.data.results);

        const firstBuilding = buildingResponse.data.results[0];
        const firstCustomer = firstBuilding
          ? customerResponse.data.results.find(
              (customer) => customer.building === firstBuilding.id,
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

    loadOptions();

    return () => {
      cancelled = true;
    };
  }, []);

  // Sprint 14: when a customer is selected, fetch the buildings that
  // customer is linked to (M:N CustomerBuildingMembership) so the
  // building dropdown can be narrowed to only valid pairs. The legacy
  // `customer.building` is still respected as a fallback for any
  // customer the operator has not yet re-linked.
  const [customerLinkedBuildingIds, setCustomerLinkedBuildingIds] = useState<
    Set<number> | null
  >(null);

  useEffect(() => {
    if (!form.customer) {
      setCustomerLinkedBuildingIds(null);
      return;
    }
    let cancelled = false;
    api
      .get<PaginatedResponse<{ building_id: number }>>(
        `/customers/${form.customer}/buildings/`,
      )
      .then((response) => {
        if (cancelled) return;
        setCustomerLinkedBuildingIds(
          new Set(response.data.results.map((r) => r.building_id)),
        );
      })
      .catch(() => {
        // Endpoint requires admin permissions; for non-admin users
        // this fetch will 403. Fall back to the legacy
        // customer.building hint so the dropdown is still useful.
        if (!cancelled) setCustomerLinkedBuildingIds(null);
      });
    return () => {
      cancelled = true;
    };
  }, [form.customer]);

  const filteredCustomers = useMemo(() => {
    if (!form.building) return customers;
    const buildingId = Number(form.building);
    return customers.filter(
      (customer) => customer.building === buildingId,
    );
  }, [customers, form.building]);

  const filteredBuildings = useMemo(() => {
    if (!form.customer) return buildings;
    if (customerLinkedBuildingIds === null) {
      // Either we have not loaded yet or the user is non-admin and
      // we cannot read the link list. Fall back to the legacy
      // customer.building anchor to keep the dropdown helpful.
      const c = customers.find((x) => String(x.id) === form.customer);
      if (c?.building) {
        return buildings.filter((b) => b.id === c.building);
      }
      return buildings;
    }
    return buildings.filter((b) => customerLinkedBuildingIds.has(b.id));
  }, [buildings, customers, form.customer, customerLinkedBuildingIds]);

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

  const selectedBuilding = useMemo(
    () => buildings.find((b) => String(b.id) === form.building),
    [buildings, form.building],
  );
  const selectedCustomer = useMemo(
    () => customers.find((c) => String(c.id) === form.customer),
    [customers, form.customer],
  );

  function update<K extends keyof CreateTicketForm>(
    name: K,
    value: CreateTicketForm[K],
  ) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");

    if (!form.title.trim()) {
      setError(t("validation_title_required"));
      return;
    }
    if (!form.description.trim()) {
      setError(t("validation_description_required"));
      return;
    }
    if (!form.building) {
      setError(t("validation_location_required"));
      return;
    }
    if (!form.customer) {
      setError(t("validation_customer_required"));
      return;
    }

    setSubmitting(true);

    try {
      const response = await api.post<{ id: number }>("/tickets/", {
        title: form.title.trim(),
        description: form.description.trim(),
        room_label: form.room_label.trim(),
        type: form.type,
        priority: form.priority,
        building: Number(form.building),
        customer: Number(form.customer),
      });

      const newId = response.data.id;

      if (stagedAttachment) {
        try {
          const formData = new FormData();
          formData.append("file", stagedAttachment);
          await api.post(`/tickets/${newId}/attachments/`, formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch {
          // Non-fatal: surface but still navigate. The detail page lets users retry.
        }
      }

      navigate(`/tickets/${newId}`);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const noOptions =
    !loadingOptions && (buildings.length === 0 || customers.length === 0);

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_tickets")}
          </Link>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("eyebrow")}
          </div>
          <h2 className="page-title">{t("title")}</h2>
          <p className="page-sub">{t("subtitle")}</p>
        </div>
      </div>

      {loadingOptions && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {noOptions && !error && (
        <div className="alert-error" style={{ marginBottom: 16 }}>
          {t("no_access_message")}
        </div>
      )}

      <form className="create-layout" onSubmit={handleSubmit}>
        <div className="card create-main">
          <div className="form-section">
            <div className="form-section-title">
              {t("section_issue_title")}
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="f-type">
                  {t("field_category_label")}
                </label>
                <select
                  id="f-type"
                  className="field-select"
                  value={form.type}
                  onChange={(event) => update("type", event.target.value)}
                >
                  {TICKET_TYPE_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {t(TICKET_TYPE_KEYS[value])}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="f-building">
                  {t("field_location_label")}
                </label>
                <select
                  id="f-building"
                  className="field-select"
                  value={form.building}
                  onChange={(event) => update("building", event.target.value)}
                  disabled={filteredBuildings.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("field_location_placeholder")}
                  </option>
                  {filteredBuildings.map((building) => (
                    <option key={building.id} value={building.id}>
                      {building.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="f-customer">
                  {t("field_customer_label")}
                </label>
                <select
                  id="f-customer"
                  className="field-select"
                  value={form.customer}
                  onChange={(event) => update("customer", event.target.value)}
                  disabled={filteredCustomers.length === 0}
                  required
                >
                  <option value="" disabled>
                    {filteredCustomers.length === 0
                      ? t("field_customer_no_options")
                      : t("field_customer_placeholder")}
                  </option>
                  {filteredCustomers.map((customer) => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="f-room">
                  {t("field_room_label")}
                </label>
                <input
                  id="f-room"
                  className="field-input"
                  type="text"
                  placeholder={t("field_room_placeholder")}
                  value={form.room_label}
                  onChange={(event) => update("room_label", event.target.value)}
                />
              </div>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="f-title">
                {t("field_title_label")}
              </label>
              <input
                id="f-title"
                className="field-input"
                type="text"
                placeholder={t("field_title_placeholder")}
                maxLength={255}
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="f-desc">
                {t("field_description_label")}
              </label>
              <textarea
                id="f-desc"
                className="field-textarea"
                placeholder={t("field_description_placeholder")}
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                required
              />
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title">
              {t("section_priority_title")}
            </div>
            <div className="form-section-helper">
              {t("section_priority_helper")}
            </div>
            <div className="priority-grid">
              {PRIORITY_CARDS.map((card) => {
                const Icon = card.icon;
                const isSelected = form.priority === card.value;
                return (
                  <button
                    type="button"
                    key={card.value}
                    data-prio={card.value}
                    className={`priority-card ${isSelected ? "selected" : ""}`}
                    onClick={() => update("priority", card.value)}
                  >
                    <span className="priority-card-icon">
                      <Icon size={16} strokeWidth={2} />
                    </span>
                    <span className="priority-card-label">
                      {t(card.labelKey)}
                    </span>
                    <span className="priority-card-helper">
                      {t(card.helperKey)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title">
              {t("section_attachments_title")}
            </div>
            <div className="form-section-helper">
              {t("section_attachments_helper")}
            </div>
            <label className="upload-zone">
              <UploadCloud
                className="upload-icon"
                size={22}
                strokeWidth={2}
              />
              <span className="upload-title">
                {stagedAttachment
                  ? stagedAttachment.name
                  : t("attachment_drop_hint")}
              </span>
              <span className="upload-hint">
                {stagedAttachment
                  ? `${(stagedAttachment.size / 1024 / 1024).toFixed(2)} ${t("attachment_replace_hint")}`
                  : t("attachment_size_hint")}
              </span>
              <input
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf"
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  if (file && file.size > 10 * 1024 * 1024) {
                    setError(t("attachment_too_large"));
                    event.target.value = "";
                    return;
                  }
                  setError("");
                  setStagedAttachment(file);
                }}
              />
            </label>
          </div>

          {error && (
            <div
              className="alert-error"
              style={{ margin: "0 22px 18px" }}
              role="alert"
            >
              {error}
            </div>
          )}

          <div className="form-actions">
            <Link to="/" className="btn btn-secondary">
              {t("cancel")}
            </Link>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || loadingOptions || noOptions}
            >
              {submitting ? t("creating") : t("submit")}
              <ArrowRight size={14} strokeWidth={2.5} />
            </button>
          </div>
        </div>

        <aside className="create-side">
          <div className="card">
            <div className="section-head">
              <div className="section-head-title">{t("summary_title")}</div>
            </div>
            <div className="side-card-body">
              <div className="preview-list">
                <div className="preview-row">
                  <span className="preview-key">{t("summary_location")}</span>
                  <span className="preview-val">
                    {selectedBuilding?.name || "—"}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">{t("summary_customer")}</span>
                  <span className="preview-val">
                    {selectedCustomer?.name || "—"}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">{t("summary_category")}</span>
                  <span className="preview-val">
                    {t(
                      TICKET_TYPE_KEYS[form.type as TicketTypeValue] ??
                        "type_report",
                    )}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">{t("summary_priority")}</span>
                  <span className="preview-val">
                    {t(`common:priority.${form.priority.toLowerCase()}`)}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">{t("summary_attachment")}</span>
                  <span className="preview-val">
                    {stagedAttachment ? stagedAttachment.name : t("summary_none")}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                }}
              >
                <Info
                  size={16}
                  strokeWidth={2}
                  color="var(--green-2)"
                />
                <div className="section-head-title">
                  {t("guidelines_title")}
                </div>
              </div>
            </div>
            <div style={{ padding: "14px 16px 16px" }}>
              <ul className="guideline-list">
                <li className="guideline-item">
                  <CircleCheck size={14} strokeWidth={2.5} />
                  <span>{t("guideline_1")}</span>
                </li>
                <li className="guideline-item">
                  <CircleCheck size={14} strokeWidth={2.5} />
                  <span>{t("guideline_2")}</span>
                </li>
                <li className="guideline-item">
                  <CircleCheck size={14} strokeWidth={2.5} />
                  <span>{t("guideline_3")}</span>
                </li>
              </ul>
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                }}
              >
                <Clock size={16} strokeWidth={2} color="var(--green-2)" />
                <div className="section-head-title">
                  {t("response_slas_title")}
                </div>
              </div>
            </div>
            <div style={{ padding: "6px 16px 12px" }}>
              <div className="sla-list">
                <div className="sla-list-item" data-prio="NORMAL">
                  <span className="sla-list-name">{t("sla_medium_name")}</span>
                  <span className="sla-list-time">{t("sla_medium_time")}</span>
                </div>
                <div className="sla-list-item" data-prio="HIGH">
                  <span className="sla-list-name">{t("sla_high_name")}</span>
                  <span className="sla-list-time">{t("sla_high_time")}</span>
                </div>
                <div className="sla-list-item" data-prio="URGENT">
                  <span className="sla-list-name">{t("sla_urgent_name")}</span>
                  <span className="sla-list-time">{t("sla_urgent_time")}</span>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </form>
    </div>
  );
}
