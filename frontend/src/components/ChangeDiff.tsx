/**
 * Sprint 28 Batch 15.1 — human-readable AuditLog diff.
 *
 * The audit log page renders `log.changes` as a JSON blob today,
 * producing output like `{"language":{"after":"en","before":"nl"}}`.
 * That's accurate but unreadable. This component takes the same
 * `Record<field, { before, after }>` shape and renders a tidy
 * before → after table.
 *
 * Field names default to `prettyEnum(field)`; callers can override
 * via `fieldLabel` to wire up i18n (e.g. `t("access_role.label")`
 * instead of `"Access role"`). Same for enum-shaped values via
 * `valueLabel` — necessary so `CUSTOMER_LOCATION_MANAGER` renders as
 * the translated label instead of the raw enum.
 *
 * Deep objects fall back to a one-line summary with a `<details>`
 * toggle exposing the raw JSON, so we still never throw on a
 * malformed payload.
 */
import { useTranslation } from "react-i18next";
import { prettyEnum } from "../lib/enumLabels";

export interface ChangeDiffProps {
  changes: Record<string, unknown> | null | undefined;
  /** Optional translator for field names. Defaults to `prettyEnum`. */
  fieldLabel?: (fieldName: string) => string;
  /**
   * Optional translator for enum-shaped values. Receives the raw
   * field name + the raw value. Return `null` to fall through to the
   * default rendering.
   */
  valueLabel?: (fieldName: string, value: unknown) => string | null;
  /** Test id attached to the wrapping element. */
  testId?: string;
}

interface ChangeRow {
  field: string;
  before: unknown;
  after: unknown;
}

function isChangeShape(
  value: unknown,
): value is { before?: unknown; after?: unknown } {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const keys = Object.keys(value as Record<string, unknown>);
  // We accept rows that have at least one of `before` / `after`.
  return keys.some((k) => k === "before" || k === "after");
}

function parseChanges(
  changes: Record<string, unknown> | null | undefined,
): ChangeRow[] {
  if (!changes || typeof changes !== "object") {
    return [];
  }
  const rows: ChangeRow[] = [];
  for (const [field, raw] of Object.entries(changes)) {
    if (isChangeShape(raw)) {
      const inner = raw as { before?: unknown; after?: unknown };
      rows.push({ field, before: inner.before, after: inner.after });
    } else {
      // Fallback — not a {before,after} row. Represent as a single
      // "value" cell so the operator still sees what was logged.
      rows.push({ field, before: undefined, after: raw });
    }
  }
  return rows;
}

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

interface ValueCellProps {
  field: string;
  value: unknown;
  valueLabel?: ChangeDiffProps["valueLabel"];
}

function ValueCell({ field, value, valueLabel }: ValueCellProps) {
  if (value === undefined || value === null || value === "") {
    return <span className="change-diff-empty">—</span>;
  }

  if (valueLabel) {
    const translated = valueLabel(field, value);
    if (translated !== null && translated !== undefined) {
      return <span>{translated}</span>;
    }
  }

  if (typeof value === "boolean") {
    return <span>{value ? "true" : "false"}</span>;
  }

  if (typeof value === "number") {
    return <span>{String(value)}</span>;
  }

  if (typeof value === "string") {
    return <span>{value}</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="change-diff-empty">—</span>;
    }
    if (value.every(isPrimitive)) {
      return <span>{value.map((v) => String(v)).join(", ")}</span>;
    }
    return (
      <details className="change-diff-details">
        <summary>{`${value.length} items`}</summary>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </details>
    );
  }

  // Object — render a compact summary + JSON details.
  const keys = Object.keys(value as Record<string, unknown>);
  const summary = keys.length === 0 ? "{}" : `{ ${keys.length} keys }`;
  return (
    <details className="change-diff-details">
      <summary>{summary}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function ChangeDiff({
  changes,
  fieldLabel,
  valueLabel,
  testId,
}: ChangeDiffProps) {
  const { t } = useTranslation("common");
  const rows = parseChanges(changes);

  if (rows.length === 0) {
    return (
      <div className="change-diff change-diff-empty-block" data-testid={testId}>
        {t("change_diff.empty")}
      </div>
    );
  }

  return (
    <dl className="change-diff" data-testid={testId}>
      {rows.map((row) => (
        <div className="change-diff-row" key={row.field}>
          <dt className="change-diff-field">
            {fieldLabel ? fieldLabel(row.field) : prettyEnum(row.field)}
          </dt>
          <dd className="change-diff-values">
            <span className="change-diff-before">
              <ValueCell
                field={row.field}
                value={row.before}
                valueLabel={valueLabel}
              />
            </span>
            <span className="change-diff-arrow" aria-hidden="true">
              →
            </span>
            <span className="change-diff-after">
              <ValueCell
                field={row.field}
                value={row.after}
                valueLabel={valueLabel}
              />
            </span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

