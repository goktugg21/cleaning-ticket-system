import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { getApiError } from "../../api/client";
import {
  addBuildingManager,
  createBuilding,
  deactivateBuilding,
  extractAdminFieldErrors,
  getBuilding,
  listBuildingManagers,
  listCompanies,
  listUsers,
  reactivateBuilding,
  removeBuildingManager,
  updateBuilding,
} from "../../api/admin";
import type { AdminFieldErrors } from "../../api/admin";
import type {
  BuildingAdmin,
  BuildingManagerMembership,
  CompanyAdmin,
  UserAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";

export function BuildingFormPage() {
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

  const [building, setBuilding] = useState<BuildingAdmin | null>(null);
  const [company, setCompany] = useState<number | "">("");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [postalCode, setPostalCode] = useState("");

  const deactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const reactivateDialogRef = useRef<HTMLDialogElement | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // Membership section state.
  const [members, setMembers] = useState<BuildingManagerMembership[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserAdmin[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");
  const [memberError, setMemberError] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<BuildingManagerMembership | null>(null);
  const removeDialogRef = useRef<HTMLDialogElement | null>(null);

  const reloadMembers = useMemo(
    () => async () => {
      if (numericId === null) return;
      try {
        const [membersResponse, candidatesResponse] = await Promise.all([
          listBuildingManagers(numericId),
          listUsers({ role: "BUILDING_MANAGER", page_size: 200 }),
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
      await addBuildingManager(numericId, Number(selectedUserId));
      setSelectedUserId("");
      await reloadMembers();
    } catch (err) {
      setMemberError(getApiError(err));
    } finally {
      setMemberBusy(false);
    }
  }

  function openRemoveDialog(membership: BuildingManagerMembership) {
    setRemoveTarget(membership);
    removeDialogRef.current?.showModal();
  }

  async function handleConfirmRemove() {
    if (numericId === null || !removeTarget) return;
    setMemberBusy(true);
    setMemberError("");
    try {
      await removeBuildingManager(numericId, removeTarget.user_id);
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
    if (searchParams.get("saved") === "ok") {
      setSavedBanner("Building saved.");
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
    if (isCreate || numericId === null) return;
    let cancelled = false;
    setLoading(true);
    getBuilding(numericId)
      .then((data) => {
        if (cancelled) return;
        setBuilding(data);
        setCompany(data.company);
        setName(data.name);
        setAddress(data.address);
        setCity(data.city);
        setCountry(data.country);
        setPostalCode(data.postal_code);
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

  // Company is locked in edit mode; for create it is locked when the actor
  // only sees one company (the COMPANY_ADMIN-with-one-company case).
  const companyLocked = !isCreate || (companiesLoaded && companies.length <= 1);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    setFieldErrors({});
    setSubmitting(true);
    try {
      if (isCreate) {
        if (company === "") {
          setFieldErrors({ company: "Pick a company." });
          setSubmitting(false);
          return;
        }
        const created = await createBuilding({
          company: Number(company),
          name: name.trim(),
          address: address.trim(),
          city: city.trim(),
          country: country.trim(),
          postal_code: postalCode.trim(),
        });
        navigate(`/admin/buildings/${created.id}?saved=ok`, { replace: true });
        return;
      }
      if (numericId === null) return;
      const updated = await updateBuilding(numericId, {
        name: name.trim(),
        address: address.trim(),
        city: city.trim(),
        country: country.trim(),
        postal_code: postalCode.trim(),
      });
      setBuilding(updated);
      setSavedBanner("Building saved.");
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
      await deactivateBuilding(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/buildings?deactivated=ok", { replace: true });
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
      await reactivateBuilding(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/buildings?reactivated=ok", { replace: true });
    } catch (err) {
      setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <div>
      <Link to="/admin/buildings" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        Back to buildings
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">
            {isCreate ? "Create building" : `Edit ${building?.name ?? "building"}`}
          </h2>
          {!isCreate && building && !building.is_active && (
            <p className="page-sub">
              <span className="cell-tag cell-tag-closed">
                <i />
                Inactive
              </span>
            </p>
          )}
        </div>
        {!isCreate && building && !building.is_active && isSuperAdmin && (
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
            <label className="field-label" htmlFor="building-company">
              Company *
            </label>
            <select
              id="building-company"
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
              {!isCreate && building && !companies.some((c) => c.id === building.company) && (
                <option value={building.company}>Company #{building.company}</option>
              )}
            </select>
            {fieldErrors.company && (
              <div className="alert-error login-error" role="alert">
                {fieldErrors.company}
              </div>
            )}
          </div>

          <div className="field">
            <label className="field-label" htmlFor="building-name">
              Name *
            </label>
            <input
              id="building-name"
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
            <label className="field-label" htmlFor="building-address">
              Address
            </label>
            <input
              id="building-address"
              className="field-input"
              type="text"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
            />
          </div>

          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="building-city">
                City
              </label>
              <input
                id="building-city"
                className="field-input"
                type="text"
                value={city}
                onChange={(event) => setCity(event.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="building-postal">
                Postal code
              </label>
              <input
                id="building-postal"
                className="field-input"
                type="text"
                value={postalCode}
                onChange={(event) => setPostalCode(event.target.value)}
              />
            </div>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="building-country">
              Country
            </label>
            <input
              id="building-country"
              className="field-input"
              type="text"
              value={country}
              onChange={(event) => setCountry(event.target.value)}
            />
          </div>

          <div className="form-actions" style={{ marginTop: 12 }}>
            {!isCreate && building && building.is_active && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => deactivateDialogRef.current?.showModal()}
              >
                Deactivate
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim()}>
              {submitting ? "Saving…" : isCreate ? "Create building" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      {!isCreate && building && (
        <section className="card" style={{ marginTop: 16, padding: "20px 22px" }}>
          <h3 className="section-title">Managers</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            Users with the BUILDING_MANAGER role assigned to this building. Add an existing user
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
                  <th>Assigned</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => (
                  <tr key={membership.id}>
                    <td className="td-subject">{membership.user_email}</td>
                    <td>{membership.user_full_name || "—"}</td>
                    <td className="td-date">
                      {new Date(membership.assigned_at).toLocaleDateString()}
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
                No managers assigned yet.
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddMember}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-building-manager">
                Add manager
              </label>
              <select
                id="add-building-manager"
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

      <dialog
        ref={deactivateDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>Deactivate {building?.name ?? "building"}?</h3>
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
        <h3 style={{ marginBottom: 8 }}>Reactivate {building?.name ?? "building"}?</h3>
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

      <dialog
        ref={removeDialogRef}
        style={{ padding: 24, borderRadius: 8, border: "1px solid var(--border)", maxWidth: 460 }}
      >
        <h3 style={{ marginBottom: 8 }}>
          Remove {removeTarget?.user_email ?? "manager"} from {building?.name ?? "building"}?
        </h3>
        <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
          Their other memberships are unaffected. They can be re-added later.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              removeDialogRef.current?.close();
              setRemoveTarget(null);
            }}
            disabled={memberBusy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleConfirmRemove}
            disabled={memberBusy}
          >
            {memberBusy ? "Removing…" : "Remove"}
          </button>
        </div>
      </dialog>
    </div>
  );
}
