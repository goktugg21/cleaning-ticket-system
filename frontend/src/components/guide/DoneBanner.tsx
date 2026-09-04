/**
 * P-12 §D.24 rule 4 — the teal "Done" banner: what happened, what did
 * NOT happen, and the one next step. A bare toast is never the only
 * feedback. Dismissible; survives one reload (useDoneBanner +
 * doneBannerStore carry that contract).
 */
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

import type { DoneAnnouncement } from "./doneBannerStore";
import "./guide.css";

export function DoneBanner({
  done,
  onDismiss,
  testId = "guide-done",
}: {
  done: DoneAnnouncement;
  onDismiss: () => void;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="guide-done" role="status" data-testid={testId}>
      <span className="guide-kicker guide-kicker-done">{t("guide.done")}</span>
      <div className="guide-done-words">
        <p className="guide-done-title">{done.title}</p>
        {done.body && <p className="guide-done-body">{done.body}</p>}
      </div>
      {done.actionLabel && done.actionTo && (
        <Link
          to={done.actionTo}
          className="btn btn-primary"
          data-testid={`${testId}-action`}
        >
          {done.actionLabel}
        </Link>
      )}
      <button
        type="button"
        className="guide-done-dismiss"
        onClick={onDismiss}
        aria-label={t("guide.dismiss")}
        data-testid={`${testId}-dismiss`}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
