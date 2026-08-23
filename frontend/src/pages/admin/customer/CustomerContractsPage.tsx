import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getCustomer } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import { listContracts } from "../../../api/contracts";
import type { Contract } from "../../../api/contracts.types";
import { Plus } from "lucide-react";

import { useAuth } from "../../../auth/AuthContext";
import { canManageContracts } from "../../../auth/permissions";
import { ContractFormDialog } from "../contracts/ContractFormDialog";
import { formatDate, formatMoney } from "../contracts/contractTables";
import { CustomerSubPageHeader } from "./CustomerSubPageHeader";
import { ExtraWorkRegisterSection } from "./ExtraWorkRegisterSection";

/**
 * Sprint 162 §4 — one customer's contracts, in the same place their
 * Buildings, Users, Pricing and Extra Work live.
 *
 * **No new endpoint.** `/api/contracts/?customer=<id>` already filters
 * (`views_contracts.apply_contract_filters`), already scopes through
 * `filter_contracts_for`, and already 403s every customer-side role —
 * so this page is a caller, not a surface. Adding a second endpoint
 * would have been a second place for the scoping rule to be got wrong.
 *
 * **This page is provider-side only.** Contracts carry the customer's
 * negotiated prices, and Sprint 160 deliberately opened no
 * customer-facing surface for them. A CUSTOMER_* role never reaches
 * this route (the customer area's own guard) and would be 403'd by the
 * endpoint regardless; `contracts/tests/test_api.py` pins the second
 * floor.
 *
 * **Bounded**, like every list over a server collection: the page reads
 * one page of the paginated endpoint and says how many there are in
 * total, rather than fetching everything to render a section.
 */
export function CustomerContractsPage() {
  // `:id`, matching every sibling route under /admin/customers/.
  const { id: customerId } = useParams<{ id: string }>();
  const id = Number(customerId);
  const { t, i18n } = useTranslation("contracts");
  const { t: tc } = useTranslation("common");

  const [contracts, setContracts] = useState<Contract[]>([]);
  const [count, setCount] = useState(0);
  const [customerName, setCustomerName] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);

  const load = useCallback(() => {
    if (!Number.isFinite(id)) return undefined;
    let cancelled = false;
    Promise.all([listContracts({ customer: id }), getCustomer(id)])
      .then(([list, customer]) => {
        if (cancelled) return;
        setContracts(list.results);
        setCount(list.count);
        setCustomerName(customer.name);
        setIsActive(customer.is_active);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => load(), [load]);

  const locale = i18n.language;
  const { me } = useAuth();
  const canManage = canManageContracts(me?.role);

  return (
    <div data-testid="customer-contracts-page">
      <CustomerSubPageHeader customerName={customerName} isActive={isActive} />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <div className="section-head">
          <div>
            <span className="section-head-title">{t("list.title")}</span>{" "}
            <span className="section-head-sub">
              {t("table.countLabel", { count })}
            </span>
          </div>
          {/* Sprint 169 §7 — the SAME gate the contracts list uses, not
              a role list written again here: a role that can see this
              page but not create gets no button at all, rather than one
              that 403s. */}
          {canManage && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setFormOpen(true)}
              data-testid="customer-contracts-new"
            >
              <Plus size={14} strokeWidth={2.5} />
              {t("actions.newContract")}
            </button>
          )}
        </div>

        {!loaded && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                <th>{t("table.contractNo")}</th>
                <th>{t("table.locations")}</th>
                <th>{t("table.type")}</th>
                <th className="contract-num">{t("table.monthly")}</th>
                <th>{tc("status")}</th>
                <th>{t("fields.startDate")}</th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((row) => (
                <tr key={row.id}>
                  <td className="td-subject">
                    <Link to={`/admin/contracts/${row.id}`}>
                      {row.contract_no}
                    </Link>
                  </td>
                  <td>
                    {row.buildings.length === 0 ? (
                      <span className="muted-empty">—</span>
                    ) : (
                      row.buildings.map((b) => b.name).join(", ")
                    )}
                  </td>
                  <td>
                    {row.contract_type_name ?? (
                      <span className="muted-empty">—</span>
                    )}
                  </td>
                  <td className="contract-num">
                    {formatMoney(row.monthly_amount, locale)}
                  </td>
                  <td>
                    <span className={`cell-tag ${STATUS_TAG[row.status]}`}>
                      {t(`status.${row.status}`)}
                    </span>
                  </td>
                  <td className="td-date">
                    {formatDate(row.start_date, locale)}
                  </td>
                </tr>
              ))}
              {loaded && contracts.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    {t("customerSection.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* The page shows ONE page of the endpoint. When there are more,
            say so and send the operator to the full list filtered to
            this customer, rather than silently showing a prefix. */}
        {count > contracts.length && (
          <div className="pagination">
            <span className="pagination-info">
              {t("customerSection.showing", {
                shown: contracts.length,
                count,
              })}
            </span>
            <Link
              className="btn btn-secondary btn-sm"
              to={`/admin/contracts?customer=${id}`}
              data-testid="customer-contracts-see-all"
            >
              {t("customerSection.seeAll")}
            </Link>
          </div>
        )}
      </div>
      {/* W16 — the extra works register, under the recurring
          agreements and not mixed into them. Two kinds of money live on
          this page and they must not be added up: above is what this
          customer pays every month by agreement, below is what they
          have taken on job by job. The reference system keeps its own
          register out of the contract list for the same reason
          (`ContractController.php:37`). */}
      <ExtraWorkRegisterSection customerId={id} canManage={canManage} />

      {/* The SAME create dialog the main contracts list opens, with
          the customer fixed. A second form here is how two screens end
          up disagreeing about what a contract needs. */}
      <ContractFormDialog
        open={formOpen}
        fixedCustomerId={id}
        onClose={() => setFormOpen(false)}
        onCreated={() => {
          setFormOpen(false);
          // The row appears without a page reload: the page's own
          // loader is re-run rather than the browser reloading.
          load();
        }}
      />
    </div>
  );
}

/** Same mapping the contracts list and detail pages use — the design
 *  system's `cell-tag`, not a palette of this page's own. */
const STATUS_TAG: Record<Contract["status"], string> = {
  ACTIVE: "cell-tag-open",
  DRAFT: "cell-tag-muted",
  EXPIRED: "cell-tag-closed",
  CANCELLED: "cell-tag-rejected",
};
