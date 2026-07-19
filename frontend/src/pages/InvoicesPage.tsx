// RF-13 (#106) — Invoices v1 ("Facturen"): a provider-side overview of
// the month's billable Extra Work.
//
// Data: ONE call to the existing list endpoint with ?billing_period=
// YYYY-MM (page_size 500) — the same COALESCE(invoice_date, completion
// month) bucketing the invoice run uses. No new backend endpoint; the
// only backend delta this part shipped is the three final_* amounts on
// the list serializer. Totals apply the final-with-quoted-fallback
// rule (mirrors reports/dimensions._amounts_for_state for earned EW).
//
// Grouping: customer -> expandable per-building breakdown; filters for
// customer / building / status (open vs invoiced) applied client-side
// over the month's rows. Rows link to the EW detail.
//
// Actions: mark / clear the month at the EXISTING endpoint granularity
// (company + month — backend iterates every earned, not-yet-invoiced
// EW of the company billing that month). Confirm-guarded with the
// affected company, month and row count spelled out. SA/CA only; BM
// views read-only (mirrors report access).
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BadgeEuro, ChevronDown } from "lucide-react";

import { getApiError } from "../api/client";
import {
  clearExtraWorkInvoiced,
  listExtraWork,
  markExtraWorkInvoiced,
} from "../api/extraWork";
import type { ExtraWorkRequestList } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { isProviderAdmin } from "../auth/permissions";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { useToast } from "../components/ToastProvider";
import { formatDate, formatMoney } from "../lib/intl";

type StatusFilter = "ALL" | "OPEN" | "INVOICED";

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// Final-with-quoted-fallback (the backend revenue rule): an EW that
// bills this month is earned, so prefer the final (actual-hours)
// amounts and fall back to the quoted estimate only when final is NULL.
function rowAmounts(r: ExtraWorkRequestList): {
  subtotal: number;
  vat: number;
  total: number;
} {
  const num = (v: string | null | undefined): number => {
    const n = v != null ? Number.parseFloat(v) : NaN;
    return Number.isFinite(n) ? n : 0;
  };
  if (r.final_total_amount != null) {
    return {
      subtotal: num(r.final_subtotal_amount),
      vat: num(r.final_vat_amount),
      total: num(r.final_total_amount),
    };
  }
  return {
    subtotal: num(r.subtotal_amount),
    vat: num(r.vat_amount),
    total: num(r.total_amount),
  };
}

interface GroupTotals {
  count: number;
  open: number;
  invoiced: number;
  subtotal: number;
  vat: number;
  total: number;
}

function sumRows(rows: ExtraWorkRequestList[]): GroupTotals {
  const totals: GroupTotals = {
    count: rows.length,
    open: 0,
    invoiced: 0,
    subtotal: 0,
    vat: 0,
    total: 0,
  };
  for (const r of rows) {
    if (r.is_invoiced === true) totals.invoiced += 1;
    else totals.open += 1;
    const a = rowAmounts(r);
    totals.subtotal += a.subtotal;
    totals.vat += a.vat;
    totals.total += a.total;
  }
  return totals;
}

export function InvoicesPage() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const { push: pushToast } = useToast();
  const canRunActions = isProviderAdmin(me?.role);

  const [month, setMonth] = useState(currentMonth);
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const [customerFilter, setCustomerFilter] = useState("ALL");
  const [buildingFilter, setBuildingFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [expandedCustomers, setExpandedCustomers] = useState<Set<number>>(
    () => new Set(),
  );

  const [running, setRunning] = useState(false);
  const confirmRef = useRef<ConfirmDialogHandle>(null);
  const [pendingAction, setPendingAction] = useState<"mark" | "clear" | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    listExtraWork({ billing_period: month, page_size: 500 })
      .then((resp) => {
        if (cancelled) return;
        setRows(resp.results);
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
  }, [month, refreshKey]);

  // Filter options derive from the month's rows (no extra API calls).
  const customerOptions = useMemo(() => {
    const map = new Map<number, string>();
    for (const r of rows) map.set(r.customer, r.customer_name);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);
  const buildingOptions = useMemo(() => {
    const map = new Map<number, string>();
    for (const r of rows) map.set(r.building, r.building_name);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);

  const visibleRows = useMemo(() => {
    return rows.filter((r) => {
      if (customerFilter !== "ALL" && String(r.customer) !== customerFilter)
        return false;
      if (buildingFilter !== "ALL" && String(r.building) !== buildingFilter)
        return false;
      if (statusFilter === "OPEN" && r.is_invoiced === true) return false;
      if (statusFilter === "INVOICED" && r.is_invoiced !== true) return false;
      return true;
    });
  }, [rows, customerFilter, buildingFilter, statusFilter]);

  // customer id -> rows, then building id -> rows inside the group.
  const groups = useMemo(() => {
    const byCustomer = new Map<number, ExtraWorkRequestList[]>();
    for (const r of visibleRows) {
      const list = byCustomer.get(r.customer) ?? [];
      list.push(r);
      byCustomer.set(r.customer, list);
    }
    return [...byCustomer.entries()]
      .map(([customerId, customerRows]) => {
        const byBuilding = new Map<number, ExtraWorkRequestList[]>();
        for (const r of customerRows) {
          const list = byBuilding.get(r.building) ?? [];
          list.push(r);
          byBuilding.set(r.building, list);
        }
        return {
          customerId,
          customerName: customerRows[0].customer_name,
          rows: customerRows,
          totals: sumRows(customerRows),
          buildings: [...byBuilding.entries()].map(
            ([buildingId, buildingRows]) => ({
              buildingId,
              buildingName: buildingRows[0].building_name,
              rows: buildingRows,
              totals: sumRows(buildingRows),
            }),
          ),
        };
      })
      .sort((a, b) => a.customerName.localeCompare(b.customerName));
  }, [visibleRows]);

  const monthTotals = useMemo(() => sumRows(visibleRows), [visibleRows]);

  // Single-company rule (mirrors the EW list's invoice-run toolbar):
  // the mark/clear endpoints take ONE company + month.
  const runCompany = useMemo(() => {
    const companies = new Set(rows.map((r) => r.company));
    return companies.size === 1 && rows.length > 0 ? rows[0].company : null;
  }, [rows]);
  const openCount = useMemo(
    () => rows.filter((r) => r.is_invoiced !== true).length,
    [rows],
  );
  const invoicedCount = rows.length - openCount;

  const toggleCustomer = (id: number) =>
    setExpandedCustomers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  function requestAction(action: "mark" | "clear") {
    setPendingAction(action);
    confirmRef.current?.open();
  }

  async function handleConfirmAction() {
    if (pendingAction === null || runCompany === null) return;
    const [year, monthNum] = month.split("-").map(Number);
    setRunning(true);
    setError("");
    try {
      const res =
        pendingAction === "mark"
          ? await markExtraWorkInvoiced({
              company: runCompany,
              year,
              month: monthNum,
            })
          : await clearExtraWorkInvoiced({
              company: runCompany,
              year,
              month: monthNum,
            });
      pushToast({
        variant: "success",
        title:
          pendingAction === "mark"
            ? t("billing.toast_marked", { count: res.invoiced_count ?? 0 })
            : t("billing.toast_cleared", { count: res.cleared_count ?? 0 }),
      });
      confirmRef.current?.close();
      setPendingAction(null);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(getApiError(err));
      confirmRef.current?.close();
      setPendingAction(null);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div data-testid="invoices-page">
      <PageHeader
        eyebrow={t("billing.eyebrow")}
        title={t("billing.title")}
        subtitle={t("billing.subtitle")}
      />

      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div className="invoices-toolbar">
          <label className="field invoices-toolbar-field">
            <span className="field-label">{t("billing.month_label")}</span>
            <input
              className="field-input"
              type="month"
              value={month}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
              data-testid="invoices-month"
            />
          </label>
          <label className="field invoices-toolbar-field">
            <span className="field-label">{t("billing.filter_customer")}</span>
            <select
              className="field-select"
              value={customerFilter}
              onChange={(e) => setCustomerFilter(e.target.value)}
              data-testid="invoices-filter-customer"
            >
              <option value="ALL">{t("billing.filter_all")}</option>
              {customerOptions.map(([id, name]) => (
                <option key={id} value={String(id)}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="field invoices-toolbar-field">
            <span className="field-label">{t("billing.filter_building")}</span>
            <select
              className="field-select"
              value={buildingFilter}
              onChange={(e) => setBuildingFilter(e.target.value)}
              data-testid="invoices-filter-building"
            >
              <option value="ALL">{t("billing.filter_all")}</option>
              {buildingOptions.map(([id, name]) => (
                <option key={id} value={String(id)}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="field invoices-toolbar-field">
            <span className="field-label">{t("billing.filter_status")}</span>
            <select
              className="field-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              data-testid="invoices-filter-status"
            >
              <option value="ALL">{t("billing.filter_all")}</option>
              <option value="OPEN">{t("billing.status_open")}</option>
              <option value="INVOICED">{t("billing.status_invoiced")}</option>
            </select>
          </label>
        </div>

        <div className="invoices-month-summary" data-testid="invoices-summary">
          <span>
            {t("billing.summary_line", {
              count: monthTotals.count,
              open: monthTotals.open,
              invoiced: monthTotals.invoiced,
            })}
          </span>
          <span className="invoices-month-summary-money">
            {t("billing.summary_totals", {
              subtotal: formatMoney(monthTotals.subtotal),
              vat: formatMoney(monthTotals.vat),
              total: formatMoney(monthTotals.total),
            })}
          </span>
        </div>

        {canRunActions && (
          <div className="invoices-actions" data-testid="invoices-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={running || runCompany === null || openCount === 0}
              onClick={() => requestAction("mark")}
              data-testid="invoices-mark-button"
            >
              {t("billing.action_mark")}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={running || runCompany === null || invoicedCount === 0}
              onClick={() => requestAction("clear")}
              data-testid="invoices-clear-button"
            >
              {t("billing.action_clear")}
            </button>
            {runCompany === null && rows.length > 0 && (
              <span className="muted small">
                {t("billing.multi_company_hint")}
              </span>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={BadgeEuro}
          title={t("billing.empty_title")}
          description={t("billing.empty_desc")}
        />
      ) : (
        groups.map((group) => {
          const expanded = expandedCustomers.has(group.customerId);
          return (
            <section
              key={group.customerId}
              className="card invoices-group"
              data-testid="invoices-group"
              data-customer-id={group.customerId}
              data-open={expanded ? "true" : "false"}
            >
              <button
                type="button"
                className="invoices-group-head"
                onClick={() => toggleCustomer(group.customerId)}
                aria-expanded={expanded}
                data-testid="invoices-group-toggle"
              >
                <ChevronDown
                  size={15}
                  strokeWidth={2.2}
                  className={
                    expanded
                      ? "invoices-chevron invoices-chevron-open"
                      : "invoices-chevron"
                  }
                  aria-hidden="true"
                />
                <span className="invoices-group-name">
                  {group.customerName}
                </span>
                <span className="muted small">
                  {t("billing.group_meta", {
                    count: group.totals.count,
                    open: group.totals.open,
                  })}
                </span>
                <span className="invoices-group-total">
                  {formatMoney(group.totals.total)}
                </span>
              </button>

              {expanded && (
                <div className="invoices-group-body">
                  {group.buildings.map((building) => (
                    <div
                      key={building.buildingId}
                      className="invoices-building"
                      data-testid="invoices-building"
                    >
                      <div className="invoices-building-head">
                        <span className="invoices-building-name">
                          {building.buildingName}
                        </span>
                        <span className="muted small">
                          {t("billing.group_meta", {
                            count: building.totals.count,
                            open: building.totals.open,
                          })}
                        </span>
                        <span className="invoices-group-total">
                          {formatMoney(building.totals.total)}
                        </span>
                      </div>
                      <table className="data-table invoices-table">
                        <thead>
                          <tr>
                            <th>{t("billing.col_title")}</th>
                            <th>{t("billing.col_completed")}</th>
                            <th>{t("billing.col_status")}</th>
                            <th className="invoices-num">
                              {t("billing.col_subtotal")}
                            </th>
                            <th className="invoices-num">
                              {t("billing.col_vat")}
                            </th>
                            <th className="invoices-num">
                              {t("billing.col_total")}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {building.rows.map((r) => {
                            const a = rowAmounts(r);
                            return (
                              <tr key={r.id} data-testid="invoices-row">
                                <td>
                                  <Link
                                    to={`/extra-work/${r.id}`}
                                    className="link"
                                  >
                                    {r.title}
                                  </Link>
                                </td>
                                <td className="muted small">
                                  {r.invoice_date
                                    ? formatDate(r.invoice_date)
                                    : r.customer_decided_at
                                      ? formatDate(r.customer_decided_at)
                                      : "—"}
                                </td>
                                <td>
                                  <span
                                    className={
                                      r.is_invoiced === true
                                        ? "invoices-badge invoices-badge-invoiced"
                                        : "invoices-badge invoices-badge-open"
                                    }
                                  >
                                    {r.is_invoiced === true
                                      ? t("billing.status_invoiced")
                                      : t("billing.status_open")}
                                  </span>
                                </td>
                                <td className="invoices-num">
                                  {formatMoney(a.subtotal)}
                                </td>
                                <td className="invoices-num">
                                  {formatMoney(a.vat)}
                                </td>
                                <td className="invoices-num">
                                  <strong>{formatMoney(a.total)}</strong>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}
            </section>
          );
        })
      )}

      <ConfirmDialog
        ref={confirmRef}
        title={
          pendingAction === "clear"
            ? t("billing.confirm_clear_title", { month })
            : t("billing.confirm_mark_title", { month })
        }
        body={
          pendingAction === "clear"
            ? t("billing.confirm_clear_body", {
                count: invoicedCount,
                month,
              })
            : t("billing.confirm_mark_body", {
                count: openCount,
                month,
              })
        }
        confirmLabel={
          pendingAction === "clear"
            ? t("billing.action_clear")
            : t("billing.action_mark")
        }
        onConfirm={handleConfirmAction}
        onCancel={() => setPendingAction(null)}
        busy={running}
        destructive
      />
    </div>
  );
}
