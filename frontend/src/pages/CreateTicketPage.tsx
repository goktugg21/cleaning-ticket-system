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
  { value: "REPORT", label: "Report" },
  { value: "COMPLAINT", label: "Complaint" },
  { value: "REQUEST", label: "Request" },
  { value: "SUGGESTION", label: "Suggestion" },
  { value: "QUOTE_REQUEST", label: "Quote request" },
];

const PRIORITY_OPTIONS = [
  { value: "NORMAL", label: "Normal" },
  { value: "HIGH", label: "High" },
  { value: "URGENT", label: "Urgent" },
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
              (c) => c.building === firstBuilding.id,
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
    return customers.filter((c) => c.building === Number(form.building));
  }, [customers, form.building]);

  useEffect(() => {
    if (!form.customer) return;
    const stillValid = filteredCustomers.some(
      (c) => String(c.id) === form.customer,
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

  const noOptions = !loadingOptions && (buildings.length === 0 || customers.length === 0);

  return (
    <>
      <header className="page-head">
        <div>
          <Link to="/" className="link-back">
            ← Back to tickets
          </Link>
          <p className="eyebrow">New ticket</p>
          <h1>Create ticket</h1>
          <p className="muted">
            Provide a clear title and description so the team can act quickly.
          </p>
        </div>
      </header>

      <section className="card">
        {loadingOptions && <p className="muted">Loading buildings and customers…</p>}

        {noOptions && !error && (
          <div className="error">
            You don't have access to any building or customer to create a ticket against.
          </div>
        )}

        <form className="form" onSubmit={handleSubmit}>
          <label>
            <span>Title *</span>
            <input
              value={form.title}
              onChange={(event) => update("title", event.target.value)}
              maxLength={255}
              required
            />
          </label>

          <label>
            <span>Description *</span>
            <textarea
              value={form.description}
              onChange={(event) => update("description", event.target.value)}
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

          {error && <div className="error">{error}</div>}

          <div className="actions">
            <Link to="/" className="button secondary">
              Cancel
            </Link>
            <button disabled={submitting || loadingOptions || noOptions}>
              {submitting ? "Creating…" : "Create ticket"}
            </button>
          </div>
        </form>
      </section>
    </>
  );
}
