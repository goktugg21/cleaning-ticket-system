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

interface PriorityCard {
  value: "NORMAL" | "HIGH" | "URGENT";
  label: string;
  helper: string;
  icon: typeof Info;
}

const TICKET_TYPES = [
  { value: "REPORT", label: "Report" },
  { value: "COMPLAINT", label: "Complaint" },
  { value: "REQUEST", label: "Request" },
  { value: "SUGGESTION", label: "Suggestion" },
  { value: "QUOTE_REQUEST", label: "Quote request" },
];

const PRIORITY_CARDS: PriorityCard[] = [
  {
    value: "NORMAL",
    label: "Medium",
    helper: "Standard 24 h SLA",
    icon: CircleCheck,
  },
  {
    value: "HIGH",
    label: "High",
    helper: "Expedited — 4 h SLA",
    icon: TriangleAlert,
  },
  {
    value: "URGENT",
    label: "Urgent",
    helper: "Critical — 1 h SLA",
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

  const filteredCustomers = useMemo(() => {
    if (!form.building) return customers;
    return customers.filter(
      (customer) => customer.building === Number(form.building),
    );
  }, [customers, form.building]);

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

  const selectedBuilding = useMemo(
    () => buildings.find((b) => String(b.id) === form.building),
    [buildings, form.building],
  );
  const selectedCustomer = useMemo(
    () => customers.find((c) => String(c.id) === form.customer),
    [customers, form.customer],
  );
  const selectedType = useMemo(
    () => TICKET_TYPES.find((t) => t.value === form.type),
    [form.type],
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
      setError("Short description is required.");
      return;
    }
    if (!form.description.trim()) {
      setError("Detailed description is required.");
      return;
    }
    if (!form.building) {
      setError("Please choose a location.");
      return;
    }
    if (!form.customer) {
      setError("Please choose a customer.");
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
            Back to tickets
          </Link>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            New ticket
          </div>
          <h2 className="page-title">Create ticket</h2>
          <p className="page-sub">
            Capture the request clearly and assign the right location.
          </p>
        </div>
      </div>

      {loadingOptions && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {noOptions && !error && (
        <div className="alert-error" style={{ marginBottom: 16 }}>
          You don't have access to any building or customer to create a ticket
          against.
        </div>
      )}

      <form className="create-layout" onSubmit={handleSubmit}>
        <div className="card create-main">
          <div className="form-section">
            <div className="form-section-title">Issue details</div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="f-type">
                  Category
                </label>
                <select
                  id="f-type"
                  className="field-select"
                  value={form.type}
                  onChange={(event) => update("type", event.target.value)}
                >
                  {TICKET_TYPES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="f-building">
                  Location *
                </label>
                <select
                  id="f-building"
                  className="field-select"
                  value={form.building}
                  onChange={(event) => update("building", event.target.value)}
                  disabled={buildings.length === 0}
                  required
                >
                  <option value="" disabled>
                    Select facility / zone…
                  </option>
                  {buildings.map((building) => (
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
                  Customer *
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
                      ? "No customers in this location"
                      : "Select customer…"}
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
                  Room / area
                </label>
                <input
                  id="f-room"
                  className="field-input"
                  type="text"
                  placeholder="e.g. Server Room A, Bldg 4"
                  value={form.room_label}
                  onChange={(event) => update("room_label", event.target.value)}
                />
              </div>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="f-title">
                Short description *
              </label>
              <input
                id="f-title"
                className="field-input"
                type="text"
                placeholder="Brief summary of the issue"
                maxLength={255}
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
                required
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="f-desc">
                Detailed description *
              </label>
              <textarea
                id="f-desc"
                className="field-textarea"
                placeholder="Provide as much context as possible — equipment, location, observed behaviour, urgency."
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                required
              />
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title">Priority level</div>
            <div className="form-section-helper">
              Select the impact level of this issue.
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
                    <span className="priority-card-label">{card.label}</span>
                    <span className="priority-card-helper">{card.helper}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title">Attachments</div>
            <div className="form-section-helper">
              Optional. Photos and PDFs help the team respond faster.
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
                  : "Click to upload or drag and drop"}
              </span>
              <span className="upload-hint">
                {stagedAttachment
                  ? `${(stagedAttachment.size / 1024 / 1024).toFixed(2)} MB · click to replace`
                  : "PNG, JPG, PDF up to 10 MB"}
              </span>
              <input
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf"
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  if (file && file.size > 10 * 1024 * 1024) {
                    setError("Attachment file size cannot exceed 10 MB.");
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
              Cancel
            </Link>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || loadingOptions || noOptions}
            >
              {submitting ? "Creating…" : "Create ticket"}
              <ArrowRight size={14} strokeWidth={2.5} />
            </button>
          </div>
        </div>

        <aside className="create-side">
          <div className="card">
            <div className="section-head">
              <div className="section-head-title">Summary</div>
            </div>
            <div className="side-card-body">
              <div className="preview-list">
                <div className="preview-row">
                  <span className="preview-key">Location</span>
                  <span className="preview-val">
                    {selectedBuilding?.name || "—"}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">Customer</span>
                  <span className="preview-val">
                    {selectedCustomer?.name || "—"}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">Category</span>
                  <span className="preview-val">
                    {selectedType?.label || "Report"}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">Priority</span>
                  <span className="preview-val">
                    {form.priority.charAt(0) +
                      form.priority.slice(1).toLowerCase()}
                  </span>
                </div>
                <div className="preview-row">
                  <span className="preview-key">Attachment</span>
                  <span className="preview-val">
                    {stagedAttachment ? stagedAttachment.name : "None"}
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
                <div className="section-head-title">Ticket guidelines</div>
              </div>
            </div>
            <div style={{ padding: "14px 16px 16px" }}>
              <ul className="guideline-list">
                <li className="guideline-item">
                  <CircleCheck size={14} strokeWidth={2.5} />
                  <span>
                    Be as specific as possible in the short description for
                    faster routing.
                  </span>
                </li>
                <li className="guideline-item">
                  <CircleCheck size={14} strokeWidth={2.5} />
                  <span>Include exact room numbers or asset IDs if known.</span>
                </li>
                <li className="guideline-item">
                  <CircleCheck size={14} strokeWidth={2.5} />
                  <span>
                    Photos drastically improve response times for maintenance
                    issues.
                  </span>
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
                <div className="section-head-title">Response SLAs</div>
              </div>
            </div>
            <div style={{ padding: "6px 16px 12px" }}>
              <div className="sla-list">
                <div className="sla-list-item" data-prio="NORMAL">
                  <span className="sla-list-name">Medium priority</span>
                  <span className="sla-list-time">24 hours</span>
                </div>
                <div className="sla-list-item" data-prio="HIGH">
                  <span className="sla-list-name">High priority</span>
                  <span className="sla-list-time">4 hours</span>
                </div>
                <div className="sla-list-item" data-prio="URGENT">
                  <span className="sla-list-name">Urgent</span>
                  <span className="sla-list-time">Immediate (1 h)</span>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </form>
    </div>
  );
}
