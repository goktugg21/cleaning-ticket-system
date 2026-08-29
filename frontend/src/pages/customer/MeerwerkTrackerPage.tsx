/**
 * FE-2 (Addendum D §D.4) — the customer's meerwerk TRACKER.
 *
 * One object per request, grouped by the server's `display_phase`.
 * The groups that ask something of the reader come first; history
 * sinks to the bottom. The spawned ticket never appears as a separate
 * item — its milestones live inside each request's own timeline.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PlusCircle } from "lucide-react";

import { getApiError } from "../../api/client";
import { listAllExtraWork } from "../../api/extraWork";
import type {
  ExtraWorkDisplayPhase,
  ExtraWorkRequestList,
} from "../../api/types";
import { BoundedList } from "../../components/BoundedList";
import { PageHeader } from "../../components/PageHeader";
import { PhaseBadge } from "../../components/customer/PhaseBadge";
import { formatDate } from "../../lib/intl";

/** Render order: action first, then motion, then history. */
const PHASE_ORDER: ExtraWorkDisplayPhase[] = [
  "WAITING_YOUR_APPROVAL",
  "WAITING_COMPLETION_APPROVAL",
  "WAITING_PRICE",
  "SCHEDULED",
  "IN_EXECUTION",
  "DONE",
  "INVOICED",
  "REJECTED",
  "CANCELLED",
  // Provider-side wording never reaches a customer read, but the type
  // admits it, so the tracker files it with the other wait.
  "WAITING_CUSTOMER_APPROVAL",
];

export function MeerwerkTrackerPage() {
  const { t } = useTranslation("common");
  const [rows, setRows] = useState<ExtraWorkRequestList[] | null>(null);
  const [error, setError] = useState("");
  /** FE-4 (Addendum D §D.12 item 6) — one chip per phase present, plus
   *  "Alles"; the groups below narrow to the chosen phase. */
  const [phaseFilter, setPhaseFilter] = useState<ExtraWorkDisplayPhase | "">("");

  useEffect(() => {
    let cancelled = false;
    listAllExtraWork()
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const allGroups =
    rows === null
      ? []
      : PHASE_ORDER.map((phase) => ({
          phase,
          items: rows.filter((row) => row.display_phase === phase),
        })).filter((group) => group.items.length > 0);
  const groups = allGroups.filter(
    (group) => phaseFilter === "" || group.phase === phaseFilter,
  );

  return (
    <div data-testid="meerwerk-tracker-page">
      <PageHeader
        eyebrow={t("meerwerk_tracker.eyebrow")}
        title={t("meerwerk_tracker.title")}
        subtitle={t("meerwerk_tracker.subtitle")}
        actions={
          <Link
            to="/extra-work/new"
            className="btn btn-primary"
            data-testid="meerwerk-tracker-new"
          >
            <PlusCircle size={15} strokeWidth={2} />
            {t("meerwerk_tracker.new")}
          </Link>
        }
      />

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {rows === null ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : rows.length === 0 ? (
        <section className="card" style={{ padding: 20 }}>
          <p className="muted" data-testid="meerwerk-tracker-empty">
            {t("meerwerk_tracker.empty")}
          </p>
        </section>
      ) : (
        <>
        <div className="wp-strip" data-testid="meerwerk-tracker-chips" style={{ marginBottom: 14 }}>
          <button
            type="button"
            className={`status-tile${phaseFilter === "" ? " status-tile-active" : ""}`}
            aria-pressed={phaseFilter === ""}
            onClick={() => setPhaseFilter("")}
            data-testid="meerwerk-tracker-chip-all"
          >
            <span className="status-tile-label">{t("meerwerk_tracker.filter_all")}</span>
            <span className="status-tile-count">{rows.length}</span>
          </button>
          {allGroups.map((group) => (
            <button
              key={group.phase}
              type="button"
              className={`status-tile${phaseFilter === group.phase ? " status-tile-active" : ""}`}
              aria-pressed={phaseFilter === group.phase}
              onClick={() =>
                setPhaseFilter(phaseFilter === group.phase ? "" : group.phase)
              }
              data-testid={`meerwerk-tracker-chip-${group.phase}`}
            >
              <span className="status-tile-label">{t(`phase.ew.${group.phase}`)}</span>
              <span className="status-tile-count">{group.items.length}</span>
            </button>
          ))}
        </div>
        {groups.map((group) => (
          <section
            key={group.phase}
            className="card"
            style={{ padding: 18, marginBottom: 14 }}
            data-testid={`meerwerk-group-${group.phase}`}
          >
            <div
              className="section-head-title"
              style={{ marginBottom: 8, display: "flex", gap: 10 }}
            >
              <PhaseBadge kind="ew" phase={group.phase} customer />
              <span className="muted small" style={{ alignSelf: "center" }}>
                {t("meerwerk_tracker.group_count", {
                  count: group.items.length,
                })}
              </span>
            </div>
            <BoundedList
              size="md"
              count={group.items.length}
              ariaLabel={t(`phase.ew.${group.phase}`)}
              testIdPrefix={`meerwerk-group-${group.phase}`}
            >
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {group.items.map((row) => (
                  <li key={row.id} className="wp-undated-row">
                    <div className="wp-undated-row-main">
                      <Link
                        to={`/extra-work/${row.id}`}
                        data-testid={`meerwerk-row-${row.id}`}
                      >
                        {row.title}
                      </Link>
                      <span className="muted small">
                        {[
                          row.building_name,
                          t("meerwerk_tracker.requested_on", {
                            date: formatDate(row.requested_at),
                          }),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </BoundedList>
          </section>
        ))}
        </>
      )}
    </div>
  );
}
