/**
 * Sprint 157 §2 — put workers and managers on Extra Work.
 *
 * One dialog, used from both directions the owner asked for: from the
 * LIST (several requests selected, pick people) and from the DETAIL page
 * (one request, pick people). The caller supplies the requests; only the
 * summary line differs, and it differs because it is computed from what
 * it is given.
 *
 * The role is chosen INSIDE the dialog rather than by opening two
 * different buttons, because "assign" is one intent and worker-or-manager
 * is a property of it. Both are offered as a plain two-way choice with
 * their meanings spelled out — the §5/§6b lesson, repeated: a control
 * whose meaning you have to infer is a broken control.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal here. `ConfirmDialog` stays native and ref-driven where it is
 * used.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { EntityPicker } from "../EntityPicker";
import type { EntityPickerOption } from "../EntityPicker";
import type { ExtraWorkAssignmentRole } from "../../api/types";

export function AssignPeopleDialog({
  requestCount,
  candidates,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  /** How many requests the people will be put on. Drives the summary. */
  requestCount: number;
  candidates: EntityPickerOption[];
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: (userIds: number[], role: ExtraWorkAssignmentRole) => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [userIds, setUserIds] = useState<number[]>([]);
  const [role, setRole] = useState<ExtraWorkAssignmentRole>("WORKER");
  const firstRef = useRef<HTMLButtonElement>(null);

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
      data-testid="assign-people-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("assign.title")}
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
        className="card"
        style={{
          maxWidth: 620,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>{t("assign.title")}</h3>
        {/* The mandatory "N to M" line, same rule as BulkAssignDialog. */}
        <p
          className="muted small"
          style={{ marginTop: 0, marginBottom: 16 }}
          data-testid="assign-people-summary"
        >
          {t("assign.summary", {
            people: userIds.length,
            requests: requestCount,
          })}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="assign-people-error"
          >
            {error}
          </div>
        )}

        <div className="assign-role-choice">
          {(["WORKER", "MANAGER"] as const).map((option, index) => (
            <button
              key={option}
              ref={index === 0 ? firstRef : undefined}
              type="button"
              className={
                role === option
                  ? "assign-role-option assign-role-option-active"
                  : "assign-role-option"
              }
              aria-pressed={role === option}
              onClick={() => setRole(option)}
              disabled={busy}
              data-testid={`assign-role-${option.toLowerCase()}`}
            >
              <span className="assign-role-label">
                {t(`assign.role_${option.toLowerCase()}`)}
              </span>
              <span className="assign-role-desc">
                {t(`assign.role_${option.toLowerCase()}_desc`)}
              </span>
            </button>
          ))}
        </div>

        <EntityPicker
          options={candidates}
          selectedIds={userIds}
          onChange={setUserIds}
          disabled={busy}
          emptyText={t("assign.no_candidates")}
          testIdPrefix="assign-people"
        />

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
            data-testid="assign-people-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || userIds.length === 0 || requestCount === 0}
            onClick={() => onConfirm(userIds, role)}
            data-testid="assign-people-confirm"
          >
            {t("assign.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
