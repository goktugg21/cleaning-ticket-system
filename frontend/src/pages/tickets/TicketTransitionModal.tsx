import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AssignableStaff } from "../../api/admin";
import type { TransitionRequirements } from "../../api/types";

/**
 * W13-FIX §1 — THE TRANSITION MODAL.
 *
 *     The owner's father, twenty years a programmer, on the workflow
 *     card: "If you work on those transition modals, this job is done."
 *
 *     The owner: "I click. It has to give me a warning. I cannot be
 *     sure whether the button worked."
 *
 * Before this, every workflow button fired its POST on the first click.
 * Nothing was asked and nothing was confirmed, so a job could be
 * recorded as started with nobody doing it and no date on it, and the
 * only way to learn what a button did was to press it.
 *
 * Now pressing a move opens THIS, and the move does not happen until it
 * is answered. It asks the three things a step can need:
 *
 *     WHO is doing it      the staff picker, multi-select
 *     WHEN                 the start date and time
 *     WHAT IT NEEDS to be  the note that travels with the move
 *     reported done
 *
 * WHICH of those it asks for is NOT decided here. The component renders
 * a field per entry in `requirements.unmet`, and that list comes from
 * `GET /tickets/<id>/transition-requirements/`, which is the same
 * `transition_requirements.py` that `apply_transition` enforces. A
 * screen that predicted the rule would be a second copy of it, and this
 * codebase has already been bitten twice by exactly that (CLAUDE.md:
 * the render-order array, the pagination class). So the page asks.
 *
 * It is a plain overlay, not a native `<dialog>`, matching the sibling
 * picker in `ResponsibleManagersSection`. CLAUDE.md's `<dialog>` rule
 * exists because a conditionally-MOUNTED native dialog is invisible and
 * an unmounted-while-open one freezes the page; an overlay div has
 * neither failure mode, and mounting it conditionally is correct.
 */

export interface TransitionAnswers {
  note: string;
  assigned_staff_ids?: number[];
  scheduled_start_at?: string;
  /** W14 §4 — the justification an OVERRIDE carries. Never merged into
   *  `note`: the note is the operational comment on the move, the
   *  reason is what the audit row records, and collapsing them would
   *  put one value in two meanings. */
  override_reason?: string;
  /** W-UX1 §4 — TRUE only when the operator explicitly chose to move
   *  without the proof this step requires.
   *
   *  This is a deliberate departure from W10 §4's "is_override is the
   *  BACKEND's call". That rule exists so an ORDINARY move is not
   *  stamped as an override in the audit trail — and it is right for
   *  every other path. Skipping a required photo or note is not an
   *  ordinary move; it IS the override, and the machine cannot infer
   *  that from the status pair because the pair is a perfectly normal
   *  completion. Sending it is also what makes the reason survive:
   *  `state_machine` writes `override_reason if is_override else ""`
   *  (state_machine.py:727), so a reason sent without the flag is
   *  discarded and the bypass would cost nothing. */
  is_override?: boolean;
}

/** W-FIX1 B2 (audit F24) — the prefilled start is never in the past:
 *  the plan's start when it is still ahead, otherwise TODAY at the
 *  plan's wall-clock time. Ticket 373 opened on "yesterday 00:00". */
function prefillStartsAt(current: string, now: Date = new Date()): string {
  if (!current) return "";
  const planned = new Date(current);
  if (Number.isNaN(planned.getTime())) return "";
  if (planned.getTime() >= now.getTime()) return current;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(planned.getHours())}:${pad(planned.getMinutes())}`
  );
}

export interface TicketTransitionModalProps {
  /** The verb already rendered on the button that opened this. */
  actionLabel: string;
  fromStatusLabel: string;
  toStatusLabel: string;
  /** null while the requirements call is still in flight. */
  requirements: TransitionRequirements | null;
  loading: boolean;
  staff: AssignableStaff[];
  /** W-FIX1 C3 (audit F34) — why the list is empty when the server
   *  refused it; rendered under the picker so a disabled confirm has
   *  a sentence next to it. */
  staffError?: string;
  /** R2 — who is ALREADY on this ticket. Shown as the settled default
   *  and NEVER posted back: `staff` below is the server's addable list,
   *  which already excludes them, so re-sending one is the duplicate
   *  that answers `staff_already_assigned`. Carried assignments (an EW
   *  spawn hands its workers to the ticket) arrive through this list,
   *  which is why the modal never has to know they were carried. */
  currentAssignees: { id: number; label: string }[];
  /** R2 — the date the ticket already carries, "YYYY-MM-DDTHH:mm" in
   *  LOCAL time, ready for `<input type="datetime-local">`, or "". */
  currentScheduledStartAt: string;
  busy: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: (answers: TransitionAnswers) => void;
  /** W-FIX2 — upload one file as completion proof, through the ticket's
   *  EXISTING attachment endpoint. The gate reads
   *  `_ticket_has_visible_attachment`, i.e. ordinary non-hidden
   *  `TicketAttachment` rows, so an ordinary upload satisfies it and no
   *  backend change is needed. Resolves when the row exists. */
  onUploadProof?: (file: File) => Promise<void>;
}

export function TicketTransitionModal({
  actionLabel,
  fromStatusLabel,
  toStatusLabel,
  requirements,
  loading,
  staff,
  staffError = "",
  currentAssignees,
  currentScheduledStartAt,
  busy,
  error,
  onCancel,
  onConfirm,
  onUploadProof,
}: TicketTransitionModalProps) {
  const { t } = useTranslation(["ticket_detail", "common"]);

  // No reset effect here on purpose. The answers must not survive a
  // change of STEP -- a date typed for "start the work" must never be
  // submitted against "send it to the customer" -- and CLAUDE.md's rule
  // for exactly this is to KEY the component rather than to setState in
  // an effect body. `TicketDetailPage` mounts this with
  // `key={transitionTarget}`, so a different move is a different
  // component instance and these three start empty by construction.
  const [note, setNote] = useState("");
  // W-FIX1 — the people being ADDED, and only them. It was seeded with
  // the existing crew, which read well and posted a duplicate: the
  // picker's own source excludes anyone already holding a base slot
  // here, so every seeded id was one the server would refuse. The crew
  // is rendered above as settled fact instead.
  const [picked, setPicked] = useState<number[]>([]);
  const [startsAt, setStartsAt] = useState(() =>
    prefillStartsAt(currentScheduledStartAt),
  );
  const [reason, setReason] = useState("");
  /** W-UX1 §4 — the two-press bypass: pressing it once reveals the
   *  reason, and only a reason arms the move. */
  const [overriding, setOverriding] = useState(false);
  // W-FIX2 — the modal said "a photo or a note" and offered only a note.
  const [proofUploading, setProofUploading] = useState(false);
  const [proofUploaded, setProofUploaded] = useState(false);
  const [proofError, setProofError] = useState("");

  const unmet = useMemo(() => requirements?.unmet ?? [], [requirements]);
  const needsAssignee = unmet.includes("assignee");
  /** R2 — "the modal SHOWS what already exists and asks only for
   *  what is missing". A requirement the ticket already satisfies is
   *  still part of this step's checklist, so it renders — prefilled
   *  and editable — instead of vanishing and leaving the operator to
   *  wonder whether it was asked for. `requirements` carries the
   *  satisfied ones for exactly this reason. */
  const has = (key: string) =>
    (requirements?.requirements ?? []).some((r) => r.key === key);
  const showAssignee = has("assignee");
  const showSchedule = has("schedule");
  const needsSchedule = unmet.includes("schedule");
  /**
   * W14 §4 — THE MOVE IS AN OVERRIDE AND THE SERVER WILL WANT A REASON.
   *
   * Not predicted here. `state_machine.transition_needs_override_reason`
   * decides, `transition-requirements` reports it, and this renders
   * whatever comes back — the same "the page does not predict, it asks"
   * the module was built on.
   *
   * Before this, the endpoint did not report it and so this form never
   * asked: the operator pressed Undo, was shown a modal wanting only an
   * optional note, pressed its button, and the modal closed on a 400
   * nobody was shown. The owner: "undo and the correction actions do
   * not seem to work. I could not get them to work."
   */
  const needsReason = unmet.includes("override_reason");
  /** W-UX1 §4 — this step wants proof the work happened, and the ticket
   *  does not carry it yet. R3: it says so INLINE, here, the moment it
   *  is unmet, rather than being met as a 400 after the press. */
  const needsProof = unmet.includes("completion_evidence");

  // Every unmet requirement must have an answer before the move is
  // offered. This is the "DOES NOT TRANSITION until it is answered"
  // half that lives on the screen; the backend enforces the same thing
  // independently, so a client that skipped this still cannot move it.
  /** W-FIX1 B2 (audit F24) — moving an EXISTING schedule is a
   *  reschedule, and a reschedule needs its reason; the note is that
   *  reason on this door, so it stops being optional the moment the
   *  date differs from the one the ticket already has. */
  const movingSchedule =
    showSchedule &&
    currentScheduledStartAt !== "" &&
    startsAt !== "" &&
    startsAt !== currentScheduledStartAt;
  const answered =
    (!needsAssignee || picked.length > 0 || currentAssignees.length > 0) &&
    (!needsSchedule || startsAt !== "") &&
    (!movingSchedule || note.trim() !== "") &&
    (!needsReason || reason.trim() !== "") &&
    // Proof is answered by writing the note this step asks for, or by
    // explicitly overriding WITH a reason. Nothing else.
    (!needsProof ||
      note.trim() !== "" ||
      proofUploaded ||
      (overriding && reason.trim() !== ""));

  function confirm() {
    const answers: TransitionAnswers = { note: note.trim() };
    // Send the selection whenever the block was SHOWN and the
    // operator changed it, not only when the requirement was unmet:
    // editing a carried-over crew is the R2 affordance, and a change
    // the modal accepted but did not post would be a lie.
    if (showAssignee && picked.length > 0) answers.assigned_staff_ids = picked;
    if (needsReason && reason.trim() !== "") {
      answers.override_reason = reason.trim();
    }
    if (needsProof && overriding && reason.trim() !== "") {
      answers.override_reason = reason.trim();
      answers.is_override = true;
    }
    if (showSchedule && startsAt !== "") {
      // <input type="datetime-local"> has no zone; the browser's own
      // offset is the operator's intent, so build the instant locally
      // and send ISO. Sending the naive string would be read as UTC by
      // DRF and silently shift the start by the offset.
      answers.scheduled_start_at = new Date(startsAt).toISOString();
    }
    onConfirm(answers);
  }

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={actionLabel}
      data-testid="transition-modal"
    >
      <div className="card ew-plan-dialog transition-dialog">
        <h3 className="section-title ew-plan-dialog-title">{actionLabel}</h3>

        {/* The move itself, in words, so the operator can see WHERE this
            puts the ticket before committing to it -- the whole of the
            father's "I cannot be sure whether the button worked". */}
        <p className="transition-dialog-move" data-testid="transition-modal-move">
          {t("transition.move", {
            from: fromStatusLabel,
            to: toStatusLabel,
          })}
        </p>

        {loading ? (
          <p className="muted small" data-testid="transition-modal-loading">
            {t("common:loading")}
          </p>
        ) : (
          <>
            {/* W-UX1 §4 / R3 — the requirement warning, inline, as a
                state line. The note field below IS the answer, so the
                warning points at it rather than at a 400 the operator
                would otherwise meet after pressing. */}
            {needsProof && (
              <div
                className="transition-field"
                data-testid="transition-field-proof"
              >
                {/* R3 — and it CLEARS LIVE. The warning is about a
                    missing thing, so the moment either kind of proof is
                    present it has nothing to say. */}
                {note.trim() === "" && !proofUploaded && (
                  <p className="alert-error" role="status">
                    {t("transition.proof_required")}
                  </p>
                )}
                {onUploadProof && (
                  <div className="transition-proof-upload">
                    <label className="field-label" htmlFor="transition-proof-file">
                      {t("transition.proof_photo_label")}
                    </label>
                    <input
                      id="transition-proof-file"
                      type="file"
                      accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf"
                      disabled={proofUploading}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (!file) return;
                        setProofError("");
                        setProofUploading(true);
                        void onUploadProof(file)
                          .then(() => setProofUploaded(true))
                          .catch((err: unknown) =>
                            setProofError(
                              err instanceof Error
                                ? err.message
                                : String(err),
                            ),
                          )
                          .finally(() => setProofUploading(false));
                      }}
                      data-testid="transition-proof-file"
                    />
                    {proofUploading && (
                      <span className="muted small">
                        {t("transition.proof_photo_uploading")}
                      </span>
                    )}
                    {proofUploaded && (
                      <span className="muted small" data-testid="transition-proof-done">
                        {t("transition.proof_photo_done")}
                      </span>
                    )}
                    {proofError && (
                      <p className="alert-error" role="alert">
                        {proofError}
                      </p>
                    )}
                  </div>
                )}
                {!overriding ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setOverriding(true)}
                    data-testid="transition-proof-override"
                  >
                    {t("transition.proof_override")}
                  </button>
                ) : (
                  <>
                    <label className="field-label" htmlFor="transition-proof-reason">
                      {t("transition.proof_override_reason")}
                    </label>
                    <textarea
                      id="transition-proof-reason"
                      className="field-textarea"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      data-testid="transition-proof-reason"
                    />
                  </>
                )}
              </div>
            )}

            {showAssignee && (
              <div className="transition-field" data-testid="transition-field-assignee">
                <span className="field-label" id="transition-who-label">
                  {t("transition.who_label")}
                </span>
                {/* R2 — who is on it already, as settled fact. Not
                    checkboxes: taking somebody OFF a job is the
                    assignment section's own action, and a control that
                    looks like it removes them but does not would be
                    worse than no control. */}
                {currentAssignees.length > 0 && (
                  <div
                    className="parts-chip-row"
                    data-testid="transition-current-assignees"
                  >
                    {currentAssignees.map((person) => (
                      <span key={person.id} className="parts-chip">
                        {person.label}
                      </span>
                    ))}
                  </div>
                )}
                {/* W-FIX1 — NO ADD CONTROL WHEN THERE IS NOBODY TO ADD,
                    and no apology line either. The old empty state said
                    "nobody available to assign" on a ticket whose whole
                    crew was standing right above it, because `staff` is
                    the ADDABLE list and a fully-staffed job empties it. */}
                {staff.length > 0 && (
                  <>
                <p className="muted small">{t("transition.who_hint")}</p>
                <div
                  className="assign-picker"
                  role="group"
                  aria-labelledby="transition-who-label"
                >
                  {(
                    staff.map((person) => (
                      <label key={person.id} className="assign-picker-row">
                        <input
                          type="checkbox"
                          className="checkbox-input"
                          checked={picked.includes(person.id)}
                          onChange={(event) =>
                            setPicked((current) =>
                              event.target.checked
                                ? [...current, person.id]
                                : current.filter((id) => id !== person.id),
                            )
                          }
                          data-testid="transition-staff-option"
                        />
                        <span>{person.full_name?.trim() || person.email}</span>
                      </label>
                    ))
                  )}
                </div>
                  </>
                )}
              </div>
            )}

            {staffError && (
              <p
                className="form-error"
                data-testid="transition-assignee-unavailable"
              >
                {t("transition.assignee_list_unavailable")} {staffError}
              </p>
            )}

            {showSchedule && (
              <div className="transition-field" data-testid="transition-field-schedule">
                <label className="field-label" htmlFor="transition-starts-at">
                  {t("transition.when_label")}
                </label>
                <p className="muted small">{t("transition.when_hint")}</p>
                <input
                  id="transition-starts-at"
                  type="datetime-local"
                  className="filter-control"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                  data-testid="transition-starts-at"
                />
              </div>
            )}

            {needsReason && (
              <div
                className="transition-field"
                data-testid="transition-field-override-reason"
              >
                <label
                  className="field-label"
                  htmlFor="transition-override-reason"
                >
                  {t("transition.reason_label")}
                </label>
                {/* Says WHY it is being asked for, because "this is not
                    a step the workflow offers" is the whole reason the
                    field is here and the operator cannot see the
                    transition table. */}
                <p className="muted small">{t("transition.reason_hint")}</p>
                <textarea
                  id="transition-override-reason"
                  className="filter-control"
                  rows={3}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  data-testid="transition-override-reason"
                />
              </div>
            )}

            <div className="transition-field">
              <label className="field-label" htmlFor="transition-note">
                {t("transition.note_label")}
              </label>
              <p className="muted small">{t("transition.note_hint")}</p>
              {movingSchedule && (
                <p
                  className="form-hint ew-hours-tone-over"
                  data-testid="transition-note-required"
                >
                  {t("transition.note_required_for_move")}
                </p>
              )}
              <textarea
                id="transition-note"
                className="filter-control"
                rows={3}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                data-testid="transition-note"
              />
            </div>
          </>
        )}

        {error && (
          <div className="alert-error" role="alert" data-testid="transition-modal-error">
            {error}
          </div>
        )}

        <div className="ew-plan-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid="transition-modal-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={confirm}
            disabled={busy || loading || !answered}
            data-testid="transition-modal-confirm"
          >
            {busy ? t("updating") : actionLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
