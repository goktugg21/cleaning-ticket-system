import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getContractForecast } from "../../../api/contracts";
import type { ContractForecast } from "../../../api/contracts.types";
import { Term } from "../../../components/contracts/ContractTerms";
import type { ContractTerm } from "../../../components/contracts/ContractTerms";
import { formatDate, formatMoney, formatPeriod } from "./contractTables";

/**
 * Sprint 160 §5 — the Invoice Preview.
 *
 * A CALCULATION, rendered. Nothing on this screen writes: the rows are
 * what the contract's own dates and billing settings imply, every one
 * of them carries the status `Planned`, and there is deliberately no
 * "generate" button. Turning a due row into a real invoice is Sprint
 * 158's, and the absence of the affordance here is part of that
 * boundary rather than an omission.
 *
 * Two numbers on this screen legitimately disagree and the copy has to
 * carry that, because it looks like a bug otherwise:
 *
 *  * the caption totals the rows SHOWN (the invoices still to come),
 *  * the summary strip's yearly figure totals every period in the
 *    year, INCLUDING the already-raised first invoice, which is why it
 *    is the larger of the two and why it is not monthly x 12 whenever
 *    a part period has been prorated.
 */
export function ContractInvoicePreview({
  contractId,
  onTerm,
}: {
  contractId: number;
  /** P-3 §C.2 — the page's term dialog; every term here teaches. */
  onTerm: (term: ContractTerm) => void;
}) {
  const { t, i18n } = useTranslation("contracts");
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [forecast, setForecast] = useState<ContractForecast | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState("");

  // Derived rather than set in the effect body — see the note in
  // `ContractsAdminPage`. Stepping the year changes the key, so the
  // table is correctly "loading" the moment the arrow is pressed.
  const requestKey = `${contractId}:${year}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    getContractForecast(contractId, year)
      .then((data) => {
        if (cancelled) return;
        setForecast(data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [contractId, year, requestKey]);

  const locale = i18n.language;

  return (
    <section className="contract-forecast" data-testid="contract-forecast">
      <header className="contract-forecast-header">
        <h3><Term term="forecast" onOpen={onTerm}>{t("forecast.title")}</Term></h3>
        <div className="contract-year-stepper" role="group" aria-label={t("forecast.year")}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setYear((current) => current - 1)}
            aria-label={t("forecast.previousYear")}
            data-testid="forecast-year-prev"
          >
            <ChevronLeft size={16} strokeWidth={2} />
          </button>
          <span className="contract-year-value" data-testid="forecast-year">
            {year}
          </span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setYear((current) => current + 1)}
            aria-label={t("forecast.nextYear")}
            data-testid="forecast-year-next"
          >
            <ChevronRight size={16} strokeWidth={2} />
          </button>
        </div>
      </header>

      {error && (
        <div className="alert-error" role="alert">
          {error}
        </div>
      )}

      <p className="contract-forecast-caption" data-testid="forecast-caption">
        {t("forecast.caption", {
          count: forecast?.rows.length ?? 0,
          total: formatMoney(forecast?.rows_total ?? "0", locale),
        })}
      </p>

      {forecast?.excluded_first_invoice && (
        <p className="muted" data-testid="forecast-excluded-note">
          {t("forecast.firstInvoiceExcluded", {
            date: formatDate(forecast.first_invoice_date, locale),
          })}
        </p>
      )}

      <div className="table-wrap">
        <table className="data-table data-table-dense">
          <thead>
            <tr>
              <th>{t("forecast.invoiceDate")}</th>
              <th>{t("forecast.period")}</th>
              <th className="contract-num">{t("forecast.amount")}</th>
              <th>{t("forecast.status")}</th>
            </tr>
          </thead>
          <tbody>
            {(forecast?.rows ?? []).map((row) => (
              <tr key={row.invoice_date + row.period_start}>
                <td>{formatDate(row.invoice_date, locale)}</td>
                <td>
                  {formatPeriod(row.period_start, locale)}
                  {row.is_prorated && (
                    <Term term="prorated" onOpen={onTerm}>
                      <span className="cell-tag cell-tag-muted" style={{ marginLeft: 6 }}>
                        {t("forecast.prorated")}
                      </span>
                    </Term>
                  )}
                </td>
                <td className="contract-num">{formatMoney(row.amount, locale)}</td>
                <td>
                  <span className="cell-tag cell-tag-normal">
                    {t("forecast.planned")}
                  </span>
                </td>
              </tr>
            ))}
            {!loading && (forecast?.rows.length ?? 0) === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  {t("forecast.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="contract-forecast-summary" data-testid="forecast-summary">
        {/* Sprint 173 §6 — LABELLED. This figure is the revision in
            force TODAY, so a contract starting in 2027 reads 0,00
            beside a header saying EUR 2.500 and the two look like one
            number disagreeing with itself. The calculation is right;
            it was the label that was missing. Where nothing is in force
            yet the card says so rather than showing a zero. */}
        <SummaryItem
          label={<Term term="monthly" onOpen={onTerm}>{t("forecast.monthlyAmount")}</Term>}
          value={
            Number(forecast?.monthly_amount ?? 0) === 0 ? (
              <Term term="noneInForce" onOpen={onTerm}>{t("forecast.noneInForce")}</Term>
            ) : (
              formatMoney(forecast?.monthly_amount ?? "0", locale)
            )
          }
          hint={t("forecast.asOfToday")}
        />
        <SummaryItem
          label={<Term term="yearly" onOpen={onTerm}>{t("forecast.yearlyAmount")}</Term>}
          value={formatMoney(forecast?.yearly_amount ?? "0", locale)}
        />
        <SummaryItem
          label={<Term term="invoicesPerYear" onOpen={onTerm}>{t("forecast.invoicesPerYear")}</Term>}
          value={String(forecast?.invoices_per_year ?? 0)}
        />
      </div>
    </section>
  );
}

function SummaryItem({
  label,
  value,
  hint,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="summary-stat">
      <span className="summary-stat-label">{label}</span>
      <span className="summary-stat-value">{value}</span>
      {hint && <span className="summary-stat-meta">{hint}</span>}
    </div>
  );
}
