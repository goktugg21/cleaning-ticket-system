import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  deactivateUser,
  getUser,
  listBuildings,
  listCompanies,
  listCustomers,
  reactivateUser,
  updateUser,
} from "../../api/admin";
import type { Role, UserAdminDetail } from "../../api/types";
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
  CUSTOMER_USER: "common:roles.customer_user",
};

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
