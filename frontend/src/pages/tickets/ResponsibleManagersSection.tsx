// W13 — MANAGERS. One named section, one table, one button.
//
// The owner's father, twenty years a programmer, used this page for
// twenty minutes: "I understood nothing right now." "You have put
// everything one under the other. Have you never used a form?"
//
// He also asked why a ticket has a head manager AND a responsible
// manager. It has both because two sprints added one each, and the
// answer to "what is the difference" is: nothing a user can act on.
// Checked before collapsing them:
//
//   * PERMISSION: neither grants any. A BUILDING_MANAGER's visibility
//     comes from `BuildingManagerAssignment` (building-level) in
//     `accounts/scoping.py`; neither `Ticket.assigned_to` nor
//     `TicketManagerAssignment` appears there at all.
//   * ELIGIBILITY: identical -- role BUILDING_MANAGER plus a
//     BuildingManagerAssignment for this ticket's building.
//   * FILTERING: `TicketFilter.my_managed` is the UNION of the two, so
//     the rest of the app already treats them as one thing.
//   * The ONE real difference: writing `assigned_to` sends assignment /
//     unassignment email; adding a responsible manager sends none.
//
// So the two are collapsed HERE, in the UI, onto the M:N -- the one that
// can hold more than one person, which is what a ticket actually needs.
// The single pointer and its emails are untouched on the server; nothing
// on this page writes it any more. Turning those emails on for this path
// is a product decision, not a cleanup, and is called out in the report.
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CollapsibleCard } from "../../components/CollapsibleCard";
import { getApiError } from "../../api/client";
import {
  addManagerAssignments,
  listManagerAssignments,
  removeManagerAssignment,
} from "../../api/managerAssignments";
import type { TicketManagerAssignment } from "../../api/managerAssignments";
import type { AssignableManager } from "../../api/types";

interface Props {
  ticketId: number;
  canManage: boolean;
  assignableManagers: AssignableManager[];
  onChanged?: () => void;
}

export function ResponsibleManagersSection({
  ticketId,
  canManage,
  assignableManagers,
  onChanged,
}: Props) {
  const { t } = useTranslation(["ticket_detail", "common"]);
  const [rows, setRows] = useState<TicketManagerAssignment[]>([]);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  /** W13 — a SET, because a manager assigns two people at once. */
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  // Bumped to force a refetch after a successful add/remove (state is only
  // set in async callbacks, never synchronously in the effect body).
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    listManagerAssignments(ticketId)
      .then((data) => {
        if (!cancelled) {
          setRows(data);
          setHidden(false);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response
          ?.status;
        if (status === 403) {
          // BM without the building's assign-staff key — hide the section
          // rather than surfacing an error on the page.
          setHidden(true);
        } else {
          setError(getApiError(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ticketId, canManage, reloadNonce]);

  if (!canManage || hidden) return null;

  function mapError(err: unknown): string {
    const code = (
      err as { response?: { data?: { code?: string } } }
    )?.response?.data?.code;
    if (code === "manager_assignment_terminal") {
      return t("resp_mgr.error_terminal");
    }
    if (
      code === "manager_not_eligible" ||
      code === "manager_assignment_target_invalid" ||
      code === "manager_assignment_scope_forbidden"
    ) {
      return t("resp_mgr.error_not_eligible");
    }
    return getApiError(err);
  }

  const assignedIds = new Set(rows.map((r) => r.user_id));
  const candidates = assignableManagers.filter((m) => !assignedIds.has(m.id));

  async function handleAdd() {
    if (picked.length === 0) return;
    setBusy(true);
    setError("");
    try {
      await addManagerAssignments(ticketId, picked);
      setPicked([]);
      setPickerOpen(false);
      setReloadNonce((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setError(mapError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(userId: number) {
    setBusy(true);
    setError("");
    try {
      await removeManagerAssignment(ticketId, userId);
      setReloadNonce((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setError(mapError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <CollapsibleCard
      title={t("resp_mgr.title")}
      meta={t("resp_mgr.count", { count: rows.length })}
      // #110 Part A — default COLLAPSED like the other right-column
      // cards (Workflow stays the only always-open card). No persistKey;
      // the ticket-keyed detail-side wrapper remounts it per ticket.
      // W-PLAN2 Task 2 — open by default (Details + Activity are the
      // only cards that stay collapsed).
      defaultOpen
      testId="responsible-managers-section"
    >
      <div style={{ padding: "0 18px 14px" }}>
        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 10 }}
            data-testid="responsible-managers-error"
          >
            {error}
          </div>
        )}

        {rows.length === 0 ? (
          /* The empty state says what to do, and the button that does it
             is the only button in the section. */
          <div className="assign-empty" data-testid="responsible-managers-empty">
            <p className="assign-empty-title">{t("resp_mgr.empty")}</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setPickerOpen(true)}
              disabled={busy}
              data-testid="responsible-managers-add-first"
            >
              {t("resp_mgr.add_first")}
            </button>
          </div>
        ) : (
          <>
            <table
              className="data-table data-table-dense assign-table"
              data-testid="responsible-managers-list"
            >
              <thead>
                <tr>
                  <th className="assign-table-person">
                    {t("resp_mgr.col_person")}
                  </th>
                  <th className="assign-table-since">
                    {t("resp_mgr.col_since")}
                  </th>
                  <th className="assign-table-actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} data-testid="responsible-manager-row">
                    <td
                      className="assign-table-person"
                      title={row.user_full_name?.trim() || row.user_email}
                    >
                      {row.user_full_name?.trim() || row.user_email}
                    </td>
                    <td className="assign-table-since">
                      {row.assigned_at?.slice(0, 10) ?? "-"}
                    </td>
                    <td className="assign-table-actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void handleRemove(row.user_id)}
                        disabled={busy}
                        data-testid="responsible-manager-remove"
                      >
                        <X size={13} strokeWidth={2.5} aria-hidden="true" />
                        {t("resp_mgr.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="assign-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setPickerOpen(true)}
                disabled={busy}
                data-testid="responsible-managers-add-open"
              >
                {t("resp_mgr.add_button")}
              </button>
            </div>
          </>
        )}
      </div>

      {/* W13 — the picker is a MODAL. "You click something on the right
          and it appears at the far left of the page."
          Candidates EXCLUDE everyone already on the ticket, so the same
          person cannot be added twice -- prevented where the choice is
          made, not reported afterwards. No date is asked for: a date
          nobody needs in order to assign belongs to editing, later. */}
      {pickerOpen && (
        <div
          className="ew-plan-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={t("resp_mgr.add_button")}
          data-testid="responsible-managers-dialog"
        >
          <div className="card ew-plan-dialog">
            <h3 className="section-title ew-plan-dialog-title">
              {t("resp_mgr.add_button")}
            </h3>
            <div className="assign-picker">
              {candidates.length === 0 ? (
                <p className="muted small" data-testid="responsible-managers-none-left">
                  {t("resp_mgr.no_candidates")}
                </p>
              ) : (
                candidates.map((manager) => (
                  <label key={manager.id} className="assign-picker-row">
                    <input
                      type="checkbox"
                      className="checkbox-input"
                      checked={picked.includes(manager.id)}
                      onChange={(event) =>
                        setPicked((current) =>
                          event.target.checked
                            ? [...current, manager.id]
                            : current.filter((id) => id !== manager.id),
                        )
                      }
                      data-testid="responsible-managers-candidate"
                    />
                    <span>{manager.full_name?.trim() || manager.email}</span>
                  </label>
                ))
              )}
            </div>
            <div className="ew-plan-actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setPicked([]);
                  setPickerOpen(false);
                }}
                disabled={busy}
                data-testid="responsible-managers-cancel"
              >
                {t("common:cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void handleAdd()}
                disabled={busy || picked.length === 0}
                data-testid="responsible-managers-confirm"
              >
                {t("resp_mgr.add_confirm", { count: picked.length })}
              </button>
            </div>
          </div>
        </div>
      )}
    </CollapsibleCard>
  );
}
