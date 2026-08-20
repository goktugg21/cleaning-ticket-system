/**
 * Sprint W4-Q §2 — the SLA warning thresholds screen (/admin/sla-warnings).
 *
 * The three time-driven warnings shipped in W1-B with every threshold
 * behind an environment variable. That is tunable by a deploy, which is
 * not tunable, and it was ONE number for every tenant on the platform.
 * This is the screen that fixes both.
 *
 * WHAT IT HAS TO MAKE OBVIOUS
 * ---------------------------
 * 1. Which company you are editing. There is a picker even for a
 *    COMPANY_ADMIN with exactly one company, because "whose numbers am I
 *    changing" should never be something you infer.
 * 2. Whether a number is this company's or the platform's. A blank input
 *    means "not configured, using the default", and the default is
 *    printed next to it as the placeholder AND spelled out under the
 *    field. An override that happens to equal the default still reads as
 *    an override, because it is one — it stops tracking the default the
 *    moment it is saved.
 * 3. What the number MEANS. "24" is not a threshold anybody can reason
 *    about; "24 business hours (Mon-Fri 09:00-17:00) - about 3 working
 *    days" is. The window comes from the server, which reads the same
 *    settings the engine measures with, so the sentence cannot go stale.
 *
 * ZERO IS A LEGAL VALUE. An empty field clears the override; a typed 0
 * stores zero and means "warn me the moment it lands". They must never
 * render or behave the same, which is the reason the state below is
 * `string` and not `number | null` — an input that round-trips through a
 * number cannot tell "" from 0.
 *
 * CUSTOMERS NEVER REACH THIS. The route is gated on the same SA/CA rule
 * the backend enforces, and the backend 403s rather than returning an
 * empty list, so a customer cannot even learn the endpoint's shape.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlarmClock, RotateCcw } from "lucide-react";

import { getApiError } from "../../api/client";
import {
  listSlaWarningThresholds,
  resetSlaWarningThresholds,
  saveSlaWarningThresholds,
} from "../../api/sla";
import type {
  SlaBusinessWindow,
  SlaCompanyThresholds,
  SlaThresholdRow,
} from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import { useToast } from "../../components/ToastProvider";

/** The three warnings, and which fields belong to each. Rendering by
 *  WARNING rather than as a flat list of seven inputs is the whole
 *  usability argument: a threshold means nothing without the warning it
 *  governs, and the pair (first notice, escalation) only makes sense
 *  side by side. Iterated from here by the renderer; the server's field
 *  list is what validates, this is only the grouping. */
const GROUPS: { key: string; fields: string[] }[] = [
  {
    key: "approval_cutoff",
    fields: ["approval_cutoff_days", "approval_cutoff_escalate_days"],
  },
  {
    key: "manager_review",
    fields: [
      "manager_review_business_hours",
      "manager_review_escalate_business_hours",
    ],
  },
  {
    key: "not_started",
    fields: [
      "not_started_business_hours",
      "not_started_escalate_business_hours",
    ],
  },
  { key: "cooldown", fields: ["cooldown_hours"] },
];

function draftFrom(company: SlaCompanyThresholds | null): Record<string, string> {
  const draft: Record<string, string> = {};
  if (!company) return draft;
  for (const row of company.thresholds) {
    // `?? ""` and not `|| ""`: an override of 0 is a real value and must
    // survive into the input as "0", not collapse into "not configured".
    draft[row.field] = row.override === null ? "" : String(row.override);
  }
  return draft;
}

export function SlaWarningsAdminPage() {
  const { t } = useTranslation("common");
  const { push: pushToast } = useToast();
  const [companies, setCompanies] = useState<SlaCompanyThresholds[]>([]);
  const [window_, setWindow] = useState<SlaBusinessWindow | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Loads once. `loading` STARTS true and is only ever cleared in the
  // settled branch — the starts-true idiom the project uses, because a
  // synchronous `setLoading(true)` reached from an effect body trips
  // `react-hooks/set-state-in-effect` and the lint baseline is frozen
  // at exactly 44.
  useEffect(() => {
    let cancelled = false;
    listSlaWarningThresholds()
      .then((data) => {
        if (cancelled) return;
        setCompanies(data.results);
        setWindow(data.business_window);
        const first = data.results[0] ?? null;
        setSelectedId(first ? first.company : null);
        setDraft(draftFrom(first));
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = useMemo(
    () => companies.find((c) => c.company === selectedId) ?? null,
    [companies, selectedId],
  );

  const byField = useMemo(() => {
    const map = new Map<string, SlaThresholdRow>();
    for (const row of selected?.thresholds ?? []) map.set(row.field, row);
    return map;
  }, [selected]);

  /** The "24 business hours (Mon-Fri 09:00-17:00)" sentence. Built from
   *  the server's window so it cannot drift from what the engine
   *  actually measures. */
  const explain = useCallback(
    (row: SlaThresholdRow, value: number): string => {
      // `n`, deliberately not `count`: i18next treats a `count`
      // interpolation as a plural request and starts looking for
      // `key_one` / `key_other`. These sentences carry their own
      // "dag(en)" style plural, the way the warning e-mails already do,
      // so a plural machine here would only add key pairs the nl/en
      // lockstep has to keep in step for no gain.
      if (row.unit === "days") return t("sla_warnings.unit_days", { n: value });
      if (row.unit === "hours") return t("sla_warnings.unit_hours", { n: value });
      const w = window_;
      if (!w) return t("sla_warnings.unit_business_hours_plain", { n: value });
      const perDay = w.hours_per_day > 0 ? w.hours_per_day : 8;
      const days = Math.round((value / perDay) * 10) / 10;
      return t("sla_warnings.unit_business_hours", {
        n: value,
        start: w.start,
        end: w.end,
        days,
      });
    },
    [t, window_],
  );

  const selectCompany = useCallback(
    (id: number) => {
      setSelectedId(id);
      setDraft(draftFrom(companies.find((c) => c.company === id) ?? null));
      setError("");
    },
    [companies],
  );

  const applyResult = useCallback((updated: SlaCompanyThresholds) => {
    setCompanies((prev) =>
      prev.map((c) => (c.company === updated.company ? updated : c)),
    );
    setDraft(draftFrom(updated));
  }, []);

  const handleSave = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      const patch: Record<string, number | null> = {};
      for (const row of selected.thresholds) {
        const raw = (draft[row.field] ?? "").trim();
        patch[row.field] = raw === "" ? null : Number(raw);
      }
      applyResult(await saveSlaWarningThresholds(selected.company, patch));
      pushToast({
        variant: "success",
        title: t("sla_warnings.saved"),
      });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }, [selected, draft, applyResult, pushToast, t]);

  const handleReset = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      applyResult(await resetSlaWarningThresholds(selected.company));
      pushToast({ variant: "success", title: t("sla_warnings.reset_done") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }, [selected, applyResult, pushToast, t]);

  return (
    <div data-testid="sla-warnings-page">
      <PageHeader
        eyebrow={t("sla_warnings.eyebrow")}
        title={t("sla_warnings.title")}
        subtitle={t("sla_warnings.subtitle")}
        actions={
          selected ? (
            <>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleReset}
                disabled={saving || !selected.is_customized}
                data-testid="sla-warnings-reset"
              >
                <RotateCcw size={15} strokeWidth={2} />
                {t("sla_warnings.reset")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSave}
                disabled={saving}
                data-testid="sla-warnings-save"
              >
                {t("save")}
              </button>
            </>
          ) : undefined
        }
      />

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="card" style={{ padding: 16 }}>
          {t("sla_warnings.loading")}
        </div>
      ) : companies.length === 0 ? (
        <div className="card" style={{ padding: 16 }}>
          {t("sla_warnings.no_companies")}
        </div>
      ) : (
        <>
          <div
            className="card"
            style={{ padding: 16, marginBottom: 16 }}
            data-testid="sla-warnings-company-card"
          >
            <label className="field" style={{ maxWidth: 360 }}>
              <span className="field-label">
                {t("sla_warnings.company_label")}
              </span>
              <select
                className="field-select"
                value={selectedId === null ? "" : String(selectedId)}
                onChange={(event) => selectCompany(Number(event.target.value))}
                data-testid="sla-warnings-company-select"
              >
                {companies.map((company) => (
                  <option key={company.company} value={String(company.company)}>
                    {company.company_name}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
              {selected?.is_customized
                ? t("sla_warnings.state_custom", {
                    when: selected.updated_at
                      ? new Date(selected.updated_at).toLocaleDateString()
                      : "",
                    who: selected.updated_by_name ?? "",
                  })
                : t("sla_warnings.state_default")}
            </p>
            <p className="muted small" style={{ marginTop: 4, marginBottom: 0 }}>
              {t("sla_warnings.tenancy_note")}
            </p>
          </div>

          {GROUPS.map((group) => (
            <div
              className="card"
              style={{ padding: 16, marginBottom: 16 }}
              key={group.key}
              data-testid={`sla-warnings-group-${group.key}`}
            >
              <h3 style={{ marginTop: 0, marginBottom: 4, fontSize: 16 }}>
                <AlarmClock
                  size={15}
                  strokeWidth={2}
                  style={{ verticalAlign: "-2px", marginRight: 6 }}
                />
                {t(`sla_warnings.group.${group.key}.title`)}
              </h3>
              <p className="muted small" style={{ marginTop: 0 }}>
                {t(`sla_warnings.group.${group.key}.what`)}
              </p>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 24,
                }}
              >
                {group.fields.map((field) => {
                  const row = byField.get(field);
                  if (!row) return null;
                  const raw = (draft[field] ?? "").trim();
                  const shown = raw === "" ? row.default : Number(raw);
                  return (
                    <label
                      className="field"
                      key={field}
                      style={{ minWidth: 260, flex: "1 1 260px" }}
                    >
                      <span className="field-label">
                        {t(`sla_warnings.field.${field}`)}
                      </span>
                      <input
                        className="field-input"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        value={draft[field] ?? ""}
                        placeholder={String(row.default)}
                        onChange={(event) =>
                          setDraft((prev) => ({
                            ...prev,
                            [field]: event.target.value,
                          }))
                        }
                        data-testid={`sla-warnings-input-${field}`}
                      />
                      <span
                        className="muted small"
                        data-testid={`sla-warnings-meaning-${field}`}
                      >
                        {Number.isFinite(shown)
                          ? explain(row, shown)
                          : t("sla_warnings.unit_invalid")}
                      </span>
                      <span
                        className="muted small"
                        data-testid={`sla-warnings-source-${field}`}
                      >
                        {raw === ""
                          ? t("sla_warnings.source_default", {
                              value: row.default,
                            })
                          : t("sla_warnings.source_company")}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
