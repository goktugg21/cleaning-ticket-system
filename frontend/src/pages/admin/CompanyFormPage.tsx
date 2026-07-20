import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  addCompanyAdmin,
  createCompany,
  getCompany,
  listCompanyAdmins,
  listUsers,
  removeCompanyAdmin,
  updateCompany,
} from "../../api/admin";
import type { CompanyWritePayload } from "../../api/admin";
import {
  COMPANY_POLICY_FLAGS,
  type CompanyAdmin,
  type CompanyAdminMembership,
  type CompanyPolicyFlag,
  type UserAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { ImageUploadField } from "../../components/ImageUploadField";
import { deleteCompanyLogo, uploadCompanyLogo } from "../../api/media";
import { useEntityForm } from "../../hooks/useEntityForm";
import { useSavedBanner } from "../../hooks/useSavedBanner";
import { Toggle } from "../../components/Toggle";

// Short i18n key alias per policy flag (keeps the common.json keys readable
// vs. the long backend field names).
const POLICY_KEY: Record<CompanyPolicyFlag, string> = {
  provider_admin_may_manage_customer_company_admins: "manage_cca",
  provider_admin_may_manage_catalog: "manage_catalog",
  provider_admin_may_manage_customer_prices: "manage_prices",
  provider_admin_may_quote_override_start: "quote_override",
};

export function CompanyFormPage() {
  const { id } = useParams();
  const isCreate = id === undefined;
  const { t, i18n } = useTranslation("common");

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
    saved: t("companies.banner_saved"),
  });

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [defaultLanguage, setDefaultLanguage] = useState("nl");
  // Provider-policy flags. SUPER_ADMIN-only writable: a COMPANY_ADMIN sees
  // them read-only and they are NEVER added to the PATCH payload for a
  // non-SA (the backend validate_* would 400 the whole save if they were).
  const [policy, setPolicy] = useState<Record<CompanyPolicyFlag, boolean>>({
    provider_admin_may_manage_customer_company_admins: false,
    provider_admin_may_manage_catalog: false,
    provider_admin_may_manage_customer_prices: false,
    provider_admin_may_quote_override_start: false,
  });

  const form = useEntityForm<CompanyAdmin, CompanyWritePayload>({
    id,
    fetchFn: getCompany,
    createFn: createCompany,
    updateFn: updateCompany,
    buildPayload: () => {
      const payload: CompanyWritePayload = {
        name: name.trim(),
        default_language: defaultLanguage,
      };
      if (isCreate) {
        if (slug.trim()) payload.slug = slug.trim();
      } else if (isSuperAdmin) {
        payload.slug = slug.trim();
      }
      // Provider-policy flags are SUPER_ADMIN-only writable. Include them
      // ONLY for a SA editing an existing company — a COMPANY_ADMIN must
      // never send them (the backend would 400 the whole PATCH).
      if (!isCreate && isSuperAdmin) {
        for (const flag of COMPANY_POLICY_FLAGS) {
          payload[flag] = policy[flag];
        }
      }
      return payload;
    },
    applyEntity: (entity) => {
      setName(entity.name);
      setSlug(entity.slug);
      setDefaultLanguage(entity.default_language);
      setPolicy({
        provider_admin_may_manage_customer_company_admins:
          entity.provider_admin_may_manage_customer_company_admins,
        provider_admin_may_manage_catalog:
          entity.provider_admin_may_manage_catalog,
        provider_admin_may_manage_customer_prices:
          entity.provider_admin_may_manage_customer_prices,
        provider_admin_may_quote_override_start:
          entity.provider_admin_may_quote_override_start,
      });
    },
    successPath: (entity) => `/admin/companies/${entity.id}?saved=ok`,
    onEditSuccess: () => setSavedBanner(t("companies.banner_saved")),
  });
  const company = form.entity;
  const numericId = form.numericId;

  // RF-1 — company logo (same override pattern as the customer form).
  const [logoOverride, setLogoOverride] = useState<string | null | undefined>(
    undefined,
  );
  const logoUrl =
    logoOverride !== undefined ? logoOverride : (company?.logo_url ?? null);
  // Show to SUPER_ADMIN or a COMPANY_ADMIN (backend checks membership).
  const canManageLogo =
    me?.role === "SUPER_ADMIN" || me?.role === "COMPANY_ADMIN";

  // Membership section state. Independent of the main form.
  const [members, setMembers] = useState<CompanyAdminMembership[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserAdmin[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");
  const [memberError, setMemberError] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<CompanyAdminMembership | null>(null);
  const removeDialogRef = useRef<ConfirmDialogHandle>(null);

  // The API enforces this too; UI gates it for clarity.
  const forbidden = isCreate && !isSuperAdmin;

  const slugReadOnly = useMemo(() => !isCreate && !isSuperAdmin, [isCreate, isSuperAdmin]);

  const reloadMembers = useMemo(
    () => async () => {
      if (numericId === null) return;
      try {
        const [membersResponse, candidatesResponse] = await Promise.all([
          listCompanyAdmins(numericId),
          listUsers({ role: "COMPANY_ADMIN", page_size: 200 }),
        ]);
        setMembers(membersResponse.results);
        const memberIds = new Set(membersResponse.results.map((m) => m.user_id));
        setAvailableUsers(
          candidatesResponse.results.filter((u) => !memberIds.has(u.id)),
        );
      } catch (err) {
        setMemberError(getApiError(err));
      }
    },
    [numericId],
  );

  useEffect(() => {
    if (isCreate || numericId === null) return;
    reloadMembers();
  }, [isCreate, numericId, reloadMembers]);

  async function handleAddMember(event: FormEvent) {
    event.preventDefault();
    if (numericId === null || selectedUserId === "") return;
    setMemberError("");
    setMemberBusy(true);
    try {
      await addCompanyAdmin(numericId, Number(selectedUserId));
      setSelectedUserId("");
      await reloadMembers();
    } catch (err) {
      setMemberError(getApiError(err));
    } finally {
      setMemberBusy(false);
    }
  }

  function openRemoveDialog(membership: CompanyAdminMembership) {
    setRemoveTarget(membership);
    removeDialogRef.current?.open();
  }

  async function handleConfirmRemove() {
    if (numericId === null || !removeTarget) return;
    setMemberBusy(true);
    setMemberError("");
    try {
      await removeCompanyAdmin(numericId, removeTarget.user_id);
      removeDialogRef.current?.close();
      setRemoveTarget(null);
      await reloadMembers();
    } catch (err) {
      setMemberError(getApiError(err));
      removeDialogRef.current?.close();
    } finally {
      setMemberBusy(false);
    }
  }

  if (forbidden) {
    return (
      <div>
        <Link to="/admin/companies" className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {t("company_form.back")}
        </Link>
        <div className="page-header">
          <div>
            <div className="eyebrow" style={{ marginBottom: 8 }}>
              {t("nav.admin_group")}
            </div>
            <h2 className="page-title">{t("company_form.forbidden_title")}</h2>
            <p className="page-sub">
              {t("company_form.forbidden_desc")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const companyName = company?.name ?? t("company_form.fallback");

  // Sprint 29 Batch 29.3 — back link points at the detail page when
  // editing (so Cancel and back land in the same place); the create
  // flow keeps the back-to-list shortcut.
  const backHref = isCreate || numericId === null
    ? "/admin/companies"
    : `/admin/companies/${numericId}`;
  const backLabel = isCreate
    ? t("company_form.back")
    : t("company_form.back_to_detail");

  return (
    <div>
      <Link to={backHref} className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {backLabel}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">
            {isCreate
              ? t("companies.create")
              : t("company_form.edit_title", { name: companyName })}
          </h2>
          {!isCreate && company && !company.is_active && (
            <p className="page-sub">
              <span className="cell-tag cell-tag-closed">
                <i />
                {t("admin.status_inactive")}
              </span>
            </p>
          )}
        </div>
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

      {form.loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <form className="card" onSubmit={form.handleSubmit}>
          {/* RF-1 — company logo (edit mode only; needs an existing id). */}
          {!isCreate && company && canManageLogo && (
            <div className="form-section">
              <div className="form-section-title">
                {t("company_form.logo_title")}
              </div>
              <ImageUploadField
                imageUrl={logoUrl}
                name={company.name}
                rounded={false}
                testId="company-logo-upload"
                onUpload={async (file) => {
                  const url = await uploadCompanyLogo(company.id, file);
                  setLogoOverride(url);
                }}
                onRemove={async () => {
                  await deleteCompanyLogo(company.id);
                  setLogoOverride(null);
                }}
              />
            </div>
          )}
          <div className="form-section">
            <div className="form-section-title">{t("company_form.card_label_title")}</div>
            <div className="form-section-helper">{t("company_form.card_label_desc")}</div>
          <div className="field">
            <label className="field-label" htmlFor="company-name">
              {t("admin.col_name")} *
            </label>
            <input
              id="company-name"
              className="field-input"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
            {form.fieldErrors.name && (
              <div className="alert-error login-error" role="alert">
                {form.fieldErrors.name}
              </div>
            )}
          </div>

          <div className="field">
            <label className="field-label" htmlFor="company-slug">
              {t("companies.col_slug")}
              {slugReadOnly && (
                <span className="muted small" style={{ marginLeft: 8 }}>
                  {t("company_form.slug_readonly_hint")}
                </span>
              )}
            </label>
            <input
              id="company-slug"
              className="field-input"
              type="text"
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
              readOnly={slugReadOnly}
              placeholder={isCreate ? t("company_form.slug_placeholder") : ""}
            />
            {form.fieldErrors.slug && (
              <div className="alert-error login-error" role="alert">
                {form.fieldErrors.slug}
              </div>
            )}
          </div>

          <div className="field">
            <label className="field-label" htmlFor="company-language">
              {t("companies.col_default_language")}
            </label>
            <select
              id="company-language"
              className="field-select"
              value={defaultLanguage}
              onChange={(event) => setDefaultLanguage(event.target.value)}
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {form.fieldErrors.default_language && (
              <div className="alert-error login-error" role="alert">
                {form.fieldErrors.default_language}
              </div>
            )}
          </div>

          </div>

          {/* Provider policy — SUPER_ADMIN-only writable grants. A
              COMPANY_ADMIN sees them read-only (disabled) and they are
              never added to the PATCH payload for a non-SA. */}
          {!isCreate && (
            <div className="form-section" data-testid="company-policy-section">
              <div className="form-section-title">
                {t("company_policy.section_title")}
              </div>
              <div className="form-section-helper">
                {t("company_policy.section_desc")}
              </div>
              {!isSuperAdmin && (
                <p
                  className="muted small"
                  style={{ marginBottom: 10 }}
                  data-testid="company-policy-readonly-hint"
                >
                  {t("company_policy.readonly_hint")}
                </p>
              )}
              <div className="settings-toggle-group">
                {COMPANY_POLICY_FLAGS.map((flag) => {
                  const dangerous =
                    flag === "provider_admin_may_quote_override_start";
                  const key = POLICY_KEY[flag];
                  return (
                    <div
                      key={flag}
                      className="field"
                      style={{ marginBottom: 8 }}
                    >
                      <label className="settings-toggle-row">
                        <Toggle
                          checked={policy[flag]}
                          disabled={!isSuperAdmin || form.submitting}
                          onChange={(event) =>
                            setPolicy((prev) => ({
                              ...prev,
                              [flag]: event.target.checked,
                            }))
                          }
                          data-testid={`company-policy-${flag}`}
                        />
                        <span>
                          {t(`company_policy.${key}_label`)}
                          {dangerous && (
                            <span
                              className="cell-tag cell-tag-rejected"
                              style={{ marginLeft: 8 }}
                              data-testid="company-policy-dangerous-badge"
                            >
                              <i />
                              {t("company_policy.dangerous_badge")}
                            </span>
                          )}
                        </span>
                      </label>
                      <p
                        className="muted small"
                        style={{
                          margin: "2px 0 0 30px",
                          ...(dangerous
                            ? { color: "var(--red-1, #b42318)" }
                            : {}),
                        }}
                      >
                        {t(`company_policy.${key}_helper`)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="form-actions">
            {!isCreate && numericId !== null && (
              <Link
                to={`/admin/companies/${numericId}`}
                className="btn btn-ghost"
                data-testid="company-edit-cancel"
              >
                {t("admin_form.cancel")}
              </Link>
            )}
            <button type="submit" className="btn btn-primary" disabled={form.submitting || !name.trim()}>
              {form.submitting
                ? t("admin_form.saving")
                : isCreate
                  ? t("companies.create")
                  : t("admin_form.save_changes")}
            </button>
          </div>
        </form>
      )}

      {!isCreate && company && (
        <section
          className="card"
          data-testid="section-admins"
          style={{ marginTop: 16, padding: "20px 22px" }}
        >
          <h3 className="section-title">{t("company_form.section_admins_title")}</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("company_form.section_admins_desc")}
          </p>

          {memberError && (
            <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
              {memberError}
            </div>
          )}

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("users.col_email")}</th>
                  <th>{t("users.col_full_name")}</th>
                  <th>{t("admin_form.col_added")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => (
                  <tr key={membership.id}>
                    <td className="td-subject">{membership.user_email}</td>
                    <td>{membership.user_full_name || "—"}</td>
                    <td className="td-date">
                      {new Date(membership.created_at).toLocaleDateString(dateLocale)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openRemoveDialog(membership)}
                      >
                        {t("admin_form.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {members.length === 0 && (
              <p className="muted small" style={{ padding: "12px 0" }}>
                {t("company_form.no_admins_yet")}
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddMember}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-company-admin">
                {t("company_form.add_admin")}
              </label>
              <select
                id="add-company-admin"
                className="field-select"
                value={selectedUserId === "" ? "" : String(selectedUserId)}
                onChange={(event) => {
                  const v = event.target.value;
                  setSelectedUserId(v === "" ? "" : Number(v));
                }}
                disabled={memberBusy || availableUsers.length === 0}
              >
                <option value="">
                  {availableUsers.length === 0
                    ? t("admin_form.no_eligible_users")
                    : t("admin_form.select_user")}
                </option>
                {availableUsers.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.email}
                    {user.full_name ? ` — ${user.full_name}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              data-testid="member-add-button"
              disabled={memberBusy || selectedUserId === ""}
            >
              {memberBusy ? t("admin_form.adding") : t("admin_form.add")}
            </button>
          </form>
        </section>
      )}

      <ConfirmDialog
        ref={removeDialogRef}
        title={t("company_form.dialog_remove_title", {
          email: removeTarget?.user_email ?? "",
          name: companyName,
        })}
        body={t("company_form.dialog_remove_body")}
        confirmLabel={t("admin_form.remove")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={memberBusy}
      />
    </div>
  );
}
