// #7 Part B — the per-ticket "Responsible managers" M:N surface
// (TicketManagerAssignment), DISTINCT from the single ticket.assigned_to
// primary pointer. Lets a ticket carry several responsible BUILDING_MANAGERs.
//
// PROVIDER-MANAGEMENT ONLY: the whole section is gated on `canManage`
// (isProviderManagementRole = SA / CA / BM). The component is always
// rendered by TicketDetailPage but SELF-GATES: for STAFF / CUSTOMER_USER it
// returns null and the fetch effect early-returns, so they never see
// add/remove and never call the endpoint. A BM without the building's
// `osius.ticket.assign_staff` key gets a LIST 403 -> we hide the section
// (set `hidden`) rather than erroring the page. State is only set inside
// async callbacks (no synchronous setState in an effect body).
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
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
  const [addUserId, setAddUserId] = useState<string>("");
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

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    if (addUserId === "") return;
    setBusy(true);
    setError("");
    try {
      await addManagerAssignments(ticketId, [Number(addUserId)]);
      setAddUserId("");
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
      defaultOpen={false}
      testId="responsible-managers-section"
    >
      <div style={{ padding: "0 18px 14px" }}>
        <p className="muted small" style={{ margin: "0 0 10px" }}>
          {t("resp_mgr.desc")}
        </p>

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
          <p
            className="muted small"
            data-testid="responsible-managers-empty"
            style={{ margin: "0 0 10px" }}
          >
            {t("resp_mgr.empty")}
          </p>
        ) : (
          <ul
            data-testid="responsible-managers-list"
            style={{
              listStyle: "none",
              margin: "0 0 10px",
              padding: 0,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            {rows.map((row) => (
              <li
                key={row.id}
                className="cell-tag cell-tag-open"
                data-testid="responsible-manager-chip"
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <i />
                <span>{row.user_full_name?.trim() || row.user_email}</span>
                <button
                  type="button"
                  onClick={() => handleRemove(row.user_id)}
                  disabled={busy}
                  aria-label={t("resp_mgr.remove")}
                  data-testid="responsible-manager-remove"
                  style={{
                    border: "none",
                    background: "transparent",
                    cursor: "pointer",
                    padding: 0,
                    display: "inline-flex",
                    color: "inherit",
                  }}
                >
                  <X size={13} strokeWidth={2.5} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <form
          onSubmit={handleAdd}
          style={{ display: "flex", gap: 8, alignItems: "flex-end" }}
        >
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <label className="field-label" htmlFor="resp-mgr-add">
              {t("resp_mgr.add_label")}
            </label>
            <select
              id="resp-mgr-add"
              className="field-select"
              value={addUserId}
              onChange={(event) => setAddUserId(event.target.value)}
              disabled={busy || candidates.length === 0}
              data-testid="responsible-managers-add-select"
            >
              <option value="">
                {candidates.length === 0
                  ? t("resp_mgr.no_candidates")
                  : t("resp_mgr.add_placeholder")}
              </option>
              {candidates.map((manager) => (
                <option key={manager.id} value={manager.id}>
                  {manager.full_name?.trim() || manager.email}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            className="btn btn-secondary"
            disabled={busy || addUserId === ""}
            data-testid="responsible-managers-add-button"
          >
            {busy ? t("resp_mgr.adding") : t("resp_mgr.add_button")}
          </button>
        </form>
      </div>
    </CollapsibleCard>
  );
}
