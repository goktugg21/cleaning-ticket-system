import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  addCompanyAdmin,
  createCompany,
  deactivateCompany,
  getCompany,
  listCompanyAdmins,
  listUsers,
  reactivateCompany,
  removeCompanyAdmin,
  updateCompany,
} from "../../api/admin";
import type { CompanyWritePayload } from "../../api/admin";
import type {
  CompanyAdmin,
  CompanyAdminMembership,
  UserAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useEntityForm } from "../../hooks/useEntityForm";
import { useSavedBanner } from "../../hooks/useSavedBanner";

export function CompanyFormPage() {
  const navigate = useNavigate();
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
      return payload;
    },
    applyEntity: (entity) => {
      setName(entity.name);
      setSlug(entity.slug);
      setDefaultLanguage(entity.default_language);
    },
    successPath: (entity) => `/admin/companies/${entity.id}?saved=ok`,
    onEditSuccess: () => setSavedBanner(t("companies.banner_saved")),
  });
  const company = form.entity;
  const numericId = form.numericId;

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

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

  async function handleConfirmDeactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    form.setGeneralError("");
    try {
      await deactivateCompany(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/companies?deactivated=ok", { replace: true });
    } catch (err) {
      form.setGeneralError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    form.setGeneralError("");
    try {
      await reactivateCompany(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/companies?reactivated=ok", { replace: true });
    } catch (err) {
      form.setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const companyName = company?.name ?? t("company_form.fallback");

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
        {!isCreate && company && !company.is_active && isSuperAdmin && (
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

      {form.loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <form className="card" onSubmit={form.handleSubmit}>
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
          <div className="form-actions">
            {!isCreate && company && company.is_active && (
              <button
                type="button"
                className="btn btn-ghost"
                data-testid="deactivate-button"
                onClick={() => deactivateDialogRef.current?.open()}
              >
                {t("admin_form.deactivate")}
              </button>
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
        ref={deactivateDialogRef}
        title={t("company_form.dialog_deactivate_title", { name: companyName })}
        body={t("company_form.dialog_deactivate_body")}
        confirmLabel={t("admin_form.deactivate")}
        onConfirm={handleConfirmDeactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reactivateDialogRef}
        title={t("company_form.dialog_reactivate_title", { name: companyName })}
        body={t("company_form.dialog_reactivate_body")}
        confirmLabel={t("admin_form.reactivate")}
        onConfirm={handleConfirmReactivate}
        busy={actionBusy}
      />

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
