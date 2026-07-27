import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { createManagedUnit, listManagedUnits } from "../api/admin";
import type { ManagedUnit } from "../api/types";
import { getApiError } from "../api/client";

const ADD_NEW_VALUE = "__add_new__";
const UNMANAGED_VALUE = "__unmanaged__";

export interface ManagedUnitPickerProps {
  id: string;
  companyId?: number;
  managedUnitId: number | null;
  customUnitLabel: string;
  onChange: (managedUnitId: number | null, label: string) => void;
  disabled?: boolean;
}

/**
 * Sprint 123 — replaces the free-text "Other unit" input on the
 * `Service` and `CustomerCustomPrice` forms with a picker over the
 * company's managed unit catalog, plus an inline "add new" flow so a
 * genuinely new unit does not require leaving the page.
 *
 * The current value is always shown even when it falls outside the
 * fetched active list — either because the linked unit was archived
 * after being selected, or because the row predates the catalog and
 * still carries only a free-text `custom_unit_label` with no
 * `managed_unit`. Both are pinned into the option list rather than
 * silently dropped, so opening an existing row never forces a new
 * choice just to redisplay it.
 */
export function ManagedUnitPicker({
  id,
  companyId,
  managedUnitId,
  customUnitLabel,
  onChange,
  disabled,
}: ManagedUnitPickerProps) {
  const { t } = useTranslation("common");
  const [units, setUnits] = useState<ManagedUnit[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [addError, setAddError] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  // `companyId` is expected stable for this component's mounted lifetime
  // (both call sites only mount the picker once their own company context
  // has already resolved) — the effect has no synchronous setState in its
  // body, so a caller-side company change is handled by remounting via
  // `key`, not by resetting state here (see the two call sites).
  useEffect(() => {
    let cancelled = false;
    listManagedUnits({ company: companyId, is_active: true })
      .then((data) => {
        if (cancelled) return;
        setUnits(data);
        setLoadError("");
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const hasCurrentInActiveList =
    managedUnitId !== null && units.some((u) => u.id === managedUnitId);
  const pinnedArchived =
    managedUnitId !== null && !hasCurrentInActiveList
      ? { id: managedUnitId, label: customUnitLabel }
      : null;
  const showUnmanagedPin =
    managedUnitId === null && customUnitLabel.trim() !== "";

  function startAdd() {
    setAdding(true);
    setNewLabel("");
    setAddError("");
  }

  function cancelAdd() {
    setAdding(false);
    setNewLabel("");
    setAddError("");
  }

  function handleSelectChange(value: string) {
    if (value === ADD_NEW_VALUE) {
      startAdd();
      return;
    }
    if (value === UNMANAGED_VALUE) {
      onChange(null, customUnitLabel);
      return;
    }
    const numericId = Number(value);
    const picked =
      units.find((u) => u.id === numericId) ??
      (pinnedArchived && pinnedArchived.id === numericId
        ? pinnedArchived
        : undefined);
    if (picked) {
      onChange(picked.id, picked.label);
    }
  }

  async function handleConfirmAdd(event: FormEvent) {
    event.preventDefault();
    const trimmed = newLabel.trim();
    if (!trimmed) {
      setAddError(t("managed_units.error_label_required"));
      return;
    }
    setAddBusy(true);
    setAddError("");
    try {
      const created = await createManagedUnit({
        label: trimmed,
        company: companyId,
      });
      setUnits((prev) =>
        [...prev, created].sort((a, b) => a.label.localeCompare(b.label)),
      );
      onChange(created.id, created.label);
      setAdding(false);
      setNewLabel("");
    } catch (err) {
      setAddError(getApiError(err));
    } finally {
      setAddBusy(false);
    }
  }

  if (adding) {
    return (
      <div className="field" data-testid="managed-unit-picker-add">
        <label className="field-label" htmlFor={`${id}-new-label`}>
          {t("managed_units.field_label")} *
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            id={`${id}-new-label`}
            className="field-input"
            type="text"
            maxLength={50}
            value={newLabel}
            onChange={(event) => setNewLabel(event.target.value)}
            placeholder={t("managed_units.field_label_placeholder")}
            data-testid="managed-unit-picker-new-label-input"
            disabled={addBusy}
            autoFocus
          />
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleConfirmAdd}
            disabled={addBusy}
            data-testid="managed-unit-picker-confirm-add"
          >
            {addBusy ? t("admin_form.saving") : t("managed_units.add_confirm")}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={cancelAdd}
            disabled={addBusy}
            data-testid="managed-unit-picker-cancel-add"
          >
            {t("services.cancel")}
          </button>
        </div>
        {addError && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginTop: 8 }}
            data-testid="managed-unit-picker-add-error"
          >
            {addError}
          </div>
        )}
      </div>
    );
  }

  const selectValue =
    managedUnitId !== null
      ? String(managedUnitId)
      : showUnmanagedPin
        ? UNMANAGED_VALUE
        : "";

  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {t("managed_units.field_label")} *
      </label>
      <select
        id={id}
        className="field-select"
        value={selectValue}
        onChange={(event) => handleSelectChange(event.target.value)}
        data-testid="managed-unit-picker-select"
        disabled={disabled || loading}
        required
      >
        <option value="" disabled>
          {loading
            ? t("managed_units.loading")
            : t("managed_units.select_placeholder")}
        </option>
        {pinnedArchived && (
          <option value={String(pinnedArchived.id)}>
            {t("managed_units.archived_option", {
              label: pinnedArchived.label,
            })}
          </option>
        )}
        {showUnmanagedPin && (
          <option value={UNMANAGED_VALUE}>
            {t("managed_units.unmanaged_option", { label: customUnitLabel })}
          </option>
        )}
        {units.map((unit) => (
          <option key={unit.id} value={unit.id}>
            {unit.label}
          </option>
        ))}
        <option value={ADD_NEW_VALUE}>
          {t("managed_units.add_new_option")}
        </option>
      </select>
      {loadError && (
        <div className="alert-error" role="alert" style={{ marginTop: 8 }}>
          {loadError}
        </div>
      )}
    </div>
  );
}
