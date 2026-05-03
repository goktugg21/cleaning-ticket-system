import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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

const TICKET_TYPES = [
  { value: "REPORT", label: "Report", helper: "Routine cleaning or facility report" },
  { value: "COMPLAINT", label: "Complaint", helper: "Something needs attention" },
  { value: "REQUEST", label: "Request", helper: "A service or maintenance request" },
  { value: "SUGGESTION", label: "Suggestion", helper: "Improvement idea or feedback" },
  { value: "QUOTE_REQUEST", label: "Quote request", helper: "Pricing or work estimate" },
];

const PRIORITY_OPTIONS = [
  {
    value: "NORMAL",
    label: "Normal",
    helper: "Standard follow-up",
  },
  {
    value: "HIGH",
    label: "High",
    helper: "Needs faster attention",
  },
  {
    value: "URGENT",
    label: "Urgent",
    helper: "Critical operational issue",
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
          building: current.building || (firstBuilding ? String(firstBuilding.id) : ""),
          customer: current.customer || (firstCustomer ? String(firstCustomer.id) : ""),
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
    return customers.filter((customer) => customer.building === Number(form.building));
  }, [customers, form.building]);

  const selectedType = useMemo(
    () => TICKET_TYPES.find((option) => option.value === form.type),
    [form.type],
  );

  const selectedBuilding = useMemo(
    () => buildings.find((building) => String(building.id) === form.building),
    [buildings, form.building],
  );

  const selectedCustomer = useMemo(
    () => customers.find((customer) => String(customer.id) === form.customer),
    [customers, form.customer],
  );

  useEffect(() => {
    if (!form.customer) return;

    const stillValid = filteredCustomers.some(
      (customer) => String(customer.id) === form.customer,
    );

    if (!stillValid) {
      setForm((current) => ({
        ...current,
        customer: filteredCustomers[0] ? String(filteredCustomers[0].id) : "",
      }));
    }
  }, [filteredCustomers, form.customer]);

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
      setError("Title is required.");
      return;
    }

    if (!form.description.trim()) {
      setError("Description is required.");
      return;
    }

    if (!form.building) {
      setError("Please choose a building.");
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

      navigate(`/tickets/${response.data.id}`);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const noOptions =
    !loadingOptions && (buildings.length === 0 || customers.length === 0);

  return (
    <>
      <header className="page-head hero-head">
        <div>
          <Link to="/" className="link-back">
            ← Back to tickets
          </Link>
          <p className="eyebrow">New ticket</p>
          <h1>Create ticket</h1>
          <p className="muted">
            Capture the request clearly, assign the right location, and let the team move fast.
          </p>
        </div>
      </header>

      {loadingOptions && (
        <section className="card soft-card">
          <p className="muted">Loading buildings and customers…</p>
        </section>
      )}

      {noOptions && !error && (
        <div className="error">
          You don't have access to any building or customer to create a ticket against.
        </div>
      )}

      <form className="create-ticket-layout" onSubmit={handleSubmit}>
        <section className="card create-ticket-main">
          <div className="form-section-head">
            <div>
              <p className="eyebrow">Ticket information</p>
              <h2>Request details</h2>
            </div>
            <span className="quiet-pill">Required fields marked *</span>
          </div>

          <div className="form-section">
            <label>
              <span>Title *</span>
              <input
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
                maxLength={255}
                placeholder="e.g. Restroom cleaning needed on floor 2"
                required
              />
            </label>

            <label>
              <span>Description *</span>
              <textarea
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                placeholder="Describe the issue, location, urgency, and any useful context."
                required
              />
            </label>

            <label>
              <span>Room / area</span>
              <input
                value={form.room_label}
                onChange={(event) => update("room_label", event.target.value)}
                placeholder="e.g. Ground floor lobby"
              />
            </label>
          </div>

          <div className="form-section split-section">
            <div>
              <p className="section-kicker">Location</p>
              <div className="grid two">
                <label>
                  <span>Building *</span>
                  <select
                    value={form.building}
                    onChange={(event) => update("building", event.target.value)}
                    required
                    disabled={buildings.length === 0}
                  >
                    <option value="" disabled>
                      Select a building
                    </option>
                    {buildings.map((building) => (
                      <option value={building.id} key={building.id}>
                        {building.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  <span>Customer *</span>
                  <select
                    value={form.customer}
                    onChange={(event) => update("customer", event.target.value)}
                    required
                    disabled={filteredCustomers.length === 0}
                  >
                    <option value="" disabled>
                      {filteredCustomers.length === 0
                        ? "No customers in this building"
                        : "Select a customer"}
                    </option>
                    {filteredCustomers.map((customer) => (
                      <option value={customer.id} key={customer.id}>
                        {customer.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div>
              <p className="section-kicker">Category</p>
              <div className="grid two">
                <label>
                  <span>Type</span>
                  <select
                    value={form.type}
                    onChange={(event) => update("type", event.target.value)}
                  >
                    {TICKET_TYPES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  <span>Priority</span>
                  <select
                    value={form.priority}
                    onChange={(event) => update("priority", event.target.value)}
                  >
                    {PRIORITY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </div>

          {error && <div className="error">{error}</div>}

          <div className="actions form-actions">
            <Link to="/" className="button secondary">
              Cancel
            </Link>
            <button disabled={submitting || loadingOptions || noOptions}>
              {submitting ? "Creating…" : "Create ticket"}
            </button>
          </div>
        </section>

        <aside className="create-ticket-side">
          <section className="card side-card">
            <p className="eyebrow">Priority</p>
            <h2>Set urgency</h2>

            <div className="priority-choice-list">
              {PRIORITY_OPTIONS.map((option) => (
                <button
                  type="button"
                  key={option.value}
                  className={`priority-choice ${
                    form.priority === option.value ? "selected" : ""
                  }`}
                  onClick={() => update("priority", option.value)}
                >
                  <span>
                    <b>{option.label}</b>
                    <small>{option.helper}</small>
                  </span>
                  <i aria-hidden />
                </button>
              ))}
            </div>
          </section>

          <section className="card side-card">
            <p className="eyebrow">Summary</p>
            <h2>Before submit</h2>

            <dl className="preview-list">
              <div>
                <dt>Building</dt>
                <dd>{selectedBuilding?.name || "Not selected"}</dd>
              </div>
              <div>
                <dt>Customer</dt>
                <dd>{selectedCustomer?.name || "Not selected"}</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>{selectedType?.label || "Report"}</dd>
              </div>
              <div>
                <dt>Attachments</dt>
                <dd>Can be added after ticket creation</dd>
              </div>
            </dl>
          </section>

          <section className="card side-card muted-card">
            <h2>Next step</h2>
            <p className="muted">
              After creating the ticket, you can add files, send updates, assign a manager,
              and move the ticket through the approval workflow.
            </p>
          </section>
        </aside>
      </form>
    </>
  );
}
