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
 *
 * W-P4 §1 — THE WORDS, AND ONLY THE WORDS. Every label and state line
 * on this screen was rewritten in plain language; not one line of
 * behaviour below moved. Three things the old copy left the reader to
 * work out: "SLA" named nothing (the title now says what the page
 * sends), the group headings named a SITUATION rather than the moment
 * a message goes out ("When work has not started on time"), and the
 * second threshold in each pair read "Then warn again after", which
 * only makes sense while you are looking at its sibling — each field
 * now says "First warning" / "Second warning" and stands on its own.
 * The strings live in `common.json` under `sla_warnings.*`; nothing
 * here reads them by any route other than the `t()` calls already
 * present.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { RotateCcw } from "lucide-react";

import { getApiError } from "../../api/client";
import {
  listSlaWarningThresholds,
  resetSlaWarningThresholds,
  saveSlaWarningThresholds,
} from "../../api/sla";
import type { SlaThresholdPatch } from "../../api/sla";
import type {
  SlaAlsoNotify,
  SlaBusinessWindow,
  SlaCompanyThresholds,
  SlaThresholdRow,
  SlaWarningKey,
} from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import { useToast } from "../../components/ToastProvider";
import { HowThisWorks } from "../../components/guide/HowThisWorks";
import { WhatHappens } from "../../components/guide/WhatHappens";
import { formatDate } from "../../lib/intl";

/**
 * W7 §7 — THREE warnings, then one timing setting. In that order.
 *
 * The page used to render four peer cards, each headed by an alarm-clock
 * icon and a paragraph, with two explanation lines under every input.
 * Nothing on it said how many things it configured, and the owner read
 * it as an alarm console rather than as a settings page. It is a
 * settings page for three warnings, so it now looks like one: the three
 * warnings are NUMBERED and ordered the way a job runs (nothing started
 * -> nobody reviewed it -> the customer has not approved it before their
 * billing date), and the repeat interval is not a fourth warning and no
 * longer sits as one.
 *
 * `kind` is what the renderer branches on; the numbering is derived from
 * it, so a fourth warning added here is numbered without touching the
 * renderer, and a second timing setting cannot accidentally become
 * "warning 4".
 */
const GROUPS: { key: string; kind: "warning" | "timing"; fields: string[] }[] = [
  {
    key: "not_started",
    kind: "warning",
    fields: [
      "not_started_business_hours",
      "not_started_escalate_business_hours",
    ],
  },
  {
    key: "manager_review",
    kind: "warning",
    fields: [
      "manager_review_business_hours",
      "manager_review_escalate_business_hours",
    ],
  },
  {
    key: "approval_cutoff",
    kind: "warning",
    fields: ["approval_cutoff_days", "approval_cutoff_escalate_days"],
  },
  { key: "cooldown", kind: "timing", fields: ["cooldown_hours"] },
];

/**
 * W8 §1 — WHO EACH NUMBER SENDS A MESSAGE TO.
 *
 * The owner read this page and asked: "What exactly does 'Nobody has
 * started' refer to? Which work? Which ticket? Which SLA? Which
 * company?" All four answers existed on the page and none of them was
 * attached to the number that causes them — the subject was in a
 * paragraph under the heading, and the recipient was in a third line
 * under both inputs, phrased as a pair ("the assigned staff, then the
 * responsible manager") that the reader had to zip together with the
 * two fields themselves.
 *
 * So the recipient moves ONTO the field. Each threshold now renders as
 * one readable line — warn after N, and this is who hears about it —
 * and the paragraph and the shared "Goes to" line are deleted rather
 * than shortened. A person reading one line knows what happens and to
 * whom; that is the whole test.
 */
const FIELD_RECIPIENT: Record<string, string> = {
  not_started_business_hours: "not_started_business_hours",
  not_started_escalate_business_hours:
    "not_started_escalate_business_hours",
  manager_review_business_hours: "manager_review_business_hours",
  manager_review_escalate_business_hours:
    "manager_review_escalate_business_hours",
  approval_cutoff_days: "approval_cutoff_days",
  approval_cutoff_escalate_days: "approval_cutoff_escalate_days",
};

/** How many warnings there are, for the "1 of 3" marker. Counted from
 *  GROUPS, never typed as a literal three. */
const WARNING_COUNT = GROUPS.filter((g) => g.kind === "warning").length;

/** Each warning's ordinal, keyed by group. Derived from the order of the
 *  WARNINGS in GROUPS rather than from the array index, so a timing
 *  setting placed anywhere in the list cannot shift the numbering. */
const WARNING_ORDINAL: Record<string, number> = Object.fromEntries(
  GROUPS.filter((g) => g.kind === "warning").map((g, i) => [g.key, i + 1]),
);

/** P-5 S8 — which rings a warning may be ADDED to: everything except
 *  the ring that already receives its first warning. */
const OFFERED_RINGS: Record<SlaWarningKey, SlaAlsoNotify[]> = {
  not_started: ["responsible_manager", "company_admins"],
  manager_review: ["assigned_staff", "company_admins"],
  approval_cutoff: ["assigned_staff", "responsible_manager", "company_admins"],
};

const WARNING_KEYS: SlaWarningKey[] = ["not_started", "manager_review", "approval_cutoff"];

function isWarningKey(key: string): key is SlaWarningKey {
  return (WARNING_KEYS as string[]).includes(key);
}

/** The choices draft, editable in place. */
interface ChoicesDraft {
  count_calendar_days: boolean;
  weekly_summary_enabled: boolean;
  warnings: Record<
    SlaWarningKey,
    { also_notify: SlaAlsoNotify[]; extra_email: string; final_days: string }
  >;
}

function choicesFrom(company: SlaCompanyThresholds | null): ChoicesDraft {
  const warnings = {} as ChoicesDraft["warnings"];
  for (const key of WARNING_KEYS) {
    const w = company?.choices?.warnings?.[key];
    warnings[key] = {
      also_notify: [...(w?.also_notify ?? [])],
      extra_email: w?.extra_email ?? "",
      final_days:
        w?.final_escalate_days === null || w?.final_escalate_days === undefined
          ? ""
          : String(w.final_escalate_days),
    };
  }
  return {
    count_calendar_days: company?.choices?.count_calendar_days ?? false,
    weekly_summary_enabled: company?.choices?.weekly_summary_enabled ?? false,
    warnings,
  };
}

/** P-7 S6 — one warning's additions at their defaults? (nothing to
 *  fold open for). */
function warningChoicesAreDefault(w: ChoicesDraft["warnings"][SlaWarningKey]): boolean {
  return w.also_notify.length === 0 && w.extra_email.trim() === "" && w.final_days === "";
}

/** P-7 S6 — the fold's summary in a few words: who else hears it, the
 *  extra address, the third step — or "standard". */
function warningChoicesSummary(
  w: ChoicesDraft["warnings"][SlaWarningKey],
  t: TFunction,
): string {
  const parts: string[] = [];
  if (w.also_notify.length > 0) {
    parts.push(
      t("sla_warnings.summary_also", {
        who: w.also_notify.map((ring) => t(`sla_warnings.ring.${ring}`)).join(", "),
      }),
    );
  }
  if (w.extra_email.trim() !== "") parts.push(w.extra_email.trim());
  if (w.final_days !== "") {
    parts.push(t("sla_warnings.summary_final", { n: Number(w.final_days) || 0 }));
  }
  return parts.length > 0 ? parts.join(" · ") : t("sla_warnings.summary_default");
}

function choicesAreDefault(c: ChoicesDraft): boolean {
  return (
    !c.count_calendar_days &&
    !c.weekly_summary_enabled &&
    WARNING_KEYS.every(
      (key) =>
        c.warnings[key].also_notify.length === 0 &&
        c.warnings[key].extra_email.trim() === "" &&
        c.warnings[key].final_days.trim() === "",
    )
  );
}

function choicesPatch(c: ChoicesDraft): SlaThresholdPatch {
  const patch: SlaThresholdPatch = {
    count_calendar_days: c.count_calendar_days,
    weekly_summary_enabled: c.weekly_summary_enabled,
  };
  for (const key of WARNING_KEYS) {
    const w = c.warnings[key];
    patch[`${key}_also_notify`] = w.also_notify;
    patch[`${key}_extra_email`] = w.extra_email.trim();
    patch[`${key}_final_escalate_days`] =
      w.final_days.trim() === "" ? null : Number(w.final_days);
  }
  return patch;
}

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
  // P-5 S8 — the choices beside the numbers.
  const [choices, setChoices] = useState<ChoicesDraft>(() => choicesFrom(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");

  // Loads once. `loading` STARTS true and is only ever cleared in the
  // settled branch — the starts-true idiom the project uses, because a
  // synchronous `setLoading(true)` reached from an effect body trips
  // `react-hooks/set-state-in-effect` and the lint baseline is frozen
  // at exactly 42 (41 errors, 1 warning) — the 44 this comment used to
  // name was the stale figure CLAUDE.md corrected.
  useEffect(() => {
    let cancelled = false;
    listSlaWarningThresholds()
      .then((data) => {
        if (cancelled) return;
        setCompanies(data.results);
        setWindow(data.business_window);
        // The server hands back the caller's OWN company first
        // (`sla.views_thresholds._own_company_first`), so opening on
        // the first row IS opening on your own company.
        //
        // W8 tried to choose here instead, out of `me.company_ids`.
        // That set is every company on the platform for a SUPER_ADMIN
        // (`accounts.scoping.company_ids_for` returns the whole table
        // for that role), so the "find the one that is mine" call
        // matched row zero every time and the page went on opening on
        // whichever tenant sorted first alphabetically. One place
        // decides the order now, and it is the place that knows which
        // company the deployment belongs to.
        const first = data.results[0] ?? null;
        setSelectedId(first ? first.company : null);
        setDraft(draftFrom(first));
        setChoices(choicesFrom(first));
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
      // P-5 S8.3 — honest captions: in calendar mode the working
      // window is not what is counted, so the sentence says the clock.
      if (choices.count_calendar_days) {
        return t("sla_warnings.unit_calendar_hours", {
          n: value,
          days: Math.round((value / 24) * 10) / 10,
        });
      }
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
    [t, window_, choices.count_calendar_days],
  );

  const selectCompany = useCallback(
    (id: number) => {
      setSelectedId(id);
      const next = companies.find((c) => c.company === id) ?? null;
      setDraft(draftFrom(next));
      setChoices(choicesFrom(next));
      setError("");
    },
    [companies],
  );

  const applyResult = useCallback((updated: SlaCompanyThresholds) => {
    setCompanies((prev) =>
      prev.map((c) => (c.company === updated.company ? updated : c)),
    );
    setDraft(draftFrom(updated));
    setChoices(choicesFrom(updated));
  }, []);

  // W-T3 §1 — Save and Reset had been reporting into the SAME banner as
  // the page LOAD. Conflated, a refused save read as "this page is
  // broken" rather than "that button did not work"; separated, the
  // message sits directly under the two buttons that fired it and the
  // load keeps its own.
  const handleSave = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    setActionError("");
    try {
      const patch: SlaThresholdPatch = {};
      let anySet = false;
      for (const row of selected.thresholds) {
        const raw = (draft[row.field] ?? "").trim();
        patch[row.field] = raw === "" ? null : Number(raw);
        if (raw !== "") anySet = true;
      }
      // P-5 S8 — the choices travel with the numbers; a company with
      // nothing set anywhere is reset (no row) rather than saved.
      Object.assign(patch, choicesPatch(choices));
      if (!choicesAreDefault(choices)) anySet = true;
      // W8 §2 — SAVING AN ALL-BLANK FORM IS "BACK TO DEFAULTS", AND IT
      // MUST NOT LEAVE A ROW BEHIND.
      //
      // Pressing Save on an untouched page used to PUT seven nulls,
      // which creates a `SlaWarningThreshold` row storing nothing. One
      // exists on crmtest today for exactly that reason. It changes no
      // number — `is_customized` correctly ignores an all-null row — but
      // it is a record of a decision nobody made, it cannot be reached
      // by "Back to defaults" (that button is disabled precisely because
      // the row is not a customisation), and it is the sort of ghost
      // that makes an operator distrust the screen. An empty form is a
      // request to use the defaults, so it goes to the endpoint that
      // means that.
      applyResult(
        anySet
          ? await saveSlaWarningThresholds(selected.company, patch)
          : await resetSlaWarningThresholds(selected.company),
      );
      pushToast({
        variant: "success",
        title: t("sla_warnings.saved"),
      });
    } catch (err) {
      setActionError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }, [selected, draft, choices, applyResult, pushToast, t]);

  const handleReset = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    setActionError("");
    try {
      applyResult(await resetSlaWarningThresholds(selected.company));
      pushToast({ variant: "success", title: t("sla_warnings.reset_done") });
    } catch (err) {
      setActionError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }, [selected, applyResult, pushToast, t]);

  return (
    <div data-testid="sla-warnings-page">
      <PageHeader
        eyebrow={t("sla_warnings.eyebrow")}
        /* W8 §2 — WHICH COMPANY, in the title. The owner asked "which
           company?" of a page whose answer was a dropdown halfway down
           it. The picker still decides; the heading says out loud which
           one it is on. */
        title={
          selected
            ? t("sla_warnings.title_for_company", {
                company: selected.company_name,
              })
            : t("sla_warnings.title")
        }
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
              <span style={{ textAlign: "right" }}>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleSave}
                  disabled={saving}
                  data-testid="sla-warnings-save"
                >
                  {t("save")}
                </button>
                {/* P-13 §D.24 rule 8 — the pre-read. */}
                <WhatHappens testId="sla-warnings-save-what">
                  {t("sla_warnings.what_save")}
                </WhatHappens>
              </span>
            </>
          ) : undefined
        }
      />

      {/* P-13 §D.24 rule 8 — what this page CAN do. */}
      <HowThisWorks
        pageKey="sla-warnings"
        testId="sla-warnings-how"
        lines={[
          t("sla_warnings.how_1"),
          t("sla_warnings.how_2"),
          t("sla_warnings.how_3"),
          t("sla_warnings.how_4"),
        ]}
      />

      {/* The ACTION's failure, directly under the buttons that fired
          it. Separate from the load banner below. */}
      {actionError && (
        <div
          className="alert alert-error"
          role="alert"
          data-testid="sla-warnings-action-error"
        >
          {actionError}
        </div>
      )}

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
            {/* ONE line, not three. The tenancy note said in a sentence
                what the picker above it already says by existing, and
                the defaults are PLATFORM-wide (`sla.thresholds.defaults`
                reads Django settings, not the company row), so the only
                thing worth stating here is whether this company has
                stepped off them and who did it. */}
            <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
              {selected?.is_customized
                ? t("sla_warnings.state_custom", {
                    when: formatDate(selected.updated_at),
                    who: selected.updated_by_name ?? "",
                  })
                : t("sla_warnings.state_default")}
            </p>
          </div>

          {GROUPS.map((group) => (
            <div
              className={
                group.kind === "warning"
                  ? "card sla-warning-card"
                  : "card sla-timing-card"
              }
              key={group.key}
              data-testid={`sla-warnings-group-${group.key}`}
            >
              {/* The number is the structure. Three numbered cards say
                  "this page configures three things" without a sentence
                  claiming it, and the repeat interval is visibly not one
                  of them. */}
              <div className="sla-warning-head">
                {group.kind === "warning" && (
                  <span className="sla-warning-num" aria-hidden="true">
                    {WARNING_ORDINAL[group.key]}
                  </span>
                )}
                <div>
                  {/* W8 §1 — the title NAMES THE SUBJECT. "Nobody has
                      started" named nothing an operator could point at,
                      which is exactly what the owner asked about. The
                      explanatory paragraph that used to sit under it is
                      deleted, not shortened: the subject belongs in the
                      heading and the recipient belongs on the field. */}
                  <h3 className="sla-warning-title">
                    {t(`sla_warnings.group.${group.key}.title`)}
                    {group.kind === "warning" && (
                      <span className="sla-warning-of">
                        {t("sla_warnings.n_of_total", {
                          n: WARNING_ORDINAL[group.key],
                          total: WARNING_COUNT,
                        })}
                      </span>
                    )}
                  </h3>
                </div>
              </div>
              <div className="sla-warning-fields">
                {group.fields.map((field) => {
                  const row = byField.get(field);
                  if (!row) return null;
                  const raw = (draft[field] ?? "").trim();
                  const shown = raw === "" ? row.default : Number(raw);
                  return (
                    <label className="field sla-warning-field" key={field}>
                      <span className="sla-field-head">
                        <span className="field-label">
                          {t(`sla_warnings.field.${field}`)}
                        </span>
                        {/* Where the number comes from, as a chip beside
                            the label rather than a second sentence under
                            the input. Two muted lines per input was most
                            of this page's text. */}
                        <span
                          className={
                            raw === ""
                              ? "sla-source-chip is-default"
                              : "sla-source-chip is-own"
                          }
                          data-testid={`sla-warnings-source-${field}`}
                        >
                          {raw === ""
                            ? t("sla_warnings.chip_default")
                            : t("sla_warnings.chip_own")}
                        </span>
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
                      {/* WHO HEARS ABOUT IT, on the field that causes
                          it. One line per threshold, so the first and
                          the escalation each say their own recipient
                          instead of sharing a sentence the reader had
                          to split in two. */}
                      {FIELD_RECIPIENT[field] && (
                        <span
                          className="sla-field-to"
                          data-testid={`sla-warnings-to-${field}`}
                        >
                          {t("sla_warnings.goes_to_inline", {
                            who: t(`sla_warnings.to.${field}`),
                          })}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
              {/* P-5 S8 — the owner's additions, in the page's own
                  sentence style: who else hears it, an extra address,
                  and the third step. */}
              {/* P-7 S6 — the default view is the four warnings and
                  their values, as before S8. The recipients, the extra
                  address and the third step fold behind ONE "Aanpassen"
                  per warning; the summary says in a few words what is
                  set, so the fold answers even closed. Opens itself
                  when something is set. */}
              {isWarningKey(group.key) && (
                <details
                  className="form-fold sla-warning-fold"
                  open={!warningChoicesAreDefault(choices.warnings[group.key])}
                  data-testid={`sla-warnings-adjust-${group.key}`}
                >
                  <summary className="form-fold-summary">
                    {t("sla_warnings.adjust")}
                    <span className="form-fold-summary-value">
                      {warningChoicesSummary(choices.warnings[group.key], t)}
                    </span>
                  </summary>
                <div
                  className="sla-warning-choices"
                  data-testid={`sla-warnings-choices-${group.key}`}
                >
                  <span className="field-label">
                    {t("sla_warnings.also_notify_label")}
                  </span>
                  <div className="sla-choice-row">
                    {OFFERED_RINGS[group.key].map((ring) => {
                      const key = group.key as SlaWarningKey;
                      const on = choices.warnings[key].also_notify.includes(ring);
                      return (
                        <label className="sla-check" key={ring}>
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={(event) =>
                              setChoices((prev) => ({
                                ...prev,
                                warnings: {
                                  ...prev.warnings,
                                  [key]: {
                                    ...prev.warnings[key],
                                    also_notify: event.target.checked
                                      ? [...prev.warnings[key].also_notify, ring]
                                      : prev.warnings[key].also_notify.filter((r) => r !== ring),
                                  },
                                },
                              }))
                            }
                            data-testid={`sla-warnings-ring-${group.key}-${ring}`}
                          />
                          {t(`sla_warnings.ring.${ring}`)}
                        </label>
                      );
                    })}
                  </div>
                  <label className="field sla-choice-field">
                    <span className="field-label">{t("sla_warnings.extra_email_label")}</span>
                    <input
                      className="field-input"
                      type="email"
                      value={choices.warnings[group.key].extra_email}
                      onChange={(event) => {
                        const key = group.key as SlaWarningKey;
                        setChoices((prev) => ({
                          ...prev,
                          warnings: {
                            ...prev.warnings,
                            [key]: { ...prev.warnings[key], extra_email: event.target.value },
                          },
                        }));
                      }}
                      data-testid={`sla-warnings-extra-email-${group.key}`}
                    />
                    <span className="muted small">{t("sla_warnings.extra_email_hint")}</span>
                  </label>
                  <label className="sla-check">
                    <input
                      type="checkbox"
                      checked={choices.warnings[group.key].final_days !== ""}
                      onChange={(event) => {
                        const key = group.key as SlaWarningKey;
                        setChoices((prev) => ({
                          ...prev,
                          warnings: {
                            ...prev.warnings,
                            [key]: {
                              ...prev.warnings[key],
                              final_days: event.target.checked ? "3" : "",
                            },
                          },
                        }));
                      }}
                      data-testid={`sla-warnings-final-${group.key}`}
                    />
                    {t("sla_warnings.final_step_label")}
                  </label>
                  {choices.warnings[group.key].final_days !== "" && (
                    <label className="field sla-choice-field">
                      <span className="field-label">{t("sla_warnings.final_step_days_label")}</span>
                      <input
                        className="field-input"
                        type="number"
                        min={1}
                        inputMode="numeric"
                        value={choices.warnings[group.key].final_days}
                        onChange={(event) => {
                          const key = group.key as SlaWarningKey;
                          setChoices((prev) => ({
                            ...prev,
                            warnings: {
                              ...prev.warnings,
                              [key]: { ...prev.warnings[key], final_days: event.target.value },
                            },
                          }));
                        }}
                        data-testid={`sla-warnings-final-days-${group.key}`}
                      />
                      <span className="muted small">
                        {t("sla_warnings.final_step_sentence", {
                          n: Number(choices.warnings[group.key].final_days) || 0,
                        })}
                      </span>
                    </label>
                  )}
                </div>
                </details>
              )}
            </div>
          ))}
          {/* P-5 S8.3 / S8.4 — company-wide: how time is counted, and
              the weekly list. */}
          <div className="card sla-timing-card" data-testid="sla-warnings-group-counting">
            <div className="sla-warning-head">
              <div>
                <h3 className="sla-warning-title">{t("sla_warnings.group.counting.title")}</h3>
              </div>
            </div>
            {/* P-7 S6 — same fold for the company-wide pair: counting
                (weekend) and the weekly summary. */}
            <details
              className="form-fold sla-warning-fold"
              open={choices.count_calendar_days || choices.weekly_summary_enabled}
              data-testid="sla-warnings-adjust-counting"
            >
              <summary className="form-fold-summary">
                {t("sla_warnings.adjust")}
                <span className="form-fold-summary-value">
                  {[
                    choices.count_calendar_days
                      ? t("sla_warnings.summary_calendar")
                      : t("sla_warnings.summary_working"),
                    choices.weekly_summary_enabled ? t("sla_warnings.summary_weekly_on") : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </summary>
            <div className="sla-warning-fields">
              <label className="field sla-choice-field">
                <select
                  className="field-select"
                  value={choices.count_calendar_days ? "calendar" : "working"}
                  onChange={(event) =>
                    setChoices((prev) => ({
                      ...prev,
                      count_calendar_days: event.target.value === "calendar",
                    }))
                  }
                  data-testid="sla-warnings-counting"
                >
                  <option value="working">
                    {t("sla_warnings.counting_working", {
                      start: window_?.start ?? "09:00",
                      end: window_?.end ?? "17:00",
                    })}
                  </option>
                  <option value="calendar">{t("sla_warnings.counting_calendar")}</option>
                </select>
                <span className="muted small">{t("sla_warnings.counting_note")}</span>
              </label>
              <label className="sla-check">
                <input
                  type="checkbox"
                  checked={choices.weekly_summary_enabled}
                  onChange={(event) =>
                    setChoices((prev) => ({
                      ...prev,
                      weekly_summary_enabled: event.target.checked,
                    }))
                  }
                  data-testid="sla-warnings-weekly"
                />
                {t("sla_warnings.weekly_label")}
              </label>
            </div>
            </details>
          </div>
        </>
      )}
    </div>
  );
}
