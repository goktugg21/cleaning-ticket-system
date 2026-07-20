// Sprint 5 — read-only sub-tasks view for NON-manager roles on the ticket
// detail. The manager (SA/CA/BM) surface is StaffSlotEditor; this renders the
// ticket's nested `sub_tasks` with no write controls.
//
// Privacy: the backend serializes `ticket.sub_tasks` WITHOUT the per-role
// redaction that `assigned_staff` gets, so the nested staff_assignments carry
// staff identity + internal notes. We therefore only show that detail to
// PROVIDER-side viewers (STAFF). For customer-side viewers we show a
// PII-safe summary (title / description / progress / a slot count) — never a
// staff name, email, or note — mirroring the anonymised assigned-staff list.
import { useTranslation } from "react-i18next";
import { CalendarClock, ListChecks } from "lucide-react";

import type { SubTask, SubTaskAssignment } from "../../api/admin";
import { SlotStatusBadge } from "../../components/SlotStatusBadge";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime } from "../../lib/intl";
import { Toggle } from "../../components/Toggle";

function assignmentWindow(
  slot: SubTaskAssignment,
  unscheduled: string,
): string {
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
  return parts.length > 0 ? parts.join(" · ") : unscheduled;
}

export function SubTaskReadOnly({
  subTasks,
  autoCompleteOnSubtasks,
  showStaffDetails,
}: {
  subTasks: SubTask[];
  autoCompleteOnSubtasks: boolean;
  // True for provider-side STAFF (may see staff identity + notes); false for
  // customer-side viewers (PII-safe summary only).
  showStaffDetails: boolean;
}) {
  const { t } = useTranslation(["staff_slots", "common"]);

  function badge(st: SubTask): {
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

  return (
    <div
      data-testid="subtask-readonly"
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
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--text-faint)",
        }}
      >
        {t("subtasks.section_title")}
      </div>

      {/* Provider-side STAFF see the (read-only) auto-complete state; the
          internal opt-in is hidden from customer-side viewers. */}
      {showStaffDetails && (
        <div
          data-testid="subtask-readonly-auto-complete"
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
            style={{ display: "flex", alignItems: "center", gap: 8 }}
          >
            <Toggle
              checked={autoCompleteOnSubtasks}
              onChange={() => {}}
              disabled
            />
            <span className="small" style={{ fontWeight: 600 }}>
              {t("subtasks.auto_complete_label")}
            </span>
          </label>
          <p className="muted small" style={{ margin: 0 }}>
            {t("subtasks.auto_complete_desc")}
          </p>
        </div>
      )}

      {subTasks.map((st) => {
        const b = badge(st);
        const count = st.staff_assignments.length;
        return (
          <div
            key={st.id}
            data-testid="subtask-readonly-group"
            data-subtask-id={st.id}
            style={{
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: 10,
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
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  minWidth: 0,
                }}
              >
                <ListChecks size={14} strokeWidth={2} />
                <strong style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                  {st.title}
                </strong>
              </div>
              <StatusBadge
                variant="cell"
                status={{ kind: "generic", tone: b.tone, label: b.label }}
              />
            </div>
            {st.description && (
              <div className="muted small" style={{ marginTop: 4 }}>
                {st.description}
              </div>
            )}

            {showStaffDetails ? (
              count === 0 ? (
                <p className="muted small" style={{ margin: "8px 0 0" }}>
                  {t("subtasks.empty_slots")}
                </p>
              ) : (
                <ul
                  style={{ listStyle: "none", margin: "8px 0 0", padding: 0 }}
                >
                  {st.staff_assignments.map((slot) => (
                    <li
                      key={slot.id}
                      data-testid="subtask-readonly-slot"
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
                        <strong>
                          {slot.user_full_name?.trim() || slot.user_email}
                        </strong>
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
                        {assignmentWindow(slot, t("editor.unscheduled"))}
                      </div>
                      {slot.assignment_note && (
                        <div className="small" style={{ marginTop: 4 }}>
                          {slot.assignment_note}
                        </div>
                      )}
                      {slot.slot_status === "COMPLETED" && (
                        <div className="muted small" style={{ marginTop: 4 }}>
                          {t("editor.completed_at", {
                            when: formatDateTime(slot.completed_at),
                          })}
                          {slot.completion_note
                            ? ` · ${slot.completion_note}`
                            : ""}
                        </div>
                      )}
                      {slot.slot_status === "UNABLE_TO_COMPLETE" &&
                        slot.unable_to_complete_reason && (
                          <div
                            className="muted small"
                            style={{ marginTop: 4 }}
                          >
                            {t("editor.unable_reason", {
                              reason: slot.unable_to_complete_reason,
                            })}
                          </div>
                        )}
                    </li>
                  ))}
                </ul>
              )
            ) : (
              count > 0 && (
                <div className="muted small" style={{ marginTop: 6 }}>
                  {t("subtasks.slot_count", { count })}
                </div>
              )
            )}
          </div>
        );
      })}
    </div>
  );
}
