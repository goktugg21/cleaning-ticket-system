// Sprint 26C — Extra Work list page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n
// namespace; audit doc §6 / §7 row 19 flagged this page as
// hard-coded English. Functionality is unchanged.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, PlusCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listExtraWork } from "../api/extraWork";
import type {
  ExtraWorkCategory,
  ExtraWorkRequestList,
  ExtraWorkStatus,
} from "../api/types";
import { getApiError } from "../api/client";


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

const STATUS_I18N_KEY: Record<ExtraWorkStatus, string> = {
  REQUESTED: "status.requested",
  UNDER_REVIEW: "status.under_review",
  PRICING_PROPOSED: "status.pricing_proposed",
  CUSTOMER_APPROVED: "status.customer_approved",
  CUSTOMER_REJECTED: "status.customer_rejected",
  CANCELLED: "status.cancelled",
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
  const { t } = useTranslation(["extra_work", "common"]);
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
    <div data-testid="extra-work-list-page">
      <div className="page-header">
        <div>
          <Link to="/" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_dashboard")}
          </Link>
          <h2 className="page-title">{t("list.page_title")}</h2>
          <p className="page-sub">{t("list.page_subtitle")}</p>
        </div>
        <div className="page-header-actions">
          <Link
            className="btn btn-primary btn-sm"
            to="/extra-work/new"
            data-testid="extra-work-list-create-link"
          >
            <PlusCircle size={14} strokeWidth={2.2} />
            <span style={{ marginLeft: 6 }}>{t("list.create_button")}</span>
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
        <div
          className="alert-info"
          style={{ marginBottom: 16 }}
          role="status"
          data-testid="extra-work-list-empty"
        >
          {t("list.empty_state")}
        </div>
      )}

      {rows.length > 0 && (
        <div className="card" style={{ overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("list.column_title")}</th>
                <th>{t("list.column_status")}</th>
                <th>{t("list.column_category")}</th>
                <th>{t("list.column_building")}</th>
                <th>{t("list.column_customer")}</th>
                <th style={{ textAlign: "right" }}>
                  {t("list.column_total")}
                </th>
                <th>{t("list.column_requested")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link to={`/extra-work/${row.id}`}>{row.title}</Link>
                  </td>
                  <td>{t(STATUS_I18N_KEY[row.status] ?? row.status)}</td>
                  <td>{t(CATEGORY_I18N_KEY[row.category] ?? row.category)}</td>
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
