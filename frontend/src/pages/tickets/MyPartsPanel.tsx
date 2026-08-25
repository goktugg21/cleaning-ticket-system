// W26.4 — THE WORKER'S HALF: "My parts".
//
// A STAFF member opening their ticket used to get `SubTaskReadOnly`:
// every part of the job, every person on it, and no way to say they had
// finished any of it. The part they were standing in front of was one
// entry in a list of work that was mostly not theirs, and the only
// control that could finish it lived on a different surface.
//
// So the worker's view is their OWN parts, and each one carries the
// action that finishes it.
//
// WHAT "MARK DONE" ACTUALLY WRITES, and why there is no new endpoint:
// `SubTask` has no status column. `SubTask.is_done` is DERIVED — a part
// is done when every slot filed under it is COMPLETED. So finishing a
// part is this person completing THEIR OWN SLOT in it, which
// `PATCH /staff-assignments/<id>/` has allowed a slot's owner to do
// since Sprint 14E and which already fires the auto-complete roll-up.
// Nothing here is a new permission; the button reaches the door that
// was already there.
//
// It opens `SlotCompletionDialog` rather than PATCHing directly,
// because completion is not always free: a ticket raised from extra
// work can require a note, a photo, or both, and that dialog is the one
// place that asks the server what THIS job needs and keeps its own
// button honest. A bare "mark done" would be refused
// `completion_evidence_required` with nowhere to put the evidence.
import { useState } from "react";
import { CheckCircle2, ListChecks } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SubTask, SubTaskAssignment } from "../../api/admin";
import { BoundedList } from "../../components/BoundedList";
import { SlotStatusBadge } from "../../components/SlotStatusBadge";
import { StatusBadge } from "../../components/StatusBadge";
import { SlotCompletionDialog } from "../SlotCompletionDialog";

/** A part this viewer is on, paired with THEIR slot in it. */
type MyPart = { part: SubTask; mine: SubTaskAssignment };

export function MyPartsPanel({
  ticketId,
  subTasks,
  myUserId,
  autoCompleteOnSubtasks,
  onChanged,
}: {
  ticketId: number;
  subTasks: SubTask[];
  myUserId: number;
  /** Read-only here: the switch is a manager's (PA/SA) to set. */
  autoCompleteOnSubtasks: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const [completing, setCompleting] = useState<MyPart | null>(null);

  // ONLY their own parts, and only the slot that is theirs. A part can
  // carry several people; the others' rows are not this viewer's
  // business and are not rendered here (the manager surface keeps the
  // whole picture).
  const mine: MyPart[] = [];
  for (const part of subTasks) {
    const slot = part.staff_assignments.find(
      (candidate) => candidate.user_id === myUserId,
    );
    if (slot) mine.push({ part, mine: slot });
  }

  if (mine.length === 0) return null;

  const outstanding = mine.filter(
    (entry) => entry.mine.slot_status !== "COMPLETED",
  ).length;

  function partBadge(part: SubTask): {
    tone: "approved" | "progress" | "neutral";
    label: string;
  } {
    if (part.is_done) {
      return { tone: "approved", label: t("subtasks.status_done") };
    }
    if (part.staff_assignments.length > 0) {
      return { tone: "progress", label: t("subtasks.status_in_progress") };
    }
    return { tone: "neutral", label: t("subtasks.status_pending") };
  }

  return (
    <div
      data-testid="my-parts"
      style={{
        marginTop: 14,
        paddingTop: 12,
        borderTop: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <ListChecks size={14} strokeWidth={2} aria-hidden="true" />
        <span
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--text-faint)",
          }}
        >
          {t("my_parts.title")}
        </span>
        <span
          className="muted small"
          style={{ marginLeft: "auto" }}
          data-testid="my-parts-count"
        >
          {t("my_parts.outstanding", {
            count: outstanding,
            total: mine.length,
          })}
        </span>
      </div>

      {/* The switch is stated, not offered: when it is on, finishing the
          last part is what sends the ticket to review, and a worker who
          is not told that is being surprised by their own button. */}
      {autoCompleteOnSubtasks && (
        <p
          className="muted small"
          style={{ margin: 0 }}
          data-testid="my-parts-auto-note"
        >
          {t("my_parts.auto_complete_on")}
        </p>
      )}

      <BoundedList
        size="md"
        count={mine.length}
        ariaLabel={t("my_parts.title")}
        testIdPrefix="my-parts-list"
        className="assign-picker"
      >
        {mine.map(({ part, mine: slot }) => {
          const badge = partBadge(part);
          const isDone = slot.slot_status === "COMPLETED";
          return (
            <div
              key={part.id}
              data-testid="my-parts-row"
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: 10,
                marginBottom: 8,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
              data-part-id={part.id}
              data-slot-id={slot.id}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 8,
                  minWidth: 0,
                }}
              >
                <strong
                  style={{
                    flex: "1 1 auto",
                    minWidth: 0,
                    overflowWrap: "anywhere",
                  }}
                >
                  {part.title}
                </strong>
                <StatusBadge
                  variant="cell"
                  status={{
                    kind: "generic",
                    tone: badge.tone,
                    label: badge.label,
                  }}
                />
                {/* The part's state and THIS person's state are two
                    different facts on a shared part: the part is still
                    in progress while a colleague finishes, but their
                    own slot is done. Both are shown. */}
                <SlotStatusBadge status={slot.slot_status} />
              </div>

              {part.description && (
                <p className="muted small" style={{ margin: 0 }}>{part.description}</p>
              )}
              {slot.assignment_note && (
                <p
                  className="muted small"
                  style={{ margin: 0 }}
                  data-testid="my-parts-row-instruction"
                >
                  {slot.assignment_note}
                </p>
              )}

              <div style={{ display: "flex", gap: 6 }}>
                {isDone ? (
                  <span
                    className="muted small"
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                    data-testid="my-parts-row-done"
                  >
                    <CheckCircle2
                      size={13}
                      strokeWidth={2.2}
                      aria-hidden="true"
                    />
                    {t("my_parts.done")}
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => setCompleting({ part, mine: slot })}
                    data-testid="my-parts-mark-done"
                  >
                    {t("my_parts.mark_done")}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </BoundedList>

      {completing && (
        <SlotCompletionDialog
          // Keyed by slot so switching parts re-seeds the form instead
          // of carrying the previous part's note into the next one.
          key={completing.mine.id}
          slot={{ id: completing.mine.id, ticket_id: ticketId }}
          onCancel={() => setCompleting(null)}
          onDone={() => {
            setCompleting(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
