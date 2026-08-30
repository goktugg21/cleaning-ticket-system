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
import type { CompanyAdmin, CompanyAdminPerson, CompanySummary, CompanyPolicyFlag } from "../../api/types";
import { BoundedList } from "../../components/BoundedList";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { COMPANY_POLICY_FLAGS } from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import { Toggle } from "../../components/Toggle";
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
const POLICY_KEY: Record<CompanyPolicyFlag, string> = {
  provider_admin_may_manage_customer_company_admins: "manage_cca",
  provider_admin_may_manage_catalog: "manage_catalog",
  provider_admin_may_manage_customer_prices: "manage_prices",
  provider_admin_may_quote_override_start: "quote_override",
};

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
  // P-4 (Part F) — starts TRUE: the first paint is "loading", never a
  // blank canvas under the title (the void the owner reported).
  const [loading, setLoading] = useState(true);
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

  const policyRows = COMPANY_POLICY_FLAGS.map((flag) => ({
    flag,
    key: POLICY_KEY[flag],
    on: company ? company[flag] : false,
    dangerous: flag === "provider_admin_may_quote_override_start",
  }));

  const count = (value: number | null | undefined) =>
    value === null || value === undefined ? null : value;

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
      ) : !company ? (
        /* P-4 (Part F) — NEVER A VOID. A company that could not be read
           says so in words, with the way back. */
        <section className="card" role="status" data-testid="company-detail-unavailable" style={{ padding: 22 }}>
          <div className="section-head-title">{t("company_detail.unavailable_title")}</div>
          <p className="muted" style={{ marginTop: 6 }}>
            {error || t("company_detail.unavailable_body")}
          </p>
          <Link to="/admin/companies" className="btn btn-secondary btn-sm" style={{ marginTop: 10 }}>
            {t("company_form.back")}
          </Link>
        </section>
      ) : (
        <>
          {/* P-4 (Part F) — FACTS FIRST, the ticket detail's rhythm: four
              questions, always visible, then the folds. The stat tiles
              are the counts of the folds below and open them. */}
          <div className="facts" data-testid="company-detail-facts">
            <div className="ew-ctx-block" data-testid="company-fact-who">
              <div className="ew-ctx-label">{t("company_detail.fact_company")}</div>
              <div className="ew-ctx-body">
                <div className="ew-ctx-strong">{company.name}</div>
                <div className="ew-ctx-sub">{languageLabel}</div>
              </div>
            </div>
            <div className="ew-ctx-block" data-testid="company-fact-status">
              <div className="ew-ctx-label">{t("company_detail.field_status")}</div>
              <div className="ew-ctx-body">
                <div className="ew-ctx-strong">
                  {isActive
                    ? t("company_detail.status_active")
                    : t("company_detail.status_inactive")}
                </div>
                {company.logo_url && (
                  <img
                    src={company.logo_url}
                    alt=""
                    style={{ maxHeight: 32, maxWidth: 140, marginTop: 4 }}
                    data-testid="company-detail-logo"
                  />
                )}
              </div>
            </div>
            <div className="ew-ctx-block" data-testid="company-fact-work">
              <div className="ew-ctx-label">{t("company_detail.fact_work")}</div>
              <div className="ew-ctx-body">
                <div className="ew-ctx-strong">
                  {count(summary?.open_ticket_count) === null
                    ? t("company_detail.fact_unknown")
                    : t("company_detail.fact_open_tickets", { count: summary?.open_ticket_count ?? 0 })}
                </div>
                <div className="ew-ctx-sub">
                  {count(summary?.open_extra_work_count) === null
                    ? ""
                    : t("company_detail.fact_open_extra_work", { count: summary?.open_extra_work_count ?? 0 })}
                </div>
              </div>
            </div>
            <div className="ew-ctx-block" data-testid="company-fact-people">
              <div className="ew-ctx-label">{t("company_detail.fact_people")}</div>
              <div className="ew-ctx-body">
                <div className="ew-ctx-strong">
                  {count(summary?.employee_count) === null
                    ? t("company_detail.fact_unknown")
                    : t("company_detail.fact_employees", { count: summary?.employee_count ?? 0 })}
                </div>
                <div className="ew-ctx-sub">
                  {count(summary?.admin_count) === null
                    ? ""
                    : t("company_detail.fact_admins", { count: summary?.admin_count ?? 0 })}
                </div>
              </div>
            </div>
          </div>

          <div
            className="summary-grid summary-grid-chips"
            data-testid="company-detail-stats"
          >
            {[
              { key: "buildings", label: t("company_detail.stat_buildings"), value: summary?.building_count, href: "#company-buildings" },
              { key: "customers", label: t("company_detail.stat_customers"), value: summary?.customer_count, href: "#company-customers" },
              { key: "admins", label: t("company_detail.stat_admins"), value: summary?.admin_count, href: "#company-admins" },
              { key: "employees", label: t("company_detail.stat_employees"), value: summary?.employee_count, href: "#company-employees" },
            ]
              .filter((stat) => stat.value !== null && stat.value !== undefined)
              .map((stat) => (
                <a
                  className="summary-stat summary-stat-link"
                  key={stat.key}
                  href={stat.href}
                  data-testid={`company-detail-stat-${stat.key}`}
                >
                  <span className="summary-stat-label">{stat.label}</span>
                  <span className="summary-stat-value">{stat.value}</span>
                </a>
              ))}
          </div>

          {/* The policy: the read-only TWIN of the edit page's toggle
              card — human captions, the danger note — never a column of
              screaming-caps label rows. */}
          <section
            className="card"
            data-testid="company-detail-policy-card"
            style={{ padding: "20px 22px", marginBottom: 16 }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">{t("company_policy.section_title")}</div>
                <div className="section-head-sub">{t("company_policy.section_desc")}</div>
              </div>
            </div>
            <div className="settings-toggle-group">
              {policyRows.map((row) => (
                <div key={row.flag} className="field" style={{ marginBottom: 8 }} data-testid={`company-detail-policy-${row.flag}`}>
                  <label className="settings-toggle-row">
                    <Toggle checked={row.on} disabled onChange={() => undefined} />
                    <span>
                      {t(`company_policy.${row.key}_label`)}
                      {row.dangerous && (
                        <span className="cell-tag cell-tag-rejected" style={{ marginLeft: 8 }}>
                          <i />
                          {t("company_policy.dangerous_badge")}
                        </span>
                      )}
                    </span>
                  </label>
                  <p
                    className="muted small"
                    style={{ margin: "2px 0 0 30px", ...(row.dangerous ? { color: "var(--red-1, #b42318)" } : {}) }}
                  >
                    {t(`company_policy.${row.key}_helper`)}
                  </p>
                </div>
              ))}
            </div>
            {!isSuperAdmin && (
              <p className="muted small" style={{ marginTop: 6 }}>
                {t("company_policy.readonly_hint")}
              </p>
            )}
          </section>

          <details className="form-fold" id="company-admins" open data-testid="company-detail-admins-card">
            <summary className="form-fold-summary">
              {t("company_detail.admins_title")}
              <span className="form-fold-summary-value">{admins.length}</span>
            </summary>
            <div className="form-fold-body">
              <p className="muted small" style={{ marginTop: 0 }}>{t("company_detail.admins_desc")}</p>
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
                      {admins.some((person) => person.phone) && (
                        <th>{t("customer_contacts.field_phone")}</th>
                      )}
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
                        {admins.some((row) => row.phone) && (
                          <td>{person.phone ? <a href={`tel:${person.phone}`}>{person.phone}</a> : ""}</td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </BoundedList>
            </div>
          </details>

          {/* The three relation lists, each behind its own fold with its
              count on the summary (bounded lists inside). */}
          <CompanyRelationCards companyId={company.id} />

          {/* Advanced: the technical value nobody needs day to day. */}
          <details className="action-fold" data-testid="company-detail-advanced">
            <summary className="form-fold-summary">{t("company_detail.advanced")}</summary>
            <dl className="action-fold-raw">
              <dt>{t("company_detail.field_slug")}</dt>
              <dd><code>{company.slug}</code></dd>
            </dl>
          </details>

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
      )}
    </div>
  );
}
