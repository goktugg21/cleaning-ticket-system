// W14 — STAFF ASSIGNMENT: one name, one table, one button.
//
// What the owner read, top to bottom, before this file:
//
//     Assignment  0 staff members
//     Assigned Osius Demo staff / No staff assigned yet
//     Staff slots / Add sub-task
//     "Split this ticket into dated work slots -- one per staff member ..."
//     No staff slots yet. Add one to dispatch a staff member.
//     Add slot / Staff member / <checkboxes> / Start / End / Time window
//       label / Assignment note / Add slot
//     Auto-complete when all sub-tasks are done + its explanation
//
// Four headings, two explanatory paragraphs and three buttons for one idea:
// put people on this job. A table of assigned people does not need a
// sentence explaining that it is a table of assigned people, so the prose is
// gone -- both paragraphs, and the empty state trimmed to one line.
//
// The two near-identical buttons are resolved to one. `Add slot` and
// `Add sub-task` were not the same operation (one attaches a PERSON, one
// names a PART of the job) but they sat side by side under one heading
// looking like a choice between two ways to do the same thing. So there is
// exactly one primary button here and one door onto staffing, whichever of
// the two you meant.
//
// W26.2 -- PARTS are the second door, and it is a door, not a section.
// They used to be an inline table that appeared only once parts existed,
// with the auto-complete switch underneath it; the control that CREATED a
// part had gone with the assign dialog's part picker (W19), which left the
// whole surface reachable only for parts nobody could make. Now a
// secondary `Parts (N)` button sits next to the assign action and opens
// `SubTasksModal`, which owns every part operation. Nothing about parts is
// rendered on this card any more, including on a ticket that has none --
// the count on the button is the whole statement.
//
// The button carries the same predicate as the assign action because it is
// inside this card, and `TicketDetailPage` renders this card only for
// provider MANAGEMENT roles (`isProviderManagementRole`). The one control
// with a NARROWER gate is the auto-complete switch inside the modal --
// PA/SA only, via `canSetAutoCompleteFlag`, because that is what
// `auto-complete-flag/` enforces (403 `auto_complete_flag_forbidden`).
//
// Shape copied from `ResponsibleManagersSection` (W13), which is the same
// shape the owner's reference system uses for its two assignment blocks:
// a NAME, a count, a table, an empty state, and one button.
import { useEffect, useRef, useState } from "react";
import { Pencil, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  addTicketStaffAssignment,
  listAssignableStaff,
  listSubTasks,
  listTicketStaffAssignments,
  removeTicketStaffAssignment,
  updateStaffSlot,
} from "../../api/admin";
import type {
  AssignableStaff,
  StaffSlotCreatePayload,
  StaffSlotPatch,
  SubTask,
  TicketStaffAssignmentAdmin,
} from "../../api/admin";
import type { TicketStatus } from "../../api/types";
import { getApiError } from "../../api/client";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { SlotStatusBadge } from "../../components/SlotStatusBadge";
import { useToast } from "../../components/ToastProvider";
import { formatDateTime } from "../../lib/intl";
import { isoToLocalInput, localInputToIso } from "../../lib/slotTime";
import { AssignStaffDialog } from "./AssignStaffDialog";
import type { AssignStaffResult } from "./AssignStaffDialog";
import { SubTasksModal } from "./SubTasksModal";

// Frontend mirror of the backend TERMINAL_TICKET_STATUSES. Part CRUD, part
// placement and the auto-complete flag all 400/403 on these, so the controls
// that write them are absent; the table stays.
const TERMINAL_TICKET_STATUSES: ReadonlySet<TicketStatus> =
  new Set<TicketStatus>([
    "APPROVED",
    "REJECTED",
    "CLOSED",
    "CONVERTED_TO_EXTRA_WORK",
  ]);

// W26.3 — SHADOW DISPLAY: one row per PERSON, not one row per slot.
//
// A person on this job holds ONE base slot (`sub_task === null`) and, on
// top of it, one slot per part of the job they were given. Rendered
// slot-by-slot that is "Ahmet, Ahmet, Ahmet" down the card -- the exact
// disease the owner's rule exists to kill, and the reason parts were
// unusable before this sprint. So the base slot IS the row (name,
// schedule, actions) and the parts hang under the name as chips. Part
// slots never become rows, and they carry no schedule of their own:
// time lives on the base slot.
//
// The two exceptions are both LEGACY shapes the server can no longer
// create, and both resolve the same way -- give the row back rather
// than hide it, because a row nobody can see is a row nobody can
// delete:
//
//   * a second BASE slot for the same person (pre-W26 duplicates) gets
//     its own row, so it stays editable and removable;
//   * part slots with NO base slot (pre-W26.3, when a first slot could
//     be filed straight into a part) each get their own row, because
//     there is no base row to hang them under.
type PersonRow = {
  /** The slot this row represents, and whose actions it carries. */
  anchor: TicketStaffAssignmentAdmin;
  /** Part slots drawn as chips under the name. Never rows themselves. */
  partSlots: TicketStaffAssignmentAdmin[];
};

function buildPersonRows(all: TicketStaffAssignmentAdmin[]): PersonRow[] {
  const byUser = new Map<number, TicketStaffAssignmentAdmin[]>();
  for (const slot of all) {
    const bucket = byUser.get(slot.user_id);
    if (bucket) bucket.push(slot);
    else byUser.set(slot.user_id, [slot]);
  }
  const rows: PersonRow[] = [];
  // Map iterates in first-insertion order, so people keep the order the
  // server sent them in rather than being re-sorted by this grouping.
  for (const slots of byUser.values()) {
    const base = slots.filter((slot) => slot.sub_task === null);
    const parts = slots.filter((slot) => slot.sub_task !== null);
    if (base.length === 0) {
      for (const part of parts) rows.push({ anchor: part, partSlots: [] });
      continue;
    }
    rows.push({ anchor: base[0], partSlots: parts });
    for (const extra of base.slice(1)) {
      rows.push({ anchor: extra, partSlots: [] });
    }
  }
  return rows;
}

export function StaffAssignmentSection({
  ticketId,
  onChanged,
  autoCompleteOnSubtasks,
  canSetAutoCompleteFlag,
  ticketStatus,
  customerWantedDate,
}: {
  ticketId: number;
  onChanged?: () => void;
  autoCompleteOnSubtasks: boolean;
  /** Provider admin (PA/SA) only; the backend is the hard gate (403). */
  canSetAutoCompleteFlag: boolean;
  ticketStatus: TicketStatus;
  /** W19 -- `Ticket.customer_wanted_date`, forwarded to the assign/edit
   *  dialog so the window is picked with the customer's wish in view. */
  customerWantedDate?: string | null;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const { push } = useToast();

  const isTerminal = TERMINAL_TICKET_STATUSES.has(ticketStatus);

  const [slots, setSlots] = useState<TicketStaffAssignmentAdmin[]>([]);
  const [assignable, setAssignable] = useState<AssignableStaff[]>([]);
  const [parts, setParts] = useState<SubTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [assignOpen, setAssignOpen] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [editing, setEditing] = useState<TicketStaffAssignmentAdmin | null>(
    null,
  );

  const removeRef = useRef<ConfirmDialogHandle>(null);
  const [removeTarget, setRemoveTarget] =
    useState<TicketStaffAssignmentAdmin | null>(null);
  // W-T3 §1 — the remove confirm's own failure, rendered in the dialog.
  const [removeError, setRemoveError] = useState("");
  // W26.2 -- parts live behind one door now (`SubTasksModal`), so the
  // rename draft, the remove confirm and the auto-complete flag are that
  // modal's state, not this card's.
  const [partsOpen, setPartsOpen] = useState(false);

  async function reload() {
    const [slotResp, staffResp, partResp] = await Promise.all([
      listTicketStaffAssignments(ticketId),
      listAssignableStaff(ticketId),
      listSubTasks(ticketId),
    ]);
    setSlots(slotResp.results);
    setAssignable(staffResp);
    setParts(partResp);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [slotResp, staffResp, partResp] = await Promise.all([
          listTicketStaffAssignments(ticketId),
          listAssignableStaff(ticketId),
          listSubTasks(ticketId),
        ]);
        if (cancelled) return;
        setSlots(slotResp.results);
        setAssignable(staffResp);
        setParts(partResp);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [ticketId]);

  function personName(slot: TicketStaffAssignmentAdmin): string {
    return slot.user_full_name?.trim() || slot.user_email;
  }

  function windowText(slot: TicketStaffAssignmentAdmin): string {
    const bits: string[] = [];
    if (slot.scheduled_start_at) {
      bits.push(
        slot.scheduled_end_at
          ? `${formatDateTime(slot.scheduled_start_at)} - ${formatDateTime(
              slot.scheduled_end_at,
            )}`
          : formatDateTime(slot.scheduled_start_at),
      );
    }
    if (slot.time_window_label) bits.push(slot.time_window_label);
    return bits.length > 0 ? bits.join(" - ") : t("editor.unscheduled");
  }

  function partTitle(partId: number | null): string | null {
    if (partId === null) return null;
    return parts.find((p) => p.id === partId)?.title ?? null;
  }

  // ONE confirm, however many people and however many windows.
  //
  // The people are written one at a time on purpose. The server refuses a
  // second slot for someone who already holds ANY slot here
  // (`staff_already_assigned`, W26 -- one person, one slot; it superseded
  // W13-FIX §6c's narrower `duplicate_flat_assignment`, which this branch
  // was still testing for and so never matched), and a refusal has to be
  // able to NAME the person it refused. So each write is caught on its
  // own: the ones that landed are kept and announced, the ones that were
  // refused are listed by name with what to change, and the table behind
  // the dialog is reloaded either way so it never disagrees with what
  // actually happened.
  //
  // W14 note: this replaces W13-FIX's client-side pre-filter, which
  // silently REMOVED such a person from the picker and then needed a
  // sentence of prose to explain the empty list. Everyone eligible is
  // offered; the server is the one that refuses, and it says why.
  async function handleAssign(result: AssignStaffResult) {
    setBusy(true);
    setDialogError("");
    try {
      const done: string[] = [];
      const refused: string[] = [];
      for (const userId of result.userIds) {
        const staff = assignable.find((entry) => entry.id === userId);
        const name =
          staff?.full_name?.trim() || staff?.email || String(userId);
        const times = result.timesByUser[userId];
        // W19 -- the dialog edits people and times, so the write carries
        // people and times. `assignment_note` / `sub_task` are OMITTED,
        // not sent empty: a new slot starts without either (the server
        // defaults), and the fields stay editable where they live (the
        // per-slot editor and the Parts table).
        const payload: StaffSlotCreatePayload = {
          scheduled_start_at: localInputToIso(times.start),
          scheduled_end_at: localInputToIso(times.end),
          time_window_label: times.windowLabel.trim(),
        };
        try {
          await addTicketStaffAssignment(ticketId, userId, payload);
          done.push(name);
        } catch (err) {
          const code = (
            err as { response?: { data?: { code?: string } } }
          )?.response?.data?.code;
          if (code === "staff_already_assigned") refused.push(name);
          else throw err;
        }
      }
      await reload();
      onChanged?.();
      if (done.length > 0) {
        push({
          variant: "success",
          title: t("assign.toast_assigned", {
            count: done.length,
            names: done.join(", "),
          }),
        });
      }
      // The dialog CLOSES either way. Leaving it open with the same
      // people still ticked invites a second confirm that would assign
      // the ones who already landed all over again; the refusal is a
      // sentence on screen, next to a table that now shows exactly who
      // is on the job.
      setAssignOpen(false);
      if (refused.length > 0) {
        push({
          variant: "error",
          title: t("assign.error_duplicate", {
            count: refused.length,
            names: refused.join(", "),
          }),
        });
      }
    } catch (err) {
      setDialogError(getApiError(err));
      await reload().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveEdit(result: AssignStaffResult) {
    if (!editing) return;
    setBusy(true);
    setDialogError("");
    try {
      const times = result.timesByUser[editing.user_id];
      // W19 -- a time edit PATCHes ONLY the time. `assignment_note` and
      // `sub_task` are absent from the body, and a partial update never
      // touches an absent field, so an existing slot note or part link
      // survives every window change (the invariant the old echo fields
      // existed to protect -- now protected by omission instead).
      const patch: StaffSlotPatch = {
        scheduled_start_at: localInputToIso(times.start),
        scheduled_end_at: localInputToIso(times.end),
        time_window_label: times.windowLabel.trim(),
      };
      await updateStaffSlot(ticketId, editing.id, patch);
      const name = personName(editing);
      setEditing(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("assign.toast_saved", { name }) });
    } catch (err) {
      setDialogError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmRemove() {
    if (!removeTarget) return;
    const name = personName(removeTarget);
    setBusy(true);
    setRemoveError("");
    try {
      await removeTicketStaffAssignment(ticketId, removeTarget.id);
      removeRef.current?.close();
      setRemoveTarget(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("assign.toast_removed", { name }) });
    } catch (err) {
      // W-T3 §1 — the dialog STAYS OPEN and names the refusal inside
      // itself. It used to close and drop the message into the card's
      // banner, which read as "the remove happened" while the row was
      // still there.
      setRemoveError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // NOT gated on the roster. A person may legitimately hold a second
  // window on the same ticket, and a dead primary button is the failure
  // mode CLAUDE.md calls out -- so the button always opens, and the
  // dialog is where "nobody is eligible for this building" gets said.
  const canAssign = !busy;

  const personRows = buildPersonRows(slots);

  // W26.3 (c) — the PART picker's source. Parts divide the people
  // already on the job, so the modal offers exactly the base-slot
  // holders, deduped (a legacy duplicate base slot must not list the
  // same person twice). Derived from the slots this card already holds
  // rather than fetched: `assignable-staff` is the JOB-level picker and
  // means the opposite set -- people NOT yet on the job.
  const onJob = Array.from(
    new Map(
      slots
        .filter((slot) => slot.sub_task === null)
        .map((slot) => [slot.user_id, { id: slot.user_id, name: personName(slot) }]),
    ).values(),
  );

  // Removing a base slot takes the person off the job, and the server
  // takes their parts with it. The confirm NAMES those parts, because
  // this deletes more than the row that was clicked.
  const removeTargetParts =
    removeTarget && removeTarget.sub_task === null
      ? slots
          .filter(
            (slot) =>
              slot.user_id === removeTarget.user_id && slot.sub_task !== null,
          )
          .map((slot) => partTitle(slot.sub_task))
          .filter((title): title is string => title !== null)
      : [];

  return (
    <div className="assign-section" data-testid="staff-assignment-section">
      {error && (
        <div
          className="alert-error"
          role="alert"
          data-testid="staff-assignment-error"
        >
          {error}
        </div>
      )}

      {loading ? (
        <p className="muted small">{t("editor.loading")}</p>
      ) : slots.length === 0 ? (
        <div className="assign-empty" data-testid="staff-assignment-empty">
          <p className="assign-empty-title">{t("assign.empty")}</p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setDialogError("");
              setAssignOpen(true);
            }}
            disabled={!canAssign}
            data-testid="staff-assignment-assign"
          >
            {t("assign.title")}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setPartsOpen(true)}
            disabled={busy}
            data-testid="ticket-parts-open"
          >
            {t("parts.open", { n: parts.length })}
          </button>
        </div>
      ) : (
        <>
          <BoundedList
            size="md"
            count={slots.length}
            ariaLabel={t("assign.table_label")}
            testIdPrefix="staff-assignment-list"
            className="table-wrap"
          >
            <table
              className="data-table data-table-dense assign-table"
              data-testid="staff-assignment-table"
            >
              {/* THREE columns, not four -- the constraint is MEASURED,
                  not guessed. This card is the right rail, and the rail
                  is 310px at a 1280 viewport (337px at 1366, 361px at
                  1440; below ~1100 the layout stacks and the card goes
                  full width). Rendered, these three columns come to
                  301px -- 107 name / 85 when / 109 actions -- with no
                  clipped cell and no page-level horizontal scroll at any
                  of those widths. A fourth text column for State would
                  not have fit, and the failure mode is the truncated
                  "MANAGER | ASSIG..." header W13-FIX had just finished
                  repairing on the managers table next door. The state is
                  a line inside the When cell instead. */}
              <thead>
                <tr>
                  <th className="assign-table-person">
                    {t("assign.col_person")}
                  </th>
                  <th>{t("assign.col_when")}</th>
                  <th className="assign-table-actions" />
                </tr>
              </thead>
              <tbody>
                {personRows.map(({ anchor: slot, partSlots }) => {
                  // A legacy part-anchored row still names its part, so
                  // the row says what it is; a normal row's parts are
                  // the chips below.
                  const ownPart = partTitle(slot.sub_task);
                  const chips = partSlots
                    .map((part) => partTitle(part.sub_task))
                    .filter((title): title is string => title !== null);
                  return (
                    <tr
                      key={slot.id}
                      data-testid="staff-assignment-row"
                      data-slot-id={slot.id}
                      data-staff-id={slot.user_id}
                    >
                      <td
                        className="assign-table-person"
                        title={slot.user_email}
                      >
                        {personName(slot)}
                        {ownPart && (
                          <span
                            className="assign-table-part"
                            data-testid="staff-assignment-row-part"
                          >
                            {ownPart}
                          </span>
                        )}
                        {chips.length > 0 && (
                          <span
                            className="parts-chip-row parts-chip-row-stacked"
                            data-testid="staff-assignment-row-chips"
                          >
                            {chips.map((title) => (
                              <span
                                key={title}
                                className="parts-chip"
                                data-testid="staff-assignment-chip"
                              >
                                {title}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                      {/* The badge is the state; the line under it is
                          what the person reported. A manager who has to
                          click a row open to find out why the work did
                          not happen is being made to hunt for the one
                          fact the row exists to carry. */}
                      <td data-testid="staff-assignment-row-when">
                        <span className="assign-table-when">
                          {windowText(slot)}
                        </span>
                        <SlotStatusBadge status={slot.slot_status} />
                        {slot.assignment_note && (
                          <span
                            className="assign-table-note"
                            data-testid="staff-assignment-row-instruction"
                          >
                            {slot.assignment_note}
                          </span>
                        )}
                        {slot.slot_status === "COMPLETED" &&
                          slot.completion_note && (
                            <span
                              className="assign-table-note"
                              data-testid="staff-assignment-row-report"
                            >
                              {slot.completion_note}
                            </span>
                          )}
                        {slot.slot_status === "UNABLE_TO_COMPLETE" &&
                          slot.unable_to_complete_reason && (
                            <span
                              className="assign-table-note"
                              data-testid="staff-assignment-row-report"
                            >
                              {slot.unable_to_complete_reason}
                            </span>
                          )}
                      </td>
                      <td className="assign-table-actions">
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            setDialogError("");
                            setEditing(slot);
                          }}
                          disabled={busy}
                          data-testid="staff-assignment-edit"
                        >
                          <Pencil size={13} strokeWidth={2.2} aria-hidden="true" />
                          {t("assign.edit")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            setRemoveTarget(slot);
                            setRemoveError("");
                            removeRef.current?.open();
                          }}
                          disabled={busy}
                          data-testid="staff-assignment-remove"
                        >
                          <X size={13} strokeWidth={2.5} aria-hidden="true" />
                          {t("assign.remove")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </BoundedList>
          <div className="assign-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setDialogError("");
                setAssignOpen(true);
              }}
              disabled={!canAssign}
              data-testid="staff-assignment-assign"
            >
              {t("assign.title")}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setPartsOpen(true)}
              disabled={busy}
              data-testid="ticket-parts-open"
            >
              {t("parts.open", { n: parts.length })}
            </button>
          </div>
        </>
      )}

      {partsOpen && (
        <SubTasksModal
          ticketId={ticketId}
          parts={parts}
          onJob={onJob}
          isTerminal={isTerminal}
          canSetAutoCompleteFlag={canSetAutoCompleteFlag}
          autoCompleteOnSubtasks={autoCompleteOnSubtasks}
          onChanged={async () => {
            await reload();
            onChanged?.();
          }}
          onClose={() => setPartsOpen(false)}
        />
      )}

      {assignOpen && (
        <AssignStaffDialog
          mode="assign"
          candidates={assignable}
          customerWantedDate={customerWantedDate}
          busy={busy}
          error={dialogError}
          noCandidatesText={t("editor.no_eligible")}
          onCancel={() => {
            setAssignOpen(false);
            setDialogError("");
          }}
          onConfirm={(result) => void handleAssign(result)}
        />
      )}

      {editing && (
        <AssignStaffDialog
          // Prop-derived initial state: keyed by the row so switching rows
          // re-seeds the form instead of leaking the previous one.
          key={editing.id}
          mode="edit"
          candidates={assignable}
          editingPersonId={editing.user_id}
          editingPersonName={personName(editing)}
          initialTimes={{
            start: isoToLocalInput(editing.scheduled_start_at),
            end: isoToLocalInput(editing.scheduled_end_at),
            windowLabel: editing.time_window_label,
          }}
          customerWantedDate={customerWantedDate}
          busy={busy}
          error={dialogError}
          noCandidatesText={t("editor.no_eligible")}
          onCancel={() => {
            setEditing(null);
            setDialogError("");
          }}
          onConfirm={(result) => void handleSaveEdit(result)}
        />
      )}

      <ConfirmDialog
        ref={removeRef}
        title={t("editor.remove_dialog_title", {
          name: removeTarget ? personName(removeTarget) : "",
        })}
        body={
          <>
            {removeTargetParts.length > 0
              ? t("editor.remove_dialog_body_with_parts", {
                  parts: removeTargetParts.join(" \u00b7 "),
                })
              : t("editor.remove_dialog_body")}
            {removeError && (
              <div
                className="alert-error"
                role="alert"
                data-testid="staff-assignment-remove-error"
              >
                {removeError}
              </div>
            )}
          </>
        }
        confirmLabel={t("assign.remove")}
        onConfirm={handleConfirmRemove}
        onCancel={() => {
          setRemoveTarget(null);
          setRemoveError("");
        }}
        busy={busy}
        destructive
      />

    </div>
  );
}
