/**
 * W3-F — the plan, as it reads back. "A planned job should read as
 * planned at a glance."
 *
 * Provider-only, and the caller is responsible for that: the four
 * planning fields are stripped from a CUSTOMER_USER response server-side
 * (`_PROVIDER_ONLY_FIELDS`), so a customer would render an empty block
 * here rather than a leak — but an empty block that only providers ever
 * see is still the wrong shape, and the page gates the mount on the role
 * check it already uses.
 *
 * TWO THINGS THIS DELIBERATELY SHOWS THAT A NAIVE VERSION WOULD NOT
 * -----------------------------------------------------------------
 * **A crew member who has been taken OFF the work still appears**, with
 * their hours, marked. Their row carries `is_assigned: false` from the
 * server for exactly this, and it still counts in the total. Hiding it
 * would reproduce the reference system's defect, where the grid is built
 * from the assignment list so a removed worker's hours vanish from the
 * screen while still counting in every total — the screen and the total
 * disagree, with nothing on screen to explain it (their live work 474
 * shows 13.5 distributed hours against a budget of 1.00, silently).
 *
 * **The overrun renders on the READ surface too**, not only in the reply
 * to whoever pressed save. The manager approving the work is usually not
 * the person who planned it, and they need to see the overrun on the
 * screen they approve from.
 *
 * NOT MONEY. Every figure here is hours.
 */
import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";

import type { ExtraWorkRequestDetail } from "../../api/types";
import { formatDate } from "../../lib/intl";

export function PlanSummary({ ew }: { ew: ExtraWorkRequestDetail }) {
  const { t } = useTranslation(["extra_work", "common"]);

  const rows = ew.planned_hours ?? [];
  const overrun = ew.planned_hours_overrun ?? null;
  const hasWindow = Boolean(
    ew.provider_planned_date || ew.provider_planned_end_date,
  );
  const hasPlan =
    Boolean(ew.budget_hours) ||
    rows.length > 0 ||
    hasWindow ||
    ew.file_upload_required === true ||
    ew.completion_notes_required === true;

  if (!hasPlan) return null;

  return (
    <div className="ew-plan-summary" data-testid="extra-work-plan-summary">
      <span className="muted small ew-plan-summary-title">
        {t("plan.summary_title")}
      </span>

      <div className="ew-plan-summary-figures">
        <div>
          <div className="muted small">{t("plan.budget_hours_label")}</div>
          <div data-testid="extra-work-plan-summary-budget">
            {ew.budget_hours
              ? t("plan.hours_value", { hours: ew.budget_hours })
              : t("detail.empty_dash")}
          </div>
        </div>
        <div>
          <div className="muted small">{t("plan.distributed_label")}</div>
          <div data-testid="extra-work-plan-summary-total">
            {t("plan.hours_value", { hours: ew.planned_hours_total ?? "0.00" })}
          </div>
        </div>
        <div>
          {/* OUR window. Named so it cannot be read as the customer's
              requested date, which sits in the grid above. */}
          <div className="muted small">{t("plan.our_window_title")}</div>
          <div data-testid="extra-work-plan-summary-window">
            {hasWindow
              ? `${
                  ew.provider_planned_date
                    ? formatDate(ew.provider_planned_date)
                    : t("detail.empty_dash")
                } - ${
                  ew.provider_planned_end_date
                    ? formatDate(ew.provider_planned_end_date)
                    : t("detail.empty_dash")
                }`
              : t("detail.empty_dash")}
          </div>
        </div>
      </div>

      {rows.length > 0 && (
        <ul className="ew-plan-summary-crew">
          {rows.map((row) => (
            <li
              key={row.user_id}
              className="ew-plan-summary-crew-row"
              data-testid="extra-work-plan-summary-crew-row"
            >
              <span className="ew-plan-summary-crew-name">
                {row.user_full_name || row.user_email}
                {!row.is_assigned && (
                  /* Still counted in the total above — see the
                     docblock. */
                  <span
                    className="ew-plan-summary-unassigned"
                    data-testid="extra-work-plan-summary-unassigned"
                  >
                    {t("plan.no_longer_assigned")}
                  </span>
                )}
              </span>
              <span>{t("plan.hours_value", { hours: row.hours })}</span>
            </li>
          ))}
        </ul>
      )}

      {overrun && (
        <div
          className="ew-plan-overrun"
          role="status"
          data-testid="extra-work-plan-summary-overrun"
        >
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <div className="ew-plan-overrun-title">
              {t("plan.overrun_title", { over: overrun.over_by })}
            </div>
            <div className="muted small">
              {t("plan.overrun_hint", {
                distributed: overrun.distributed_hours,
                budget: overrun.budget_hours,
              })}
            </div>
          </div>
        </div>
      )}

      {(ew.file_upload_required || ew.completion_notes_required) && (
        <div
          className="ew-plan-summary-flags muted small"
          data-testid="extra-work-plan-summary-flags"
        >
          {ew.file_upload_required && (
            <span>{t("plan.photo_required_label")}</span>
          )}
          {ew.completion_notes_required && (
            <span>{t("plan.notes_required_label")}</span>
          )}
        </div>
      )}
    </div>
  );
}
