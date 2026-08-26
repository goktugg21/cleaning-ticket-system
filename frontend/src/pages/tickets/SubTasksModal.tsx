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
import { CalendarDays, Pencil, X } from "lucide-react";
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
import { formatDate } from "../../lib/intl";
import { formatPlannedWindow } from "../../lib/plannedWindow";

/** A "YYYY-MM-DD" in the viewer's locale; explicit midnight so a bare
 *  date is not read as UTC and printed a day early. */
function formatDay(iso: string): string {
  return formatDate(`${iso}T00:00:00`);
}

/** W-LATE §3a — the server's refusal, with the FIELD it belongs to.
 *  `part_windows.refusal` answers `{detail, code, field}`; anything
 *  else is a plain error for the modal's own banner. */
function windowRefusal(err: unknown): { field: string; message: string } | null {
  const data = (err as { response?: { data?: { field?: string; detail?: string } } })
    ?.response?.data;
  if (data && typeof data.field === "string" && typeof data.detail === "string") {
    return { field: data.field, message: data.detail };
  }
  return null;
}

/** The window as one line: "10 aug – 12 aug · 08:00-10:00". */
function windowText(
  part: Pick<SubTask, "planned_start_date" | "planned_end_date" | "time_window_label">,
  empty: string,
): string {
  const days = formatPlannedWindow(
    part.planned_start_date,
    part.planned_end_date,
    formatDay,
    { empty: "", endOnly: (end) => end },
  );
  const bits = [days, part.time_window_label].filter(Boolean);
  return bits.length > 0 ? bits.join(" · ") : empty;
}

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
  // W26.4 -- MANY people per part, one Assign. Keyed by part id, so an
  // open picker on one row keeps its ticks while another row is worked.
  const [pickByPart, setPickByPart] = useState<Record<number, number[]>>({});
  // Which row currently has its picker open. Only one at a time: the
  // rows are the same width, and two open pickers push the actions of
  // every row between them off the screen the W26.3 layout just fixed.
  const [pickerPartId, setPickerPartId] = useState<number | null>(null);
  // W26.3 -- a refusal belongs to the ROW that caused it. Keyed by part
  // id so assigning on one part never blanks another row's message.
  const [errorByPart, setErrorByPart] = useState<Record<number, string>>({});
  // W-LATE §3a -- the window editor: which row has it open, its draft,
  // and the refusal AT THE FIELD (the server names the field).
  const [windowPartId, setWindowPartId] = useState<number | null>(null);
  const [windowDraft, setWindowDraft] = useState({ start: "", end: "", label: "" });
  const [windowError, setWindowError] = useState<{ field: string; message: string } | null>(null);
  // The add form's optional window, and its own field-level refusal.
  const [newStart, setNewStart] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [addError, setAddError] = useState<{ field: string; message: string } | null>(null);

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
    setAddError(null);
    try {
      await createSubTask(ticketId, {
        title,
        ...(newStart ? { planned_start_date: newStart } : {}),
        ...(newEnd ? { planned_end_date: newEnd } : {}),
        ...(newLabel.trim() ? { time_window_label: newLabel.trim() } : {}),
      });
      setNewTitle("");
      setNewStart("");
      setNewEnd("");
      setNewLabel("");
      await onChanged();
    } catch (err) {
      // W-LATE §3a -- a window refusal lands under the field it names;
      // anything else keeps the modal's banner.
      const refusal = windowRefusal(err);
      if (refusal) setAddError(refusal);
      else setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // W-LATE §3a -- open the window editor seeded with what the part has.
  function openWindowEditor(part: SubTask) {
    setWindowPartId(part.id);
    setWindowError(null);
    setWindowDraft({
      start: part.planned_start_date ?? "",
      end: part.planned_end_date ?? "",
      label: part.time_window_label ?? "",
    });
  }

  async function handleSaveWindow(part: SubTask) {
    setBusy(true);
    setError("");
    setWindowError(null);
    try {
      await updateSubTask(ticketId, part.id, {
        planned_start_date: windowDraft.start || null,
        planned_end_date: windowDraft.end || null,
        time_window_label: windowDraft.label.trim(),
      });
      setWindowPartId(null);
      await onChanged();
      push({
        variant: "success",
        title: t("parts.toast_window_saved", { part: part.title }),
      });
    } catch (err) {
      const refusal = windowRefusal(err);
      if (refusal) setWindowError(refusal);
      else setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  /** W-LATE §3b -- the part's state, as the chip vocabulary the Work
   *  Plan already uses: done = strikethrough, last day = orange, missed
   *  = red with "niet gedaan op <end>". */
  function stateChip(part: SubTask) {
    const state = part.window_state ?? "NONE";
    if (state === "NONE" || state === "OPEN") return null;
    const cls =
      state === "DONE"
        ? "parts-chip parts-chip-done"
        : state === "LAST_DAY"
          ? "parts-chip parts-chip-last-day"
          : "parts-chip parts-chip-missed";
    const end = part.planned_end_date ?? part.planned_start_date;
    const label =
      state === "DONE"
        ? t("subtasks.status_done")
        : state === "LAST_DAY"
          ? t("parts.state_last_day")
          : end
            ? t("parts.missed_on", { date: formatDay(end) })
            : t("parts.state_missed");
    return (
      <span className={cls} data-testid="ticket-part-window-state" data-state={state}>
        {label}
      </span>
    );
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
  // simply does not offer them; the inline refusal below is for the case
  // where this list is stale.
  function offerableFor(part: SubTask): JobMember[] {
    const taken = new Set(
      part.staff_assignments.map((slot) => slot.user_id),
    );
    return onJob.filter((person) => !taken.has(person.id));
  }

  function togglePick(partId: number, userId: number) {
    setPickByPart((current) => {
      const chosen = current[partId] ?? [];
      return {
        ...current,
        [partId]: chosen.includes(userId)
          ? chosen.filter((id) => id !== userId)
          : [...chosen, userId],
      };
    });
  }

  function closePicker(partId: number) {
    setPickerPartId(null);
    setPickByPart((current) => {
      const next = { ...current };
      delete next[partId];
      return next;
    });
  }

  // W26.4 -- BULK ASSIGN, still one rule and one door.
  //
  // Several people, ONE Assign action, but one request PER PERSON
  // through the SAME chokepoint the single assign used
  // (`POST /staff-assignments/` with `sub_task` set). There is no bulk
  // endpoint and deliberately so: a batch would need its own copy of
  // the (user, sub_task) rule to say which member of the batch it
  // refused, and a second copy of that rule is exactly what W26.3 spent
  // a sprint removing.
  //
  // A refusal is NOT skipped silently. The picker already omits anyone
  // on this part, so a same-part duplicate can only mean the list this
  // browser is holding is out of date -- and a silent skip would leave
  // the operator believing they had just assigned someone they had not.
  // So the ones that landed are announced, and the ones refused are
  // named on the row with the reason.
  async function handleAssignToPart(part: SubTask) {
    const chosen = pickByPart[part.id] ?? [];
    if (chosen.length === 0) return;
    setBusy(true);
    setError("");
    setErrorByPart((current) => {
      const next = { ...current };
      delete next[part.id];
      return next;
    });
    const nameOf = (id: number) =>
      onJob.find((person) => person.id === id)?.name ?? String(id);
    const done: string[] = [];
    const duplicate: string[] = [];
    const notOnJob: string[] = [];
    let unexpected = "";
    try {
      for (const userId of chosen) {
        try {
          await addTicketStaffAssignment(ticketId, userId, {
            sub_task: part.id,
          });
          done.push(nameOf(userId));
        } catch (err) {
          const code = (err as { response?: { data?: { code?: string } } })
            ?.response?.data?.code;
          if (code === "staff_already_assigned") duplicate.push(nameOf(userId));
          else if (code === "staff_not_on_job") notOnJob.push(nameOf(userId));
          else unexpected = getApiError(err);
        }
      }
      // The list is reloaded whatever happened, so the row can never
      // disagree with what was actually written.
      await onChanged();
      if (done.length > 0) {
        push({
          variant: "success",
          title: t("parts.toast_assigned", {
            count: done.length,
            names: done.join(", "),
            part: part.title,
          }),
        });
      }
      const refusals: string[] = [];
      if (duplicate.length > 0) {
        refusals.push(
          t("parts.error_same_part_named", {
            count: duplicate.length,
            names: duplicate.join(", "),
          }),
        );
      }
      if (notOnJob.length > 0) {
        refusals.push(
          t("parts.error_not_on_job_named", {
            count: notOnJob.length,
            names: notOnJob.join(", "),
          }),
        );
      }
      if (unexpected) refusals.push(unexpected);
      if (refusals.length > 0) {
        setErrorByPart((current) => ({
          ...current,
          [part.id]: refusals.join(" "),
        }));
      }
      // The picker closes either way. Leaving it open with the same
      // people still ticked invites a second confirm that would try the
      // ones that already landed all over again.
      closePicker(part.id);
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
              const pickerOpen = pickerPartId === part.id;
              const chosen = pickByPart[part.id] ?? [];
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

                  {/* W-LATE §3a/§3b -- the part's own window and where it
                      stands against it. One line, always present, so a
                      part without a window says so instead of showing
                      nothing where a colleague's row shows a date. */}
                  <div className="parts-row-window" data-testid="ticket-part-window">
                    <CalendarDays size={12} strokeWidth={2} aria-hidden="true" />
                    <span
                      className={
                        part.window_state === "DONE" ? "parts-chip-done" : undefined
                      }
                      data-testid="ticket-part-window-text"
                    >
                      {windowText(part, t("parts.window_none"))}
                    </span>
                    {stateChip(part)}
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
                          {/* W26.4 -- the assign control OPENS a
                              picker rather than being one. A
                              multi-select has to show several names at
                              once, and a control that tall inside the
                              inline actions row would undo the W26.3
                              layout for every row on screen. So the
                              row keeps one button, and the picker
                              opens underneath it. */}
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            onClick={() => {
                              if (pickerOpen) closePicker(part.id);
                              else setPickerPartId(part.id);
                            }}
                            disabled={busy || offerable.length === 0}
                            aria-expanded={pickerOpen}
                            title={
                              offerable.length === 0
                                ? onJob.length === 0
                                  ? t("parts.assign_nobody_on_job")
                                  : t("parts.assign_everyone_here")
                                : undefined
                            }
                            data-testid="ticket-part-assign-open"
                          >
                            {offerable.length === 0
                              ? onJob.length === 0
                                ? t("parts.assign_nobody_on_job")
                                : t("parts.assign_everyone_here")
                              : t("parts.assign_button")}
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
                            onClick={() => {
                              if (windowPartId === part.id) setWindowPartId(null);
                              else openWindowEditor(part);
                            }}
                            disabled={busy}
                            aria-expanded={windowPartId === part.id}
                            data-testid="ticket-part-window-edit"
                          >
                            <CalendarDays size={13} strokeWidth={2.2} aria-hidden="true" />
                            {t("parts.window_edit")}
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

                  {/* W-LATE §3a -- the window editor, under the row. Three
                      inputs, the server's refusal under the input it
                      names, and the whole ticket window quoted in that
                      refusal so the operator knows what to fit inside. */}
                  {windowPartId === part.id && !isTerminal && (
                    <div data-testid="ticket-part-window-editor">
                      <div className="parts-window-fields">
                        <label className="field">
                          <span className="field-label">{t("parts.window_start")}</span>
                          <input
                            type="date"
                            className="field-input"
                            value={windowDraft.start}
                            disabled={busy}
                            onChange={(event) =>
                              setWindowDraft((d) => ({ ...d, start: event.target.value }))
                            }
                            data-testid="ticket-part-window-start"
                          />
                          {windowError?.field === "planned_start_date" && (
                            <span className="parts-window-error" role="alert" data-testid="ticket-part-window-error" data-field="planned_start_date">
                              {windowError.message}
                            </span>
                          )}
                        </label>
                        <label className="field">
                          <span className="field-label">{t("parts.window_end")}</span>
                          <input
                            type="date"
                            className="field-input"
                            value={windowDraft.end}
                            disabled={busy}
                            onChange={(event) =>
                              setWindowDraft((d) => ({ ...d, end: event.target.value }))
                            }
                            data-testid="ticket-part-window-end"
                          />
                          {windowError?.field === "planned_end_date" && (
                            <span className="parts-window-error" role="alert" data-testid="ticket-part-window-error" data-field="planned_end_date">
                              {windowError.message}
                            </span>
                          )}
                        </label>
                        <label className="field">
                          <span className="field-label">{t("parts.window_time")}</span>
                          <input
                            type="text"
                            className="field-input"
                            maxLength={64}
                            placeholder={t("parts.window_time_placeholder")}
                            value={windowDraft.label}
                            disabled={busy}
                            onChange={(event) =>
                              setWindowDraft((d) => ({ ...d, label: event.target.value }))
                            }
                            data-testid="ticket-part-window-time"
                          />
                        </label>
                      </div>
                      {windowError && windowError.field !== "planned_start_date" && windowError.field !== "planned_end_date" && (
                        <p className="parts-row-error" role="alert">{windowError.message}</p>
                      )}
                      <div className="assign-actions">
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={() => void handleSaveWindow(part)}
                          disabled={busy}
                          data-testid="ticket-part-window-save"
                        >
                          {t("parts.window_save")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => setWindowPartId(null)}
                          disabled={busy}
                          data-testid="ticket-part-window-cancel"
                        >
                          {t("common:cancel")}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* The picker's wrapper takes no class of its own:
                      `.parts-row` is already a column flex container, so
                      a bare div spans it and stacks its title, list and
                      actions. The list and the buttons reuse
                      `.assign-picker` / `.assign-picker-row` /
                      `.assign-actions` -- the ticket-level assign
                      dialog's own checkbox list. It is the same control,
                      so it reads the same and needs no new CSS. */}
                  {pickerOpen && !isTerminal && (
                    <div data-testid="ticket-part-picker">
                      <div className="muted small">
                        {t("parts.assign_label")}
                      </div>
                      {/* The job's assigned people are a SERVER
                          collection, so the list is bounded even though
                          a ticket rarely carries many (CLAUDE.md). */}
                      <BoundedList
                        size="sm"
                        count={offerable.length}
                        ariaLabel={t("parts.assign_label")}
                        testIdPrefix="ticket-part-picker-list"
                        className="assign-picker"
                      >
                        {offerable.map((person) => (
                          <label
                            key={person.id}
                            className="assign-picker-row"
                            data-testid="ticket-part-picker-option"
                            data-user-id={person.id}
                          >
                            <input
                              type="checkbox"
                              checked={chosen.includes(person.id)}
                              disabled={busy}
                              onChange={() => togglePick(part.id, person.id)}
                            />
                            <span>{person.name}</span>
                          </label>
                        ))}
                      </BoundedList>
                      <div className="assign-actions">
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={() => void handleAssignToPart(part)}
                          disabled={busy || chosen.length === 0}
                          data-testid="ticket-part-assign"
                        >
                          {t("parts.assign_confirm", { count: chosen.length })}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => closePicker(part.id)}
                          disabled={busy}
                          data-testid="ticket-part-picker-cancel"
                        >
                          {t("common:cancel")}
                        </button>
                      </div>
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
                onKeyDown={(event) => {
                  // W-UX F46 -- Enter adds, like the button beside it.
                  if (event.key === "Enter" && !busy && newTitle.trim() !== "") {
                    event.preventDefault();
                    void handleAddPart();
                  }
                }}
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
            {/* W-LATE §3a -- the optional window on a new part. Same three
                inputs as the row editor; a refusal lands under its field. */}
            <div className="parts-window-fields" data-testid="ticket-part-add-window">
              <label className="field">
                <span className="field-label">{t("parts.window_start")}</span>
                <input
                  type="date"
                  className="field-input"
                  value={newStart}
                  disabled={busy}
                  onChange={(event) => setNewStart(event.target.value)}
                  data-testid="ticket-part-add-start"
                />
                {addError?.field === "planned_start_date" && (
                  <span className="parts-window-error" role="alert" data-testid="ticket-part-add-error" data-field="planned_start_date">
                    {addError.message}
                  </span>
                )}
              </label>
              <label className="field">
                <span className="field-label">{t("parts.window_end")}</span>
                <input
                  type="date"
                  className="field-input"
                  value={newEnd}
                  disabled={busy}
                  onChange={(event) => setNewEnd(event.target.value)}
                  data-testid="ticket-part-add-end"
                />
                {addError?.field === "planned_end_date" && (
                  <span className="parts-window-error" role="alert" data-testid="ticket-part-add-error" data-field="planned_end_date">
                    {addError.message}
                  </span>
                )}
              </label>
              <label className="field">
                <span className="field-label">{t("parts.window_time")}</span>
                <input
                  type="text"
                  className="field-input"
                  maxLength={64}
                  placeholder={t("parts.window_time_placeholder")}
                  value={newLabel}
                  disabled={busy}
                  onChange={(event) => setNewLabel(event.target.value)}
                  data-testid="ticket-part-add-time"
                />
              </label>
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
