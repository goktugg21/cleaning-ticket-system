import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { getCustomer, listCustomerBuildings } from "../../api/admin";
import type {
  CustomerAdmin,
  CustomerBuildingMembership,
} from "../../api/types";

/**
 * Sprint 28 Batch 12 — Building Manager read-only customer detail.
 *
 * Renders read-only fields for a single customer the BM is allowed to
 * see (scope-enforced server-side via `scope_customers_for`). No
 * Add / Edit / Delete / form controls. A side action links to the
 * Contacts read-only view for the same customer.
 *
 * 404 from the backend (BM not in scope) is surfaced as an inline
 * error; the route guard `CustomerReadRoute` already kept the BM
 * inside the role wall.
 */
export function BuildingManagerCustomerDetailPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");
  const numericId = useMemo(() => {
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [buildings, setBuildings] = useState<CustomerBuildingMembership[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      // Sprint 28 Batch 12 — mirror `CustomerContactsPage.tsx`
      // (Batch 4) pattern: defer the synchronous setState into a
      // microtask to keep the effect body free of cascading-render
      // lint hits. The microtask runs before paint so the UI
      // converges in the same frame.
      queueMicrotask(() => {
        if (!cancelled) setError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    // Sprint 28 Batch 12 — existing baseline pattern; synchronous
    // loading=true before the async fetch resolves so the page
    // never flashes an empty state.
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    Promise.all([
      getCustomer(numericId),
      listCustomerBuildings(numericId).catch(() => ({
        count: 0,
        next: null,
        previous: null,
        results: [],
      })),
    ])
      .then(([customerData, buildingsResponse]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setBuildings(buildingsResponse.results);
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
  }, [numericId, t]);

  return (
    <div className="admin-page" data-testid="bm-customer-detail-page">
      <header className="admin-page-head">
        <div>
          <Link
            to="/admin/customers"
            className="admin-back-link"
            data-testid="bm-customer-detail-back"
          >
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("bm_customer_detail.back")}
          </Link>
          <h1
            className="admin-page-title"
            data-testid="bm-customer-detail-title"
          >
            {customer ? customer.name : t("loading")}
          </h1>
          <p
            className="admin-page-sub"
            data-testid="bm-customer-detail-readonly-hint"
          >
            {t("bm_customer_detail.readonly_hint")}
          </p>
        </div>
      </header>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !customer ? (
        <p className="muted">{t("loading")}</p>
      ) : customer ? (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-head">
              <div className="section-head-title">
                {t("bm_customer_detail.section_basic_title")}
              </div>
            </div>
            <dl className="readonly-grid">
              <dt>{t("customers.col_name")}</dt>
              <dd data-testid="bm-customer-detail-name">{customer.name}</dd>
              <dt>{t("customers.col_contact_email")}</dt>
              <dd>{customer.contact_email || "—"}</dd>
              <dt>{t("customers.col_phone")}</dt>
              <dd>{customer.phone || "—"}</dd>
              <dt>{t("bm_customer_detail.field_language")}</dt>
              <dd>{customer.language || "—"}</dd>
              <dt>{t("bm_customer_detail.field_active")}</dt>
              <dd>
                {customer.is_active
                  ? t("bm_customer_detail.active_yes")
                  : t("bm_customer_detail.active_no")}
              </dd>
            </dl>
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-head">
              <div className="section-head-title">
                {t("bm_customer_detail.section_buildings_title")}
              </div>
            </div>
            {buildings.length === 0 ? (
              <p className="muted" data-testid="bm-customer-detail-buildings-empty">
                {t("bm_customer_detail.buildings_empty")}
              </p>
            ) : (
              <ul
                className="readonly-list"
                data-testid="bm-customer-detail-buildings"
              >
                {buildings.map((row) => (
                  <li key={row.id}>{row.building_name}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="card">
            <div className="section-head">
              <div className="section-head-title">
                {t("bm_customer_detail.section_contacts_title")}
              </div>
            </div>
            <p className="muted" style={{ marginBottom: 8 }}>
              {t("bm_customer_detail.contacts_hint")}
            </p>
            <Link
              to={`/admin/customers/${customer.id}/contacts`}
              className="btn btn-secondary btn-sm"
              data-testid="bm-customer-detail-contacts-link"
            >
              {t("bm_customer_detail.contacts_link")}
            </Link>
          </div>
        </>
      ) : null}
    </div>
  );
}
