// Sprint 32 — shared, read-only unified audit-timeline renderer.
//
// Renders the five `source` row shapes from
// GET /api/audit/tickets/<id>/timeline/ in the app's existing `.timeline`
// visual language. Used by BOTH the ticket-detail activity card (for
// provider-audit roles) and the audit-log page's per-ticket lookup panel.
//
// The status_history rows are rendered byte-for-byte like the legacy
// TicketDetailPage block (same `.timeline-row` / `.timeline-dot` /
// `.timeline-time` / `.timeline-text` markup, the same i18n keys, and the
// same `data-testid="timeline-override-badge"`), so the ticket-detail e2e
// keeps passing. Free text (status note + override reason + EW note) is run
// through `sanitizeStatusNote` so the demo seed marker never leaks. Enum-
// shaped values render through humanizers / StatusBadge / i18n — never raw —
// so the no-raw-enums audit holds even inside the lookup panel.
import { Fragment } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  AuditSeverity,
  TicketTimelineRow,
  TimelineAuditLogRow,
  TimelineExtraWorkLinkRow,
  TimelineExtraWorkStatusHistoryRow,
  TimelinePlannedOccurrenceLinkRow,
  TimelineStatusHistoryRow,
} from "../api/types";
import { formatDate } from "../lib/intl";
import { prettyEnum } from "../lib/enumLabels";
import { ChangeDiff } from "./ChangeDiff";
import { StatusBadge } from "./StatusBadge";

type TimelineColor = "green" | "red" | "amber" | "muted";

// Mirror of TicketDetailPage.humanName — email local-part, title-cased.
function humanName(email: string | null | undefined, fallback: string): string {
  if (!email) return fallback;
  const local = email.split("@")[0];
  return local
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Mirror of TicketDetailPage.sanitizeStatusNote — strip the canonical demo
// seed marker so it never reaches a rendered surface. Applied to status
// notes AND override reasons (the seed walk stamps both).
function sanitizeFreeText(raw: string | null | undefined): string {
  if (!raw) return "";
  const trimmed = raw.trim();
  if (!trimmed) return "";
  if (/^seed_demo_data\b/i.test(trimmed)) return "";
  if (/seed_demo_data\s*→/i.test(trimmed)) return "";
  return trimmed;
}

// HIGH-severity red-flag badge; NORMAL renders nothing (quiet). Mirrors the
// StatusBadge tone language so the audit feed reads consistently. The label
// is always i18n (never the raw "HIGH" enum) so the no-raw-enums audit holds.
export function SeverityBadge({ severity }: { severity: AuditSeverity }) {
  const { t } = useTranslation("common");
  if (severity !== "HIGH") return null;
  return (
    <StatusBadge
      status={{
        kind: "generic",
        tone: "rejected",
        label: t("audit_logs.severity_high"),
      }}
      variant="cell"
    />
  );
}

interface RowShellProps {
  color: TimelineColor;
  timestamp: string | null;
  testId?: string;
  children: ReactNode;
}

function TimelineRow({ color, timestamp, testId, children }: RowShellProps) {
  return (
    <div className="timeline-row" data-color={color} data-testid={testId}>
      <div className="timeline-dot" />
      <div>
        <div className="timeline-time">
          {timestamp ? formatDate(timestamp) : "—"}
        </div>
        {children}
      </div>
    </div>
  );
}

export function UnifiedTimeline({ rows }: { rows: TicketTimelineRow[] }) {
  const { t } = useTranslation(["ticket_detail", "common"]);

  const tStatus = (status: string | null): string => {
    if (!status) return t("status_default_created");
    return t(`common:status.${status.toLowerCase()}`);
  };
  const unassigned = t("unassigned");

  function renderStatusHistory(row: TimelineStatusHistoryRow, first: boolean) {
    const color: TimelineColor = !row.old_status
      ? "green"
      : row.new_status === "REJECTED"
        ? "red"
        : row.new_status === "WAITING_CUSTOMER_APPROVAL"
          ? "amber"
          : first
            ? "green"
            : "muted";
    const cleanedNote = sanitizeFreeText(row.note);
    const cleanedReason = sanitizeFreeText(row.override_reason);
    return (
      <TimelineRow color={color} timestamp={row.timestamp}>
        <div className="timeline-text">
          <b>{humanName(row.changed_by_email, unassigned)}</b>
          {row.old_status ? (
            <>
              {t("timeline_status_changed_from_to")}
              <span
                className={`pill ${row.old_status === "OPEN" ? "open" : "progress"}`}
              >
                {tStatus(row.old_status)}
              </span>
              {t("timeline_status_to")}
              <span className="pill progress">{tStatus(row.new_status)}</span>
            </>
          ) : (
            <>
              {t("timeline_created_as")}
              <span className="pill progress">{tStatus(row.new_status)}</span>
            </>
          )}
          {cleanedNote ? `. ${cleanedNote}` : "."}
        </div>
        {row.is_override && (
          <div
            className="muted small"
            data-testid="timeline-override-badge"
            style={{ marginTop: 4 }}
          >
            <b>{t("timeline_override_badge")}</b>
            {cleanedReason
              ? ` · ${t("timeline_override_reason", { reason: cleanedReason })}`
              : ""}
          </div>
        )}
      </TimelineRow>
    );
  }

  function renderAuditLog(row: TimelineAuditLogRow) {
    const actionLabel = t(`common:audit_logs.action_${row.action.toLowerCase()}`);
    const cleanedReason = sanitizeFreeText(row.reason);
    return (
      <TimelineRow color="muted" timestamp={row.timestamp}>
        <div className="timeline-text">
          <b>{humanName(row.actor_email, t("common:audit_logs.system_actor"))}</b>{" "}
          {t("timeline_audit_event", {
            action: actionLabel,
            target: prettyEnum(row.target_model.split(".").pop() ?? row.target_model),
          })}
          <SeverityBadge severity={row.severity} />
          {cleanedReason ? `. ${cleanedReason}` : ""}
        </div>
        <div style={{ marginTop: 6 }}>
          <ChangeDiff changes={row.changes} />
        </div>
      </TimelineRow>
    );
  }

  function renderExtraWorkLink(row: TimelineExtraWorkLinkRow) {
    return (
      <TimelineRow color="muted" timestamp={row.timestamp}>
        <div className="timeline-text">
          {t("timeline_ew_reference", {
            id: row.extra_work_id,
            relation: t(`timeline_ew_relation_${row.relation}`),
          })}{" "}
          <StatusBadge
            status={{ kind: "extra-work", value: row.extra_work_status }}
            variant="cell"
          />
        </div>
      </TimelineRow>
    );
  }

  function renderExtraWorkStatus(row: TimelineExtraWorkStatusHistoryRow) {
    const cleanedNote = sanitizeFreeText(row.note);
    return (
      <TimelineRow color="muted" timestamp={row.timestamp}>
        <div className="timeline-text">
          <b>{humanName(row.changed_by_email, unassigned)}</b>{" "}
          {t("timeline_ew_status_change", { id: row.extra_work_id })}{" "}
          <StatusBadge
            status={{ kind: "extra-work", value: row.old_status }}
            variant="cell"
          />
          {" → "}
          <StatusBadge
            status={{ kind: "extra-work", value: row.new_status }}
            variant="cell"
          />
          {cleanedNote ? `. ${cleanedNote}` : ""}
          {row.is_override && (
            <span className="muted small" style={{ marginLeft: 6 }}>
              · {t("timeline_override_badge")}
            </span>
          )}
        </div>
      </TimelineRow>
    );
  }

  function renderOccurrence(row: TimelinePlannedOccurrenceLinkRow) {
    return (
      <TimelineRow color="muted" timestamp={row.timestamp}>
        <div className="timeline-text">
          {t("timeline_occurrence_reference", {
            id: row.occurrence_id,
            date: row.planned_date ? formatDate(row.planned_date) : "—",
          })}{" "}
          <span className="pill progress">{prettyEnum(row.status)}</span>
        </div>
      </TimelineRow>
    );
  }

  return (
    <>
      {rows.map((row, index) => {
        const key = `${row.source}-${index}-${row.timestamp ?? ""}`;
        // Wrap in a keyed Fragment (not a div) so each `.timeline-row`
        // stays a DIRECT child of the `.timeline` container — the
        // connector-line CSS depends on that.
        return (
          <Fragment key={key}>
            {row.source === "status_history"
              ? renderStatusHistory(row, index === 0)
              : row.source === "audit_log"
                ? renderAuditLog(row)
                : row.source === "extra_work_link"
                  ? renderExtraWorkLink(row)
                  : row.source === "extra_work_status_history"
                    ? renderExtraWorkStatus(row)
                    : row.source === "planned_occurrence_link"
                      ? renderOccurrence(row)
                      : null}
          </Fragment>
        );
      })}
    </>
  );
}
