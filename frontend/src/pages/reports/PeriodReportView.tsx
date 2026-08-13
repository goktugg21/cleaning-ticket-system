import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";

/**
 * Sprint 178 §2 — the shell every one of the four new reports sits in.
 *
 * All four take the same `?from=&to=` period, return the same envelope
 * (`from`, `to`, a body, a `total`) and offer the same CSV and PDF, so
 * the period picker, the fetch, the loading and error states and the two
 * download buttons are written ONCE here. The four report views are then
 * just "what does a row look like".
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
 */

export interface PeriodPayload {
  from: string;
  to: string;
  total: string | number;
  generated_at?: string;
}

export function PeriodReportView<T extends PeriodPayload>({
  endpoint,
  stem,
  emptyHint,
  children,
  testIdPrefix,
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
}) {
  const { t } = useTranslation(["reports", "common"]);

  const today = new Date();
  const start = new Date(today.getTime() - 27 * 24 * 60 * 60 * 1000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);

  const [from, setFrom] = useState(iso(start));
  const [to, setTo] = useState(iso(today));
  const [payload, setPayload] = useState<T | null>(null);
  const [error, setError] = useState("");
  // A request KEY rather than a loading boolean set in an effect body:
  // `react-hooks/set-state-in-effect` forbids the latter, and deriving
  // "is this the answer I asked for" from the key is what the rest of
  // this app does (see CatalogTab).
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const requestKey = `${from}:${to}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api
      .get<T>(endpoint, { params: { from, to } })
      .then((response) => {
        if (cancelled) return;
        setPayload(response.data);
        setError("");
        setLoadedKey(`${from}:${to}`);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(getApiError(err));
        setPayload(null);
        setLoadedKey(`${from}:${to}`);
      });
    return () => {
      cancelled = true;
    };
  }, [endpoint, from, to]);

  async function download(fmt: "csv" | "pdf") {
    try {
      const response = await api.get(`${endpoint}export.${fmt}`, {
        params: { from, to },
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

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      {loading && (
        <div className="loading-bar" style={{ margin: 0 }}>
          <div className="loading-bar-fill" />
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
            </div>
          ) : (
            children(payload)
          )}
        </>
      )}
    </div>
  );
}
