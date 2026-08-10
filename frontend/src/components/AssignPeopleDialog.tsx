/**
 * Sprint 159 §2 — staff a job in ONE dialog and ONE confirm.
 *
 * Sprint 158 made the two roles eligible separately, which was right:
 * a field worker is not a candidate to MANAGE a job. But the dialog
 * still took one role per operation — pick a role, pick people,
 * confirm, reopen, pick the other role, confirm again. The owner wants
 * both at once, and he is right that this is one intent.
 *
 * So the role TOGGLE is gone (that is a control removed, not moved) and
 * both pickers are on screen side by side, each offering only its own
 * eligible candidates. The candidates are the SERVER's answer, per role,
 * from `buildings.assignment_eligibility` — the same helper the write
 * validator uses, so "offerable" and "acceptable" cannot disagree
 * (Sprint 152.1 §1a).
 *
 * One confirm sends one request, and the endpoint writes both sets in
 * one transaction: an ineligible manager rejects the workers with it
 * rather than leaving half a crew on the job. That property is the
 * reason this is one request and not two.
 *
 * Lives in `components/` rather than `components/extra-work/` because
 * tickets use it too, and its copy is in `common` for the same reason.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal here. `ConfirmDialog` stays native and ref-driven where it is
 * used (CLAUDE.md §3).
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { EntityPicker } from "./EntityPicker";
import type { EntityPickerOption } from "./EntityPicker";

export function AssignPeopleDialog({
  summary,
  managerCandidates,
  workerCandidates,
  busy,
  error,
  onCancel,
  onConfirm,
  testIdPrefix = "assign-people",
}: {
  /** The mandatory "N to M" line, computed by the caller because only it
   *  knows whether the targets are requests or tickets. */
  summary: string;
  managerCandidates: EntityPickerOption[];
  workerCandidates: EntityPickerOption[];
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  /** Either list may be empty; both empty is refused by the button. */
  onConfirm: (managerIds: number[], workerIds: number[]) => void;
  testIdPrefix?: string;
}) {
  const { t } = useTranslation("common");
  const [managerIds, setManagerIds] = useState<number[]>([]);
  const [workerIds, setWorkerIds] = useState<number[]>([]);
  const firstRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    firstRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div
      data-testid={`${testIdPrefix}-modal`}
      role="dialog"
      aria-modal="true"
      aria-label={t("assign_people.title")}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        ref={firstRef}
        tabIndex={-1}
        className="card"
        style={{
          maxWidth: 760,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>
          {t("assign_people.title")}
        </h3>
        {/* The mandatory "N to M" line, same rule as BulkAssignDialog. */}
        <p
          className="muted small"
          style={{ marginTop: 0, marginBottom: 16 }}
          data-testid={`${testIdPrefix}-summary`}
        >
          {summary}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid={`${testIdPrefix}-error`}
          >
            {error}
          </div>
        )}

        {/* Side by side, and each side says what the role is FOR — the
            §6b lesson repeated: a control whose meaning you have to
            infer is a broken control. */}
        <div className="assign-people-columns">
          <div className="field">
            <span className="field-label">
              {t("assign_people.managers_label")}
            </span>
            <p className="field-hint muted small" style={{ marginTop: 0 }}>
              {t("assign_people.managers_desc")}
            </p>
            <EntityPicker
              options={managerCandidates}
              selectedIds={managerIds}
              onChange={setManagerIds}
              disabled={busy}
              emptyText={t("assign_people.no_managers")}
              testIdPrefix={`${testIdPrefix}-managers`}
            />
          </div>

          <div className="field">
            <span className="field-label">
              {t("assign_people.workers_label")}
            </span>
            <p className="field-hint muted small" style={{ marginTop: 0 }}>
              {t("assign_people.workers_desc")}
            </p>
            <EntityPicker
              options={workerCandidates}
              selectedIds={workerIds}
              onChange={setWorkerIds}
              disabled={busy}
              emptyText={t("assign_people.no_workers")}
              testIdPrefix={`${testIdPrefix}-workers`}
            />
          </div>
        </div>

        <p
          className="week-setup-summary"
          role="status"
          data-testid={`${testIdPrefix}-counts`}
        >
          {t("assign_people.selected_counts", {
            managers: managerIds.length,
            workers: workerIds.length,
          })}
        </p>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 16,
          }}
        >
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testIdPrefix}-cancel`}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={
              busy || (managerIds.length === 0 && workerIds.length === 0)
            }
            onClick={() => onConfirm(managerIds, workerIds)}
            data-testid={`${testIdPrefix}-confirm`}
          >
            {t("assign_people.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
