import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listCustomers } from "../../api/admin";
import type { CustomerAdmin } from "../../api/types";

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
    // do NOT pass company/building/active filters here — the page is
    // a simple read-only landing.
    listCustomers({ page_size: 100, is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCustomers(response.results);
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
    <div className="admin-page" data-testid="bm-customers-page">
      <header className="admin-page-head">
        <div>
          <div className="admin-page-eyebrow">
            {t("bm_customers.eyebrow")}
          </div>
          <h1 className="admin-page-title">{t("bm_customers.title")}</h1>
          <p className="admin-page-sub" data-testid="bm-customers-readonly-hint">
            {t("bm_customers.readonly_hint")}
          </p>
        </div>
        <div className="admin-page-actions">
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
        </div>
      </header>

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
          <table className="admin-table">
            <thead>
              <tr>
                <th>{t("customers.col_name")}</th>
                <th>{t("customers.col_contact_email")}</th>
                <th>{t("customers.col_phone")}</th>
              </tr>
            </thead>
            <tbody data-testid="bm-customers-tbody">
              {sortedCustomers.map((customer) => (
                <tr key={customer.id} data-testid={`bm-customer-row-${customer.id}`}>
                  <td>
                    <Link
                      to={`/admin/customers/${customer.id}`}
                      data-testid={`bm-customer-link-${customer.id}`}
                    >
                      {customer.name}
                    </Link>
                  </td>
                  <td>{customer.contact_email || "—"}</td>
                  <td>{customer.phone || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
