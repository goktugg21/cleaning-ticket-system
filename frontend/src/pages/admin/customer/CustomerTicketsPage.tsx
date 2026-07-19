import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Megaphone, Ticket } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import { listAllTickets } from "../../../api/tickets";
import type { CustomerAdmin, TicketList } from "../../../api/types";
import { ClickableRow } from "../../../components/ClickableRow";
import { EmptyState } from "../../../components/EmptyState";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDate } from "../../../lib/intl";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * M6.1 / IA 2026-06-25 — the customer Tickets tab, now the SINGLE
 * ticket-content surface for a customer (the separate Meldingen tab
 * merged into it — they were one model sliced two ways). A filter-chip
 * strip narrows the same list:
 *   * Alle      → GET /api/tickets/?customer=<id>
 *   * Tickets   → GET /api/tickets/?customer=<id>&exclude_type=REPORT
 *   * Meldingen → GET /api/tickets/?customer=<id>&type=REPORT
 * The chip state lives in the `?filter=` search param so the retired
 * /meldingen route can redirect here with the chip pre-applied and deep
 * links stay shareable. Scope is enforced server-side by
 * `scope_tickets_for` BEFORE the filterset narrows, so a caller without
 * access to this customer gets zero rows rather than a 403. View-first:
 * each row links to the existing `/tickets/<id>` detail page.
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

type TicketChip = "all" | "tickets" | "meldingen";

export function CustomerTicketsPage() {
  const { id } = useParams();
  const { t } = useTranslation(["common", "create_ticket"]);
  const [searchParams, setSearchParams] = useSearchParams();

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  // Chip state rides in ?filter= so the retired /meldingen route (and
  // any old bookmark) can land here with the chip pre-applied.
  const raw = searchParams.get("filter");
  const chip: TicketChip =
    raw === "meldingen" || raw === "tickets" ? raw : "all";
  const setChip = (next: TicketChip) => {
    setSearchParams(next === "all" ? {} : { filter: next }, { replace: true });
  };

  // i18n variant key: the "Alle" view reuses the tickets copy (the chips
  // themselves communicate the narrowing); Meldingen keeps its own.
  const v = chip === "meldingen" ? "meldingen" : "tickets";

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
      listAllTickets({
        customer: numericId,
        ...(chip === "meldingen"
          ? { type: "REPORT" }
          : chip === "tickets"
            ? { exclude_type: "REPORT" }
            : {}),
      }),
    ])
      .then(([customerData, ticketRows]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setRows(ticketRows ?? []);
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
  }, [numericId, chip, t]);

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

  return (
    <div data-testid="customer-tickets-page">
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

          {/* IA — the merged filter strip (Alle / Tickets / Meldingen). */}
          <div
            className="work-strip-toggle"
            style={{ marginBottom: 14 }}
            data-testid="customer-tickets-chips"
          >
            {(["all", "tickets", "meldingen"] as TicketChip[]).map((c) => (
              <button
                key={c}
                type="button"
                className="btn btn-secondary btn-sm"
                aria-pressed={chip === c}
                onClick={() => setChip(c)}
                data-testid={`customer-tickets-chip-${c}`}
              >
                {t(`customer_view.chip_${c}`)}
              </button>
            ))}
          </div>

          {rows.length === 0 ? (
            <EmptyState
              icon={chip === "meldingen" ? Megaphone : Ticket}
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
