import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  addStaffVisibility,
  deactivateUser,
  getStaffProfile,
  getUser,
  listBuildings,
  listCompanies,
  listCustomers,
  listStaffVisibility,
  reactivateUser,
  removeStaffVisibility,
  updateStaffProfile,
  updateStaffVisibility,
  updateUser,
} from "../../api/admin";
import type {
  BuildingAdmin,
  BuildingStaffVisibilityAdmin,
  Role,
  StaffProfileAdmin,
  StaffVisibilityLevel,
  UserAdminDetail,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useEntityForm } from "../../hooks/useEntityForm";
import { useSavedBanner } from "../../hooks/useSavedBanner";

interface UserUpdatePayload {
  full_name: string;
  language: string;
  role: Role;
}

const ROLE_KEYS: Record<Role, string> = {
  SUPER_ADMIN: "common:roles.super_admin",
  COMPANY_ADMIN: "common:roles.company_admin",
  BUILDING_MANAGER: "common:roles.building_manager",
  STAFF: "common:roles.staff",
  CUSTOMER_USER: "common:roles.customer_user",
};

// Sprint 23B — STAFF deliberately left OUT of ALL_ROLES. STAFF users
// are created via the Sprint 23A `StaffProfile` admin path; the
// generic user form keeps its pre-23B options to avoid letting an
// operator type-promote an existing user into STAFF without also
// creating the matching profile and visibility rows. Display of an
// already-STAFF user still works because ROLE_KEYS covers it above.
const ALL_ROLES: Role[] = [
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "CUSTOMER_USER",
];

export function UserFormPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const { t } = useTranslation("common");

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const languageOptions = useMemo(
    () => [
      { value: "nl", label: `${t("language_dutch")} (nl)` },
      { value: "en", label: `${t("language_english")} (en)` },
    ],
    [t],
  );

  const [savedBanner, setSavedBanner] = useSavedBanner({
    saved: t("users.banner_saved"),
  });

  const [fullName, setFullName] = useState("");
  const [language, setLanguage] = useState("nl");
  const [role, setRole] = useState<Role>("CUSTOMER_USER");

  const [companyNames, setCompanyNames] = useState<string[]>([]);
  const [buildingNames, setBuildingNames] = useState<string[]>([]);
  const [customerNames, setCustomerNames] = useState<string[]>([]);

  const form = useEntityForm<UserAdminDetail, UserUpdatePayload>({
    id,
    fetchFn: getUser,
    updateFn: updateUser,
    buildPayload: () => ({
      full_name: fullName.trim(),
      language,
      role,
    }),
    applyEntity: (entity) => {
      setFullName(entity.full_name);
      setLanguage(entity.language);
      setRole(entity.role);
    },
    successPath: (entity) => `/admin/users/${entity.id}?saved=ok`,
    onEditSuccess: () => setSavedBanner(t("users.banner_saved")),
  });
  const user = form.entity;
  const numericId = form.numericId ?? Number.NaN;

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const isSelf = me?.id === numericId;
  const roleDisabled =
    isSelf ||
    // COMPANY_ADMIN cannot manage SUPER_ADMIN or COMPANY_ADMIN roles.
    (!isSuperAdmin && user?.role && (user.role === "SUPER_ADMIN" || user.role === "COMPANY_ADMIN"));

  // The set of role options the actor can pick. The API enforces this too;
  // the UI hides options the actor cannot pick so the user does not get a 400
  // by clicking. SUPER_ADMIN sees all four. COMPANY_ADMIN sees only the three
  // roles they can promote toward (excluding SUPER_ADMIN); COMPANY_ADMIN as a
  // target role is also excluded because demoting/promoting to COMPANY_ADMIN
  // is super-admin-only.
  const availableRoleOptions: Role[] = useMemo(() => {
    if (isSuperAdmin) return ALL_ROLES;
    return ["BUILDING_MANAGER", "CUSTOMER_USER"];
  }, [isSuperAdmin]);

  // Lazy-load membership names. Only fetch the lists the user actually has
  // memberships in. Each list call is bounded by page_size=200 so most
  // installs fit in one request.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    if (user.company_ids.length > 0) {
      listCompanies({ page_size: 200 })
        .then((response) => {
          if (cancelled) return;
          const names = response.results
            .filter((c) => user.company_ids.includes(c.id))
            .map((c) => c.name);
          setCompanyNames(names);
        })
        .catch(() => {
          if (!cancelled) setCompanyNames([]);
        });
    } else {
      setCompanyNames([]);
    }
    if (user.building_ids.length > 0) {
      listBuildings({ page_size: 200 })
        .then((response) => {
          if (cancelled) return;
          const names = response.results
            .filter((b) => user.building_ids.includes(b.id))
            .map((b) => b.name);
          setBuildingNames(names);
        })
        .catch(() => {
          if (!cancelled) setBuildingNames([]);
        });
    } else {
      setBuildingNames([]);
    }
    if (user.customer_ids.length > 0) {
      listCustomers({ page_size: 200 })
        .then((response) => {
          if (cancelled) return;
          const names = response.results
            .filter((c) => user.customer_ids.includes(c.id))
            .map((c) => c.name);
          setCustomerNames(names);
        })
        .catch(() => {
          if (!cancelled) setCustomerNames([]);
        });
    } else {
      setCustomerNames([]);
    }
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function handleConfirmDeactivate() {
    if (!user) return;
    setActionBusy(true);
    form.setGeneralError("");
    try {
      await deactivateUser(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/users?deactivated=ok", { replace: true });
    } catch (err) {
      form.setGeneralError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (!user) return;
    setActionBusy(true);
    form.setGeneralError("");
    try {
      await reactivateUser(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/users?reactivated=ok", { replace: true });
    } catch (err) {
      form.setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <div>
      <Link to="/admin/users" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("user_form.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{user?.email ?? t("roles.fallback")}</h2>
          <p className="page-sub" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="cell-tag cell-tag-open">
              <i />
              {t(ROLE_KEYS[role] ?? "common:roles.fallback")}
            </span>
            {user && !user.is_active && (
              <span className="cell-tag cell-tag-closed">
                <i />
                {t("admin.status_inactive")}
              </span>
            )}
            {isSelf && <span className="muted small">{t("user_form.this_is_you")}</span>}
          </p>
        </div>
        {user && !user.is_active && isSuperAdmin && (
          <div className="page-header-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid="reactivate-button"
              onClick={() => reactivateDialogRef.current?.open()}
            >
              {t("admin_form.reactivate")}
            </button>
          </div>
        )}
      </div>

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {form.generalError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {form.generalError}
        </div>
      )}

      {form.loading || !user ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <>
          <form className="card" onSubmit={form.handleSubmit}>
            <div className="form-section">
              <div className="form-section-title">{t("user_form.card_label_title")}</div>
              <div className="form-section-helper">{t("user_form.card_label_desc")}</div>
            <div className="field">
              <label className="field-label" htmlFor="user-email">
                {t("users.col_email")}
              </label>
              <input
                id="user-email"
                className="field-input"
                type="email"
                value={user.email}
                readOnly
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="user-full-name">
                {t("users.col_full_name")}
              </label>
              <input
                id="user-full-name"
                className="field-input"
                type="text"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
              />
              {form.fieldErrors.full_name && (
                <div className="alert-error login-error" role="alert">
                  {form.fieldErrors.full_name}
                </div>
              )}
            </div>

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="user-language">
                  {t("users.col_language")}
                </label>
                <select
                  id="user-language"
                  className="field-select"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                >
                  {languageOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="user-role">
                  {t("users.col_role")}
                  {roleDisabled && (
                    <span className="muted small" style={{ marginLeft: 8 }}>
                      {isSelf
                        ? t("user_form.role_disabled_self")
                        : t("user_form.role_disabled_actor")}
                    </span>
                  )}
                </label>
                <select
                  id="user-role"
                  className="field-select"
                  value={role}
                  onChange={(event) => setRole(event.target.value as Role)}
                  disabled={roleDisabled}
                >
                  {/* Always include the current role so a disabled select still shows it. */}
                  {!availableRoleOptions.includes(role) && (
                    <option value={role}>
                      {t(ROLE_KEYS[role] ?? "common:roles.fallback")}
                    </option>
                  )}
                  {availableRoleOptions.map((option) => (
                    <option key={option} value={option}>
                      {t(ROLE_KEYS[option])}
                    </option>
                  ))}
                </select>
                {form.fieldErrors.role && (
                  <div className="alert-error login-error" role="alert">
                    {form.fieldErrors.role}
                  </div>
                )}
                {/* Sprint 27E (closes G-F4) — make the absence of
                    STAFF in the dropdown intentional and discoverable
                    rather than confusing. Always shown so a SUPER_ADMIN
                    or COMPANY_ADMIN landing on a non-STAFF user has
                    the breadcrumb to the right surface. */}
                <p
                  className="muted small"
                  data-testid="user-form-staff-helper"
                  style={{ marginTop: 4 }}
                >
                  {t("user_form.role_staff_helper")}
                </p>
              </div>
            </div>

            </div>
            <div className="form-actions">
              {user.is_active && !isSelf && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  data-testid="deactivate-button"
                  onClick={() => deactivateDialogRef.current?.open()}
                >
                  {t("admin_form.deactivate")}
                </button>
              )}
              <button type="submit" className="btn btn-primary" disabled={form.submitting}>
                {form.submitting ? t("admin_form.saving") : t("admin_form.save_changes")}
              </button>
            </div>
          </form>

          {/* Sprint 24A — Staff details + building visibility editor.
              Only shown for STAFF users. SUPER_ADMIN sees it for any
              STAFF; COMPANY_ADMIN sees it for STAFF in their own
              company. BUILDING_MANAGER / STAFF / CUSTOMER_USER never
              reach this page (the Users admin route is gated). The
              section consumes its own endpoints
              (/api/users/<id>/staff-profile/ and
              /api/users/<id>/staff-visibility/) so the parent form's
              PATCH does not need a new field. */}
          {user.role === "STAFF" && (
            <StaffDetailsSection
              userId={numericId}
              userEmail={user.email}
              canEdit={!isSelf}
            />
          )}

          <section className="card" style={{ marginTop: 16, padding: "20px 22px" }}>
            <h3 className="section-title">{t("user_form.memberships_title")}</h3>
            <p className="muted small" style={{ marginBottom: 12 }}>
              {t("user_form.memberships_desc")}
            </p>
            {(() => {
              const companyIds = user.company_ids;
              const buildingIds = user.building_ids;
              const customerIds = user.customer_ids;
              return (
                <div className="detail-kv-list">
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("nav.companies")}</span>
                    <span className="detail-kv-val">
                      {companyIds.length === 0
                        ? "—"
                        : companyNames.length > 0
                          ? companyNames.join(", ")
                          : t("user_form.loading_names", { count: companyIds.length })}
                    </span>
                  </div>
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("nav.buildings")}</span>
                    <span className="detail-kv-val">
                      {buildingIds.length === 0
                        ? "—"
                        : buildingNames.length > 0
                          ? buildingNames.join(", ")
                          : t("user_form.loading_names", { count: buildingIds.length })}
                    </span>
                  </div>
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("nav.customers")}</span>
                    <span className="detail-kv-val">
                      {customerIds.length === 0
                        ? "—"
                        : customerNames.length > 0
                          ? customerNames.join(", ")
                          : t("user_form.loading_names", { count: customerIds.length })}
                    </span>
                  </div>
                </div>
              );
            })()}
          </section>
        </>
      )}

      <ConfirmDialog
        ref={deactivateDialogRef}
        title={t("user_form.dialog_deactivate_title", {
          email: user?.email ?? "",
        })}
        body={t("user_form.dialog_deactivate_body")}
        confirmLabel={t("admin_form.deactivate")}
        onConfirm={handleConfirmDeactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reactivateDialogRef}
        title={t("user_form.dialog_reactivate_title", {
          email: user?.email ?? "",
        })}
        body={t("user_form.dialog_reactivate_body")}
        confirmLabel={t("admin_form.reactivate")}
        onConfirm={handleConfirmReactivate}
        busy={actionBusy}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sprint 24A — Staff details + building visibility editor.
//
// Embedded in UserFormPage when the target user has role=STAFF. Owns
// two GET/PATCH cycles (profile + visibility list) plus building
// add/remove. Backend permissions:
//
//   - StaffProfileView                 : SUPER_ADMIN / COMPANY_ADMIN
//                                        of the staff user's company
//   - BuildingStaffVisibilityViews     : same gate
//
// Cross-company COMPANY_ADMIN attempts are rejected by the backend
// before any state mutates; we surface the error inline rather than
// guess at the actor's company in the frontend.
//
// Mobile note: the visibility editor renders cards/list at <=600px
// via the existing `.admin-card-list` / `.admin-list-wrap` swap
// (Sprint 22 pattern). The widest control is a per-row select +
// remove button stacked vertically on phones.
// ---------------------------------------------------------------------------

interface StaffDetailsSectionProps {
  userId: number;
  userEmail: string;
  canEdit: boolean;
}

function StaffDetailsSection({
  userId,
  userEmail,
  canEdit,
}: StaffDetailsSectionProps) {
  const { t } = useTranslation("common");

  const [profile, setProfile] = useState<StaffProfileAdmin | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState("");
  const [profileBanner, setProfileBanner] = useSavedBanner({
    saved: t("staff_admin.banner_profile_saved"),
  });
  const [phone, setPhone] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [canRequestAssignment, setCanRequestAssignment] = useState(true);
  const [isActive, setIsActive] = useState(true);
  const [profileSaving, setProfileSaving] = useState(false);

  const [visibility, setVisibility] = useState<BuildingStaffVisibilityAdmin[]>(
    [],
  );
  const [visibilityLoading, setVisibilityLoading] = useState(true);
  const [visibilityError, setVisibilityError] = useState("");
  const [visibilityBanner, setVisibilityBanner] = useSavedBanner({
    saved: t("staff_admin.banner_visibility_saved"),
  });
  const [allBuildings, setAllBuildings] = useState<BuildingAdmin[]>([]);
  const [selectedBuildingToAdd, setSelectedBuildingToAdd] = useState<
    number | ""
  >("");
  const [visibilityBusyKey, setVisibilityBusyKey] = useState<string | null>(
    null,
  );

  const [removeTarget, setRemoveTarget] =
    useState<BuildingStaffVisibilityAdmin | null>(null);
  const removeDialogRef = useRef<ConfirmDialogHandle>(null);

  // Profile load.
  useEffect(() => {
    let cancelled = false;
    setProfileLoading(true);
    getStaffProfile(userId)
      .then((data) => {
        if (cancelled) return;
        setProfile(data);
        setPhone(data.phone ?? "");
        setInternalNote(data.internal_note ?? "");
        setCanRequestAssignment(data.can_request_assignment);
        setIsActive(data.is_active);
        setProfileError("");
      })
      .catch((err) => {
        if (!cancelled) setProfileError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setProfileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  // Visibility list load.
  const reloadVisibility = useCallback(async () => {
    setVisibilityLoading(true);
    try {
      const response = await listStaffVisibility(userId);
      setVisibility(response.results);
      setVisibilityError("");
    } catch (err) {
      setVisibilityError(getApiError(err));
    } finally {
      setVisibilityLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    reloadVisibility();
  }, [reloadVisibility]);

  // Pre-fetch the candidate building list once so the add-control can
  // render synchronously. `is_active=true` filter mirrors what every
  // other admin add-list uses; the backend additionally enforces the
  // same-company guard so a COMPANY_ADMIN cannot grant cross-company
  // visibility by tampering with the dropdown.
  useEffect(() => {
    let cancelled = false;
    listBuildings({ is_active: "true", page_size: 200 })
      .then((response) => {
        if (!cancelled) setAllBuildings(response.results);
      })
      .catch(() => {
        if (!cancelled) setAllBuildings([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const grantedBuildingIds = useMemo(
    () => new Set(visibility.map((v) => v.building_id)),
    [visibility],
  );
  const grantableBuildings = useMemo(
    () => allBuildings.filter((b) => !grantedBuildingIds.has(b.id)),
    [allBuildings, grantedBuildingIds],
  );

  async function handleProfileSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canEdit) return;
    setProfileSaving(true);
    setProfileError("");
    try {
      const updated = await updateStaffProfile(userId, {
        phone: phone.trim(),
        internal_note: internalNote,
        can_request_assignment: canRequestAssignment,
        is_active: isActive,
      });
      setProfile(updated);
      setProfileBanner(t("staff_admin.banner_profile_saved"));
    } catch (err) {
      setProfileError(getApiError(err));
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleAddVisibility(event: FormEvent) {
    event.preventDefault();
    if (selectedBuildingToAdd === "") return;
    const buildingId = Number(selectedBuildingToAdd);
    setVisibilityBusyKey(`add-${buildingId}`);
    setVisibilityError("");
    try {
      await addStaffVisibility(userId, buildingId);
      setSelectedBuildingToAdd("");
      await reloadVisibility();
      setVisibilityBanner(t("staff_admin.banner_visibility_saved"));
    } catch (err) {
      setVisibilityError(getApiError(err));
    } finally {
      setVisibilityBusyKey(null);
    }
  }

  async function handleToggleCanRequest(
    row: BuildingStaffVisibilityAdmin,
    next: boolean,
  ) {
    setVisibilityBusyKey(`toggle-${row.building_id}`);
    setVisibilityError("");
    try {
      await updateStaffVisibility(userId, row.building_id, {
        can_request_assignment: next,
      });
      await reloadVisibility();
      setVisibilityBanner(t("staff_admin.banner_visibility_saved"));
    } catch (err) {
      setVisibilityError(getApiError(err));
    } finally {
      setVisibilityBusyKey(null);
    }
  }

  // Sprint 28 Batch 10 — visibility-level write surface. Uses the same
  // PATCH endpoint as the can-request toggle; the backend accepts
  // `visibility_level` alongside the existing `can_request_assignment`
  // field. We send only the level so unrelated rows / concurrent edits
  // on the can-request flag are not clobbered.
  async function handleChangeVisibilityLevel(
    row: BuildingStaffVisibilityAdmin,
    next: StaffVisibilityLevel,
  ) {
    setVisibilityBusyKey(`level-${row.building_id}`);
    setVisibilityError("");
    try {
      await updateStaffVisibility(userId, row.building_id, {
        visibility_level: next,
      });
      await reloadVisibility();
      setVisibilityBanner(t("staff_admin.banner_visibility_saved"));
    } catch (err) {
      setVisibilityError(getApiError(err));
    } finally {
      setVisibilityBusyKey(null);
    }
  }

  function openRemoveDialog(row: BuildingStaffVisibilityAdmin) {
    setRemoveTarget(row);
    removeDialogRef.current?.open();
  }

  async function handleConfirmRemove() {
    if (!removeTarget) return;
    setVisibilityBusyKey(`remove-${removeTarget.building_id}`);
    setVisibilityError("");
    try {
      await removeStaffVisibility(userId, removeTarget.building_id);
      removeDialogRef.current?.close();
      setRemoveTarget(null);
      await reloadVisibility();
      setVisibilityBanner(t("staff_admin.banner_visibility_saved"));
    } catch (err) {
      setVisibilityError(getApiError(err));
      removeDialogRef.current?.close();
    } finally {
      setVisibilityBusyKey(null);
    }
  }

  return (
    <section
      aria-label={t("staff_admin.aria_section")}
      data-testid="staff-details-section"
    >
      {/* ---------- Staff profile card ---------- */}
      <form
        className="card"
        style={{ marginTop: 16, padding: "20px 22px" }}
        onSubmit={handleProfileSubmit}
        data-testid="staff-profile-form"
      >
        <h3 className="section-title">{t("staff_admin.profile_title")}</h3>
        <p className="muted small" style={{ marginBottom: 12 }}>
          {t("staff_admin.profile_desc")}
        </p>

        {profileBanner && (
          <div className="alert-info" role="status" style={{ marginBottom: 12 }}>
            {profileBanner}
          </div>
        )}
        {profileError && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {profileError}
          </div>
        )}

        {profileLoading || !profile ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : (
          <>
            <div className="field">
              <label className="field-label" htmlFor="staff-phone">
                {t("staff_admin.field_phone")}
              </label>
              <input
                id="staff-phone"
                className="field-input"
                type="tel"
                value={phone}
                placeholder={t("staff_admin.field_phone_placeholder")}
                onChange={(event) => setPhone(event.target.value)}
                disabled={!canEdit || profileSaving}
                data-testid="staff-phone-input"
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="staff-internal-note">
                {t("staff_admin.field_internal_note")}
              </label>
              <textarea
                id="staff-internal-note"
                className="field-input"
                rows={3}
                value={internalNote}
                placeholder={t("staff_admin.field_internal_note_placeholder")}
                onChange={(event) => setInternalNote(event.target.value)}
                disabled={!canEdit || profileSaving}
                data-testid="staff-internal-note-input"
                style={{ resize: "vertical" }}
              />
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: canEdit ? "pointer" : "default",
                }}
              >
                <input
                  type="checkbox"
                  checked={canRequestAssignment}
                  onChange={(event) =>
                    setCanRequestAssignment(event.target.checked)
                  }
                  disabled={!canEdit || profileSaving}
                  data-testid="staff-can-request-checkbox"
                />
                <span>{t("staff_admin.field_can_request_assignment")}</span>
              </label>
              <p className="muted small" style={{ marginTop: 4 }}>
                {t("staff_admin.field_can_request_assignment_hint")}
              </p>
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: canEdit ? "pointer" : "default",
                }}
              >
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(event) => setIsActive(event.target.checked)}
                  disabled={!canEdit || profileSaving}
                  data-testid="staff-profile-active-checkbox"
                />
                <span>{t("staff_admin.field_is_active")}</span>
              </label>
              <p className="muted small" style={{ marginTop: 4 }}>
                {t("staff_admin.field_is_active_hint")}
              </p>
            </div>
            <div className="form-actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!canEdit || profileSaving}
                data-testid="staff-profile-save"
              >
                {profileSaving
                  ? t("admin_form.saving")
                  : t("admin_form.save_changes")}
              </button>
            </div>
          </>
        )}
      </form>

      {/* ---------- Building visibility card ---------- */}
      <section
        className="card"
        style={{ marginTop: 16, padding: "20px 22px" }}
        data-testid="staff-visibility-section"
      >
        <h3 className="section-title">{t("staff_admin.visibility_title")}</h3>
        <p className="muted small" style={{ marginBottom: 12 }}>
          {t("staff_admin.visibility_desc")}
        </p>

        {visibilityBanner && (
          <div className="alert-info" role="status" style={{ marginBottom: 12 }}>
            {visibilityBanner}
          </div>
        )}
        {visibilityError && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {visibilityError}
          </div>
        )}

        {visibilityLoading ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : visibility.length === 0 ? (
          <p className="muted small" style={{ padding: "12px 0" }}>
            {t("staff_admin.visibility_no_rows")}
          </p>
        ) : (
          <>
            {/* Desktop table — Sprint 22 pattern: hidden at <=600px in
                index.css so the mobile card list below takes over. */}
            <div className="table-wrap admin-list-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("staff_admin.col_building")}</th>
                    <th>{t("staff_admin.level_label")}</th>
                    <th>{t("staff_admin.col_can_request")}</th>
                    <th aria-label={t("staff_admin.col_actions")} />
                  </tr>
                </thead>
                <tbody>
                  {visibility.map((row) => {
                    const toggleBusy =
                      visibilityBusyKey === `toggle-${row.building_id}`;
                    const levelBusy =
                      visibilityBusyKey === `level-${row.building_id}`;
                    const removeBusy =
                      visibilityBusyKey === `remove-${row.building_id}`;
                    return (
                      <tr
                        key={row.id}
                        data-testid="staff-visibility-row"
                        data-building-id={row.building_id}
                      >
                        <td className="td-subject">{row.building_name}</td>
                        <td>
                          <select
                            className="field-select"
                            value={row.visibility_level}
                            onChange={(event) =>
                              handleChangeVisibilityLevel(
                                row,
                                event.target.value as StaffVisibilityLevel,
                              )
                            }
                            disabled={!canEdit || levelBusy}
                            aria-label={t("staff_admin.level_label")}
                            data-testid={`staff-visibility-level-select-${row.building_id}`}
                          >
                            <option value="ASSIGNED_ONLY">
                              {t("staff_admin.level.assigned_only")}
                            </option>
                            <option value="BUILDING_READ">
                              {t("staff_admin.level.building_read")}
                            </option>
                            <option value="BUILDING_READ_AND_ASSIGN">
                              {t(
                                "staff_admin.level.building_read_and_assign",
                              )}
                            </option>
                          </select>
                        </td>
                        <td>
                          <label
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 6,
                              cursor: canEdit ? "pointer" : "default",
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={row.can_request_assignment}
                              onChange={(event) =>
                                handleToggleCanRequest(
                                  row,
                                  event.target.checked,
                                )
                              }
                              disabled={!canEdit || toggleBusy}
                              data-testid="staff-visibility-can-request"
                            />
                            <span className="muted small">
                              {t(
                                "staff_admin.visibility_can_request_label",
                              )}
                            </span>
                          </label>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => openRemoveDialog(row)}
                            disabled={!canEdit || removeBusy}
                            data-testid="staff-visibility-remove"
                          >
                            {t("staff_admin.visibility_remove_button")}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile parallel — phone-class viewports show this list
                instead of the desktop table. Sprint 22 pattern. */}
            <ul
              className="admin-card-list"
              data-testid="staff-visibility-card-list"
              aria-label={t("staff_admin.visibility_title")}
            >
              {visibility.map((row) => {
                const toggleBusy =
                  visibilityBusyKey === `toggle-${row.building_id}`;
                const levelBusy =
                  visibilityBusyKey === `level-${row.building_id}`;
                const removeBusy =
                  visibilityBusyKey === `remove-${row.building_id}`;
                return (
                  <li
                    key={row.id}
                    className="admin-card"
                    data-testid="staff-visibility-card"
                    data-building-id={row.building_id}
                  >
                    <div
                      className="admin-card-link"
                      style={{ cursor: "default" }}
                    >
                      <div className="admin-card-head">
                        <span className="admin-card-title">
                          {row.building_name}
                        </span>
                      </div>
                      <div
                        className="admin-card-meta-row"
                        style={{ marginTop: 6 }}
                      >
                        <label
                          className="field-label"
                          style={{ display: "block", marginBottom: 4 }}
                        >
                          {t("staff_admin.level_label")}
                        </label>
                        <select
                          className="field-select"
                          value={row.visibility_level}
                          onChange={(event) =>
                            handleChangeVisibilityLevel(
                              row,
                              event.target.value as StaffVisibilityLevel,
                            )
                          }
                          disabled={!canEdit || levelBusy}
                          aria-label={t("staff_admin.level_label")}
                          data-testid={`staff-visibility-level-select-mobile-${row.building_id}`}
                        >
                          <option value="ASSIGNED_ONLY">
                            {t("staff_admin.level.assigned_only")}
                          </option>
                          <option value="BUILDING_READ">
                            {t("staff_admin.level.building_read")}
                          </option>
                          <option value="BUILDING_READ_AND_ASSIGN">
                            {t(
                              "staff_admin.level.building_read_and_assign",
                            )}
                          </option>
                        </select>
                      </div>
                      <div
                        className="admin-card-meta-row"
                        style={{ marginTop: 6 }}
                      >
                        <label
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            cursor: canEdit ? "pointer" : "default",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={row.can_request_assignment}
                            onChange={(event) =>
                              handleToggleCanRequest(
                                row,
                                event.target.checked,
                              )
                            }
                            disabled={!canEdit || toggleBusy}
                            data-testid="staff-visibility-can-request-mobile"
                          />
                          <span className="muted small">
                            {t("staff_admin.visibility_can_request_label")}
                          </span>
                        </label>
                      </div>
                      <div
                        className="admin-card-actions"
                        style={{ display: "flex", gap: 6, marginTop: 8 }}
                      >
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => openRemoveDialog(row)}
                          disabled={!canEdit || removeBusy}
                          data-testid="staff-visibility-remove-mobile"
                        >
                          {t("staff_admin.visibility_remove_button")}
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}

        {/* Add row */}
        {canEdit && (
          <form
            onSubmit={handleAddVisibility}
            style={{
              display: "flex",
              gap: 8,
              marginTop: 12,
              alignItems: "flex-end",
              flexWrap: "wrap",
            }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0, minWidth: 0 }}>
              <label className="field-label" htmlFor="staff-visibility-add">
                {t("staff_admin.visibility_add")}
              </label>
              <select
                id="staff-visibility-add"
                className="field-select"
                value={
                  selectedBuildingToAdd === ""
                    ? ""
                    : String(selectedBuildingToAdd)
                }
                onChange={(event) => {
                  const v = event.target.value;
                  setSelectedBuildingToAdd(v === "" ? "" : Number(v));
                }}
                disabled={
                  visibilityBusyKey !== null ||
                  grantableBuildings.length === 0
                }
                data-testid="staff-visibility-add-select"
              >
                <option value="">
                  {grantableBuildings.length === 0
                    ? t("staff_admin.visibility_no_more")
                    : t("staff_admin.visibility_select_placeholder")}
                </option>
                {grantableBuildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={
                visibilityBusyKey !== null || selectedBuildingToAdd === ""
              }
              data-testid="staff-visibility-add-button"
            >
              {visibilityBusyKey?.startsWith("add-")
                ? t("admin_form.adding")
                : t("admin_form.add")}
            </button>
          </form>
        )}
      </section>

      <ConfirmDialog
        ref={removeDialogRef}
        title={t("staff_admin.dialog_remove_title", {
          building: removeTarget?.building_name ?? "",
        })}
        body={t("staff_admin.dialog_remove_body", {
          email: userEmail,
        })}
        confirmLabel={t("staff_admin.visibility_remove_button")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={visibilityBusyKey !== null}
        destructive
      />
    </section>
  );
}
