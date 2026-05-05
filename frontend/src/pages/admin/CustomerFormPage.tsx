import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { getApiError } from "../../api/client";
import {
  addCustomerUser,
  createCustomer,
  deactivateCustomer,
  getCustomer,
  listBuildings,
  listCompanies,
  listCustomerUsers,
  listUsers,
  reactivateCustomer,
  removeCustomerUser,
  updateCustomer,
} from "../../api/admin";
import type { AdminFieldErrors, CustomerWritePayload } from "../../api/admin";
import type {
  BuildingAdmin,
  CompanyAdmin,
  CustomerAdmin,
  CustomerUserMembership,
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

export function CustomerFormPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isCreate = id === undefined;

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [savedBanner, setSavedBanner] = useSavedBanner({ saved: "Customer saved." });

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

  const [company, setCompany] = useState<number | "">("");
  const [building, setBuilding] = useState<number | "">("");
  const [name, setName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("nl");

  const form = useEntityForm<CustomerAdmin, CustomerWritePayload>({
    id,
    fetchFn: getCustomer,
    createFn: createCustomer,
    updateFn: updateCustomer,
    validate: () => {
      if (!isCreate) return null;
      const errs: AdminFieldErrors = {};
      if (company === "") errs.company = "Pick a company.";
      if (building === "") errs.building = "Pick a building.";
      return Object.keys(errs).length > 0 ? errs : null;
    },
    buildPayload: () => {
      const payload: CustomerWritePayload = {
        name: name.trim(),
        contact_email: contactEmail.trim(),
        phone: phone.trim(),
        language,
      };
      if (isCreate) {
        if (company !== "") payload.company = Number(company);
        if (building !== "") payload.building = Number(building);
      }
      return payload;
    },
    applyEntity: (entity) => {
      setCompany(entity.company);
      setBuilding(entity.building);
      setName(entity.name);
      setContactEmail(entity.contact_email);
      setPhone(entity.phone);
      setLanguage(entity.language);
    },
    successPath: (entity) => `/admin/customers/${entity.id}?saved=ok`,
    onEditSuccess: () => setSavedBanner("Customer saved."),
  });
  const customer = form.entity;
  const numericId = form.numericId;

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // Membership section state.
  const [members, setMembers] = useState<CustomerUserMembership[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserAdmin[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");
  const [memberError, setMemberError] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<CustomerUserMembership | null>(null);
  const removeDialogRef = useRef<ConfirmDialogHandle>(null);

  const reloadMembers = useMemo(
    () => async () => {
      if (numericId === null) return;
      try {
        const [membersResponse, candidatesResponse] = await Promise.all([
          listCustomerUsers(numericId),
          listUsers({ role: "CUSTOMER_USER", page_size: 200 }),
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
      await addCustomerUser(numericId, Number(selectedUserId));
      setSelectedUserId("");
      await reloadMembers();
    } catch (err) {
      setMemberError(getApiError(err));
    } finally {
      setMemberBusy(false);
    }
  }

  function openRemoveDialog(membership: CustomerUserMembership) {
    setRemoveTarget(membership);
    removeDialogRef.current?.open();
  }

  async function handleConfirmRemove() {
    if (numericId === null || !removeTarget) return;
    setMemberBusy(true);
    setMemberError("");
    try {
      await removeCustomerUser(numericId, removeTarget.user_id);
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

  const companyLocked = useMemo(
    () => !isCreate || (companiesLoaded && companies.length <= 1),
    [isCreate, companiesLoaded, companies.length],
  );
  const buildingLocked = !isCreate;

  async function handleConfirmDeactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    form.setGeneralError("");
    try {
      await deactivateCustomer(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/customers?deactivated=ok", { replace: true });
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
      await reactivateCustomer(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/customers?reactivated=ok", { replace: true });
    } catch (err) {
      form.setGeneralError(getApiError(err));
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
              {form.fieldErrors.company && (
                <div className="alert-error login-error" role="alert">
                  {form.fieldErrors.company}
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
              {form.fieldErrors.building && (
                <div className="alert-error login-error" role="alert">
                  {form.fieldErrors.building}
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
            {form.fieldErrors.name && (
              <div className="alert-error login-error" role="alert">
                {form.fieldErrors.name}
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
              {form.fieldErrors.contact_email && (
                <div className="alert-error login-error" role="alert">
                  {form.fieldErrors.contact_email}
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
                onClick={() => deactivateDialogRef.current?.open()}
              >
                Deactivate
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={form.submitting || !name.trim()}>
              {form.submitting ? "Saving…" : isCreate ? "Create customer" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      {!isCreate && customer && (
        <section className="card" style={{ marginTop: 16, padding: "20px 22px" }}>
          <h3 className="section-title">Users</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            Customer-side users (CUSTOMER_USER role) linked to this customer. Add an existing user
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
                  <th>Linked</th>
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
                No users linked yet.
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddMember}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-customer-user">
                Add user
              </label>
              <select
                id="add-customer-user"
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
        title={`Deactivate ${customer?.name ?? "customer"}?`}
        body="It will be hidden from non-super-admin users. Tickets attached to it remain visible to staff."
        confirmLabel="Deactivate"
        onConfirm={handleConfirmDeactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reactivateDialogRef}
        title={`Reactivate ${customer?.name ?? "customer"}?`}
        body="Reactivating restores it for all roles. Existing memberships and tickets are unchanged."
        confirmLabel="Reactivate"
        onConfirm={handleConfirmReactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={removeDialogRef}
        title={`Remove ${removeTarget?.user_email ?? "user"} from ${customer?.name ?? "customer"}?`}
        body="Their other memberships are unaffected. They can be re-added later."
        confirmLabel="Remove"
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={memberBusy}
      />
    </div>
  );
}
