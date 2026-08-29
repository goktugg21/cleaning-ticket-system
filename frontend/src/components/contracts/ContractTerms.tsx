import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import type {
  Contract,
  ContractForecast,
  ContractRevision,
  ContractStats,
} from "../../api/contracts.types";
import { contractTypeLabel } from "../../lib/contractTypeLabel";
import {
  formatDate,
  formatMoney,
  formatNumber,
  formatPeriod,
  lineValue,
} from "../../pages/admin/contracts/contractTables";
import { MONTHS_PER_PERIOD, plainDate } from "./contractSentence";

/**
 * P-3 §C — CONTRACTS CLARITY. Words, layout and self-teaching modals;
 * not one rule, field, calculation or endpoint changes (Addendum D
 * §D.15: the functional revision waits for the owner's meeting).
 *
 * Two things live here:
 *
 *   `contractSentence`  — a contract, wherever it is listed, reads like
 *                          a sentence: "B Amsterdam — € 850 per maand
 *                          voor B1 + B2 — sinds jan 2026 — volgende
 *                          periode: sep". Every fact is on the row the
 *                          server already sends.
 *   `Term` + `ContractTermDialog` — every term teaches on click. The
 *                          dialog makes the word obvious by SHOWING it
 *                          with THIS contract's own numbers: "Versie 2 —
 *                          geldig vanaf 1 sep. Wat veranderde: € 800 →
 *                          € 850 per maand." No glossary paragraphs: one
 *                          short line of words at most, the rest is the
 *                          contract's own facts.
 */

export type ContractTerm =
  | "contractNo"
  | "customer"
  | "locations"
  | "type"
  | "status"
  | "startDate"
  | "endDate"
  | "monthly"
  | "yearly"
  | "hours"
  | "hoursPerYear"
  | "projects"
  | "billingPeriod"
  | "billingDay"
  | "billingType"
  | "paymentTerms"
  | "proration"
  | "revision"
  | "revisionState"
  | "forecast"
  | "prorated"
  | "noneInForce"
  | "invoicesPerYear";

export interface TermContext {
  contract: Contract | null;
  revisions?: ContractRevision[];
  forecast?: ContractForecast | null;
  stats?: ContractStats | null;
}

/** A word that teaches on click. */
export function Term({
  term,
  onOpen,
  children,
  testId,
}: {
  term: ContractTerm;
  onOpen: (term: ContractTerm) => void;
  children: ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation("contracts");
  return (
    <button
      type="button"
      className="term-link"
      onClick={(event) => {
        event.stopPropagation();
        onOpen(term);
      }}
      aria-haspopup="dialog"
      title={t("teach.click_hint")}
      data-testid={testId ?? `contract-term-${term}`}
    >
      {children}
    </button>
  );
}

function revisionNumber(revisions: ContractRevision[], revision: ContractRevision): number {
  const sorted = [...revisions].sort((a, b) =>
    a.effective_from < b.effective_from ? -1 : a.effective_from > b.effective_from ? 1 : a.id - b.id,
  );
  return sorted.findIndex((r) => r.id === revision.id) + 1;
}

function sortedRevisions(revisions: ContractRevision[]): ContractRevision[] {
  return [...revisions].sort((a, b) =>
    a.effective_from < b.effective_from ? -1 : a.effective_from > b.effective_from ? 1 : a.id - b.id,
  );
}

/** The dialog's content: a title and SHORT lines, most of them the
 *  contract's own facts. Built as data so the render is one shape. */
function teach(
  term: ContractTerm,
  ctx: TermContext,
  t: TFunction,
  locale: string,
): { title: string; lines: string[]; note: string } {
  const c = ctx.contract;
  const revisions = ctx.revisions ?? [];
  const forecast = ctx.forecast ?? null;
  const money = (v: string | number) => formatMoney(v, locale);
  const date = (v: string | null) => formatDate(v, locale);
  const periodWord = c ? t(`teach.period_noun.${c.billing_period}`) : "";
  const lines: string[] = [];
  let note = "";

  switch (term) {
    case "contractNo": {
      if (c) {
        const [, year, seq] = c.contract_no.match(/^CNT-(\d{4})-(\d+)$/) ?? [];
        lines.push(
          year
            ? t("teach.contractNo.example", { no: c.contract_no, year, seq })
            : c.contract_no,
        );
      }
      note = t("teach.contractNo.note");
      break;
    }
    case "customer":
      if (c?.customer_name) lines.push(c.customer_name);
      note = t("teach.customer.note");
      break;
    case "locations":
      if (c) lines.push(...c.buildings.map((b) => b.name));
      if (c && c.buildings.length === 0) lines.push(t("sentence.no_locations"));
      note = t("teach.locations.note");
      break;
    case "type":
      if (c?.contract_type_name) {
        lines.push(contractTypeLabel(c.contract_type_name, c.contract_type_standard_slot, t));
      }
      note = t("teach.type.note");
      break;
    case "status": {
      for (const s of ["DRAFT", "ACTIVE", "EXPIRED", "CANCELLED"] as const) {
        const count = ctx.stats ? ctx.stats[s.toLowerCase() as "draft" | "active" | "expired" | "cancelled"] : null;
        const mine = c?.status === s;
        lines.push(
          `${t(`status.${s}`)} — ${t(`teach.status.${s}`)}${
            count !== null && count !== undefined ? ` (${count})` : ""
          }${mine ? ` ← ${t("teach.status.this_one")}` : ""}`,
        );
      }
      if (c?.status === "EXPIRED" && c.end_date) {
        lines.push(t("teach.status.expired_because", { date: date(c.end_date) }));
      }
      note = t("teach.status.note");
      break;
    }
    case "startDate":
    case "endDate":
      if (c) {
        lines.push(
          c.end_date
            ? t("teach.dates.from_until", { from: date(c.start_date), until: date(c.end_date) })
            : t("teach.dates.from_open", { from: date(c.start_date) }),
        );
      }
      note = t("teach.dates.note");
      break;
    case "monthly": {
      if (c) {
        lines.push(t("teach.monthly.total", { amount: money(c.monthly_amount) }));
        for (const line of c.projects) {
          lines.push(`${line.name}: ${money(lineValue(c, line, "prices", "monthly"))}`);
        }
        if (c.projects.length === 0) lines.push(t("teach.monthly.no_lines"));
      } else if (ctx.stats) {
        lines.push(t("teach.monthly.total", { amount: money(ctx.stats.monthly_total) }));
      }
      note = t("teach.monthly.note");
      break;
    }
    case "yearly": {
      if (c) {
        lines.push(t("teach.yearly.total", { amount: money(c.yearly_amount) }));
        lines.push(
          t("teach.yearly.compare", {
            monthly: money(c.monthly_amount),
            twelve: money(Number(c.monthly_amount) * 12),
          }),
        );
      } else if (ctx.stats) {
        lines.push(t("teach.yearly.total", { amount: money(ctx.stats.yearly_total) }));
      }
      note = t("teach.yearly.note");
      break;
    }
    case "hours": {
      if (c) {
        lines.push(
          t("teach.hours.total", { hours: formatNumber(c.total_hours, locale), period: periodWord }),
        );
        for (const line of c.projects) {
          lines.push(`${line.name}: ${formatNumber(line.hours, locale)} ${t("teach.hours.unit")}`);
        }
      }
      note = t("teach.hours.note");
      break;
    }
    case "hoursPerYear":
      if (c) {
        const per = 12 / MONTHS_PER_PERIOD[c.billing_period];
        lines.push(
          t("teach.hoursPerYear.calc", {
            hours: formatNumber(c.total_hours, locale),
            times: per,
            total: formatNumber(Number(c.total_hours) * per, locale),
          }),
        );
      }
      note = t("teach.hoursPerYear.note");
      break;
    case "projects":
      if (c) {
        for (const line of c.projects) {
          lines.push(
            `${line.name} — ${line.building_name ?? t("projects.wholeContract")} — ${money(line.amount)} ${t(`sentence.per_${c.billing_period}`)}`,
          );
        }
        if (c.projects.length === 0) lines.push(t("projects.empty"));
      }
      note = t("teach.projects.note");
      break;
    case "billingPeriod": {
      if (c) {
        lines.push(t(`teach.billingPeriod.${c.billing_period}`));
        for (const row of (forecast?.rows ?? []).slice(0, 3)) {
          lines.push(`${formatPeriod(row.period_start, locale)} → ${t("teach.billingPeriod.invoice_on", { date: date(row.invoice_date) })}`);
        }
      }
      note = t("teach.billingPeriod.note");
      break;
    }
    case "billingDay": {
      if (c) {
        lines.push(t("teach.billingDay.rule", { day: c.billing_day }));
        const row = forecast?.rows[0];
        if (row) {
          lines.push(t("teach.billingDay.example", { date: date(row.invoice_date), period: formatPeriod(row.period_start, locale) }));
        }
      }
      note = t("teach.billingDay.note");
      break;
    }
    case "billingType": {
      if (c) {
        lines.push(t(`teach.billingType.${c.billing_type}`, { day: c.billing_day }));
        const row = forecast?.rows[0];
        if (row) {
          lines.push(t("teach.billingType.example", { date: date(row.invoice_date), period: formatPeriod(row.period_start, locale) }));
        }
      }
      note = t("teach.billingType.note");
      break;
    }
    case "paymentTerms": {
      if (c) {
        const row = forecast?.rows[0];
        const base = plainDate(row?.invoice_date ?? c.start_date);
        const due = base ? new Date(base.getTime() + c.payment_terms_days * 86_400_000) : null;
        lines.push(
          t("teach.paymentTerms.example", {
            days: c.payment_terms_days,
            invoice: base ? base.toLocaleDateString(locale, { day: "2-digit", month: "short", year: "numeric" }) : "",
            due: due ? due.toLocaleDateString(locale, { day: "2-digit", month: "short", year: "numeric" }) : "",
          }),
        );
      }
      note = t("teach.paymentTerms.note");
      break;
    }
    case "proration": {
      if (c) {
        lines.push(c.start_proration ? t("teach.proration.on") : t("teach.proration.off"));
        const row = (forecast?.rows ?? []).find((r) => r.is_prorated);
        if (row) {
          lines.push(
            t("teach.proration.example", {
              period: formatPeriod(row.period_start, locale),
              covered: row.covered_days,
              total: row.period_days,
              amount: money(row.amount),
            }),
          );
        } else {
          lines.push(t("teach.proration.starts", { date: date(c.start_date) }));
        }
      }
      note = t("teach.proration.note");
      break;
    }
    case "revision": {
      const sorted = sortedRevisions(revisions);
      sorted.forEach((rev, index) => {
        const prev = sorted[index - 1];
        let line = t("teach.revision.line", {
          n: index + 1,
          label: rev.label,
          date: date(rev.effective_from),
          amount: money(rev.amount),
          period: periodWord,
        });
        if (rev.is_active) line += ` — ${t("teach.revision.in_force")}`;
        else if (!rev.is_locked) line += ` — ${t("teach.revision.editable")}`;
        else line += ` — ${t("teach.revision.replaced")}`;
        lines.push(line);
        if (prev && prev.amount !== rev.amount) {
          lines.push(
            `   ${t("teach.revision.changed", { from: money(prev.amount), to: money(rev.amount), period: periodWord })}`,
          );
        }
      });
      if (sorted.length === 0) lines.push(t("revisions.empty"));
      note = t("teach.revision.note");
      break;
    }
    case "revisionState":
      lines.push(`${t("revisions.isActive")} — ${t("teach.revisionState.active")}`);
      lines.push(`${t("revisions.isPlanned")} — ${t("teach.revisionState.planned")}`);
      lines.push(`${t("revisions.isPast")} — ${t("teach.revisionState.past")}`);
      if (c && revisions.length > 0) {
        const active = revisions.find((r) => r.is_active);
        if (active) {
          lines.push(
            t("teach.revisionState.this_one", {
              n: revisionNumber(revisions, active),
              date: date(active.effective_from),
            }),
          );
        }
      }
      note = "";
      break;
    case "forecast":
      if (forecast) {
        lines.push(
          t("teach.forecast.rows", {
            count: forecast.rows.length,
            year: forecast.year,
            total: money(forecast.rows_total),
          }),
        );
      }
      note = t("teach.forecast.note");
      break;
    case "prorated": {
      const row = (forecast?.rows ?? []).find((r) => r.is_prorated);
      if (row) {
        lines.push(
          t("teach.proration.example", {
            period: formatPeriod(row.period_start, locale),
            covered: row.covered_days,
            total: row.period_days,
            amount: money(row.amount),
          }),
        );
      }
      note = t("teach.proration.note");
      break;
    }
    case "noneInForce": {
      const first = sortedRevisions(revisions)[0];
      lines.push(
        t("teach.noneInForce.line", {
          today: new Date().toLocaleDateString(locale, { day: "2-digit", month: "short", year: "numeric" }),
          date: first ? date(first.effective_from) : date(c?.start_date ?? null),
        }),
      );
      note = t("teach.noneInForce.note");
      break;
    }
    case "invoicesPerYear":
      if (c) {
        lines.push(
          t("teach.invoicesPerYear.line", {
            count: 12 / MONTHS_PER_PERIOD[c.billing_period],
            period: periodWord,
          }),
        );
      }
      note = "";
      break;
    default:
      break;
  }
  return { title: t(`teach.title.${term}`), lines, note };
}

/**
 * The teaching dialog. A native <dialog>, rendered UNCONDITIONALLY and
 * driven through its ref (CLAUDE.md: never `{cond && <dialog/>}`); it
 * opens when `term` is set and closes on Escape, backdrop or the button.
 */
export function ContractTermDialog({
  term,
  context,
  onClose,
}: {
  term: ContractTerm | null;
  context: TermContext;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation("contracts");
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (term && !node.open) node.showModal();
    if (!term && node.open) node.close();
  }, [term]);
  useEffect(() => {
    const node = ref.current;
    return () => {
      if (node?.open) node.close();
    };
  }, []);
  const content = term ? teach(term, context, t, i18n.language) : null;
  return (
    <dialog
      ref={ref}
      className="term-dialog"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      data-testid="contract-term-dialog"
      data-term={term ?? ""}
    >
      {content && (
        <div className="term-dialog-body">
          <h3 className="term-dialog-title">{content.title}</h3>
          {content.lines.length > 0 && (
            <ul className="term-dialog-lines" data-testid="contract-term-lines">
              {content.lines.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          )}
          {content.note && <p className="term-dialog-note">{content.note}</p>}
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onClose}
              data-testid="contract-term-close"
            >
              {t("teach.close")}
            </button>
          </div>
        </div>
      )}
    </dialog>
  );
}
