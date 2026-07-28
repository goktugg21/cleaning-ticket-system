// Sprint 26C — Extra Work list page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n namespace.
// Sprint 28 Batch 15.3 — rebuilt with KPI strip, filter bar, StatusBadge,
//   formatMoney/formatDate, ClickableRow, mobile card list, EmptyState.
//   Functional contract is unchanged; only the presentation layer moves.
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  CheckCircle2,
  Clock,
  Inbox,
  PlusCircle,
  Search,
  Sparkles,
  Wallet,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { listCustomerBuildings, listCustomers } from "../api/admin";
import { listLabels } from "../api/customerLabels";
import { listAllExtraWork } from "../api/extraWork";
import type {
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerLabel,
  ExtraWorkCategory,
  ExtraWorkRequestIntent,
  ExtraWorkRequestList,
  ExtraWorkStatus,
} from "../api/types";
import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { isProviderManagementRole } from "../auth/permissions";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { RouteBadge } from "../components/RouteBadge";
import { StatusBadge } from "../components/StatusBadge";
import { rowAmounts } from "../lib/billing";
import { formatDate, formatMoney } from "../lib/intl";

const CATEGORY_I18N_KEY: Record<ExtraWorkCategory, string> = {
  DEEP_CLEANING: "category.deep_cleaning",
  WINDOW_CLEANING: "category.window_cleaning",
  FLOOR_MAINTENANCE: "category.floor_maintenance",
  SANITARY_SERVICE: "category.sanitary_service",
  WASTE_REMOVAL: "category.waste_removal",
  FURNITURE_MOVING: "category.furniture_moving",
  EVENT_CLEANING: "category.event_cleaning",
  EMERGENCY_CLEANING: "category.emergency_cleaning",
  OTHER: "category.other",
};

const STATUS_I18N_KEY: Record<ExtraWorkStatus, string> = {
  REQUESTED: "status.requested",
  UNDER_REVIEW: "status.under_review",
  PRICING_PROPOSED: "status.pricing_proposed",
  CUSTOMER_APPROVED: "status.customer_approved",
  // Sprint 29 Batch 29.8 — operational segment.
  IN_PROGRESS: "status.in_progress",
  COMPLETED: "status.completed",
  CUSTOMER_REJECTED: "status.customer_rejected",
  CANCELLED: "status.cancelled",
};

const STATUS_FILTER_OPTIONS: ReadonlyArray<ExtraWorkStatus> = [
  "REQUESTED",
  "UNDER_REVIEW",
  "PRICING_PROPOSED",
  "CUSTOMER_APPROVED",
  // Sprint 29 Batch 29.8 — surface the operational segment in the
  // list filter so operators can narrow to in-progress / completed
  // execution rows.
  "IN_PROGRESS",
  "COMPLETED",
  "CUSTOMER_REJECTED",
  "CANCELLED",
];

type StatusFilter = ExtraWorkStatus | "ALL";
type CategoryFilter = ExtraWorkCategory | "ALL";

interface ExtraWorkKpis {
  open: number; // REQUESTED + UNDER_REVIEW
  awaiting: number; // PRICING_PROPOSED
  approved: number; // CUSTOMER_APPROVED
  totalValue: string; // decimal-string sum of earned amounts (excludes CANCELLED)
}

function KpiCard({
  icon: Icon,
  label,
  value,
  meta,
  testId,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  meta: string;
  testId: string;
}) {
  return (
    <div className="ew-kpi-card" data-testid={testId}>
      <div className="ew-kpi-card-icon" aria-hidden="true">
        <Icon size={18} strokeWidth={1.9} />
      </div>
      <div className="ew-kpi-card-body">
        <div className="ew-kpi-card-label">{label}</div>
        <div className="ew-kpi-card-value">{value}</div>
        <div className="ew-kpi-card-meta">{meta}</div>
      </div>
    </div>
  );
}

export function ExtraWorkListPage() {
  const { t } = useTranslation(["extra_work", "common"]);
  const { me } = useAuth();
  // M6.3 — additive "my work" deep-link reads. With both params absent
  // these resolve to undefined below, so the fetch is unchanged.
  const [searchParams] = useSearchParams();
  // Provider-only: the billing-month picker, invoice-status filter, and the
  // invoiced column. The backend redacts the billing fields for CUSTOMER_USER
  // anyway; this also hides the controls from them.
  const isProvider = isProviderManagementRole(me?.role);
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filter state (client-side; the backend list endpoint IS paginated, but
  // Sprint 120 switched this page to `listAllExtraWork`, which pages
  // through every `next` until exhausted (capped, see api/extraWork.ts) —
  // so `rows` below is the FULL matching set regardless of how many pages
  // that takes, and filtering happens over the complete set, not one page.
  const [searchInput, setSearchInput] = useState("");
  // RF-18 (#107) — dashboard widgets deep-link with ?status=<EW status>;
  // read once at mount (validated), the dropdown owns the state after.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const raw = new URLSearchParams(window.location.search).get("status");
    return raw && (STATUS_FILTER_OPTIONS as readonly string[]).includes(raw)
      ? (raw as StatusFilter)
      : "ALL";
  });
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("ALL");

  // Server-side filters (M4): these drive the 2d list endpoint
  // (?billing_period / ?invoice_status). Search / status / category stay
  // client-side. "" = no billing-month filter.
  const [billingMonth, setBillingMonth] = useState("");
  const [invoiceStatus, setInvoiceStatus] = useState<
    "ALL" | "completed" | "invoiced"
  >("ALL");

  // Sprint 128 — provider label-cascade filters (Customer -> Building ->
  // Department -> Work Type), all four server-side (they compose in the
  // backend ExtraWorkRequestFilter). Building / Department / Work Type are
  // per-customer, so they are disabled until a customer is chosen and cleared
  // when it changes. Provider-only: a CUSTOMER_USER is already scoped to one
  // customer, so a customer picker is meaningless for them.
  const [customerFilter, setCustomerFilter] = useState("");
  const [buildingFilter, setBuildingFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [workTypeFilter, setWorkTypeFilter] = useState("");
  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  // The chosen customer's buildings + label lists, tagged with the customer
  // id so a stale set from the previously chosen customer is never offered.
  const [customerScoped, setCustomerScoped] = useState<{
    customerId: number;
    buildings: CustomerBuildingMembership[];
    departments: CustomerLabel[];
    workTypes: CustomerLabel[];
  } | null>(null);

  // #108 Part F — the mark/clear-invoiced run moved to the Facturen
  // page (owner decision); this list keeps the billing-month +
  // invoice-status FILTERS and a pointer link to /invoices.

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const allRows = await listAllExtraWork({
          billing_period: billingMonth || undefined,
          invoice_status: invoiceStatus === "ALL" ? undefined : invoiceStatus,
          created_by:
            searchParams.get("mine") === "1" && me?.id ? me.id : undefined,
          request_intent:
            (searchParams.get("request_intent") as
              | ExtraWorkRequestIntent
              | null) ?? undefined,
          // Sprint 128 — the label cascade (all server-side). A foreign /
          // stale child filter simply narrows to zero rows (scope-safe).
          customer: customerFilter ? Number(customerFilter) : undefined,
          building: buildingFilter ? Number(buildingFilter) : undefined,
          department: departmentFilter ? Number(departmentFilter) : undefined,
          work_type: workTypeFilter ? Number(workTypeFilter) : undefined,
        });
        if (!cancelled) setRows(allRows);
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
  }, [
    billingMonth,
    invoiceStatus,
    searchParams,
    me?.id,
    customerFilter,
    buildingFilter,
    departmentFilter,
    workTypeFilter,
  ]);

  // Sprint 128 — load the customer list once (provider only; a CUSTOMER_USER
  // has no customer picker).
  useEffect(() => {
    if (!isProvider) return;
    let cancelled = false;
    listCustomers({ page_size: 200 })
      .then((res) => {
        if (!cancelled) setCustomers(res.results);
      })
      .catch(() => {
        // A load failure just leaves the customer picker empty.
      });
    return () => {
      cancelled = true;
    };
  }, [isProvider]);

  // Sprint 128 — LOAD-ONLY effect (no synchronous setState — CLAUDE.md §3):
  // when the customer filter changes, load the chosen customer's buildings +
  // active label lists. The three dependent filters are CLEARED in the
  // customer <select> onChange (an event handler, not here), so a stale child
  // id never reaches the fetch; `customerScoped` is guarded by customer id
  // below so a stale option set is never shown either.
  useEffect(() => {
    const customerId = customerFilter ? Number(customerFilter) : null;
    if (!customerId) return;
    let cancelled = false;
    Promise.all([
      listCustomerBuildings(customerId),
      listLabels(customerId, "department", { is_active: true }),
      listLabels(customerId, "work_type", { is_active: true }),
    ])
      .then(([buildingsRes, departments, workTypes]) => {
        if (!cancelled) {
          setCustomerScoped({
            customerId,
            buildings: buildingsRes.results,
            departments,
            workTypes,
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCustomerScoped({
            customerId,
            buildings: [],
            departments: [],
            workTypes: [],
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [customerFilter]);

  // KPI strip — computed from the full loaded set (not the filtered
  // view) so the operator always sees the same headline numbers
  // regardless of which filter is active. `rows` is now the COMPLETE
  // matching set (Sprint 120 — listAllExtraWork exhausts every page), so
  // these totals no longer silently undercount past 100 rows. A backend
  // aggregation endpoint remains a future option if request volume on
  // very large tenants becomes a real cost; not needed for correctness.
  const kpis = useMemo<ExtraWorkKpis>(() => {
    let open = 0;
    let awaiting = 0;
    let approved = 0;
    let totalNum = 0;
    for (const r of rows) {
      if (r.status === "REQUESTED" || r.status === "UNDER_REVIEW") open += 1;
      else if (r.status === "PRICING_PROPOSED") awaiting += 1;
      else if (r.status === "CUSTOMER_APPROVED") approved += 1;
      // Earned = final actual-hours amount when present, else the quoted
      // estimate (rowAmounts — the shared billing rule the /invoices widget
      // uses), so this KPI agrees with the per-row Total column below.
      if (r.status !== "CANCELLED") {
        totalNum += rowAmounts(r).total;
      }
    }
    return {
      open,
      awaiting,
      approved,
      totalValue: totalNum.toFixed(2),
    };
  }, [rows]);

  const visibleRows = useMemo(() => {
    const needle = searchInput.trim().toLowerCase();
    return rows.filter((r) => {
      if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
      if (categoryFilter !== "ALL" && r.category !== categoryFilter) return false;
      if (needle) {
        const hay = `${r.title} ${r.building_name ?? ""} ${
          r.customer_name ?? ""
        }`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [rows, searchInput, statusFilter, categoryFilter]);

  // M4 (3c) — client-side itemized CSV of the in-view rows. Mirrors the
  // proposal-PDF Blob + object-URL + synthetic <a download> pattern. UTF-8
  // BOM so Excel reads Dutch characters, CRLF line endings, quoted fields.
  function exportCsv() {
    const esc = (v: string | null | undefined) =>
      `"${String(v ?? "").replace(/"/g, '""')}"`;
    const headers = [
      t("list.column_title"),
      t("list.column_customer"),
      t("list.column_building"),
      t("list.column_status"),
      t("list.export_col_subtotal"),
      t("list.export_col_vat"),
      t("list.column_total"),
      t("list.column_billing"),
      t("list.export_col_invoice_date"),
      t("list.column_requested"),
    ];
    const lines = [headers.map(esc).join(",")];
    for (const row of visibleRows) {
      // Earned (final-with-quoted-fallback) so the export matches the on-screen
      // Total; the three columns stay coherent (subtotal + vat == total).
      const amounts = rowAmounts(row);
      lines.push(
        [
          row.title,
          row.customer_name,
          row.building_name,
          t(STATUS_I18N_KEY[row.status] ?? row.status),
          amounts.subtotal.toFixed(2),
          amounts.vat.toFixed(2),
          amounts.total.toFixed(2),
          row.is_invoiced
            ? t("list.billing_invoiced")
            : t("list.billing_to_invoice"),
          row.invoice_date ? formatDate(row.invoice_date) : "",
          formatDate(row.requested_at),
        ]
          .map(esc)
          .join(","),
      );
    }
    const csv = "\uFEFF" + lines.join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `extra-work_${billingMonth}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Sprint 128 — the child options to OFFER right now, guarded inline so a set
  // fetched for a previously chosen customer is never shown against the
  // current one (and TS narrows `customerScoped`).
  const scopedBuildings =
    customerScoped && String(customerScoped.customerId) === customerFilter
      ? customerScoped.buildings
      : [];
  const scopedDepartments =
    customerScoped && String(customerScoped.customerId) === customerFilter
      ? customerScoped.departments
      : [];
  const scopedWorkTypes =
    customerScoped && String(customerScoped.customerId) === customerFilter
      ? customerScoped.workTypes
      : [];
  const customerChosen = customerFilter !== "";

  return (
    <div data-testid="extra-work-list-page">
      <PageHeader
        backLink={{ to: "/", label: t("back_to_dashboard") }}
        eyebrow={t("common:ops")}
        title={t("list.page_title")}
        subtitle={t("list.page_subtitle")}
        actions={
          <Link
            className="btn btn-primary btn-sm"
            to="/extra-work/new"
            data-testid="extra-work-list-create-link"
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

      {/* KPI strip */}
      <div className="ew-list-kpi-row" data-testid="extra-work-list-kpi-row">
        <KpiCard
          icon={Inbox}
          label={t("kpi.open_label")}
          value={kpis.open}
          meta={t("kpi.open_meta")}
          testId="extra-work-list-kpi-open"
        />
        <KpiCard
          icon={Clock}
          label={t("kpi.awaiting_label")}
          value={kpis.awaiting}
          meta={t("kpi.awaiting_meta")}
          testId="extra-work-list-kpi-awaiting"
        />
        <KpiCard
          icon={CheckCircle2}
          label={t("kpi.approved_label")}
          value={kpis.approved}
          meta={t("kpi.approved_meta")}
          testId="extra-work-list-kpi-approved"
        />
        <KpiCard
          icon={Wallet}
          label={t("kpi.value_label")}
          value={formatMoney(kpis.totalValue)}
          meta={t("kpi.value_meta")}
          testId="extra-work-list-kpi-value"
        />
      </div>

      {/* Filter bar */}
      <div
        className="card ew-list-filters"
        data-testid="extra-work-list-filters"
      >
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
          <span className="filter-label">{t("list.column_status")}</span>
          <select
            className="filter-control"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as StatusFilter)
            }
          >
            <option value="ALL">{t("list.filter_all_statuses")}</option>
            {STATUS_FILTER_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {t(STATUS_I18N_KEY[s])}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("list.column_category")}</span>
          <select
            className="filter-control"
            value={categoryFilter}
            onChange={(event) =>
              setCategoryFilter(event.target.value as CategoryFilter)
            }
          >
            <option value="ALL">{t("list.filter_all_categories")}</option>
            {(Object.keys(CATEGORY_I18N_KEY) as ExtraWorkCategory[]).map(
              (c) => (
                <option key={c} value={c}>
                  {t(CATEGORY_I18N_KEY[c])}
                </option>
              ),
            )}
          </select>
        </div>
        {isProvider && (
          <>
            {/* Sprint 128 — the label cascade: Customer -> Building ->
                Department -> Work Type. The last three are per-customer, so
                they are disabled (with a hint) until a customer is chosen and
                clear when it changes. */}
            <div className="filter-field">
              <span className="filter-label">{t("list.filter_customer")}</span>
              <select
                className="filter-control"
                value={customerFilter}
                onChange={(event) => {
                  // Clear the dependent (per-customer) filters here in the
                  // event handler — never in the load effect (CLAUDE.md §3).
                  setCustomerFilter(event.target.value);
                  setBuildingFilter("");
                  setDepartmentFilter("");
                  setWorkTypeFilter("");
                }}
                data-testid="extra-work-list-filter-customer"
              >
                <option value="">{t("list.filter_all_customers")}</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">{t("list.filter_building")}</span>
              <select
                className="filter-control"
                value={buildingFilter}
                onChange={(event) => setBuildingFilter(event.target.value)}
                disabled={!customerChosen}
                data-testid="extra-work-list-filter-building"
              >
                <option value="">{t("list.filter_all_buildings")}</option>
                {scopedBuildings.map((b) => (
                  <option key={b.building_id} value={b.building_id}>
                    {b.building_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_department")}
              </span>
              <select
                className="filter-control"
                value={departmentFilter}
                onChange={(event) => setDepartmentFilter(event.target.value)}
                disabled={!customerChosen}
                data-testid="extra-work-list-filter-department"
              >
                <option value="">{t("list.filter_all_departments")}</option>
                {scopedDepartments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_work_type")}
              </span>
              <select
                className="filter-control"
                value={workTypeFilter}
                onChange={(event) => setWorkTypeFilter(event.target.value)}
                disabled={!customerChosen}
                data-testid="extra-work-list-filter-work-type"
              >
                <option value="">{t("list.filter_all_work_types")}</option>
                {scopedWorkTypes.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </div>
            {!customerChosen && (
              <div className="filter-field">
                <span className="muted small">
                  {t("list.filter_pick_customer_hint")}
                </span>
              </div>
            )}
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_billing_month")}
              </span>
              <span
                style={{
                  display: "inline-flex",
                  gap: 6,
                  alignItems: "center",
                }}
              >
                <input
                  className="filter-control"
                  type="month"
                  value={billingMonth}
                  onChange={(event) => setBillingMonth(event.target.value)}
                  data-testid="extra-work-list-billing-month"
                />
                {billingMonth && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setBillingMonth("")}
                  >
                    {t("list.filter_billing_month_clear")}
                  </button>
                )}
              </span>
            </div>
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_invoice_status")}
              </span>
              <select
                className="filter-control"
                value={invoiceStatus}
                onChange={(event) =>
                  setInvoiceStatus(
                    event.target.value as "ALL" | "completed" | "invoiced",
                  )
                }
                data-testid="extra-work-list-invoice-status"
              >
                <option value="ALL">{t("list.invoice_status_all")}</option>
                <option value="completed">
                  {t("list.invoice_status_completed")}
                </option>
                <option value="invoiced">
                  {t("list.invoice_status_invoiced")}
                </option>
              </select>
            </div>
          </>
        )}
      </div>

      {/* M4 toolbar, reduced by #108 Part F — the mark/clear-invoiced
          run lives on the Facturen page now; a muted pointer replaces
          the buttons. The month label + CSV export stay. */}
      {isProvider && billingMonth && (
        <div
          className="card"
          data-testid="extra-work-list-invoice-run"
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
            marginBottom: 16,
          }}
        >
          <span style={{ fontWeight: 600 }}>
            {t("list.invoice_run_label", { month: billingMonth })}
          </span>
          <span className="muted small">
            {t("list.invoice_run_pointer_prefix")}{" "}
            <Link to="/invoices" className="link">
              {t("list.invoice_run_pointer_link")}
            </Link>
          </span>
          <div style={{ marginLeft: "auto" }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={visibleRows.length === 0}
              onClick={exportCsv}
              data-testid="extra-work-list-export-csv"
            >
              {t("list.export_csv")}
            </button>
          </div>
        </div>
      )}

      {/* Empty / list */}
      {!loading && visibleRows.length === 0 && !error && (
        <EmptyState
          icon={Sparkles}
          title={
            billingMonth
              ? t("list.empty_billing_month")
              : rows.length === 0
                ? t("list.empty_state")
                : t("list.empty_filtered_title")
          }
          description={
            billingMonth || rows.length === 0
              ? undefined
              : t("list.empty_filtered_desc")
          }
          testId="extra-work-list-empty"
        />
      )}

      {visibleRows.length > 0 && (
        <div className="responsive-table-wrap">
          <div className="card" style={{ overflow: "hidden" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("list.column_title")}</th>
                  <th>{t("list.column_status")}</th>
                  <th>{t("list.column_route")}</th>
                  <th>{t("list.column_category")}</th>
                  <th>{t("list.column_building")}</th>
                  <th>{t("list.column_customer")}</th>
                  <th style={{ textAlign: "right" }}>
                    {t("list.column_total")}
                  </th>
                  {isProvider && <th>{t("list.column_billing")}</th>}
                  <th>{t("list.column_requested")}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <ClickableRow
                    key={row.id}
                    to={`/extra-work/${row.id}`}
                    testId="extra-work-row"
                  >
                    <td className="td-subject">
                      <Link to={`/extra-work/${row.id}`}>{row.title}</Link>
                    </td>
                    <td>
                      <StatusBadge
                        status={{ kind: "extra-work", value: row.status }}
                      />
                    </td>
                    <td>
                      <RouteBadge value={row.routing_decision} />
                    </td>
                    <td>
                      {t(CATEGORY_I18N_KEY[row.category] ?? row.category)}
                    </td>
                    <td>{row.building_name}</td>
                    <td>{row.customer_name}</td>
                    <td style={{ textAlign: "right" }}>
                      {formatMoney(rowAmounts(row).total)}
                    </td>
                    {isProvider && (
                      <td>
                        {row.is_invoiced ? (
                          <span className="badge badge-approved">
                            {t("list.billing_invoiced")}
                          </span>
                        ) : (
                          <span className="badge badge-normal">
                            {t("list.billing_to_invoice")}
                          </span>
                        )}
                        {row.invoice_date && (
                          <div
                            style={{
                              fontSize: "0.8em",
                              marginTop: 2,
                              color: "var(--text-muted)",
                            }}
                          >
                            {formatDate(row.invoice_date)}
                          </div>
                        )}
                      </td>
                    )}
                    <td>{formatDate(row.requested_at)}</td>
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
            {visibleRows.map((row) => (
              <li key={row.id} className="admin-card">
                <Link
                  to={`/extra-work/${row.id}`}
                  className="admin-card-link"
                  data-testid="extra-work-card"
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{row.title}</span>
                    <span
                      style={{
                        display: "inline-flex",
                        gap: 6,
                        alignItems: "center",
                        flexWrap: "wrap",
                      }}
                    >
                      <StatusBadge
                        status={{ kind: "extra-work", value: row.status }}
                      />
                      <RouteBadge value={row.routing_decision} />
                    </span>
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_route")}</dt>
                      <dd>
                        {row.routing_decision === "INSTANT"
                          ? t("route_badge.instant", { ns: "common" })
                          : t("route_badge.proposal", { ns: "common" })}
                      </dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_category")}</dt>
                      <dd>
                        {t(CATEGORY_I18N_KEY[row.category] ?? row.category)}
                      </dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_building")}</dt>
                      <dd>{row.building_name}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_customer")}</dt>
                      <dd>{row.customer_name}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_total")}</dt>
                      <dd>{formatMoney(rowAmounts(row).total)}</dd>
                    </div>
                    {isProvider && (
                      <div className="admin-card-meta-row">
                        <dt>{t("list.column_billing")}</dt>
                        <dd>
                          {row.is_invoiced ? (
                            <span className="badge badge-approved">
                              {t("list.billing_invoiced")}
                            </span>
                          ) : (
                            <span className="badge badge-normal">
                              {t("list.billing_to_invoice")}
                            </span>
                          )}
                          {row.invoice_date
                            ? ` · ${formatDate(row.invoice_date)}`
                            : ""}
                        </dd>
                      </div>
                    )}
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_requested")}</dt>
                      <dd>{formatDate(row.requested_at)}</dd>
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


