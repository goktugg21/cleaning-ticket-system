// W14 — ONE DOOR onto "put people on this job".
//
// The owner, reading the assignment area of a ticket top to bottom, counted
// four headings, two explanatory paragraphs and three buttons for one idea.
// His question was the whole brief: "why can I not assign several staff at
// once AND separately with time slots?"
//
// He could not because the two halves of that sentence were two different
// controls. `Add slot` took one person and one window. Assigning three people
// to the same morning meant opening it three times. Giving each of them a
// different window meant opening it three times as well -- the identical
// number of presses for two jobs that feel nothing alike.
//
// So both cases are this dialog:
//
//   * tick the people (several, in one go);
//   * optionally give them a time -- ONE time for everybody, or, one radio
//     across, a separate window per person;
//   * optionally file the work under a named part of the job;
//   * one confirm.
//
// Assigning three people to the same morning is one action. Giving each of
// them a different window is the same modal, expanded. Both doors were
// closed and this one opened in their place.
//
// The same dialog, in `edit` mode, is where an existing person's window is
// changed -- the person is fixed, everything else is the form above. A
// second dialog for "the same thing but afterwards" is the confusion this
// file exists to remove.
//
// A NON-native overlay, conditionally mounted, like every other editing
// modal here (`ConfirmDialog` stays native and ref-driven -- CLAUDE.md §3).
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AssignableStaff, SubTask } from "../../api/admin";
import { localInputToIso } from "../../lib/slotTime";

export interface SlotTimeDraft {
  /** `datetime-local` values -- local wall time, no timezone. */
  start: string;
  end: string;
  windowLabel: string;
}

const EMPTY_SLOT_TIME: SlotTimeDraft = {
  start: "",
  end: "",
  windowLabel: "",
};

export interface AssignStaffResult {
  /** In edit mode this is the single person already on the slot. */
  userIds: number[];
  /** One entry per id in `userIds`, already resolved from same-for-all. */
  timesByUser: Record<number, SlotTimeDraft>;
  note: string;
  /** An existing part of the job, or null for the general pool. */
  partId: number | null;
  /** Non-empty means: create this part first, then file the work under it. */
  newPartTitle: string;
}

/** Sentinel `value` for the "a new part" option of the part select. */
const NEW_PART = "__new__";

function endsBeforeStart(times: SlotTimeDraft): boolean {
  const start = localInputToIso(times.start);
  const end = localInputToIso(times.end);
  return Boolean(start && end && end < start);
}

export function AssignStaffDialog({
  mode,
  candidates,
  editingPersonId,
  editingPersonName,
  initialTimes,
  initialNote,
  initialPartId,
  parts,
  allowParts,
  busy,
  error,
  noCandidatesText,
  onCancel,
  onConfirm,
  testIdPrefix = "assign-staff",
}: {
  mode: "assign" | "edit";
  /** Assign mode only -- who may be ticked. */
  candidates: AssignableStaff[];
  /** Edit mode only -- the person whose window is being changed. */
  editingPersonId?: number;
  editingPersonName?: string;
  initialTimes?: SlotTimeDraft;
  initialNote?: string;
  initialPartId?: number | null;
  parts: SubTask[];
  /** False on a terminal ticket, where the backend refuses part placement. */
  allowParts: boolean;
  busy?: boolean;
  error?: string;
  noCandidatesText: string;
  onCancel: () => void;
  onConfirm: (result: AssignStaffResult) => void;
  testIdPrefix?: string;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);

  const [userIds, setUserIds] = useState<number[]>(
    mode === "edit" && editingPersonId !== undefined ? [editingPersonId] : [],
  );
  const [perPerson, setPerPerson] = useState(false);
  const [shared, setShared] = useState<SlotTimeDraft>(
    initialTimes ?? EMPTY_SLOT_TIME,
  );
  const [byUser, setByUser] = useState<Record<number, SlotTimeDraft>>({});
  const [note, setNote] = useState(initialNote ?? "");
  const [part, setPart] = useState<string>(
    initialPartId === undefined || initialPartId === null
      ? ""
      : String(initialPartId),
  );
  const [newPartTitle, setNewPartTitle] = useState("");

  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    cardRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  // Per-person windows are only a different thing from one shared window when
  // there is more than one person, so below two the control is not offered.
  const perPersonAvailable = mode === "assign" && userIds.length > 1;
  const effectivePerPerson = perPersonAvailable && perPerson;

  const selected = useMemo(
    () =>
      mode === "edit"
        ? []
        : userIds
            .map((id) => candidates.find((c) => c.id === id))
            .filter((c): c is AssignableStaff => c !== undefined),
    [mode, userIds, candidates],
  );

  const timesFor = (userId: number): SlotTimeDraft =>
    effectivePerPerson ? (byUser[userId] ?? EMPTY_SLOT_TIME) : shared;

  const badWindow = effectivePerPerson
    ? userIds.some((id) => endsBeforeStart(timesFor(id)))
    : endsBeforeStart(shared);
  const missingPartTitle = part === NEW_PART && newPartTitle.trim() === "";
  const nothingPicked = userIds.length === 0;

  function setPersonTimes(userId: number, next: SlotTimeDraft) {
    setByUser((current) => ({ ...current, [userId]: next }));
  }

  function submit() {
    if (nothingPicked || badWindow || missingPartTitle) return;
    const timesByUser: Record<number, SlotTimeDraft> = {};
    for (const id of userIds) timesByUser[id] = timesFor(id);
    onConfirm({
      userIds,
      timesByUser,
      note,
      partId:
        !allowParts || part === "" || part === NEW_PART ? null : Number(part),
      newPartTitle: allowParts && part === NEW_PART ? newPartTitle.trim() : "",
    });
  }

  const title =
    mode === "assign" ? t("assign.title") : t("assign.edit_title");

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid={`${testIdPrefix}-modal`}
    >
      <div
        ref={cardRef}
        tabIndex={-1}
        className="card ew-plan-dialog"
      >
        <h3 className="section-title ew-plan-dialog-title">{title}</h3>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid={`${testIdPrefix}-error`}
          >
            {error}
          </div>
        )}

        {mode === "assign" ? (
          <div className="field">
            {/* A group of checkboxes has no single control to label, so the
                group is named by aria-labelledby rather than a <label for>
                pointing at nothing. */}
            <span className="field-label" id={`${testIdPrefix}-people-label`}>
              {t("assign.people_label")}
            </span>
            {candidates.length === 0 ? (
              <p className="muted small" data-testid={`${testIdPrefix}-none`}>
                {noCandidatesText}
              </p>
            ) : (
              <div
                className="assign-picker"
                role="group"
                aria-labelledby={`${testIdPrefix}-people-label`}
                data-testid={`${testIdPrefix}-people`}
              >
                {candidates.map((staff) => (
                  <label key={staff.id} className="assign-picker-row">
                    <input
                      type="checkbox"
                      className="checkbox-input"
                      checked={userIds.includes(staff.id)}
                      disabled={busy}
                      onChange={(event) =>
                        setUserIds((current) =>
                          event.target.checked
                            ? [...current, staff.id]
                            : current.filter((id) => id !== staff.id),
                        )
                      }
                      data-testid={`${testIdPrefix}-person`}
                      data-user-id={staff.id}
                    />
                    <span>{staff.full_name?.trim() || staff.email}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="field">
            <span className="field-label">{t("assign.people_label")}</span>
            <p
              className="assign-edit-person"
              data-testid={`${testIdPrefix}-editing-person`}
            >
              {editingPersonName}
            </p>
          </div>
        )}

        {perPersonAvailable && (
          <div className="field">
            <span className="field-label" id={`${testIdPrefix}-mode-label`}>
              {t("assign.time_label")}
            </span>
            <div
              className="assign-time-modes"
              role="radiogroup"
              aria-labelledby={`${testIdPrefix}-mode-label`}
            >
              <label className="assign-picker-row">
                <input
                  type="radio"
                  name={`${testIdPrefix}-time-mode`}
                  checked={!perPerson}
                  disabled={busy}
                  onChange={() => setPerPerson(false)}
                  data-testid={`${testIdPrefix}-time-same`}
                />
                <span>{t("assign.time_same")}</span>
              </label>
              <label className="assign-picker-row">
                <input
                  type="radio"
                  name={`${testIdPrefix}-time-mode`}
                  checked={perPerson}
                  disabled={busy}
                  onChange={() => setPerPerson(true)}
                  data-testid={`${testIdPrefix}-time-per-person`}
                />
                <span>{t("assign.time_per_person")}</span>
              </label>
            </div>
          </div>
        )}

        {effectivePerPerson ? (
          <div data-testid={`${testIdPrefix}-per-person-times`}>
            {selected.map((staff) => (
              <fieldset
                key={staff.id}
                className="assign-person-times"
                data-testid={`${testIdPrefix}-person-times`}
                data-user-id={staff.id}
              >
                <legend className="assign-person-times-name">
                  {staff.full_name?.trim() || staff.email}
                </legend>
                <SlotTimeFields
                  idPrefix={`${testIdPrefix}-${staff.id}`}
                  value={timesFor(staff.id)}
                  onChange={(next) => setPersonTimes(staff.id, next)}
                  disabled={busy}
                />
              </fieldset>
            ))}
          </div>
        ) : (
          <SlotTimeFields
            idPrefix={`${testIdPrefix}-shared`}
            value={shared}
            onChange={setShared}
            disabled={busy}
          />
        )}

        <div className="field">
          <label className="field-label" htmlFor={`${testIdPrefix}-note`}>
            {t("assign.note_label")}
          </label>
          <textarea
            id={`${testIdPrefix}-note`}
            className="field-textarea"
            value={note}
            disabled={busy}
            onChange={(event) => setNote(event.target.value)}
            data-testid={`${testIdPrefix}-note`}
          />
        </div>

        {allowParts && (
          <div className="field">
            <label className="field-label" htmlFor={`${testIdPrefix}-part`}>
              {t("assign.part_label")}
            </label>
            <select
              id={`${testIdPrefix}-part`}
              className="field-select"
              value={part}
              disabled={busy}
              onChange={(event) => setPart(event.target.value)}
              data-testid={`${testIdPrefix}-part`}
            >
              <option value="">{t("assign.part_none")}</option>
              {parts.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.title}
                </option>
              ))}
              <option value={NEW_PART}>{t("assign.part_new")}</option>
            </select>
            {part === NEW_PART && (
              <input
                className="field-input"
                type="text"
                maxLength={200}
                value={newPartTitle}
                disabled={busy}
                placeholder={t("assign.part_new_placeholder")}
                aria-label={t("assign.part_new")}
                onChange={(event) => setNewPartTitle(event.target.value)}
                data-testid={`${testIdPrefix}-new-part-title`}
                style={{ marginTop: 6 }}
              />
            )}
          </div>
        )}

        {badWindow && (
          <div
            className="alert-error"
            role="alert"
            data-testid={`${testIdPrefix}-bad-window`}
          >
            {t("editor.end_before_start")}
          </div>
        )}

        <div className="ew-plan-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testIdPrefix}-cancel`}
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={submit}
            disabled={busy || nothingPicked || badWindow || missingPartTitle}
            data-testid={`${testIdPrefix}-confirm`}
          >
            {mode === "assign"
              ? t("assign.confirm", { count: userIds.length })
              : t("common:save")}
          </button>
        </div>
      </div>
    </div>
  );
}

// Start / end / window-label inputs. Local presentational helper (not
// exported) so this module still exposes exactly one component to
// react-refresh.
function SlotTimeFields({
  idPrefix,
  value,
  onChange,
  disabled,
}: {
  idPrefix: string;
  value: SlotTimeDraft;
  onChange: (next: SlotTimeDraft) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation("staff_slots");
  return (
    <div className="assign-time-fields">
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-start`}>
          {t("editor.field_start")}
        </label>
        <input
          id={`${idPrefix}-start`}
          className="field-input"
          type="datetime-local"
          value={value.start}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...value, start: event.target.value })
          }
          data-testid={`${idPrefix}-start`}
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
          value={value.end}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, end: event.target.value })}
          data-testid={`${idPrefix}-end`}
        />
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
          value={value.windowLabel}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...value, windowLabel: event.target.value })
          }
          data-testid={`${idPrefix}-window`}
        />
      </div>
    </div>
  );
}
