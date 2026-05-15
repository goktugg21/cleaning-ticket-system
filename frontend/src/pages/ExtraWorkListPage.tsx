// Sprint 26C — Extra Work list page.
//
// Plain English labels for the MVP (no i18n) per the Sprint 26C
// brief. The list endpoint is already scoped server-side, so this
// page just renders whatever rows the API returns.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, PlusCircle } from "lucide-react";

import { listExtraWork } from "../api/extraWork";
import type { ExtraWorkRequestList } from "../api/types";
import { getApiError } from "../api/client";


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

const STATUS_LABELS: Record<string, string> = {
  REQUESTED: "Requested",
  UNDER_REVIEW: "Under review",
  PRICING_PROPOSED: "Pricing proposed",
  CUSTOMER_APPROVED: "Customer approved",
  CUSTOMER_REJECTED: "Customer rejected",
  CANCELLED: "Cancelled",
};


function formatDate(value: string | null): string {
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

function formatMoney(value: string | null | undefined): string {
  if (!value) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toFixed(2);
}

export function ExtraWorkListPage() {
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const response = await listExtraWork();
        if (!cancelled) setRows(response.results);
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
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            Back to dashboard
          </Link>
          <h2 className="page-title">Extra Work</h2>
          <p className="page-sub">
            Requests for additional services outside the standard
            cleaning contract. Pricing is proposed by the provider
            and approved by the customer before any work begins.
          </p>
        </div>
        <div className="page-header-actions">
          <Link className="btn btn-primary btn-sm" to="/extra-work/new">
            <PlusCircle size={14} strokeWidth={2.2} />
            <span style={{ marginLeft: 6 }}>New Extra Work</span>
          </Link>
        </div>
      </div>

      {loading && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {!loading && rows.length === 0 && !error && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          No Extra Work requests yet. Create one to get started.
        </div>
      )}

      {rows.length > 0 && (
        <div className="card" style={{ overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Category</th>
                <th>Building</th>
                <th>Customer</th>
                <th style={{ textAlign: "right" }}>Total</th>
                <th>Requested</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link to={`/extra-work/${row.id}`}>{row.title}</Link>
                  </td>
                  <td>{STATUS_LABELS[row.status] ?? row.status}</td>
                  <td>{CATEGORY_LABELS[row.category] ?? row.category}</td>
                  <td>{row.building_name}</td>
                  <td>{row.customer_name}</td>
                  <td style={{ textAlign: "right" }}>
                    {formatMoney(row.total_amount)}
                  </td>
                  <td>{formatDate(row.requested_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
