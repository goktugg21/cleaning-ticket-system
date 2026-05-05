import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { getApiError } from "../../api/client";
import {
  deactivateUser,
  extractAdminFieldErrors,
  getUser,
  listBuildings,
  listCompanies,
  listCustomers,
  reactivateUser,
  updateUser,
} from "../../api/admin";
import type { AdminFieldErrors } from "../../api/admin";
import type { Role, UserAdminDetail } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";

const LANGUAGE_OPTIONS = [
  { value: "nl", label: "Dutch (nl)" },
  { value: "en", label: "English (en)" },
];

const ROLE_LABEL: Record<Role, string> = {
  SUPER_ADMIN: "Super admin",
  COMPANY_ADMIN: "Company admin",
  BUILDING_MANAGER: "Building manager",
  CUSTOMER_USER: "Customer user",
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
  const numericId = Number(id);

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [searchParams, setSearchParams] = useSearchParams();
  const [savedBanner, setSavedBanner] = useState("");

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<AdminFieldErrors>({});

  const [user, setUser] = useState<UserAdminDetail | null>(null);
  const [fullName, setFullName] = useState("");
  const [language, setLanguage] = useState("nl");
  const [role, setRole] = useState<Role>("CUSTOMER_USER");

  const [companyNames, setCompanyNames] = useState<string[]>([]);
  const [buildingNames, setBuildingNames] = useState<string[]>([]);
  const [customerNames, setCustomerNames] = useState<string[]>([]);

  const deactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const reactivateDialogRef = useRef<HTMLDialogElement | null>(null);
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

  useEffect(() => {
    if (searchParams.get("saved") === "ok") {
      setSavedBanner("User saved.");
      const next = new URLSearchParams(searchParams);
      next.delete("saved");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!Number.isFinite(numericId)) return;
    let cancelled = false;
    setLoading(true);
    getUser(numericId)
      .then((data) => {
        if (cancelled) return;
        setUser(data);
        setFullName(data.full_name);
        setLanguage(data.language);
        setRole(data.role);
      })
      .catch((err) => {
        if (!cancelled) setGeneralError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId]);

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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    setGeneralError("");
    setFieldErrors({});
    setSubmitting(true);
    try {
      const updated = await updateUser(numericId, {
        full_name: fullName.trim(),
        language,
        role,
      });
      setUser(updated);
      setFullName(updated.full_name);
      setLanguage(updated.language);
      setRole(updated.role);
      setSavedBanner("User saved.");
    } catch (err) {
      const fields = extractAdminFieldErrors(err);
      if (Object.keys(fields).length > 0) {
        setFieldErrors(fields);
        if (fields.detail) setGeneralError(fields.detail);
      } else {
        setGeneralError(getApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirmDeactivate() {
    if (!user) return;
    setActionBusy(true);
    setGeneralError("");
    try {
      await deactivateUser(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/users?deactivated=ok", { replace: true });
    } catch (err) {
      setGeneralError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (!user) return;
    setActionBusy(true);
    setGeneralError("");
    try {
      await reactivateUser(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/users?reactivated=ok", { replace: true });
    } catch (err) {
      setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <div>
      <Link to="/admin/users" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        Back to users
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">{user?.email ?? "User"}</h2>
          <p className="page-sub" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="cell-tag cell-tag-open">
              <i />
              {ROLE_LABEL[role] ?? role}
            </span>
            {user && !user.is_active && (
              <span className="cell-tag cell-tag-closed">
                <i />
                Inactive
              </span>
            )}
            {isSelf && <span className="muted small">This is you</span>}
          </p>
        </div>
        {user && !user.is_active && isSuperAdmin && (
          <div className="page-header-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => reactivateDialogRef.current?.showModal()}
            >
              Reactivate
            </button>
          </div>
        )}
      </div>

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {generalError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {generalError}
        </div>
      )}

      {loading || !user ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <>
          <form className="card" onSubmit={handleSubmit} style={{ padding: "20px 22px" }}>
            <div className="field">
              <label className="field-label" htmlFor="user-email">
                Email
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
                Full name
              </label>
              <input
                id="user-full-name"
                className="field-input"
                type="text"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
              />
              {fieldErrors.full_name && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.full_name}
                </div>
              )}
            </div>

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="user-language">
                  Language
                </label>
                <select
                  id="user-language"
                  className="field-select"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                >
                  {LANGUAGE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="user-role">
                  Role
                  {roleDisabled && (
                    <span className="muted small" style={{ marginLeft: 8 }}>
                      {isSelf
                        ? "(you cannot change your own role)"
                        : "(only super admins can manage this role)"}
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
                    <option value={role}>{ROLE_LABEL[role] ?? role}</option>
                  )}
                  {availableRoleOptions.map((option) => (
                    <option key={option} value={option}>
                      {ROLE_LABEL[option]}
                    </option>
                  ))}
                </select>
                {fieldErrors.role && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.role}
                  </div>
                )}
              </div>
            </div>

            <div className="form-actions" style={{ marginTop: 12 }}>
              {user.is_active && !isSelf && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => deactivateDialogRef.current?.showModal()}
                >
                  Deactivate
                </button>
              )}
              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? "Saving…" : "Save changes"}
              </button>
            </div>
          </form>

          <section className="card" style={{ marginTop: 16, padding: "20px 22px" }}>
            <h3 className="section-title">Memberships</h3>
            <p className="muted small" style={{ marginBottom: 12 }}>
              Read-only summary. Memberships are managed from the entity detail pages.
            </p>
            <div className="detail-kv-list">
              <div className="detail-kv-row">
                <span className="detail-kv-label">Companies</span>
                <span className="detail-kv-val">
                  {user.company_ids.length === 0
                    ? "—"
                    : companyNames.length > 0
                      ? companyNames.join(", ")
                      : `${user.company_ids.length} (loading names…)`}
                </span>
              </div>
              <div className="detail-kv-row">
                <span className="detail-kv-label">Buildings</span>
                <span className="detail-kv-val">
                  {user.building_ids.length === 0
                    ? "—"
                    : buildingNames.length > 0
                      ? buildingNames.join(", ")
                      : `${user.building_ids.length} (loading names…)`}
                </span>
              </div>
              <div className="detail-kv-row">
                <span className="detail-kv-label">Customers</span>
                <span className="detail-kv-val">
                  {user.customer_ids.length === 0
                    ? "—"
                    : customerNames.length > 0
                      ? customerNames.join(", ")
                      : `${user.customer_ids.length} (loading names…)`}
                </span>
              </div>
            </div>
          </section>
        </>
      )}

      <dialog
        ref={deactivateDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>Deactivate {user?.email ?? "user"}?</h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
          They will lose access immediately. Their data and history are kept; a super admin can
          reactivate them later.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => deactivateDialogRef.current?.close()}
            disabled={actionBusy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleConfirmDeactivate}
            disabled={actionBusy}
          >
            {actionBusy ? "Deactivating…" : "Deactivate"}
          </button>
        </div>
      </dialog>

      <dialog
        ref={reactivateDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>Reactivate {user?.email ?? "user"}?</h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
          Reactivating restores their account. They will regain access using their existing
          password (or can request a reset).
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => reactivateDialogRef.current?.close()}
            disabled={actionBusy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleConfirmReactivate}
            disabled={actionBusy}
          >
            {actionBusy ? "Reactivating…" : "Reactivate"}
          </button>
        </div>
      </dialog>
    </div>
  );
}
