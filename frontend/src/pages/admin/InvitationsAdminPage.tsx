import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  createInvitation,
  extractAdminFieldErrors,
  listBuildings,
  listCompanies,
  listCustomers,
  listInvitations,
  revokeInvitation,
} from "../../api/admin";
import type { AdminFieldErrors, InvitationCreatePayload } from "../../api/admin";
import type {
  BuildingAdmin,
  CompanyAdmin,
  CustomerAdmin,
  InvitationAdmin,
  Role,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type StatusTab = "PENDING" | "ACCEPTED" | "EXPIRED" | "ALL";

const ROLE_KEYS: Record<Role, string> = {
  SUPER_ADMIN: "common:roles.super_admin",
  COMPANY_ADMIN: "common:roles.company_admin",
  BUILDING_MANAGER: "common:roles.building_manager",
  CUSTOMER_USER: "common:roles.customer_user",
};

function statusPillClass(status: InvitationAdmin["status"]): string {
  return `status-pill status-pill--${status.toLowerCase()}`;
}

function getInitials(fullName: string, email: string): string {
  const cleaned = (fullName || "").trim();
  if (cleaned) {
    const parts = cleaned.split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (email.split("@")[0] || "?").slice(0, 2).toUpperCase();
}

// Relative time using Intl.RelativeTimeFormat with numeric:"auto" so we
// get "yesterday" / "tomorrow" / "in 3 days" naturally in both nl and en.
// Falls back to absolute date when the gap exceeds 30 days. Empty input
// returns an em dash.
function formatRelative(iso: string | null | undefined, lang: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diffMs = date.getTime() - Date.now();
  const absHr = Math.abs(diffMs) / 3600000;
  const absDay = Math.abs(diffMs) / 86400000;
  const locale = lang === "nl" ? "nl-NL" : "en-US";
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (absHr < 1) {
    return rtf.format(Math.round(diffMs / 60000), "minute");
  }
  if (absHr < 24) {
    return rtf.format(Math.round(diffMs / 3600000), "hour");
  }
  if (absDay < 30) {
    return rtf.format(Math.round(diffMs / 86400000), "day");
  }
  return date.toLocaleDateString(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function InvitationsAdminPage() {
  const { me } = useAuth();
  const { t, i18n } = useTranslation("common");
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  // Available role choices for the create form. SUPER_ADMIN can pick any role
  // (including SUPER_ADMIN, no scope). COMPANY_ADMIN can pick the three
  // non-super-admin roles. The API enforces this; the UI hides forbidden
  // options so an actor does not get a 400 from clicking.
  const availableRoles: Role[] = useMemo(
    () =>
      isSuperAdmin
        ? ["SUPER_ADMIN", "COMPANY_ADMIN", "BUILDING_MANAGER", "CUSTOMER_USER"]
        : ["COMPANY_ADMIN", "BUILDING_MANAGER", "CUSTOMER_USER"],
    [isSuperAdmin],
  );

  // ---- List state ------------------------------------------------------

  const [invitations, setInvitations] = useState<InvitationAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [statusTab, setStatusTab] = useState<StatusTab>("PENDING");

  const [savedBanner, setSavedBanner] = useSavedBanner({});

  const load = useCallback(async () => {
    setListLoading(true);
    setListError("");
    try {
      const response = await listInvitations({ page });
      setInvitations(response.results);
      setCount(response.count);
      setNext(response.next);
      setPrevious(response.previous);
    } catch (err) {
      setListError(getApiError(err));
    } finally {
      setListLoading(false);
    }
  }, [page]);

  useEffect(() => {
    load();
  }, [load]);

  // Status filter is client-side: the API does not currently expose a
  // status query param. The four tabs are PENDING/ACCEPTED/EXPIRED/ALL —
  // REVOKED entries surface only under ALL.
  const filteredInvitations = useMemo(() => {
    if (statusTab === "ALL") return invitations;
    return invitations.filter((i) => i.status === statusTab);
  }, [invitations, statusTab]);

  // Counts for the page-header stats summary. Always reflect the full
  // set returned by the API, regardless of which tab is active.
  const totalCount = invitations.length;
  const pendingCount = invitations.filter((i) => i.status === "PENDING").length;
  const acceptedCount = invitations.filter((i) => i.status === "ACCEPTED").length;
  const expiredCount = invitations.filter((i) => i.status === "EXPIRED").length;

  // ---- Create form state -----------------------------------------------

  const [formEmail, setFormEmail] = useState("");
  const [formFullName, setFormFullName] = useState("");
  const [formRole, setFormRole] = useState<Role>(
    availableRoles.includes("BUILDING_MANAGER") ? "BUILDING_MANAGER" : availableRoles[0],
  );
  const [formCompany, setFormCompany] = useState<number | "">("");
  const [formBuildings, setFormBuildings] = useState<number[]>([]);
  const [formCustomers, setFormCustomers] = useState<number[]>([]);

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);
  const [buildingOptions, setBuildingOptions] = useState<BuildingAdmin[]>([]);
  const [customerOptions, setCustomerOptions] = useState<CustomerAdmin[]>([]);

  const [submitting, setSubmitting] = useState(false);
  const [formGeneralError, setFormGeneralError] = useState("");
  const [formFieldErrors, setFormFieldErrors] = useState<AdminFieldErrors>({});

  // Companies once on mount (used both for the COMPANY_ADMIN role-scope
  // dropdown and as a parent filter for buildings/customers).
  useEffect(() => {
    let cancelled = false;
    listCompanies({ is_active: "true", page_size: 200 })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response.results);
        // Auto-select for COMPANY_ADMIN with one company in scope.
        if (response.results.length === 1) {
          setFormCompany(response.results[0].id);
        }
      })
      .finally(() => {
        if (!cancelled) setCompaniesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Reload building/customer options whenever the company filter changes.
  useEffect(() => {
    if (formCompany === "") {
      setBuildingOptions([]);
      setCustomerOptions([]);
      return;
    }
    let cancelled = false;
    listBuildings({ is_active: "true", page_size: 200, company: formCompany })
      .then((response) => {
        if (!cancelled) setBuildingOptions(response.results);
      })
      .catch(() => {
        if (!cancelled) setBuildingOptions([]);
      });
    listCustomers({ is_active: "true", page_size: 200, company: formCompany })
      .then((response) => {
        if (!cancelled) setCustomerOptions(response.results);
      })
      .catch(() => {
        if (!cancelled) setCustomerOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [formCompany]);

  // When the role changes, drop scope selections that no longer apply.
  useEffect(() => {
    setFormBuildings([]);
    setFormCustomers([]);
    setFormFieldErrors({});
  }, [formRole]);

  const companyLocked = companiesLoaded && companies.length <= 1;

  function toggleBuilding(id: number) {
    setFormBuildings((current) =>
      current.includes(id) ? current.filter((b) => b !== id) : [...current, id],
    );
  }

  function toggleCustomer(id: number) {
    setFormCustomers((current) =>
      current.includes(id) ? current.filter((c) => c !== id) : [...current, id],
    );
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormGeneralError("");
    setFormFieldErrors({});

    const trimmedEmail = formEmail.trim();
    const errs: AdminFieldErrors = {};
    if (!trimmedEmail) errs.email = "Email is required.";
    if (formRole === "COMPANY_ADMIN" && formCompany === "") {
      errs.company_ids = "Pick a company.";
    }
    if (formRole === "BUILDING_MANAGER" && formBuildings.length === 0) {
      errs.building_ids = "Pick at least one building.";
    }
    if (formRole === "CUSTOMER_USER" && formCustomers.length === 0) {
      errs.customer_ids = "Pick at least one customer.";
    }
    if (Object.keys(errs).length > 0) {
      setFormFieldErrors(errs);
      return;
    }

    const payload: InvitationCreatePayload = {
      email: trimmedEmail,
      full_name: formFullName.trim(),
      role: formRole,
    };
    if (formRole === "COMPANY_ADMIN" && formCompany !== "") {
      payload.company_ids = [Number(formCompany)];
    }
    if (formRole === "BUILDING_MANAGER") {
      payload.building_ids = formBuildings;
    }
    if (formRole === "CUSTOMER_USER") {
      payload.customer_ids = formCustomers;
    }

    setSubmitting(true);
    try {
      await createInvitation(payload);
      setSavedBanner(`Invitation sent to ${trimmedEmail}.`);
      setFormEmail("");
      setFormFullName("");
      setFormBuildings([]);
      setFormCustomers([]);
      // Reload the list. Reset to page 1 so the new invitation is on top.
      if (page !== 1) {
        setPage(1);
      } else {
        await load();
      }
    } catch (err) {
      const fields = extractAdminFieldErrors(err);
      if (Object.keys(fields).length > 0) {
        setFormFieldErrors(fields);
        if (fields.detail) setFormGeneralError(fields.detail);
      } else {
        setFormGeneralError(getApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  // ---- Revoke flow -----------------------------------------------------

  const revokeDialogRef = useRef<ConfirmDialogHandle>(null);
  const [revokeTarget, setRevokeTarget] = useState<InvitationAdmin | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);

  function openRevokeDialog(invitation: InvitationAdmin) {
    setRevokeTarget(invitation);
    revokeDialogRef.current?.open();
  }

  async function handleConfirmRevoke() {
    if (!revokeTarget) return;
    setRevokeBusy(true);
    try {
      await revokeInvitation(revokeTarget.id);
      revokeDialogRef.current?.close();
      setSavedBanner(`Invitation to ${revokeTarget.email} revoked.`);
      setRevokeTarget(null);
      await load();
    } catch (err) {
      setListError(getApiError(err));
      revokeDialogRef.current?.close();
    } finally {
      setRevokeBusy(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("invitations.title")}</h2>
          <div className="invitations-stats">
            <span>
              {totalCount} {t("invitations.total")}
            </span>
            <span className="dot" />
            <span>
              {pendingCount} {t("invitations.pending_label")}
            </span>
            {acceptedCount > 0 && (
              <>
                <span className="dot" />
                <span className="accepted-text">
                  {acceptedCount} {t("invitations.accepted_label")}
                </span>
              </>
            )}
            {expiredCount > 0 && (
              <>
                <span className="dot" />
                <span className="expired-text">
                  {expiredCount} {t("invitations.expired_label")}
                </span>
              </>
            )}
          </div>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={load}
            disabled={listLoading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("refresh")}
          </button>
        </div>
      </div>

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {/* Form card: two-column body (description on the left, fields on
          the right). The form-actions row at the bottom keeps its
          shared border-top + subtle bg styling. */}
      <section className="card">
        {formGeneralError && (
          <div
            className="alert-error"
            role="alert"
            style={{ margin: "16px 32px 0" }}
          >
            {formGeneralError}
          </div>
        )}
        <form onSubmit={handleCreate}>
          <div className="invitation-form-split">
            <div className="invitation-form-info">
              <div className="eyebrow">{t("invitations.send_eyebrow")}</div>
              <div className="invitation-form-title">
                {t("invitations.invite_teammate")}
              </div>
              <div className="invitation-form-desc">
                {t("invitations.form_description")}
              </div>
              <div className="invitation-form-note">
                {t("invitations.expires_note")}
              </div>
            </div>

            <div className="invitation-form-fields">
              <div className="form-grid-2">
                <div className="field">
                  <label className="field-label" htmlFor="invite-email">
                    {t("invitations.field_email")} *
                  </label>
                  <input
                    id="invite-email"
                    className="field-input"
                    type="email"
                    value={formEmail}
                    onChange={(event) => setFormEmail(event.target.value)}
                    required
                  />
                  {formFieldErrors.email && (
                    <div className="alert-error login-error" role="alert">
                      {formFieldErrors.email}
                    </div>
                  )}
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="invite-full-name">
                    {t("invitations.field_full_name")} {t("invitations.field_optional")}
                  </label>
                  <input
                    id="invite-full-name"
                    className="field-input"
                    type="text"
                    value={formFullName}
                    onChange={(event) => setFormFullName(event.target.value)}
                  />
                </div>
              </div>

              <div className="form-grid-2">
                <div className="field">
                  <label className="field-label" htmlFor="invite-role">
                    {t("invitations.field_role")} *
                  </label>
                  <select
                    id="invite-role"
                    className="field-select"
                    value={formRole}
                    onChange={(event) => setFormRole(event.target.value as Role)}
                  >
                    {availableRoles.map((role) => (
                      <option key={role} value={role}>
                        {t(ROLE_KEYS[role])}
                      </option>
                    ))}
                  </select>
                  {formFieldErrors.role && (
                    <div className="alert-error login-error" role="alert">
                      {formFieldErrors.role}
                    </div>
                  )}
                </div>

                {formRole !== "SUPER_ADMIN" && (
                  <div className="field">
                    <label className="field-label" htmlFor="invite-company">
                      {t("invitations.field_company")}
                      {formRole === "COMPANY_ADMIN" && " *"}
                    </label>
                    <select
                      id="invite-company"
                      className="field-select"
                      value={formCompany === "" ? "" : String(formCompany)}
                      onChange={(event) => {
                        const v = event.target.value;
                        setFormCompany(v === "" ? "" : Number(v));
                      }}
                      disabled={companyLocked}
                      required={formRole === "COMPANY_ADMIN"}
                    >
                      <option value="">
                        {formRole === "COMPANY_ADMIN"
                          ? t("invitations.select_company_placeholder")
                          : t("invitations.all_companies")}
                      </option>
                      {companies.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                    {formFieldErrors.company_ids && (
                      <div className="alert-error login-error" role="alert">
                        {formFieldErrors.company_ids}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {formRole === "BUILDING_MANAGER" && (
                <div className="field">
                  <label className="field-label">{t("invitations.field_buildings")} *</label>
                  <p className="field-helper">
                    {t("invitations.buildings_hint")}
                  </p>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 8,
                      marginTop: 4,
                    }}
                  >
                    {buildingOptions.length === 0 ? (
                      <span className="muted small">
                        {formCompany === ""
                          ? t("invitations.select_company_first")
                          : "No buildings in this company."}
                      </span>
                    ) : (
                      buildingOptions.map((b) => {
                        const active = formBuildings.includes(b.id);
                        return (
                          <button
                            key={b.id}
                            type="button"
                            className={`btn btn-sm ${active ? "btn-primary" : "btn-secondary"}`}
                            onClick={() => toggleBuilding(b.id)}
                            aria-pressed={active}
                          >
                            {b.name}
                          </button>
                        );
                      })
                    )}
                  </div>
                  {formFieldErrors.building_ids && (
                    <div className="alert-error login-error" role="alert">
                      {formFieldErrors.building_ids}
                    </div>
                  )}
                </div>
              )}

              {formRole === "CUSTOMER_USER" && (
                <div className="field">
                  <label className="field-label">{t("invitations.field_customers")} *</label>
                  <p className="field-helper">
                    {t("invitations.customers_hint")}
                  </p>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 8,
                      marginTop: 4,
                    }}
                  >
                    {customerOptions.length === 0 ? (
                      <span className="muted small">
                        {formCompany === ""
                          ? t("invitations.select_company_first")
                          : "No customers in this company."}
                      </span>
                    ) : (
                      customerOptions.map((c) => {
                        const active = formCustomers.includes(c.id);
                        return (
                          <button
                            key={c.id}
                            type="button"
                            className={`btn btn-sm ${active ? "btn-primary" : "btn-secondary"}`}
                            onClick={() => toggleCustomer(c.id)}
                            aria-pressed={active}
                          >
                            {c.name}
                          </button>
                        );
                      })
                    )}
                  </div>
                  {formFieldErrors.customer_ids && (
                    <div className="alert-error login-error" role="alert">
                      {formFieldErrors.customer_ids}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="btn btn-primary"
              data-testid="invite-submit"
              disabled={submitting}
            >
              {submitting ? t("invitations.sending") : t("invitations.send_invitation")}
            </button>
          </div>
        </form>
      </section>

      {/* Activity card: status tabs + table. Tabs replace the old
          single-select status filter. The fetch logic is unchanged
          (one /api/auth/invitations/ call); the tab choice filters
          client-side via filteredInvitations. */}
      <section className="card" style={{ overflow: "hidden", marginTop: 16 }}>
        <div className="activity-card-header">
          <div>
            <div className="eyebrow">{t("invitations.activity_eyebrow")}</div>
            <div className="activity-card-title">
              {t("invitations.all_invitations")}
            </div>
          </div>
          <div className="status-tabs">
            <button
              type="button"
              data-testid="status-tab-pending"
              className={statusTab === "PENDING" ? "active" : ""}
              onClick={() => setStatusTab("PENDING")}
            >
              {t("invitations.pending_label")}
            </button>
            <button
              type="button"
              data-testid="status-tab-accepted"
              className={statusTab === "ACCEPTED" ? "active" : ""}
              onClick={() => setStatusTab("ACCEPTED")}
            >
              {t("invitations.accepted_label")}
            </button>
            <button
              type="button"
              data-testid="status-tab-expired"
              className={statusTab === "EXPIRED" ? "active" : ""}
              onClick={() => setStatusTab("EXPIRED")}
            >
              {t("invitations.expired_label")}
            </button>
            <button
              type="button"
              data-testid="status-tab-all"
              className={statusTab === "ALL" ? "active" : ""}
              onClick={() => setStatusTab("ALL")}
            >
              {t("invitations.all_label")}
            </button>
          </div>
        </div>

        {listLoading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        {listError && (
          <div className="alert-error" style={{ margin: 12 }} role="alert">
            {listError}
          </div>
        )}

        <div className="table-wrap">
          <table className="invitations-table" data-testid="invitations-table">
            <colgroup>
              <col style={{ width: "32%" }} />
              <col style={{ width: "18%" }} />
              <col style={{ width: "13%" }} />
              <col style={{ width: "12%" }} />
              <col style={{ width: "12%" }} />
              <col style={{ width: "13%" }} />
            </colgroup>
            <thead>
              <tr>
                <th>{t("invitations.col_recipient")}</th>
                <th>{t("invitations.col_role")}</th>
                <th>{t("invitations.col_status")}</th>
                <th>{t("invitations.col_sent")}</th>
                <th>{t("invitations.col_expires")}</th>
                <th className="text-right">{t("invitations.col_actions")}</th>
              </tr>
            </thead>
            <tbody>
              {filteredInvitations.map((invitation) => {
                const canRevoke =
                  invitation.status === "PENDING" &&
                  (isSuperAdmin || invitation.created_by_email === me?.email);
                const displayName =
                  invitation.full_name?.trim() ||
                  invitation.email.split("@")[0];
                return (
                  <tr key={invitation.id}>
                    <td>
                      <div className="recipient-cell">
                        <div className="recipient-avatar">
                          {getInitials(invitation.full_name, invitation.email)}
                        </div>
                        <div className="recipient-text">
                          <div className="recipient-name">{displayName}</div>
                          <div className="recipient-email">
                            {invitation.email}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>{t(ROLE_KEYS[invitation.role] ?? "common:roles.fallback")}</td>
                    <td>
                      <span className={statusPillClass(invitation.status)}>
                        <span className="status-pill-dot" />
                        {t(`invitations.status_${invitation.status.toLowerCase()}`)}
                      </span>
                    </td>
                    <td className="muted-cell">
                      {formatRelative(invitation.created_at, i18n.language)}
                    </td>
                    <td className="muted-cell">
                      {formatRelative(invitation.expires_at, i18n.language)}
                    </td>
                    <td className="text-right">
                      {canRevoke && (
                        <button
                          type="button"
                          className="link-action link-action--danger"
                          onClick={() => openRevokeDialog(invitation)}
                        >
                          {t("invitations.revoke")}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {!listLoading && filteredInvitations.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">＋</div>
              <div className="empty-title">
                {t("invitations.empty_title")}
              </div>
              <p className="empty-sub">{t("invitations.empty_desc")}</p>
            </div>
          )}
        </div>

        {(previous || next) && (
          <div className="pagination">
            <span className="pagination-info">
              {t("invitations.pagination_page", { page, total: count })}
            </span>
            <div className="pagination-controls">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={listLoading || !previous || page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("invitations.pagination_previous")}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={listLoading || !next}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("invitations.pagination_next")}
              </button>
            </div>
          </div>
        )}
      </section>

      <ConfirmDialog
        ref={revokeDialogRef}
        title={`Revoke invitation to ${revokeTarget?.email ?? "user"}?`}
        body="The invitation link will stop working immediately. You can send a new one if needed."
        confirmLabel="Revoke"
        onConfirm={handleConfirmRevoke}
        onCancel={() => setRevokeTarget(null)}
        busy={revokeBusy}
      />
    </div>
  );
}
