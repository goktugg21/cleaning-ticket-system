import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { getCustomer, listCustomerBuildings } from "../../api/admin";
import { PageHeader } from "../../components/PageHeader";
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
    <div data-testid="bm-customer-detail-page">
      {/* Sprint 180 §1 — the shared header. `admin-page-head`,
          `admin-back-link`, `admin-page-title` and `admin-page-sub` were
          defined nowhere, so the back link rendered as a plain inline
          anchor and the customer's name as a browser-default `h1` in the
          body face. `PageHeader` owns the back link (`link-back`, with
          the same chevron) and the house 28/800 title. Both test ids are
          kept where they were. */}
      <PageHeader
        backLink={{
          to: "/admin/customers",
          label: t("bm_customer_detail.back"),
        }}
        title={
          <span data-testid="bm-customer-detail-title">
            {customer ? customer.name : t("loading")}
          </span>
        }
        subtitle={
          <span data-testid="bm-customer-detail-readonly-hint">
            {t("bm_customer_detail.readonly_hint")}
          </span>
        }
      />

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
            {/* Sprint 180 §1 — the house read-only field rows
                (`detail-field-row` / `-label` / `-value`), which is what
                the building and customer detail pages use. The
                definition list this replaces asked for a class that had
                no rule behind it at all, so its labels and values
                stacked as plain block text with the reset removing even
                the browser's own indent — the two columns the markup
                implied never existed. An empty value now carries
                `muted-empty`, exactly as on the building detail page. */}
            <>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customers.col_name")}
                </div>
                <div
                  className="detail-field-value"
                  data-testid="bm-customer-detail-name"
                >
                  {customer.name}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customers.col_contact_email")}
                </div>
                <div
                  className={`detail-field-value${
                    customer.contact_email ? "" : " muted-empty"
                  }`}
                >
                  {customer.contact_email || "—"}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customers.col_phone")}
                </div>
                <div
                  className={`detail-field-value${
                    customer.phone ? "" : " muted-empty"
                  }`}
                >
                  {customer.phone || "—"}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("bm_customer_detail.field_language")}
                </div>
                <div
                  className={`detail-field-value${
                    customer.language ? "" : " muted-empty"
                  }`}
                >
                  {customer.language || "—"}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("bm_customer_detail.field_active")}
                </div>
                <div className="detail-field-value">
                  {customer.is_active
                    ? t("bm_customer_detail.active_yes")
                    : t("bm_customer_detail.active_no")}
                </div>
              </div>
            </>
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
