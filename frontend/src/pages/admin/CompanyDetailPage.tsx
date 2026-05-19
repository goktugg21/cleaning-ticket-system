import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Users } from "lucide-react";

import { getApiError } from "../../api/client";
import {
  deactivateCompany,
  getCompany,
  listCompanyAdmins,
  reactivateCompany,
} from "../../api/admin";
import type {
  CompanyAdmin,
  CompanyAdminMembership,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { useSavedBanner } from "../../hooks/useSavedBanner";

/**
 * Sprint 29 Batch 29.3 — Company Detail page (read-only view).
 *
 * View-first per the 2026-05-15 stakeholder doc §3. `/admin/companies/:id`
 * loads this page in read-only mode; an explicit role-gated Edit button
 * (top right) navigates to `/admin/companies/:id/edit` which renders
 * the legacy `CompanyFormPage` form. SUPER_ADMIN may also Deactivate /
 * Reactivate from this page — those affordances moved verbatim from the
 * form page so the read-only surface still carries the lifecycle
 * actions an admin expects.
 *
 * The page intentionally does NOT mutate company fields or admin
 * memberships — those affordances live on the edit form.
 */
export function CompanyDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const { t, i18n } = useTranslation("common");

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [savedBanner] = useSavedBanner({
    saved: t("companies.banner_saved"),
  });

  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [members, setMembers] = useState<CompanyAdminMembership[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setError(t("company_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    Promise.all([
      getCompany(numericId),
      listCompanyAdmins(numericId).catch(() => ({
        count: 0,
        next: null,
        previous: null,
        results: [] as CompanyAdminMembership[],
      })),
    ])
      .then(([companyData, membersResponse]) => {
        if (cancelled) return;
        setCompany(companyData);
        setMembers(membersResponse.results);
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
      await deactivateCompany(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/companies?deactivated=ok", { replace: true });
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
      await reactivateCompany(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/companies?reactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  // SUPER_ADMIN always; COMPANY_ADMIN only if this company is in their
  // membership set. The backend enforces this independently; the UI
  // gate is defence in depth and keeps the affordance honest.
  const canEdit =
    me?.role === "SUPER_ADMIN" ||
    (me?.role === "COMPANY_ADMIN" &&
      company !== null &&
      me.company_ids.includes(company.id));

  const companyName = company?.name ?? t("company_form.fallback");
  const isActive = company?.is_active ?? true;

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const languageLabel = (() => {
    if (!company) return "";
    if (company.default_language === "nl") {
      return `${t("language_dutch")} (nl)`;
    }
    if (company.default_language === "en") {
      return `${t("language_english")} (en)`;
    }
    return company.default_language;
  })();

  const headerActions = company ? (
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
      {isActive && isSuperAdmin && (
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
          to={`/admin/companies/${company.id}/edit`}
          className="btn btn-primary btn-sm"
          data-testid="company-edit-link"
        >
          {t("company_detail.edit_button")}
        </Link>
      )}
    </>
  ) : null;

  return (
    <div data-testid="company-detail-page">
      <PageHeader
        backLink={{
          to: "/admin/companies",
          label: t("company_form.back"),
        }}
        eyebrow={t("nav.admin_group")}
        title={companyName}
        statusPill={
          !isActive ? (
            <span className="cell-tag cell-tag-closed">
              <i />
              {t("company_detail.status_inactive")}
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

      {loading && !company ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : company ? (
        <>
          <section
            className="card"
            data-testid="company-detail-about-card"
            style={{ padding: "20px 22px", marginBottom: 16 }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">
                  {t("company_detail.about_title")}
                </div>
                <div className="section-head-sub">
                  {t("company_detail.about_desc")}
                </div>
              </div>
            </div>

            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_detail.field_name")}
              </div>
              <div className="detail-field-value">{company.name}</div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_detail.field_slug")}
              </div>
              <div className="detail-field-value">{company.slug}</div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_detail.field_default_language")}
              </div>
              <div className="detail-field-value">{languageLabel}</div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_detail.field_status")}
              </div>
              <div className="detail-field-value">
                {isActive ? (
                  <span className="cell-tag cell-tag-open">
                    <i />
                    {t("company_detail.status_active")}
                  </span>
                ) : (
                  <span className="cell-tag cell-tag-closed">
                    <i />
                    {t("company_detail.status_inactive")}
                  </span>
                )}
              </div>
            </div>
          </section>

          <section
            className="card"
            data-testid="company-detail-admins-card"
            style={{ padding: "20px 22px" }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">
                  {t("company_detail.admins_title")}
                </div>
                <div className="section-head-sub">
                  {t("company_detail.admins_desc")}
                </div>
              </div>
            </div>

            {members.length === 0 ? (
              <EmptyState
                icon={Users}
                title={t("company_detail.admins_empty")}
                compact
                testId="company-detail-admins-empty"
              />
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("users.col_email")}</th>
                      <th>{t("users.col_full_name")}</th>
                      <th>{t("admin_form.col_added")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((membership) => (
                      <tr key={membership.id}>
                        <td className="td-subject">{membership.user_email}</td>
                        <td>{membership.user_full_name || "—"}</td>
                        <td className="td-date">
                          {new Date(
                            membership.created_at,
                          ).toLocaleDateString(dateLocale)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <ConfirmDialog
            ref={deactivateDialogRef}
            title={t("company_form.dialog_deactivate_title", {
              name: companyName,
            })}
            body={t("company_form.dialog_deactivate_body")}
            confirmLabel={t("admin_form.deactivate")}
            onConfirm={handleConfirmDeactivate}
            busy={actionBusy}
          />

          <ConfirmDialog
            ref={reactivateDialogRef}
            title={t("company_form.dialog_reactivate_title", {
              name: companyName,
            })}
            body={t("company_form.dialog_reactivate_body")}
            confirmLabel={t("admin_form.reactivate")}
            onConfirm={handleConfirmReactivate}
            busy={actionBusy}
          />
        </>
      ) : null}
    </div>
  );
}
