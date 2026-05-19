import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  deactivateUser,
  getBuilding,
  getCompany,
  getCustomer,
  getUser,
  reactivateUser,
} from "../../api/admin";
import type {
  BuildingAdmin,
  CompanyAdmin,
  CustomerAdmin,
  UserAdminDetail,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { RoleBadge } from "../../components/RoleBadge";
import { useSavedBanner } from "../../hooks/useSavedBanner";
import { formatDateTime } from "../../lib/intl";

/**
 * Sprint 29 Batch 29.6 — User Detail page (read-only view).
 *
 * View-first per the 2026-05-15 stakeholder doc §3. `/admin/users/:id`
 * loads this page in read-only mode; an explicit role-gated Edit button
 * (top right) navigates to `/admin/users/:id/edit` which renders the
 * legacy `UserFormPage` form (including the memberships / staff-profile /
 * staff-visibility editors — those affordances stay on the edit surface
 * as written in the 29.6 brief). SUPER_ADMIN may also Deactivate /
 * Reactivate from this page — those affordances moved verbatim from the
 * form page.
 *
 * Mirrors the 29.3 (Companies) / 29.4 (Buildings) detail shape. A few
 * shape differences specific to users:
 *
 *   - The two-tier fetch resolves three relational id arrays
 *     (company_ids / building_ids / customer_ids) to names via
 *     parallel `Promise.all`s. Each per-entity fetch is defensive — a
 *     403 on a single membership entity (e.g. a COMPANY_ADMIN viewing a
 *     cross-company SUPER_ADMIN's company memberships) must not break
 *     the page; the null is filtered out before render.
 *
 *   - The Customer access card is a PLACEHOLDER for Sprint 29 Batch
 *     29.7. Per-row links land on the existing 29.2 deep-link
 *     `/admin/customers/<id>/permissions?focus_user=<id>`. The locked
 *     `data-testid` strings on the row + link are stable so 29.7 can
 *     attach a permission-override rollup chip on the right side of
 *     the row without re-wiring this page. We deliberately do not
 *     compute any override counts here.
 */
export function UserDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const { t } = useTranslation("common");

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [savedBanner] = useSavedBanner({
    saved: t("users.banner_saved"),
  });

  const [user, setUser] = useState<UserAdminDetail | null>(null);
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);
  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setError(t("user_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    // Tier 1: fetch the user.
    getUser(numericId)
      .then(async (userData) => {
        if (cancelled) return;
        setUser(userData);
        // Tier 2: parallel resolution of the three relational id
        // arrays. Each per-entity fetch is defensive — a single 403
        // on a membership entity must not break the page; we filter
        // nulls when rendering.
        const [resolvedCompanies, resolvedBuildings, resolvedCustomers] =
          await Promise.all([
            Promise.all(
              userData.company_ids.map((cid) =>
                getCompany(cid).catch(() => null),
              ),
            ),
            Promise.all(
              userData.building_ids.map((bid) =>
                getBuilding(bid).catch(() => null),
              ),
            ),
            Promise.all(
              userData.customer_ids.map((cid) =>
                getCustomer(cid).catch(() => null),
              ),
            ),
          ]);
        if (cancelled) return;
        setCompanies(
          resolvedCompanies.filter((c): c is CompanyAdmin => c !== null),
        );
        setBuildings(
          resolvedBuildings.filter((b): b is BuildingAdmin => b !== null),
        );
        setCustomers(
          resolvedCustomers.filter((c): c is CustomerAdmin => c !== null),
        );
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

  async function handleConfirmDeactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setError("");
    try {
      await deactivateUser(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/users?deactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setError("");
    try {
      await reactivateUser(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/users?reactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  // SUPER_ADMIN always; COMPANY_ADMIN may edit any user EXCEPT
  // SUPER_ADMIN / COMPANY_ADMIN targets (mirrors UserFormPage L118–119
  // and the backend's role-management guard). Backend enforces this
  // independently; the UI gate is defence in depth.
  const canEdit =
    me?.role === "SUPER_ADMIN" ||
    (me?.role === "COMPANY_ADMIN" &&
      user !== null &&
      user.role !== "SUPER_ADMIN" &&
      user.role !== "COMPANY_ADMIN");

  // The form page uses email as title fallback for the page header;
  // here we prefer full_name (more user-friendly) and fall back to
  // email when blank — matches the rest of the admin detail set.
  const headerTitle = user
    ? user.full_name && user.full_name.trim().length > 0
      ? user.full_name
      : user.email
    : "";

  const isActive = user?.is_active ?? true;

  const languageLabel = (() => {
    if (!user) return "";
    if (user.language === "nl") {
      return `${t("language_dutch")} (nl)`;
    }
    if (user.language === "en") {
      return `${t("language_english")} (en)`;
    }
    return user.language;
  })();

  const isSelf = me?.id === numericId;

  const headerActions = user ? (
    <>
      {!isActive && isSuperAdmin && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid="reactivate-button"
          onClick={() => reactivateDialogRef.current?.open()}
        >
          {t("admin_form.reactivate")}
        </button>
      )}
      {isActive && isSuperAdmin && !isSelf && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid="deactivate-button"
          onClick={() => deactivateDialogRef.current?.open()}
        >
          {t("admin_form.deactivate")}
        </button>
      )}
      {canEdit && (
        <Link
          to={`/admin/users/${user.id}/edit`}
          className="btn btn-primary btn-sm"
          data-testid="user-edit-link"
        >
          {t("user_detail.edit_button")}
        </Link>
      )}
    </>
  ) : null;

  const hasAnyMembership =
    companies.length > 0 || buildings.length > 0 || customers.length > 0;

  return (
    <div data-testid="user-detail-page">
      <PageHeader
        backLink={{
          to: "/admin/users",
          label: t("user_form.back"),
        }}
        eyebrow={t("nav.admin_group")}
        title={headerTitle}
        statusPill={
          !isActive ? (
            <span className="cell-tag cell-tag-closed">
              <i />
              {t("user_detail.status_inactive")}
            </span>
          ) : undefined
        }
        actions={headerActions}
      />

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !user ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : user ? (
        <>
          <section
            className="card"
            data-testid="user-detail-about-card"
            style={{ padding: "20px 22px", marginBottom: 16 }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">
                  {t("user_detail.about_title")}
                </div>
                <div className="section-head-sub">
                  {t("user_detail.about_desc")}
                </div>
              </div>
            </div>

            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("user_detail.field_full_name")}
              </div>
              <div
                className={`detail-field-value${
                  user.full_name ? "" : " muted-empty"
                }`}
              >
                {user.full_name || "—"}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("user_detail.field_email")}
              </div>
              <div className="detail-field-value">
                <a href={`mailto:${user.email}`}>{user.email}</a>
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("user_detail.field_role")}
              </div>
              <div className="detail-field-value">
                <RoleBadge role={user.role} />
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("user_detail.field_language")}
              </div>
              <div className="detail-field-value">{languageLabel}</div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("user_detail.field_status")}
              </div>
              <div className="detail-field-value">
                {isActive ? (
                  <span className="cell-tag cell-tag-open">
                    <i />
                    {t("user_detail.status_active")}
                  </span>
                ) : (
                  <span className="cell-tag cell-tag-closed">
                    <i />
                    {t("user_detail.status_inactive")}
                  </span>
                )}
              </div>
            </div>
            {user.deleted_at !== null && (
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("user_detail.field_deleted_at")}
                </div>
                <div className="detail-field-value muted-empty">
                  {formatDateTime(user.deleted_at)}
                </div>
              </div>
            )}
          </section>

          <section
            className="card"
            data-testid="user-detail-memberships-card"
            style={{ padding: "20px 22px", marginBottom: 16 }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">
                  {t("user_detail.memberships.title")}
                </div>
                <div className="section-head-sub">
                  {t("user_detail.memberships.desc")}
                </div>
              </div>
            </div>

            {!hasAnyMembership ? (
              <EmptyState
                title={t("user_detail.memberships.empty")}
                compact
                testId="user-detail-memberships-empty"
              />
            ) : (
              <>
                {companies.length > 0 && (
                  <div className="user-detail-membership-group">
                    <div className="user-detail-membership-group-title">
                      {t("user_detail.memberships.companies_title")}
                    </div>
                    <ul className="user-detail-membership-list">
                      {companies.map((c) => (
                        <li key={c.id}>
                          <Link to={`/admin/companies/${c.id}`}>{c.name}</Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {buildings.length > 0 && (
                  <div className="user-detail-membership-group">
                    <div className="user-detail-membership-group-title">
                      {t("user_detail.memberships.buildings_title")}
                    </div>
                    <ul className="user-detail-membership-list">
                      {buildings.map((b) => (
                        <li key={b.id}>
                          <Link to={`/admin/buildings/${b.id}`}>{b.name}</Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {customers.length > 0 && (
                  <div className="user-detail-membership-group">
                    <div className="user-detail-membership-group-title">
                      {t("user_detail.memberships.customers_title")}
                    </div>
                    <ul className="user-detail-membership-list">
                      {customers.map((c) => (
                        <li key={c.id}>
                          <Link to={`/admin/customers/${c.id}`}>{c.name}</Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </section>

          {/* Sprint 29 Batch 29.7 placeholder — per-customer access row
              with a "View permissions" deep-link that lands on
              29.2's `?focus_user=` surface. The locked testid strings
              (`user-detail-customer-row-<id>` and
              `user-detail-permissions-link-<id>`) are stable so 29.7
              can attach a permission-override rollup chip on the
              right of each row without re-wiring this page. */}
          {user.customer_ids.length > 0 && customers.length > 0 && (
            <section
              className="card"
              data-testid="user-detail-customer-access-card"
              style={{ padding: "20px 22px" }}
            >
              <div className="section-head" style={{ marginBottom: 8 }}>
                <div>
                  <div className="section-head-title">
                    {t("user_detail.customer_access.title")}
                  </div>
                  <div className="section-head-sub">
                    {t("user_detail.customer_access.desc")}
                  </div>
                </div>
              </div>

              <ul className="user-detail-customer-access-list">
                {customers.map((c) => (
                  <li
                    key={c.id}
                    className="user-detail-customer-access-row"
                    data-testid={`user-detail-customer-row-${c.id}`}
                  >
                    <span className="user-detail-customer-access-name">
                      <Link to={`/admin/customers/${c.id}`}>{c.name}</Link>
                    </span>
                    <Link
                      to={`/admin/customers/${c.id}/permissions?focus_user=${user.id}`}
                      className="btn btn-ghost btn-sm"
                      data-testid={`user-detail-permissions-link-${c.id}`}
                    >
                      {t("user_detail.customer_access.view_permissions")}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ConfirmDialog
            ref={deactivateDialogRef}
            title={t("user_form.dialog_deactivate_title", {
              email: user.email,
            })}
            body={t("user_form.dialog_deactivate_body")}
            confirmLabel={t("admin_form.deactivate")}
            onConfirm={handleConfirmDeactivate}
            busy={actionBusy}
          />

          <ConfirmDialog
            ref={reactivateDialogRef}
            title={t("user_form.dialog_reactivate_title", {
              email: user.email,
            })}
            body={t("user_form.dialog_reactivate_body")}
            confirmLabel={t("admin_form.reactivate")}
            onConfirm={handleConfirmReactivate}
            busy={actionBusy}
          />
        </>
      ) : null}
    </div>
  );
}

