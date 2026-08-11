import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Users } from "lucide-react";

import { getApiError } from "../../api/client";
import {
  deactivateCompany,
  getCompany,
  getCompanySummary,
  listCompanyAdminPeople,
  reactivateCompany,
} from "../../api/admin";
import type {
  CompanyAdmin,
  CompanyAdminPerson,
  CompanySummary,
} from "../../api/types";
import { BoundedList } from "../../components/BoundedList";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { CompanyRelationCards } from "../../components/CompanyRelationCards";
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
  const { t } = useTranslation("common");

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
  // Sprint 156 §1 — the four relation lists and the tile counts. Each is
  // its OWN read with its own catch, so one unreadable block leaves the
  // rest of the page intact; that mirrors the server, which wraps each
  // summary block for the same reason.
  const [summary, setSummary] = useState<CompanySummary | null>(null);
  const [admins, setAdmins] = useState<CompanyAdminPerson[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // Sprint 163 §4 — the three relation cards' state, handlers and
  // dialogs moved to `components/CompanyRelationCards`, which owns
  // them for both this page and the company edit page.

  // The reload token went with the cards: they were its only writer,
  // and they now own their own. This page's reads happen once.

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
    // The company itself is the only read that may fail the page; every
    // other one degrades to an empty card or an em dash. A company whose
    // extra-work module cannot be read must still show its buildings.
    Promise.all([
      getCompany(numericId),
      getCompanySummary(numericId).catch(() => null),
      listCompanyAdminPeople(numericId).catch(() => []),
    ])
      .then(([companyData, summaryData, adminRows]) => {
        if (cancelled) return;
        setCompany(companyData);
        setSummary(summaryData);
        setAdmins(adminRows);
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

  // ---- Sprint 159 §4 — the three editable cards --------------------

  /** Every write here goes through one wrapper so the busy flag, the
   *  error surface and the re-read cannot drift apart between cards. */
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

            {/* Sprint 161 §2 — a compact TWO-COLUMN field grid, not
                nine full-width rows. Sprint 157 was right that the page
                under-displayed what its Edit changes, and every field it
                added stays; what changed here is only the layout, which
                had turned the About block into a 417px column of single
                lines and pushed the stat tiles and relation cards - the
                things that actually carry the page - below the fold. */}
            <div className="detail-field-grid">
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
            {/* Sprint 157 §4 — the four provider-policy switches and the
                logo. The Edit action already reached ALL of them: it
                opens `CompanyFormPage`, which edits name, slug, default
                language, logo and these four booleans, i.e. every
                writable field `Company` has. What was missing was the
                other half — the DETAIL page displayed four fields while
                the form edited nine, so the Edit looked thin because the
                page did not show what it changes.

                Showing them here also makes the switches discoverable:
                they govern what a provider ADMIN may do to a customer's
                company admins, catalog and prices, and they were
                previously invisible unless you opened the edit form. */}
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_policy.manage_cca_label")}
              </div>
              <div className="detail-field-value">
                {company.provider_admin_may_manage_customer_company_admins
                  ? t("admin.status_active")
                  : t("company_detail.policy_off")}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_policy.manage_catalog_label")}
              </div>
              <div className="detail-field-value">
                {company.provider_admin_may_manage_catalog
                  ? t("admin.status_active")
                  : t("company_detail.policy_off")}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_policy.manage_prices_label")}
              </div>
              <div className="detail-field-value">
                {company.provider_admin_may_manage_customer_prices
                  ? t("admin.status_active")
                  : t("company_detail.policy_off")}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_policy.quote_override_label")}
              </div>
              <div className="detail-field-value">
                {company.provider_admin_may_quote_override_start
                  ? t("admin.status_active")
                  : t("company_detail.policy_off")}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("company_detail.field_logo")}
              </div>
              <div className="detail-field-value">
                {company.logo_url ? (
                  <img
                    src={company.logo_url}
                    alt=""
                    style={{ maxHeight: 40, maxWidth: 160 }}
                    data-testid="company-detail-logo"
                  />
                ) : (
                  <span className="muted-empty">—</span>
                )}
              </div>
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
            </div>
          </section>

          {/* Sprint 156 §1 — the tiles. A null count renders an em
              dash, never a zero: the server returns null when a block is
              not answerable for this actor, and 0 would be the different
              and false claim that there are none. */}
          <div
            className="summary-grid summary-grid-chips"
            data-testid="company-detail-stats"
          >
            {[
              { key: "buildings", label: t("company_detail.stat_buildings"), value: summary?.building_count },
              { key: "customers", label: t("company_detail.stat_customers"), value: summary?.customer_count },
              { key: "admins", label: t("company_detail.stat_admins"), value: summary?.admin_count },
              { key: "employees", label: t("company_detail.stat_employees"), value: summary?.employee_count },
              { key: "open-tickets", label: t("company_detail.stat_open_tickets"), value: summary?.open_ticket_count },
              { key: "open-extra-work", label: t("company_detail.stat_open_extra_work"), value: summary?.open_extra_work_count },
            ].map((stat) => (
              <div
                className="summary-stat"
                key={stat.key}
                style={{ cursor: "default" }}
                data-testid={`company-detail-stat-${stat.key}`}
              >
                <span className="summary-stat-label">{stat.label}</span>
                <span className="summary-stat-value">
                  {stat.value === null || stat.value === undefined
                    ? "—"
                    : stat.value}
                </span>
              </div>
            ))}
          </div>

          {/* Company admins. E-mail AND phone, and the name reaches the
              person — the old card showed three columns of text with no
              way to open anybody (§7). */}
          <section
            className="card"
            data-testid="company-detail-admins-card"
            style={{ padding: "20px 22px", marginBottom: 16 }}
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

            <BoundedList
              size="md"
              count={admins.length}
              ariaLabel={t("company_detail.admins_title")}
              testIdPrefix="company-detail-admins"
              className="table-wrap"
              emptyState={
                <EmptyState
                  icon={Users}
                  title={t("company_detail.admins_empty")}
                  compact
                  testId="company-detail-admins-empty"
                />
              }
            >
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("users.col_full_name")}</th>
                    <th>{t("users.col_email")}</th>
                    <th>{t("customer_contacts.field_phone")}</th>
                  </tr>
                </thead>
                <tbody>
                  {admins.map((person) => (
                    <tr key={person.id}>
                      <td className="td-subject">
                        <Link to={`/admin/users/${person.id}`}>
                          {person.full_name || person.email}
                        </Link>
                      </td>
                      <td>
                        <a href={`mailto:${person.email}`}>{person.email}</a>
                      </td>
                      <td>
                        {person.phone ? (
                          <a href={`tel:${person.phone}`}>{person.phone}</a>
                        ) : (
                          <span className="muted-empty">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </BoundedList>
          </section>
          {/* Sprint 163 §4 — the three relation cards, extracted so
              the company EDIT page can carry them too. This page's
              rendered output is unchanged: the component owns the
              same fetches, the same three useEditMode controllers,
              the same dialogs and the same handlers it used to hold
              inline. */}
          <CompanyRelationCards companyId={company.id} />

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
