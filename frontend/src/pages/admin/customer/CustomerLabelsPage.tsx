// Sprint 128 — provider-side per-customer Extra Work label management.
// ONE page, two sections (Afdelingen + Werktypes), each a small CRUD list.
// Provider WRITE (SUPER_ADMIN / COMPANY_ADMIN); BUILDING_MANAGER READ (they
// hold the relabel action) — the route is CustomerReadRoute (SA/CA/BM) and
// the write controls are gated on isProviderAdmin, so the page renders
// read-only for a BM. Backend: /api/customers/<id>/{departments,work-types}/.
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getCustomer } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import {
  createLabel,
  deleteLabel,
  labelErrorCode,
  listLabels,
  updateLabel,
  type LabelKind,
} from "../../../api/customerLabels";
import type { CustomerAdmin, CustomerLabel } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { isProviderAdmin } from "../../../auth/permissions";
import { BoundedList } from "../../../components/BoundedList";
import {
  ConfirmDialog,
  type ConfirmDialogHandle,
} from "../../../components/ConfirmDialog";
import { CustomerSubPageHeader } from "./CustomerSubPageHeader";
import { customerLabelName } from "../../../lib/customerLabelName";

/** Map a coded label API error to an i18n key, else null (caller falls back
 *  to getApiError). Both list kinds share the same message keys. */
function labelErrorKey(error: unknown): string | null {
  const code = labelErrorCode(error);
  switch (code) {
    case "department_name_conflict":
    case "work_type_name_conflict":
      return "labels.error_name_conflict";
    case "label_name_required":
      return "labels.error_name_required";
    case "department_protected":
    case "work_type_protected":
      return "labels.error_in_use";
    default:
      return null;
  }
}

interface LabelSectionProps {
  customerId: number;
  kind: LabelKind;
  title: string;
  help: string;
  canWrite: boolean;
}

function LabelSection({
  customerId,
  kind,
  title,
  help,
  canWrite,
}: LabelSectionProps) {
  const { t } = useTranslation("common");
  const [labels, setLabels] = useState<CustomerLabel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CustomerLabel | null>(null);
  // ConfirmDialog is imperative: mounted-but-invisible until `.open()` calls
  // showModal(). The Sprint 128 version rendered it conditionally without ever
  // opening it, so Delete did nothing — hold a handle and open it explicitly.
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  // A refetch counter drives the load effect. Mutations bump it (a plain
  // event-handler setState — NOT a set-state-in-effect) rather than calling a
  // state-setting loader from an effect (CLAUDE.md §3).
  const [refetchTick, setRefetchTick] = useState(0);
  const refetch = () => setRefetchTick((n) => n + 1);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        // Management view: unfiltered, so archived rows stay visible +
        // reactivatable (the picker requests is_active=true separately).
        const rows = await listLabels(customerId, kind);
        if (!cancelled) {
          setLabels(rows);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [customerId, kind, refetchTick]);

  function showError(err: unknown) {
    const key = labelErrorKey(err);
    setError(key ? t(key) : getApiError(err));
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    setError("");
    try {
      await createLabel(customerId, kind, {
        name: newName.trim(),
        description: newDescription.trim(),
      });
      setNewName("");
      setNewDescription("");
      refetch();
    } catch (err) {
      showError(err);
    } finally {
      setCreating(false);
    }
  }

  function startEdit(row: CustomerLabel) {
    setEditingId(row.id);
    setEditName(row.name);
    setEditDescription(row.description);
    setError("");
  }

  async function saveEdit(row: CustomerLabel) {
    if (!editName.trim()) return;
    setBusyId(row.id);
    setError("");
    try {
      await updateLabel(customerId, kind, row.id, {
        name: editName.trim(),
        description: editDescription.trim(),
      });
      setEditingId(null);
      refetch();
    } catch (err) {
      showError(err);
    } finally {
      setBusyId(null);
    }
  }

  async function toggleActive(row: CustomerLabel) {
    setBusyId(row.id);
    setError("");
    try {
      await updateLabel(customerId, kind, row.id, {
        is_active: !row.is_active,
      });
      refetch();
    } catch (err) {
      showError(err);
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    // The confirm button does not auto-close the (imperative) dialog; close it
    // ourselves in both branches.
    try {
      await deleteLabel(customerId, kind, deleteTarget.id);
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
      refetch();
    } catch (err) {
      // The in-use case (…_protected) surfaces the archive hint in the section
      // error; close the dialog and show it.
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
      showError(err);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }} data-testid={`labels-section-${kind}`}>
      <div className="form-section">
        <div className="form-section-title">{title}</div>
        <p className="muted small" style={{ marginTop: 0 }}>
          {help}
        </p>

        {error && (
          <div className="alert-error" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        {canWrite && (
          <form
            onSubmit={handleCreate}
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "flex-end",
              gap: 8,
              marginBottom: 12,
            }}
          >
            <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span className="muted small">{t("labels.col_name")}</span>
              <input
                className="field-input"
                value={newName}
                maxLength={128}
                placeholder={t("labels.add_name_placeholder")}
                onChange={(e) => setNewName(e.target.value)}
                data-testid={`labels-new-name-${kind}`}
              />
            </label>
            <label
              style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 180 }}
            >
              <span className="muted small">{t("labels.col_description")}</span>
              <input
                className="field-input"
                value={newDescription}
                placeholder={t("labels.add_description_placeholder")}
                onChange={(e) => setNewDescription(e.target.value)}
                data-testid={`labels-new-description-${kind}`}
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={creating || !newName.trim()}
              data-testid={`labels-add-${kind}`}
            >
              {creating ? t("labels.adding") : t("labels.add_button")}
            </button>
          </form>
        )}

        {loading ? (
          <p className="muted small">{t("labels.loading")}</p>
        ) : (
          <BoundedList
            size="md"
            count={labels.length}
            ariaLabel={title}
            testIdPrefix={`labels-list-${kind}`}
            emptyState={<p className="muted small">{t("labels.empty")}</p>}
          >
            <ul className="multi-select-list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {labels.map((row) => (
                <li
                  key={row.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 4px",
                    borderBottom: "1px solid var(--border-subtle, #eee)",
                    opacity: row.is_active ? 1 : 0.6,
                  }}
                  data-testid={`labels-row-${kind}-${row.id}`}
                >
                  {editingId === row.id ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, flex: 1 }}>
                      <input
                        className="field-input"
                        value={editName}
                        maxLength={128}
                        onChange={(e) => setEditName(e.target.value)}
                        data-testid={`labels-edit-name-${kind}`}
                      />
                      <input
                        className="field-input"
                        value={editDescription}
                        style={{ flex: 1, minWidth: 160 }}
                        onChange={(e) => setEditDescription(e.target.value)}
                        data-testid={`labels-edit-description-${kind}`}
                      />
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={busyId === row.id || !editName.trim()}
                        onClick={() => void saveEdit(row)}
                      >
                        {busyId === row.id ? t("labels.saving") : t("labels.save")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setEditingId(null)}
                      >
                        {t("labels.cancel")}
                      </button>
                    </div>
                  ) : (
                    <>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 500 }}>
                          {customerLabelName(row.name, t)}
                          {!row.is_active && (
                            <span className="cell-tag cell-tag-closed" style={{ marginLeft: 8 }}>
                              <i />
                              {t("labels.badge_archived")}
                            </span>
                          )}
                        </div>
                        {row.description && (
                          <div className="muted small">{row.description}</div>
                        )}
                      </div>
                      {canWrite && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => startEdit(row)}
                          >
                            {t("labels.edit")}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={busyId === row.id}
                            onClick={() => void toggleActive(row)}
                          >
                            {row.is_active ? t("labels.archive") : t("labels.unarchive")}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => {
                              setDeleteTarget(row);
                              deleteDialogRef.current?.open();
                            }}
                          >
                            {t("labels.delete")}
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </BoundedList>
        )}
      </div>

      {/* Rendered UNCONDITIONALLY (imperative dialog); shown via
          deleteDialogRef.current.open(). ConfirmDialog owns its own
          open-on-unmount cleanup. */}
      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("labels.delete_confirm_title")}
        body={
          deleteTarget
            ? t("labels.delete_confirm_body", { name: deleteTarget.name })
            : ""
        }
        confirmLabel={t("labels.delete_confirm_button")}
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

export function CustomerLabelsPage() {
  const { t } = useTranslation("common");
  const { id } = useParams();
  const numericId = Number(id);
  const { me } = useAuth();
  const canWrite = isProviderAdmin(me?.role);
  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCustomer(numericId)
      .then((data) => {
        if (!cancelled) setCustomer(data);
      })
      .catch(() => {
        // The header falls back to the empty name; each section surfaces its
        // own load error.
      });
    return () => {
      cancelled = true;
    };
  }, [numericId]);

  return (
    <div className="page">
      <CustomerSubPageHeader
        customerName={customer?.name ?? ""}
        isActive={customer?.is_active ?? true}
        eyebrow={t("nav.customer_submenu.labels")}
      />
      {!canWrite && (
        <p className="muted small" data-testid="labels-read-only-note">
          {t("labels.read_only_note")}
        </p>
      )}
      <LabelSection
        customerId={numericId}
        kind="department"
        title={t("labels.section_departments")}
        help={t("labels.section_departments_help")}
        canWrite={canWrite}
      />
      <LabelSection
        customerId={numericId}
        kind="work_type"
        title={t("labels.section_work_types")}
        help={t("labels.section_work_types_help")}
        canWrite={canWrite}
      />
    </div>
  );
}
