/**
 * FE-2 (Addendum D §D.3.1) — the customer START page.
 *
 * "My open items" and nothing else: my meldingen still in motion, the
 * meerwerk that waits on MY decision (a price to approve, finished
 * work to check), and unread messages. No provider KPIs, no triage
 * queues, no console vocabulary — and no keys shared with the provider
 * dashboard (`start.*` is this page's own bundle prefix).
 *
 * One primary action: Melding maken.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessagesSquare, PlusCircle } from "lucide-react";

import { getInboxUnreadCount } from "../../api/inbox";
import { listAllExtraWork } from "../../api/extraWork";
import { listAllTickets } from "../../api/tickets";
import type { ExtraWorkRequestList, TicketList } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { BoundedList } from "../../components/BoundedList";
import { PageHeader } from "../../components/PageHeader";
import { PhaseBadge } from "../../components/customer/PhaseBadge";
import { formatDate } from "../../lib/intl";

/** Meldingen the customer is still waiting on. The server computes the
 *  phase; this only picks which phases count as "in motion". */
const OPEN_TICKET_PHASES = new Set([
  "RECEIVED",
  "PLANNED",
  "IN_EXECUTION",
  "WAITING_YOUR_APPROVAL",
]);

/** Meerwerk phases that wait on the CUSTOMER's own decision. */
const DECISION_PHASES = new Set([
  "WAITING_YOUR_APPROVAL",
  "WAITING_COMPLETION_APPROVAL",
]);

export function StartPage() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const customerId = me?.customer_ids?.[0] ?? null;

  const [meldingen, setMeldingen] = useState<TicketList[] | null>(null);
  const [decisions, setDecisions] = useState<ExtraWorkRequestList[] | null>(
    null,
  );
  const [unread, setUnread] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [ticketRows, ewRows, unreadCount] = await Promise.all([
          customerId !== null
            ? listAllTickets({ type: "REPORT", customer: customerId })
            : Promise.resolve([]),
          listAllExtraWork(),
          getInboxUnreadCount(),
        ]);
        if (cancelled) return;
        setMeldingen(
          ticketRows.filter((row) => OPEN_TICKET_PHASES.has(row.display_phase)),
        );
        setDecisions(
          ewRows.filter((row) => DECISION_PHASES.has(row.display_phase)),
        );
        setUnread(unreadCount);
        setError("");
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  return (
    <div data-testid="customer-start-page">
      <PageHeader
        eyebrow={t("start.eyebrow")}
        title={t("start.title")}
        subtitle={t("start.subtitle")}
        actions={
          <Link
            to="/tickets/new"
            className="btn btn-primary"
            data-testid="start-new-melding"
          >
            <PlusCircle size={15} strokeWidth={2} />
            {t("start.new_melding")}
          </Link>
        }
      />

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Waits on YOU — the one list that asks for something. */}
      <section className="card" style={{ padding: 18, marginBottom: 16 }}>
        <div className="section-head-title" style={{ marginBottom: 4 }}>
          {t("start.decisions_title")}
        </div>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("start.decisions_sub")}
        </p>
        {decisions === null ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : decisions.length === 0 ? (
          <p className="muted small" data-testid="start-decisions-empty">
            {t("start.decisions_empty")}
          </p>
        ) : (
          <BoundedList
            size="md"
            count={decisions.length}
            ariaLabel={t("start.decisions_title")}
            testIdPrefix="start-decisions"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {decisions.map((row) => (
                <li key={row.id} className="wp-undated-row">
                  <div className="wp-undated-row-main">
                    <Link to={`/extra-work/${row.id}`}>{row.title}</Link>
                    <span className="muted small">
                      {[row.building_name, formatDate(row.requested_at)]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                  <PhaseBadge kind="ew" phase={row.display_phase} customer />
                </li>
              ))}
            </ul>
          </BoundedList>
        )}
      </section>

      {/* My meldingen in motion. */}
      <section className="card" style={{ padding: 18, marginBottom: 16 }}>
        <div className="section-head-title" style={{ marginBottom: 4 }}>
          {t("start.meldingen_title")}
        </div>
        {meldingen === null ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : meldingen.length === 0 ? (
          <p className="muted small" data-testid="start-meldingen-empty">
            {t("start.meldingen_empty")}
          </p>
        ) : (
          <BoundedList
            size="md"
            count={meldingen.length}
            ariaLabel={t("start.meldingen_title")}
            testIdPrefix="start-meldingen"
          >
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {meldingen.map((row) => (
                <li key={row.id} className="wp-undated-row">
                  <div className="wp-undated-row-main">
                    <Link to={`/tickets/${row.id}`}>{row.title}</Link>
                    <span className="muted small">
                      {[row.building_name, formatDate(row.created_at)]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                  <PhaseBadge kind="ticket" phase={row.display_phase} />
                </li>
              ))}
            </ul>
          </BoundedList>
        )}
        <p className="small" style={{ marginBottom: 0 }}>
          <Link to="/my/meldingen">{t("start.meldingen_all")}</Link>
        </p>
      </section>

      {/* Unread messages — a pointer, not a feed. */}
      <section className="card" style={{ padding: 18 }}>
        <Link
          to="/inbox"
          className="attn-row"
          data-testid="start-unread-messages"
          style={{ display: "flex", alignItems: "center", gap: 10 }}
        >
          <MessagesSquare size={16} strokeWidth={2} />
          <span className="attn-row-label">{t("start.unread_title")}</span>
          <span className="attn-count">{unread ?? "—"}</span>
        </Link>
      </section>
    </div>
  );
}
