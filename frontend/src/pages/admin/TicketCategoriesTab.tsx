import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createTicketCategory,
  deleteTicketCategory,
  listTicketCategories,
  updateTicketCategory,
} from "../../api/tickets";
import type { TicketCategory } from "../../api/types";
import type { TicketCategoryWritePayload } from "../../api/tickets";
import { BoundedList } from "../../components/BoundedList";
import { CatalogCompanySelect } from "../../components/CatalogTab";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { Toggle } from "../../components/Toggle";
import { useCatalogCompanies } from "../../lib/useCatalogCompanies";

interface FormState {
  slug: string;
  label_nl: string;
  label_en: string;
  color: string;
  sort_order: string;
  is_active: boolean;
  available_at_intake: boolean;
}

const EMPTY_FORM: FormState = {
  slug: "",
  label_nl: "",
  label_en: "",
  color: "",
  sort_order: "0",
  is_active: true,
  available_at_intake: true,
};

/** A slug the operator does not have to think about.
 *
 *  Derived from the Dutch label while the field is untouched, because
 *  the key is a machine concern and asking somebody to invent one is
 *  asking them to do the computer's job. It stays editable: a company
 *  migrating from another system may need to match an existing key. */
function slugFrom(label: string): string {
  return label
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

/**
 * W13 — "Meldingsoorten": the one classification a melding carries.
 *
 * Replaces `WorkCategoriesTab`, which managed the Sprint 185 kind-of-work
 * catalog. That catalog sat beside the `TicketType` enum, and between
 * them a melding had two overlapping classifications whose form labels
 * both read "category". A programmer of twenty years looked at the
 * ticket page and asked "Where is its category?" — there were two, and
 * neither held his answer.
 *
 * ## Not a `CatalogTab`, and why
 *
 * The five sibling catalogs are (name, active, sort) and `CatalogTab`
 * renders exactly that. This one carries two labels, a colour and the
 * intake flag, and a tab that could not set them would be a tab that
 * hides the fields that matter. `ManagedUnitsTab` and `HourTypesTab`
 * made the same call for the same reason; all three still render the
 * shared `CatalogCompanySelect`, so every catalog offers one control
 * for "which company" rather than three.
 *
 * ## One section, one table, one button
 *
 * There is no prose between the controls. The two things a reader would
 * otherwise need explaining are shown instead of described: an
 * archived row is greyed and says Archived, and a row that cannot be
 * chosen at intake carries a "Verdict" tag next to its label. The
 * modal's own intake toggle is where that is decided, next to the
 * words it applies to.
 */
export function TicketCategoriesTab() {
  const { t } = useTranslation("common");

  const { companies, companyId, setCompanyId } = useCatalogCompanies(true);
  const mustNameCompany = companies.length > 1;

  const [rows, setRows] = useState<TicketCategory[]>([]);
  const [loadError, setLoadError] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  // Derived `loading` — see `MyHoursPage` for why it is not stored.
  const fetchKey = `${showInactive}|${companyId}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== fetchKey;

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [editing, setEditing] = useState<TicketCategory | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [slugTouched, setSlugTouched] = useState(false);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<TicketCategory | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listTicketCategories({
      ...(showInactive ? {} : { is_active: "true" as const }),
      ...(companyId === "" ? {} : { company: companyId }),
    })
      .then((all) => {
        if (cancelled) return;
        setRows(all);
        setLoadError("");
        setLoadedKey(fetchKey);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoadedKey(fetchKey);
      });
    return () => {
      cancelled = true;
    };
  }, [showInactive, companyId, fetchKey]);

  /**
   * Re-read after a mutation. NEVER THROWS — the write already
   * committed, so a failed re-read must not turn a saved row into a
   * form error. Stale list plus a visible page-level message.
   */
  async function refresh() {
    try {
      setRows(
        await listTicketCategories({
          ...(showInactive ? {} : { is_active: "true" as const }),
          ...(companyId === "" ? {} : { company: companyId }),
        }),
      );
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }

  function openCreate() {
    setMode("create");
    setEditing(null);
    setForm({
      ...EMPTY_FORM,
      // Slotted after the last row, ten apart, so the operator can drop
      // one in between later without renumbering the rest.
      sort_order: String(
        rows.reduce((max, row) => Math.max(max, row.sort_order), 0) + 10,
      ),
    });
    setSlugTouched(false);
    setFormError("");
  }

  function openEdit(row: TicketCategory) {
    setMode("edit");
    setEditing(row);
    setForm({
      slug: row.slug,
      label_nl: row.label_nl,
      label_en: row.label_en,
      color: row.color,
      sort_order: String(row.sort_order),
      is_active: row.is_active,
      available_at_intake: row.available_at_intake,
    });
    setSlugTouched(true);
    setFormError("");
  }

  function closeModal() {
    setMode(null);
    setEditing(null);
    setFormError("");
  }

  function updateLabelNl(value: string) {
    setForm((prev) => ({
      ...prev,
      label_nl: value,
      // Only while the operator has not taken the key over themselves.
      slug: slugTouched ? prev.slug : slugFrom(value),
    }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!form.label_nl.trim()) {
      setFormError(t("ticket_categories.error_label_required"));
      return;
    }
    if (mode === "create" && mustNameCompany && companyId === "") {
      setFormError(t("catalog.error_company_required"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    const payload: TicketCategoryWritePayload = {
      label_nl: form.label_nl.trim(),
      label_en: form.label_en.trim(),
      color: form.color.trim(),
      sort_order: Number(form.sort_order) || 0,
      is_active: form.is_active,
      available_at_intake: form.available_at_intake,
      // The KEY is create-only. Changing it after rows point at it by
      // slug is how a mapping breaks silently, and no operator asked to.
      ...(mode === "create"
        ? {
            slug: form.slug.trim() || slugFrom(form.label_nl),
            ...(companyId === "" ? {} : { company: companyId }),
          }
        : {}),
    };
    try {
      if (mode === "create") {
        await createTicketCategory(payload);
      } else if (mode === "edit" && editing) {
        await updateTicketCategory(editing.id, payload);
      }
      await refresh();
      closeModal();
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleToggleActive(row: TicketCategory) {
    try {
      await updateTicketCategory(row.id, { is_active: !row.is_active });
      await refresh();
    } catch (err) {
      setLoadError(getApiError(err));
    }
  }

  function openDeleteDialog(row: TicketCategory) {
    setDeleteTarget(row);
    deleteDialogRef.current?.open();
  }

  function handleCancelDelete() {
    deleteDialogRef.current?.close();
    setDeleteTarget(null);
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteTicketCategory(deleteTarget.id);
      await refresh();
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      // Most often `ticket_category_in_use`: the endpoint refuses to
      // delete a category meldingen still carry and says to archive.
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <div data-testid="ticket-categories-tab">
      <div className="section-head" style={{ marginBottom: 12 }}>
        <div className="section-head-title">
          {t("ticket_categories.title")}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <CatalogCompanySelect
            companies={companies}
            companyId={companyId}
            onChange={setCompanyId}
            testId="ticket-categories-company"
          />
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Toggle
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
              data-testid="ticket-categories-show-archived"
            />
            <span className="muted small">
              {t("ticket_categories.show_archived")}
            </span>
          </label>
          {/* ONE primary action. Everything else on this tab is a
              per-row verb on the row it belongs to. */}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={openCreate}
            data-testid="ticket-categories-add"
          >
            {t("ticket_categories.add")}
          </button>
        </div>
      </div>

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <BoundedList
          size="lg"
          count={rows.length}
          ariaLabel={t("ticket_categories.title")}
          testIdPrefix="ticket-categories"
          className="table-wrap"
          emptyState={
            <div style={{ padding: "28px 20px", textAlign: "center" }}>
              <p className="muted" style={{ margin: 0 }}>
                {t("ticket_categories.empty")}
              </p>
            </div>
          }
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("ticket_categories.col_label")}</th>
                <th>{t("ticket_categories.col_label_en")}</th>
                <th>{t("ticket_categories.col_key")}</th>
                <th style={{ textAlign: "right" }}>
                  {t("ticket_categories.col_in_use")}
                </th>
                <th>{t("status")}</th>
                <th>{t("contract_hours.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} data-testid="ticket-categories-row">
                  <td className="td-subject">
                    <span
                      className="ticket-category-chip"
                      style={
                        row.color ? { background: row.color } : undefined
                      }
                      aria-hidden="true"
                    />
                    {row.label_nl}
                    {/* W13 §4 — shown, not explained. A row that cannot
                        be chosen at intake says so on the row, so the
                        rule needs no sentence above the table. */}
                    {!row.available_at_intake && (
                      <span
                        className="cell-tag cell-tag-muted"
                        style={{ marginLeft: 8 }}
                        data-testid="ticket-categories-verdict-tag"
                      >
                        {t("ticket_categories.verdict_tag")}
                      </span>
                    )}
                  </td>
                  <td className="muted small">{row.label_en || "—"}</td>
                  <td className="muted small">{row.slug}</td>
                  <td style={{ textAlign: "right" }}>{row.usage_count}</td>
                  <td>
                    <span
                      className={
                        row.is_active
                          ? "cell-tag cell-tag-normal"
                          : "cell-tag cell-tag-muted"
                      }
                    >
                      {row.is_active
                        ? t("ticket_categories.active")
                        : t("ticket_categories.archived")}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openEdit(row)}
                        data-testid="ticket-categories-edit"
                      >
                        {t("ticket_categories.edit")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => handleToggleActive(row)}
                        data-testid="ticket-categories-archive"
                      >
                        {row.is_active
                          ? t("ticket_categories.archive")
                          : t("ticket_categories.reactivate")}
                      </button>
                      {/* Delete is offered only where it can succeed:
                          the endpoint refuses to delete a category
                          meldingen still carry, and a button that
                          always errors is worse than no button. */}
                      {row.usage_count === 0 && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => openDeleteDialog(row)}
                          data-testid="ticket-categories-delete"
                        >
                          {t("contract_hours.delete")}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </BoundedList>
      )}

      {mode !== null && (
        <div
          data-testid="ticket-categories-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            mode === "create"
              ? t("ticket_categories.add")
              : t("ticket_categories.edit")
          }
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
          <form
            onSubmit={handleSubmit}
            className="card"
            style={{
              maxWidth: 520,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3
              className="section-title"
              style={{ marginTop: 0, marginBottom: 12 }}
            >
              {mode === "create"
                ? t("ticket_categories.add")
                : t("ticket_categories.edit")}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="ticket-categories-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="tc-label-nl">
                {t("ticket_categories.field_label_nl")} *
              </label>
              <input
                id="tc-label-nl"
                className="field-input"
                value={form.label_nl}
                onChange={(event) => updateLabelNl(event.target.value)}
                data-testid="ticket-categories-input-label-nl"
                required
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="tc-label-en">
                {t("ticket_categories.field_label_en")}
              </label>
              <input
                id="tc-label-en"
                className="field-input"
                value={form.label_en}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, label_en: event.target.value }))
                }
                data-testid="ticket-categories-input-label-en"
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="tc-slug">
                {t("ticket_categories.field_key")}
              </label>
              <input
                id="tc-slug"
                className="field-input"
                value={form.slug}
                onChange={(event) => {
                  setSlugTouched(true);
                  setForm((prev) => ({ ...prev, slug: event.target.value }));
                }}
                data-testid="ticket-categories-input-slug"
                /* Read-only once the row exists: rows point at a
                   category by this key, and renaming it is how a
                   mapping breaks with nothing on screen to show it. */
                readOnly={mode === "edit"}
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="tc-color">
                {t("ticket_categories.field_color")}
              </label>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  id="tc-color"
                  type="color"
                  className="field-input"
                  style={{ width: 56, padding: 2 }}
                  value={form.color || "#5a6b7a"}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, color: event.target.value }))
                  }
                  data-testid="ticket-categories-input-color"
                  disabled={formBusy}
                />
                {/* Clearing is a real choice — no chip is a valid look —
                    and a colour input cannot express "none". */}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setForm((prev) => ({ ...prev, color: "" }))}
                  disabled={formBusy || form.color === ""}
                  data-testid="ticket-categories-clear-color"
                >
                  {t("ticket_categories.clear_color")}
                </button>
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="tc-sort">
                {t("ticket_categories.field_sort_order")}
              </label>
              <input
                id="tc-sort"
                className="field-input"
                type="number"
                value={form.sort_order}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    sort_order: event.target.value,
                  }))
                }
                data-testid="ticket-categories-input-sort"
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Toggle
                  checked={form.available_at_intake}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      available_at_intake: event.target.checked,
                    }))
                  }
                  data-testid="ticket-categories-input-intake"
                  disabled={formBusy}
                />
                <span>{t("ticket_categories.field_available_at_intake")}</span>
              </label>
            </div>

            <div className="field">
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Toggle
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="ticket-categories-input-active"
                  disabled={formBusy}
                />
                <span>{t("ticket_categories.field_is_active")}</span>
              </label>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeModal}
                disabled={formBusy}
                data-testid="ticket-categories-modal-cancel"
              >
                {t("cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="ticket-categories-modal-save"
              >
                {formBusy ? t("admin_form.saving") : t("hours_week_grid.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Unconditionally rendered and ref-driven (CLAUDE.md §3): a
          native <dialog> wrapped in a condition mounts INVISIBLE and the
          trigger looks dead. */}
      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("ticket_categories.delete_confirm_title")}
        body={t("ticket_categories.delete_confirm_body")}
        confirmLabel={t("contract_hours.delete")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />
    </div>
  );
}
