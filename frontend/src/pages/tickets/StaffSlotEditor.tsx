// Phase B — manager "Staff slots / Work assignments" editor on the ticket
// detail page. Provider-management ONLY (the parent gates on
// isProviderManagementRole; STAFF + CUSTOMER never render this and so never
// call the management slot endpoints, which would 403 them).
//
// Each slot is one TicketStaffAssignment row; a ticket can carry several
// (Ramazan's AM/PM split = two slots). Managers add a dated slot, edit its
// schedule/window/note, or remove it. Completion (note/photo evidence) and
// "unable" belong to the staff agenda (Part C) — this editor never sets
// COMPLETED.
//
// Sprint 5 — SUB-TASKS (frontend) layered on the multi-slot UI:
//   * A ticket can be split into named SubTasks; each slot may be PLACED
//     into a sub-task (manager create + PATCH re-placement) or left loose in
//     the "General" pool. With >=1 sub-task the slots render grouped under
//     their sub-task + a General group; with zero sub-tasks the editor
//     renders EXACTLY as before (the flat slot list).
//   * Managers (SA/CA/BM) add / edit / delete sub-tasks. Deleting a sub-task
//     SET_NULLs its slots back to General — it never deletes a slot or its
//     evidence (so the confirm copy says so).
//   * The per-ticket "auto-complete on sub-tasks" opt-in toggle is writable
//     ONLY by a provider admin (PA/SA); BM sees it disabled. The backend is
//     the hard gate (403 `auto_complete_flag_forbidden`).
//   * All sub-task mutation + sub_task placement + the flag are blocked on a
//     terminal ticket (the backend 400s); we hide/disable those controls and
//     keep a read-only display.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, ListChecks, Pencil, Plus, Trash2, X } from "lucide-react";

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
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { SlotStatusBadge } from "../../components/SlotStatusBadge";
import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/ToastProvider";
import { formatDateTime } from "../../lib/intl";

// Frontend mirror of the backend TERMINAL_TICKET_STATUSES. Sub-task CRUD,
// sub_task placement, and the auto-complete flag all 400 on these (matching
// the schedule control), so we hide/disable those controls — the read-only
// display stays. Existing plain-slot add/edit/remove keep their current
// (ungated) behaviour; the backend is their gate.
const TERMINAL_TICKET_STATUSES: ReadonlySet<TicketStatus> = new Set<TicketStatus>(
  ["APPROVED", "REJECTED", "CLOSED", "CONVERTED_TO_EXTRA_WORK"],
);

interface SlotFormState {
  start: string; // datetime-local value (local time, no tz)
  end: string;
  windowLabel: string;
  note: string;
  // "" = General / loose (no sub-task); otherwise String(subTaskId).
  subTask: string;
}
const EMPTY_FORM: SlotFormState = {
  start: "",
  end: "",
  windowLabel: "",
  note: "",
  subTask: "",
};

interface SubTaskFormState {
  title: string;
  description: string;
  ordering: string; // number input value; "" = let the backend default it
}
const EMPTY_SUBTASK_FORM: SubTaskFormState = {
  title: "",
  description: "",
  ordering: "",
};

function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
    d.getDate(),
  )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function localInputToIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

export function StaffSlotEditor({
  ticketId,
  onChanged,
  autoCompleteOnSubtasks,
  canSetAutoCompleteFlag,
  ticketStatus,
}: {
  ticketId: number;
  onChanged?: () => void;
  // Current value of the per-ticket auto-complete-on-sub-tasks opt-in
  // (read off the parent ticket detail). Mirrored into local state so the
  // toggle reflects the write immediately; never re-synced from the prop
  // (this toggle is the only writer of the flag on this page).
  autoCompleteOnSubtasks: boolean;
  // Writable only by a provider admin (PA/SA = isProviderAdmin). BM may
  // READ the flag but the backend 403s a write.
  canSetAutoCompleteFlag: boolean;
  ticketStatus: TicketStatus;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const { push } = useToast();

  const isTerminal = TERMINAL_TICKET_STATUSES.has(ticketStatus);

  const [slots, setSlots] = useState<TicketStaffAssignmentAdmin[]>([]);
  const [assignable, setAssignable] = useState<AssignableStaff[]>([]);
  const [subTasks, setSubTasks] = useState<SubTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [addUserId, setAddUserId] = useState("");
  const [addForm, setAddForm] = useState<SlotFormState>(EMPTY_FORM);

  const [editingSlotId, setEditingSlotId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<SlotFormState>(EMPTY_FORM);

  const removeRef = useRef<ConfirmDialogHandle>(null);
  const [removeTarget, setRemoveTarget] =
    useState<TicketStaffAssignmentAdmin | null>(null);

  // Sub-task CRUD surface.
  const [showAddSubTask, setShowAddSubTask] = useState(false);
  const [subTaskForm, setSubTaskForm] =
    useState<SubTaskFormState>(EMPTY_SUBTASK_FORM);
  const [editingSubTaskId, setEditingSubTaskId] = useState<number | null>(null);
  const [editSubTaskForm, setEditSubTaskForm] =
    useState<SubTaskFormState>(EMPTY_SUBTASK_FORM);
  const removeSubTaskRef = useRef<ConfirmDialogHandle>(null);
  const [removeSubTaskTarget, setRemoveSubTaskTarget] = useState<SubTask | null>(
    null,
  );

  // Auto-complete-on-sub-tasks opt-in. Seeded from the prop; updated from the
  // setAutoCompleteFlag response (no effect-body setState).
  const [autoFlag, setAutoFlag] = useState(autoCompleteOnSubtasks);
  const [flagBusy, setFlagBusy] = useState(false);
  const [flagError, setFlagError] = useState("");

  async function reload() {
    const [slotResp, staffResp, subTaskResp] = await Promise.all([
      listTicketStaffAssignments(ticketId),
      listAssignableStaff(ticketId),
      listSubTasks(ticketId),
    ]);
    setSlots(slotResp.results);
    setAssignable(staffResp);
    setSubTasks(subTaskResp);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [slotResp, staffResp, subTaskResp] = await Promise.all([
          listTicketStaffAssignments(ticketId),
          listAssignableStaff(ticketId),
          listSubTasks(ticketId),
        ]);
        if (cancelled) return;
        setSlots(slotResp.results);
        setAssignable(staffResp);
        setSubTasks(subTaskResp);
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

  // Multi-slot per staff — the same staff member may be added again as
  // another dated slot (Ahmet 09:00-11:00 AND 15:00-17:00), so we no
  // longer grey out already-assigned staff in the add dropdown.
  const candidates = assignable;

  // Slot grouping: with >=1 sub-task we render grouped; otherwise flat. A
  // slot whose sub_task points outside the list (shouldn't happen) falls
  // back into General so it is never hidden.
  const subTaskIds = new Set(subTasks.map((st) => st.id));
  const looseSlots = slots.filter(
    (s) => s.sub_task === null || !subTaskIds.has(s.sub_task),
  );

  function windowText(slot: TicketStaffAssignmentAdmin): string {
    const parts: string[] = [];
    if (slot.scheduled_start_at) {
      parts.push(
        slot.scheduled_end_at
          ? `${formatDateTime(slot.scheduled_start_at)} – ${formatDateTime(
              slot.scheduled_end_at,
            )}`
          : formatDateTime(slot.scheduled_start_at),
      );
    }
    if (slot.time_window_label) parts.push(slot.time_window_label);
    return parts.length > 0 ? parts.join(" · ") : t("editor.unscheduled");
  }

  function endBeforeStart(form: SlotFormState): boolean {
    const isoStart = localInputToIso(form.start);
    const isoEnd = localInputToIso(form.end);
    return Boolean(isoStart && isoEnd && isoEnd < isoStart);
  }

  function subTaskBadge(st: SubTask): {
    tone: "approved" | "progress" | "neutral";
    label: string;
  } {
    if (st.is_done) {
      return { tone: "approved", label: t("subtasks.status_done") };
    }
    if (st.staff_assignments.length > 0) {
      return { tone: "progress", label: t("subtasks.status_in_progress") };
    }
    return { tone: "neutral", label: t("subtasks.status_pending") };
  }

  async function handleAdd() {
    if (addUserId === "") return;
    if (endBeforeStart(addForm)) {
      setError(t("editor.end_before_start"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload: StaffSlotCreatePayload = {
        scheduled_start_at: localInputToIso(addForm.start),
        scheduled_end_at: localInputToIso(addForm.end),
        time_window_label: addForm.windowLabel.trim(),
        assignment_note: addForm.note.trim(),
      };
      // Only forward sub_task when placement is meaningful + allowed; on a
      // terminal ticket placement 400s, so we omit it (loose slot).
      if (subTasks.length > 0 && !isTerminal) {
        payload.sub_task = addForm.subTask === "" ? null : Number(addForm.subTask);
      }
      await addTicketStaffAssignment(ticketId, Number(addUserId), payload);
      setShowAdd(false);
      setAddUserId("");
      setAddForm(EMPTY_FORM);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("editor.toast_added") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  function startEdit(slot: TicketStaffAssignmentAdmin) {
    setEditingSlotId(slot.id);
    setEditForm({
      start: isoToLocalInput(slot.scheduled_start_at),
      end: isoToLocalInput(slot.scheduled_end_at),
      windowLabel: slot.time_window_label,
      note: slot.assignment_note,
      subTask: slot.sub_task === null ? "" : String(slot.sub_task),
    });
  }

  async function handleSaveEdit(slot: TicketStaffAssignmentAdmin) {
    if (endBeforeStart(editForm)) {
      setError(t("editor.end_before_start"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const patch: StaffSlotPatch = {
        scheduled_start_at: localInputToIso(editForm.start),
        scheduled_end_at: localInputToIso(editForm.end),
        time_window_label: editForm.windowLabel.trim(),
        assignment_note: editForm.note.trim(),
      };
      // Re-placement / detach. Omitted on a terminal ticket so we never
      // re-validate an existing placement the backend would now reject.
      if (subTasks.length > 0 && !isTerminal) {
        patch.sub_task = editForm.subTask === "" ? null : Number(editForm.subTask);
      }
      await updateStaffSlot(ticketId, slot.id, patch);
      setEditingSlotId(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("editor.toast_saved") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmRemove() {
    if (!removeTarget) return;
    setBusy(true);
    setError("");
    try {
      await removeTicketStaffAssignment(ticketId, removeTarget.id);
      removeRef.current?.close();
      setRemoveTarget(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("editor.toast_removed") });
    } catch (err) {
      setError(getApiError(err));
      removeRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  async function handleAddSubTask() {
    if (subTaskForm.title.trim() === "") return;
    setBusy(true);
    setError("");
    try {
      await createSubTask(ticketId, {
        title: subTaskForm.title.trim(),
        description: subTaskForm.description.trim(),
        ordering:
          subTaskForm.ordering.trim() === ""
            ? undefined
            : Number(subTaskForm.ordering),
      });
      setShowAddSubTask(false);
      setSubTaskForm(EMPTY_SUBTASK_FORM);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("subtasks.toast_added") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  function startEditSubTask(st: SubTask) {
    setEditingSubTaskId(st.id);
    setEditSubTaskForm({
      title: st.title,
      description: st.description,
      ordering: String(st.ordering),
    });
  }

  async function handleSaveEditSubTask(st: SubTask) {
    if (editSubTaskForm.title.trim() === "") return;
    setBusy(true);
    setError("");
    try {
      await updateSubTask(ticketId, st.id, {
        title: editSubTaskForm.title.trim(),
        description: editSubTaskForm.description.trim(),
        ordering:
          editSubTaskForm.ordering.trim() === ""
            ? undefined
            : Number(editSubTaskForm.ordering),
      });
      setEditingSubTaskId(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("subtasks.toast_saved") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmRemoveSubTask() {
    if (!removeSubTaskTarget) return;
    setBusy(true);
    setError("");
    try {
      await deleteSubTask(ticketId, removeSubTaskTarget.id);
      removeSubTaskRef.current?.close();
      setRemoveSubTaskTarget(null);
      await reload();
      onChanged?.();
      push({ variant: "success", title: t("subtasks.toast_removed") });
    } catch (err) {
      setError(getApiError(err));
      removeSubTaskRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleAutoComplete(next: boolean) {
    setFlagBusy(true);
    setFlagError("");
    try {
      const updated = await setAutoCompleteFlag(ticketId, next);
      setAutoFlag(updated.auto_complete_on_subtasks);
      onChanged?.();
    } catch (err) {
      setFlagError(getApiError(err));
    } finally {
      setFlagBusy(false);
    }
  }

  function slotName(slot: TicketStaffAssignmentAdmin): string {
    return slot.user_full_name?.trim() || slot.user_email;
  }

  // One slot row — reused by the flat list, each sub-task group, and the
  // General group. Closes over editing/handlers state.
  function renderSlot(slot: TicketStaffAssignmentAdmin) {
    return (
      <li
        key={slot.id}
        data-testid="staff-slot-card"
        data-staff-id={slot.user_id}
        data-slot-id={slot.id}
        style={{
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 10,
          marginBottom: 8,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <strong>{slotName(slot)}</strong>
          <SlotStatusBadge status={slot.slot_status} />
        </div>
        <div
          className="muted small"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 4,
          }}
        >
          <CalendarClock size={13} strokeWidth={2} />
          {windowText(slot)}
        </div>
        {slot.assignment_note && (
          <div className="small" style={{ marginTop: 4 }}>
            {slot.assignment_note}
          </div>
        )}
        {slot.slot_status === "COMPLETED" && (
          <div
            className="muted small"
            style={{ marginTop: 4 }}
            data-testid="staff-slot-completion"
          >
            {t("editor.completed_at", {
              when: formatDateTime(slot.completed_at),
            })}
            {slot.completion_note ? ` · ${slot.completion_note}` : ""}
          </div>
        )}
        {slot.slot_status === "UNABLE_TO_COMPLETE" &&
          slot.unable_to_complete_reason && (
            <div
              className="muted small"
              style={{ marginTop: 4 }}
              data-testid="staff-slot-unable"
            >
              {t("editor.unable_reason", {
                reason: slot.unable_to_complete_reason,
              })}
            </div>
          )}

        {editingSlotId === slot.id ? (
          <SlotFields
            form={editForm}
            setForm={setEditForm}
            disabled={busy}
            idPrefix={`edit-${slot.id}`}
            subTasks={subTasks}
            showSubTaskSelect={subTasks.length > 0 && !isTerminal}
          />
        ) : null}

        <div
          style={{
            display: "flex",
            gap: 8,
            marginTop: 8,
            flexWrap: "wrap",
          }}
        >
          {editingSlotId === slot.id ? (
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => handleSaveEdit(slot)}
                disabled={busy}
                data-testid="staff-slot-save"
              >
                {busy ? t("common:save") + "…" : t("common:save")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setEditingSlotId(null)}
                disabled={busy}
              >
                {t("common:cancel")}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => startEdit(slot)}
                disabled={busy}
                data-testid="staff-slot-edit"
              >
                <Pencil size={13} strokeWidth={2} />
                {t("editor.edit_slot")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setRemoveTarget(slot);
                  removeRef.current?.open();
                }}
                disabled={busy}
                data-testid="staff-slot-remove"
              >
                <Trash2 size={13} strokeWidth={2} />
                {t("editor.remove_slot")}
              </button>
            </>
          )}
        </div>
      </li>
    );
  }

  // One sub-task group — its header (title + computed status badge + manager
  // edit/delete) and the slots placed into it.
  function renderSubTaskGroup(st: SubTask) {
    const groupSlots = slots.filter((s) => s.sub_task === st.id);
    const badge = subTaskBadge(st);
    const editing = editingSubTaskId === st.id;
    return (
      <div
        key={st.id}
        data-testid="subtask-group"
        data-subtask-id={st.id}
        style={{
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 10,
          marginBottom: 8,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <div
            style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}
          >
            <ListChecks size={14} strokeWidth={2} />
            <strong style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              {st.title}
            </strong>
          </div>
          <StatusBadge
            variant="cell"
            status={{ kind: "generic", tone: badge.tone, label: badge.label }}
          />
        </div>
        {st.description && (
          <div className="muted small" style={{ marginTop: 4 }}>
            {st.description}
          </div>
        )}

        {editing ? (
          <SubTaskFields
            form={editSubTaskForm}
            setForm={setEditSubTaskForm}
            disabled={busy}
            idPrefix={`edit-subtask-${st.id}`}
          />
        ) : null}

        {!isTerminal && (
          <div
            style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}
          >
            {editing ? (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => handleSaveEditSubTask(st)}
                  disabled={busy || editSubTaskForm.title.trim() === ""}
                  data-testid="subtask-save"
                >
                  {busy ? t("common:save") + "…" : t("common:save")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setEditingSubTaskId(null)}
                  disabled={busy}
                >
                  {t("common:cancel")}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => startEditSubTask(st)}
                  disabled={busy}
                  data-testid="subtask-edit"
                >
                  <Pencil size={13} strokeWidth={2} />
                  {t("subtasks.edit")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setRemoveSubTaskTarget(st);
                    removeSubTaskRef.current?.open();
                  }}
                  disabled={busy}
                  data-testid="subtask-remove"
                >
                  <Trash2 size={13} strokeWidth={2} />
                  {t("subtasks.remove")}
                </button>
              </>
            )}
          </div>
        )}

        {groupSlots.length === 0 ? (
          <p className="muted small" style={{ margin: "8px 0 0" }}>
            {t("subtasks.empty_slots")}
          </p>
        ) : (
          <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0 }}>
            {groupSlots.map(renderSlot)}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div
      data-testid="staff-slot-editor"
      style={{
        marginTop: 14,
        paddingTop: 12,
        borderTop: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--text-faint)",
          }}
        >
          {t("editor.title")}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {!isTerminal && !showAddSubTask && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setShowAddSubTask(true);
                setError("");
              }}
              disabled={busy}
              data-testid="subtask-add-toggle"
            >
              <Plus size={14} strokeWidth={2.2} />
              {t("subtasks.add")}
            </button>
          )}
          {!showAdd && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setShowAdd(true);
                setError("");
              }}
              disabled={busy || candidates.length === 0}
              data-testid="staff-slot-add-toggle"
            >
              <Plus size={14} strokeWidth={2.2} />
              {t("editor.add_slot")}
            </button>
          )}
        </div>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {t("editor.desc")}
      </p>

      {/* Auto-complete-on-sub-tasks opt-in (PA/SA write; BM read-only). */}
      <div
        data-testid="subtask-auto-complete"
        style={{
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 10,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            cursor:
              canSetAutoCompleteFlag && !isTerminal && !flagBusy
                ? "pointer"
                : "default",
          }}
        >
          <input
            type="checkbox"
            checked={autoFlag}
            disabled={!canSetAutoCompleteFlag || isTerminal || flagBusy}
            onChange={(event) => handleToggleAutoComplete(event.target.checked)}
            data-testid="subtask-auto-complete-toggle"
          />
          <span className="small" style={{ fontWeight: 600 }}>
            {t("subtasks.auto_complete_label")}
          </span>
        </label>
        <p className="muted small" style={{ margin: 0 }}>
          {t("subtasks.auto_complete_desc")}
        </p>
        {!canSetAutoCompleteFlag && (
          <p className="muted small" style={{ margin: 0 }}>
            {t("subtasks.auto_complete_pa_only")}
          </p>
        )}
        {flagError && (
          <div className="alert-error" role="alert">
            {flagError}
          </div>
        )}
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginTop: 2 }}>
          {error}
        </div>
      )}

      {showAddSubTask && !isTerminal && (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 10,
          }}
          data-testid="subtask-add-form"
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <strong className="small">{t("subtasks.add")}</strong>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label={t("common:cancel")}
              onClick={() => {
                setShowAddSubTask(false);
                setSubTaskForm(EMPTY_SUBTASK_FORM);
                setError("");
              }}
            >
              <X size={14} strokeWidth={2.2} />
            </button>
          </div>
          <SubTaskFields
            form={subTaskForm}
            setForm={setSubTaskForm}
            disabled={busy}
            idPrefix="add-subtask"
          />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleAddSubTask}
              disabled={busy || subTaskForm.title.trim() === ""}
              data-testid="subtask-add-submit"
            >
              {busy ? t("subtasks.adding") : t("subtasks.add")}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="muted small">{t("editor.loading")}</p>
      ) : subTasks.length === 0 ? (
        slots.length === 0 ? (
          <p
            className="muted small"
            data-testid="staff-slot-empty"
            style={{ padding: "2px 0" }}
          >
            {t("editor.empty")}
          </p>
        ) : (
          <ul
            style={{ listStyle: "none", margin: 0, padding: 0 }}
            data-testid="staff-slot-list"
          >
            {slots.map(renderSlot)}
          </ul>
        )
      ) : (
        <div data-testid="subtask-groups">
          {subTasks.map(renderSubTaskGroup)}
          {looseSlots.length > 0 && (
            <div
              data-testid="subtask-general-group"
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: 10,
                marginBottom: 8,
              }}
            >
              <strong
                className="small"
                style={{ color: "var(--text-faint)" }}
              >
                {t("subtasks.general_group")}
              </strong>
              <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0 }}>
                {looseSlots.map(renderSlot)}
              </ul>
            </div>
          )}
        </div>
      )}

      {showAdd && (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: 10,
          }}
          data-testid="staff-slot-add-form"
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <strong className="small">{t("editor.add_slot")}</strong>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label={t("common:cancel")}
              onClick={() => {
                setShowAdd(false);
                setAddUserId("");
                setAddForm(EMPTY_FORM);
                setError("");
              }}
            >
              <X size={14} strokeWidth={2.2} />
            </button>
          </div>
          <div className="field" style={{ marginTop: 6 }}>
            <label className="field-label" htmlFor="staff-slot-add-user">
              {t("editor.field_assignee")}
            </label>
            <select
              id="staff-slot-add-user"
              className="field-select"
              value={addUserId}
              onChange={(event) => setAddUserId(event.target.value)}
              disabled={busy || candidates.length === 0}
              data-testid="staff-slot-add-user"
            >
              <option value="">
                {candidates.length === 0
                  ? t("editor.no_eligible")
                  : t("editor.select_assignee")}
              </option>
              {candidates.map((staff) => (
                <option key={staff.id} value={String(staff.id)}>
                  {staff.full_name || staff.email}
                </option>
              ))}
            </select>
          </div>
          <SlotFields
            form={addForm}
            setForm={setAddForm}
            disabled={busy}
            idPrefix="add"
            subTasks={subTasks}
            showSubTaskSelect={subTasks.length > 0 && !isTerminal}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleAdd}
              disabled={busy || addUserId === ""}
              data-testid="staff-slot-add-submit"
            >
              {busy ? t("editor.adding") : t("editor.add_slot")}
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        ref={removeRef}
        title={t("editor.remove_dialog_title", {
          name: removeTarget ? slotName(removeTarget) : "",
        })}
        body={t("editor.remove_dialog_body")}
        confirmLabel={t("editor.remove_slot")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={busy}
        destructive
      />

      <ConfirmDialog
        ref={removeSubTaskRef}
        title={t("subtasks.remove_dialog_title", {
          title: removeSubTaskTarget ? removeSubTaskTarget.title : "",
        })}
        body={t("subtasks.remove_dialog_body")}
        confirmLabel={t("subtasks.remove")}
        onConfirm={handleConfirmRemoveSubTask}
        onCancel={() => setRemoveSubTaskTarget(null)}
        busy={busy}
        destructive
      />
    </div>
  );
}

// Shared schedule/window/note inputs for the add + edit slot forms, plus the
// Sprint 5 sub-task placement selector. Kept as a local presentational helper
// (not exported) so the file exposes one component to react-refresh.
function SlotFields({
  form,
  setForm,
  disabled,
  idPrefix,
  subTasks,
  showSubTaskSelect,
}: {
  form: SlotFormState;
  setForm: (next: SlotFormState) => void;
  disabled: boolean;
  idPrefix: string;
  subTasks: SubTask[];
  showSubTaskSelect: boolean;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <div style={{ marginTop: 6 }}>
      {showSubTaskSelect && (
        <div className="field">
          <label className="field-label" htmlFor={`${idPrefix}-subtask`}>
            {t("subtasks.field_subtask")}
          </label>
          <select
            id={`${idPrefix}-subtask`}
            className="field-select"
            value={form.subTask}
            onChange={(event) =>
              setForm({ ...form, subTask: event.target.value })
            }
            disabled={disabled}
            data-testid={`${idPrefix}-subtask-select`}
          >
            <option value="">{t("subtasks.general_group")}</option>
            {subTasks.map((st) => (
              <option key={st.id} value={String(st.id)}>
                {st.title}
              </option>
            ))}
          </select>
        </div>
      )}
      {/* Single column: this editor lives in the narrow ticket-detail
          sidebar, where two datetime-local inputs side-by-side cannot
          shrink (grid min-width:auto) and the End field overflowed the
          card. Stacking keeps both inputs full-width within the card. */}
      <div className="form-2col" style={{ gridTemplateColumns: "1fr" }}>
        <div className="field">
          <label className="field-label" htmlFor={`${idPrefix}-start`}>
            {t("editor.field_start")}
          </label>
          <input
            id={`${idPrefix}-start`}
            className="field-input"
            type="datetime-local"
            value={form.start}
            onChange={(event) =>
              setForm({ ...form, start: event.target.value })
            }
            disabled={disabled}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={`${idPrefix}-end`}>
            {t("editor.field_end")}
          </label>
          <input
            id={`${idPrefix}-end`}
            className="field-input"
            type="datetime-local"
            value={form.end}
            onChange={(event) => setForm({ ...form, end: event.target.value })}
            disabled={disabled}
          />
        </div>
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-window`}>
          {t("editor.field_window")}
        </label>
        <input
          id={`${idPrefix}-window`}
          className="field-input"
          type="text"
          maxLength={64}
          placeholder={t("editor.field_window_placeholder")}
          value={form.windowLabel}
          onChange={(event) =>
            setForm({ ...form, windowLabel: event.target.value })
          }
          disabled={disabled}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-note`}>
          {t("editor.field_note")}
        </label>
        <textarea
          id={`${idPrefix}-note`}
          className="field-textarea"
          placeholder={t("editor.field_note_placeholder")}
          value={form.note}
          onChange={(event) => setForm({ ...form, note: event.target.value })}
          disabled={disabled}
        />
      </div>
    </div>
  );
}

// Title / description / display-order inputs for the add + edit sub-task
// forms. Local presentational helper (not exported).
function SubTaskFields({
  form,
  setForm,
  disabled,
  idPrefix,
}: {
  form: SubTaskFormState;
  setForm: (next: SubTaskFormState) => void;
  disabled: boolean;
  idPrefix: string;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <div style={{ marginTop: 6 }}>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-title`}>
          {t("subtasks.field_title")}
        </label>
        <input
          id={`${idPrefix}-title`}
          className="field-input"
          type="text"
          maxLength={200}
          placeholder={t("subtasks.field_title_placeholder")}
          value={form.title}
          onChange={(event) => setForm({ ...form, title: event.target.value })}
          disabled={disabled}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-description`}>
          {t("subtasks.field_description")}
        </label>
        <textarea
          id={`${idPrefix}-description`}
          className="field-textarea"
          placeholder={t("subtasks.field_description_placeholder")}
          value={form.description}
          onChange={(event) =>
            setForm({ ...form, description: event.target.value })
          }
          disabled={disabled}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-ordering`}>
          {t("subtasks.field_ordering")}
        </label>
        <input
          id={`${idPrefix}-ordering`}
          className="field-input"
          type="number"
          value={form.ordering}
          onChange={(event) =>
            setForm({ ...form, ordering: event.target.value })
          }
          disabled={disabled}
        />
      </div>
    </div>
  );
}
