import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
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

const LANGUAGE_OPTIONS = [
  { value: "nl", label: "Dutch (nl)" },
  { value: "en", label: "English (en)" },
];

export function CompanyFormPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isCreate = id === undefined;

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [savedBanner, setSavedBanner] = useSavedBanner({ saved: "Company saved." });

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
    onEditSuccess: () => setSavedBanner("Company saved."),
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
          Back to companies
        </Link>
        <div className="page-header">
          <div>
            <div className="eyebrow" style={{ marginBottom: 8 }}>
              Admin
            </div>
            <h2 className="page-title">Forbidden</h2>
            <p className="page-sub">
              Only super admins can create new companies. Ask one to create it for you, or edit an
              existing company below.
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

  return (
    <div className="page-form-narrow">
      <Link to="/admin/companies" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        Back to companies
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">
            {isCreate ? "Create company" : `Edit ${company?.name ?? "company"}`}
          </h2>
          {!isCreate && company && !company.is_active && (
            <p className="page-sub">
              <span className="cell-tag cell-tag-closed">
                <i />
                Inactive
              </span>
            </p>
          )}
        </div>
        {!isCreate && company && !company.is_active && isSuperAdmin && (
          <div className="page-header-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => reactivateDialogRef.current?.open()}
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
        <form className="card" onSubmit={form.handleSubmit} style={{ padding: "20px 22px" }}>
          <div className="field">
            <label className="field-label" htmlFor="company-name">
              Name *
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
              Slug
              {slugReadOnly && (
                <span className="muted small" style={{ marginLeft: 8 }}>
                  (only super admins can change slugs)
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
              placeholder={isCreate ? "Leave blank to auto-generate from the name" : ""}
            />
            {form.fieldErrors.slug && (
              <div className="alert-error login-error" role="alert">
                {form.fieldErrors.slug}
              </div>
            )}
          </div>

          <div className="field">
            <label className="field-label" htmlFor="company-language">
              Default language
            </label>
            <select
              id="company-language"
              className="field-select"
              value={defaultLanguage}
              onChange={(event) => setDefaultLanguage(event.target.value)}
            >
              {LANGUAGE_OPTIONS.map((option) => (
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

          <div className="form-actions" style={{ marginTop: 12 }}>
            {!isCreate && company && company.is_active && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => deactivateDialogRef.current?.open()}
              >
                Deactivate
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={form.submitting || !name.trim()}>
              {form.submitting ? "Saving…" : isCreate ? "Create company" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      {!isCreate && company && (
        <section className="card" style={{ marginTop: 16, padding: "20px 22px" }}>
          <h3 className="section-title">Admins</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            Users with the COMPANY_ADMIN role linked to this company. Add an existing user
            below; new users come in via invitations.
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
                  <th>Email</th>
                  <th>Full name</th>
                  <th>Added</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => (
                  <tr key={membership.id}>
                    <td className="td-subject">{membership.user_email}</td>
                    <td>{membership.user_full_name || "—"}</td>
                    <td className="td-date">
                      {new Date(membership.created_at).toLocaleDateString()}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openRemoveDialog(membership)}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {members.length === 0 && (
              <p className="muted small" style={{ padding: "12px 0" }}>
                No admins linked yet.
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddMember}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-company-admin">
                Add admin
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
                    ? "No eligible users"
                    : "Select a user…"}
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
              disabled={memberBusy || selectedUserId === ""}
            >
              {memberBusy ? "Adding…" : "Add"}
            </button>
          </form>
        </section>
      )}

      <ConfirmDialog
        ref={deactivateDialogRef}
        title={`Deactivate ${company?.name ?? "company"}?`}
        body="It will be hidden from non-super-admin users. Tickets attached to it remain visible to staff."
        confirmLabel="Deactivate"
        onConfirm={handleConfirmDeactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reactivateDialogRef}
        title={`Reactivate ${company?.name ?? "company"}?`}
        body="Reactivating restores it for all roles. Existing memberships and tickets are unchanged."
        confirmLabel="Reactivate"
        onConfirm={handleConfirmReactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={removeDialogRef}
        title={`Remove ${removeTarget?.user_email ?? "user"} from ${company?.name ?? "company"}?`}
        body="Their other memberships are unaffected. They can be re-added later."
        confirmLabel="Remove"
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={memberBusy}
      />
    </div>
  );
}
