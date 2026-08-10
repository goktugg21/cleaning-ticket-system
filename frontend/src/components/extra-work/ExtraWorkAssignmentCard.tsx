/**
 * Sprint 157 §2 — "who is on this request", on the Extra Work detail
 * page.
 *
 * Read-only until the operator presses Edit, like every other list since
 * Sprint 155 §4: outside edit mode there are no remove buttons and no
 * Add, so a mis-click cannot take somebody off a job.
 *
 * The candidate list is the company's employees, fetched from the Sprint
 * 156 §1 endpoint. That endpoint answers "who works for this company"
 * through all three attachments (company membership, building
 * assignments, building visibility), which is exactly the question the
 * server's own `user_is_in_company` check asks when it validates the
 * write — so the picker offers precisely what the endpoint will accept,
 * and the operator never sees an option that always fails.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  bulkAssignExtraWork,
  listExtraWorkAssignmentCandidates,
  listExtraWorkAssignments,
} from "../../api/extraWork";
import type {
  AssignmentCandidate,
  ExtraWorkAssignment,
  ExtraWorkAssignmentRole,
} from "../../api/types";
import { BoundedList } from "../BoundedList";
import { EditModeToggle } from "../EditModeToggle";
import { useEditMode } from "../../lib/useEditMode";
import { AssignPeopleDialog } from "./AssignPeopleDialog";

export function ExtraWorkAssignmentCard({ extraWorkId }: { extraWorkId: number }) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [rows, setRows] = useState<ExtraWorkAssignment[]>([]);
  // Keyed by ROLE: the eligible people differ per role, so one
  // cached list would show a worker in the manager picker.
  const [candidates, setCandidates] = useState<
    Partial<Record<ExtraWorkAssignmentRole, AssignmentCandidate[]>>
  >({});
  const [pickerRole, setPickerRole] =
    useState<ExtraWorkAssignmentRole>("WORKER");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  const edit = useEditMode(rows.map((r) => r.id));

  // A reload TOKEN rather than a `load()` the effect calls. Calling an
  // async loader from an effect body trips
  // `react-hooks/set-state-in-effect` — ESLint cannot see that the
  // setState happens in a later microtask — and the frozen baseline
  // means the choice is between an eslint-disable and writing it the way
  // the rest of this codebase does. The fetch is inlined with a
  // `cancelled` flag, exactly like `DocumentsFilePane`, and a refresh is
  // a token bump.
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    let cancelled = false;
    listExtraWorkAssignments(extraWorkId)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [extraWorkId, reloadKey]);

  // Sprint 158 §1 — the SERVER decides who is eligible, per role, from
  // the request's building. The client never computes it, which is what
  // makes "offerable" and "acceptable" the same list.
  const loadCandidates = useCallback(
    async (role: ExtraWorkAssignmentRole) => {
      if (candidates[role]) return;
      try {
        const rows = await listExtraWorkAssignmentCandidates(extraWorkId, role);
        setCandidates((current) => ({ ...current, [role]: rows }));
      } catch (err) {
        setError(getApiError(err));
      }
    },
    [candidates, extraWorkId],
  );

  async function openAdd() {
    setError("");
    setAddOpen(true);
    await loadCandidates(pickerRole);
  }

  async function runAssign(
    userIds: number[],
    role: ExtraWorkAssignmentRole,
    mode: "assign" | "unassign",
  ) {
    setBusy(true);
    setError("");
    try {
      await bulkAssignExtraWork({
        requests: [extraWorkId],
        users: userIds,
        role,
        mode,
      });
      setAddOpen(false);
      reload();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // Already-assigned people are not offered again. The server would
  // count a repeat as `already_assigned` rather than failing, so this is
  // tidiness rather than correctness — but an option that provably does
  // nothing should not be in the list.
  // Already-assigned people are not offered again — per ROLE, because
  // the same person may legitimately be a worker and a manager.
  const assignedIdsForRole = new Set(
    rows.filter((r) => r.role === pickerRole).map((r) => r.user_id),
  );

  return (
    <section
      className="card"
      data-testid="extra-work-assignments-card"
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">{t("assign.card_title")}</div>
          <div className="section-head-sub">{t("assign.card_desc")}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {(edit.editMode || rows.length === 0) && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={openAdd}
              disabled={busy}
              data-testid="extra-work-assign-add"
            >
              {t("assign.button")}
            </button>
          )}
          {rows.length > 0 && (
            <EditModeToggle
              editMode={edit.editMode}
              onToggle={edit.toggleMode}
              disabled={busy}
              testId="extra-work-assign-edit-toggle"
            />
          )}
        </div>
      </div>

      {error && (
        <div
          className="alert-error"
          role="alert"
          style={{ marginBottom: 12 }}
          data-testid="extra-work-assign-error"
        >
          {error}
        </div>
      )}

      <BoundedList
        size="md"
        count={rows.length}
        ariaLabel={t("assign.card_title")}
        testIdPrefix="extra-work-assignments"
        className="table-wrap"
        emptyState={
          <p className="muted small" style={{ padding: "12px 0", margin: 0 }}>
            {t("assign.empty")}
          </p>
        }
      >
        <table className="data-table data-table-dense">
          <thead>
            <tr>
              <th>{t("common:users.col_full_name")}</th>
              <th>{t("assign.col_role")}</th>
              <th>{t("common:users.col_email")}</th>
              <th>{t("common:customer_contacts.field_phone")}</th>
              {edit.editMode && (
                <th aria-label={t("common:admin.col_actions")} />
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="td-subject">
                  {/* §9's rule: a row reaches the thing it names. */}
                  <Link to={`/admin/users/${row.user_id}`}>
                    {row.user_full_name || row.user_email}
                  </Link>
                </td>
                <td>{t(`assign.role_${row.role.toLowerCase()}`)}</td>
                <td>
                  <a href={`mailto:${row.user_email}`}>{row.user_email}</a>
                </td>
                <td>
                  {row.user_phone ? (
                    <a href={`tel:${row.user_phone}`}>{row.user_phone}</a>
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </td>
                {edit.editMode && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => runAssign([row.user_id], row.role, "unassign")}
                      disabled={busy}
                      data-testid={`extra-work-assign-remove-${row.id}`}
                    >
                      {t("assign.remove")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </BoundedList>

      {addOpen && (
        <AssignPeopleDialog
          requestCount={1}
          candidates={(candidates[pickerRole] ?? [])
            .filter((person) => !assignedIdsForRole.has(person.id))
            .map((person) => ({
              id: person.id,
              label: person.full_name || person.email,
              sublabel: person.email,
            }))}
          role={pickerRole}
          onRoleChange={(role) => {
            setPickerRole(role);
            void loadCandidates(role);
          }}
          busy={busy}
          error={error}
          onCancel={() => setAddOpen(false)}
          onConfirm={(userIds, role) => runAssign(userIds, role, "assign")}
        />
      )}
    </section>
  );
}
