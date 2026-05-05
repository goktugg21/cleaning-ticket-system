import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { getApiError } from "../../api/client";
import {
  createCompany,
  deactivateCompany,
  extractAdminFieldErrors,
  getCompany,
  reactivateCompany,
  updateCompany,
} from "../../api/admin";
import type { AdminFieldErrors } from "../../api/admin";
import type { CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";

const LANGUAGE_OPTIONS = [
  { value: "nl", label: "Dutch (nl)" },
  { value: "en", label: "English (en)" },
];

export function CompanyFormPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isCreate = id === undefined;
  const numericId = isCreate ? null : Number(id);

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [searchParams, setSearchParams] = useSearchParams();
  const [savedBanner, setSavedBanner] = useState("");

  const [loading, setLoading] = useState(!isCreate);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<AdminFieldErrors>({});

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [defaultLanguage, setDefaultLanguage] = useState("nl");
  const [company, setCompany] = useState<CompanyAdmin | null>(null);

  const deactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const reactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // The API enforces this too; UI gates it for clarity.
  const forbidden = isCreate && !isSuperAdmin;

  useEffect(() => {
    if (searchParams.get("saved") === "ok") {
      setSavedBanner("Company saved.");
      const next = new URLSearchParams(searchParams);
      next.delete("saved");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (isCreate || numericId === null) return;
    let cancelled = false;
    setLoading(true);
    getCompany(numericId)
      .then((data) => {
        if (cancelled) return;
        setCompany(data);
        setName(data.name);
        setSlug(data.slug);
        setDefaultLanguage(data.default_language);
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
  }, [isCreate, numericId]);

  const slugReadOnly = useMemo(() => !isCreate && !isSuperAdmin, [isCreate, isSuperAdmin]);

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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    setFieldErrors({});
    setSubmitting(true);
    try {
      if (isCreate) {
        const payload: { name: string; slug?: string; default_language: string } = {
          name: name.trim(),
          default_language: defaultLanguage,
        };
        if (slug.trim()) payload.slug = slug.trim();
        const created = await createCompany(payload);
        navigate(`/admin/companies/${created.id}?saved=ok`, { replace: true });
        return;
      }
      if (numericId === null) return;
      const payload: { name: string; slug?: string; default_language: string } = {
        name: name.trim(),
        default_language: defaultLanguage,
      };
      if (isSuperAdmin) payload.slug = slug.trim();
      const updated = await updateCompany(numericId, payload);
      setCompany(updated);
      setName(updated.name);
      setSlug(updated.slug);
      setDefaultLanguage(updated.default_language);
      setSavedBanner("Company saved.");
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
    if (numericId === null) return;
    setActionBusy(true);
    setGeneralError("");
    try {
      await deactivateCompany(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/companies?deactivated=ok", { replace: true });
    } catch (err) {
      setGeneralError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setGeneralError("");
    try {
      await reactivateCompany(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/companies?reactivated=ok", { replace: true });
    } catch (err) {
      setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

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

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <form className="card" onSubmit={handleSubmit} style={{ padding: "20px 22px" }}>
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
            {fieldErrors.name && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.name}
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
            {fieldErrors.slug && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.slug}
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
            {fieldErrors.default_language && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.default_language}
              </div>
            )}
          </div>

          <div className="form-actions" style={{ marginTop: 12 }}>
            {!isCreate && company && company.is_active && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => deactivateDialogRef.current?.showModal()}
              >
                Deactivate
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim()}>
              {submitting ? "Saving…" : isCreate ? "Create company" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      <dialog
        ref={deactivateDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>Deactivate {company?.name ?? "company"}?</h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
          It will be hidden from non-super-admin users. Tickets attached to it remain visible to
          staff.
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
        <h3 style={{ marginBottom: 8 }}>Reactivate {company?.name ?? "company"}?</h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
          Reactivating restores it for all roles. Existing memberships and tickets are unchanged.
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
