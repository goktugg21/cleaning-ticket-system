/**
 * W1-C (`docs/planning/ew-gap-closing-plan.md` §2.4) — the money strip.
 *
 * FOUR figures, each labelled so an operator knows what it means without
 * asking anybody. They are deliberately not attached to a chip and they
 * are deliberately not five:
 *
 *   1. Quoted, not yet started  price agreed, nobody has begun.
 *   2. In progress             begun, not finished.
 *   3. Done this period        finished inside the billing month.
 *   4. Invoiced this period    of (3), the part already billed.
 *
 * (1) and (2) are where the open book stands right now. (3) and (4) are
 * one billing month, and (4) is a SUBSET of (3) — its label says so out
 * loud ("of that, invoiced") because a strip whose numbers look like
 * four independent totals invites somebody to add them up.
 *
 * ## W-NAV1.2b — four figures, but never four on one page
 *
 * The strip rendered all four on BOTH pages, so each page showed half
 * its money and half somebody else's. The owner's rule is that a page
 * shows only its own. The split follows the split W-NAV1.2 already made
 * in the pages themselves:
 *
 *   Extra Work Quote   (1) alone. The page holds requests with no
 *                      operational ticket, so (2), (3) and (4) are by
 *                      definition about rows that are NOT on it.
 *   Chargeable work    (2), (3), (4). Work has started on everything
 *                      this page lists, so (1) is about rows that are
 *                      NOT on it.
 *
 * `figures` is a REQUIRED prop, not a variant name with a default: a
 * default is how a third caller silently gets somebody else's money
 * again. Naming the keys also keeps the choice in the page that owns
 * the money, where it can be read next to the rows it describes.
 *
 * No figure is COMPUTED differently — this is display selection and
 * nothing else. The endpoint still returns all four; each page renders
 * the ones that are its own.
 *
 * ## W2-C — the same four figures, half the height
 *
 * The owner: "there are a lot of chips and cards. it looks confusing
 * make them simpler. without giving up important information." Measured
 * at 1440x1000, this strip was 184px of a 702px wall of controls
 * standing between the page header and the first row of data.
 *
 * What went: the four icon tiles (a generic clock / hammer / check /
 * banknote said nothing the label did not) and the padding around them.
 * What stayed: every figure, every label, the sentence under each one,
 * the request count and the unpriced count. The sentences were REWRITTEN
 * rather than trimmed — each now states the CONSEQUENCE the label does
 * not ("money committed, not yet earned"), because a second sentence
 * that only rephrases the heading is two lines earning one line's worth.
 *
 * ## Where the numbers come from
 *
 * `GET /api/extra-work/financial-summary/` — ONE server aggregate over
 * every Extra Work in scope, not a sum of whatever page a list is
 * holding. Every amount there goes through the server-side mirror of
 * `rowAmounts()` (`frontend/src/lib/billing.ts`), so this component
 * NEVER does arithmetic: it formats decimal strings and nothing else.
 * Adding a subtotal here, however small, would be the second money
 * formula the plan forbids.
 *
 * ## Zero versus unpriced
 *
 * Zero is a legal price — free work and goodwill lines are ordinary
 * business — so "€ 0,00" has to keep meaning "this costs nothing". A
 * figure renders an EM DASH only when it would print zero AND every
 * request behind it is unpriced: there, the zero is an absence rather
 * than a price, and the footnote says how many rows it stands for.
 *
 * BOTH halves of that test are required, and the dev data is why. Four
 * seeded requests carry a cached total (EUR 1028.50, EUR 1500.40, …)
 * with no pricing lines at all, so `is_priced` is false while
 * `rowAmounts()` has a real amount to show. Dashing on `is_priced`
 * alone would have hidden EUR 5941.10 behind a dash on this very
 * screen, next to a KPI card showing the same money — which is a worse
 * lie than the one the dash exists to prevent. When there IS an amount,
 * the amount is shown and the footnote carries the caveat.
 *
 * The SUM is unaffected either way: an unpriced row contributes zero,
 * because zero is what it contributes (`sumRows` in `lib/billing.ts`
 * says the same in as many words).
 *
 * ## Who sees it
 *
 * Provider management only. The endpoint answers 403 to anybody else, so
 * the gate lives here rather than in each page — two callers cannot then
 * disagree about it, and a customer never issues the request at all.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getExtraWorkFinancialSummary } from "../../api/extraWork";
import type {
  ExtraWorkFinancialFigure,
  ExtraWorkFinancialFigureKey,
  ExtraWorkFinancialSummary,
} from "../../api/extraWork";
import { getApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { isProviderManagementRole } from "../../auth/permissions";
import { formatMoney } from "../../lib/intl";

/**
 * The four figures in reading order, as ONE constant keyed by the union.
 *
 * A `Record` over `ExtraWorkFinancialFigureKey` rather than an array
 * literal, because the compiler then refuses a fifth figure that has no
 * entry here and refuses to drop one that does — the Sprint 126/130
 * lesson in CLAUDE.md, where a second hand-maintained render array left
 * a whole permission group invisible for three sprints. Render order is
 * this object's declaration order, which is what `Object.keys` returns
 * for string keys, so there is no second list to keep in step.
 *
 * W2-C — the value was a `LucideIcon` until the icons came out. It is
 * `true` now: the Record is carried for the exhaustiveness check alone,
 * which is the only reason it ever existed.
 *
 * W-NAV1.2b — it earns that keep twice over now. Each variant below
 * renders a FILTER over this one order, not a second hand-written list:
 * a fifth figure still has to be placed here, and each page still shows
 * its own figures in the one canonical reading order.
 */
const FIGURE_KEYS: Record<ExtraWorkFinancialFigureKey, true> = {
  quoted_not_started: true,
  in_progress: true,
  done_this_period: true,
  invoiced_this_period: true,
};

const FIGURE_ORDER = Object.keys(
  FIGURE_KEYS,
) as ExtraWorkFinancialFigureKey[];

/**
 * Which figures each page owns.
 *
 * A `variant` rather than two exported key arrays: exporting a non
 * component from a component file trips `react-refresh/only-export-
 * components`, and the baseline admits no new violations. It is the
 * better shape anyway — the two pages name WHICH VIEW they are, and the
 * mapping from view to figures stays here next to the figures, so the
 * split can never be half-changed in one page and not the other.
 *
 *   quote      price agreed, nobody has begun. What the Extra Work
 *              Quote list holds, and the only figure about it.
 *   execution  begun, finished this month, and the billed part of that.
 *              What the Chargeable work view holds.
 *
 * Between them they name all four exactly once — the strip has no
 * figure that belongs to neither page and none that belongs to both.
 */
export type FinancialStripVariant = "quote" | "execution";

const VARIANT_FIGURES: Record<
  FinancialStripVariant,
  ReadonlyArray<ExtraWorkFinancialFigureKey>
> = {
  quote: ["quoted_not_started"],
  execution: ["in_progress", "done_this_period", "invoiced_this_period"],
};

function FigureCard({
  figureKey,
  figure,
  period,
  testIdPrefix,
}: {
  figureKey: ExtraWorkFinancialFigureKey;
  figure: ExtraWorkFinancialFigure | null;
  period: string;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("extra_work");
  // The figure would print zero AND nobody has priced any of the work
  // behind it, so that zero is an ABSENCE, not a price.
  // `formatMoney(null)` is the app's one em dash — not a second dash
  // literal typed here.
  //
  // The zero test is a STRING compare against the server's fixed 2dp
  // wire shape, deliberately: this component does no arithmetic on
  // money, not even a parse, because the server has already applied the
  // one billing rule and a number parsed here is a number that can
  // drift from it.
  const isAbsence =
    figure !== null &&
    figure.count > 0 &&
    figure.unpriced_count === figure.count &&
    figure.total === "0.00";

  return (
    <div className="ew-money-card" data-testid={`${testIdPrefix}-${figureKey}`}>
      <div className="ew-money-card-body">
        <div className="ew-money-card-label">
          {t(`financial_strip.${figureKey}_label`)}
        </div>
        <div className="ew-money-card-value">
          {figure === null
            ? formatMoney(null)
            : formatMoney(isAbsence ? null : figure.total)}
        </div>
        <div className="ew-money-card-meta">
          {t(`financial_strip.${figureKey}_meta`, { period })}
        </div>
        {figure !== null && (
          <div className="ew-money-card-foot">
            {t("financial_strip.request_count", { count: figure.count })}
            {figure.unpriced_count > 0 && (
              // One phrasing for every case, "5 of 5" included: it is
              // the precise sentence whether it explains a dash or
              // qualifies an amount, and two near-identical strings
              // would be two chances to say it differently.
              <span className="ew-money-card-unpriced">
                {" "}
                {/* Not `count`: i18next reserves that name for
                    pluralisation and would go looking for `_one` /
                    `_other` variants this key does not have. */}
                {t("financial_strip.unpriced", {
                  unpriced: figure.unpriced_count,
                  total: figure.count,
                })}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function FinancialStrip({
  variant,
  customerId,
  buildingId,
  testIdPrefix = "ew-money-strip",
}: {
  /** Which view this is, and so which figures are its own. Required —
   *  see the W-NAV1.2b note at the top of the file. A default is how a
   *  third caller silently gets somebody else's money again. */
  variant: FinancialStripVariant;
  /** Narrow to one customer — the customer-scoped mounts of the two
   *  pages. A convenience only: the server scopes first, so naming a
   *  customer the actor cannot see returns nothing, not their money. */
  customerId?: number;
  buildingId?: number;
  testIdPrefix?: string;
}) {
  const { me } = useAuth();
  const isProvider = isProviderManagementRole(me?.role);
  const [summary, setSummary] = useState<ExtraWorkFinancialSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // No synchronous `setState` in the effect body (the house rule, and
  // `react-hooks/set-state-in-effect`): `loading` starts true and is
  // only ever turned off, in the async callback. A refetch after a prop
  // change therefore keeps the previous figures on screen until the new
  // ones land, which beats blanking four numbers to em dashes and back.
  useEffect(() => {
    if (!isProvider) return;
    let cancelled = false;
    getExtraWorkFinancialSummary({
      customer: customerId,
      building: buildingId,
    })
      .then((data) => {
        if (cancelled) return;
        setSummary(data);
        setError("");
      })
      .catch((err) => {
        if (cancelled) return;
        setSummary(null);
        setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isProvider, customerId, buildingId]);

  if (!isProvider) return null;

  const period = summary?.period ?? "";

  return (
    <section
      className="ew-money-strip"
      data-testid={testIdPrefix}
      aria-busy={loading}
    >
      {/* W-NAV1.2b — the heading block is gone, both variants.
          It read "Money — where it stands now" over "Two figures for
          today, and two for billing month X", and after the split that
          sentence is false on BOTH pages: the quote list shows one
          figure and the chargeable view shows one for today and two for
          the month. Rewriting it would be new prose on two pages that
          did not ask for any, and keeping it would be a counted claim
          that no longer counts. The tile labels already name every
          figure, and the billing month it applies to is still spelled
          out in `done_this_period_meta`, so nothing that was on screen
          has gone missing with it. */}
      {error ? (
        <p
          className="muted small"
          role="status"
          data-testid={`${testIdPrefix}-error`}
        >
          {error}
        </p>
      ) : (
        <div className="ew-money-strip-row">
          {/* Filtered out of the ONE canonical order, so each page
              renders its own figures in the same reading order the
              strip has always used. */}
          {FIGURE_ORDER.filter((key) =>
            VARIANT_FIGURES[variant].includes(key),
          ).map((key) => (
            <FigureCard
              key={key}
              figureKey={key}
              figure={summary ? summary.figures[key] : null}
              period={period}
              testIdPrefix={testIdPrefix}
            />
          ))}
        </div>
      )}
    </section>
  );
}
