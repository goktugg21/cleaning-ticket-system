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
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, Pencil, Plus, Trash2, X } from "lucide-react";

import {
  addTicketStaffAssignment,
  listAssignableStaff,
  listTicketStaffAssignments,
  removeTicketStaffAssignment,
  updateStaffSlot,
} from "../../api/admin";
import type {
  AssignableStaff,
  TicketStaffAssignmentAdmin,
} from "../../api/admin";
import { getApiError } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { SlotStatusBadge } from "../../components/SlotStatusBadge";
import { useToast } from "../../components/ToastProvider";
import { formatDateTime } from "../../lib/intl";

interface SlotFormState {
  start: string; // datetime-local value (local time, no tz)
  end: string;
  windowLabel: string;
  note: string;
}
const EMPTY_FORM: SlotFormState = {
  start: "",
  end: "",
  windowLabel: "",
  note: "",
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
}: {
  ticketId: number;
  onChanged?: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const { push } = useToast();

  const [slots, setSlots] = useState<TicketStaffAssignmentAdmin[]>([]);
  const [assignable, setAssignable] = useState<AssignableStaff[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [addUserId, setAddUserId] = useState("");
  const [addForm, setAddForm] = useState<SlotFormState>(EMPTY_FORM);

  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<SlotFormState>(EMPTY_FORM);

  const removeRef = useRef<ConfirmDialogHandle>(null);
  const [removeTarget, setRemoveTarget] =
    useState<TicketStaffAssignmentAdmin | null>(null);

  async function reload() {
    const [slotResp, staffResp] = await Promise.all([
      listTicketStaffAssignments(ticketId),
      listAssignableStaff(ticketId),
    ]);
    setSlots(slotResp.results);
    setAssignable(staffResp);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [slotResp, staffResp] = await Promise.all([
          listTicketStaffAssignments(ticketId),
          listAssignableStaff(ticketId),
        ]);
        if (cancelled) return;
        setSlots(slotResp.results);
        setAssignable(staffResp);
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

  const assignedIds = useMemo(
    () => new Set(slots.map((s) => s.user_id)),
    [slots],
  );
  const candidates = useMemo(
    () => assignable.filter((a) => !assignedIds.has(a.id)),
    [assignable, assignedIds],
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

  async function handleAdd() {
    if (addUserId === "") return;
    if (endBeforeStart(addForm)) {
      setError(t("editor.end_before_start"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await addTicketStaffAssignment(ticketId, Number(addUserId), {
        scheduled_start_at: localInputToIso(addForm.start),
        scheduled_end_at: localInputToIso(addForm.end),
        time_window_label: addForm.windowLabel.trim(),
        assignment_note: addForm.note.trim(),
      });
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
    setEditingUserId(slot.user_id);
    setEditForm({
      start: isoToLocalInput(slot.scheduled_start_at),
      end: isoToLocalInput(slot.scheduled_end_at),
      windowLabel: slot.time_window_label,
      note: slot.assignment_note,
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
      await updateStaffSlot(ticketId, slot.user_id, {
        scheduled_start_at: localInputToIso(editForm.start),
        scheduled_end_at: localInputToIso(editForm.end),
        time_window_label: editForm.windowLabel.trim(),
        assignment_note: editForm.note.trim(),
      });
      setEditingUserId(null);
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
      await removeTicketStaffAssignment(ticketId, removeTarget.user_id);
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

  function slotName(slot: TicketStaffAssignmentAdmin): string {
    return slot.user_full_name?.trim() || slot.user_email;
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
      <p className="muted small" style={{ margin: 0 }}>
        {t("editor.desc")}
      </p>

      {error && (
        <div className="alert-error" role="alert" style={{ marginTop: 2 }}>
          {error}
        </div>
      )}

      {loading ? (
        <p className="muted small">{t("editor.loading")}</p>
      ) : slots.length === 0 ? (
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
          {slots.map((slot) => (
            <li
              key={slot.id}
              data-testid="staff-slot-card"
              data-staff-id={slot.user_id}
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

              {editingUserId === slot.user_id ? (
                <SlotFields
                  form={editForm}
                  setForm={setEditForm}
                  disabled={busy}
                  idPrefix={`edit-${slot.user_id}`}
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
                {editingUserId === slot.user_id ? (
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
                      onClick={() => setEditingUserId(null)}
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
          ))}
        </ul>
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
    </div>
  );
}

// Shared schedule/window/note inputs for the add + edit forms. Kept as a
// local presentational helper (not exported) so the file exposes one
// component to react-refresh.
function SlotFields({
  form,
  setForm,
  disabled,
  idPrefix,
}: {
  form: SlotFormState;
  setForm: (next: SlotFormState) => void;
  disabled: boolean;
  idPrefix: string;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <div style={{ marginTop: 6 }}>
      <div className="form-2col">
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
