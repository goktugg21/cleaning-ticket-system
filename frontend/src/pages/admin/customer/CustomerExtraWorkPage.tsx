import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { FileText, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import { listAllExtraWork } from "../../../api/extraWork";
import type {
  CustomerAdmin,
  ExtraWorkCategory,
  ExtraWorkRequestList,
} from "../../../api/types";
import { ClickableRow } from "../../../components/ClickableRow";
import { EmptyState } from "../../../components/EmptyState";
import { RouteBadge } from "../../../components/RouteBadge";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDate, formatMoney } from "../../../lib/intl";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 31 — Customer Extra Work tab.
 *
 * Mirrors the existing customer-scoped sub-page family (Overview /
 * Buildings / Users / Contacts / Settings) and consumes the
 * backend-supplied `GET /api/extra-work/?customer=<id>` filter. Scope
 * is enforced server-side by `extra_work.scoping.scope_extra_work_for`
 * BEFORE the filterset narrows, so the response respects the caller's
 * scope regardless of the query-param value. View-first per spec §3 —
 * the rows are a list, not an editor; each row's title links to the
 * existing `/extra-work/<id>` detail page where the read/edit surface
 * already lives.
 */
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

export function CustomerExtraWorkPage({
  quoteOnly = false,
}: {
  quoteOnly?: boolean;
}) {
  const { id } = useParams();
  const { t } = useTranslation(["common", "extra_work"]);

  // M6.2 — quote-requests variant of this page. The defaults keep the
  // extra-work tab byte-identical (same i18n + testid segments, same
  // fetch); quoteOnly narrows the fetch to request_intent=REQUEST_QUOTE
  // and swaps only the variant-specific copy + testids.
  const v = quoteOnly ? "quote_requests" : "extra_work"; // i18n segment
  const tv = quoteOnly ? "quote-requests" : "extra-work"; // testid segment

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    // Two parallel fetches: the customer (for the header name +
    // active-status pill) and the scoped Extra Work list. The list
    // is filtered server-side via `?customer=<id>`; the
    // scope-respecting `get_queryset` runs before the filter so a
    // caller without access to this customer gets zero rows rather
    // than a 403 — same defence-in-depth shape the ticket list uses.
    Promise.all([
      getCustomer(numericId),
      listAllExtraWork({
        customer: numericId,
        ...(quoteOnly ? { request_intent: "REQUEST_QUOTE" } : {}),
      }),
    ])
      .then(([customerData, ewRows]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setRows(ewRows);
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
  }, [numericId, quoteOnly, t]);

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

  return (
    <div data-testid={`customer-${tv}-page`}>
      <CustomerSubPageHeader
        customerName={customerName}
        isActive={isActive}
      />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : customer ? (
        <>
          <p
            className="section-explainer"
            data-testid={`customer-${tv}-explainer`}
          >
            {t(`customer_view.${v}.explainer`, {
              customer: customerName,
            })}
          </p>

          {rows.length === 0 ? (
            <EmptyState
              icon={quoteOnly ? FileText : Sparkles}
              title={t(`customer_view.${v}.empty_title`)}
              description={t(`customer_view.${v}.empty_desc`)}
              testId={`customer-${tv}-empty`}
            />
          ) : (
            <section
              className="card"
              data-testid={`customer-${tv}-section`}
              style={{ padding: "20px 22px", overflow: "hidden" }}
            >
              <div className="section-head" style={{ marginBottom: 12 }}>
                <div>
                  <div className="section-head-title">
                    {t(`customer_view.${v}.list_title`)}
                  </div>
                  <div className="section-head-sub">
                    {t(`customer_view.${v}.list_subtitle`, {
                      count: rows.length,
                    })}
                  </div>
                </div>
              </div>

              <div className="table-wrap">
                <table
                  className="data-table"
                  data-testid={`customer-${tv}-table`}
                >
                  <thead>
                    <tr>
                      <th>{t("extra_work:list.column_title")}</th>
                      <th>{t("extra_work:list.column_status")}</th>
                      <th>{t("extra_work:list.column_route")}</th>
                      <th>{t("extra_work:list.column_category")}</th>
                      <th>{t("extra_work:list.column_building")}</th>
                      <th style={{ textAlign: "right" }}>
                        {t("extra_work:list.column_total")}
                      </th>
                      <th>{t("extra_work:list.column_requested")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <ClickableRow
                        key={row.id}
                        to={`/extra-work/${row.id}`}
                        testId={`customer-${tv}-row`}
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
                          {t(
                            `extra_work:${CATEGORY_I18N_KEY[row.category] ?? row.category}`,
                          )}
                        </td>
                        <td>{row.building_name}</td>
                        <td style={{ textAlign: "right" }}>
                          {formatMoney(row.total_amount)}
                        </td>
                        <td>{formatDate(row.requested_at)}</td>
                      </ClickableRow>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
