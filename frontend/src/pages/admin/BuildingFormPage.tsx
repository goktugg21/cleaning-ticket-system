import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  addBuildingManager,
  createBuilding,
  deactivateBuilding,
  getBuilding,
  listBuildingManagers,
  listCompanies,
  listUsers,
  reactivateBuilding,
  removeBuildingManager,
  updateBuilding,
} from "../../api/admin";
import type { BuildingWritePayload } from "../../api/admin";
import type {
  BuildingAdmin,
  BuildingManagerMembership,
  CompanyAdmin,
  UserAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useEntityForm } from "../../hooks/useEntityForm";
import { useSavedBanner } from "../../hooks/useSavedBanner";

export function BuildingFormPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isCreate = id === undefined;
  const { t, i18n } = useTranslation("common");

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [savedBanner, setSavedBanner] = useSavedBanner({
    saved: t("buildings.banner_saved"),
  });

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);

  const [company, setCompany] = useState<number | "">("");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [postalCode, setPostalCode] = useState("");

  const form = useEntityForm<BuildingAdmin, BuildingWritePayload>({
    id,
    fetchFn: getBuilding,
    createFn: createBuilding,
    updateFn: updateBuilding,
    validate: () => {
      if (isCreate && company === "") return { company: t("building_form.error_pick_company") };
      return null;
    },
    buildPayload: () => {
      const payload: BuildingWritePayload = {
        name: name.trim(),
        address: address.trim(),
        city: city.trim(),
        country: country.trim(),
        postal_code: postalCode.trim(),
      };
      if (isCreate && company !== "") payload.company = Number(company);
      return payload;
    },
    applyEntity: (entity) => {
      setCompany(entity.company);
      setName(entity.name);
      setAddress(entity.address);
      setCity(entity.city);
      setCountry(entity.country);
      setPostalCode(entity.postal_code);
    },
    successPath: (entity) => `/admin/buildings/${entity.id}?saved=ok`,
    onEditSuccess: () => setSavedBanner(t("buildings.banner_saved")),
  });
  const building = form.entity;
  const numericId = form.numericId;

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  // Membership section state.
  const [members, setMembers] = useState<BuildingManagerMembership[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserAdmin[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");
  const [memberError, setMemberError] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<BuildingManagerMembership | null>(null);
  const removeDialogRef = useRef<ConfirmDialogHandle>(null);

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
    removeDialogRef.current?.open();
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

  // Company is locked in edit mode; for create it is locked when the actor
  // only sees one company (the COMPANY_ADMIN-with-one-company case).
  const companyLocked = !isCreate || (companiesLoaded && companies.length <= 1);

  async function handleConfirmDeactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    form.setGeneralError("");
    try {
      await deactivateBuilding(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/buildings?deactivated=ok", { replace: true });
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
      await reactivateBuilding(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/buildings?reactivated=ok", { replace: true });
    } catch (err) {
      form.setGeneralError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const buildingName = building?.name ?? t("building_form.fallback");

  return (
    <div>
      <Link to="/admin/buildings" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("building_form.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">
            {isCreate
              ? t("buildings.create")
              : t("building_form.edit_title", { name: buildingName })}
          </h2>
          {!isCreate && building && !building.is_active && (
            <p className="page-sub">
              <span className="cell-tag cell-tag-closed">
                <i />
                {t("admin.status_inactive")}
              </span>
            </p>
          )}
        </div>
        {!isCreate && building && !building.is_active && isSuperAdmin && (
          <div className="page-header-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid="reactivate-button"
              onClick={() => reactivateDialogRef.current?.open()}
            >
              {t("admin_form.reactivate")}
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
        <form className="card" onSubmit={form.handleSubmit}>
          <div className="form-section">
            <div className="form-section-title">{t("building_form.card_label_title")}</div>
            <div className="form-section-helper">{t("building_form.card_label_desc")}</div>
          <div className="field">
            <label className="field-label" htmlFor="building-company">
              {t("company")} *
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
                {t("invitations.select_company_placeholder")}
              </option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
              {!isCreate && building && !companies.some((c) => c.id === building.company) && (
                <option value={building.company}>
                  {t("buildings.company_fallback", { id: building.company })}
                </option>
              )}
            </select>
            {form.fieldErrors.company && (
              <div className="alert-error login-error" role="alert">
                {form.fieldErrors.company}
              </div>
            )}
          </div>

          <div className="field">
            <label className="field-label" htmlFor="building-name">
              {t("admin.col_name")} *
            </label>
            <input
              id="building-name"
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
            <label className="field-label" htmlFor="building-address">
              {t("admin.col_address")}
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
                {t("building_form.field_city")}
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
                {t("building_form.field_postal_code")}
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
              {t("building_form.field_country")}
            </label>
            <input
              id="building-country"
              className="field-input"
              type="text"
              value={country}
              onChange={(event) => setCountry(event.target.value)}
            />
          </div>

          </div>
          <div className="form-actions">
            {!isCreate && building && building.is_active && (
              <button
                type="button"
                className="btn btn-ghost"
                data-testid="deactivate-button"
                onClick={() => deactivateDialogRef.current?.open()}
              >
                {t("admin_form.deactivate")}
              </button>
            )}
            <button type="submit" className="btn btn-primary" disabled={form.submitting || !name.trim()}>
              {form.submitting
                ? t("admin_form.saving")
                : isCreate
                  ? t("buildings.create")
                  : t("admin_form.save_changes")}
            </button>
          </div>
        </form>
      )}

      {!isCreate && building && (
        <section
          className="card"
          data-testid="section-managers"
          style={{ marginTop: 16, padding: "20px 22px" }}
        >
          <h3 className="section-title">{t("building_form.section_managers_title")}</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("building_form.section_managers_desc")}
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
                  <th>{t("users.col_email")}</th>
                  <th>{t("users.col_full_name")}</th>
                  <th>{t("admin_form.col_assigned")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => (
                  <tr key={membership.id}>
                    <td className="td-subject">{membership.user_email}</td>
                    <td>{membership.user_full_name || "—"}</td>
                    <td className="td-date">
                      {new Date(membership.assigned_at).toLocaleDateString(dateLocale)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openRemoveDialog(membership)}
                      >
                        {t("admin_form.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {members.length === 0 && (
              <p className="muted small" style={{ padding: "12px 0" }}>
                {t("building_form.no_managers_yet")}
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddMember}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-building-manager">
                {t("building_form.add_manager")}
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
                    ? t("admin_form.no_eligible_users")
                    : t("admin_form.select_user")}
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
              data-testid="member-add-button"
              disabled={memberBusy || selectedUserId === ""}
            >
              {memberBusy ? t("admin_form.adding") : t("admin_form.add")}
            </button>
          </form>
        </section>
      )}

      <ConfirmDialog
        ref={deactivateDialogRef}
        title={t("building_form.dialog_deactivate_title", { name: buildingName })}
        body={t("building_form.dialog_deactivate_body")}
        confirmLabel={t("admin_form.deactivate")}
        onConfirm={handleConfirmDeactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reactivateDialogRef}
        title={t("building_form.dialog_reactivate_title", { name: buildingName })}
        body={t("building_form.dialog_reactivate_body")}
        confirmLabel={t("admin_form.reactivate")}
        onConfirm={handleConfirmReactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={removeDialogRef}
        title={t("building_form.dialog_remove_title", {
          email: removeTarget?.user_email ?? "",
          name: buildingName,
        })}
        body={t("building_form.dialog_remove_body")}
        confirmLabel={t("admin_form.remove")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={memberBusy}
      />
    </div>
  );
}
