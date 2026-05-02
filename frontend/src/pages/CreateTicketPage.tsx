import type { FormEvent } from "react";
import { useEffect, useState } from "react";
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

export function CreateTicketPage() {
  const navigate = useNavigate();
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState<CreateTicketForm>({
    title: "",
    description: "",
    room_label: "",
    type: "REPORT",
    priority: "NORMAL",
    building: "",
    customer: "",
  });

  useEffect(() => {
    async function loadOptions() {
      const [buildingResponse, customerResponse] = await Promise.all([
        api.get<PaginatedResponse<Building>>("/buildings/"),
        api.get<PaginatedResponse<Customer>>("/customers/"),
      ]);

      setBuildings(buildingResponse.data.results);
      setCustomers(customerResponse.data.results);

      setForm((current) => ({
        ...current,
        building: current.building || String(buildingResponse.data.results[0]?.id ?? ""),
        customer: current.customer || String(customerResponse.data.results[0]?.id ?? ""),
      }));
    }

    loadOptions().catch((err) => setError(getApiError(err)));
  }, []);

  function update(name: keyof CreateTicketForm, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");

    if (!form.building || !form.customer) {
      setError("Building and customer are required.");
      return;
    }

    try {
      const response = await api.post("/tickets/", {
        ...form,
        building: Number(form.building),
        customer: Number(form.customer),
      });
      navigate(`/tickets/${response.data.id}`);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">New ticket</p>
          <h1>Create ticket</h1>
        </div>
        <Link className="button secondary" to="/">Back</Link>
      </header>

      <section className="card">
        <form className="form" onSubmit={handleSubmit}>
          <label>
            Title
            <input value={form.title} onChange={(event) => update("title", event.target.value)} required />
          </label>

          <label>
            Description
            <textarea value={form.description} onChange={(event) => update("description", event.target.value)} required />
          </label>

          <label>
            Room label
            <input value={form.room_label} onChange={(event) => update("room_label", event.target.value)} />
          </label>

          <div className="grid two">
            <label>
              Building
              <select value={form.building} onChange={(event) => update("building", event.target.value)}>
                {buildings.map((building) => (
                  <option value={building.id} key={building.id}>{building.name}</option>
                ))}
              </select>
            </label>

            <label>
              Customer
              <select value={form.customer} onChange={(event) => update("customer", event.target.value)}>
                {customers.map((customer) => (
                  <option value={customer.id} key={customer.id}>{customer.name}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid two">
            <label>
              Type
              <select value={form.type} onChange={(event) => update("type", event.target.value)}>
                <option value="REPORT">REPORT</option>
                <option value="REQUEST">REQUEST</option>
                <option value="COMPLAINT">COMPLAINT</option>
              </select>
            </label>

            <label>
              Priority
              <select value={form.priority} onChange={(event) => update("priority", event.target.value)}>
                <option value="LOW">LOW</option>
                <option value="NORMAL">NORMAL</option>
                <option value="HIGH">HIGH</option>
                <option value="URGENT">URGENT</option>
              </select>
            </label>
          </div>

          {error && <div className="error">{error}</div>}

          <button>Create ticket</button>
        </form>
      </section>
    </main>
  );
}
