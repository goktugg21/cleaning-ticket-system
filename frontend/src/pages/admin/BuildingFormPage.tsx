import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  addBuildingManager,
  bulkLinkBuildings,
  createBuilding,
  getBuilding,
  listAllCompanies,
  listAllCustomers,
  listBuildingCustomers,
  listBuildingManagers,
  listUsers,
  removeBuildingManager,
  updateBuilding,
} from "../../api/admin";
import type { BuildingWritePayload } from "../../api/admin";
import type {
  BuildingAdmin,
  BuildingManagerMembership,
  CompanyAdmin,
  CustomerAdmin,
  CustomerBuildingMembership,
  UserAdmin,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { BoundedList } from "../../components/BoundedList";
import { EntityPicker } from "../../components/EntityPicker";
import { useToast } from "../../components/ToastProvider";
import { useEntityForm } from "../../hooks/useEntityForm";
import { useSavedBanner } from "../../hooks/useSavedBanner";

export function BuildingFormPage() {
  const { id } = useParams();
  const isCreate = id === undefined;
  const { t, i18n } = useTranslation("common");
  const { push: pushToast } = useToast();

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

  // Sprint 154 §H (building half) — the mirror image of the customer
  // form's linked-buildings section: pick the CUSTOMERS served here, in
  // create mode as well as edit mode.
  const [linkedCustomers, setLinkedCustomers] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [companyCustomers, setCompanyCustomers] = useState<CustomerAdmin[]>([]);
  const [customersToLink, setCustomersToLink] = useState<number[]>([]);
  const [pendingCustomerIds, setPendingCustomerIds] = useState<number[]>([]);
  const [customerLinkError, setCustomerLinkError] = useState("");
  const [customerLinkBusy, setCustomerLinkBusy] = useState(false);
  const [customerLinkToken, setCustomerLinkToken] = useState(0);

  const form = useEntityForm<BuildingAdmin, BuildingWritePayload>({
    id,
    fetchFn: getBuilding,
    // Sprint 154 §H — link the chosen customers in the same trip that
    // creates the building. The M:N rows need a building id, so the
    // create lands first. A link failure must NOT lose the created
    // building: it is swallowed and surfaced as a toast, which survives
    // the navigation to the detail page.
    createFn: async (payload) => {
      const created = await createBuilding(payload);
      if (pendingCustomerIds.length > 0) {
        try {
          await bulkLinkBuildings({
            buildings: [created.id],
            relation: "customers",
            targets: pendingCustomerIds,
            mode: "link",
          });
        } catch (err) {
          pushToast({
            variant: "error",
            title: t("building_form.create_link_failed"),
            description: getApiError(err),
          });
        }
      }
      return created;
    },
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
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
        if (isCreate && response.length === 1) {
          setCompany(response[0].id);
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

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const buildingName = building?.name ?? t("building_form.fallback");

  // Sprint 29 Batch 29.4 — back link points at the detail page when
  // editing (so Cancel and the back chevron land in the same place);
  // the create flow keeps the back-to-list shortcut.
  const backHref =
    isCreate || numericId === null
      ? "/admin/buildings"
      : `/admin/buildings/${numericId}`;
  const backLabel = isCreate
    ? t("building_form.back")
    : t("building_form.back_to_detail");

  // Sprint 154 §H — the customer candidate universe and (in edit mode)
  // the current links. Company-scoped: a customer of another provider
  // can never be served at this building, so offering one would be a
  // rejection waiting to happen.
  useEffect(() => {
    if (company === "") return;
    let cancelled = false;
    listAllCustomers({ is_active: "true", company })
      .then((rows) => {
        if (!cancelled) setCompanyCustomers(rows);
      })
      .catch(() => {
        if (!cancelled) setCompanyCustomers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [company]);

  // DERIVED, not cleared in the effect above. Clearing the fetched list
  // when `company` goes back to "" would be a synchronous setState in an
  // effect body — the exact thing CLAUDE.md §3 and the ESLint baseline
  // forbid. Deriving the empty case here is equivalent for the reader
  // and costs no render pass: a stale list can never be shown, because
  // "no company chosen" always resolves to [].
  const companyCustomerOptions = useMemo(
    () => (company === "" ? [] : companyCustomers),
    [company, companyCustomers],
  );

  useEffect(() => {
    if (isCreate || form.numericId === null) return;
    let cancelled = false;
    listBuildingCustomers(form.numericId)
      .then((rows) => {
        if (!cancelled) setLinkedCustomers(rows);
      })
      .catch(() => {
        if (!cancelled) setLinkedCustomers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isCreate, form.numericId, customerLinkToken]);

  const availableCustomersToLink = useMemo(() => {
    const linked = new Set(linkedCustomers.map((l) => l.customer));
    return companyCustomerOptions.filter((c) => !linked.has(c.id));
  }, [companyCustomerOptions, linkedCustomers]);

  async function handleAddCustomerLinks() {
    if (form.numericId === null || customersToLink.length === 0) return;
    setCustomerLinkError("");
    setCustomerLinkBusy(true);
    try {
      await bulkLinkBuildings({
        buildings: [form.numericId],
        relation: "customers",
        targets: customersToLink,
        mode: "link",
      });
      setCustomersToLink([]);
      setCustomerLinkToken((n) => n + 1);
    } catch (err) {
      setCustomerLinkError(getApiError(err));
    } finally {
      setCustomerLinkBusy(false);
    }
  }

  async function handleRemoveCustomerLink(customerId: number) {
    if (form.numericId === null) return;
    setCustomerLinkError("");
    setCustomerLinkBusy(true);
    try {
      await bulkLinkBuildings({
        buildings: [form.numericId],
        relation: "customers",
        targets: [customerId],
        mode: "unlink",
      });
      setCustomerLinkToken((n) => n + 1);
    } catch (err) {
      setCustomerLinkError(getApiError(err));
    } finally {
      setCustomerLinkBusy(false);
    }
  }

  return (
    <div>
      <Link to={backHref} className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {backLabel}
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
            {!isCreate && numericId !== null && (
              <Link
                to={`/admin/buildings/${numericId}`}
                className="btn btn-ghost"
                data-testid="building-edit-cancel"
              >
                {t("admin_form.cancel")}
              </Link>
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

      {/* Sprint 154 §H — the linked-customers section, in BOTH modes.
          In create mode the links cannot be written yet (there is no
          building id), so the choice is held and applied straight after
          the create; see the `createFn` wrapper above. */}
      <section
        className="card"
        data-testid="section-building-customers"
        style={{ marginTop: 16, padding: "20px 22px" }}
      >
        <h3 className="section-title">
          {t("building_form.section_customers_title")}
        </h3>
        <p className="muted small" style={{ marginBottom: 12 }}>
          {isCreate
            ? company === ""
              ? t("customer_form.select_company_first")
              : t("building_form.create_link_customers_hint")
            : t("building_form.section_customers_desc")}
        </p>

        {customerLinkError && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {customerLinkError}
          </div>
        )}

        {isCreate ? (
          company !== "" && (
            <EntityPicker
              options={companyCustomerOptions.map((c) => ({
                id: c.id,
                label: c.name,
                sublabel: c.contact_email,
              }))}
              selectedIds={pendingCustomerIds}
              onChange={setPendingCustomerIds}
              disabled={form.submitting}
              emptyText={t("building_form.no_eligible_customers")}
              testIdPrefix="building-form-create-customers"
              size="sm"
            />
          )
        ) : (
          <>
            <BoundedList
              size="md"
              count={linkedCustomers.length}
              ariaLabel={t("building_form.section_customers_title")}
              testIdPrefix="building-form-linked-customers"
              className="table-wrap"
              emptyState={
                <p className="muted small" style={{ padding: "12px 0" }}>
                  {t("building_form.no_customers_linked")}
                </p>
              }
            >
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("admin.col_name")}</th>
                    <th aria-label={t("admin.col_actions")} />
                  </tr>
                </thead>
                <tbody>
                  {linkedCustomers.map((link) => (
                    <tr key={link.id}>
                      <td className="td-subject">
                        <Link to={`/admin/customers/${link.customer}`}>
                          {link.customer_name || String(link.customer)}
                        </Link>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => handleRemoveCustomerLink(link.customer)}
                          disabled={customerLinkBusy}
                          data-testid={`building-form-unlink-customer-${link.customer}`}
                        >
                          {t("admin_form.remove")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </BoundedList>

            <div style={{ marginTop: 14 }}>
              <div className="detail-field-label" style={{ marginBottom: 6 }}>
                {t("building_form.add_customers")}
              </div>
              <EntityPicker
                options={availableCustomersToLink.map((c) => ({
                  id: c.id,
                  label: c.name,
                  sublabel: c.contact_email,
                }))}
                selectedIds={customersToLink}
                onChange={setCustomersToLink}
                disabled={customerLinkBusy}
                emptyText={t("building_form.no_eligible_customers")}
                testIdPrefix="building-form-add-customers"
                size="sm"
              />
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  marginTop: 10,
                }}
              >
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleAddCustomerLinks}
                  disabled={customerLinkBusy || customersToLink.length === 0}
                  data-testid="building-form-add-customers-button"
                >
                  {customerLinkBusy
                    ? t("admin_form.adding")
                    : t("admin_form.add")}
                </button>
              </div>
            </div>
          </>
        )}
      </section>

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
