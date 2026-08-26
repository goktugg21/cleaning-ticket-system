import { useState } from "react";
import { AlarmClock, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { Role } from "../../api/types";
import type { WorkPlanEntry } from "../../api/workPlan";
import { detailPath, formatDay } from "./entryHelpers";
import { LATE_LEVEL_CLASS, latenessOf, sortLate } from "./lateness";
import type { LateFacts } from "./lateness";
import { PartChips } from "./PartChips";

/**
 * W-LATE §1a — the late strip.
 *
 * Full-width ABOVE the week grid, and it WRAPS: every late job is a card,
 * the cards flow left to right and then down, and nothing on this page
 * scrolls sideways. The grid below keeps its own dimensions; this strip
 * borrows nothing from it and lends nothing to it.
 *
 * THE LAW OF THE WAVE. A job not done keeps its planned date. It is in
 * this strip today because it is unfinished, not because anything moved,
 * and it will be here tomorrow for the same reason with one more day on
 * its badge. The badge therefore prints the PLANNED date and how far past
 * it we are — never a date the system invented.
 *
 * ORDER. Left to right, ascending severity: orange (the plan is broken),
 * red (the promise is broken), bordeaux (thirty days and not one hour).
 * Within a rung, the least late first, so the whole strip reads
 * monotonically worse as the eye travels right. The server sorts the
 * list the same way; `sortLate` re-applies the same key so a list the
 * page assembled itself comes out identically.
 *
 * THE WORST NEVER HIDES. The strip shows its first rows and offers
 * "+N more" for the rest — a cap without an expander would hide exactly
 * the bordeaux cards that sort last. When the SERVER stopped at its
 * bound, the notice says so, in the same words the week uses.
 */

/** How many cards render before the expander. Twelve is three rows of
 *  four at 1366 (content 1110px / ~262px per card), which is enough to
 *  see the strip's shape and its colours before deciding to open it. */
const SHOWN_DEFAULT = 12;

export function LateStrip({
  entries,
  truncated,
  limit,
  role,
}: {
  entries: WorkPlanEntry[];
  truncated: boolean;
  limit: number;
  role: Role | null;
}) {
  const { t } = useTranslation("staff_slots");
  const [expanded, setExpanded] = useState(false);
  const sorted = sortLate(entries);
  if (sorted.length === 0) return null;
  const shown = expanded ? sorted : sorted.slice(0, SHOWN_DEFAULT);
  const hidden = sorted.length - shown.length;

  return (
    <section
      className="wp-late"
      data-testid="agenda-late-strip"
      aria-label={t("late.strip_title")}
    >
      <div className="wp-late-head">
        <span className="section-head-title wp-late-title">
          <AlarmClock size={15} strokeWidth={2.4} aria-hidden="true" />
          {t("late.strip_title")}
          <span className="wp-late-count" data-testid="agenda-late-count">
            {t("late.count", { count: sorted.length })}
          </span>
        </span>
        <span className="muted small">{t("late.strip_desc")}</span>
      </div>
      <ul className="wp-late-cards" data-testid="agenda-late-cards">
        {shown.map((entry) => (
          <LateCard key={entry.key} entry={entry} role={role} />
        ))}
      </ul>
      {(hidden > 0 || expanded) && (
        <button
          type="button"
          className="btn btn-ghost btn-sm wp-late-more"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          data-testid="agenda-late-more"
        >
          {expanded ? t("late.less") : t("late.more", { count: hidden })}
        </button>
      )}
      {truncated && (
        <p className="wp-notice" role="status" data-testid="agenda-late-truncated">
          {t("agenda.truncated_note", { count: limit })}
        </p>
      )}
    </section>
  );
}

/**
 * The badge every late surface prints — the strip card, the week card,
 * the day modal's late half. One function so "Gepland 25 aug — 1 dag te
 * laat" is spelled once.
 */
export function LateBadge({
  facts,
  testId = "agenda-late-badge",
}: {
  facts: LateFacts;
  testId?: string;
}) {
  const { t } = useTranslation("staff_slots");
  const lines: string[] = [];
  if (facts.plannedDate && facts.plannedDaysLate !== null) {
    lines.push(
      t("late.badge_planned", {
        date: formatDay(facts.plannedDate),
        count: facts.plannedDaysLate,
      }),
    );
  } else if (facts.plannedDate) {
    lines.push(t("late.q_planned", { date: formatDay(facts.plannedDate) }));
  } else {
    lines.push(t("late.badge_undated"));
  }
  if (facts.deadline && facts.deadlineDaysLate !== null) {
    lines.push(
      t("late.badge_deadline", {
        date: formatDay(facts.deadline),
        count: facts.deadlineDaysLate,
      }),
    );
  }
  if (facts.level === 3 && facts.anchorDays !== null) {
    lines.push(t("late.badge_quarantine", { count: facts.anchorDays }));
  }
  return (
    <span
      className={`wp-late-badge wp-late-badge-l${facts.level}`}
      data-testid={testId}
      data-level={facts.level}
      title={t(`late.level_${facts.level}`)}
    >
      {lines.map((line, index) => (
        <span key={index} className="wp-late-badge-line">
          {line}
        </span>
      ))}
    </span>
  );
}

function LateCard({
  entry,
  role,
}: {
  entry: WorkPlanEntry;
  role: Role | null;
}) {
  const { t } = useTranslation("staff_slots");
  const facts = latenessOf(entry);
  if (!facts) return null;
  const to = detailPath(entry, role);
  const isExtraWork = entry.kind === "EXTRA_WORK";
  const heading = (
    <>
      {entry.ticket_no ? `${entry.ticket_no} · ` : ""}
      {entry.title}
    </>
  );
  const where = [entry.building_name, entry.customer_name]
    .filter(Boolean)
    .join(" · ");
  const crew =
    entry.assignee_names.length > 0
      ? entry.assignee_names.join(", ") +
        (entry.assignee_count > entry.assignee_names.length
          ? ` +${entry.assignee_count - entry.assignee_names.length}`
          : "")
      : t("late.crew_none");

  return (
    <li
      className={`wp-late-card ${LATE_LEVEL_CLASS[facts.level]}`}
      data-testid="agenda-late-card"
      data-level={facts.level}
      data-kind={entry.kind}
      data-job={entry.ticket_id !== null ? `ticket-${entry.ticket_id}` : entry.key}
    >
      <span className="wp-late-card-kind">
        {isExtraWork ? t("agenda.source_extra_work") : t("agenda.source_ticket")}
        <span className="wp-late-card-level">{t(`late.level_${facts.level}`)}</span>
      </span>
      {to ? (
        <Link to={to} className="wp-card-title">
          {heading}
        </Link>
      ) : (
        <span className="wp-card-title">{heading}</span>
      )}
      {where && <span className="wp-card-where">{where}</span>}
      <span className="wp-late-card-crew" data-testid="agenda-late-card-crew">
        <Users size={11} strokeWidth={2} aria-hidden="true" />
        {crew}
      </span>
      {entry.parts.length > 0 && (
        <PartChips parts={entry.parts} testId="agenda-late-card-part" />
      )}
      <LateBadge facts={facts} />
    </li>
  );
}
