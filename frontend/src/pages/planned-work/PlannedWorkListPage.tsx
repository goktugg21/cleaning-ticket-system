// Sprint 11/12 frontend — RecurringJob list. Provider-only surface;
// the route guard + backend both gate STAFF / CUSTOMER_USER out.
//
// The list viewset does no server-side filtering, so the active/archived
// filter + search run client-side over the (generously paged) result set.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, PlusCircle, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listRecurringJobs } from "../../api/plannedWork";
import type { RecurringJob } from "../../api/plannedWork.types";
import { getApiError } from "../../api/client";
import { ClickableRow } from "../../components/ClickableRow";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { formatMoney } from "../../lib/intl";

type StatusFilter = "active" | "archived" | "all";

function windowSummary(job: RecurringJob): string {
  const parts: string[] = [];
  if (job.preferred_start_time) parts.push(job.preferred_start_time.slice(0, 5));
  if (job.time_window_label) parts.push(job.time_window_label);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export function PlannedWorkListPage() {
  const { t } = useTranslation(["planned_work", "common"]);

  const [rows, setRows] = useState<RecurringJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");

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

  function pricingSummary(job: RecurringJob): string {
    if (job.pricing_mode === "FIXED" && job.fixed_price != null) {
      return `${formatMoney(job.fixed_price)} ${t("pricing.ex_vat_suffix")}`;
    }
    if (job.pricing_mode === "HOURLY") return t("pricing_mode.HOURLY");
    return t("pricing.included");
  }

  const visibleRows = useMemo(() => {
    const needle = searchInput.trim().toLowerCase();
    return rows.filter((job) => {
      if (statusFilter === "active" && !job.is_active) return false;
      if (statusFilter === "archived" && job.is_active) return false;
      if (needle) {
        const hay = `${job.title} ${job.building_name ?? ""} ${
          job.customer_name ?? ""
        }`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [rows, searchInput, statusFilter]);

  const hasFilters = statusFilter !== "active" || searchInput.trim().length > 0;

  return (
    <div data-testid="planned-work-list-page">
      <PageHeader
        backLink={{ to: "/", label: t("list.back_to_dashboard") }}
        eyebrow={t("common:ops")}
        title={t("list.page_title")}
        subtitle={
          loading
            ? t("list.loading")
            : t("list.count", { count: visibleRows.length })
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
        <div className="filter-field">
          <span className="filter-label">{t("list.filter_status_label")}</span>
          <select
            className="filter-control"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as StatusFilter)
            }
          >
            <option value="active">{t("list.filter_active")}</option>
            <option value="archived">{t("list.filter_archived")}</option>
            <option value="all">{t("list.filter_all")}</option>
          </select>
        </div>
      </div>

      {!loading && visibleRows.length === 0 && !error && (
        <EmptyState
          icon={CalendarClock}
          title={
            hasFilters ? t("list.empty_filtered_title") : t("list.empty_title")
          }
          description={
            hasFilters ? t("list.empty_filtered_desc") : t("list.empty_desc")
          }
          action={
            hasFilters ? undefined : (
              <Link className="btn btn-primary btn-sm" to="/planned-work/new">
                {t("list.create_button")}
              </Link>
            )
          }
          testId="planned-work-empty"
        />
      )}

      {visibleRows.length > 0 && (
        <div className="responsive-table-wrap">
          <div className="card" style={{ overflow: "hidden" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("list.col_title")}</th>
                  <th>{t("list.col_building")}</th>
                  <th>{t("list.col_customer")}</th>
                  <th>{t("list.col_frequency")}</th>
                  <th>{t("list.col_window")}</th>
                  <th>{t("list.col_pricing")}</th>
                  <th>{t("list.col_status")}</th>
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
                    </td>
                    <td>{job.building_name}</td>
                    <td>{job.customer_name}</td>
                    <td>{t(`frequency.${job.frequency}`)}</td>
                    <td>{windowSummary(job)}</td>
                    <td>{pricingSummary(job)}</td>
                    <td>
                      <StatusBadge
                        variant="cell"
                        status={{
                          kind: "generic",
                          tone: job.is_active ? "approved" : "closed",
                          label: job.is_active
                            ? t("list.row_active")
                            : t("list.row_archived"),
                        }}
                      />
                    </td>
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
                        label: job.is_active
                          ? t("list.row_active")
                          : t("list.row_archived"),
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
                      <dd>{t(`frequency.${job.frequency}`)}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.col_pricing")}</dt>
                      <dd>{pricingSummary(job)}</dd>
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
