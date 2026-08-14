import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listAllCustomers } from "../../api/admin";
import type { CustomerAdmin } from "../../api/types";
import { PageHeader } from "../../components/PageHeader";

/**
 * Sprint 28 Batch 12 — Building Manager read-only customer list.
 *
 * Renders the customer list scoped to the BM's assigned buildings
 * (the backend's `scope_customers_for` helper already returns this
 * shape for BM via the `customer_ids_for` building-link join).
 *
 * View-first per spec §3 + master plan §6 Batch 12. No Add / Edit /
 * Delete affordances are rendered. Rows are clickable to a
 * read-only detail page. The page is reachable only by
 * BUILDING_MANAGER through `CustomerReadRoute`; admins reach
 * `CustomersAdminPage` (the edit-capable variant) at the same URL.
 */
export function BuildingManagerCustomersPage() {
  const { t } = useTranslation("common");

  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Sprint 28 Batch 12 — existing baseline pattern in the codebase
    // (CustomerPricingPage / CustomerContactsPage / etc.). The
    // data-loader effect synchronously flips loading=true so the row
    // never flashes empty before the async fetch resolves.
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    // BM scope is enforced server-side; the BM only ever sees
    // customers linked to their assigned buildings. We deliberately
    // do NOT pass company/building filters here — the page is a simple
    // read-only landing with no pagination UI, so it must have EVERY
    // matching row — Sprint 136: this was still capped at page_size:100
    // with no follow-up, missed by Sprint 135's page_size:200-only grep.
    listAllCustomers({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCustomers(response);
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
  }, [reloadTick]);

  const hasRows = customers.length > 0;

  const sortedCustomers = useMemo(
    () => [...customers].sort((a, b) => a.name.localeCompare(b.name)),
    [customers],
  );

  return (
    <div data-testid="bm-customers-page">
      {/* Sprint 180 §1 — the shared header, which is what `PageHeader`'s
          own docstring asks every page-level route to mount. This page
          rolled its own out of `admin-page-head` / `admin-page-eyebrow` /
          `admin-page-title` / `admin-page-sub` / `admin-page-actions`,
          none of which is defined anywhere: the title rendered at the
          browser's default `h1` (~2em bold) in the body face instead of
          the house 28/800, and the eyebrow, hint and button row had no
          styling at all. The subtitle keeps its test id. */}
      <PageHeader
        eyebrow={t("bm_customers.eyebrow")}
        title={t("bm_customers.title")}
        subtitle={
          <span data-testid="bm-customers-readonly-hint">
            {t("bm_customers.readonly_hint")}
          </span>
        }
        actions={
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setReloadTick((tick) => tick + 1)}
            disabled={loading}
            data-testid="bm-customers-refresh"
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("refresh")}
          </button>
        }
      />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card">
        {loading && customers.length === 0 ? (
          <p className="muted">{t("loading")}</p>
        ) : !hasRows ? (
          <p className="muted" data-testid="bm-customers-empty">
            {t("bm_customers.empty")}
          </p>
        ) : (
          /* Sprint 180 §1 — `data-table` inside `table-wrap`, the house
             pair. `admin-table` was defined nowhere, so this read-only
             list rendered as a bare browser table — no header treatment,
             no cell padding, no row rule — beside the admin twin of the
             same screen, which is a `data-table`. The wrapper comes with
             it because `.data-table` carries `min-width: 860px` and
             would otherwise overflow the card on a phone, which is the
             width this reader is most likely to be on. */
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("customers.col_name")}</th>
                  <th>{t("customers.col_contact_email")}</th>
                  <th>{t("customers.col_phone")}</th>
                </tr>
              </thead>
              <tbody data-testid="bm-customers-tbody">
                {sortedCustomers.map((customer) => (
                  <tr
                    key={customer.id}
                    data-testid={`bm-customer-row-${customer.id}`}
                  >
                    <td className="td-subject">
                      <Link
                        to={`/admin/customers/${customer.id}`}
                        data-testid={`bm-customer-link-${customer.id}`}
                      >
                        {customer.name}
                      </Link>
                    </td>
                    <td>
                      {customer.contact_email || (
                        <span className="muted-empty">—</span>
                      )}
                    </td>
                    <td>
                      {customer.phone || <span className="muted-empty">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
