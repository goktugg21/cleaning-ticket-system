// Sprint 26B — Create Extra Work page.
//
// Reuses the building/customer matching shape from
// CreateTicketPage so a customer can pick a (building, customer)
// pair the backend will accept. Category dropdown drives an
// "Other" free-text input that the backend requires when
// category === "OTHER".
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronLeft } from "lucide-react";

import { api, getApiError } from "../api/client";
import { createExtraWork } from "../api/extraWork";
import type {
  Building,
  Customer,
  ExtraWorkCategory,
  ExtraWorkUrgency,
  PaginatedResponse,
} from "../api/types";


interface FormState {
  building: string;
  customer: string;
  title: string;
  description: string;
  category: ExtraWorkCategory;
  category_other_text: string;
  urgency: ExtraWorkUrgency;
  preferred_date: string;
}

const EMPTY_FORM: FormState = {
  building: "",
  customer: "",
  title: "",
  description: "",
  category: "DEEP_CLEANING",
  category_other_text: "",
  urgency: "NORMAL",
  preferred_date: "",
};

const CATEGORIES: { value: ExtraWorkCategory; label: string }[] = [
  { value: "DEEP_CLEANING", label: "Deep cleaning" },
  { value: "WINDOW_CLEANING", label: "Window cleaning" },
  { value: "FLOOR_MAINTENANCE", label: "Floor maintenance" },
  { value: "SANITARY_SERVICE", label: "Sanitary service" },
  { value: "WASTE_REMOVAL", label: "Waste removal" },
  { value: "FURNITURE_MOVING", label: "Furniture moving" },
  { value: "EVENT_CLEANING", label: "Event cleaning" },
  { value: "EMERGENCY_CLEANING", label: "Emergency cleaning" },
  { value: "OTHER", label: "Other" },
];

const URGENCIES: { value: ExtraWorkUrgency; label: string }[] = [
  { value: "NORMAL", label: "Normal" },
  { value: "HIGH", label: "High" },
  { value: "URGENT", label: "Urgent" },
];

const DESCRIPTION_HELPER =
  "Please describe the extra work in as much detail as possible: " +
  "exact area, room, surface, preferred date/time, urgency, access " +
  "instructions, photos, and anything that affects pricing.";

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


export function CreateExtraWorkPage() {
  const navigate = useNavigate();

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  useEffect(() => {
    let cancelled = false;
    async function load() {
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

  // Keep selections in sync if the customer-building intersection
  // narrows after a pick.
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

  function update<K extends keyof FormState>(name: K, value: FormState[K]) {
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
    if (!form.building || !form.customer) {
      setError("Building and customer must both be selected.");
      return;
    }
    if (form.category === "OTHER" && !form.category_other_text.trim()) {
      setError("Please describe the unlisted category in the Other field.");
      return;
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
      });
      navigate(`/extra-work/${created.id}`);
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
          <Link to="/extra-work" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            Back to Extra Work
          </Link>
          <h2 className="page-title">New Extra Work request</h2>
          <p className="page-sub">
            Describe the additional service you'd like. The provider
            will review it, propose pricing line by line, and ask you
            to approve before any work happens.
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
          No accessible building or customer. Ask your administrator to
          give you access.
        </div>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <form className="create-layout" onSubmit={handleSubmit}>
        <div className="card create-main">
          <div className="form-section">
            <div className="form-section-title">Location &amp; customer</div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-building">
                  Building
                </label>
                <select
                  id="ew-building"
                  className="field-select"
                  value={form.building}
                  onChange={(event) => update("building", event.target.value)}
                  disabled={filteredBuildings.length === 0}
                  required
                >
                  <option value="" disabled>
                    Select a building…
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
                  Customer
                </label>
                <select
                  id="ew-customer"
                  className="field-select"
                  value={form.customer}
                  onChange={(event) => update("customer", event.target.value)}
                  disabled={filteredCustomers.length === 0}
                  required
                >
                  <option value="" disabled>
                    Select a customer…
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
            <div className="form-section-title">What needs to happen</div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-category">
                  Category
                </label>
                <select
                  id="ew-category"
                  className="field-select"
                  value={form.category}
                  onChange={(event) =>
                    update("category", event.target.value as ExtraWorkCategory)
                  }
                >
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ew-urgency">
                  Urgency
                </label>
                <select
                  id="ew-urgency"
                  className="field-select"
                  value={form.urgency}
                  onChange={(event) =>
                    update("urgency", event.target.value as ExtraWorkUrgency)
                  }
                >
                  {URGENCIES.map((u) => (
                    <option key={u.value} value={u.value}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {form.category === "OTHER" && (
              <div className="field">
                <label className="field-label" htmlFor="ew-category-other">
                  Other category (required)
                </label>
                <input
                  id="ew-category-other"
                  className="field-input"
                  type="text"
                  maxLength={128}
                  placeholder="e.g. Sealant repair"
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
                Title
              </label>
              <input
                id="ew-title"
                className="field-input"
                type="text"
                maxLength={255}
                placeholder="Short summary, e.g. 'Strip and seal lobby floor'"
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
                required
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-description">
                Description
              </label>
              <textarea
                id="ew-description"
                className="field-textarea"
                placeholder={DESCRIPTION_HELPER}
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                required
              />
              <div
                className="muted small"
                style={{ marginTop: 6, lineHeight: 1.4 }}
              >
                {DESCRIPTION_HELPER}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-preferred-date">
                Preferred date (optional)
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

          <div
            className="form-actions"
            style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}
          >
            <Link to="/extra-work" className="btn btn-secondary btn-sm">
              Cancel
            </Link>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={submitting || loadingOptions || noOptions}
            >
              {submitting ? "Submitting…" : "Submit request"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
