import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";
import type { ReportFilters } from "../../api/reports";

/**
 * Sprint 178 §2 — the shell every one of the four new reports sits in.
 *
 * All four take the same period, return the same envelope (`from`, `to`,
 * a body, a `total`) and offer the same CSV and PDF, so the period
 * picker, the fetch, the loading and error states and the two download
 * buttons are written ONCE here. The four report views are then just
 * "what does a row look like".
 *
 * That is the same reasoning `CatalogTab` embodies for the catalogs, and
 * the reason there is no page per report: four copies of a period picker
 * is four places for the CSV and the screen to start disagreeing about
 * which period they are showing.
 *
 * The download is the Sprint 171 blob + object-URL + synthetic anchor
 * pattern, unchanged — the export travels with the SAME query string the
 * JSON fetch used, so a file can never cover a different period than the
 * table it was downloaded from.
 *
 * ## Sprint 180 §1 — the page's filters reach in here
 *
 * The Reports page computes a company, a building and a date range and
 * hands them to its twelve charts. The four report cards were rendered
 * with no props at all and this shell accepted only a from/to pair of
 * its own, defaulting to the last 28 days — so "this building, last
 * month" was answerable on one half of the page and not on the other,
 * and that is the question an operator asks every day.
 *
 * Now `filters` comes in from the page:
 *
 *   * `company` and `building` are read-only here and travel on every
 *     request, JSON and export alike. They are not editable inside the
 *     modal on purpose — the page's own pickers are two centimetres
 *     away, and a second pair would be a second answer to "which
 *     building am I looking at";
 *   * `from` / `to` SEED the local period, which stays editable. The
 *     modal mounts fresh each time a card is opened, so the seed is
 *     always the page's current range; narrowing the period for one
 *     report without disturbing the twelve charts behind it is worth
 *     the local state.
 *
 * The server echoes the resolved scope back as `payload.scope`, with the
 * NAMES, so the header line below states which slice is on screen
 * without this component having to look a building up.
 */

/** The `scope` echo every one of the four endpoints returns. */
export interface ReportScope {
  company_id: number | null;
  company_name: string | null;
  building_id: number | null;
  building_name: string | null;
}

export interface PeriodPayload {
  from: string;
  to: string;
  total: string | number;
  generated_at?: string;
  scope?: ReportScope;
}

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function isoDaysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
}

export function PeriodReportView<T extends PeriodPayload>({
  endpoint,
  stem,
  emptyHint,
  children,
  testIdPrefix,
  filters,
}: {
  /** e.g. "/reports/employee-hours-by-building/" — with its trailing slash. */
  endpoint: string;
  /** Download filename stem, matching the server's own. */
  stem: string;
  /**
   * What to say when the report is correct but has nothing in it. The
   * distinction matters enough to be a required prop: an operator must
   * never have to guess whether an empty screen means "no data" or
   * "broken".
   */
  emptyHint: string;
  children: (payload: T) => ReactNode;
  testIdPrefix: string;
  /**
   * The Reports page's filter bar. `company` / `building` apply as they
   * come; `from` / `to` seed the editable period below. The 28-day
   * fallback is kept for a caller that has no page filters yet.
   */
  filters: ReportFilters;
}) {
  const { t } = useTranslation(["reports", "common"]);

  const [from, setFrom] = useState(() => filters.from ?? isoDaysAgo(27));
  const [to, setTo] = useState(() => filters.to ?? isoToday());
  const [payload, setPayload] = useState<T | null>(null);
  const [error, setError] = useState("");

  const company = filters.company;
  const building = filters.building;

  // ONE param object for the fetch and both downloads, so a file can
  // never cover a different slice than the table it came from.
  const params = useMemo(() => {
    const out: Record<string, string> = { from, to };
    if (company !== undefined) out.company = String(company);
    if (building !== undefined) out.building = String(building);
    return out;
  }, [from, to, company, building]);

  // A request KEY rather than a loading boolean set in an effect body:
  // `react-hooks/set-state-in-effect` forbids the latter, and deriving
  // "is this the answer I asked for" from the key is what the rest of
  // this app does (see CatalogTab). The company and the building are
  // part of the key — without them a filter change would leave the
  // previous slice's rows on screen looking answered.
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const requestKey = `${from}:${to}:${company ?? ""}:${building ?? ""}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const key = `${params.from}:${params.to}:${params.company ?? ""}:${params.building ?? ""}`;
    api
      .get<T>(endpoint, { params })
      .then((response) => {
        if (cancelled) return;
        setPayload(response.data);
        setError("");
        setLoadedKey(key);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(getApiError(err));
        setPayload(null);
        setLoadedKey(key);
      });
    return () => {
      cancelled = true;
    };
  }, [endpoint, params]);

  async function download(fmt: "csv" | "pdf") {
    try {
      const response = await api.get(`${endpoint}export.${fmt}`, {
        params,
        responseType: "blob",
      });
      const href = URL.createObjectURL(response.data as Blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `${stem}-${from}-to-${to}.${fmt}`;
      anchor.click();
      URL.revokeObjectURL(href);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  // The scope the SERVER resolved, not the ids this component was
  // handed: it carries the names, and it is the proof that the filter
  // actually reached the query rather than only the URL.
  const scope = payload?.scope;
  const scopeParts: string[] = [];
  if (scope?.company_name) {
    scopeParts.push(t("period_scope_company", { name: scope.company_name }));
  }
  if (scope?.building_name) {
    scopeParts.push(t("period_scope_building", { name: scope.building_name }));
  }

  return (
    <div data-testid={`${testIdPrefix}-view`}>
      <div
        className="filter-bar"
        style={{ marginBottom: 12, alignItems: "flex-end" }}
      >
        <div className="filter-field">
          <span className="filter-label">{t("period_from")}</span>
          <input
            type="date"
            className="filter-control"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
            data-testid={`${testIdPrefix}-from`}
          />
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("period_to")}</span>
          <input
            type="date"
            className="filter-control"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            data-testid={`${testIdPrefix}-to`}
          />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void download("csv")}
            disabled={loading || !payload}
            data-testid={`${testIdPrefix}-export-csv`}
          >
            {t("period_export_csv")}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void download("pdf")}
            disabled={loading || !payload}
            data-testid={`${testIdPrefix}-export-pdf`}
          >
            {t("period_export_pdf")}
          </button>
        </div>
      </div>

      {scopeParts.length > 0 && (
        <p
          className="muted small"
          style={{ marginTop: 0, marginBottom: 12 }}
          data-testid={`${testIdPrefix}-scope`}
        >
          {scopeParts.join(" · ")}
        </p>
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      {loading && (
        <div
          className="skeleton-lines"
          aria-hidden="true"
          data-testid={`${testIdPrefix}-skeleton`}
          style={{ padding: "8px 0 16px" }}
        >
          <span className="skeleton-line" style={{ width: "40%" }} />
          <span className="skeleton-line" />
          <span className="skeleton-line" style={{ width: "85%" }} />
          <span className="skeleton-line short" />
        </div>
      )}

      {!loading && !error && payload && (
        <>
          {/* An empty report is an ANSWER, and says so. The alternative
              is a blank panel an operator reads as a broken screen.

              Sprint 179B §4 — and it now LOOKS like one. The sentence
              was a single 14px grey line at the left edge of a 1320px
              panel: `.muted` sets colour only, so it inherited the body
              size and sat one step LARGER than every other secondary
              line on the screen, with no margin, no padding and nothing
              around it. This is the house empty state — the same
              `.empty-state` / `.empty-title` / `.empty-sub` the admin
              lists use — so a report with nothing in it reads as a
              finished screen rather than a failed one. */}
          {Number(payload.total) === 0 ? (
            <div className="empty-state" data-testid={`${testIdPrefix}-empty`}>
              <div className="empty-title">{t("period_empty_title")}</div>
              <p className="empty-sub">{emptyHint}</p>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  // One obvious action: a year back from the end date.
                  const end = new Date(to);
                  end.setDate(end.getDate() - 365);
                  setFrom(end.toISOString().slice(0, 10));
                }}
                data-testid={`${testIdPrefix}-widen`}
              >
                {t("widen_period")}
              </button>
            </div>
          ) : (
            children(payload)
          )}
        </>
      )}
    </div>
  );
}
