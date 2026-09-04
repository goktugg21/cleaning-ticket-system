/**
 * P-12 §D.24 rule 2 — the green card under the purpose line naming the
 * ONE thing waiting and its button. The PAGE computes whether anything
 * waits (from its own counts) and simply does not render this when
 * nothing does; the card never celebrates zero. Never two things — the
 * second lives on its tab.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import "./guide.css";

export interface GuideAction {
  label: string;
  /** Router path — rendered as a Link. */
  to?: string;
  /** Or a handler — rendered as a button. */
  onClick?: () => void;
}

function ActionButton({
  action,
  testId,
}: {
  action: GuideAction;
  testId: string;
}) {
  if (action.to && !action.onClick) {
    return (
      <Link to={action.to} className="btn btn-primary" data-testid={testId}>
        {action.label}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className="btn btn-primary"
      onClick={action.onClick}
      data-testid={testId}
    >
      {action.label}
    </button>
  );
}

export function StartHere({
  children,
  action,
  testId = "guide-start-here",
}: {
  /** The sentence: what is waiting, in plain words. */
  children: ReactNode;
  action?: GuideAction;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="guide-start" data-testid={testId}>
      <span className="guide-kicker guide-kicker-start">{t("guide.start_here")}</span>
      <p className="guide-start-sentence">{children}</p>
      {action && <ActionButton action={action} testId={`${testId}-action`} />}
    </div>
  );
}

export { ActionButton as GuideActionButton };
