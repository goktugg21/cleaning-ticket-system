import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Megaphone, Ticket } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import { listTickets } from "../../../api/tickets";
import type { CustomerAdmin, TicketList } from "../../../api/types";
import { ClickableRow } from "../../../components/ClickableRow";
import { EmptyState } from "../../../components/EmptyState";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDate } from "../../../lib/intl";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * M6.1 — Customer Tickets / Meldingen tabs (provider side).
 *
 * One shared page switched by `meldingOnly`. It mirrors the customer
 * Extra Work sub-page and consumes the M6.1 ticket filters:
 *   * Tickets   → GET /api/tickets/?customer=<id>&exclude_type=REPORT
 *   * Meldingen → GET /api/tickets/?customer=<id>&type=REPORT
 * The two surfaces are deliberately disjoint (a melding is a REPORT-type
 * ticket). Scope is enforced server-side by `scope_tickets_for` BEFORE
 * the filterset narrows, so a caller without access to this customer
 * gets zero rows rather than a 403. View-first: each row links to the
 * existing `/tickets/<id>` detail page.
 */

// Ticket sub-type label keys — the canonical map lives in the create
// ticket flow (`create_ticket:type_*`); reuse those exact keys here so
// the labels stay in lockstep rather than printing the raw enum.
type TicketTypeValue =
  | "REPORT"
  | "COMPLAINT"
  | "REQUEST"
  | "SUGGESTION"
  | "QUOTE_REQUEST";

const TICKET_TYPE_KEYS: Record<TicketTypeValue, string> = {
  REPORT: "type_report",
  COMPLAINT: "type_complaint",
  REQUEST: "type_request",
  SUGGESTION: "type_suggestion",
  QUOTE_REQUEST: "type_quote_request",
};

export function CustomerTicketsPage({
  meldingOnly = false,
}: {
  meldingOnly?: boolean;
}) {
  const { id } = useParams();
  const { t } = useTranslation(["common", "create_ticket"]);

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  // i18n + testid variant key.
  const v = meldingOnly ? "meldingen" : "tickets";

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [rows, setRows] = useState<TicketList[]>([]);
  // Starts true so the initial render shows the loading bar without a
  // synchronous setState in the effect body (keeps the page clear of
  // react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) {
          setError(t("bm_customer_detail.invalid_id"));
          setLoading(false);
        }
      });
      return () => {
        cancelled = true;
      };
    }
    // Two parallel fetches: the customer (header name + active pill) and
    // the scoped ticket list. The list is filtered server-side; the
    // scope-respecting queryset runs before the filter so an
    // out-of-scope caller gets zero rows rather than a 403.
    Promise.all([
      getCustomer(numericId),
      listTickets({
        customer: numericId,
        ...(meldingOnly ? { type: "REPORT" } : { exclude_type: "REPORT" }),
      }),
    ])
      .then(([customerData, ticketResponse]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setRows(ticketResponse.results ?? []);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, meldingOnly, t]);

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

  return (
    <div data-testid={`customer-${v}-page`}>
      <CustomerSubPageHeader customerName={customerName} isActive={isActive} />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : customer ? (
        <>
          <p className="section-explainer" data-testid={`customer-${v}-explainer`}>
            {t(`customer_view.${v}.explainer`, { customer: customerName })}
          </p>

          {rows.length === 0 ? (
            <EmptyState
              icon={meldingOnly ? Megaphone : Ticket}
              title={t(`customer_view.${v}.empty_title`)}
              description={t(`customer_view.${v}.empty_desc`)}
              testId={`customer-${v}-empty`}
            />
          ) : (
            <section
              className="card"
              data-testid={`customer-${v}-section`}
              style={{ padding: "20px 22px", overflow: "hidden" }}
            >
              <div className="section-head" style={{ marginBottom: 12 }}>
                <div>
                  <div className="section-head-title">
                    {t(`customer_view.${v}.list_title`)}
                  </div>
                  <div className="section-head-sub">
                    {t(`customer_view.${v}.list_subtitle`, {
                      count: rows.length,
                    })}
                  </div>
                </div>
              </div>

              <div className="table-wrap">
                <table className="data-table" data-testid={`customer-${v}-table`}>
                  <thead>
                    <tr>
                      <th>{t("customer_view.ticket_table.col_subject")}</th>
                      <th>{t("customer_view.ticket_table.col_type")}</th>
                      <th>{t("customer_view.ticket_table.col_status")}</th>
                      <th>{t("customer_view.ticket_table.col_building")}</th>
                      <th>{t("customer_view.ticket_table.col_created")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <ClickableRow
                        key={row.id}
                        to={`/tickets/${row.id}`}
                        testId={`customer-${v}-row`}
                      >
                        <td className="td-subject">
                          <Link to={`/tickets/${row.id}`}>{row.title}</Link>
                        </td>
                        <td>
                          {TICKET_TYPE_KEYS[row.type as TicketTypeValue]
                            ? t(
                                `create_ticket:${TICKET_TYPE_KEYS[row.type as TicketTypeValue]}`,
                              )
                            : row.type}
                        </td>
                        <td>
                          <StatusBadge
                            status={{ kind: "ticket", value: row.status }}
                          />
                        </td>
                        <td>{row.building_name}</td>
                        <td>{formatDate(row.created_at)}</td>
                      </ClickableRow>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
