// Invoicing Phase 5 — the customer "Facturen" LIST page (read-only).
//
// A CUSTOMER_USER's own SENT invoices (GET /api/invoices/my/). No due panel,
// no generate, no filters — a read-only list; each row opens the read-only
// detail. The backend redacts + scopes (SENT-only, membership-level).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BadgeEuro } from "lucide-react";

import { getApiError } from "../api/client";
import { listMyInvoices } from "../api/invoices";
import type { CustomerInvoice } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { formatMoney } from "../lib/intl";

function formatPeriod(year: number | null, month: number | null): string {
  if (!year || !month) return "—";
  return `${String(month).padStart(2, "0")}-${year}`;
}

export function MyInvoicesPage() {
  const { t } = useTranslation("common");
  const [invoices, setInvoices] = useState<CustomerInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const rows = await listMyInvoices();
        if (!cancelled) setInvoices(rows);
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
    <div data-testid="my-invoices-page">
      <PageHeader
        eyebrow={t("customer_facturen.eyebrow")}
        title={t("customer_facturen.title")}
        subtitle={t("customer_facturen.subtitle")}
      />

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : invoices.length === 0 ? (
        <EmptyState
          icon={BadgeEuro}
          title={t("customer_facturen.empty_title")}
          description={t("customer_facturen.empty_desc")}
        />
      ) : (
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="data-table" data-testid="my-invoices-table">
            <thead>
              <tr>
                <th>{t("customer_facturen.col_number")}</th>
                <th>{t("customer_facturen.col_building")}</th>
                <th>{t("customer_facturen.col_period")}</th>
                <th>{t("customer_facturen.col_status")}</th>
                <th style={{ textAlign: "right" }}>
                  {t("customer_facturen.col_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} data-testid="my-invoices-row">
                  <td>
                    <Link to={`/my/facturen/${inv.id}`} className="link">
                      {inv.number ?? `#${inv.id}`}
                      {inv.is_reversal && (
                        <span className="muted small" style={{ marginLeft: 6 }}>
                          ({t("facturen.credit_note")})
                        </span>
                      )}
                    </Link>
                  </td>
                  <td className="muted small">
                    {inv.building_name ?? t("facturen.all_buildings")}
                  </td>
                  <td className="muted small">
                    {formatPeriod(inv.period_year, inv.period_month)}
                  </td>
                  <td>
                    <span className="cell-tag cell-tag-open">
                      <i />
                      {t("facturen.status_sent")}
                    </span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <strong>{formatMoney(inv.total_amount)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
