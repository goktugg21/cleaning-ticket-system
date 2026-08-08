/**
 * Sprint 154 §D/§E — edit one or more fields across many rows at once.
 *
 * THE RULE THIS COMPONENT EXISTS TO ENFORCE: every field defaults to
 * "leave unchanged", and a field left on that default is not sent at all.
 * A bulk edit that silently overwrote a field the operator did not touch
 * would be the worst kind of bug — it looks like it worked, and the
 * damage is spread across every row they selected.
 *
 * That is why the value type is `string` with `""` meaning "untouched",
 * and why `buildPatch` drops empties rather than sending them. The server
 * additionally allow-lists what it will accept and 400s on anything else
 * (`buildings/views_bulk.py`), so a typo here is a rejection, not a
 * silent no-op.
 *
 * A non-native overlay, conditionally mounted — see `BulkAssignDialog`
 * for why that is correct here and a native `<dialog>` would not be.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export interface BulkEditField {
  /** The wire key. Must be on the server's allow-list. */
  key: string;
  label: string;
  /** A picker (default) or a free-text box. A text field's "leave
   *  unchanged" is simply an empty box — which is why a bulk edit can
   *  never CLEAR a text field to "", only set it to something. Clearing
   *  one row's city is a single-row edit; doing it to twenty at once is
   *  almost always a mistake, so the affordance is deliberately absent. */
  type?: "select" | "text";
  placeholder?: string;
  options?: { value: string; label: string }[];
}

export function BulkEditDialog({
  title,
  intro,
  fields,
  onCancel,
  onSubmit,
  busy,
  error,
  testIdPrefix,
}: {
  title: string;
  intro: string;
  fields: BulkEditField[];
  onCancel: () => void;
  onSubmit: (patch: Record<string, string>) => void;
  busy?: boolean;
  error?: string;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  // "" is the sentinel for "leave unchanged" — never a real value.
  const [values, setValues] = useState<Record<string, string>>({});

  const patch = useMemo(() => {
    const out: Record<string, string> = {};
    for (const field of fields) {
      const value = (values[field.key] ?? "").trim();
      if (value) out[field.key] = value;
    }
    return out;
  }, [fields, values]);

  const nothingChosen = Object.keys(patch).length === 0;

  return (
    <div
      data-testid={`${testIdPrefix}-modal`}
      role="dialog"
      aria-modal="true"
      aria-label={title}
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
      <div className="card" style={{ maxWidth: 520, width: "100%", padding: 24 }}>
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>{title}</h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {intro}
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

        {fields.map((field) =>
          field.type === "text" ? (
            <div className="field" key={field.key}>
              <label
                className="field-label"
                htmlFor={`${testIdPrefix}-${field.key}`}
              >
                {field.label}
              </label>
              <input
                id={`${testIdPrefix}-${field.key}`}
                className="field-input"
                type="text"
                value={values[field.key] ?? ""}
                placeholder={field.placeholder}
                onChange={(event) =>
                  setValues((prev) => ({
                    ...prev,
                    [field.key]: event.target.value,
                  }))
                }
                disabled={busy}
                data-testid={`${testIdPrefix}-field-${field.key}`}
              />
            </div>
          ) : (
          <div className="field" key={field.key}>
            <label
              className="field-label"
              htmlFor={`${testIdPrefix}-${field.key}`}
            >
              {field.label}
            </label>
            <select
              id={`${testIdPrefix}-${field.key}`}
              className="field-select"
              value={values[field.key] ?? ""}
              onChange={(event) =>
                setValues((prev) => ({
                  ...prev,
                  [field.key]: event.target.value,
                }))
              }
              disabled={busy}
              data-testid={`${testIdPrefix}-field-${field.key}`}
            >
              {/* Always first, always the default. */}
              <option value="">{t("bulk_edit.leave_unchanged")}</option>
              {(field.options ?? []).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          ),
        )}

        {nothingChosen && (
          <p className="muted small" style={{ marginTop: 4 }}>
            {t("bulk_edit.nothing_selected")}
          </p>
        )}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            marginTop: 20,
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid={`${testIdPrefix}-cancel`}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => onSubmit(patch)}
            disabled={busy || nothingChosen}
            data-testid={`${testIdPrefix}-save`}
          >
            {busy ? t("admin_form.saving") : t("admin_form.save_changes")}
          </button>
        </div>
      </div>
    </div>
  );
}
