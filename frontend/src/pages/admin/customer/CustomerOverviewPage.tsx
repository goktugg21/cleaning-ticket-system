import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Mail,
  MapPin,
  Receipt,
  ShieldCheck,
  Tag,
  UserCog,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  getCompany,
  getCustomer,
  listCustomerBuildings,
  listCustomerContacts,
  listCustomerPrices,
  listCustomerUsers,
  reactivateCustomer,
} from "../../../api/admin";
import type {
  CompanyAdmin,
  CustomerAdmin,
  CustomerBuildingMembership,
} from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 28 Batch 13 (rework) — Customer Overview page (admin variant).
 *
 * View-first per the 2026-05-15 stakeholder doc §3. The page is a
 * useful operator dashboard for a single customer — not a tile menu.
 * Composition top-to-bottom:
 *
 *   1. CustomerSubPageHeader (back link + name + Edit basics action).
 *   2. Explainer paragraph naming the provider company + linked-
 *      building count.
 *   3. Four-card clickable stat strip (Buildings / Users / Contacts /
 *      Pricing) routing into the sub-pages.
 *   4. Linked buildings preview (first 5 + View-all footer link), with
 *      a friendly empty-state when none are linked.
 *   5. Quicklink grid for the six management areas.
 *
 * Nothing on this page mutates a permission, a policy, or a per-
 * building access row — those affordances live exclusively on the
 * Permissions sub-page. The Playwright spec locks that contract.
 */
export function CustomerOverviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [providerCompany, setProviderCompany] = useState<CompanyAdmin | null>(
    null,
  );
  const [linkedBuildings, setLinkedBuildings] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [memberCount, setMemberCount] = useState<number | null>(null);
  const [contactCount, setContactCount] = useState<number | null>(null);
  const [pricingCount, setPricingCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

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
    // Run the five reads in parallel. Each non-customer fetch falls
    // back to a friendly "—" placeholder if the endpoint 403s or 404s
    // for the current operator (e.g. a COMPANY_ADMIN looking at a
    // legacy customer with no pricing rows yet).
    Promise.all([
      getCustomer(numericId),
      listCustomerBuildings(numericId).catch(() => ({
        count: 0,
        next: null,
        previous: null,
        results: [],
      })),
      listCustomerUsers(numericId).catch(() => ({
        count: 0,
        next: null,
        previous: null,
        results: [],
      })),
      listCustomerContacts(numericId).catch(() => [] as never[]),
      listCustomerPrices(numericId).catch(() => [] as never[]),
    ])
      .then(
        ([
          customerData,
          buildingsResponse,
          usersResponse,
          contactsResponse,
          pricesResponse,
        ]) => {
          if (cancelled) return;
          setCustomer(customerData);
          setLinkedBuildings(buildingsResponse.results);
          setMemberCount(usersResponse.count ?? usersResponse.results.length);
          setContactCount(contactsResponse.length);
          setPricingCount(pricesResponse.length);
          // Provider company name is informational; if the lookup fails
          // we fall back to the generic explainer.
          getCompany(customerData.company)
            .then((company) => {
              if (!cancelled) setProviderCompany(company);
            })
            .catch(() => {
              if (!cancelled) setProviderCompany(null);
            });
        },
      )
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

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setError("");
    try {
      await reactivateCustomer(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/customers?reactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;
  const buildingsCount = linkedBuildings.length;

  const headerActions = customer ? (
    <>
      {!isActive && isSuperAdmin && (
        <button
          type="button"
          className="btn btn-primary btn-sm"
          data-testid="reactivate-button"
          onClick={() => reactivateDialogRef.current?.open()}
        >
          {t("admin_form.reactivate")}
        </button>
      )}
      <Link
        to={`/admin/customers/${customer.id}/edit`}
        className="btn btn-secondary btn-sm"
        data-testid="customer-overview-edit-basics"
      >
        {t("customer_view.overview.edit_basics")}
      </Link>
    </>
  ) : null;

  const explainerText = providerCompany
    ? t("customer_view.overview.explainer_with_provider", {
        customer: customerName,
        provider: providerCompany.name,
        count: buildingsCount,
      })
    : t("customer_view.overview.explainer_generic", {
        customer: customerName,
        count: buildingsCount,
      });

  return (
    <div data-testid="customer-overview-page">
      <CustomerSubPageHeader
        customerName={customerName}
        isActive={isActive}
        actions={headerActions}
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
            data-testid="customer-overview-explainer"
          >
            {explainerText}
          </p>

          <div
            className="summary-grid"
            data-testid="customer-overview-stat-strip"
          >
            <Link
              to={`/admin/customers/${customer.id}/buildings`}
              className="summary-stat"
              data-testid="customer-overview-stat-buildings"
            >
              <span className="summary-stat-label">
                {t("customer_view.overview.stat_linked_buildings")}
              </span>
              <span className="summary-stat-value">{buildingsCount}</span>
              <span className="summary-stat-meta">
                {t("customer_view.overview.quicklink_buildings_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/users`}
              className="summary-stat"
              data-testid="customer-overview-stat-users"
            >
              <span className="summary-stat-label">
                {t("customer_view.overview.stat_customer_users")}
              </span>
              <span className="summary-stat-value">
                {memberCount ?? "—"}
              </span>
              <span className="summary-stat-meta">
                {t("customer_view.overview.quicklink_users_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/contacts`}
              className="summary-stat"
              data-testid="customer-overview-stat-contacts"
            >
              <span className="summary-stat-label">
                {t("customer_view.overview.stat_contacts")}
              </span>
              <span className="summary-stat-value">
                {contactCount ?? "—"}
              </span>
              <span className="summary-stat-meta">
                {t("customer_view.overview.quicklink_contacts_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/pricing`}
              className="summary-stat"
              data-testid="customer-overview-stat-pricing"
            >
              <span className="summary-stat-label">
                {t("customer_view.overview.stat_pricing")}
              </span>
              <span className="summary-stat-value">
                {pricingCount ?? "—"}
              </span>
              <span className="summary-stat-meta">
                {t("customer_view.overview.quicklink_pricing_desc")}
              </span>
            </Link>
          </div>

          <div
            className="card"
            data-testid="customer-overview-buildings-preview"
            style={{ marginBottom: 18 }}
          >
            <div className="section-head">
              <div className="section-head-title">
                {t("customer_view.overview.buildings_preview_title")}
              </div>
              {buildingsCount > 5 && (
                <Link
                  to={`/admin/customers/${customer.id}/buildings`}
                  className="btn btn-ghost btn-sm"
                >
                  {t("customer_view.overview.buildings_preview_view_all", {
                    count: buildingsCount,
                  })}
                </Link>
              )}
            </div>
            <div style={{ padding: "14px 18px 18px" }}>
              {buildingsCount === 0 ? (
                <p className="muted small">
                  {t("customer_view.overview.buildings_preview_empty")}
                </p>
              ) : (
                <div className="bld-list">
                  {linkedBuildings.slice(0, 5).map((link) => (
                    <div
                      key={link.id}
                      className="bld-row-head"
                      style={{ alignItems: "flex-start" }}
                    >
                      <div style={{ display: "flex", flexDirection: "column" }}>
                        <span className="bld-row-name">{link.building_name}</span>
                        {link.building_address && (
                          <span
                            className="muted small"
                            style={{ marginTop: 2 }}
                          >
                            {link.building_address}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div
            className="quicklink-grid"
            data-testid="customer-overview-quicklinks"
          >
            <Link
              to={`/admin/customers/${customer.id}/contacts`}
              className="quicklink-card"
              data-testid="customer-overview-quicklink-contacts"
            >
              <span className="quicklink-card-head">
                <Mail size={18} strokeWidth={2} />
                {t("customer_view.overview.quicklink_contacts")}
              </span>
              <span className="quicklink-card-desc">
                {t("customer_view.overview.quicklink_contacts_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/buildings`}
              className="quicklink-card"
              data-testid="customer-overview-quicklink-buildings"
            >
              <span className="quicklink-card-head">
                <MapPin size={18} strokeWidth={2} />
                {t("customer_view.overview.quicklink_buildings")}
              </span>
              <span className="quicklink-card-desc">
                {t("customer_view.overview.quicklink_buildings_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/users`}
              className="quicklink-card"
              data-testid="customer-overview-quicklink-users"
            >
              <span className="quicklink-card-head">
                <UserCog size={18} strokeWidth={2} />
                {t("customer_view.overview.quicklink_users")}
              </span>
              <span className="quicklink-card-desc">
                {t("customer_view.overview.quicklink_users_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/permissions`}
              className="quicklink-card"
              data-testid="customer-overview-quicklink-permissions"
            >
              <span className="quicklink-card-head">
                <ShieldCheck size={18} strokeWidth={2} />
                {t("customer_view.overview.quicklink_permissions")}
              </span>
              <span className="quicklink-card-desc">
                {t("customer_view.overview.quicklink_permissions_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/pricing`}
              className="quicklink-card"
              data-testid="customer-overview-quicklink-pricing"
            >
              <span className="quicklink-card-head">
                <Tag size={18} strokeWidth={2} />
                {t("customer_view.overview.quicklink_pricing")}
              </span>
              <span className="quicklink-card-desc">
                {t("customer_view.overview.quicklink_pricing_desc")}
              </span>
            </Link>
            <Link
              to={`/admin/customers/${customer.id}/extra-work`}
              className="quicklink-card"
              data-testid="customer-overview-quicklink-extra-work"
            >
              <span className="quicklink-card-head">
                <Receipt size={18} strokeWidth={2} />
                {t("customer_view.overview.quicklink_extra_work")}
              </span>
              <span className="quicklink-card-desc">
                {t("customer_view.overview.quicklink_extra_work_desc")}
              </span>
            </Link>
          </div>

          <ConfirmDialog
            ref={reactivateDialogRef}
            title={t("customer_form.dialog_reactivate_title", {
              name: customerName,
            })}
            body={t("customer_form.dialog_reactivate_body")}
            confirmLabel={t("admin_form.reactivate")}
            onConfirm={handleConfirmReactivate}
            busy={actionBusy}
          />
        </>
      ) : null}
    </div>
  );
}
