/**
 * Sprint 154 §G.2 — one card per set of people (or customers) linked to
 * a building.
 *
 * FOUR relations, ONE component. Customers, Managers, Staff and Contact
 * persons differ only in where their rows come from, what a row is
 * called, and what the candidate list is — so those are props, and
 * everything structural (the bounded list, the per-row remove, the
 * checkbox + bulk remove, the Add multi-select, the confirm) is written
 * once. Four cards written four times is four places for the "remove"
 * button to behave differently.
 *
 * NONE of these models are new. `CustomerBuildingMembership`,
 * `BuildingManagerAssignment`, `BuildingStaffVisibility` and
 * `ContactBuildingLink` have all existed for many sprints; staff↔building
 * has been editable from the USER's page since Sprint 23A. This card
 * surfaces existing relations from the building's side, which is the one
 * direction that was missing.
 *
 * Every list here is a SERVER collection, so every one is
 * `BoundedList`-bounded (CLAUDE.md §8). A building in a shopping centre
 * can have dozens of contacts.
 */
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { bulkLinkBuildings } from "../../../api/admin";
import type { BuildingLinkRelation } from "../../../api/types";
import { BoundedList } from "../../../components/BoundedList";
import { BulkAssignDialog } from "../../../components/BulkAssignDialog";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EditModeToggle } from "../../../components/EditModeToggle";
import type { EntityPickerOption } from "../../../components/EntityPicker";
import { MultiSelectToolbar } from "../../../components/MultiSelectToolbar";
import { useEditMode } from "../../../lib/useEditMode";

/** One rendered row, flattened from whichever membership model backs it. */
export interface RelationRow {
  /** The membership row id — used for selection only. */
  linkId: number;
  /** The id the bulk endpoint wants as a `target`. NOT the link id. */
  targetId: number;
  name: string;
  email?: string;
  phone?: string;
  meta?: string;
}

export function BuildingRelationCard({
  buildingId,
  relation,
  title,
  description,
  emptyText,
  rows,
  candidates,
  addTitle,
  testIdPrefix,
  disabled,
  onChanged,
}: {
  buildingId: number;
  relation: BuildingLinkRelation;
  title: string;
  description: string;
  emptyText: string;
  rows: RelationRow[];
  /** Everything linkable that is not already linked. The caller computes
   *  the difference, because only it knows the candidate universe. */
  candidates: EntityPickerOption[];
  addTitle: string;
  testIdPrefix: string;
  disabled?: boolean;
  /** Refetch this card's rows (and the page's counts). */
  onChanged: () => void | Promise<void>;
}) {
  const { t } = useTranslation("common");
  // Sprint 155 §4 — the shared Edit-mode controller. `editMode` and the
  // selection are both DERIVED there; see lib/useEditMode.ts for why
  // neither may be raw state.
  const edit = useEditMode(rows.map((r) => r.linkId));
  const [addOpen, setAddOpen] = useState(false);
  const [addIds, setAddIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const removeDialogRef = useRef<ConfirmDialogHandle>(null);

  const selectedTargetIds = rows
    .filter((r) => edit.isSelected(r.linkId))
    .map((r) => r.targetId);

  /** Where a row's NAME links to, per relation. Null = no detail page
   *  exists for that kind of row, and none is invented. */
  const detailPath: ((row: RelationRow) => string) | null =
    relation === "customers"
      ? (row) => `/admin/customers/${row.targetId}`
      : relation === "managers" || relation === "staff"
        ? (row) => `/admin/users/${row.targetId}`
        : null;

  async function runLink(targets: number[], mode: "link" | "unlink") {
    setBusy(true);
    setError("");
    try {
      await bulkLinkBuildings({
        buildings: [buildingId],
        relation,
        targets,
        mode,
      });
      // Local selection cleared BEFORE the refetch: the server call has
      // already succeeded, so the rows that were selected are gone.
      edit.clear();
      setAddIds([]);
      setAddOpen(false);
      removeDialogRef.current?.close();
      await onChanged();
    } catch (err) {
      setError(getApiError(err));
      removeDialogRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="card"
      data-testid={`${testIdPrefix}-card`}
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">{title}</div>
          <div className="section-head-sub">{description}</div>
        </div>
        {/* Sprint 155 §4 — nothing on this card is directly editable any
            more. Sprint 154 showed a checkbox on every row and an Add
            button at all times, so a mis-click removed a link with no
            intent step in between. Add and the whole selection UI now
            live INSIDE edit mode; outside it the card is a clean
            read-only list.

            One toggle, not two controls: the same button is Edit and
            Done, which is the pattern CustomerPricingPage established
            and the one operators here have already learnt. */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {edit.editMode && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setAddIds([]);
                setError("");
                setAddOpen(true);
              }}
              disabled={disabled || busy}
              data-testid={`${testIdPrefix}-add-button`}
            >
              {t("building_detail.add")}
            </button>
          )}
          <EditModeToggle
            editMode={edit.editMode}
            onToggle={edit.toggleMode}
            disabled={disabled || busy}
            testId={`${testIdPrefix}-edit-toggle`}
          />
        </div>
      </div>
      {/* An empty card has no rows to select, so `editMode` derives to
          false and the Add button above would be unreachable. This is
          the one path into it. */}
      {edit.editModeRequested && rows.length === 0 && (
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          style={{ marginBottom: 8 }}
          onClick={() => {
            setAddIds([]);
            setError("");
            setAddOpen(true);
          }}
          disabled={disabled || busy}
          data-testid={`${testIdPrefix}-add-button-empty`}
        >
          {t("building_detail.add")}
        </button>
      )}

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

      {edit.editMode && (
        <div className="list-edit-bar">
          <MultiSelectToolbar
            selectedCount={edit.selection.length}
            onSelectAll={edit.selectAll}
            onClearAll={edit.clear}
            disabled={busy}
            actions={[
              {
                key: "remove",
                label: t("building_detail.remove_selected"),
                destructive: true,
                onClick: () => removeDialogRef.current?.open(),
              },
            ]}
            testIdPrefix={`${testIdPrefix}-bulk`}
          />
        </div>
      )}

      <BoundedList
        size="md"
        count={rows.length}
        ariaLabel={title}
        testIdPrefix={testIdPrefix}
        className="table-wrap"
        emptyState={
          <p className="muted small" style={{ padding: "12px 0", margin: 0 }}>
            {emptyText}
          </p>
        }
      >
        <table className="data-table data-table-dense">
          <thead>
            {/* The checkbox column EXISTS only inside edit mode, so the
                read view keeps exactly the geometry it had before —
                same rule as the pricing list's edit mode. */}
            <tr>
              {edit.editMode && (
                <th className="th-select">
                  <input
                    type="checkbox"
                    checked={edit.allSelected}
                    onChange={() =>
                      edit.allSelected ? edit.clear() : edit.selectAll()
                    }
                    disabled={rows.length === 0 || busy}
                    aria-label={title}
                    data-testid={`${testIdPrefix}-select-all`}
                  />
                </th>
              )}
              <th>{t("admin.col_name")}</th>
              <th>{t("users.col_email")}</th>
              <th>{t("customer_contacts.field_phone")}</th>
              {edit.editMode && <th aria-label={t("admin.col_actions")} />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.linkId}>
                {edit.editMode && (
                  <td className="td-select">
                    <input
                      type="checkbox"
                      checked={edit.isSelected(row.linkId)}
                      onChange={() => edit.toggle(row.linkId)}
                      disabled={busy}
                      aria-label={t("building_detail.select_row", {
                        name: row.name,
                      })}
                      data-testid={`${testIdPrefix}-select-${row.linkId}`}
                    />
                  </td>
                )}
                <td className="td-subject">
                  {/* Sprint 156 §7 — the row reaches the thing it names.
                      These four cards listed people and customers with
                      no way to open any of them, so "who is this staff
                      member" meant leaving the building page and
                      searching the Users list by hand.

                      `detailPath` is null for contacts: a Contact is not
                      a User and has no detail page of its own — it is
                      edited on the customer's Contacts sub-page — so
                      linking one would be inventing a route. Reported
                      rather than faked. */}
                  {detailPath ? (
                    <Link
                      to={detailPath(row)}
                      data-testid={`${testIdPrefix}-open-${row.targetId}`}
                    >
                      {row.name}
                    </Link>
                  ) : (
                    row.name
                  )}
                  {row.meta && (
                    <span
                      className="muted small"
                      style={{ display: "block", marginTop: 2 }}
                    >
                      {row.meta}
                    </span>
                  )}
                </td>
                <td>
                  {row.email ? (
                    <a href={`mailto:${row.email}`}>{row.email}</a>
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </td>
                <td>
                  {/* Empty renders an em dash, never a blank cell — a
                      blank one reads as a rendering bug. */}
                  {row.phone ? (
                    <a href={`tel:${row.phone}`}>{row.phone}</a>
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </td>
                {edit.editMode && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => runLink([row.targetId], "unlink")}
                      disabled={busy || disabled}
                      data-testid={`${testIdPrefix}-remove-${row.linkId}`}
                    >
                      {t("admin_form.remove")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </BoundedList>

      {/* Rendered UNCONDITIONALLY and ref-driven (CLAUDE.md §3). */}
      <ConfirmDialog
        ref={removeDialogRef}
        title={t("building_detail.remove_title")}
        body={t("building_detail.remove_body", {
          count: edit.selection.length,
        })}
        confirmLabel={t("building_detail.remove_selected")}
        onConfirm={() => runLink(selectedTargetIds, "unlink")}
        busy={busy}
        destructive
      />

      {addOpen && (
        <BulkAssignDialog
          title={addTitle}
          summary={t("building_detail.add_summary", { count: addIds.length })}
          options={candidates}
          selectedIds={addIds}
          onChange={setAddIds}
          onCancel={() => setAddOpen(false)}
          onConfirm={() => runLink(addIds, "link")}
          confirmLabel={t("bulk_link.confirm")}
          busy={busy}
          error={error}
          emptyText={t("building_detail.no_candidates")}
          testIdPrefix={`${testIdPrefix}-add`}
        />
      )}
    </section>
  );
}
