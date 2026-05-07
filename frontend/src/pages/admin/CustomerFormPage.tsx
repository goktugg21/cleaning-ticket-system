import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
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

export function CustomerFormPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isCreate = id === undefined;
  const { t, i18n } = useTranslation("common");

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const languageOptions = useMemo(
    () => [
      { value: "nl", label: `${t("language_dutch")} (nl)` },
      { value: "en", label: `${t("language_english")} (en)` },
    ],
    [t],
  );

  const [savedBanner, setSavedBanner] = useSavedBanner({
    saved: t("customers.banner_saved"),
  });

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
      if (company === "") errs.company = t("customer_form.error_pick_company");
      if (building === "") errs.building = t("customer_form.error_pick_building");
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
    onEditSuccess: () => setSavedBanner(t("customers.banner_saved")),
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

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const customerName = customer?.name ?? t("customer_form.fallback");

  return (
    <div>
      <Link to="/admin/customers" className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("customer_form.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">
            {isCreate
              ? t("customers.create")
              : t("customer_form.edit_title", { name: customerName })}
          </h2>
          {!isCreate && customer && !customer.is_active && (
            <p className="page-sub">
              <span className="cell-tag cell-tag-closed">
                <i />
                {t("admin.status_inactive")}
              </span>
            </p>
          )}
        </div>
        {!isCreate && customer && !customer.is_active && isSuperAdmin && (
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
            <div className="form-section-title">{t("customer_form.card_label_title")}</div>
            <div className="form-section-helper">{t("customer_form.card_label_desc")}</div>
          <div className="form-2col">
            <div className="field">
              <label className="field-label" htmlFor="customer-company">
                {t("company")} *
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
                  {t("invitations.select_company_placeholder")}
                </option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
                {!isCreate &&
                  customer &&
                  !companies.some((c) => c.id === customer.company) && (
                    <option value={customer.company}>
                      {t("buildings.company_fallback", { id: customer.company })}
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
              <label className="field-label" htmlFor="customer-building">
                {t("building")} *
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
                  {company === ""
                    ? t("customer_form.select_company_first")
                    : t("customer_form.select_building_placeholder")}
                </option>
                {buildings.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
                {!isCreate &&
                  customer &&
                  !buildings.some((b) => b.id === customer.building) && (
                    <option value={customer.building}>
                      {t("customers.building_fallback", { id: customer.building })}
                    </option>
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
              {t("admin.col_name")} *
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
                {t("customers.col_contact_email")}
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
                {t("customer_form.field_phone")}
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
              {t("users.col_language")}
            </label>
            <select
              id="customer-language"
              className="field-select"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          </div>
          <div className="form-actions">
            {!isCreate && customer && customer.is_active && (
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
                  ? t("customers.create")
                  : t("admin_form.save_changes")}
            </button>
          </div>
        </form>
      )}

      {!isCreate && customer && (
        <section
          className="card"
          data-testid="section-customer-users"
          style={{ marginTop: 16, padding: "20px 22px" }}
        >
          <h3 className="section-title">{t("customer_form.section_users_title")}</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("customer_form.section_users_desc")}
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
                  <th>{t("customer_form.col_linked")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => (
                  <tr key={membership.id}>
                    <td className="td-subject">{membership.user_email}</td>
                    <td>{membership.user_full_name || "—"}</td>
                    <td className="td-date">
                      {new Date(membership.created_at).toLocaleDateString(dateLocale)}
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
                {t("customer_form.no_users_yet")}
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddMember}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-customer-user">
                {t("customer_form.add_user")}
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
        title={t("customer_form.dialog_deactivate_title", { name: customerName })}
        body={t("customer_form.dialog_deactivate_body")}
        confirmLabel={t("admin_form.deactivate")}
        onConfirm={handleConfirmDeactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reactivateDialogRef}
        title={t("customer_form.dialog_reactivate_title", { name: customerName })}
        body={t("customer_form.dialog_reactivate_body")}
        confirmLabel={t("admin_form.reactivate")}
        onConfirm={handleConfirmReactivate}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={removeDialogRef}
        title={t("customer_form.dialog_remove_title", {
          email: removeTarget?.user_email ?? "",
          name: customerName,
        })}
        body={t("customer_form.dialog_remove_body")}
        confirmLabel={t("admin_form.remove")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={memberBusy}
      />
    </div>
  );
}
