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
import { BillingCutoffNotice } from "../components/BillingCutoffNotice";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { formatMoney } from "../lib/intl";
import { monthName } from "../lib/billingSentence";

/** P-7 S4.1 — the period as words ("augustus 2026").
 *  P-15 (P-14's S4 finding) — a SENT invoice with no stored period
 *  says its SEND month instead of a dash: a dash on a money row reads
 *  like an error beside neighbours that say "juni 2026". */
function formatPeriod(
  year: number | null,
  month: number | null,
  sentAt: string | null,
): string {
  if (year && month) {
    return monthName(`${year}-${String(month).padStart(2, "0")}`);
  }
  if (sentAt) return monthName(sentAt.slice(0, 7));
  return "—";
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

      {/* Sprint W1-B item 14 — the other half of the same explanation.
          This page is where "why is work I never approved on my bill?"
          gets asked, so this is where it gets answered, next to the
          bills rather than in a mail the reader has to go and find. */}
      <BillingCutoffNotice variant="invoice" />

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
          {/* P-16 (P-14 S4) — at phone width this money page showed no
              money: PERIODE, STATUS and TOTAAL sat inside the table's
              own scroll with no affordance. The FE-7 `table-cards`
              collapse turns every row into a card; the page's own
              media rule puts number and TOTAL first. */}
          <table
            className="data-table table-cards my-invoices-cards"
            data-testid="my-invoices-table"
          >
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
                  <td className="td-subject">
                    <Link to={`/my/facturen/${inv.id}`} className="link">
                      {inv.number ?? `#${inv.id}`}
                      {inv.is_reversal && (
                        <span className="muted small" style={{ marginLeft: 6 }}>
                          ({t("facturen.credit_note")})
                        </span>
                      )}
                      {inv.credited_by_number && (
                        <span className="muted small" style={{ marginLeft: 6 }}>
                          (
                          {t("facturen.credited_by", {
                            number: inv.credited_by_number,
                          })}
                          )
                        </span>
                      )}
                    </Link>
                  </td>
                  <td
                    className="muted small"
                    data-label={t("customer_facturen.col_building")}
                  >
                    {inv.building_name ?? t("facturen.all_buildings")}
                  </td>
                  <td
                    className="muted small"
                    data-label={t("customer_facturen.col_period")}
                  >
                    {formatPeriod(inv.period_year, inv.period_month, inv.sent_at)}
                  </td>
                  <td data-label={t("customer_facturen.col_status")}>
                    <span className="cell-tag cell-tag-open">
                      <i />
                      {t("facturen.status_sent")}
                    </span>
                  </td>
                  <td
                    className="my-invoices-total"
                    style={{ textAlign: "right" }}
                    data-label={t("customer_facturen.col_total")}
                  >
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
