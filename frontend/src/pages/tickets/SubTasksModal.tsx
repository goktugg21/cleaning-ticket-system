// W26.2 — PARTS OF THIS JOB: one door, one owner.
//
// Before this file, "parts" were three fragments in two places. The parts
// table lived inline in the assignment card and appeared only once parts
// existed; the auto-complete switch sat under it; and the one control that
// CREATED a part had been removed with the assign dialog's part picker
// (W19), which left `createSubTask` in the API client with no caller at
// all. A manager could rename and delete parts they had no way to make.
//
// So parts move behind ONE secondary button next to the assign action, and
// everything about them happens here: the list with the people on each
// part, the input that adds one, the per-part assign control, and the
// auto-complete switch. Nothing about parts is on the ticket page itself.
//
// Two things this modal deliberately does NOT do:
//
//   * It does not own the picker's rule. The people it offers are the
//     ticket's `assignable-staff`, which already omits anyone holding a
//     slot here (W26, one person one slot) -- so "offerable" and
//     "acceptable" cannot disagree. When they do anyway (a stale list),
//     the server's 400 `staff_already_assigned` is shown INLINE, next to
//     the control that caused it, not as a toast over a closed modal.
//
//   * It does not nest a native <dialog>. Removing a part confirms in the
//     row itself. A `ConfirmDialog` inside a conditionally-mounted overlay
//     is the CLAUDE.md §3 trap from both directions: this overlay closes
//     itself on Escape, and Escape also closes a native dialog, so one
//     key would unmount an open dialog and leave the page inert
//     (Sprint 118).
//
// A NON-native overlay, conditionally mounted, like `AssignStaffDialog`.
import { useEffect, useRef, useState } from "react";
import { Pencil, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  addTicketStaffAssignment,
  createSubTask,
  deleteSubTask,
  setAutoCompleteFlag,
  updateSubTask,
} from "../../api/admin";
import type { AssignableStaff, SubTask } from "../../api/admin";
import { getApiError } from "../../api/client";
import { BoundedList } from "../../components/BoundedList";
import { StatusBadge } from "../../components/StatusBadge";
import { Toggle } from "../../components/Toggle";

export function SubTasksModal({
  ticketId,
  parts,
  candidates,
  isTerminal,
  canSetAutoCompleteFlag,
  autoCompleteOnSubtasks,
  onChanged,
  onClose,
}: {
  ticketId: number;
  parts: SubTask[];
  /** The ticket's assignable staff -- already excludes anyone who holds a
   *  slot on this ticket (W26). */
  candidates: AssignableStaff[];
  isTerminal: boolean;
  /** Provider admin (PA/SA) only; the backend is the hard gate (403). */
  canSetAutoCompleteFlag: boolean;
  autoCompleteOnSubtasks: boolean;
  /** Reload the parent's parts + slots after a write. */
  onChanged: () => Promise<void>;
  onClose: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [newTitle, setNewTitle] = useState("");
  const [renamingPartId, setRenamingPartId] = useState<number | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [confirmRemoveId, setConfirmRemoveId] = useState<number | null>(null);
  const [pickByPart, setPickByPart] = useState<Record<number, number>>({});

  const [autoFlag, setAutoFlag] = useState(autoCompleteOnSubtasks);
  const [flagBusy, setFlagBusy] = useState(false);

  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    cardRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

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

  async function handleAddPart() {
    const title = newTitle.trim();
    if (title === "") return;
    setBusy(true);
    setError("");
    try {
      await createSubTask(ticketId, { title });
      setNewTitle("");
      await onChanged();
    } catch (err) {
      setError(getApiError(err));
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
      await onChanged();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRemovePart(part: SubTask) {
    setBusy(true);
    setError("");
    try {
      await deleteSubTask(ticketId, part.id);
      setConfirmRemoveId(null);
      await onChanged();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // The per-part assign uses the SAME slot-create path as every other
  // assign on this ticket -- `POST /staff-assignments/` with `sub_task`
  // set. So the one-person-one-slot rule is the server's, said once:
  // a 400 `staff_already_assigned` is rendered here, in the modal, rather
  // than thrown at a toast the operator reads after the list has moved.
  async function handleAssignToPart(part: SubTask) {
    const userId = pickByPart[part.id];
    if (!userId) return;
    setBusy(true);
    setError("");
    try {
      await addTicketStaffAssignment(ticketId, userId, { sub_task: part.id });
      setPickByPart((current) => {
        const next = { ...current };
        delete next[part.id];
        return next;
      });
      await onChanged();
    } catch (err) {
      setError(getApiError(err));
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
      await onChanged();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setFlagBusy(false);
    }
  }

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("parts.title")}
      data-testid="ticket-parts-modal"
    >
      <div ref={cardRef} tabIndex={-1} className="card ew-plan-dialog">
        <h3 className="section-title ew-plan-dialog-title">
          {t("parts.title")}
        </h3>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="ticket-parts-modal-error"
          >
            {error}
          </div>
        )}

        {parts.length === 0 ? (
          <p className="muted small" data-testid="ticket-parts-modal-empty">
            {t("parts.empty")}
          </p>
        ) : (
          <BoundedList
            size="md"
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
                  <th>{t("parts.col_people")}</th>
                  {!isTerminal && <th className="assign-table-actions" />}
                </tr>
              </thead>
              <tbody>
                {parts.map((part) => {
                  const badge = partBadge(part);
                  const renaming = renamingPartId === part.id;
                  const confirming = confirmRemoveId === part.id;
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
                      <td data-testid="ticket-part-people">
                        <StatusBadge
                          variant="cell"
                          status={{
                            kind: "generic",
                            tone: badge.tone,
                            label: badge.label,
                          }}
                        />
                        {part.staff_assignments.length === 0 ? (
                          <span
                            className="assign-table-note"
                            data-testid="ticket-part-nobody"
                          >
                            {t("parts.none_assigned")}
                          </span>
                        ) : (
                          part.staff_assignments.map((slot) => (
                            <span
                              key={slot.id}
                              className="assign-table-note"
                              data-testid="ticket-part-person"
                              data-user-id={slot.user_id}
                            >
                              {slot.user_full_name?.trim() || slot.user_email}
                            </span>
                          ))
                        )}
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
                          ) : confirming ? (
                            <>
                              <button
                                type="button"
                                className="btn btn-danger btn-sm"
                                onClick={() => void handleRemovePart(part)}
                                disabled={busy}
                                data-testid="ticket-part-remove-confirm"
                              >
                                {t("parts.confirm_yes")}
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => setConfirmRemoveId(null)}
                                disabled={busy}
                                data-testid="ticket-part-remove-cancel"
                              >
                                {t("common:cancel")}
                              </button>
                            </>
                          ) : (
                            <>
                              <select
                                className="field-input"
                                value={pickByPart[part.id] ?? ""}
                                disabled={busy || candidates.length === 0}
                                aria-label={t("parts.assign_label")}
                                onChange={(event) =>
                                  setPickByPart((current) => ({
                                    ...current,
                                    [part.id]: Number(event.target.value),
                                  }))
                                }
                                data-testid="ticket-part-assign-select"
                              >
                                <option value="">
                                  {candidates.length === 0
                                    ? t("editor.no_eligible")
                                    : t("parts.assign_choose")}
                                </option>
                                {candidates.map((staff) => (
                                  <option key={staff.id} value={staff.id}>
                                    {staff.full_name?.trim() || staff.email}
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() => void handleAssignToPart(part)}
                                disabled={busy || !pickByPart[part.id]}
                                data-testid="ticket-part-assign"
                              >
                                {t("parts.assign_button")}
                              </button>
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
                                onClick={() => setConfirmRemoveId(part.id)}
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
        )}

        {!isTerminal && (
          <div className="field">
            <label className="field-label" htmlFor="ticket-part-add-input">
              {t("parts.add_label")}
            </label>
            <div className="assign-actions">
              <input
                id="ticket-part-add-input"
                className="field-input"
                type="text"
                maxLength={200}
                placeholder={t("parts.add_placeholder")}
                value={newTitle}
                disabled={busy}
                onChange={(event) => setNewTitle(event.target.value)}
                data-testid="ticket-part-add-input"
              />
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void handleAddPart()}
                disabled={busy || newTitle.trim() === ""}
                data-testid="ticket-part-add"
              >
                {t("parts.add_button")}
              </button>
            </div>
          </div>
        )}

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

        <div className="assign-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            disabled={busy}
            data-testid="ticket-parts-modal-close"
          >
            {t("parts.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
