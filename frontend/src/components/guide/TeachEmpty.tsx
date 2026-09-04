/**
 * P-12 §D.24 rule 5 — empty states teach: the thing, and how it gets
 * here. "No drafts. A draft appears when you press Make a draft on
 * finished work."
 */
import { GuideActionButton, type GuideAction } from "./StartHere";
import "./guide.css";

export function TeachEmpty({
  title,
  body,
  action,
  testId = "guide-empty",
}: {
  title: string;
  body: string;
  action?: GuideAction;
  testId?: string;
}) {
  return (
    <div className="guide-empty" data-testid={testId}>
      <b>{title}</b>
      <p>{body}</p>
      {action && <GuideActionButton action={action} testId={`${testId}-action`} />}
    </div>
  );
}
