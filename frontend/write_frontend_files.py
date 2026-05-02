from pathlib import Path

files = {
"src/api/client.ts": r'''
import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api",
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("accessToken");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function getApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (typeof data === "string") return data;
    if (data?.detail) return String(data.detail);
    if (data?.code) return String(data.code);
    if (data) return JSON.stringify(data);
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Unknown error";
}
''',

"src/api/types.ts": r'''
export type Role =
  | "SUPER_ADMIN"
  | "COMPANY_ADMIN"
  | "BUILDING_MANAGER"
  | "CUSTOMER_USER";

export type TicketStatus =
  | "OPEN"
  | "IN_PROGRESS"
  | "WAITING_CUSTOMER_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "CLOSED"
  | "REOPENED_BY_ADMIN";

export type TicketMessageType = "PUBLIC_REPLY" | "INTERNAL_NOTE";

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Me {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  language: string;
  is_active: boolean;
  company_ids: number[];
  building_ids: number[];
  customer_ids: number[];
}

export interface Company {
  id: number;
  name: string;
  slug: string;
  default_language: string;
  is_active: boolean;
}

export interface Building {
  id: number;
  company: number;
  name: string;
  address: string;
  city: string;
  country: string;
  postal_code: string;
  is_active: boolean;
}

export interface Customer {
  id: number;
  company: number;
  building: number;
  name: string;
  contact_email: string;
  phone: string;
  language: string;
  is_active: boolean;
}

export interface TicketList {
  id: number;
  ticket_no: string;
  title: string;
  type: string;
  priority: string;
  status: TicketStatus;
  company: number;
  building: number;
  building_name: string;
  customer: number;
  customer_name: string;
  assigned_to: number | null;
  assigned_to_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface TicketStatusHistory {
  id: number;
  old_status: TicketStatus;
  new_status: TicketStatus;
  changed_by: number;
  changed_by_email: string;
  note: string;
  created_at: string;
}

export interface TicketDetail extends TicketList {
  description: string;
  room_label: string;
  created_by: number;
  created_by_email: string;
  first_response_at: string | null;
  sent_for_approval_at: string | null;
  approved_at: string | null;
  rejected_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  status_history: TicketStatusHistory[];
  allowed_next_statuses: TicketStatus[];
}

export interface TicketMessage {
  id: number;
  ticket: number;
  author: number;
  author_email: string;
  message: string;
  message_type: TicketMessageType;
  is_hidden: boolean;
  created_at: string;
}
''',

"src/auth/AuthContext.tsx": r'''
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { Me } from "../api/types";

interface AuthContextValue {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  reloadMe: () => Promise<void>;
}

interface TokenResponse {
  access: string;
  refresh: string;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const reloadMe = useCallback(async () => {
    const response = await api.get<Me>("/auth/me/");
    setMe(response.data);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    delete api.defaults.headers.common.Authorization;
    setMe(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.post<TokenResponse>("/auth/token/", { email, password });
    localStorage.setItem("accessToken", response.data.access);
    localStorage.setItem("refreshToken", response.data.refresh);
    api.defaults.headers.common.Authorization = `Bearer ${response.data.access}`;
    await reloadMe();
  }, [reloadMe]);

  useEffect(() => {
    const token = localStorage.getItem("accessToken");
    if (!token) {
      setLoading(false);
      return;
    }

    api.defaults.headers.common.Authorization = `Bearer ${token}`;

    reloadMe()
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [logout, reloadMe]);

  const value = useMemo(
    () => ({ me, loading, login, logout, reloadMe }),
    [me, loading, login, logout, reloadMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
''',

"src/pages/LoginPage.tsx": r'''
import { FormEvent, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const navigate = useNavigate();
  const { me, login } = useAuth();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("Admin12345!");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div>
          <p className="eyebrow">Cleaning Ticket System</p>
          <h1>Login</h1>
          <p className="muted">Django API token ile giriş.</p>
        </div>

        <form onSubmit={handleSubmit} className="form">
          <label>
            Email
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>

          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {error && <div className="error">{error}</div>}

          <button disabled={submitting}>
            {submitting ? "Logging in..." : "Login"}
          </button>
        </form>
      </section>
    </main>
  );
}
''',

"src/pages/DashboardPage.tsx": r'''
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getApiError } from "../api/client";
import type { PaginatedResponse, TicketList } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function DashboardPage() {
  const { me, logout } = useAuth();
  const [tickets, setTickets] = useState<TicketList[]>([]);
  const [error, setError] = useState("");

  async function loadTickets() {
    try {
      const response = await api.get<PaginatedResponse<TicketList>>("/tickets/");
      setTickets(response.data.results);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  useEffect(() => {
    loadTickets();
  }, []);

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1>Tickets</h1>
          <p className="muted">
            {me?.email} · {me?.role}
          </p>
        </div>

        <div className="actions">
          <Link className="button secondary" to="/tickets/new">New ticket</Link>
          <button className="secondary" onClick={logout}>Logout</button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="card">
        <div className="table">
          <div className="table-row table-head">
            <span>No</span>
            <span>Title</span>
            <span>Status</span>
            <span>Building</span>
            <span>Customer</span>
          </div>

          {tickets.map((ticket) => (
            <Link to={`/tickets/${ticket.id}`} className="table-row table-link" key={ticket.id}>
              <span>{ticket.ticket_no}</span>
              <span>{ticket.title}</span>
              <span><b className={`badge ${ticket.status.toLowerCase()}`}>{ticket.status}</b></span>
              <span>{ticket.building_name}</span>
              <span>{ticket.customer_name}</span>
            </Link>
          ))}

          {tickets.length === 0 && <p className="empty">No tickets yet.</p>}
        </div>
      </section>
    </main>
  );
}
''',

"src/pages/CreateTicketPage.tsx": r'''
import { FormEvent, useEffect, useState } from "react";
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
''',

"src/pages/TicketDetailPage.tsx": r'''
import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, getApiError } from "../api/client";
import type {
  PaginatedResponse,
  TicketDetail,
  TicketMessage,
  TicketMessageType,
  TicketStatus,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function TicketDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [statusNote, setStatusNote] = useState("");
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<TicketMessageType>("PUBLIC_REPLY");
  const [error, setError] = useState("");

  const isStaff =
    me?.role === "SUPER_ADMIN" ||
    me?.role === "COMPANY_ADMIN" ||
    me?.role === "BUILDING_MANAGER";

  async function loadTicket() {
    if (!id) return;

    const [ticketResponse, messageResponse] = await Promise.all([
      api.get<TicketDetail>(`/tickets/${id}/`),
      api.get<PaginatedResponse<TicketMessage>>(`/tickets/${id}/messages/`),
    ]);

    setTicket(ticketResponse.data);
    setMessages(messageResponse.data.results);
  }

  useEffect(() => {
    loadTicket().catch((err) => setError(getApiError(err)));
  }, [id]);

  async function changeStatus(toStatus: TicketStatus) {
    if (!id) return;
    setError("");

    try {
      const response = await api.post<TicketDetail>(`/tickets/${id}/status/`, {
        to_status: toStatus,
        note: statusNote,
      });
      setTicket(response.data);
      setStatusNote("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    if (!id) return;
    setError("");

    try {
      await api.post(`/tickets/${id}/messages/`, {
        message,
        message_type: isStaff ? messageType : "PUBLIC_REPLY",
      });
      setMessage("");
      await loadTicket();
    } catch (err) {
      setError(getApiError(err));
    }
  }

  if (!ticket) {
    return (
      <main className="page">
        <Link to="/" className="button secondary">Back</Link>
        <p>Loading...</p>
        {error && <div className="error">{error}</div>}
      </main>
    );
  }

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">{ticket.ticket_no}</p>
          <h1>{ticket.title}</h1>
          <p className="muted">
            {ticket.building_name} · {ticket.customer_name}
          </p>
        </div>

        <Link className="button secondary" to="/">Back</Link>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="grid detail-grid">
        <div className="card">
          <h2>Ticket</h2>
          <p>{ticket.description}</p>

          <dl className="meta">
            <div><dt>Status</dt><dd><b className={`badge ${ticket.status.toLowerCase()}`}>{ticket.status}</b></dd></div>
            <div><dt>Priority</dt><dd>{ticket.priority}</dd></div>
            <div><dt>Type</dt><dd>{ticket.type}</dd></div>
            <div><dt>Room</dt><dd>{ticket.room_label || "-"}</dd></div>
            <div><dt>Created by</dt><dd>{ticket.created_by_email}</dd></div>
            <div><dt>Assigned to</dt><dd>{ticket.assigned_to_email || "-"}</dd></div>
          </dl>
        </div>

        <div className="card">
          <h2>Workflow</h2>

          <label>
            Status note
            <input
              value={statusNote}
              onChange={(event) => setStatusNote(event.target.value)}
              placeholder="Optional note"
            />
          </label>

          <div className="status-actions">
            {ticket.allowed_next_statuses.map((status) => (
              <button key={status} onClick={() => changeStatus(status)}>
                Move to {status}
              </button>
            ))}

            {ticket.allowed_next_statuses.length === 0 && (
              <p className="muted">No allowed next status for your role.</p>
            )}
          </div>
        </div>
      </section>

      <section className="grid detail-grid">
        <div className="card">
          <h2>Messages</h2>

          <div className="messages">
            {messages.map((item) => (
              <article className={`message ${item.message_type === "INTERNAL_NOTE" ? "internal" : ""}`} key={item.id}>
                <div className="message-head">
                  <b>{item.author_email}</b>
                  <span>{item.message_type}</span>
                </div>
                <p>{item.message}</p>
              </article>
            ))}

            {messages.length === 0 && <p className="empty">No messages yet.</p>}
          </div>
        </div>

        <div className="card">
          <h2>Add message</h2>

          <form className="form" onSubmit={submitMessage}>
            {isStaff && (
              <label>
                Message type
                <select
                  value={messageType}
                  onChange={(event) => setMessageType(event.target.value as TicketMessageType)}
                >
                  <option value="PUBLIC_REPLY">PUBLIC_REPLY</option>
                  <option value="INTERNAL_NOTE">INTERNAL_NOTE</option>
                </select>
              </label>
            )}

            <label>
              Message
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                required
              />
            </label>

            <button>Send message</button>
          </form>
        </div>
      </section>

      <section className="card">
        <h2>Status history</h2>
        <div className="history">
          {ticket.status_history.map((item) => (
            <div className="history-item" key={item.id}>
              <b>{item.old_status} → {item.new_status}</b>
              <span>{item.changed_by_email}</span>
              <p>{item.note || "-"}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
''',

"src/App.tsx": r'''
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { CreateTicketPage } from "./pages/CreateTicketPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();

  if (loading) {
    return <main className="page"><p>Loading...</p></main>;
  }

  if (!me) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets/new"
            element={
              <ProtectedRoute>
                <CreateTicketPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets/:id"
            element={
              <ProtectedRoute>
                <TicketDetailPage />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
''',

"src/main.tsx": r'''
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
''',

"src/index.css": r'''
:root {
  color: #172033;
  background: #f4f6fb;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
}

a {
  color: inherit;
  text-decoration: none;
}

button,
.button {
  border: 0;
  border-radius: 12px;
  padding: 11px 16px;
  background: #172033;
  color: white;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

button.secondary,
.button.secondary {
  background: #e9edf7;
  color: #172033;
}

input,
select,
textarea {
  width: 100%;
  border: 1px solid #d8deeb;
  border-radius: 12px;
  padding: 11px 12px;
  font: inherit;
  background: white;
  color: #172033;
}

textarea {
  min-height: 120px;
  resize: vertical;
}

label {
  display: grid;
  gap: 8px;
  font-weight: 700;
}

h1,
h2,
p {
  margin-top: 0;
}

.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}

.auth-card {
  width: min(440px, 100%);
  background: white;
  border-radius: 24px;
  padding: 28px;
  box-shadow: 0 20px 60px rgba(21, 32, 51, 0.12);
}

.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 32px 20px;
}

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
  margin-bottom: 24px;
}

.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.card {
  background: white;
  border-radius: 24px;
  padding: 22px;
  box-shadow: 0 10px 34px rgba(21, 32, 51, 0.08);
}

.form {
  display: grid;
  gap: 16px;
}

.grid {
  display: grid;
  gap: 18px;
}

.grid.two,
.detail-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.eyebrow {
  color: #657089;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 6px;
}

.muted {
  color: #657089;
}

.error {
  background: #fff1f1;
  color: #a21d1d;
  border: 1px solid #ffd0d0;
  border-radius: 14px;
  padding: 12px 14px;
  margin-bottom: 16px;
  font-weight: 700;
}

.table {
  display: grid;
}

.table-row {
  display: grid;
  grid-template-columns: 160px 1.4fr 220px 1fr 1fr;
  gap: 14px;
  padding: 14px 8px;
  border-bottom: 1px solid #edf0f6;
  align-items: center;
}

.table-head {
  color: #657089;
  font-size: 13px;
  font-weight: 800;
  text-transform: uppercase;
}

.table-link:hover {
  background: #f7f9fd;
}

.badge {
  border-radius: 999px;
  padding: 5px 9px;
  background: #eef2ff;
  color: #273c8f;
  font-size: 12px;
}

.badge.closed {
  background: #e8f7ee;
  color: #16723a;
}

.badge.rejected {
  background: #fff1f1;
  color: #a21d1d;
}

.badge.in_progress,
.badge.waiting_customer_approval {
  background: #fff6df;
  color: #8a5b00;
}

.meta {
  display: grid;
  gap: 12px;
  margin: 0;
}

.meta div {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #edf0f6;
  padding-bottom: 10px;
}

.meta dt {
  color: #657089;
  font-weight: 800;
}

.meta dd {
  margin: 0;
  text-align: right;
}

.status-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.messages {
  display: grid;
  gap: 12px;
}

.message {
  border: 1px solid #e3e8f3;
  border-radius: 16px;
  padding: 14px;
  background: #fbfcff;
}

.message.internal {
  background: #fff8e7;
  border-color: #ffe1a3;
}

.message-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #657089;
  font-size: 13px;
}

.history {
  display: grid;
  gap: 12px;
}

.history-item {
  border-left: 4px solid #172033;
  padding-left: 12px;
}

.history-item span {
  display: block;
  color: #657089;
  font-size: 13px;
  margin-top: 4px;
}

.empty {
  color: #657089;
  padding: 16px 0;
}

@media (max-width: 820px) {
  .topbar,
  .grid.two,
  .detail-grid {
    grid-template-columns: 1fr;
    display: grid;
  }

  .table-row {
    grid-template-columns: 1fr;
  }
}
'''
}

for file_path, content in files.items():
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")

Path(".env").write_text("VITE_API_BASE_URL=http://localhost:8000/api\n", encoding="utf-8")

print("Frontend files written successfully.")
