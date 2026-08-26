/**
 * W-LATE addendum 2 — how a notification's `severity` becomes a tone.
 *
 * One reading for the bell, the list and the toast, so the same row is
 * the same colour everywhere. `INFO` is activity and adds nothing; the
 * existing warning rendering (amber, keyed off the warning-type list)
 * already covers L1, so only L2 and L3 add a class of their own.
 */
import type { Notification } from "../api/types";
import type { ToastSeverity } from "../components/ToastProvider";

/** ` notif-item-sev-l2` / ` notif-page-row-sev-l3` / "" — with the
 *  leading space, ready to append to a className string. */
export function notificationSeverityClass(
  notification: Pick<Notification, "severity">,
  prefix: string,
): string {
  const severity = notification.severity;
  if (severity === "L2" || severity === "L3") {
    return ` ${prefix}-sev-${severity.toLowerCase()}`;
  }
  return "";
}

/** The toast's rung, or undefined for plain activity. */
export function notificationToastSeverity(
  notification: Pick<Notification, "severity">,
): ToastSeverity | undefined {
  const severity = notification.severity;
  if (severity === "L1" || severity === "L2" || severity === "L3") {
    return severity;
  }
  return undefined;
}
