import type { FormEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createService,
  createServiceCategory,
  deleteService,
  deleteServiceCategory,
  listServiceCategories,
  listServices,
  updateService,
  updateServiceCategory,
} from "../../api/admin";
import type {
  Service,
  ServiceCategory,
  ServiceCategoryCreatePayload,
  ServiceCreatePayload,
  ServiceUnitType,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";

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

type Tab = "services" | "categories";

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
  default_unit_price: string;
  default_vat_pct: string;
  is_active: boolean;
}

const EMPTY_SERVICE_FORM: ServiceFormState = {
  category: "",
  name: "",
  description: "",
  unit_type: "HOURS",
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

  // Initial parallel load.
  useEffect(() => {
    const cancelled = { current: false };
    async function load() {
      try {
        const [categoriesData, servicesData] = await Promise.all([
          listServiceCategories(),
          listServices(),
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
  }, []);

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
    setServiceFormBusy(true);
    setServiceFormError("");
    const payload: ServiceCreatePayload = {
      category: Number(serviceForm.category),
      name: serviceForm.name.trim(),
      description: serviceForm.description,
      unit_type: serviceForm.unit_type,
      default_unit_price: serviceForm.default_unit_price.trim(),
      default_vat_pct: serviceForm.default_vat_pct.trim(),
      is_active: serviceForm.is_active,
    };
    try {
      if (serviceMode === "create") {
        const created = await createService(payload);
        setServices((prev) =>
          [...prev, created].sort((a, b) => a.name.localeCompare(b.name)),
        );
        closeServiceModal();
      } else if (serviceMode === "edit" && selectedService) {
        const updated = await updateService(selectedService.id, payload);
        setServices((prev) =>
          prev
            .map((s) => (s.id === updated.id ? updated : s))
            .sort((a, b) => a.name.localeCompare(b.name)),
        );
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
        setServices((prev) =>
          prev.filter((s) => s.id !== deleteServiceTarget.id),
        );
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

  function handleCancelDelete() {
    setDeleteCategoryTarget(null);
    setDeleteServiceTarget(null);
    setDeleteKind(null);
  }

  // -------- Render --------

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
      </div>

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
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
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
                        onClick={() => setSelectedService(service)}
                      >
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
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="services-service-delete-button"
                    onClick={() => openDeleteServiceDialog(selectedService)}
                  >
                    {t("services.delete_button")}
                  </button>
                </div>
              </div>

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
      ) : (
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
                      <th>{t("services.col_active")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map((category) => (
                      <tr
                        key={category.id}
                        data-testid="services-category-row"
                        data-category-id={category.id}
                        onClick={() => setSelectedCategory(category)}
                      >
                        <td>{category.name}</td>
                        <td className="muted small">
                          {category.description || "—"}
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
                </div>
              </div>

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
                <input
                  type="checkbox"
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
                <input
                  type="checkbox"
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
    </div>
  );
}
