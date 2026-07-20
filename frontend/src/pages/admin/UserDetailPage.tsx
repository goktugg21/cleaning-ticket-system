import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Paperclip } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  deactivateUser,
  getBuilding,
  getCompany,
  getCustomer,
  getStaffProfile,
  getUser,
  listBuildingManagers,
  listCustomerUserAccess,
  listStaffVisibility,
  reactivateUser,
  updateBuildingManager,
} from "../../api/admin";
import {
  downloadCredentialDocument,
  downloadPropertyDocument,
  listCredentials,
  listProperties,
} from "../../api/staffCredentials";
import type {
  CustomProfileProperty,
  StaffCredential,
} from "../../api/staffCredentials";
import {
  BM_REVOCABLE_PERMISSION_KEYS,
  type BmRevocablePermissionKey,
} from "../../api/types";
import type {
  BuildingAdmin,
  BuildingManagerMembership,
  BuildingStaffVisibilityAdmin,
  CompanyAdmin,
  CustomerAdmin,
  CustomerUserBuildingAccess,
  StaffProfileAdmin,
  UserAdminDetail,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { useToast } from "../../components/ToastProvider";
import { PermissionsRollupChip } from "../../components/PermissionsRollupChip";
import { PermissionsRollupSummary } from "../../components/PermissionsRollupSummary";
import { RoleBadge } from "../../components/RoleBadge";
import { useSavedBanner } from "../../hooks/useSavedBanner";
import { formatDateTime } from "../../lib/intl";
import { Toggle } from "../../components/Toggle";

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
  // Sprint 29 Batch 29.7 — third-tier fan-out resolving per-customer
  // access rows for this user, used to power the
  // <PermissionsRollupChip> on each customer access row. Defensive
  // `.catch` per the entity-name fetch pattern from 29.6.
  const [accessByCustomerId, setAccessByCustomerId] = useState<
    Record<number, CustomerUserBuildingAccess[]>
  >({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // Sprint 29 Batch 29.8.5 — per-customer toggle for the inline
  // <PermissionsRollupSummary>. Single-expansion across all customer
  // rows so the operator never sees two summaries at once.
  const [summaryCustomerId, setSummaryCustomerId] = useState<number | null>(
    null,
  );

  // Sprint 31 — BM membership permission_overrides editor.
  // bmMembershipsByBuildingId is keyed by building.id and resolves to:
  //   * a `BuildingManagerMembership` row (carries the
  //     `permission_overrides` dict the editor edits),
  //   * null when the GET 403'd (caller has no read access to that
  //     building's manager list) or returned no row for this user.
  // bmDraftOverridesByBuildingId is the per-row dirty buffer; absent
  // when no edit is in progress. bmSaveBusyId is the building id
  // currently being PATCHed (one at a time). bmSavedBuildingId is the
  // last successfully-saved row (for the inline "Saved." banner).
  // bmErrorByBuildingId surfaces a per-row error from the PATCH.
  const [bmMembershipsByBuildingId, setBmMembershipsByBuildingId] = useState<
    Record<number, BuildingManagerMembership | null>
  >({});
  const [bmDraftOverridesByBuildingId, setBmDraftOverridesByBuildingId] =
    useState<Record<number, Record<string, boolean>>>({});
  const [bmSaveBusyId, setBmSaveBusyId] = useState<number | null>(null);
  const [bmSavedBuildingId, setBmSavedBuildingId] = useState<number | null>(
    null,
  );
  const [bmErrorByBuildingId, setBmErrorByBuildingId] = useState<
    Record<number, string>
  >({});

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
    setLoading(true);
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
        const filteredCustomers = resolvedCustomers.filter(
          (c): c is CustomerAdmin => c !== null,
        );
        setCompanies(
          resolvedCompanies.filter((c): c is CompanyAdmin => c !== null),
        );
        setBuildings(
          resolvedBuildings.filter((b): b is BuildingAdmin => b !== null),
        );
        setCustomers(filteredCustomers);

        // Sprint 29 Batch 29.7 — tier-3 fan-out: resolve the per-
        // customer access rows for this user so the rollup chip can
        // render the override count on each Customer access row.
        // Defensive `.catch` — a 403 / 404 on a single customer must
        // not break the page; the chip falls back to "Default" (0
        // overrides) when an entry is missing.
        const accessEntries = await Promise.all(
          filteredCustomers.map((c) =>
            listCustomerUserAccess(c.id, userData.id)
              .then(
                (r) =>
                  [c.id, r.results] as [number, CustomerUserBuildingAccess[]],
              )
              .catch(
                () =>
                  [c.id, [] as CustomerUserBuildingAccess[]] as [
                    number,
                    CustomerUserBuildingAccess[],
                  ],
              ),
          ),
        );
        if (cancelled) return;
        setAccessByCustomerId(Object.fromEntries(accessEntries));
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

  // Sprint 31 — fetch BM memberships per building. Only the GET-allowed
  // roles (SUPER_ADMIN / COMPANY_ADMIN) attempt the fetch at all — the
  // `IsSuperAdminOrCompanyAdminForCompany` permission on the list view
  // 403s everyone else, and we don't want to spam the network with
  // doomed calls. A 403 on a single building (CA outside their own
  // company) is caught defensively so other buildings still resolve.
  // The new section renders iff at least one building resolved a row
  // for THIS user.
  const userIdForBmFetch = user?.id ?? null;
  const buildingIdsForBmFetch = useMemo(
    () => buildings.map((b) => b.id),
    [buildings],
  );
  const viewerCanReadBmMemberships =
    me?.role === "SUPER_ADMIN" || me?.role === "COMPANY_ADMIN";
  useEffect(() => {
    let cancelled = false;
    if (
      !viewerCanReadBmMemberships ||
      userIdForBmFetch === null ||
      buildingIdsForBmFetch.length === 0
    ) {
      queueMicrotask(() => {
        if (!cancelled) setBmMembershipsByBuildingId({});
      });
      return () => {
        cancelled = true;
      };
    }
    Promise.all(
      buildingIdsForBmFetch.map(async (bid) => {
        try {
          const response = await listBuildingManagers(bid);
          const row = response.results.find(
            (m) => m.user_id === userIdForBmFetch,
          );
          return [bid, row ?? null] as [number, BuildingManagerMembership | null];
        } catch {
          return [bid, null] as [number, BuildingManagerMembership | null];
        }
      }),
    ).then((entries) => {
      if (!cancelled) {
        setBmMembershipsByBuildingId(Object.fromEntries(entries));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    viewerCanReadBmMemberships,
    userIdForBmFetch,
    buildingIdsForBmFetch,
  ]);

  // Editability gate per building — SUPER_ADMIN always; COMPANY_ADMIN
  // only when the building's company is in their `me.company_ids`
  // (mirrors the backend `IsSuperAdminOrCompanyAdminForCompany` rule
  // on the PATCH endpoint, defence in depth). Drives the toggle
  // disabled state + the read-only notice.
  function canEditBmOverridesForBuilding(building: BuildingAdmin): boolean {
    if (!me) return false;
    if (me.role === "SUPER_ADMIN") return true;
    if (me.role === "COMPANY_ADMIN") {
      return me.company_ids.includes(building.company);
    }
    return false;
  }

  // True when the named key is currently effective for this building.
  // Backend default is True for a BM in scope; the stored
  // `permission_overrides[key]` only NARROWS that default to False.
  // So a missing key OR an explicit `true` reads as "granted"; only
  // an explicit `false` reads as "revoked".
  function isKeyGranted(
    overrides: Record<string, boolean>,
    key: BmRevocablePermissionKey,
  ): boolean {
    return overrides[key] !== false;
  }

  // Diff a draft against the persisted membership row to decide if
  // the Save button enables. Compares the two BM-revocable keys only;
  // any other key the backend would 400 anyway.
  function bmDraftIsDirty(
    membership: BuildingManagerMembership,
    draft: Record<string, boolean>,
  ): boolean {
    for (const key of BM_REVOCABLE_PERMISSION_KEYS) {
      const stored = isKeyGranted(membership.permission_overrides, key);
      const next = isKeyGranted(draft, key);
      if (stored !== next) return true;
    }
    return false;
  }

  function toggleBmDraft(
    buildingId: number,
    key: BmRevocablePermissionKey,
    nextGranted: boolean,
  ) {
    setBmErrorByBuildingId((prev) => {
      if (prev[buildingId] === undefined) return prev;
      const next = { ...prev };
      delete next[buildingId];
      return next;
    });
    setBmSavedBuildingId((prev) =>
      prev === buildingId ? null : prev,
    );
    setBmDraftOverridesByBuildingId((prev) => {
      const membership = bmMembershipsByBuildingId[buildingId];
      const base =
        prev[buildingId] ?? membership?.permission_overrides ?? {};
      const next = { ...base };
      // Granted (default) = drop the key; revoked = explicit false.
      // Mirrors the backend "absent = default True" semantics so the
      // stored dict stays minimal.
      if (nextGranted) {
        delete next[key];
      } else {
        next[key] = false;
      }
      return { ...prev, [buildingId]: next };
    });
  }

  function resetBmDraft(buildingId: number) {
    setBmErrorByBuildingId((prev) => {
      if (prev[buildingId] === undefined) return prev;
      const next = { ...prev };
      delete next[buildingId];
      return next;
    });
    setBmSavedBuildingId((prev) =>
      prev === buildingId ? null : prev,
    );
    setBmDraftOverridesByBuildingId((prev) => {
      if (prev[buildingId] === undefined) return prev;
      const next = { ...prev };
      delete next[buildingId];
      return next;
    });
  }

  async function saveBmOverrides(building: BuildingAdmin) {
    const membership = bmMembershipsByBuildingId[building.id];
    if (!membership) return;
    const draft =
      bmDraftOverridesByBuildingId[building.id] ??
      membership.permission_overrides;
    if (!bmDraftIsDirty(membership, draft)) return;
    if (userIdForBmFetch === null) return;
    setBmSaveBusyId(building.id);
    setBmErrorByBuildingId((prev) => {
      if (prev[building.id] === undefined) return prev;
      const next = { ...prev };
      delete next[building.id];
      return next;
    });
    try {
      const updated = await updateBuildingManager(
        building.id,
        userIdForBmFetch,
        { permission_overrides: draft },
      );
      setBmMembershipsByBuildingId((prev) => ({
        ...prev,
        [building.id]: updated,
      }));
      setBmDraftOverridesByBuildingId((prev) => {
        if (prev[building.id] === undefined) return prev;
        const next = { ...prev };
        delete next[building.id];
        return next;
      });
      setBmSavedBuildingId(building.id);
    } catch (err) {
      setBmErrorByBuildingId((prev) => ({
        ...prev,
        [building.id]: getApiError(err),
      }));
    } finally {
      setBmSaveBusyId(null);
    }
  }

  // Buildings that actually resolved a BM row for this user. The
  // section header renders even when the list is empty (so a viewer
  // who CAN read but the user has zero BM assignments still sees an
  // empty-state hint), but we only render the table body when at
  // least one membership exists.
  const buildingsWithBmRow = useMemo(() => {
    return buildings.filter((b) => bmMembershipsByBuildingId[b.id] != null);
  }, [buildings, bmMembershipsByBuildingId]);
  const hasAnyBmRow = buildingsWithBmRow.length > 0;
  const shouldRenderBmSection =
    viewerCanReadBmMemberships && hasAnyBmRow;

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

          {/* Sprint 31 — Building manager per-(BM, building)
              permission_overrides editor. The card renders only when
              the viewer can READ the underlying GET
              (`IsSuperAdminOrCompanyAdminForCompany` on the manager
              list endpoint) AND the target user has at least one BM
              membership row. The two BM-revocable osius.* keys are
              the only fields the backend PATCH accepts; any other key
              is rejected with 400 server-side and we never offer one
              client-side. Editability per row is gated on whether
              the viewer can act on the building's company. */}
          {shouldRenderBmSection && (
            <section
              className="card"
              data-testid="user-detail-bm-permissions-card"
              style={{ padding: "20px 22px", marginBottom: 16 }}
            >
              <div className="section-head" style={{ marginBottom: 8 }}>
                <div>
                  <div className="section-head-title">
                    {t("user_detail.bm_permissions.title")}
                  </div>
                  <div className="section-head-sub">
                    {t("user_detail.bm_permissions.desc")}
                  </div>
                </div>
              </div>

              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("user_detail.bm_permissions.col_building")}</th>
                      <th>
                        {t("user_detail.bm_permissions.col_prepare")}
                      </th>
                      <th>
                        {t("user_detail.bm_permissions.col_override")}
                      </th>
                      <th
                        aria-label={t("user_detail.bm_permissions.col_actions")}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {buildingsWithBmRow.map((building) => {
                      const membership =
                        bmMembershipsByBuildingId[building.id];
                      if (!membership) return null;
                      const draft =
                        bmDraftOverridesByBuildingId[building.id] ??
                        membership.permission_overrides;
                      const canEdit =
                        canEditBmOverridesForBuilding(building);
                      const dirty = bmDraftIsDirty(membership, draft);
                      const busy = bmSaveBusyId === building.id;
                      const error = bmErrorByBuildingId[building.id];
                      const justSaved =
                        bmSavedBuildingId === building.id && !dirty;
                      const prepareKey =
                        "osius.building_manager.prepare_extra_work_proposal" as const;
                      const overrideKey =
                        "osius.building_manager.override_customer_decision" as const;
                      const preparedGranted = isKeyGranted(draft, prepareKey);
                      const overrideGranted = isKeyGranted(draft, overrideKey);
                      const rowTestId = `user-detail-bm-permissions-row-${building.id}`;
                      return (
                        <tr key={building.id} data-testid={rowTestId}>
                          <td className="td-subject">
                            <Link to={`/admin/buildings/${building.id}`}>
                              {building.name}
                            </Link>
                          </td>
                          <td>
                            {canEdit ? (
                              <label
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 8,
                                  cursor: busy ? "wait" : "pointer",
                                }}
                              >
                                <Toggle
                                  checked={preparedGranted}
                                  disabled={busy}
                                  onChange={(event) =>
                                    toggleBmDraft(
                                      building.id,
                                      prepareKey,
                                      event.target.checked,
                                    )
                                  }
                                  data-testid={`${rowTestId}-prepare-toggle`}
                                />
                                <span>
                                  {preparedGranted
                                    ? t("user_detail.bm_permissions.granted")
                                    : t("user_detail.bm_permissions.revoked")}
                                </span>
                              </label>
                            ) : (
                              <span
                                className={`cell-tag cell-tag-${preparedGranted ? "open" : "closed"}`}
                                data-testid={`${rowTestId}-prepare-readonly`}
                              >
                                <i />
                                {preparedGranted
                                  ? t("user_detail.bm_permissions.granted")
                                  : t("user_detail.bm_permissions.revoked")}
                              </span>
                            )}
                          </td>
                          <td>
                            {canEdit ? (
                              <label
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 8,
                                  cursor: busy ? "wait" : "pointer",
                                }}
                              >
                                <Toggle
                                  checked={overrideGranted}
                                  disabled={busy}
                                  onChange={(event) =>
                                    toggleBmDraft(
                                      building.id,
                                      overrideKey,
                                      event.target.checked,
                                    )
                                  }
                                  data-testid={`${rowTestId}-override-toggle`}
                                />
                                <span>
                                  {overrideGranted
                                    ? t("user_detail.bm_permissions.granted")
                                    : t("user_detail.bm_permissions.revoked")}
                                </span>
                              </label>
                            ) : (
                              <span
                                className={`cell-tag cell-tag-${overrideGranted ? "open" : "closed"}`}
                                data-testid={`${rowTestId}-override-readonly`}
                              >
                                <i />
                                {overrideGranted
                                  ? t("user_detail.bm_permissions.granted")
                                  : t("user_detail.bm_permissions.revoked")}
                              </span>
                            )}
                          </td>
                          <td>
                            {canEdit ? (
                              <div
                                className="card-actions-cluster"
                                style={{
                                  display: "flex",
                                  gap: 8,
                                  justifyContent: "flex-end",
                                }}
                              >
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-sm"
                                  onClick={() => resetBmDraft(building.id)}
                                  disabled={!dirty || busy}
                                  data-testid={`${rowTestId}-reset`}
                                >
                                  {t("user_detail.bm_permissions.reset")}
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-primary btn-sm"
                                  onClick={() => {
                                    void saveBmOverrides(building);
                                  }}
                                  disabled={!dirty || busy}
                                  data-testid={`${rowTestId}-save`}
                                >
                                  {busy
                                    ? t("user_detail.bm_permissions.saving")
                                    : t("user_detail.bm_permissions.save")}
                                </button>
                              </div>
                            ) : (
                              <span
                                className="muted small"
                                data-testid={`${rowTestId}-read-only-notice`}
                              >
                                {t(
                                  "user_detail.bm_permissions.read_only_notice",
                                )}
                              </span>
                            )}
                            {error && (
                              <div
                                className="alert-error"
                                role="alert"
                                style={{ marginTop: 6 }}
                                data-testid={`${rowTestId}-error`}
                              >
                                {t(
                                  "user_detail.bm_permissions.error_prefix",
                                  { detail: error },
                                )}
                              </div>
                            )}
                            {justSaved && !error && (
                              <div
                                className="muted small"
                                role="status"
                                style={{ marginTop: 6 }}
                                data-testid={`${rowTestId}-saved`}
                              >
                                {t("user_detail.bm_permissions.saved")}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* M2 P6 — read-only staff sections per the GLOBAL view-first
              rule: the detail page SHOWS staff profile, staff
              buildings, credentials and custom properties; editing
              stays on /edit. Each card fetches defensively and renders
              NOTHING on a 403/error (a BM viewer lacks the PA/SA-only
              credential endpoints — their page must not break). */}
          {user.role === "STAFF" && (
            <>
              <StaffProfileReadOnlyCard userId={user.id} />
              <StaffBuildingsReadOnlyCard userId={user.id} />
              <CredentialsReadOnlyCard userId={user.id} />
            </>
          )}
          <PropertiesReadOnlyCard userId={user.id} />

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
                {customers.map((c) => {
                  const isSummaryOpen = summaryCustomerId === c.id;
                  const accessList = accessByCustomerId[c.id] ?? [];
                  return (
                    <li
                      key={c.id}
                      className="user-detail-customer-access-row"
                      data-testid={`user-detail-customer-row-${c.id}`}
                    >
                      <div className="user-detail-customer-access-row-top">
                        <span className="user-detail-customer-access-name">
                          <Link to={`/admin/customers/${c.id}`}>{c.name}</Link>
                        </span>
                        <PermissionsRollupChip
                          customerId={c.id}
                          userId={user.id}
                          accesses={accessList}
                          testId={`user-detail-permissions-link-${c.id}`}
                          onToggle={() =>
                            setSummaryCustomerId((current) =>
                              current === c.id ? null : c.id,
                            )
                          }
                          expanded={isSummaryOpen}
                        />
                      </div>
                      {isSummaryOpen && (
                        <PermissionsRollupSummary
                          userId={user.id}
                          customerId={c.id}
                          userLabel={
                            user.full_name && user.full_name.trim().length > 0
                              ? user.full_name
                              : user.email
                          }
                          customerLabel={c.name}
                          accesses={accessList}
                          onOpenOverrides={(access) => {
                            navigate(
                              `/admin/customers/${c.id}/permissions?focus_user=${user.id}&focus_building=${access.building_id}`,
                            );
                          }}
                          onCollapse={() => setSummaryCustomerId(null)}
                        />
                      )}
                    </li>
                  );
                })}
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

// ---------------------------------------------------------------------------
// M2 P6 — read-only staff sections (GLOBAL view-first rule).
//
// Internal (non-exported) card components. Shared discipline:
//   * defensive fetch — a 403/error renders NOTHING for the section
//     (mirrors the 29.6 per-entity `.catch(() => null)` rule);
//   * async-IIFE effect with a cancelled flag, all setState behind the
//     await (never synchronously in the effect body);
//   * zero edit controls — editing lives on /admin/users/:id/edit.
// Labels reuse the existing `staff_admin.*` (common) and
// `staff_credentials` namespaces; only the yes/no value labels are new.
// ---------------------------------------------------------------------------

function StaffProfileReadOnlyCard({ userId }: { userId: number }) {
  const { t } = useTranslation("common");
  const { t: tCred } = useTranslation("staff_credentials");
  const [profile, setProfile] = useState<StaffProfileAdmin | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getStaffProfile(userId);
        if (!cancelled) setProfile(data);
      } catch {
        // 403 / error: render nothing for this section.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (profile === null) return null;
  const yesNo = (value: boolean) =>
    value ? tCred("detail.yes") : tCred("detail.no");
  return (
    <section
      className="card"
      data-testid="user-detail-staff-profile-card"
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">
            {t("staff_admin.profile_title")}
          </div>
          <div className="section-head-sub">{tCred("detail.read_only_hint")}</div>
        </div>
      </div>
      <div className="detail-field-row">
        <div className="detail-field-label">{t("staff_admin.field_phone")}</div>
        <div
          className={`detail-field-value${profile.phone ? "" : " muted-empty"}`}
        >
          {profile.phone || "—"}
        </div>
      </div>
      <div className="detail-field-row">
        <div className="detail-field-label">
          {t("staff_admin.field_internal_note")}
        </div>
        <div
          className={`detail-field-value${
            profile.internal_note ? "" : " muted-empty"
          }`}
          style={{ whiteSpace: "pre-wrap" }}
        >
          {profile.internal_note || "—"}
        </div>
      </div>
      <div className="detail-field-row">
        <div className="detail-field-label">
          {t("staff_admin.field_can_request_assignment")}
        </div>
        <div className="detail-field-value">
          {yesNo(profile.can_request_assignment)}
        </div>
      </div>
      <div className="detail-field-row">
        <div className="detail-field-label">
          {t("staff_admin.field_is_active")}
        </div>
        <div className="detail-field-value">
          {profile.is_active ? (
            <span className="cell-tag cell-tag-open">
              <i />
              {tCred("detail.yes")}
            </span>
          ) : (
            <span className="cell-tag cell-tag-closed">
              <i />
              {tCred("detail.no")}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

function StaffBuildingsReadOnlyCard({ userId }: { userId: number }) {
  const { t } = useTranslation("common");
  const { t: tCred } = useTranslation("staff_credentials");
  const [rows, setRows] = useState<BuildingStaffVisibilityAdmin[] | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await listStaffVisibility(userId);
        if (!cancelled) setRows(response.results);
      } catch {
        // 403 / error: render nothing for this section.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (rows === null) return null;
  return (
    <section
      className="card"
      data-testid="user-detail-staff-buildings-card"
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">
            {t("staff_admin.visibility_title")}
          </div>
          <div className="section-head-sub">{tCred("detail.read_only_hint")}</div>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="muted small" style={{ padding: "6px 0" }}>
          {t("staff_admin.visibility_no_rows")}
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((row) => (
            <li
              key={row.id}
              data-testid="user-detail-staff-building-row"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                borderTop: "1px solid var(--border)",
                padding: "8px 2px",
              }}
            >
              <span style={{ fontWeight: 600 }}>{row.building_name}</span>
              <span className="cell-tag cell-tag-open">
                <i />
                {t(`staff_admin.level.${row.visibility_level.toLowerCase()}`)}
              </span>
              {row.can_request_assignment && (
                <span className="muted small">
                  {t("staff_admin.visibility_can_request_label")}
                </span>
              )}
              {row.staff_completion_routes_to_customer && (
                <span className="muted small">
                  {t("staff_admin.routes_to_customer_label")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CredentialsReadOnlyCard({ userId }: { userId: number }) {
  const { t: tCred } = useTranslation("staff_credentials");
  const toast = useToast();
  const [rows, setRows] = useState<StaffCredential[] | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listCredentials(userId);
        if (!cancelled) setRows(data);
      } catch {
        // 403 / error (e.g. BM viewer): render nothing for this section.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (rows === null) return null;

  async function handleDownload(credential: StaffCredential) {
    setDownloadingId(credential.id);
    try {
      await downloadCredentialDocument(userId, credential);
    } catch (err) {
      toast.push({
        variant: "error",
        title: tCred("customer.download_failed"),
        description: getApiError(err),
      });
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <section
      className="card"
      data-testid="user-detail-credentials-card"
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">
            {tCred("section.credentials_title")}
          </div>
          <div className="section-head-sub">{tCred("detail.read_only_hint")}</div>
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          compact
          title={tCred("section.empty_credentials_title")}
          testId="user-detail-credentials-empty"
        />
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((credential) => (
            <li
              key={credential.id}
              data-testid="user-detail-credential-row"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                borderTop: "1px solid var(--border)",
                padding: "8px 2px",
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 140 }}>
                {tCred(`type.${credential.credential_type}`)}
              </span>
              <span className="cell-tag cell-tag-open">
                <i />
                {tCred(`visibility.${credential.visibility_level}`)}
              </span>
              {credential.permit_number && (
                <span className="muted small">{credential.permit_number}</span>
              )}
              <span className="muted small">
                {credential.expiry_date
                  ? tCred("summary.expires", { date: credential.expiry_date })
                  : tCred("summary.no_expiry")}
              </span>
              {credential.has_document && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={{ padding: "1px 6px", fontSize: 11 }}
                  onClick={() => {
                    void handleDownload(credential);
                  }}
                  disabled={downloadingId === credential.id}
                  data-testid="user-detail-credential-download"
                >
                  <Paperclip size={12} strokeWidth={2} />
                  {downloadingId === credential.id
                    ? tCred("field.downloading")
                    : tCred("field.download")}
                </button>
              )}
              {credential.grants.length > 0 && (
                <span
                  style={{
                    display: "inline-flex",
                    gap: 4,
                    flexWrap: "wrap",
                  }}
                >
                  {credential.grants.map((grant) => (
                    <span key={grant.id} className="cell-tag cell-tag-open">
                      {grant.customer_name}
                    </span>
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PropertiesReadOnlyCard({ userId }: { userId: number }) {
  const { t: tCred } = useTranslation("staff_credentials");
  const toast = useToast();
  const [rows, setRows] = useState<CustomProfileProperty[] | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listProperties(userId);
        if (!cancelled) setRows(data);
      } catch {
        // 403 / error: render nothing for this section.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (rows === null) return null;

  async function handleDownload(property: CustomProfileProperty) {
    setDownloadingId(property.id);
    try {
      await downloadPropertyDocument(userId, property);
    } catch (err) {
      toast.push({
        variant: "error",
        title: tCred("customer.download_failed"),
        description: getApiError(err),
      });
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <section
      className="card"
      data-testid="user-detail-properties-card"
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">
            {tCred("section.properties_title")}
          </div>
          <div className="section-head-sub">{tCred("detail.read_only_hint")}</div>
        </div>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          compact
          title={tCred("section.empty_properties_title")}
          testId="user-detail-properties-empty"
        />
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((property) => (
            <li
              key={property.id}
              data-testid="user-detail-property-row"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                borderTop: "1px solid var(--border)",
                padding: "8px 2px",
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 140 }}>
                {property.name}
              </span>
              <span className="cell-tag cell-tag-open">
                <i />
                {tCred(`visibility.${property.visibility_level}`)}
              </span>
              <span
                className="muted small"
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 260,
                }}
              >
                {property.value}
              </span>
              {property.has_document && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={{ padding: "1px 6px", fontSize: 11 }}
                  onClick={() => {
                    void handleDownload(property);
                  }}
                  disabled={downloadingId === property.id}
                  data-testid="user-detail-property-download"
                >
                  <Paperclip size={12} strokeWidth={2} />
                  {downloadingId === property.id
                    ? tCred("field.downloading")
                    : tCred("field.download")}
                </button>
              )}
              {property.grants.length > 0 && (
                <span
                  style={{
                    display: "inline-flex",
                    gap: 4,
                    flexWrap: "wrap",
                  }}
                >
                  {property.grants.map((grant) => (
                    <span key={grant.id} className="cell-tag cell-tag-open">
                      {grant.customer_name}
                    </span>
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


