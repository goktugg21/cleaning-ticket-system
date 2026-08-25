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
//   * It does not own the picker's rule. W26.3 (c): parts divide the
//     people ALREADY on the job, so each part offers the ticket's
//     base-slot holders (`onJob`) MINUS whoever is on that part already
//     -- so "offerable" and "acceptable" cannot disagree. Note this is
//     the opposite set to `assignable-staff`, which the modal used to
//     take and which lists people NOT on the job: offering those was
//     what made every per-part assign fail. When picker and server
//     disagree anyway (a stale list), the server's 400 is shown INLINE
//     on the row that caused it, not as a toast over a closed modal.
//
//   * It does not nest a native <dialog>. Removing a part confirms in the
//     row itself. A `ConfirmDialog` inside a conditionally-mounted overlay
//     is the CLAUDE.md §3 trap from both directions: this overlay closes
//     itself on Escape, and Escape also closes a native dialog, so one
//     key would unmount an open dialog and leave the page inert
//     (Sprint 118).
//
// W26.3 -- LAYOUT. The rows were a `.assign-table`, and that class is
// tuned for the ~320px RIGHT RAIL: its actions cell is `width: 1%`,
// right-aligned, and stacks every button full-width one under the next.
// Correct in the rail; inside this wide dialog it squeezed a select and
// three buttons into a narrow right-hand column -- the "sagi sikismis"
// the owner reported. So the parts list is no longer a table. Each part
// is ONE row that lays its name, state, people and actions out inline
// with room to breathe, under `.parts-*` classes that belong to this
// surface alone and inherit none of the rail's sizing.
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
import type { SubTask } from "../../api/admin";
import { getApiError } from "../../api/client";
import { BoundedList } from "../../components/BoundedList";
import { StatusBadge } from "../../components/StatusBadge";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/ToastProvider";

/** One person already on the job, as the part picker needs them. */
export type JobMember = { id: number; name: string };

export function SubTasksModal({
  ticketId,
  parts,
  onJob,
  isTerminal,
  canSetAutoCompleteFlag,
  autoCompleteOnSubtasks,
  onChanged,
  onClose,
}: {
  ticketId: number;
  parts: SubTask[];
  /** W26.3 (c) -- the people ALREADY on this job (base-slot holders).
   *  Parts divide them, so this is the opposite set to the ticket-level
   *  picker's `assignable-staff`, which lists who is NOT on the job yet.
   *  Deduped by the caller. */
  onJob: JobMember[];
  isTerminal: boolean;
  /** Provider admin (PA/SA) only; the backend is the hard gate (403). */
  canSetAutoCompleteFlag: boolean;
  autoCompleteOnSubtasks: boolean;
  /** Reload the parent's parts + slots after a write. */
  onChanged: () => Promise<void>;
  onClose: () => void;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);
  const { push } = useToast();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [newTitle, setNewTitle] = useState("");
  const [renamingPartId, setRenamingPartId] = useState<number | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [confirmRemoveId, setConfirmRemoveId] = useState<number | null>(null);
  const [pickByPart, setPickByPart] = useState<Record<number, number>>({});
  // W26.3 -- a refusal belongs to the ROW that caused it. Keyed by part
  // id so assigning on one part never blanks another row's message.
  const [errorByPart, setErrorByPart] = useState<Record<number, string>>({});

  const [autoFlag, setAutoFlag] = useState(autoCompleteOnSubtasks);
  const [flagBusy, setFlagBusy] = useState(false);

  // TWO effects, not one. Focus belongs to opening the modal and must
  // happen once; the Escape listener has to see the CURRENT `busy`, so it
  // re-binds whenever that changes. Folded together, either the listener
  // reads a stale `busy` or every write steals focus back to the card --
  // and holding `busy` in a ref instead means writing a ref during render,
  // which is its own rule.
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    cardRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Guarded on `busy` for the same reason the close button is disabled
      // while one: Escape would unmount this overlay with a write still in
      // flight, and the operator would be left looking at a list that had
      // not been reloaded yet.
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, busy]);

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

  async function handleRemovePart(part: SubTask) {
    setBusy(true);
    setError("");
    try {
      await deleteSubTask(ticketId, part.id);
      setConfirmRemoveId(null);
      await onChanged();
      push({
        variant: "success",
        title: t("parts.toast_removed", { part: part.title }),
      });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // W26.3 -- who this part can still be given to: the people on the job,
  // minus the ones already on THIS part. Same-part duplicates are what
  // the server refuses (400 `staff_already_assigned`), so the picker
  // simply does not offer them; the inline error below is for the case
  // where this list is stale.
  function offerableFor(part: SubTask): JobMember[] {
    const taken = new Set(
      part.staff_assignments.map((slot) => slot.user_id),
    );
    return onJob.filter((person) => !taken.has(person.id));
  }

  // The per-part assign uses the SAME slot-create path as every other
  // assign on this ticket -- `POST /staff-assignments/` with `sub_task`
  // set. So the rule is the server's, said once, and its refusal is
  // rendered on this row rather than thrown at a toast the operator
  // reads after the list has moved.
  async function handleAssignToPart(part: SubTask) {
    const userId = pickByPart[part.id];
    if (!userId) return;
    setBusy(true);
    setError("");
    setErrorByPart((current) => {
      const next = { ...current };
      delete next[part.id];
      return next;
    });
    try {
      await addTicketStaffAssignment(ticketId, userId, { sub_task: part.id });
      setPickByPart((current) => {
        const next = { ...current };
        delete next[part.id];
        return next;
      });
      await onChanged();
    } catch (err) {
      const code = (err as { response?: { data?: { code?: string } } })
        ?.response?.data?.code;
      // Both codes are expected here and mean different things, so they
      // get different sentences: `staff_not_on_job` is a stale picker
      // offering someone who has since left the job, and the fix is the
      // ticket-level assign; `staff_already_assigned` at part level can
      // only mean this same person is already on this same part.
      const message =
        code === "staff_not_on_job"
          ? t("parts.error_not_on_job")
          : code === "staff_already_assigned"
            ? t("parts.error_same_part")
            : getApiError(err);
      setErrorByPart((current) => ({ ...current, [part.id]: message }));
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
            className="parts-list"
          >
            {parts.map((part) => {
              const badge = partBadge(part);
              const renaming = renamingPartId === part.id;
              const confirming = confirmRemoveId === part.id;
              const offerable = offerableFor(part);
              const rowError = errorByPart[part.id];
              return (
                <div
                  className="parts-row"
                  key={part.id}
                  data-testid="ticket-part-row"
                  data-part-id={part.id}
                >
                  <div className="parts-row-head">
                    <div className="parts-row-name" data-testid="ticket-part-name">
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
                    </div>
                    <div data-testid="ticket-part-state">
                      <StatusBadge
                        variant="cell"
                        status={{
                          kind: "generic",
                          tone: badge.tone,
                          label: badge.label,
                        }}
                      />
                    </div>
                    <div
                      className="parts-chip-row"
                      data-testid="ticket-part-people"
                    >
                      {part.staff_assignments.length === 0 ? (
                        <span
                          className="muted small"
                          data-testid="ticket-part-nobody"
                        >
                          {t("parts.none_assigned")}
                        </span>
                      ) : (
                        part.staff_assignments.map((slot) => (
                          <span
                            key={slot.id}
                            className="parts-chip"
                            data-testid="ticket-part-person"
                            data-user-id={slot.user_id}
                          >
                            {slot.user_full_name?.trim() || slot.user_email}
                          </span>
                        ))
                      )}
                    </div>
                  </div>

                  {!isTerminal && (
                    <div className="parts-row-actions">
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
                            className="field-input parts-assign-select"
                            value={pickByPart[part.id] ?? ""}
                            disabled={busy || offerable.length === 0}
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
                              {/* W26.3 -- the empty picker has TWO
                                  causes and they need different
                                  sentences: nobody is on the job at
                                  all, or everyone on it is already on
                                  this part. The first tells the
                                  operator to go and assign someone to
                                  the ticket; the second says there is
                                  nothing left to do here. */}
                              {onJob.length === 0
                                ? t("parts.assign_nobody_on_job")
                                : offerable.length === 0
                                  ? t("parts.assign_everyone_here")
                                  : t("parts.assign_choose")}
                            </option>
                            {offerable.map((person) => (
                              <option key={person.id} value={person.id}>
                                {person.name}
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
                            <X size={13} strokeWidth={2.5} aria-hidden="true" />
                            {t("parts.remove")}
                          </button>
                        </>
                      )}
                    </div>
                  )}

                  {rowError && (
                    <p
                      className="parts-row-error"
                      role="alert"
                      data-testid="ticket-part-error"
                    >
                      {rowError}
                    </p>
                  )}
                </div>
              );
            })}
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
