import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Megaphone } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import { listAllTickets } from "../api/tickets";
import type { TicketList } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { BillingCutoffNotice } from "../components/BillingCutoffNotice";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { ExtraWorkOriginPill } from "../components/ExtraWorkOriginPill";
import { PageHeader } from "../components/PageHeader";
import { PhaseBadge } from "../components/customer/PhaseBadge";
import { formatDate } from "../lib/intl";

/**
 * M7.3 — Customer-facing "Mijn meldingen" page.
 *
 * Route `/my/meldingen` (wrapped in `ProtectedRoute`). Lists the
 * signed-in customer's meldingen (REPORT-type tickets). The page derives
 * the caller's own customer via `me.customer_ids[0]` and scopes the fetch
 * to it (mirroring MyEmployeesPage). A caller without customer scope — e.g.
 * a provider-side actor (COMPANY_ADMIN / BUILDING_MANAGER) who opens the
 * URL directly — gets a "no customer" empty state instead of a provider-
 * scoped ticket list. Server-side `scope_tickets_for` narrows the result as
 * a second layer. Every row is a melding, so there is intentionally no
 * "type" column. View-first: each row links to the existing `/tickets/<id>`
 * detail page. Mirrors the MyEmployeesPage chrome and the CustomerTicketsPage
 * table.
 */
export function MyMeldingenPage() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const customerId = me?.customer_ids?.[0] ?? null;
  const [rows, setRows] = useState<TicketList[]>([]);
  // Starts true so the initial render shows the loading bar without a
  // synchronous setState in the effect body (keeps the page clear of
  // react-hooks/set-state-in-effect).
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (customerId === null) {
      // No customer scope (provider-side actor): the no-customer empty
      // state renders below. Resolve loading without a synchronous
      // setState in the effect body.
      queueMicrotask(() => setLoading(false));
      return;
    }
    let cancelled = false;
    listAllTickets({ type: "REPORT", customer: customerId })
      .then((data) => {
        if (!cancelled) setRows(data ?? []);
      })
      .catch((e) => {
        if (!cancelled) setError(getApiError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  return (
    <div data-testid="my-meldingen-page">
      <PageHeader
        title={t("my_meldingen.title")}
        subtitle={t("my_meldingen.subtitle")}
      />

      {customerId === null ? (
        <EmptyState
          icon={Megaphone}
          title={t("my_meldingen.empty_no_customer_title")}
          description={t("my_meldingen.empty_no_customer_desc")}
          testId="my-meldingen-no-customer"
        />
      ) : (
        <>
          {error && (
            <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
              {error}
            </div>
          )}

          {loading ? (
            <div className="loading-bar">
              <div className="loading-bar-fill" />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={Megaphone}
              title={t("my_meldingen.empty_title")}
              description={t("my_meldingen.empty_desc")}
              testId="my-meldingen-empty"
            />
          ) : (
            <>
              {/* Sprint W1-B item 14 — the customer meets the cutoff rule
                  HERE, on the list they click through to approve from,
                  not on a settings page and not for the first time on an
                  invoice. Rendered only when there is work to approve:
                  a rule about work is noise on an empty page. */}
              <BillingCutoffNotice />
              <section
                className="card"
                data-testid="my-meldingen-section"
                style={{ padding: "20px 22px", overflow: "hidden" }}
              >
                <div className="section-head" style={{ marginBottom: 12 }}>
                  <div>
                    <div className="section-head-title">
                      {t("my_meldingen.list_title")}
                    </div>
                    <div className="section-head-sub">
                      {t("my_meldingen.list_subtitle", { count: rows.length })}
                    </div>
                  </div>
                </div>

                <div className="table-wrap">
                  <table
                    className="data-table table-cards"
                    data-testid="my-meldingen-table"
                  >
                    <thead>
                      <tr>
                        <th>{t("customer_view.ticket_table.col_subject")}</th>
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
                          testId="my-meldingen-row"
                        >
                          <td className="td-subject">
                            <Link to={`/tickets/${row.id}`}>{row.title}</Link>
                            {/* Sprint 180 §3 — a melding that grew into
                                paid extra work says so here too. The
                                customer is the one person who most needs
                                to know a row became chargeable work, and
                                the link goes to the request they can read
                                the price on. */}
                            {row.extra_work_origin && (
                              <ExtraWorkOriginPill
                                ewId={
                                  row.extra_work_origin.extra_work_request_id
                                }
                                testId="my-meldingen-row-extra-work-origin"
                                style={{ marginLeft: 8 }}
                              />
                            )}
                          </td>
                          <td data-label={t("customer_view.ticket_table.col_status")}>
                            {/* FE-2 (§D.4) — the customer reads the
                                server-computed PHASE, not the workflow
                                status enum. */}
                            <PhaseBadge
                              kind="ticket"
                              phase={row.display_phase}
                              testId="my-meldingen-phase"
                            />
                          </td>
                          <td data-label={t("customer_view.ticket_table.col_building")}>
                            {row.building_name}
                          </td>
                          <td data-label={t("customer_view.ticket_table.col_created")}>
                            {formatDate(row.created_at)}
                          </td>
                        </ClickableRow>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
