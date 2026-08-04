import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  archiveServiceCategory,
  bulkRaiseServices,
  createService,
  createServiceCategory,
  deleteService,
  deleteServiceCategory,
  listAllCompanies,
  listServiceCategories,
  listServices,
  unarchiveServiceCategory,
  updateService,
  updateServiceCategory,
} from "../../api/admin";
import type {
  CompanyAdmin,
  Service,
  ServiceCategory,
  ServiceCategoryCreatePayload,
  ServiceCreatePayload,
  ServiceUnitType,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useToast } from "../../components/ToastProvider";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { ManagedUnitPicker } from "../../components/ManagedUnitPicker";
import { CategoryGroupedPicker } from "../../components/CategoryGroupedPicker";
import { buildPickerGroups } from "../../lib/pickerGroups";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { previewAdjustedPrice } from "../../utils/bulkAdjust";
import { Toggle } from "../../components/Toggle";
import { ManagedUnitsTab } from "./ManagedUnitsTab";

/**
 * Sprint 28 Batch 5 — Provider-wide Service catalog admin page.
 *
 * Single route (`/admin/services`) that exposes BOTH the category list
 * and the service list via tabs. Mirrors the view-first shape from
 * `CustomerContactsPage` (Batch 4):
 *   - lists are read-only rows
 *   - clicking a row opens a read-only detail panel
 *   - "Add" / "Edit" / "Delete" are explicit actions; editing happens
 *     only through a modal
 *
 * Sidebar mode: top-level (admin group). The "Services" entry is
 * gated to SUPER_ADMIN + COMPANY_ADMIN in `AppShell.tsx`.
 *
 * Reference price reminder (spec §5 + master plan rule #9):
 *   `Service.default_unit_price` is a PROVIDER-SIDE REFERENCE ONLY.
 *   The instant-ticket gate (Batch 7) consults `CustomerServicePrice`
 *   rows exclusively — a Service default never falls back into a
 *   resolved customer price. The admin UI therefore labels the field
 *   "Reference unit price" so future readers do not mistake it for
 *   the resolver fallback.
 */

const UNIT_TYPES: readonly ServiceUnitType[] = [
  "HOURS",
  "SQUARE_METERS",
  "FIXED",
  "ITEM",
  "OTHER",
];

const UNIT_TYPE_I18N_KEY: Record<ServiceUnitType, string> = {
  HOURS: "services.unit_type.hours",
  SQUARE_METERS: "services.unit_type.square_meters",
  FIXED: "services.unit_type.fixed",
  ITEM: "services.unit_type.item",
  OTHER: "services.unit_type.other",
};

type Tab = "services" | "categories" | "units";

interface CategoryFormState {
  name: string;
  description: string;
  is_active: boolean;
}

const EMPTY_CATEGORY_FORM: CategoryFormState = {
  name: "",
  description: "",
  is_active: true,
};

interface ServiceFormState {
  category: number | "";
  name: string;
  description: string;
  unit_type: ServiceUnitType;
  custom_unit_label: string;
  managed_unit: number | null;
  default_unit_price: string;
  default_vat_pct: string;
  is_active: boolean;
}

const EMPTY_SERVICE_FORM: ServiceFormState = {
  category: "",
  name: "",
  description: "",
  unit_type: "HOURS",
  custom_unit_label: "",
  managed_unit: null,
  default_unit_price: "0.00",
  default_vat_pct: "21.00",
  is_active: true,
};

function formatDate(value: string, locale: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(locale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

// DRF emits Decimal as a string with trailing zeros; render a short,
// localised form for table cells. We deliberately do not parseFloat
// the value back into a number because that loses precision for
// large prices — instead we keep the canonical string and just
// strip insignificant trailing zeros for display.
function formatDecimal(value: string): string {
  if (!value) return "—";
  return value;
}

export function ServicesAdminPage() {
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const { me } = useAuth();
  // Sprint 139 §2 — SUCCESS results are toasts (auto-dismiss), FAILURE
  // results stay as in-page alerts. See `pushBulkResult` below.
  const { push: pushToast } = useToast();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [tab, setTab] = useState<Tab>("services");
  const [categories, setCategories] = useState<ServiceCategory[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  // Read-only detail panels.
  const [selectedCategory, setSelectedCategory] =
    useState<ServiceCategory | null>(null);
  const [selectedService, setSelectedService] = useState<Service | null>(null);

  // Category modal state.
  const [categoryMode, setCategoryMode] = useState<"create" | "edit" | null>(
    null,
  );
  const [categoryForm, setCategoryForm] =
    useState<CategoryFormState>(EMPTY_CATEGORY_FORM);
  const [categoryFormError, setCategoryFormError] = useState("");
  const [categoryFormBusy, setCategoryFormBusy] = useState(false);

  // Service modal state.
  const [serviceMode, setServiceMode] = useState<"create" | "edit" | null>(
    null,
  );
  const [serviceForm, setServiceForm] =
    useState<ServiceFormState>(EMPTY_SERVICE_FORM);
  const [serviceFormError, setServiceFormError] = useState("");
  const [serviceFormBusy, setServiceFormBusy] = useState(false);

  // Delete confirmations — share a single ConfirmDialog for both
  // category + service so the modal layer stays simple. `deleteKind`
  // discriminates the in-flight target.
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteKind, setDeleteKind] = useState<
    "category" | "service" | null
  >(null);
  const [deleteCategoryTarget, setDeleteCategoryTarget] =
    useState<ServiceCategory | null>(null);
  const [deleteServiceTarget, setDeleteServiceTarget] =
    useState<Service | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // Sprint 137 item 7 — iOS-style list edit mode on the services list.
  // Unlike the customer pricing lists (where DELETE soft-archives),
  // DELETE here is a REAL hard delete
  // (backend/extra_work/views_catalog.py::ServiceDetailView.delete), so
  // the button says "delete" and means it. A service still referenced
  // by any customer contract price is PROTECTed and comes back as a
  // 400 — which is exactly why the per-row failure report below is
  // load-bearing rather than decorative: a bulk run over a real catalog
  // will routinely delete some rows and be refused on others.
  const [serviceEditMode, setServiceEditMode] = useState(false);
  const [serviceBulkIds, setServiceBulkIds] = useState<number[]>([]);
  const serviceBulkDialogRef = useRef<ConfirmDialogHandle>(null);
  const [serviceBulkBusy, setServiceBulkBusy] = useState(false);
  const [serviceBulkFailures, setServiceBulkFailures] = useState<string[]>(
    [],
  );
  const [serviceBulkDone, setServiceBulkDone] = useState<number | null>(null);

  // Sprint 138 §1 — a service with ANY contract price row (active OR
  // archived) is permanently undeletable: `CustomerServicePrice.service`
  // is PROTECT and Sprint 137 item 2 established that "deleting" a price
  // only archives it. Offering Delete there produced the operator's
  // "Deleted 0 service(s), 1 failed" screen, with a 400 naming prices he
  // believed he had already deleted. Those rows get Deactiveren instead.
  const [serviceBulkActionKind, setServiceBulkActionKind] = useState<
    "delete" | "deactivate" | "activate"
  >("delete");
  // Sprint 138 §2b — bulk move to another category. This is the
  // mechanism that EMPTIES a category (so it becomes deletable), not
  // just a convenience: `Service.category` is not nullable, so a
  // service can only leave a category by joining another one.
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveTargetCategory, setMoveTargetCategory] = useState<number | "">(
    "",
  );
  // Moving live work INTO an archived category is almost always a
  // mistake, so archived targets are opt-in.
  const [moveIncludeArchived, setMoveIncludeArchived] = useState(false);
  const [moveBusy, setMoveBusy] = useState(false);
  const [moveError, setMoveError] = useState("");
  const [serviceToggleBusy, setServiceToggleBusy] = useState(false);
  // Sprint 138 §2a — cascade archive / unarchive a category.
  const categoryArchiveDialogRef = useRef<ConfirmDialogHandle>(null);
  const [categoryArchiveTarget, setCategoryArchiveTarget] =
    useState<ServiceCategory | null>(null);
  const [categoryArchiveBusy, setCategoryArchiveBusy] = useState(false);

  // M5 C — catalog default-price bulk-raise modal (services tab only).
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkSelectedIds, setBulkSelectedIds] = useState<number[]>([]);
  const [bulkMode, setBulkMode] = useState<"percent" | "fixed">("percent");
  // #108 Part C — raise vs lower.
  const [bulkDirection, setBulkDirection] = useState<"raise" | "lower">(
    "raise",
  );
  const [bulkAmount, setBulkAmount] = useState("");
  const [bulkError, setBulkError] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  // #108 Part D — display-only row filter for the long service list;
  // hidden-but-selected rows stay selected (never changes submission).
  const [bulkFilter, setBulkFilter] = useState("");

  // Sprint 135 — a SUPER_ADMIN managing a tenant with 2+ provider
  // companies must disambiguate `company` on Service / ManagedUnit
  // create (backend/extra_work/views_catalog.py::
  // _resolve_catalog_create_company 400s `service_company_required`
  // otherwise) — Categories are GLOBAL (SUPER_ADMIN-only, no `company`
  // field at all), so this selector never applies to that tab. One
  // shared control for both the Services and Units tabs.
  const [catalogCompanies, setCatalogCompanies] = useState<CompanyAdmin[]>([]);
  const [catalogCompany, setCatalogCompany] = useState<number | "">("");
  // Sprint 139 §1 — off by default: an inactive service is hidden the
  // same way an archived price is, and revealed by the same toggle.
  const [showInactive, setShowInactive] = useState(false);
  const showCompanySelector = isSuperAdmin && catalogCompanies.length > 1;

  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;
    listAllCompanies({ is_active: "true" }).then((response) => {
      if (!cancelled) setCatalogCompanies(response);
    });
    return () => {
      cancelled = true;
    };
  }, [isSuperAdmin]);

  // Initial parallel load.
  //
  // Sprint 139 §1 — INACTIVE services are hidden by default, matching
  // the customer pricing list's archived-rows rule (Sprint 137 item 2).
  // Two lists over the same idea behaved differently for no reason: a
  // deactivated service used to sit in the catalog forever marked
  // "Inactive". Reuses the endpoint's existing `?is_active=` param
  // rather than inventing a second mechanism.
  //
  // Sprint 139 §4 — the company selector now FILTERS the list too, not
  // just pick a target for new rows. Sent as `?company=`, which the
  // backend applies BEFORE `filter_services_for`, so it can only ever
  // narrow.
  useEffect(() => {
    const cancelled = { current: false };
    async function load() {
      try {
        const [categoriesData, servicesData] = await Promise.all([
          listServiceCategories(),
          listServices({
            ...(showInactive ? {} : { is_active: true }),
            ...(catalogCompany === "" ? {} : { company: catalogCompany }),
          }),
        ]);
        if (cancelled.current) return;
        setCategories(categoriesData);
        setServices(servicesData);
        setLoading(false);
      } catch (err) {
        if (!cancelled.current) {
          setLoadError(getApiError(err));
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled.current = true;
    };
  }, [showInactive, catalogCompany]);

  function resetSelections() {
    setSelectedCategory(null);
    setSelectedService(null);
  }

  // -------- Category CRUD --------

  function openCreateCategoryModal() {
    setCategoryMode("create");
    setCategoryForm(EMPTY_CATEGORY_FORM);
    setCategoryFormError("");
  }

  function openEditCategoryModal(category: ServiceCategory) {
    setCategoryMode("edit");
    setCategoryForm({
      name: category.name,
      description: category.description,
      is_active: category.is_active,
    });
    setCategoryFormError("");
  }

  function closeCategoryModal() {
    setCategoryMode(null);
    setCategoryForm(EMPTY_CATEGORY_FORM);
    setCategoryFormError("");
  }

  async function handleSubmitCategoryForm(event: FormEvent) {
    event.preventDefault();
    if (!categoryForm.name.trim()) {
      setCategoryFormError(t("services.error_name_required"));
      return;
    }
    setCategoryFormBusy(true);
    setCategoryFormError("");
    const payload: ServiceCategoryCreatePayload = {
      name: categoryForm.name.trim(),
      description: categoryForm.description,
      is_active: categoryForm.is_active,
    };
    try {
      if (categoryMode === "create") {
        const created = await createServiceCategory(payload);
        setCategories((prev) =>
          [...prev, created].sort((a, b) => a.name.localeCompare(b.name)),
        );
        closeCategoryModal();
      } else if (categoryMode === "edit" && selectedCategory) {
        const updated = await updateServiceCategory(
          selectedCategory.id,
          payload,
        );
        setCategories((prev) =>
          prev
            .map((c) => (c.id === updated.id ? updated : c))
            .sort((a, b) => a.name.localeCompare(b.name)),
        );
        setSelectedCategory(updated);
        closeCategoryModal();
      }
    } catch (err) {
      setCategoryFormError(getApiError(err));
    } finally {
      setCategoryFormBusy(false);
    }
  }

  function openDeleteCategoryDialog(category: ServiceCategory) {
    setDeleteKind("category");
    setDeleteCategoryTarget(category);
    setDeleteServiceTarget(null);
    deleteDialogRef.current?.open();
  }

  // -------- Service CRUD --------

  function openCreateServiceModal() {
    setServiceMode("create");
    setServiceForm({
      ...EMPTY_SERVICE_FORM,
      // Pre-select the first category if one exists — saves a click
      // and keeps the form valid by default.
      category: categories.length > 0 ? categories[0].id : "",
    });
    setServiceFormError("");
  }

  function openEditServiceModal(service: Service) {
    setServiceMode("edit");
    setServiceForm({
      category: service.category,
      name: service.name,
      description: service.description,
      unit_type: service.unit_type,
      custom_unit_label: service.custom_unit_label,
      managed_unit: service.managed_unit,
      default_unit_price: service.default_unit_price,
      default_vat_pct: service.default_vat_pct,
      is_active: service.is_active,
    });
    setServiceFormError("");
  }

  function closeServiceModal() {
    setServiceMode(null);
    setServiceForm(EMPTY_SERVICE_FORM);
    setServiceFormError("");
  }

  async function handleSubmitServiceForm(event: FormEvent) {
    event.preventDefault();
    if (!serviceForm.name.trim()) {
      setServiceFormError(t("services.error_name_required"));
      return;
    }
    if (serviceForm.category === "") {
      setServiceFormError(t("services.error_category_required"));
      return;
    }
    if (serviceMode === "create" && showCompanySelector && catalogCompany === "") {
      setServiceFormError(t("catalog.error_company_required"));
      return;
    }
    const priceNumber = Number(serviceForm.default_unit_price);
    if (!Number.isFinite(priceNumber) || priceNumber < 0) {
      setServiceFormError(t("services.error_price_invalid"));
      return;
    }
    const vatNumber = Number(serviceForm.default_vat_pct);
    if (!Number.isFinite(vatNumber) || vatNumber < 0) {
      setServiceFormError(t("services.error_vat_invalid"));
      return;
    }
    // RF-2 (mirror of CustomerPricingPage) — a bare "Other" unit renders as
    // nothing, so the custom label is required exactly when OTHER is chosen.
    // The backend blanks it for every concrete unit type, so it is not sent
    // then. Reuses the customer-pricing custom-unit i18n keys.
    if (
      serviceForm.unit_type === "OTHER" &&
      !serviceForm.custom_unit_label.trim()
    ) {
      setServiceFormError(
        t("customer_custom_pricing.error_unit_label_required"),
      );
      return;
    }
    setServiceFormBusy(true);
    setServiceFormError("");
    const payload: ServiceCreatePayload = {
      category: Number(serviceForm.category),
      name: serviceForm.name.trim(),
      description: serviceForm.description,
      unit_type: serviceForm.unit_type,
      custom_unit_label:
        serviceForm.unit_type === "OTHER"
          ? serviceForm.custom_unit_label.trim()
          : "",
      managed_unit:
        serviceForm.unit_type === "OTHER" ? serviceForm.managed_unit : null,
      default_unit_price: serviceForm.default_unit_price.trim(),
      default_vat_pct: serviceForm.default_vat_pct.trim(),
      is_active: serviceForm.is_active,
    };
    try {
      if (serviceMode === "create") {
        await createService(
          catalogCompany === "" ? payload : { ...payload, company: catalogCompany },
        );
        // Sprint 140 §1 — the form carries an Active toggle, so a
        // freshly created row may not match the active filters at all.
        // Re-read rather than blind-append.
        await refreshCatalogRows();
        closeServiceModal();
      } else if (serviceMode === "edit" && selectedService) {
        const updated = await updateService(selectedService.id, payload);
        // Sprint 140 §1 — unticking Active in the edit modal used to
        // leave the row on screen greyed out, contradicting the toggle.
        await refreshCatalogRows();
        setSelectedService(updated);
        closeServiceModal();
      }
    } catch (err) {
      setServiceFormError(getApiError(err));
    } finally {
      setServiceFormBusy(false);
    }
  }

  function openDeleteServiceDialog(service: Service) {
    setDeleteKind("service");
    setDeleteServiceTarget(service);
    setDeleteCategoryTarget(null);
    deleteDialogRef.current?.open();
  }

  async function handleConfirmDelete() {
    if (deleteKind === "category" && deleteCategoryTarget) {
      setDeleteBusy(true);
      try {
        await deleteServiceCategory(deleteCategoryTarget.id);
        setCategories((prev) =>
          prev.filter((c) => c.id !== deleteCategoryTarget.id),
        );
        if (selectedCategory?.id === deleteCategoryTarget.id) {
          setSelectedCategory(null);
        }
        deleteDialogRef.current?.close();
        setDeleteCategoryTarget(null);
        setDeleteKind(null);
      } catch (err) {
        // Surface backend error (most often ProtectedError when the
        // category still has services attached — the backend returns
        // 400 with a friendly message).
        setLoadError(getApiError(err));
        deleteDialogRef.current?.close();
      } finally {
        setDeleteBusy(false);
      }
      return;
    }
    if (deleteKind === "service" && deleteServiceTarget) {
      setDeleteBusy(true);
      try {
        await deleteService(deleteServiceTarget.id);
        // Sprint 140 §1 — a removal is always filter-correct on its
        // own, but the delete drops its category's `service_count`,
        // which is what gates Delete on the Categories tab. Re-read
        // both rather than let that count go stale.
        await refreshCatalogRows();
        if (selectedService?.id === deleteServiceTarget.id) {
          setSelectedService(null);
        }
        deleteDialogRef.current?.close();
        setDeleteServiceTarget(null);
        setDeleteKind(null);
      } catch (err) {
        setLoadError(getApiError(err));
        deleteDialogRef.current?.close();
      } finally {
        setDeleteBusy(false);
      }
    }
  }

  /**
   * Sprint 139 §1/§4 — refetch the service list HONOURING the current
   * archived toggle and company filter. Every post-mutation reload goes
   * through this; calling `listServices()` bare would silently drop
   * both filters and repopulate the list with rows the operator had
   * just filtered away.
   */
  function currentServiceListParams() {
    return {
      ...(showInactive ? {} : { is_active: true }),
      ...(catalogCompany === "" ? {} : { company: catalogCompany }),
    };
  }

  /**
   * Sprint 140 §1/§2 — re-read the catalog from the server after ANY
   * mutation, honouring the active archived toggle and company filter.
   *
   * This replaces Sprint 139's `applyServiceUpdates`, which mapped over
   * the rows already on screen and could therefore DROP a row but never
   * bring one back: after deactivating a service (it left the list),
   * pressing Activeren PATCHed successfully and the row never
   * reappeared. Every local-merge variant has that hole in one
   * direction or the other, so the fix is to stop merging locally.
   *
   * Chosen over a merge-and-insert helper deliberately: the server
   * orders services by `category__name, name, id`
   * (`ServiceListCreateView.get_queryset`), while the client insert it
   * would replace sorted by `name` alone — the two ALREADY disagreed,
   * so re-implementing insertion would have cemented a second, wrong
   * ordering rule. One round-trip on an admin page is the cheaper
   * correctness. No flicker: the list is swapped in a single setState
   * with the loading bar untouched, so there is no intermediate empty
   * render.
   *
   * Categories are refetched alongside because a create, delete, or
   * category change moves a category's `service_count`, which is what
   * decides whether the Categories tab offers Delete (Sprint 138 §2c).
   */
  async function refreshCatalogRows() {
    // Sprint 141 §1/§2 — THIS HELPER NEVER THROWS. That is its
    // contract, and the reason the guard lives here rather than at the
    // call sites.
    //
    // Round 4 turned thirteen synchronous state updates into
    // `await refreshX()` without auditing the throw path. Every caller
    // runs it AFTER a mutation that already committed, so a failed
    // re-read is never a failed write — but it was reaching two places
    // it had no business reaching:
    //   * bulk handlers: it jumped over the lines that reset the busy
    //     flag and closed the dialog, and `ConfirmDialog` swallows the
    //     rejection (`void onConfirm()`) while disabling BOTH buttons
    //     on `busy` — so the dialog went inert until a page reload;
    //   * create/edit: it landed in the FORM's catch, so a committed
    //     write was reported as a form error.
    //
    // Guarding at each call site would need try/finally AND a catch at
    // all thirteen — and Round 4's defect was precisely that the guard
    // was written once (at the cascade-archive) and omitted everywhere
    // else. Swallowing here makes omission impossible.
    //
    // Failure mode is deliberately "stale list + visible page-level
    // error", never a silent one: the operator is told the write landed
    // and the list did not refresh.
    try {
      const [servicesData, categoriesData] = await Promise.all([
        listServices(currentServiceListParams()),
        listServiceCategories(),
      ]);
      setServices(servicesData);
      setCategories(categoriesData);
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }

  // ---- Sprint 137 item 7 — bulk delete (services list edit mode) ----
  function exitServiceEditMode() {
    setServiceEditMode(false);
    setServiceBulkIds([]);
  }

  function toggleServiceBulkRow(serviceId: number, checked: boolean) {
    setServiceBulkIds((prev) =>
      checked ? [...prev, serviceId] : prev.filter((id) => id !== serviceId),
    );
  }

  /**
   * Delete every selected service. No bulk endpoint exists, so this is
   * N sequential DELETEs from the client (recorded as a `## NEXT` item
   * in the sprint checklist for catalogs where N could get large).
   *
   * Partial failure is the NORMAL case here, not the exception: any
   * service a customer still has a contract price for is PROTECTed and
   * returns 400. Those rows are named individually and stay selected;
   * the ones that did delete are gone. The run is never reported as a
   * clean success when anything failed.
   */
  async function handleConfirmServiceBulkDelete() {
    // Sprint 138 §1 — one dialog, three verbs. `serviceBulkActionKind`
    // is set by whichever toolbar button opened it, so the confirmation
    // copy and the request below always agree.
    if (serviceBulkActionKind !== "delete") {
      await handleConfirmServiceBulkSetActive(
        serviceBulkActionKind === "activate",
      );
      return;
    }
    setServiceBulkBusy(true);
    const targets = services.filter((s) => serviceBulkIds.includes(s.id));
    const deletedIds: number[] = [];
    const failed: { id: number; name: string }[] = [];

    for (const service of targets) {
      try {
        await deleteService(service.id);
        deletedIds.push(service.id);
      } catch {
        failed.push({ id: service.id, name: service.name });
      }
    }

    if (deletedIds.length > 0) {
      // Same reasoning as the single delete: category counts move.
      await refreshCatalogRows();
      if (selectedService && deletedIds.includes(selectedService.id)) {
        setSelectedService(null);
      }
    }
    setServiceBulkIds(failed.map((f) => f.id));
    setServiceBulkFailures(failed.map((f) => f.name));
    setServiceBulkDone(deletedIds.length);
    setServiceBulkBusy(false);
    serviceBulkDialogRef.current?.close();
    if (failed.length === 0 && deletedIds.length > 0) {
      pushToast({
        variant: "success",
        title: t("services.bulk_delete_done", { count: deletedIds.length }),
      });
    }
  }

  /**
   * Sprint 138 §1 — bulk (de)activate. This is the action a referenced
   * service gets INSTEAD of Delete: it stops appearing in pickers while
   * every contract price and shipped Extra Work line that points at it
   * stays intact. No bulk endpoint exists, so this is N sequential
   * PATCHes from the client (recorded as a `## NEXT` item); partial
   * failure is reported per row exactly as the delete path does.
   */
  async function handleConfirmServiceBulkSetActive(nextActive: boolean) {
    setServiceBulkBusy(true);
    const targets = services
      .filter((s) => serviceBulkIds.includes(s.id))
      // Skip rows already in the target state — re-saving them would
      // report a change that did not happen (the Sprint 138 §3 lesson).
      .filter((s) => s.is_active !== nextActive);
    const updated: Service[] = [];
    const failed: { id: number; name: string }[] = [];

    for (const service of targets) {
      try {
        updated.push(
          await updateService(service.id, { is_active: nextActive }),
        );
      } catch {
        failed.push({ id: service.id, name: service.name });
      }
    }

    if (updated.length > 0) {
      const byId = new Map(updated.map((s) => [s.id, s]));
      await refreshCatalogRows();
      if (selectedService && byId.has(selectedService.id)) {
        setSelectedService(byId.get(selectedService.id) ?? null);
      }
    }
    setServiceBulkIds(failed.map((f) => f.id));
    setServiceBulkFailures(failed.map((f) => f.name));
    setServiceBulkDone(updated.length);
    setServiceBulkBusy(false);
    serviceBulkDialogRef.current?.close();
    if (failed.length === 0 && updated.length > 0) {
      pushToast({
        variant: "success",
        title: t(
          nextActive
            ? "services.bulk_activate_done"
            : "services.bulk_deactivate_done",
          { count: updated.length },
        ),
      });
    }
  }

  // ---- Sprint 138 §2a — cascade archive / unarchive a category ------
  function openCategoryArchiveDialog(category: ServiceCategory) {
    setCategoryArchiveTarget(category);
    categoryArchiveDialogRef.current?.open();
  }

  /**
   * Archive a category TOGETHER WITH its services, or unarchive the
   * category alone — one backend call, one transaction. Doing it
   * client-side as N PATCHes would leave a half-archived category
   * behind on any failure.
   */
  async function handleConfirmCategoryArchive() {
    if (!categoryArchiveTarget) return;
    const archiving = categoryArchiveTarget.is_active;
    setCategoryArchiveBusy(true);
    try {
      const result = archiving
        ? await archiveServiceCategory(categoryArchiveTarget.id)
        : await unarchiveServiceCategory(categoryArchiveTarget.id);
      setCategories((prev) =>
        prev.map((c) => (c.id === result.category.id ? result.category : c)),
      );
      setSelectedCategory(result.category);
      // The cascade changed Service.is_active rows underneath us, and
      // the category's own counts with them. No wrapper needed: the
      // helper is non-throwing by contract (Sprint 141 §1).
      await refreshCatalogRows();
      pushToast({
        variant: "success",
        title: archiving
          ? t("services.category_archive_result", {
              count: result.deactivated_service_count,
            })
          : t("services.category_unarchive_result", {
              count: result.still_archived_service_count,
            }),
        // A cascade that reached several providers is worth more than
        // four seconds of the operator's attention.
        description:
          result.affected_company_count > 1
            ? t("services.category_archive_multi_company", {
                count: result.affected_company_count,
              })
            : undefined,
        durationMs: result.affected_company_count > 1 ? 8_000 : undefined,
      });
      categoryArchiveDialogRef.current?.close();
      setCategoryArchiveTarget(null);
    } catch (err) {
      setLoadError(getApiError(err));
      categoryArchiveDialogRef.current?.close();
    } finally {
      setCategoryArchiveBusy(false);
    }
  }

  /**
   * Sprint 138 §1 — single-row (de)activate from the detail panel. The
   * action a referenced service gets in place of Delete.
   */
  async function handleToggleServiceActive(service: Service) {
    setServiceToggleBusy(true);
    try {
      const updated = await updateService(service.id, {
        is_active: !service.is_active,
      });
      // Keep the detail panel on the row so the operator can flip it
      // straight back, even when the list itself no longer shows it —
      // and now the row genuinely RETURNS to the list when reactivated.
      // Set BEFORE the re-read: the panel must not depend on a network
      // call that is allowed to fail (Sprint 141 §2).
      setSelectedService(updated);
      await refreshCatalogRows();
    } catch (err) {
      setLoadError(getApiError(err));
    } finally {
      setServiceToggleBusy(false);
    }
  }

  function openServiceBulkAction(kind: "delete" | "deactivate" | "activate") {
    setServiceBulkActionKind(kind);
    setServiceBulkFailures([]);
    setServiceBulkDone(null);
    serviceBulkDialogRef.current?.open();
  }

  // ---- Sprint 138 §2b — bulk move to another category ---------------
  function openMoveModal() {
    setMoveTargetCategory("");
    setMoveIncludeArchived(false);
    setMoveError("");
    setMoveOpen(true);
  }

  /**
   * Move every selected service into the chosen category. N sequential
   * PATCHes (no bulk endpoint — see `## NEXT`), per-row failure
   * reporting. This is how a category is emptied so it can be deleted:
   * `Service.category` is NOT nullable, so a service leaves a category
   * only by joining another one.
   */
  async function handleConfirmMove() {
    if (moveTargetCategory === "") {
      setMoveError(t("services.move_error_no_target"));
      return;
    }
    setMoveBusy(true);
    setMoveError("");
    const targets = services.filter((s) => serviceBulkIds.includes(s.id));
    const updated: Service[] = [];
    const failed: { id: number; name: string }[] = [];

    for (const service of targets) {
      try {
        updated.push(
          await updateService(service.id, {
            category: Number(moveTargetCategory),
          }),
        );
      } catch {
        failed.push({ id: service.id, name: service.name });
      }
    }

    if (updated.length > 0) {
      const byId = new Map(updated.map((s) => [s.id, s]));
      // Refreshes services AND the category counts a move changes.
      await refreshCatalogRows();
      if (selectedService && byId.has(selectedService.id)) {
        setSelectedService(byId.get(selectedService.id) ?? null);
      }
    }
    setServiceBulkIds(failed.map((f) => f.id));
    setServiceBulkFailures(failed.map((f) => f.name));
    setServiceBulkDone(updated.length);
    setMoveBusy(false);
    setMoveOpen(false);
    if (failed.length === 0 && updated.length > 0) {
      pushToast({
        variant: "success",
        title: t("services.bulk_move_done", { count: updated.length }),
      });
    }
  }

  function handleCancelDelete() {
    setDeleteCategoryTarget(null);
    setDeleteServiceTarget(null);
    setDeleteKind(null);
  }

  // -------- M5 C — catalog default bulk-raise --------

  function openBulkRaise() {
    setBulkSelectedIds(activeServices.map((s) => s.id));
    setBulkMode("percent");
    setBulkDirection("raise");
    setBulkAmount("");
    setBulkFilter("");
    setBulkError("");
    setBulkOpen(true);
  }

  function closeBulkRaise() {
    setBulkOpen(false);
    setBulkError("");
  }

  function toggleBulkAll(checked: boolean) {
    setBulkSelectedIds(checked ? activeServices.map((s) => s.id) : []);
  }

  function toggleBulkRow(serviceId: number, checked: boolean) {
    setBulkSelectedIds((prev) =>
      checked ? [...prev, serviceId] : prev.filter((id) => id !== serviceId),
    );
  }

  async function handleBulkRaise() {
    if (bulkSelectedIds.length === 0) {
      setBulkError(t("services.bulk_raise_error_no_selection"));
      return;
    }
    const amountNumber = Number(bulkAmount);
    if (!Number.isFinite(amountNumber) || amountNumber <= 0) {
      setBulkError(t("services.bulk_raise_error_amount"));
      return;
    }
    // #108 Part C — client mirror of the backend guard (the server
    // re-checks): a percent lower must stay below 100.
    if (
      bulkDirection === "lower" &&
      bulkMode === "percent" &&
      amountNumber >= 100
    ) {
      setBulkError(t("services.bulk_raise_error_percent_lower"));
      return;
    }
    setBulkBusy(true);
    setBulkError("");
    try {
      await bulkRaiseServices({
        services: bulkSelectedIds,
        mode: bulkMode,
        amount: bulkAmount.trim(),
        direction: bulkDirection,
      });
      // Re-fetch so the updated catalog defaults surface in the table.
      const refreshed = await listServices(currentServiceListParams());
      setServices(refreshed);
      closeBulkRaise();
    } catch (err) {
      setBulkError(getApiError(err));
    } finally {
      setBulkBusy(false);
    }
  }

  // -------- Render --------

  // M5 C — active services are the only rows the bulk-raise modal can
  // act on. Plain derived value (the earlier-defined openBulkRaise
  // captures it, so a manual useMemo would trip the hooks rule).
  const activeServices = services.filter((s) => s.is_active);

  // Sprint 139 §3 — the catalog bulk-adjust picker, grouped by category.
  const bulkFilterTerm = bulkFilter.trim().toLowerCase();
  const bulkRaiseGroups = buildPickerGroups<Service>({
    rows: activeServices,
    categories,
    categoryOf: (service) => service.category,
    matchesFilter: (service) =>
      !bulkFilterTerm || service.name.toLowerCase().includes(bulkFilterTerm),
    fallbackName: t("customer_pricing.category_unknown"),
  });

  // ---- Sprint 138 §1 — which bulk actions may even be OFFERED -------
  // The sprint's whole theme: an action the backend will always refuse
  // should not be on screen. Delete appears only when EVERY selected
  // service is unreferenced; otherwise the operator gets Deactiveren,
  // plus a line saying how many rows forced that and why.
  const selectedServices = services.filter((s) =>
    serviceBulkIds.includes(s.id),
  );
  const selectedReferenced = selectedServices.filter((s) => s.has_price_rows);
  const selectedActiveCount = selectedServices.filter(
    (s) => s.is_active,
  ).length;
  const selectedInactiveCount = selectedServices.length - selectedActiveCount;
  const bulkDeleteOffered =
    selectedServices.length > 0 && selectedReferenced.length === 0;

  const serviceBulkActions = [
    ...(selectedActiveCount > 0
      ? [
          {
            key: "deactivate",
            label: t("services.bulk_deactivate_button"),
            onClick: () => openServiceBulkAction("deactivate"),
          },
        ]
      : []),
    ...(selectedInactiveCount > 0
      ? [
          {
            key: "activate",
            label: t("services.bulk_activate_button"),
            onClick: () => openServiceBulkAction("activate"),
          },
        ]
      : []),
    {
      key: "move",
      label: t("services.bulk_move_button"),
      onClick: openMoveModal,
    },
    ...(bulkDeleteOffered
      ? [
          {
            key: "delete",
            label: t("services.bulk_delete_button"),
            onClick: () => openServiceBulkAction("delete"),
            destructive: true,
          },
        ]
      : []),
  ];

  // Categories the bulk-move modal may target. Archived ones are opt-in
  // (moving live work into a retired category is almost always a
  // mistake), and the category every selected service is already in is
  // still listed — moving a mixed selection "back" to it is legitimate.
  const moveTargetCategories = categories.filter(
    (c) => c.is_active || moveIncludeArchived,
  );

  return (
    <div data-testid="services-admin-page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("services.page_title")}</h2>
        </div>
      </div>

      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("services.tabs_aria")}
        style={{ marginBottom: 12 }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === "services"}
          className={`composer-toggle-btn ${
            tab === "services" ? "active" : ""
          }`}
          data-testid="services-tab-services"
          onClick={() => {
            setTab("services");
            resetSelections();
          }}
        >
          {t("services.tab_services")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "categories"}
          className={`composer-toggle-btn ${
            tab === "categories" ? "active" : ""
          }`}
          data-testid="services-tab-categories"
          onClick={() => {
            setTab("categories");
            resetSelections();
          }}
        >
          {t("services.tab_categories")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "units"}
          className={`composer-toggle-btn ${
            tab === "units" ? "active" : ""
          }`}
          data-testid="services-tab-units"
          onClick={() => {
            setTab("units");
            resetSelections();
          }}
        >
          {t("services.tab_units")}
        </button>
      </div>

      {showCompanySelector && (
        <div className="field" style={{ maxWidth: 320, marginBottom: 16 }}>
          <label className="field-label" htmlFor="catalog-company-selector">
            {t("catalog.company_selector_label")}
          </label>
          <select
            id="catalog-company-selector"
            className="field-select"
            value={catalogCompany === "" ? "" : String(catalogCompany)}
            onChange={(event) => {
              const v = event.target.value;
              setCatalogCompany(v === "" ? "" : Number(v));
            }}
            data-testid="catalog-company-selector"
          >
            <option value="">
              {t("catalog.company_selector_placeholder")}
            </option>
            {catalogCompanies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
          {/* Sprint 139 §4 — the selector now FILTERS the Services and
              Units lists as well as targeting new rows, so say which
              one applies on the tab you are looking at. The categories
              hint already stated that categories are global and
              unaffected; it stays, and is now the honest counterpart to
              the filtering hint rather than the only explanation. */}
          {tab === "categories" ? (
            <p className="field-hint muted small">
              {t("catalog.company_selector_hint_categories")}
            </p>
          ) : (
            <p className="field-hint muted small">
              {catalogCompany === ""
                ? t("catalog.company_selector_hint_all")
                : t("catalog.company_selector_hint_filtering")}
            </p>
          )}
        </div>
      )}

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : tab === "services" ? (
        // -------- Services tab --------
        <>
          <div
            className="page-header"
            style={{ marginTop: 0, marginBottom: 12 }}
          >
            <div />
            <div className="page-header-actions">
              {/* Sprint 137 item 7 — Edit / Done. Outside edit mode the
                  list renders exactly as before. */}
              {/* Sprint 139 §1 + §4 — same show/hide-archived toggle
                  shape as the customer pricing page, label reflecting
                  state (Sprint 138 §4). */}
              <button
                type="button"
                className={
                  showInactive
                    ? "btn btn-secondary btn-sm"
                    : "btn btn-ghost btn-sm"
                }
                data-testid="services-show-inactive-toggle"
                aria-pressed={showInactive}
                onClick={() => setShowInactive((current) => !current)}
                disabled={loading}
              >
                {showInactive
                  ? t("services.hide_inactive_toggle")
                  : t("services.show_inactive_toggle")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="services-edit-mode-toggle"
                aria-pressed={serviceEditMode}
                onClick={() =>
                  serviceEditMode
                    ? exitServiceEditMode()
                    : setServiceEditMode(true)
                }
                disabled={services.length === 0}
              >
                {serviceEditMode
                  ? t("services.list_edit_done")
                  : t("services.list_edit_start")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="services-bulk-raise-button"
                onClick={openBulkRaise}
              >
                {t("services.bulk_raise_button")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                data-testid="services-add-service-button"
                onClick={openCreateServiceModal}
                disabled={categories.length === 0}
                title={
                  categories.length === 0
                    ? t("services.create_category_first")
                    : undefined
                }
              >
                {t("services.add_service_button")}
              </button>
            </div>
          </div>

          <div className="card" data-testid="services-services-list">
            {services.length === 0 ? (
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="services-services-empty"
              >
                <h3 style={{ marginBottom: 8 }}>
                  {t("services.empty_services_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("services.empty_services_description")}
                </p>
              </div>
            ) : (
              <>
                {/* Sprint 139 §1 — say on the list that inactive rows
                    are included, mirroring the pricing page. */}
                {showInactive && (
                  <div
                    className="alert-info"
                    role="status"
                    style={{ margin: "12px 16px 0" }}
                    data-testid="services-inactive-included-note"
                  >
                    {t("services.inactive_included_note", {
                      count: services.filter((svc) => !svc.is_active).length,
                    })}
                  </div>
                )}
                {/* Edit bar + run report sit OUTSIDE `.table-wrap`:
                    that container scrolls horizontally, and a toolbar
                    that scrolls away from its own table is worse than
                    no toolbar. */}
                {serviceEditMode && (
                  <>
                    <div className="list-edit-bar">
                      <MultiSelectToolbar
                        selectedCount={serviceBulkIds.length}
                        onSelectAll={() =>
                          setServiceBulkIds(services.map((s) => s.id))
                        }
                        onClearAll={() => setServiceBulkIds([])}
                        disabled={serviceBulkBusy}
                        actions={serviceBulkActions}
                        testIdPrefix="services-bulk-delete"
                      />
                    </div>
                    {/* Sprint 138 §1 — say WHY Delete is absent rather
                        than leaving the operator to wonder. This is the
                        screen that previously offered Delete and then
                        reported "Deleted 0 service(s), 1 failed". */}
                    <div
                      className="muted small"
                      style={{ padding: "8px 16px 0" }}
                      data-testid="services-bulk-delete-explainer"
                    >
                      {selectedReferenced.length > 0
                        ? t("services.bulk_delete_blocked_explainer", {
                            count: selectedReferenced.length,
                          })
                        : t("services.bulk_delete_explainer")}
                    </div>
                  </>
                )}
                {serviceBulkFailures.length > 0 && (
                  <div
                    className="alert-error"
                    role="alert"
                    style={{ margin: "12px 16px 0" }}
                    data-testid="services-bulk-delete-failures"
                  >
                    {t("services.bulk_delete_partial", {
                      done: serviceBulkDone ?? 0,
                      failed: serviceBulkFailures.length,
                    })}
                    <ul className="list-edit-failure-list">
                      {serviceBulkFailures.map((name) => (
                        <li key={name}>{name}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {serviceEditMode && (
                        <th className="list-edit-checkbox-cell">
                          <span className="sr-only">
                            {t("services.list_edit_select_column")}
                          </span>
                        </th>
                      )}
                      <th>{t("services.col_name")}</th>
                      <th>{t("services.col_category")}</th>
                      <th>{t("services.col_unit_type")}</th>
                      <th>{t("services.col_default_unit_price")}</th>
                      <th>{t("services.col_default_vat_pct")}</th>
                      <th>{t("services.col_active")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {services.map((service) => (
                      <tr
                        key={service.id}
                        data-testid="services-service-row"
                        data-service-id={service.id}
                        data-inactive={service.is_active ? "false" : "true"}
                        className={
                          service.is_active ? "" : "list-row-archived"
                        }
                        onClick={() => {
                          if (!serviceEditMode) {
                            setSelectedService(service);
                            return;
                          }
                          toggleServiceBulkRow(
                            service.id,
                            !serviceBulkIds.includes(service.id),
                          );
                        }}
                      >
                        {serviceEditMode && (
                          <td className="list-edit-checkbox-cell">
                            <input
                              type="checkbox"
                              className="checkbox-input"
                              data-testid="services-bulk-delete-row"
                              data-service-id={service.id}
                              checked={serviceBulkIds.includes(service.id)}
                              onChange={(event) =>
                                toggleServiceBulkRow(
                                  service.id,
                                  event.target.checked,
                                )
                              }
                              onClick={(event) => event.stopPropagation()}
                              disabled={serviceBulkBusy}
                              aria-label={service.name}
                            />
                          </td>
                        )}
                        <td>{service.name}</td>
                        <td>{service.category_name}</td>
                        <td>{t(UNIT_TYPE_I18N_KEY[service.unit_type])}</td>
                        <td>{formatDecimal(service.default_unit_price)}</td>
                        <td>{formatDecimal(service.default_vat_pct)}</td>
                        <td>
                          {service.is_active
                            ? t("admin.status_active")
                            : t("admin.status_inactive")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </>
            )}
          </div>

          {selectedService && (
            <section
              className="card"
              data-testid="services-service-detail"
              style={{ marginTop: 16, padding: "20px 22px" }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 12,
                  marginBottom: 12,
                }}
              >
                <div>
                  <div className="eyebrow" style={{ marginBottom: 4 }}>
                    {t("services.detail_service_title")}
                  </div>
                  <h3 className="section-title" style={{ margin: 0 }}>
                    {selectedService.name}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="services-service-edit-button"
                    onClick={() => openEditServiceModal(selectedService)}
                  >
                    {t("services.edit_button")}
                  </button>
                  {/* Sprint 138 §1 — a service with ANY contract price
                      row (active or ARCHIVED) can never be deleted:
                      PROTECT, and "deleting" a price only archives it.
                      Offer the action that actually works instead of a
                      Delete that is guaranteed to 400. */}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="services-service-toggle-active-button"
                    onClick={() =>
                      void handleToggleServiceActive(selectedService)
                    }
                    disabled={serviceToggleBusy}
                  >
                    {selectedService.is_active
                      ? t("services.deactivate_button")
                      : t("services.activate_button")}
                  </button>
                  {!selectedService.has_price_rows && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      data-testid="services-service-delete-button"
                      onClick={() => openDeleteServiceDialog(selectedService)}
                    >
                      {t("services.delete_button")}
                    </button>
                  )}
                </div>
              </div>

              {selectedService.has_price_rows && (
                <div
                  className="muted small"
                  style={{ marginBottom: 12 }}
                  data-testid="services-service-delete-blocked-note"
                >
                  {t("services.delete_blocked_note")}
                </div>
              )}

              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.col_category")}
                  </span>
                  <span className="detail-kv-val">
                    {selectedService.category_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_description")}
                  </span>
                  <span
                    className="detail-kv-val"
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {selectedService.description || "—"}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.col_unit_type")}
                  </span>
                  <span className="detail-kv-val">
                    {t(UNIT_TYPE_I18N_KEY[selectedService.unit_type])}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.col_default_unit_price")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDecimal(selectedService.default_unit_price)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.col_default_vat_pct")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDecimal(selectedService.default_vat_pct)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.col_active")}
                  </span>
                  <span className="detail-kv-val">
                    {selectedService.is_active
                      ? t("admin.status_active")
                      : t("admin.status_inactive")}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_reference_price_hint_label")}
                  </span>
                  <span className="detail-kv-val muted small">
                    {t("services.field_reference_price_hint")}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_created_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selectedService.created_at, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_updated_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selectedService.updated_at, dateLocale)}
                  </span>
                </div>
              </div>
            </section>
          )}
        </>
      ) : tab === "categories" ? (
        // -------- Categories tab --------
        <>
          <div
            className="page-header"
            style={{ marginTop: 0, marginBottom: 12 }}
          >
            <div />
            <div className="page-header-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                data-testid="services-add-category-button"
                onClick={openCreateCategoryModal}
              >
                {t("services.add_category_button")}
              </button>
            </div>
          </div>

          <div className="card" data-testid="services-categories-list">
            {categories.length === 0 ? (
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="services-categories-empty"
              >
                <h3 style={{ marginBottom: 8 }}>
                  {t("services.empty_categories_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("services.empty_categories_description")}
                </p>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("services.col_name")}</th>
                      <th>{t("services.col_description")}</th>
                      {/* Sprint 138 §2c — the count is visible on the
                          row so the operator can see WHY a category is
                          or is not deletable without clicking in. */}
                      <th>{t("services.col_service_count")}</th>
                      <th>{t("services.col_active")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map((category) => (
                      <tr
                        key={category.id}
                        data-testid="services-category-row"
                        data-category-id={category.id}
                        data-service-count={category.service_count}
                        onClick={() => setSelectedCategory(category)}
                      >
                        <td>{category.name}</td>
                        <td className="muted small">
                          {category.description || "—"}
                        </td>
                        <td>
                          {category.service_count === 0 ? (
                            <span className="muted">
                              {t("services.category_count_empty")}
                            </span>
                          ) : (
                            t("services.category_count", {
                              count: category.service_count,
                              active: category.active_service_count,
                            })
                          )}
                        </td>
                        <td>
                          {category.is_active
                            ? t("admin.status_active")
                            : t("admin.status_inactive")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {selectedCategory && (
            <section
              className="card"
              data-testid="services-category-detail"
              style={{ marginTop: 16, padding: "20px 22px" }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 12,
                  marginBottom: 12,
                }}
              >
                <div>
                  <div className="eyebrow" style={{ marginBottom: 4 }}>
                    {t("services.detail_category_title")}
                  </div>
                  <h3 className="section-title" style={{ margin: 0 }}>
                    {selectedCategory.name}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="services-category-edit-button"
                    onClick={() => openEditCategoryModal(selectedCategory)}
                  >
                    {t("services.edit_button")}
                  </button>
                  {/* Sprint 138 §2a — archive cascades to the
                      category's services (they cannot exist outside a
                      category); unarchive restores the category alone. */}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="services-category-archive-button"
                    onClick={() => openCategoryArchiveDialog(selectedCategory)}
                    disabled={categoryArchiveBusy}
                  >
                    {selectedCategory.is_active
                      ? t("services.category_archive_button")
                      : t("services.category_unarchive_button")}
                  </button>
                  {/* Sprint 138 §2c — `Service.category` is PROTECT, so
                      Delete can only ever succeed on an EMPTY category.
                      Offering it otherwise is the same defect as §1. */}
                  {selectedCategory.service_count === 0 && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      data-testid="services-category-delete-button"
                      onClick={() =>
                        openDeleteCategoryDialog(selectedCategory)
                      }
                    >
                      {t("services.delete_button")}
                    </button>
                  )}
                </div>
              </div>

              {selectedCategory.service_count > 0 && (
                <div
                  className="muted small"
                  style={{ marginBottom: 12 }}
                  data-testid="services-category-delete-blocked-note"
                >
                  {t("services.category_delete_blocked_note", {
                    count: selectedCategory.service_count,
                  })}
                </div>
              )}

              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_description")}
                  </span>
                  <span
                    className="detail-kv-val"
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {selectedCategory.description || "—"}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.col_active")}
                  </span>
                  <span className="detail-kv-val">
                    {selectedCategory.is_active
                      ? t("admin.status_active")
                      : t("admin.status_inactive")}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_created_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selectedCategory.created_at, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("services.field_updated_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selectedCategory.updated_at, dateLocale)}
                  </span>
                </div>
              </div>
            </section>
          )}
        </>
      ) : (
        // -------- Units tab --------
        <ManagedUnitsTab
          companyRequired={showCompanySelector}
          selectedCompany={catalogCompany}
        />
      )}

      {/* Category create/edit modal */}
      {categoryMode !== null && (
        <div
          data-testid="services-category-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            categoryMode === "create"
              ? t("services.add_category_modal_title")
              : t("services.edit_category_modal_title")
          }
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
        >
          <form
            onSubmit={handleSubmitCategoryForm}
            className="card"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {categoryMode === "create"
                ? t("services.add_category_modal_title")
                : t("services.edit_category_modal_title")}
            </h3>

            {categoryFormError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="services-category-modal-error"
              >
                {categoryFormError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="category-name">
                {t("services.field_name")} *
              </label>
              <input
                id="category-name"
                className="field-input"
                type="text"
                value={categoryForm.name}
                onChange={(event) =>
                  setCategoryForm((prev) => ({
                    ...prev,
                    name: event.target.value,
                  }))
                }
                data-testid="services-category-input-name"
                required
                disabled={categoryFormBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="category-description">
                {t("services.field_description")}
              </label>
              <textarea
                id="category-description"
                className="field-textarea"
                rows={4}
                value={categoryForm.description}
                onChange={(event) =>
                  setCategoryForm((prev) => ({
                    ...prev,
                    description: event.target.value,
                  }))
                }
                data-testid="services-category-input-description"
                disabled={categoryFormBusy}
              />
            </div>

            <div className="field">
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <Toggle
                  checked={categoryForm.is_active}
                  onChange={(event) =>
                    setCategoryForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="services-category-input-is-active"
                  disabled={categoryFormBusy}
                />
                <span>{t("services.field_is_active")}</span>
              </label>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeCategoryModal}
                disabled={categoryFormBusy}
                data-testid="services-category-modal-cancel"
              >
                {t("services.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={categoryFormBusy}
                data-testid="services-category-modal-save"
              >
                {categoryFormBusy
                  ? t("admin_form.saving")
                  : t("services.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Service create/edit modal */}
      {serviceMode !== null && (
        <div
          data-testid="services-service-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            serviceMode === "create"
              ? t("services.add_service_modal_title")
              : t("services.edit_service_modal_title")
          }
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
        >
          <form
            onSubmit={handleSubmitServiceForm}
            className="card"
            style={{
              maxWidth: 640,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {serviceMode === "create"
                ? t("services.add_service_modal_title")
                : t("services.edit_service_modal_title")}
            </h3>

            {serviceFormError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="services-service-modal-error"
              >
                {serviceFormError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="service-category">
                {t("services.field_category")} *
              </label>
              <select
                id="service-category"
                className="field-select"
                value={
                  serviceForm.category === ""
                    ? ""
                    : String(serviceForm.category)
                }
                onChange={(event) => {
                  const v = event.target.value;
                  setServiceForm((prev) => ({
                    ...prev,
                    category: v === "" ? "" : Number(v),
                  }));
                }}
                data-testid="services-service-input-category"
                required
                disabled={serviceFormBusy}
              >
                <option value="">
                  {t("services.field_category_placeholder")}
                </option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="service-name">
                {t("services.field_name")} *
              </label>
              <input
                id="service-name"
                className="field-input"
                type="text"
                value={serviceForm.name}
                onChange={(event) =>
                  setServiceForm((prev) => ({
                    ...prev,
                    name: event.target.value,
                  }))
                }
                data-testid="services-service-input-name"
                required
                disabled={serviceFormBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="service-description">
                {t("services.field_description")}
              </label>
              <textarea
                id="service-description"
                className="field-textarea"
                rows={3}
                value={serviceForm.description}
                onChange={(event) =>
                  setServiceForm((prev) => ({
                    ...prev,
                    description: event.target.value,
                  }))
                }
                data-testid="services-service-input-description"
                disabled={serviceFormBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="service-unit-type">
                {t("services.field_unit_type")} *
              </label>
              <select
                id="service-unit-type"
                className="field-select"
                value={serviceForm.unit_type}
                onChange={(event) =>
                  setServiceForm((prev) => ({
                    ...prev,
                    unit_type: event.target.value as ServiceUnitType,
                  }))
                }
                data-testid="services-service-input-unit-type"
                disabled={serviceFormBusy}
              >
                {UNIT_TYPES.map((ut) => (
                  <option key={ut} value={ut}>
                    {t(UNIT_TYPE_I18N_KEY[ut])}
                  </option>
                ))}
              </select>
            </div>

            {/* Sprint 123 — "Other" is an opaque unit backed by the
                per-company managed unit catalog; ServicesAdminPage never
                tracks a `company` of its own (this admin acts on the
                operator's own company implicitly), so no companyId is
                passed here — same implicit-default behaviour the rest of
                this form already relies on for `company` on create. */}
            {serviceForm.unit_type === "OTHER" && (
              <ManagedUnitPicker
                id="service-managed-unit"
                managedUnitId={serviceForm.managed_unit}
                customUnitLabel={serviceForm.custom_unit_label}
                onChange={(managedUnitId, label) =>
                  setServiceForm((prev) => ({
                    ...prev,
                    managed_unit: managedUnitId,
                    custom_unit_label: label,
                  }))
                }
                disabled={serviceFormBusy}
              />
            )}

            <div className="form-2col">
              <div className="field">
                <label
                  className="field-label"
                  htmlFor="service-default-unit-price"
                >
                  {t("services.field_default_unit_price")}
                </label>
                <input
                  id="service-default-unit-price"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={serviceForm.default_unit_price}
                  onChange={(event) =>
                    setServiceForm((prev) => ({
                      ...prev,
                      default_unit_price: event.target.value,
                    }))
                  }
                  data-testid="services-service-input-default-unit-price"
                  disabled={serviceFormBusy}
                />
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("services.field_reference_price_hint")}
                </div>
              </div>
              <div className="field">
                <label
                  className="field-label"
                  htmlFor="service-default-vat-pct"
                >
                  {t("services.field_default_vat_pct")}
                </label>
                <input
                  id="service-default-vat-pct"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={serviceForm.default_vat_pct}
                  onChange={(event) =>
                    setServiceForm((prev) => ({
                      ...prev,
                      default_vat_pct: event.target.value,
                    }))
                  }
                  data-testid="services-service-input-default-vat-pct"
                  disabled={serviceFormBusy}
                />
              </div>
            </div>

            <div className="field">
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <Toggle
                  checked={serviceForm.is_active}
                  onChange={(event) =>
                    setServiceForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="services-service-input-is-active"
                  disabled={serviceFormBusy}
                />
                <span>{t("services.field_is_active")}</span>
              </label>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeServiceModal}
                disabled={serviceFormBusy}
                data-testid="services-service-modal-cancel"
              >
                {t("services.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={serviceFormBusy}
                data-testid="services-service-modal-save"
              >
                {serviceFormBusy
                  ? t("admin_form.saving")
                  : t("services.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* M5 C — catalog default-price bulk-raise modal */}
      {bulkOpen && (
        <div
          data-testid="services-bulk-raise-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("services.bulk_raise_button")}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: 640,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {t("services.bulk_raise_button")}
            </h3>

            <p className="muted" style={{ marginTop: 0, marginBottom: 16 }}>
              {t("services.bulk_raise_intro")}
            </p>

            {bulkError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="services-bulk-raise-error"
              >
                {bulkError}
              </div>
            )}

            {activeServices.length === 0 ? (
              <div className="muted" style={{ marginBottom: 16 }}>
                {t("services.bulk_raise_empty")}
              </div>
            ) : (
              <>
                {/* #108 Part D — shared multi-select treatment: Select
                    all / Clear all + count + filter, internal scroll. */}
                <MultiSelectToolbar
                  selectedCount={bulkSelectedIds.length}
                  onSelectAll={() => toggleBulkAll(true)}
                  onClearAll={() => toggleBulkAll(false)}
                  disabled={bulkBusy}
                  filterValue={bulkFilter}
                  onFilterChange={setBulkFilter}
                  testIdPrefix="services-bulk-raise"
                />
                {/* Sprint 139 §3 — grouped by category through the
                    SHARED picker, same shape as copy-from-defaults and
                    the customer price bulk-adjust. Three modals over
                    the same catalog used to present it three different
                    ways. */}
                <CategoryGroupedPicker
                  groups={bulkRaiseGroups}
                  getId={(service) => service.id}
                  renderItem={(service) => (
                    <>
                      {service.name} —{" "}
                      {formatDecimal(service.default_unit_price)}
                      {/* #108 Part C — live effect preview. Backend
                          HALF_UP is authoritative; a result at or below
                          zero shows red (the server rejects the whole
                          batch). */}
                      {bulkSelectedIds.includes(service.id) &&
                        (() => {
                          const next = previewAdjustedPrice(
                            service.default_unit_price,
                            bulkMode,
                            bulkAmount,
                            bulkDirection,
                          );
                          if (next === null) return null;
                          return (
                            <span
                              style={{
                                color:
                                  next <= 0
                                    ? "var(--red)"
                                    : "var(--green-2)",
                                fontWeight: 600,
                              }}
                              data-testid="services-bulk-raise-preview"
                            >
                              {" "}
                              → {next.toFixed(2)}
                            </span>
                          );
                        })()}
                    </>
                  )}
                  selectedIds={bulkSelectedIds}
                  onToggleItem={toggleBulkRow}
                  onToggleGroup={(group, checked) =>
                    setBulkSelectedIds((prev) => {
                      const ids = group.items.map((svc) => svc.id);
                      return checked
                        ? [...new Set([...prev, ...ids])]
                        : prev.filter((id) => !ids.includes(id));
                    })
                  }
                  disabled={bulkBusy}
                  testIdPrefix="services-bulk-raise"
                />
              </>
            )}

            <div className="form-2col">
              <div className="field">
                <label
                  className="field-label"
                  htmlFor="services-bulk-direction"
                >
                  {t("services.bulk_raise_direction_label")}
                </label>
                <select
                  id="services-bulk-direction"
                  className="field-select"
                  value={bulkDirection}
                  onChange={(event) =>
                    setBulkDirection(
                      event.target.value === "lower" ? "lower" : "raise",
                    )
                  }
                  data-testid="services-bulk-raise-direction"
                  disabled={bulkBusy}
                >
                  <option value="raise">
                    {t("services.bulk_raise_direction_raise")}
                  </option>
                  <option value="lower">
                    {t("services.bulk_raise_direction_lower")}
                  </option>
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="services-bulk-mode">
                  {t("services.bulk_raise_mode_label")}
                </label>
                <select
                  id="services-bulk-mode"
                  className="field-select"
                  value={bulkMode}
                  onChange={(event) =>
                    setBulkMode(
                      event.target.value === "fixed" ? "fixed" : "percent",
                    )
                  }
                  data-testid="services-bulk-raise-mode"
                  disabled={bulkBusy}
                >
                  <option value="percent">
                    {t("services.bulk_raise_mode_percent")}
                  </option>
                  <option value="fixed">
                    {t("services.bulk_raise_mode_fixed")}
                  </option>
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="services-bulk-amount">
                  {t("services.bulk_raise_amount_label")}
                </label>
                <input
                  id="services-bulk-amount"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={bulkAmount}
                  onChange={(event) => setBulkAmount(event.target.value)}
                  data-testid="services-bulk-raise-amount"
                  disabled={bulkBusy}
                />
                <div className="muted small" style={{ marginTop: 4 }}>
                  {bulkMode === "percent"
                    ? t("services.bulk_raise_amount_percent_hint")
                    : t("services.bulk_raise_amount_fixed_hint")}
                </div>
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeBulkRaise}
                disabled={bulkBusy}
                data-testid="services-bulk-raise-cancel"
              >
                {t("services.cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleBulkRaise}
                disabled={bulkBusy || activeServices.length === 0}
                data-testid="services-bulk-raise-apply"
              >
                {bulkBusy
                  ? t("admin_form.saving")
                  : t("services.bulk_raise_apply")}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={
          deleteKind === "service"
            ? t("services.delete_service_confirm_title")
            : t("services.delete_category_confirm_title")
        }
        body={
          deleteKind === "service"
            ? t("services.delete_service_confirm_body")
            : t("services.delete_category_confirm_body")
        }
        confirmLabel={t("services.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />

      {/* Sprint 137 item 7 — ONE confirmation for the whole selection.
          Rendered unconditionally and driven through the ref only
          (CLAUDE.md §3: a conditionally mounted native <dialog> is
          invisible and its trigger looks dead). */}
      {/* Sprint 138 §2a — ONE confirmation, and it NAMES the cascade:
          archiving a category deactivates every service inside it, and
          unarchiving brings back only the category. Unconditionally
          rendered + ref-driven (CLAUDE.md §3). */}
      <ConfirmDialog
        ref={categoryArchiveDialogRef}
        title={t(
          categoryArchiveTarget?.is_active === false
            ? "services.category_unarchive_confirm_title"
            : "services.category_archive_confirm_title",
        )}
        body={t(
          categoryArchiveTarget?.is_active === false
            ? "services.category_unarchive_confirm_body"
            : "services.category_archive_confirm_body",
          {
            count: categoryArchiveTarget?.active_service_count ?? 0,
          },
        )}
        confirmLabel={t(
          categoryArchiveTarget?.is_active === false
            ? "services.category_unarchive_button"
            : "services.category_archive_button",
        )}
        onConfirm={handleConfirmCategoryArchive}
        onCancel={() => setCategoryArchiveTarget(null)}
        busy={categoryArchiveBusy}
        destructive={categoryArchiveTarget?.is_active !== false}
      />

      {/* Sprint 138 §2b — bulk move to another category. This is what
          EMPTIES a category so it can be deleted; `Service.category` is
          not nullable, so a service only leaves a category by joining
          another one. */}
      {moveOpen && (
        <div
          data-testid="services-move-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("services.bulk_move_button")}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
        >
          <div
            className="card"
            style={{ maxWidth: 520, width: "100%", padding: 24 }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {t("services.move_modal_title", {
                count: serviceBulkIds.length,
              })}
            </h3>
            <p className="muted" style={{ marginTop: 0, marginBottom: 16 }}>
              {t("services.move_modal_intro")}
            </p>

            {moveError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="services-move-error"
              >
                {moveError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="services-move-target">
                {t("services.move_target_label")}
              </label>
              <select
                id="services-move-target"
                className="field-select"
                data-testid="services-move-target"
                value={moveTargetCategory === "" ? "" : String(moveTargetCategory)}
                onChange={(event) =>
                  setMoveTargetCategory(
                    event.target.value === ""
                      ? ""
                      : Number(event.target.value),
                  )
                }
                disabled={moveBusy}
              >
                <option value="">{t("services.move_target_placeholder")}</option>
                {moveTargetCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.is_active
                      ? category.name
                      : `${category.name} — ${t("admin.status_inactive")}`}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Toggle
                  checked={moveIncludeArchived}
                  onChange={(event) =>
                    setMoveIncludeArchived(event.target.checked)
                  }
                  data-testid="services-move-include-archived"
                  disabled={moveBusy}
                />
                <span>{t("services.move_include_archived")}</span>
              </label>
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("services.move_include_archived_hint")}
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setMoveOpen(false)}
                disabled={moveBusy}
                data-testid="services-move-cancel"
              >
                {t("services.cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void handleConfirmMove()}
                disabled={moveBusy || moveTargetCategory === ""}
                data-testid="services-move-apply"
              >
                {moveBusy
                  ? t("admin_form.saving")
                  : t("services.move_apply")}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        ref={serviceBulkDialogRef}
        title={t(
          serviceBulkActionKind === "delete"
            ? "services.bulk_delete_confirm_title"
            : serviceBulkActionKind === "activate"
              ? "services.bulk_activate_confirm_title"
              : "services.bulk_deactivate_confirm_title",
          { count: serviceBulkIds.length },
        )}
        body={t(
          serviceBulkActionKind === "delete"
            ? "services.bulk_delete_confirm_body"
            : serviceBulkActionKind === "activate"
              ? "services.bulk_activate_confirm_body"
              : "services.bulk_deactivate_confirm_body",
          { count: serviceBulkIds.length },
        )}
        confirmLabel={t(
          serviceBulkActionKind === "delete"
            ? "services.bulk_delete_button"
            : serviceBulkActionKind === "activate"
              ? "services.bulk_activate_button"
              : "services.bulk_deactivate_button",
        )}
        onConfirm={handleConfirmServiceBulkDelete}
        busy={serviceBulkBusy}
        destructive={serviceBulkActionKind === "delete"}
      />
    </div>
  );
}
