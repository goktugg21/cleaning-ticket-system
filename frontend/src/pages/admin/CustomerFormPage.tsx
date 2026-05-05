import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { getApiError } from "../../api/client";
import {
  createCustomer,
  deactivateCustomer,
  extractAdminFieldErrors,
  getCustomer,
  listBuildings,
  listCompanies,
  reactivateCustomer,
  updateCustomer,
} from "../../api/admin";
import type { AdminFieldErrors } from "../../api/admin";
import type { BuildingAdmin, CompanyAdmin, CustomerAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";

const LANGUAGE_OPTIONS = [
  { value: "nl", label: "Dutch (nl)" },
  { value: "en", label: "English (en)" },
];

export function CustomerFormPage() {
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

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [company, setCompany] = useState<number | "">("");
  const [building, setBuilding] = useState<number | "">("");
  const [name, setName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("nl");

  const deactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const reactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    if (searchParams.get("saved") === "ok") {
      setSavedBanner("Customer saved.");
      const next = new URLSearchParams(searchParams);
      next.delete("saved");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    let cancelled = false;
    listCompanies({ is_active: "true", page_size: 200 })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response.results);
        if (isCreate && response.results.length === 1) {
          setCompany(response.results[0].id);
        }
      })
      .finally(() => {
        if (!cancelled) setCompaniesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isCreate]);

  useEffect(() => {
    if (company === "") {
      setBuildings([]);
      return;
    }
    let cancelled = false;
    listBuildings({ is_active: "true", page_size: 200, company })
      .then((response) => {
        if (!cancelled) setBuildings(response.results);
      })
      .catch(() => {
        if (!cancelled) setBuildings([]);
      });
    return () => {
      cancelled = true;
    };
  }, [company]);

  // In create mode, when the company changes, reset the building selection.
  // Edit mode keeps the original building (parents are locked anyway).
  useEffect(() => {
    if (!isCreate) return;
    if (
      building !== "" &&
      buildings.length > 0 &&
      !buildings.some((b) => b.id === building)
    ) {
      setBuilding("");
    }
  }, [isCreate, buildings, building]);

  useEffect(() => {
    if (isCreate || numericId === null) return;
    let cancelled = false;
    setLoading(true);
    getCustomer(numericId)
      .then((data) => {
        if (cancelled) return;
        setCustomer(data);
        setCompany(data.company);
        setBuilding(data.building);
        setName(data.name);
        setContactEmail(data.contact_email);
        setPhone(data.phone);
        setLanguage(data.language);
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

  const companyLocked = useMemo(
    () => !isCreate || (companiesLoaded && companies.length <= 1),
    [isCreate, companiesLoaded, companies.length],
  );
  const buildingLocked = !isCreate;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    setFieldErrors({});
    setSubmitting(true);
    try {
      if (isCreate) {
        if (company === "" || building === "") {
          setFieldErrors({
            ...(company === "" ? { company: "Pick a company." } : {}),
            ...(building === "" ? { building: "Pick a building." } : {}),
          });
          setSubmitting(false);
          return;
        }
        const created = await createCustomer({
          company: Number(company),
          building: Number(building),
          name: name.trim(),
          contact_email: contactEmail.trim(),
          phone: phone.trim(),
          language,
        });
        navigate(`/admin/customers/${created.id}?saved=ok`, { replace: true });
        return;
      }
      if (numericId === null) return;
      const updated = await updateCustomer(numericId, {
        name: name.trim(),
        contact_email: contactEmail.trim(),
        phone: phone.trim(),
        language,
      });
      setCustomer(updated);
      setSavedBanner("Customer saved.");
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
      await deactivateCustomer(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/customers?deactivated=ok", { replace: true });
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
      await reactivateCustomer(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/customers?reactivated=ok", { replace: true });
    } catch (err) {
      setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <div>
      <Link to="/admin/customers" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        Back to customers
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">
            {isCreate ? "Create customer" : `Edit ${customer?.name ?? "customer"}`}
          </h2>
          {!isCreate && customer && !customer.is_active && (
            <p className="page-sub">
              <span className="cell-tag cell-tag-closed">
                <i />
                Inactive
              </span>
            </p>
          )}
        </div>
        {!isCreate && customer && !customer.is_active && isSuperAdmin && (
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
          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="customer-company">
                Company *
              </label>
              <select
                id="customer-company"
                className="field-select"
                value={company === "" ? "" : String(company)}
                onChange={(event) => {
                  const v = event.target.value;
                  setCompany(v === "" ? "" : Number(v));
                }}
                disabled={companyLocked}
                required
              >
                <option value="" disabled>
                  Select company…
                </option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
                {!isCreate &&
                  customer &&
                  !companies.some((c) => c.id === customer.company) && (
                    <option value={customer.company}>Company #{customer.company}</option>
                  )}
              </select>
              {fieldErrors.company && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.company}
                </div>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="customer-building">
                Building *
              </label>
              <select
                id="customer-building"
                className="field-select"
                value={building === "" ? "" : String(building)}
                onChange={(event) => {
                  const v = event.target.value;
                  setBuilding(v === "" ? "" : Number(v));
                }}
                disabled={buildingLocked || company === ""}
                required
              >
                <option value="" disabled>
                  {company === "" ? "Select a company first" : "Select building…"}
                </option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
                {!isCreate &&
                  customer &&
                  !buildings.some((b) => b.id === customer.building) && (
                    <option value={customer.building}>Building #{customer.building}</option>
                  )}
              </select>
              {fieldErrors.building && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.building}
                </div>
              )}
            </div>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="customer-name">
              Name *
            </label>
            <input
              id="customer-name"
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

          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="customer-email">
                Contact email
              </label>
              <input
                id="customer-email"
                className="field-input"
                type="email"
                value={contactEmail}
                onChange={(event) => setContactEmail(event.target.value)}
              />
              {fieldErrors.contact_email && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.contact_email}
                </div>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="customer-phone">
                Phone
              </label>
              <input
                id="customer-phone"
                className="field-input"
                type="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
              />
            </div>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="customer-language">
              Language
            </label>
            <select
              id="customer-language"
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

          <div className="form-actions" style={{ marginTop: 12 }}>
            {!isCreate && customer && customer.is_active && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => deactivateDialogRef.current?.showModal()}
              >
                Deactivate
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim()}>
              {submitting ? "Saving…" : isCreate ? "Create customer" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      <dialog
        ref={deactivateDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>Deactivate {customer?.name ?? "customer"}?</h3>
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
        <h3 style={{ marginBottom: 8 }}>Reactivate {customer?.name ?? "customer"}?</h3>
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
