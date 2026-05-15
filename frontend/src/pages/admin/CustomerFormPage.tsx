import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  addCustomerBuilding,
  addCustomerUser,
  addCustomerUserAccess,
  createCustomer,
  deactivateCustomer,
  getCustomer,
  getCustomerPolicy,
  listBuildings,
  listCompanies,
  listCustomerBuildings,
  listCustomerUserAccess,
  listCustomerUsers,
  listUsers,
  reactivateCustomer,
  removeCustomerBuilding,
  removeCustomerUser,
  removeCustomerUserAccess,
  updateCustomer,
  updateCustomerPolicy,
  updateCustomerUserAccess,
  updateCustomerUserAccessRole,
} from "../../api/admin";
import type { AdminFieldErrors, CustomerWritePayload } from "../../api/admin";
import type {
  BuildingAdmin,
  CompanyAdmin,
  CustomerAccessRole,
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerCompanyPolicyAdmin,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
  UserAdmin,
} from "../../api/types";
import { CUSTOMER_PERMISSION_KEYS } from "../../api/types";

// Sprint 27E — 3-way control per permission key. "inherit" means
// "remove the key from `permission_overrides`" (the resolver falls
// through to policy + role default); "grant"/"revoke" set the
// override boolean explicitly.
type OverrideTriState = "inherit" | "grant" | "revoke";

function tristateFromOverride(
  overrides: Record<string, boolean>,
  key: string,
): OverrideTriState {
  if (!(key in overrides)) return "inherit";
  return overrides[key] ? "grant" : "revoke";
}

function buildOverridesPayload(
  draft: Record<string, OverrideTriState>,
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const [key, value] of Object.entries(draft)) {
    if (value === "grant") out[key] = true;
    else if (value === "revoke") out[key] = false;
    // "inherit" → omit (full-replacement semantics on the server)
  }
  return out;
}
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
  // Sprint 23B — assigned-staff contact visibility policy. Defaults
  // mirror the backend model defaults (all True). The backend gate
  // is IsSuperAdminOrCompanyAdmin on CustomerViewSet; the buildings
  // serializer surfaces these as writable, so OSIUS Admin and the
  // owning Company Admin can edit them here. CUSTOMER_USER never
  // reaches this page.
  const [showAssignedStaffName, setShowAssignedStaffName] = useState(true);
  const [showAssignedStaffEmail, setShowAssignedStaffEmail] = useState(true);
  const [showAssignedStaffPhone, setShowAssignedStaffPhone] = useState(true);

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
        show_assigned_staff_name: showAssignedStaffName,
        show_assigned_staff_email: showAssignedStaffEmail,
        show_assigned_staff_phone: showAssignedStaffPhone,
      };
      if (isCreate) {
        if (company !== "") payload.company = Number(company);
        if (building !== "") payload.building = Number(building);
      }
      return payload;
    },
    applyEntity: (entity) => {
      setCompany(entity.company);
      // Sprint 14: legacy building can be null on consolidated customers.
      setBuilding(entity.building ?? "");
      setName(entity.name);
      setContactEmail(entity.contact_email);
      setPhone(entity.phone);
      setLanguage(entity.language);
      // Sprint 23B — hydrate contact-visibility flags. Backend
      // ensures these are always present on read responses (model
      // defaults are True), so the `?? true` is belt-and-suspenders
      // for any pre-Sprint-23A customer record that somehow lacks
      // them in a serialized snapshot.
      setShowAssignedStaffName(entity.show_assigned_staff_name ?? true);
      setShowAssignedStaffEmail(entity.show_assigned_staff_email ?? true);
      setShowAssignedStaffPhone(entity.show_assigned_staff_phone ?? true);
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

  // Sprint 14 — linked-buildings section state.
  const [linkedBuildings, setLinkedBuildings] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [allCompanyBuildings, setAllCompanyBuildings] = useState<BuildingAdmin[]>(
    [],
  );
  const [selectedBuildingToLink, setSelectedBuildingToLink] = useState<
    number | ""
  >("");
  const [buildingLinkError, setBuildingLinkError] = useState("");
  const [buildingLinkBusy, setBuildingLinkBusy] = useState(false);
  const [unlinkBuildingTarget, setUnlinkBuildingTarget] =
    useState<CustomerBuildingMembership | null>(null);
  const unlinkBuildingDialogRef = useRef<ConfirmDialogHandle>(null);

  // Sprint 14 — per-customer-user building access state.
  // Indexed by user_id since the membership row is keyed on user under
  // a fixed customer (the unique constraint).
  const [accessByUserId, setAccessByUserId] = useState<
    Record<number, CustomerUserBuildingAccess[]>
  >({});
  const [accessBusyUserId, setAccessBusyUserId] = useState<number | null>(null);
  const [accessError, setAccessError] = useState("");
  const [revokeAccessTarget, setRevokeAccessTarget] = useState<{
    membership: CustomerUserMembership;
    access: CustomerUserBuildingAccess;
  } | null>(null);
  const revokeAccessDialogRef = useRef<ConfirmDialogHandle>(null);

  // Sprint 27E — permission-override editor state. When the user
  // clicks "Edit permissions" on an access pill, we open a per-access
  // section below the row with a 3-way (Inherit/Grant/Revoke) control
  // per CUSTOMER_PERMISSION_KEY. Sending an empty dict on save means
  // "Inherit every key" (backend full-replacement semantics).
  const [editingOverrideFor, setEditingOverrideFor] = useState<{
    membership: CustomerUserMembership;
    access: CustomerUserBuildingAccess;
  } | null>(null);
  const [overrideDraft, setOverrideDraft] = useState<
    Record<string, OverrideTriState>
  >({});
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideBanner, setOverrideBanner] = useSavedBanner({
    saved: t("customer_form.access_overrides_saved_banner"),
  });

  // Sprint 27E — CustomerCompanyPolicy panel state (closes G-F5).
  const [policy, setPolicy] = useState<CustomerCompanyPolicyAdmin | null>(null);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policyError, setPolicyError] = useState("");
  const [policySaving, setPolicySaving] = useState(false);
  const [policyDraft, setPolicyDraft] = useState<
    Pick<
      CustomerCompanyPolicyAdmin,
      | "customer_users_can_create_tickets"
      | "customer_users_can_approve_ticket_completion"
      | "customer_users_can_create_extra_work"
      | "customer_users_can_approve_extra_work_pricing"
    >
  >({
    customer_users_can_create_tickets: true,
    customer_users_can_approve_ticket_completion: true,
    customer_users_can_create_extra_work: true,
    customer_users_can_approve_extra_work_pricing: true,
  });
  const [policyBanner, setPolicyBanner] = useSavedBanner({
    saved: t("customer_form.policy_saved_banner"),
  });

  const isSelfAccess = (access: CustomerUserBuildingAccess) =>
    me?.id === access.user_id;

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

  // Sprint 14 — linked-buildings reload + add/remove handlers.

  const reloadLinkedBuildings = useMemo(
    () => async () => {
      if (numericId === null || customer === null) return;
      try {
        const [linksResponse, companyBuildingsResponse] = await Promise.all([
          listCustomerBuildings(numericId),
          // Pull the company's buildings so we can offer "available to
          // link" as the difference. is_active=true keeps inactive
          // buildings out of the dropdown; the operator can still see
          // them in the linked list if they were linked previously.
          listBuildings({
            is_active: "true",
            page_size: 200,
            company: customer.company,
          }),
        ]);
        setLinkedBuildings(linksResponse.results);
        setAllCompanyBuildings(companyBuildingsResponse.results);
      } catch (err) {
        setBuildingLinkError(getApiError(err));
      }
    },
    [numericId, customer],
  );

  useEffect(() => {
    if (isCreate || numericId === null || customer === null) return;
    reloadLinkedBuildings();
  }, [isCreate, numericId, customer, reloadLinkedBuildings]);

  async function handleAddBuildingLink(event: FormEvent) {
    event.preventDefault();
    if (numericId === null || selectedBuildingToLink === "") return;
    setBuildingLinkError("");
    setBuildingLinkBusy(true);
    try {
      await addCustomerBuilding(numericId, Number(selectedBuildingToLink));
      setSelectedBuildingToLink("");
      await reloadLinkedBuildings();
    } catch (err) {
      setBuildingLinkError(getApiError(err));
    } finally {
      setBuildingLinkBusy(false);
    }
  }

  function openUnlinkBuildingDialog(link: CustomerBuildingMembership) {
    setUnlinkBuildingTarget(link);
    unlinkBuildingDialogRef.current?.open();
  }

  async function handleConfirmUnlinkBuilding() {
    if (numericId === null || !unlinkBuildingTarget) return;
    setBuildingLinkBusy(true);
    setBuildingLinkError("");
    try {
      await removeCustomerBuilding(
        numericId,
        unlinkBuildingTarget.building_id,
      );
      unlinkBuildingDialogRef.current?.close();
      setUnlinkBuildingTarget(null);
      await reloadLinkedBuildings();
      // Cascade: removing a customer↔building also revokes access
      // rows for that pair on the backend; refetch every user's
      // access list so the UI reflects it.
      await reloadAllUserAccess();
    } catch (err) {
      setBuildingLinkError(getApiError(err));
      unlinkBuildingDialogRef.current?.close();
    } finally {
      setBuildingLinkBusy(false);
    }
  }

  // Sprint 14 — per-user building access loaders + handlers.

  const reloadAllUserAccess = useMemo(
    () => async () => {
      if (numericId === null) return;
      // Fetch each member's access list. For a small pilot population
      // this is fine; if the membership list grows beyond ~20 users
      // we can paginate or batch it. Sequential to keep the UI
      // deterministic; failures on one user do not poison the others.
      const next: Record<number, CustomerUserBuildingAccess[]> = {};
      for (const membership of members) {
        try {
          const response = await listCustomerUserAccess(
            numericId,
            membership.user_id,
          );
          next[membership.user_id] = response.results;
        } catch {
          next[membership.user_id] = [];
        }
      }
      setAccessByUserId(next);
    },
    [numericId, members],
  );

  useEffect(() => {
    if (isCreate || numericId === null) return;
    if (members.length === 0) {
      setAccessByUserId({});
      return;
    }
    reloadAllUserAccess();
  }, [isCreate, numericId, members, reloadAllUserAccess]);

  async function handleAddAccess(
    membership: CustomerUserMembership,
    buildingId: number,
  ) {
    if (numericId === null) return;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await addCustomerUserAccess(numericId, membership.user_id, buildingId);
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setAccessBusyUserId(null);
    }
  }

  // Sprint 23C — change a customer-user's per-building access_role.
  // PATCHes /api/customers/<id>/users/<uid>/access/<bid>/. Permission
  // gate: SUPER_ADMIN or COMPANY_ADMIN of the customer's company.
  // Optimistic refetch on success so the row reflects the new role
  // (and the access pill background, which keys on is_active).
  async function handleAccessRoleChange(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
    newRole: CustomerAccessRole,
  ) {
    if (numericId === null) return;
    if (newRole === access.access_role) return;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await updateCustomerUserAccessRole(
        numericId,
        membership.user_id,
        access.building_id,
        newRole,
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setAccessBusyUserId(null);
    }
  }

  function openRevokeAccessDialog(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) {
    setRevokeAccessTarget({ membership, access });
    revokeAccessDialogRef.current?.open();
  }

  // Sprint 27E — flip `is_active` on an access row. Backend
  // `IsSuperAdminOrCompanyAdminForCompany` gate + Sprint 27C
  // self-edit guard apply; we mirror the self-edit guard in the UI
  // (button disabled) so an actor never sees a 403 toast for their
  // own row.
  async function handleToggleAccessActive(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
    nextActive: boolean,
  ) {
    if (numericId === null) return;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await updateCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
        { is_active: nextActive },
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setAccessBusyUserId(null);
    }
  }

  // Sprint 27E — open the per-access override editor.
  function openOverrideEditor(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) {
    const draft: Record<string, OverrideTriState> = {};
    for (const key of CUSTOMER_PERMISSION_KEYS) {
      draft[key] = tristateFromOverride(access.permission_overrides, key);
    }
    setOverrideDraft(draft);
    setEditingOverrideFor({ membership, access });
  }

  function closeOverrideEditor() {
    setEditingOverrideFor(null);
    setOverrideDraft({});
  }

  async function handleSaveOverrides() {
    if (numericId === null || !editingOverrideFor) return;
    const { membership, access } = editingOverrideFor;
    setOverrideSaving(true);
    setAccessError("");
    try {
      await updateCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
        { permission_overrides: buildOverridesPayload(overrideDraft) },
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
      setOverrideBanner(t("customer_form.access_overrides_saved_banner"));
      closeOverrideEditor();
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setOverrideSaving(false);
    }
  }

  async function handleConfirmRevokeAccess() {
    if (numericId === null || !revokeAccessTarget) return;
    const { membership, access } = revokeAccessTarget;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await removeCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
      revokeAccessDialogRef.current?.close();
      setRevokeAccessTarget(null);
    } catch (err) {
      setAccessError(getApiError(err));
      revokeAccessDialogRef.current?.close();
    } finally {
      setAccessBusyUserId(null);
    }
  }

  // Sprint 27E — load the per-customer policy row when we have an
  // id (edit mode only). The backend signal guarantees the row
  // exists for every Customer; this is a plain GET.
  useEffect(() => {
    if (isCreate || numericId === null) return;
    let cancelled = false;
    setPolicyLoading(true);
    getCustomerPolicy(numericId)
      .then((data) => {
        if (cancelled) return;
        setPolicy(data);
        setPolicyDraft({
          customer_users_can_create_tickets: data.customer_users_can_create_tickets,
          customer_users_can_approve_ticket_completion:
            data.customer_users_can_approve_ticket_completion,
          customer_users_can_create_extra_work:
            data.customer_users_can_create_extra_work,
          customer_users_can_approve_extra_work_pricing:
            data.customer_users_can_approve_extra_work_pricing,
        });
        setPolicyError("");
      })
      .catch((err) => {
        if (!cancelled) setPolicyError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setPolicyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isCreate, numericId]);

  async function handleSavePolicy(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    setPolicySaving(true);
    setPolicyError("");
    try {
      const updated = await updateCustomerPolicy(numericId, policyDraft);
      setPolicy(updated);
      setPolicyDraft({
        customer_users_can_create_tickets: updated.customer_users_can_create_tickets,
        customer_users_can_approve_ticket_completion:
          updated.customer_users_can_approve_ticket_completion,
        customer_users_can_create_extra_work:
          updated.customer_users_can_create_extra_work,
        customer_users_can_approve_extra_work_pricing:
          updated.customer_users_can_approve_extra_work_pricing,
      });
      setPolicyBanner(t("customer_form.policy_saved_banner"));
    } catch (err) {
      setPolicyError(getApiError(err));
    } finally {
      setPolicySaving(false);
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

  // Sprint 14 — buildings available to link: every active building
  // in the customer's company that is NOT already linked.
  const linkedBuildingIds = useMemo(
    () => new Set(linkedBuildings.map((l) => l.building_id)),
    [linkedBuildings],
  );
  const availableBuildingsToLink = useMemo(
    () => allCompanyBuildings.filter((b) => !linkedBuildingIds.has(b.id)),
    [allCompanyBuildings, linkedBuildingIds],
  );

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
                  customer.building !== null &&
                  !buildings.some((b) => b.id === customer.building) && (
                    <option value={customer.building}>
                      {t("customers.building_fallback", {
                        id: customer.building,
                      })}
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
          {/* Sprint 23B — Assigned-staff contact-visibility policy.
              Default True; toggling off scrubs the corresponding
              field from the ticket-detail payload that CUSTOMER_USER
              receives. Other roles always see full staff contact
              info regardless of these toggles. */}
          <div className="form-section" data-testid="contact-visibility-section">
            <div className="form-section-title">
              {t("customer_form.contact_visibility_title")}
            </div>
            <div className="form-section-helper">
              {t("customer_form.contact_visibility_helper")}
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={showAssignedStaffName}
                  onChange={(event) =>
                    setShowAssignedStaffName(event.target.checked)
                  }
                  data-testid="show-assigned-staff-name"
                />
                <span>{t("customer_form.show_assigned_staff_name")}</span>
              </label>
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={showAssignedStaffEmail}
                  onChange={(event) =>
                    setShowAssignedStaffEmail(event.target.checked)
                  }
                  data-testid="show-assigned-staff-email"
                />
                <span>{t("customer_form.show_assigned_staff_email")}</span>
              </label>
            </div>
            <div className="field">
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={showAssignedStaffPhone}
                  onChange={(event) =>
                    setShowAssignedStaffPhone(event.target.checked)
                  }
                  data-testid="show-assigned-staff-phone"
                />
                <span>{t("customer_form.show_assigned_staff_phone")}</span>
              </label>
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
          data-testid="section-customer-buildings"
          style={{ marginTop: 16, padding: "20px 22px" }}
        >
          <h3 className="section-title">
            {t("customer_form.section_buildings_title")}
          </h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("customer_form.section_buildings_desc")}
          </p>

          {buildingLinkError && (
            <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
              {buildingLinkError}
            </div>
          )}

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("admin.col_name")}</th>
                  <th>{t("admin.col_address")}</th>
                  <th>{t("customer_form.col_linked")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {linkedBuildings.map((link) => (
                  <tr key={link.id}>
                    <td className="td-subject">{link.building_name}</td>
                    <td>{link.building_address || "—"}</td>
                    <td className="td-date">
                      {new Date(link.created_at).toLocaleDateString(dateLocale)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openUnlinkBuildingDialog(link)}
                        disabled={buildingLinkBusy}
                      >
                        {t("admin_form.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {linkedBuildings.length === 0 && (
              <p className="muted small" style={{ padding: "12px 0" }}>
                {t("customer_form.no_buildings_linked")}
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddBuildingLink}
            style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-customer-building">
                {t("customer_form.add_building")}
              </label>
              <select
                id="add-customer-building"
                className="field-select"
                value={
                  selectedBuildingToLink === ""
                    ? ""
                    : String(selectedBuildingToLink)
                }
                onChange={(event) => {
                  const v = event.target.value;
                  setSelectedBuildingToLink(v === "" ? "" : Number(v));
                }}
                disabled={
                  buildingLinkBusy || availableBuildingsToLink.length === 0
                }
              >
                <option value="">
                  {availableBuildingsToLink.length === 0
                    ? t("customer_form.no_eligible_buildings")
                    : t("customer_form.select_building_to_add")}
                </option>
                {availableBuildingsToLink.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              data-testid="building-link-add-button"
              disabled={buildingLinkBusy || selectedBuildingToLink === ""}
            >
              {buildingLinkBusy ? t("admin_form.adding") : t("admin_form.add")}
            </button>
          </form>
        </section>
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

          {(memberError || accessError) && (
            <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
              {memberError || accessError}
            </div>
          )}

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("users.col_email")}</th>
                  <th>{t("users.col_full_name")}</th>
                  <th>{t("customer_form.col_user_access")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => {
                  const userAccess =
                    accessByUserId[membership.user_id] ?? [];
                  const userAccessBuildingIds = new Set(
                    userAccess.map((a) => a.building_id),
                  );
                  const grantableBuildings = linkedBuildings.filter(
                    (l) => !userAccessBuildingIds.has(l.building_id),
                  );
                  const isThisUserBusy =
                    accessBusyUserId === membership.user_id;
                  return (
                    <tr key={membership.id}>
                      <td className="td-subject">{membership.user_email}</td>
                      <td>{membership.user_full_name || "—"}</td>
                      <td>
                        {userAccess.length === 0 ? (
                          <p
                            className="muted small"
                            style={{ marginBottom: 6 }}
                          >
                            {t("customer_form.access_no_buildings")}
                          </p>
                        ) : (
                          <div
                            style={{
                              display: "flex",
                              gap: 6,
                              flexWrap: "wrap",
                              marginBottom: 6,
                            }}
                          >
                            {userAccess.map((access) => {
                              // Sprint 23C — inline access_role
                              // editor. Sprint 27E adds: an Active
                              // checkbox (PATCH is_active), an
                              // "Edit permissions" button that opens
                              // the per-key override editor section
                              // below, and the Sprint 27C self-edit
                              // guard mirrored in the UI so actor
                              // controls are disabled on their own
                              // access row.
                              const isSelf = isSelfAccess(access);
                              return (
                                <span
                                  key={access.id}
                                  className="badge badge-pill"
                                  data-testid="customer-access-badge"
                                  style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: 6,
                                    padding: "2px 8px",
                                    background:
                                      access.is_active === false
                                        ? "var(--surface-3, var(--surface-2))"
                                        : "var(--surface-2)",
                                    border: "1px solid var(--border)",
                                    borderRadius: 999,
                                    fontSize: 12,
                                    opacity:
                                      access.is_active === false ? 0.6 : 1,
                                  }}
                                >
                                  <span>{access.building_name}</span>
                                  <span aria-hidden="true">·</span>
                                  <select
                                    className="customer-access-role-select"
                                    data-testid="customer-access-role-select"
                                    data-user-id={membership.user_id}
                                    data-building-id={access.building_id}
                                    value={access.access_role}
                                    disabled={isThisUserBusy || isSelf}
                                    onChange={(event) =>
                                      handleAccessRoleChange(
                                        membership,
                                        access,
                                        event.target.value as CustomerAccessRole,
                                      )
                                    }
                                    aria-label={t(
                                      "customer_form.access_role_edit_label",
                                    )}
                                    style={{
                                      fontSize: 11,
                                      padding: "0 4px",
                                      height: 20,
                                      border: "1px solid var(--border)",
                                      borderRadius: 4,
                                      background: "transparent",
                                    }}
                                  >
                                    <option value="CUSTOMER_USER">
                                      {t("access_role.customer_user")}
                                    </option>
                                    <option value="CUSTOMER_LOCATION_MANAGER">
                                      {t(
                                        "access_role.customer_location_manager",
                                      )}
                                    </option>
                                    <option value="CUSTOMER_COMPANY_ADMIN">
                                      {t(
                                        "access_role.customer_company_admin",
                                      )}
                                    </option>
                                  </select>
                                  <label
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: 4,
                                      fontSize: 11,
                                      cursor:
                                        isThisUserBusy || isSelf
                                          ? "default"
                                          : "pointer",
                                    }}
                                    title={t(
                                      "customer_form.access_active_hint",
                                    )}
                                  >
                                    <input
                                      type="checkbox"
                                      data-testid="customer-access-active-toggle"
                                      data-user-id={membership.user_id}
                                      data-building-id={access.building_id}
                                      checked={access.is_active !== false}
                                      disabled={isThisUserBusy || isSelf}
                                      onChange={(event) =>
                                        handleToggleAccessActive(
                                          membership,
                                          access,
                                          event.target.checked,
                                        )
                                      }
                                    />
                                    <span>
                                      {t(
                                        "customer_form.access_active_label",
                                      )}
                                    </span>
                                  </label>
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-xs"
                                    data-testid="customer-access-overrides-button"
                                    data-user-id={membership.user_id}
                                    data-building-id={access.building_id}
                                    style={{
                                      height: 18,
                                      padding: "0 6px",
                                      fontSize: 11,
                                    }}
                                    onClick={() =>
                                      openOverrideEditor(membership, access)
                                    }
                                    disabled={isThisUserBusy}
                                  >
                                    {t(
                                      "customer_form.access_overrides_button",
                                    )}
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-xs"
                                    style={{
                                      height: 18,
                                      padding: "0 6px",
                                      fontSize: 11,
                                    }}
                                    onClick={() =>
                                      openRevokeAccessDialog(
                                        membership,
                                        access,
                                      )
                                    }
                                    disabled={isThisUserBusy}
                                    aria-label={t(
                                      "customer_form.access_remove_button",
                                    )}
                                  >
                                    ×
                                  </button>
                                </span>
                              );
                            })}
                          </div>
                        )}
                        <div style={{ display: "flex", gap: 6 }}>
                          <select
                            className="field-select"
                            style={{ flex: 1 }}
                            value=""
                            onChange={(event) => {
                              const v = event.target.value;
                              if (v === "") return;
                              handleAddAccess(membership, Number(v));
                              event.target.value = "";
                            }}
                            disabled={
                              isThisUserBusy || grantableBuildings.length === 0
                            }
                          >
                            <option value="">
                              {grantableBuildings.length === 0
                                ? t("customer_form.access_no_more")
                                : t(
                                    "customer_form.access_select_placeholder",
                                  )}
                            </option>
                            {grantableBuildings.map((l) => (
                              <option key={l.id} value={l.building_id}>
                                {l.building_name}
                              </option>
                            ))}
                          </select>
                        </div>
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
                  );
                })}
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

      {/* Sprint 27E — per-access override editor panel. Opens
          inline below the users section when "Edit permissions" is
          clicked on any access pill above. Save fires
          handleSaveOverrides which PATCHes permission_overrides
          (full replacement) and re-fetches the row. */}
      {!isCreate && customer && editingOverrideFor && (
        <section
          className="card"
          data-testid="section-customer-overrides-editor"
          style={{ marginTop: 16, padding: "20px 22px" }}
        >
          <h3 className="section-title">
            {t("customer_form.access_overrides_section_title", {
              email: editingOverrideFor.access.user_email,
              building: editingOverrideFor.access.building_name,
            })}
          </h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("customer_form.access_overrides_section_helper")}
          </p>

          {overrideBanner && (
            <div className="alert-info" role="status" style={{ marginBottom: 12 }}>
              {overrideBanner}
            </div>
          )}
          {isSelfAccess(editingOverrideFor.access) && (
            <div className="alert-warn" role="alert" style={{ marginBottom: 12 }}>
              {t("customer_form.access_overrides_self_edit_warning")}
            </div>
          )}
          {editingOverrideFor.access.is_active === false && (
            <div className="alert-warn" role="alert" style={{ marginBottom: 12 }}>
              {t("customer_form.access_overrides_inactive_warning")}
            </div>
          )}

          <div className="table-wrap">
            <table className="data-table" data-testid="customer-overrides-table">
              <tbody>
                {CUSTOMER_PERMISSION_KEYS.map((key) => {
                  const value = overrideDraft[key] ?? "inherit";
                  return (
                    <tr key={key} data-testid="customer-overrides-row" data-permission-key={key}>
                      <td className="td-subject">
                        {t(`customer_form.permission_key.${key}`)}
                        <div
                          className="muted small"
                          style={{ fontFamily: "monospace", fontSize: 11 }}
                        >
                          {key}
                        </div>
                      </td>
                      <td>
                        <div
                          role="radiogroup"
                          aria-label={key}
                          style={{ display: "inline-flex", gap: 12 }}
                        >
                          {(["inherit", "grant", "revoke"] as const).map((opt) => (
                            <label
                              key={opt}
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 4,
                                fontSize: 12,
                                cursor: isSelfAccess(editingOverrideFor.access)
                                  ? "default"
                                  : "pointer",
                              }}
                            >
                              <input
                                type="radio"
                                name={`override-${key}`}
                                value={opt}
                                data-testid="customer-overrides-radio"
                                data-permission-key={key}
                                data-tristate={opt}
                                checked={value === opt}
                                disabled={
                                  overrideSaving ||
                                  isSelfAccess(editingOverrideFor.access)
                                }
                                onChange={() =>
                                  setOverrideDraft((prev) => ({
                                    ...prev,
                                    [key]: opt,
                                  }))
                                }
                              />
                              <span>
                                {t(`customer_form.access_overrides_${opt}`)}
                              </span>
                            </label>
                          ))}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div
            className="form-actions"
            style={{ display: "flex", gap: 8, marginTop: 12 }}
          >
            <button
              type="button"
              className="btn btn-ghost"
              onClick={closeOverrideEditor}
              disabled={overrideSaving}
              data-testid="customer-overrides-close"
            >
              {t("customer_form.access_overrides_close")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSaveOverrides}
              data-testid="customer-overrides-save"
              disabled={
                overrideSaving || isSelfAccess(editingOverrideFor.access)
              }
            >
              {overrideSaving
                ? t("admin_form.saving")
                : t("customer_form.access_overrides_save")}
            </button>
          </div>
        </section>
      )}

      {/* Sprint 27E — CustomerCompanyPolicy panel. Only the
          permission-policy booleans live here; the three
          show_assigned_staff_* mirrors remain on the parent form
          (and on the Customer model) until the runtime read switch
          lands. Backend audit is owned by the Sprint 27C signal trio
          on CustomerCompanyPolicy. */}
      {!isCreate && customer && (
        <form
          className="card"
          data-testid="section-customer-company-policy"
          style={{ marginTop: 16, padding: "20px 22px" }}
          onSubmit={handleSavePolicy}
        >
          <h3 className="section-title">{t("customer_form.policy_title")}</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("customer_form.policy_helper")}
          </p>

          {policyBanner && (
            <div className="alert-info" role="status" style={{ marginBottom: 12 }}>
              {policyBanner}
            </div>
          )}
          {policyError && (
            <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
              {policyError}
            </div>
          )}

          {policyLoading || !policy ? (
            <div className="loading-bar">
              <div className="loading-bar-fill" />
            </div>
          ) : (
            <>
              {(
                [
                  [
                    "customer_users_can_create_tickets",
                    "customer_form.policy_field_create_tickets",
                  ],
                  [
                    "customer_users_can_approve_ticket_completion",
                    "customer_form.policy_field_approve_ticket_completion",
                  ],
                  [
                    "customer_users_can_create_extra_work",
                    "customer_form.policy_field_create_extra_work",
                  ],
                  [
                    "customer_users_can_approve_extra_work_pricing",
                    "customer_form.policy_field_approve_extra_work_pricing",
                  ],
                ] as const
              ).map(([field, label]) => (
                <div className="field" key={field}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      cursor: policySaving ? "default" : "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      data-testid="customer-policy-toggle"
                      data-policy-field={field}
                      checked={policyDraft[field]}
                      onChange={(event) =>
                        setPolicyDraft((prev) => ({
                          ...prev,
                          [field]: event.target.checked,
                        }))
                      }
                      disabled={policySaving}
                    />
                    <span>{t(label)}</span>
                  </label>
                </div>
              ))}

              <div className="form-actions">
                <button
                  type="submit"
                  className="btn btn-primary"
                  data-testid="customer-policy-save"
                  disabled={policySaving}
                >
                  {policySaving
                    ? t("admin_form.saving")
                    : t("customer_form.policy_save")}
                </button>
              </div>
            </>
          )}
        </form>
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

      <ConfirmDialog
        ref={unlinkBuildingDialogRef}
        title={t("customer_form.dialog_unlink_building_title", {
          building: unlinkBuildingTarget?.building_name ?? "",
          name: customerName,
        })}
        body={t("customer_form.dialog_unlink_building_body")}
        confirmLabel={t("admin_form.remove")}
        onConfirm={handleConfirmUnlinkBuilding}
        onCancel={() => setUnlinkBuildingTarget(null)}
        busy={buildingLinkBusy}
        destructive
      />

      <ConfirmDialog
        ref={revokeAccessDialogRef}
        title={t("customer_form.dialog_revoke_access_title", {
          email: revokeAccessTarget?.membership.user_email ?? "",
          building: revokeAccessTarget?.access.building_name ?? "",
        })}
        body={t("customer_form.dialog_revoke_access_body")}
        confirmLabel={t("customer_form.access_remove_button")}
        onConfirm={handleConfirmRevokeAccess}
        onCancel={() => setRevokeAccessTarget(null)}
        busy={accessBusyUserId !== null}
        destructive
      />
    </div>
  );
}
