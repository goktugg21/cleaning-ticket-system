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
// looking like a choice between two ways to do the same thing. Creating a
// part now happens INSIDE the assign dialog -- "file this under a new part,
// called ..." -- so there is exactly one button here and one door onto
// staffing, whichever of the two you meant.
//
// PARTS get their own named section, with its own table and its own single
// button, and ONLY once parts exist. On a ticket with none -- the owner's
// ticket, and most tickets -- nothing about parts is on the page at all,
// which is the "if a role cannot use it, that role does not see it" rule
// applied to a feature nobody has reached for yet.
//
// Shape copied from `ResponsibleManagersSection` (W13), which is the same
// shape the owner's reference system uses for its two assignment blocks:
// a NAME, a count, a table, an empty state, and one button.
import { useEffect, useRef, useState } from "react";
import { Pencil, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  addTicketStaffAssignment,
  createSubTask,
  deleteSubTask,
  listAssignableStaff,
  listSubTasks,
  listTicketStaffAssignments,
  removeTicketStaffAssignment,
  setAutoCompleteFlag,
  updateStaffSlot,
  updateSubTask,
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
import { StatusBadge } from "../../components/StatusBadge";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/ToastProvider";
import { formatDateTime } from "../../lib/intl";
import { isoToLocalInput, localInputToIso } from "../../lib/slotTime";
import { AssignStaffDialog } from "./AssignStaffDialog";
import type { AssignStaffResult } from "./AssignStaffDialog";

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

export function StaffAssignmentSection({
  ticketId,
  onChanged,
  autoCompleteOnSubtasks,
  canSetAutoCompleteFlag,
  ticketStatus,
}: {
  ticketId: number;
  onChanged?: () => void;
  autoCompleteOnSubtasks: boolean;
  /** Provider admin (PA/SA) only; the backend is the hard gate (403). */
  canSetAutoCompleteFlag: boolean;
  ticketStatus: TicketStatus;
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
  const removePartRef = useRef<ConfirmDialogHandle>(null);
  const [removePartTarget, setRemovePartTarget] = useState<SubTask | null>(
    null,
  );

  // Inline rename of one part -- a row that becomes a form, so renaming a
  // part never needs a heading, a paragraph or a dialog of its own.
  const [renamingPartId, setRenamingPartId] = useState<number | null>(null);
  const [renameTitle, setRenameTitle] = useState("");

  const [autoFlag, setAutoFlag] = useState(autoCompleteOnSubtasks);
  const [flagBusy, setFlagBusy] = useState(false);

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

  // ONE confirm, however many people and however many windows.
  //
  // The people are written one at a time on purpose. The server refuses a
  // second slot for someone who already holds an indistinguishable one
  // (`duplicate_flat_assignment`, W13-FIX §6c), and a refusal has to be
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
      let targetPart = result.partId;
      let createdPartTitle = "";
      if (result.newPartTitle !== "") {
        const created = await createSubTask(ticketId, {
          title: result.newPartTitle,
        });
        targetPart = created.id;
        createdPartTitle = created.title;
      }
      const done: string[] = [];
      const refused: string[] = [];
      for (const userId of result.userIds) {
        const staff = assignable.find((entry) => entry.id === userId);
        const name =
          staff?.full_name?.trim() || staff?.email || String(userId);
        const times = result.timesByUser[userId];
        const payload: StaffSlotCreatePayload = {
          scheduled_start_at: localInputToIso(times.start),
          scheduled_end_at: localInputToIso(times.end),
          time_window_label: times.windowLabel.trim(),
          assignment_note: result.note.trim(),
        };
        if (!isTerminal) payload.sub_task = targetPart;
        try {
          await addTicketStaffAssignment(ticketId, userId, payload);
          done.push(name);
        } catch (err) {
          const code = (
            err as { response?: { data?: { code?: string } } }
          )?.response?.data?.code;
          if (code === "duplicate_flat_assignment") refused.push(name);
          else throw err;
        }
      }
      await reload();
      onChanged?.();
      if (done.length > 0) {
        const label = createdPartTitle || partTitle(targetPart) || "";
        push({
          variant: "success",
          title:
            label === ""
              ? t("assign.toast_assigned", {
                  count: done.length,
                  names: done.join(", "),
                })
              : t("assign.toast_assigned_part", {
                  count: done.length,
                  names: done.join(", "),
                  part: label,
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
      let targetPart = result.partId;
      if (result.newPartTitle !== "") {
        const created = await createSubTask(ticketId, {
          title: result.newPartTitle,
        });
        targetPart = created.id;
      }
      const times = result.timesByUser[editing.user_id];
      const patch: StaffSlotPatch = {
        scheduled_start_at: localInputToIso(times.start),
        scheduled_end_at: localInputToIso(times.end),
        time_window_label: times.windowLabel.trim(),
        assignment_note: result.note.trim(),
      };
      if (!isTerminal) patch.sub_task = targetPart;
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
    setError("");
    try {
      await removeTicketStaffAssignment(ticketId, removeTarget.id);
      removeRef.current?.close();
      setRemoveTarget(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("assign.toast_removed", { name }) });
    } catch (err) {
      setError(getApiError(err));
      removeRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  async function handleRenamePart(part: SubTask) {
    const title = renameTitle.trim();
    if (title === "") return;
    setBusy(true);
    setError("");
    try {
      await updateSubTask(ticketId, part.id, { title });
      setRenamingPartId(null);
      await reload();
      onChanged?.();
      push({
        variant: "success",
        title: t("parts.toast_renamed", { part: title }),
      });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmRemovePart() {
    if (!removePartTarget) return;
    const title = removePartTarget.title;
    setBusy(true);
    setError("");
    try {
      await deleteSubTask(ticketId, removePartTarget.id);
      removePartRef.current?.close();
      setRemovePartTarget(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("parts.toast_removed", { part: title }) });
    } catch (err) {
      setError(getApiError(err));
      removePartRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleAutoComplete(next: boolean) {
    setFlagBusy(true);
    setError("");
    try {
      const updated = await setAutoCompleteFlag(ticketId, next);
      setAutoFlag(updated.auto_complete_on_subtasks);
      onChanged?.();
      push({
        variant: "success",
        title: updated.auto_complete_on_subtasks
          ? t("parts.toast_auto_on")
          : t("parts.toast_auto_off"),
      });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setFlagBusy(false);
    }
  }

  const hasParts = parts.length > 0;
  // NOT gated on the roster. A person may legitimately hold a second
  // window on the same ticket, and a dead primary button is the failure
  // mode CLAUDE.md calls out -- so the button always opens, and the
  // dialog is where "nobody is eligible for this building" gets said.
  const canAssign = !busy;

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
              {/* THREE columns, not four. MEASURED constraint: this card
                  is a ~320px right-rail track, and the managers table
                  next door came to 327px with three columns. A separate
                  State column would have put a fourth text column in the
                  same track and truncated the names again, which is the
                  defect W13-FIX had just finished repairing. The state
                  is a line inside the When cell instead. */}
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
                {slots.map((slot) => {
                  const part = partTitle(slot.sub_task);
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
                        {part && (
                          <span
                            className="assign-table-part"
                            data-testid="staff-assignment-row-part"
                          >
                            {part}
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
          </div>
        </>
      )}

      {/* PARTS -- its own name, its own table, and only once parts exist.
          They are created inside the assign dialog, so this section never
          needs an "add" button of its own. */}
      {!loading && hasParts && (
        <div className="assign-parts" data-testid="ticket-parts-section">
          <div className="assign-parts-head">
            <span className="assign-parts-title">{t("parts.title")}</span>
            <span className="muted small" data-testid="ticket-parts-count">
              {t("parts.count", { count: parts.length })}
            </span>
          </div>
          <BoundedList
            size="sm"
            count={parts.length}
            ariaLabel={t("parts.title")}
            testIdPrefix="ticket-parts-list"
            className="table-wrap"
          >
            <table
              className="data-table data-table-dense assign-table"
              data-testid="ticket-parts-table"
            >
              <thead>
                <tr>
                  <th className="assign-table-person">{t("parts.col_part")}</th>
                  <th>{t("parts.col_state")}</th>
                  {!isTerminal && <th className="assign-table-actions" />}
                </tr>
              </thead>
              <tbody>
                {parts.map((part) => {
                  const badge = partBadge(part);
                  const renaming = renamingPartId === part.id;
                  return (
                    <tr
                      key={part.id}
                      data-testid="ticket-part-row"
                      data-part-id={part.id}
                    >
                      <td className="assign-table-person">
                        {renaming ? (
                          <input
                            className="field-input"
                            type="text"
                            maxLength={200}
                            value={renameTitle}
                            disabled={busy}
                            aria-label={t("parts.rename")}
                            onChange={(event) =>
                              setRenameTitle(event.target.value)
                            }
                            data-testid="ticket-part-rename-input"
                          />
                        ) : (
                          part.title
                        )}
                      </td>
                      <td>
                        <StatusBadge
                          variant="cell"
                          status={{
                            kind: "generic",
                            tone: badge.tone,
                            label: badge.label,
                          }}
                        />
                        <span className="assign-table-note">
                          {t("parts.people_count", {
                            count: part.staff_assignments.length,
                          })}
                        </span>
                      </td>
                      {!isTerminal && (
                        <td className="assign-table-actions">
                          {renaming ? (
                            <>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() => void handleRenamePart(part)}
                                disabled={busy || renameTitle.trim() === ""}
                                data-testid="ticket-part-rename-save"
                              >
                                {t("common:save")}
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => setRenamingPartId(null)}
                                disabled={busy}
                                data-testid="ticket-part-rename-cancel"
                              >
                                {t("common:cancel")}
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => {
                                  setRenamingPartId(part.id);
                                  setRenameTitle(part.title);
                                }}
                                disabled={busy}
                                data-testid="ticket-part-rename"
                              >
                                <Pencil
                                  size={13}
                                  strokeWidth={2.2}
                                  aria-hidden="true"
                                />
                                {t("parts.rename")}
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => {
                                  setRemovePartTarget(part);
                                  removePartRef.current?.open();
                                }}
                                disabled={busy}
                                data-testid="ticket-part-remove"
                              >
                                <X
                                  size={13}
                                  strokeWidth={2.5}
                                  aria-hidden="true"
                                />
                                {t("parts.remove")}
                              </button>
                            </>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </BoundedList>

          {/* One line, one verb-less state sentence, no explaining
              paragraph. Absent for anyone who cannot write it. */}
          {canSetAutoCompleteFlag && !isTerminal && (
            <label
              className="assign-parts-auto"
              data-testid="ticket-parts-auto-complete"
            >
              <Toggle
                checked={autoFlag}
                disabled={flagBusy}
                onChange={(event) =>
                  void handleToggleAutoComplete(event.target.checked)
                }
                data-testid="ticket-parts-auto-complete-toggle"
              />
              <span className="small">{t("parts.auto_complete_label")}</span>
            </label>
          )}
        </div>
      )}

      {assignOpen && (
        <AssignStaffDialog
          mode="assign"
          candidates={assignable}
          parts={parts}
          allowParts={!isTerminal}
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
          initialNote={editing.assignment_note}
          initialPartId={editing.sub_task}
          parts={parts}
          allowParts={!isTerminal}
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
        body={t("editor.remove_dialog_body")}
        confirmLabel={t("assign.remove")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={busy}
        destructive
      />

      <ConfirmDialog
        ref={removePartRef}
        title={t("parts.remove_dialog_title", {
          title: removePartTarget ? removePartTarget.title : "",
        })}
        body={t("parts.remove_dialog_body")}
        confirmLabel={t("parts.remove")}
        onConfirm={handleConfirmRemovePart}
        onCancel={() => setRemovePartTarget(null)}
        busy={busy}
        destructive
      />
    </div>
  );
}
