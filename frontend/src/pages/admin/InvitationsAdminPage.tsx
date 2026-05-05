import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
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

type StatusFilter = "all" | "PENDING" | "ACCEPTED" | "REVOKED" | "EXPIRED";

const ROLE_LABEL: Record<Role, string> = {
  SUPER_ADMIN: "Super admin",
  COMPANY_ADMIN: "Company admin",
  BUILDING_MANAGER: "Building manager",
  CUSTOMER_USER: "Customer user",
};

const STATUS_LABEL: Record<InvitationAdmin["status"], string> = {
  PENDING: "Pending",
  ACCEPTED: "Accepted",
  REVOKED: "Revoked",
  EXPIRED: "Expired",
};

function statusCellClass(status: InvitationAdmin["status"]): string {
  switch (status) {
    case "PENDING":
      return "cell-tag cell-tag-open";
    case "ACCEPTED":
      return "cell-tag cell-tag-approved";
    case "REVOKED":
      return "cell-tag cell-tag-rejected";
    case "EXPIRED":
      return "cell-tag cell-tag-closed";
  }
}

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export function InvitationsAdminPage() {
  const { me } = useAuth();
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
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("PENDING");

  const [savedBanner, setSavedBanner] = useState("");

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

  // Status filter is client-side because /api/auth/invitations/ does not
  // currently have a status filterset. Documented in api/admin.ts.
  const visibleInvitations = useMemo(() => {
    if (statusFilter === "all") return invitations;
    return invitations.filter((i) => i.status === statusFilter);
  }, [invitations, statusFilter]);

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

  const revokeDialogRef = useRef<HTMLDialogElement | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<InvitationAdmin | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);

  function openRevokeDialog(invitation: InvitationAdmin) {
    setRevokeTarget(invitation);
    revokeDialogRef.current?.showModal();
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
            Admin
          </div>
          <h2 className="page-title">Invitations</h2>
          <p className="page-sub">
            {listLoading
              ? "Loading invitations…"
              : `${count} ${count === 1 ? "invitation" : "invitations"}`}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={load}
            disabled={listLoading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            Refresh
          </button>
        </div>
      </div>

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      <section className="card" style={{ padding: "20px 22px" }}>
        <h3 className="section-title">Send a new invitation</h3>
        <p className="muted small" style={{ marginBottom: 12 }}>
          The invitee receives an email with a one-time link. They set their own password when
          accepting.
        </p>

        {formGeneralError && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {formGeneralError}
          </div>
        )}

        <form onSubmit={handleCreate}>
          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="invite-email">
                Email *
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
                Full name (optional)
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

          <div className="field">
            <label className="field-label" htmlFor="invite-role">
              Role *
            </label>
            <select
              id="invite-role"
              className="field-select"
              value={formRole}
              onChange={(event) => setFormRole(event.target.value as Role)}
            >
              {availableRoles.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABEL[role]}
                </option>
              ))}
            </select>
            {formFieldErrors.role && (
              <div className="alert-error login-error" role="alert">
                {formFieldErrors.role}
              </div>
            )}
          </div>

          {/* Company picker is shown for COMPANY_ADMIN role and as a parent
              filter for BUILDING_MANAGER / CUSTOMER_USER role. SUPER_ADMIN
              role has no scope inputs. */}
          {formRole !== "SUPER_ADMIN" && (
            <div className="field">
              <label className="field-label" htmlFor="invite-company">
                Company {formRole === "COMPANY_ADMIN" && "*"}
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
                  {formRole === "COMPANY_ADMIN" ? "Select company…" : "All companies"}
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

          {formRole === "BUILDING_MANAGER" && (
            <div className="field">
              <label className="field-label">Buildings *</label>
              <p className="muted small" style={{ marginBottom: 8 }}>
                Pick one or more buildings the invitee will manage.
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {buildingOptions.length === 0 ? (
                  <span className="muted small">
                    {formCompany === ""
                      ? "Select a company first."
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
              <label className="field-label">Customers *</label>
              <p className="muted small" style={{ marginBottom: 8 }}>
                Pick one or more customers the invitee will be linked to.
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {customerOptions.length === 0 ? (
                  <span className="muted small">
                    {formCompany === ""
                      ? "Select a company first."
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

          <div className="form-actions" style={{ marginTop: 12 }}>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "Sending…" : "Send invitation"}
            </button>
          </div>
        </form>
      </section>

      <div className="card" style={{ overflow: "hidden", marginTop: 16 }}>
        <div className="filter-bar">
          <div className="filter-field">
            <span className="filter-label">Status</span>
            <select
              className="filter-control"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            >
              <option value="PENDING">Pending</option>
              <option value="ACCEPTED">Accepted</option>
              <option value="REVOKED">Revoked</option>
              <option value="EXPIRED">Expired</option>
              <option value="all">All</option>
            </select>
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
          <table className="data-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th>Sent</th>
                <th>Expires</th>
                <th>Sent by</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {visibleInvitations.map((invitation) => {
                const canRevoke =
                  invitation.status === "PENDING" &&
                  (isSuperAdmin || invitation.created_by_email === me?.email);
                return (
                  <tr key={invitation.id}>
                    <td className="td-subject">{invitation.email}</td>
                    <td>{ROLE_LABEL[invitation.role] ?? invitation.role}</td>
                    <td>
                      <span className={statusCellClass(invitation.status)}>
                        <i />
                        {STATUS_LABEL[invitation.status]}
                      </span>
                    </td>
                    <td className="td-date">{formatDate(invitation.created_at)}</td>
                    <td className="td-date">{formatDate(invitation.expires_at)}</td>
                    <td>{invitation.created_by_email}</td>
                    <td>
                      {canRevoke && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => openRevokeDialog(invitation)}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {!listLoading && visibleInvitations.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">＋</div>
              <div className="empty-title">
                {statusFilter === "all"
                  ? "No invitations yet"
                  : `No ${STATUS_LABEL[statusFilter as InvitationAdmin["status"]].toLowerCase()} invitations`}
              </div>
              <p className="empty-sub">Use the form above to send the first one.</p>
            </div>
          )}
        </div>

        {(previous || next) && (
          <div className="pagination">
            <span className="pagination-info">
              Page {page} · {count} total
            </span>
            <div className="pagination-controls">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={listLoading || !previous || page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={listLoading || !next}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      <dialog
        ref={revokeDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>
          Revoke invitation to {revokeTarget?.email ?? "user"}?
        </h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
          The invitation link will stop working immediately. You can send a new one if needed.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              revokeDialogRef.current?.close();
              setRevokeTarget(null);
            }}
            disabled={revokeBusy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleConfirmRevoke}
            disabled={revokeBusy}
          >
            {revokeBusy ? "Revoking…" : "Revoke"}
          </button>
        </div>
      </dialog>
    </div>
  );
}
