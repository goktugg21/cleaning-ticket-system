import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  getExtraWorkRegister,
  syncExtraWorkRegister,
} from "../../../api/contracts";
import type { ExtraWorkRegister } from "../../../api/contracts.types";
import { useToast } from "../../../components/ToastProvider";
import { formatMoney } from "../contracts/contractTables";

/**
 * W16 — THE EXTRA WORKS REGISTER, one per customer.
 *
 *     The owner: "make the contracts page exactly the same as my
 *     father's system. Establish those connections."
 *
 * His `getOrCreateExtraWorksContract($customerId)` gives every customer
 * an auto-created contract carrying one line per piece of ad-hoc work,
 * grouped by building, with a total. That is this section.
 *
 * ## What it does NOT have, and why
 *
 * His screen has Add / Edit / Delete on the lines. This one has none of
 * the three, and that is the deliberate half of the copy.
 *
 * His lines are typed by hand: an operator writes a description and an
 * amount, and `ContractLine` in his schema carries no link to the job —
 * no ExtraWork controller or service in his codebase touches
 * `ContractLine` at all. So his register is a second set of books kept
 * in step by memory, and it is silently wrong the moment a price moves.
 *
 * Ours is a PROJECTION. Every line mirrors a real Extra Work through
 * `ContractLine.extra_work`, and its amount is rebuilt server-side from
 * the same rule the invoice reads. "Edit this line" would mean "write a
 * number the next sync overwrites", so the row links to the job
 * instead: the Extra Work is the one place that number is allowed to
 * live.
 *
 * ## Three figures, because one would be a lie
 *
 * Measured on the demo data while this was built: the register held
 * EUR 990.99 of finished work while the invoice run could only offer
 * EUR 660.66, because a third job had already been billed. A single
 * "total" would have read as "still to bill" and been wrong by a third.
 * So the strip says what has been taken on, what is finished, and what
 * is still to bill — and the last is the subtraction, done here rather
 * than in the reader's head.
 */
export function ExtraWorkRegisterSection({
  customerId,
  canManage,
}: {
  customerId: number;
  canManage: boolean;
}) {
  const { t, i18n } = useTranslation("contracts");
  const toast = useToast();
  const locale = i18n.language;

  const [register, setRegister] = useState<ExtraWorkRegister | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(() => {
    if (!Number.isFinite(customerId)) return undefined;
    let cancelled = false;
    getExtraWorkRegister(customerId)
      .then((data) => {
        if (cancelled) return;
        setRegister(data);
        setError("");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  useEffect(load, [load]);

  async function resync() {
    setSyncing(true);
    try {
      const data = await syncExtraWorkRegister(customerId);
      setRegister(data);
      const changed = data.changed;
      // W13 §4 — the action ANSWERS, and it names numbers. "Refreshed"
      // is not an answer; "2 jobs added, 1 reprice" is.
      toast.push({
        variant: "success",
        title: t("register.syncedTitle"),
        description: t("register.syncedBody", {
          added: changed?.added ?? 0,
          updated: changed?.updated ?? 0,
          removed: changed?.removed ?? 0,
        }),
      });
    } catch (err) {
      toast.push({
        variant: "error",
        title: t("register.syncFailed"),
        description: getApiError(err),
      });
    } finally {
      setSyncing(false);
    }
  }

  if (error) {
    return (
      <div className="card card-detail-pad" data-testid="ew-register">
        <div className="alert-error">{error}</div>
      </div>
    );
  }

  const summary = register?.summary;
  const stillToBill =
    summary === undefined
      ? "0"
      : String(
          Number(summary.earned_amount) - Number(summary.invoiced_amount),
        );
  const withWork = (register?.buildings ?? []).filter(
    (building) => building.job_count > 0,
  );

  return (
    <div className="card card-detail-pad" data-testid="ew-register">
      {/* A NAME, a TABLE and ONE BUTTON. */}
      <header className="section-head">
        <div>
          <div className="section-head-title">{t("register.title")}</div>
          <div className="section-head-sub">{t("register.why")}</div>
        </div>
        {canManage && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void resync()}
            disabled={syncing}
            data-testid="ew-register-sync"
          >
            <RefreshCw size={14} aria-hidden="true" />
            {syncing ? t("register.syncing") : t("register.sync")}
          </button>
        )}
      </header>

      {/* The same `summary-grid` / `summary-stat` the contract detail
          page's tiles use — the design system's, not a third one this
          section invents. */}
      {summary && (
        <div className="summary-grid" data-testid="ew-register-figures">
          <Tile
            label={t("register.committed")}
            value={formatMoney(summary.total_amount, locale)}
            hint={t("register.jobs", { count: summary.job_count })}
          />
          <Tile
            label={t("register.earned")}
            value={formatMoney(summary.earned_amount, locale)}
            hint={t("register.earnedHint")}
          />
          <Tile
            label={t("register.stillToBill")}
            value={formatMoney(stillToBill, locale)}
            hint={t("register.stillToBillHint")}
          />
        </div>
      )}

      <div className="table-wrap">
        <table className="data-table data-table-dense">
          <thead>
            <tr>
              <th>{t("register.job")}</th>
              <th className="contract-num">{t("register.amount")}</th>
            </tr>
          </thead>
          <tbody>
            {withWork.map((building) => (
              <Fragment key={building.id}>
                <tr className="contract-group-row">
                  <th scope="rowgroup">{building.name}</th>
                  <td className="contract-num">
                    {formatMoney(building.total_amount, locale)}
                  </td>
                </tr>
                {building.lines.map((line) => (
                  <tr key={line.id}>
                    <td>
                      {/* The row goes to the JOB, because that is where
                          its number is decided and the only place it
                          can be changed. */}
                      {line.extra_work ? (
                        <Link to={`/extra-work/${line.extra_work}`}>
                          {line.name}
                        </Link>
                      ) : (
                        line.name
                      )}
                    </td>
                    <td className="contract-num">
                      {formatMoney(line.amount, locale)}
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
            {loaded && withWork.length === 0 && (
              <tr>
                <td colSpan={2} className="muted">
                  {t("register.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}


/** The design system's summary tile, same markup as the contract
 *  detail page's header tiles. */
function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="summary-stat">
      <span className="summary-stat-label">{label}</span>
      <span className="summary-stat-value">{value}</span>
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}
