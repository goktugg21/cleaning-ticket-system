/**
 * FE-2 (Addendum D §D.4 + §D.5.3) — one meerwerk, as the requester
 * follows it: the phase banner, the fact block, the folded timeline,
 * and ONE primary action from the server's `actions.can_*`.
 *
 * The approval screen is §D.5.3's customer half: the price, the
 * lines, Akkoord / Afwijzen (with reason) — nothing else. Approvals
 * submit through the EXISTING endpoints (the proposal transition when
 * a sent quote exists, the request transition otherwise, the ticket
 * status change for completion approval). The spawned ticket is never
 * shown as a separate object.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Check, ChevronLeft, X } from "lucide-react";

import { api, getApiError } from "../../api/client";
import {
  getExtraWork,
  getExtraWorkTimeline,
  listProposalsForEw,
  transitionExtraWork,
  transitionProposal,
  type ExtraWorkTimelineEntry,
} from "../../api/extraWork";
import type { ExtraWorkRequestDetail, Proposal } from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import { RejectReasonDialog } from "../../components/RejectReasonDialog";
import { PhaseBanner } from "../../components/customer/PhaseBadge";
import { formatDate, formatDateTime, formatMoney } from "../../lib/intl";

export function MeerwerkDetailPage() {
  const { t } = useTranslation("common");
  const { id } = useParams<{ id: string }>();

  const [detail, setDetail] = useState<ExtraWorkRequestDetail | null>(null);
  const [timeline, setTimeline] = useState<ExtraWorkTimelineEntry[]>([]);
  const [sentProposal, setSentProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [detailData, timelineData, proposals] = await Promise.all([
        getExtraWork(id),
        getExtraWorkTimeline(id),
        listProposalsForEw(Number(id)).catch(() => [] as Proposal[]),
      ]);
      setDetail(detailData);
      setTimeline(timelineData.entries);
      setSentProposal(
        proposals.find((row) => row.status === "SENT") ?? null,
      );
      setError("");
    } catch (err) {
      setError(getApiError(err));
    }
  }, [id]);

  useEffect(() => {
    // Deferred a tick (the MyMeldingenPage pattern) so no setState can
    // run synchronously inside the effect body.
    queueMicrotask(() => {
      void load();
    });
  }, [load]);

  const phase = detail?.display_phase ?? null;
  const canDecide =
    phase === "WAITING_YOUR_APPROVAL" &&
    detail?.actions?.can_approve === true;
  const spawnedTicketId = detail?.spawned_tickets?.[0]?.id ?? null;
  const canDecideCompletion =
    phase === "WAITING_COMPLETION_APPROVAL" && spawnedTicketId !== null;

  async function decide(approve: boolean, reason?: string) {
    if (!detail || busy) return;
    setBusy(true);
    setError("");
    try {
      if (canDecide) {
        if (sentProposal) {
          await transitionProposal(detail.id, sentProposal.id, {
            to_status: approve ? "CUSTOMER_APPROVED" : "CUSTOMER_REJECTED",
            ...(reason ? { note: reason } : {}),
          });
        } else {
          await transitionExtraWork(detail.id, {
            to_status: approve ? "CUSTOMER_APPROVED" : "CUSTOMER_REJECTED",
            ...(reason ? { customer_reject_reason: reason } : {}),
          });
        }
      } else if (canDecideCompletion && spawnedTicketId !== null) {
        await api.post(`/tickets/${spawnedTicketId}/status/`, {
          to_status: approve ? "APPROVED" : "REJECTED",
          ...(reason ? { note: reason } : {}),
        });
      }
      await load();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
      setRejectOpen(false);
    }
  }

  if (!detail) {
    return (
      <div data-testid="meerwerk-detail-loading">
        {error ? (
          <div className="alert-error" role="alert">
            {error}
          </div>
        ) : (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        )}
      </div>
    );
  }

  const money =
    detail.final_total_amount ?? detail.total_amount ?? null;

  return (
    <div data-testid="meerwerk-detail-page">
      <PageHeader
        eyebrow={t("meerwerk_detail.eyebrow")}
        title={detail.title}
        subtitle={[detail.building_name, formatDate(detail.requested_at)]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <Link to="/extra-work" className="btn btn-ghost btn-sm">
            <ChevronLeft size={14} strokeWidth={2} />
            {t("meerwerk_detail.back")}
          </Link>
        }
      />

      {phase && <PhaseBanner kind="ew" phase={phase} testId="meerwerk-phase-banner" />}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      {/* §D.5.3 — the approval screen: the price, the lines, two
          buttons. Rendered only while the decision is genuinely the
          reader's (the server's can_* said so). */}
      {(canDecide || canDecideCompletion) && (
        <section
          className="card"
          style={{ padding: 18, marginBottom: 14 }}
          data-testid="meerwerk-approval"
        >
          <div className="section-head-title" style={{ marginBottom: 6 }}>
            {canDecide
              ? t("meerwerk_detail.approve_title")
              : t("meerwerk_detail.approve_completion_title")}
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {detail.line_items?.map((line) => (
              <li key={line.id} className="wp-undated-row">
                <span>
                  {line.quantity} ×{" "}
                  {line.service_name ||
                    line.custom_description ||
                    t("meerwerk_detail.line_other")}
                </span>
                <span className="muted small">
                  {line.contract_unit_price
                    ? formatMoney(line.contract_unit_price)
                    : t("meerwerk_flow.price_follows")}
                </span>
              </li>
            ))}
          </ul>
          {money !== null && (
            <p style={{ fontWeight: 600, marginTop: 10 }}>
              {t("meerwerk_detail.total", { amount: formatMoney(money) })}
            </p>
          )}
          <div style={{ display: "flex", gap: 10 }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={() => void decide(true)}
              data-testid="meerwerk-approve"
            >
              <Check size={15} strokeWidth={2} />
              {t("meerwerk_detail.approve")}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => setRejectOpen(true)}
              data-testid="meerwerk-reject"
            >
              <X size={15} strokeWidth={2} />
              {t("meerwerk_detail.reject")}
            </button>
          </div>
        </section>
      )}

      {/* The folded timeline — one story, requester words. */}
      <section
        className="card"
        style={{ padding: 18 }}
        data-testid="meerwerk-timeline"
      >
        <div className="section-head-title" style={{ marginBottom: 8 }}>
          {t("meerwerk_detail.timeline_title")}
        </div>
        <ol className="meerwerk-timeline">
          {timeline.map((entry, index) => (
            <li key={`${entry.event}-${index}`} className="meerwerk-timeline-row">
              <span className="meerwerk-timeline-when">
                {entry.at ? formatDateTime(entry.at) : "—"}
              </span>
              <span className="meerwerk-timeline-label">
                {t(`timeline.${entry.event}`)}
              </span>
              {entry.actor && (
                <span className="muted small">{entry.actor}</span>
              )}
            </li>
          ))}
        </ol>
      </section>

      <RejectReasonDialog
        open={rejectOpen}
        onCancel={() => setRejectOpen(false)}
        onConfirm={(reason) => void decide(false, reason)}
      />
    </div>
  );
}
