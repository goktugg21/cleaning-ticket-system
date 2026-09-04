/**
 * W13 — what changed, in the user's words, in ONE place.
 *
 *     The owner's father: "I don't know whether I passed between pages.
 *     I click. It has to give me a warning. It has to tell me 'you have
 *     been moved to the next stage'. I cannot be sure whether the button
 *     worked."
 *
 * He was right about this screen. The ticket's status transition and its
 * assign action both did `setTicket(response.data)` and nothing else: no
 * toast, no sentence, no acknowledgement of any kind. The page simply
 * looked slightly different afterwards and you were left to work out
 * whether that was you.
 *
 * ## THIS IS NOT A SECOND MECHANISM
 *
 * `components/ToastProvider.tsx` has been the one queue since Sprint 28
 * and has 29 caller files. Nothing here renders anything. This module
 * only WRITES THE SENTENCE, from the ticket before and the ticket after,
 * and hands it to that provider. One place composes it, so every screen
 * that announces a ticket change says it the same way and none of them
 * can drift into "Saved".
 *
 * ## WHAT IT SAYS
 *
 * The state, then the consequences, as separate facts:
 *
 *     Moved to In progress.
 *     Ahmet Yildiz is assigned.
 *
 * The title is a SENTENCE ABOUT THE WORK and never the verb on the
 * button that caused it — pressing "Start work" answers "Moved to In
 * progress", because echoing the button back only proves the click
 * registered, not that anything happened.
 *
 * A change that moved nothing says so rather than claiming a success it
 * cannot point at: if neither the status nor the crew differs, the
 * caller gets `null` and should stay quiet instead of congratulating the
 * user for a no-op.
 */
import type { TicketDetail, AssignedStaffEntry } from "../api/types";

/** The sentence, ready for `push({ variant: "success", ...it })`. */
export interface ChangeAnnouncement {
  title: string;
  description?: string;
}

type Translate = (key: string, vars?: Record<string, unknown>) => string;

function namesOf(entries: AssignedStaffEntry[] | undefined): string[] {
  return (entries ?? [])
    .map((entry) =>
      "anonymous" in entry && entry.anonymous
        ? null
        : (entry.full_name || entry.email || "").trim(),
    )
    .filter((name): name is string => Boolean(name));
}

/**
 * Compose the announcement for one ticket write.
 *
 * `statusLabel` is the caller's own status vocabulary — the same helper
 * the page's badges use — so the toast and the badge under it cannot
 * name one status two ways.
 *
 * Returns null when nothing a person would notice actually moved.
 */
export function describeTicketChange(
  before: TicketDetail | null,
  after: TicketDetail,
  t: Translate,
  statusLabel: (status: string) => string,
): ChangeAnnouncement | null {
  const statusMoved = before !== null && before.status !== after.status;

  const beforeNames = namesOf(before?.assigned_staff);
  const afterNames = namesOf(after.assigned_staff);
  const crewChanged =
    before !== null &&
    (beforeNames.length !== afterNames.length ||
      beforeNames.some((name, i) => name !== afterNames[i]));

  if (!statusMoved && !crewChanged) return null;

  // The state leads when it moved, because that is the thing the father
  // could not see. When only the crew changed, the crew is the headline
  // rather than a footnote under a status that did not move.
  const title = statusMoved
    ? t("change.moved_to", { status: statusLabel(after.status) })
    : afterNames.length === 0
      ? t("change.nobody_assigned")
      : t("change.assigned_now", { names: afterNames.join(", ") });

  if (!statusMoved) return { title };

  const description = !crewChanged
    ? undefined
    : afterNames.length === 0
      ? t("change.nobody_assigned")
      : t("change.assigned_now", { names: afterNames.join(", ") });

  return { title, description };
}
