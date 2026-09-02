// Sprint 11/12 frontend — RecurringJob list. Provider-only surface;
// the route guard + backend both gate STAFF / CUSTOMER_USER out.
//
// The list viewset does no server-side filtering, so the active/archived
// filter + search run client-side over the (generously paged) result set.
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CalendarClock, PlusCircle, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  getPlannedOccurrenceStats,
  listRecurringJobs,
  type PlannedOccurrenceStats,
} from "../../api/plannedWork";
import type { RecurringJob } from "../../api/plannedWork.types";
import { getApiError } from "../../api/client";
import { ClickableRow } from "../../components/ClickableRow";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { RoadTabs, TeachHead } from "../../components/guide/RoadTabs";
import { StartHere } from "../../components/guide/StartHere";
import { TeachEmpty } from "../../components/guide/TeachEmpty";

// P-12 E1 (§D.24 rule 3) — the rule's road: it runs, it can be paused
// (the stored mechanism is the archive — revivable, generation stops),
// and it ends when its end date passes. ONE ordered constant.
const PW_ROAD = ["active", "paused", "ended"] as const;
type PwRoadKey = (typeof PW_ROAD)[number];

function roadOf(job: RecurringJob, todayIso: string): PwRoadKey {
  if (!job.is_active || job.archived_at) return "paused";
  if (job.end_date && job.end_date < todayIso) return "ended";
  return "active";
}

function parseRoadTab(raw: string | null): PwRoadKey {
  return (PW_ROAD as readonly string[]).includes(raw ?? "")
    ? (raw as PwRoadKey)
    : "active";
}

/** P-12 E1 (§D.24 rule 6) — the rule's connections, in words: which
 *  contract line it runs for, and how it is invoiced. */
function connectionWords(
  job: RecurringJob,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const billed =
    job.pricing_mode === "FIXED"
      ? t("list.billed_per_visit")
      : job.contract_line
        ? t("list.billed_with_contract")
        : t("list.billed_no_line");
  return job.contract_line_name
    ? `${t("list.runs_for_line", { line: job.contract_line_name })} · ${billed}`
    : billed;
}

/** P-6 V2 — "2 × · 08:00, 14:00": how many visits a day and when. A job
 *  with no clock says so in words (rule 15), never a dash. */
function windowSummary(
  job: RecurringJob,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const active = job.windows.filter((w) => w.is_active);
  const times = active
    .map((w) => (w.start_time ? w.start_time.slice(0, 5) : ""))
    .filter(Boolean);
  const count = Math.max(active.length, 1);
  return `${count} × · ${times.length > 0 ? times.join(", ") : t("list.window_time_none")}`;
}

/** "Wekelijks · ma, do" — the frequency with its weekdays. */
function ruleSummary(
  job: RecurringJob,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const frequency = t(`frequency.${job.frequency}`);
  const named = job.frequency === "WEEKLY" || job.frequency === "BIWEEKLY";
  if (!named || job.weekdays.length === 0) return frequency;
  const days = [...job.weekdays]
    .sort((a, b) => a - b)
    .map((d) => t(`weekday_short.${d}`))
    .join(", ");
  return t("list.rule_days", { frequency, days });
}

export function PlannedWorkListPage() {
  const { t } = useTranslation(["planned_work", "common"]);

  const [rows, setRows] = useState<RecurringJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  // The tab in the address (§D.22 rule 3).
  const [searchParams, setSearchParams] = useSearchParams();
  const roadTab = parseRoadTab(searchParams.get("tab"));
  const setRoadTab = (next: PwRoadKey) => {
    const params = new URLSearchParams(searchParams);
    if (next === "active") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  };
  // P-12 E1 — this week's uncrewed visits (Start here).
  const [weekStats, setWeekStats] = useState<PlannedOccurrenceStats | null>(null);
  useEffect(() => {
    let cancelled = false;
    const today = new Date();
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    const end = new Date(today);
    end.setDate(end.getDate() + 6);
    getPlannedOccurrenceStats({ date_from: iso(today), date_to: iso(end) })
      .then((stats) => {
        if (!cancelled) setWeekStats(stats);
      })
      .catch(() => {
        // The list still works; Start here simply stays away.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const response = await listRecurringJobs();
        if (!cancelled) setRows(response.results);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const todayIso = new Date().toISOString().slice(0, 10);
  const roadCounts = useMemo(() => {
    const counts: Record<PwRoadKey, number> = { active: 0, paused: 0, ended: 0 };
    for (const job of rows) counts[roadOf(job, todayIso)] += 1;
    return counts;
  }, [rows, todayIso]);

  const visibleRows = useMemo(() => {
    const needle = searchInput.trim().toLowerCase();
    return rows.filter((job) => {
      if (roadOf(job, todayIso) !== roadTab) return false;
      if (needle) {
        const hay = `${job.title} ${job.building_name ?? ""} ${
          job.customer_name ?? ""
        }`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [rows, searchInput, roadTab, todayIso]);

  const hasFilters = searchInput.trim().length > 0;

  return (
    <div data-testid="planned-work-list-page">
      <PageHeader
        backLink={{ to: "/", label: t("list.back_to_dashboard") }}
        eyebrow={t("common:ops")}
        title={t("list.page_title")}
        subtitle={
          loading
            ? t("list.loading")
            : `${t("list.page_subtitle")} ${t("list.count", { count: visibleRows.length })}.`
        }
        actions={
          <Link
            className="btn btn-primary btn-sm"
            to="/planned-work/new"
            data-testid="planned-work-create-link"
          >
            <PlusCircle size={14} strokeWidth={2.2} />
            <span style={{ marginLeft: 6 }}>{t("list.create_button")}</span>
          </Link>
        }
      />

      {loading && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* P-12 E1 (§D.24 rule 2) — the ONE thing waiting: this week's
          visits with no crew, with the door to the soonest one. */}
      {weekStats && weekStats.no_crew > 0 && weekStats.no_crew_first && (
        <StartHere
          testId="planned-work-start-here"
          action={{
            label: t("list.start_no_crew_action"),
            to: `/planned-work/${weekStats.no_crew_first.recurring_job}`,
          }}
        >
          {t("list.start_no_crew", {
            count: weekStats.no_crew,
            rule: weekStats.no_crew_first.recurring_job_title,
          })}
        </StartHere>
      )}

      {/* P-12 E1 (§D.24 rule 3) — the rule's road as the tabs. */}
      <RoadTabs
        steps={PW_ROAD.map((key) => ({
          key,
          step: t(`road.${key}_step`),
          label: t(`road.${key}_label`),
          count: loading ? null : roadCounts[key],
        }))}
        activeKey={roadTab}
        onSelect={(key) => setRoadTab(key)}
        ariaLabel={t("list.page_title")}
        testIdPrefix="planned-work-tab"
      />
      <TeachHead
        testId="planned-work-teach"
        title={t(`road.${roadTab}_title`)}
        body={t(`road.${roadTab}_body`)}
      />

      <div className="card ew-list-filters" data-testid="planned-work-filters">
        <div className="filter-field search">
          <Search size={14} strokeWidth={2.2} />
          <input
            className="filter-control"
            type="search"
            placeholder={t("list.search_placeholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
      </div>

      {!loading && visibleRows.length === 0 && !error && (
        hasFilters ? (
          <EmptyState
            icon={CalendarClock}
            title={t("list.empty_filtered_title")}
            description={t("list.empty_filtered_desc")}
            testId="planned-work-empty"
          />
        ) : (
          /* §D.24 rule 5 — the empty tab teaches how a rule gets here. */
          <div className="card">
            <TeachEmpty
              testId={`planned-work-road-empty-${roadTab}`}
              title={t(`road.${roadTab}_empty_title`)}
              body={t(`road.${roadTab}_empty_body`)}
              action={
                roadTab === "active"
                  ? { label: t("list.create_button"), to: "/planned-work/new" }
                  : undefined
              }
            />
          </div>
        )
      )}

      {visibleRows.length > 0 && (
        <div className="responsive-table-wrap">
          {/* FE-7 — the card clipped its own table at 768 (overflow hidden,
              no scroller); the wrap scrolls the table inside the card. */}
          <div className="card table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("list.col_title")}</th>
                  <th>{t("list.col_building")}</th>
                  <th>{t("list.col_customer")}</th>
                  <th>{t("list.col_frequency")}</th>
                  <th>{t("list.col_window")}</th>
                  <th style={{ textAlign: "right" }}>
                    {t("list.col_occurrences")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((job) => (
                  <ClickableRow
                    key={job.id}
                    to={`/planned-work/${job.id}`}
                    testId="planned-work-row"
                  >
                    <td className="td-subject">
                      <Link to={`/planned-work/${job.id}`}>{job.title}</Link>
                      {/* §D.24 rule 6 — which contract line it runs
                          for and how it is invoiced, in words. */}
                      <span
                        className="muted small"
                        style={{ display: "block" }}
                        data-testid={`planned-work-connection-${job.id}`}
                      >
                        {connectionWords(job, t)}
                      </span>
                    </td>
                    <td>{job.building_name}</td>
                    <td>{job.customer_name}</td>
                    <td>{ruleSummary(job, t)}</td>
                    <td className="muted small">{windowSummary(job, t)}</td>
                    <td style={{ textAlign: "right" }}>
                      {job.occurrences_count}
                    </td>
                  </ClickableRow>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card fallback */}
          <ul
            className="admin-card-list"
            data-testid="admin-card-list"
            aria-label={t("list.page_title")}
          >
            {visibleRows.map((job) => (
              <li key={job.id} className="admin-card">
                <Link
                  to={`/planned-work/${job.id}`}
                  className="admin-card-link"
                  data-testid="planned-work-card"
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{job.title}</span>
                    <StatusBadge
                      variant="cell"
                      status={{
                        kind: "generic",
                        tone: job.is_active ? "approved" : "closed",
                        label: t(`road.${roadOf(job, todayIso)}_label`),
                      }}
                    />
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("list.col_building")}</dt>
                      <dd>{job.building_name}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.col_customer")}</dt>
                      <dd>{job.customer_name}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.col_frequency")}</dt>
                      <dd>{ruleSummary(job, t)}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.col_window")}</dt>
                      <dd>{windowSummary(job, t)}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.col_occurrences")}</dt>
                      <dd>{job.occurrences_count}</dd>
                    </div>
                  </dl>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
