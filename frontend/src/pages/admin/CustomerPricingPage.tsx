import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  bulkRaiseCustomerPrices,
  copyDefaultPricesToCustomer,
  createCustomerCustomPrice,
  createCustomerPrice,
  deleteCustomerCustomPrice,
  deleteCustomerPrice,
  getCustomer,
  listCustomerCustomPrices,
  listCustomerPrices,
  listServices,
  updateCustomerCustomPrice,
  updateCustomerPrice,
} from "../../api/admin";
import type {
  CustomerAdmin,
  CustomerCustomPrice,
  CustomerCustomPriceCreatePayload,
  CustomerPriceCopyFromDefaultResult,
  CustomerServicePrice,
  CustomerServicePriceCreatePayload,
  Service,
  ServiceUnitType,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { previewAdjustedPrice } from "../../utils/bulkAdjust";

/**
 * Sprint 28 Batch 5 — Per-customer contract pricing.
 *
 * Customer-scoped sidebar entry. The page lists every
 * `CustomerServicePrice` row for the URL's customer, grouped by
 * service for readability. View-first per
 * `docs/product/meeting-2026-05-15-system-requirements.md` §3:
 *   - list rows are read-only
 *   - clicking a row opens a read-only detail panel
 *   - Add / Edit / Delete are explicit modal actions
 *
 * Only an active row triggers the instant-ticket path (Batch 7). The
 * page intentionally does NOT resolve "the effective price for service
 * X right now" — that is the backend resolver's job. We just expose
 * the raw rows for the admin to manage.
 *
 * Permission: SUPER_ADMIN + COMPANY_ADMIN reach this route via
 * `AdminRoute` (see `App.tsx`). Backend re-gates with
 * `IsSuperAdminOrCompanyAdminForCustomerProvider` on every list /
 * create / detail call.
 */

/**
 * RF-2 — the sentinel `service` value for the "Other / Custom…" option
 * at the foot of the service dropdown. Picking it swaps the shared form
 * over to the custom-price shape (free-text name + its own unit type)
 * and routes the submit to the custom-price endpoint. A real service id
 * is always a number, so the sentinel cannot collide.
 */
const CUSTOM_SERVICE_SENTINEL = "__custom__" as const;

type ServiceSelection = number | "" | typeof CUSTOM_SERVICE_SENTINEL;

/**
 * RF-2 — one form state backs both price kinds. `service` discriminates:
 * the sentinel means custom (uses `custom_name` / `unit_type` /
 * `custom_unit_label`), a number means a catalog contract price (which
 * ignores those three). The price / VAT / validity fields are shared —
 * they were already identical in both flows.
 */
interface PriceFormState {
  service: ServiceSelection;
  custom_name: string;
  unit_type: ServiceUnitType;
  custom_unit_label: string;
  unit_price: string;
  vat_pct: string;
  valid_from: string;
  valid_to: string; // empty string = open-ended
  is_active: boolean;
}

/**
 * RF-2 — a row in the unified pricing list. Contract and custom rows
 * live on separate endpoints and have different shapes, so they are
 * discriminated rather than merged into one loose type.
 */
type PricingRow =
  | { kind: "contract"; row: CustomerServicePrice }
  | { kind: "custom"; row: CustomerCustomPrice };

function todayISO(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function buildEmptyForm(): PriceFormState {
  return {
    service: "",
    custom_name: "",
    unit_type: "HOURS",
    custom_unit_label: "",
    unit_price: "0.00",
    vat_pct: "21.00",
    valid_from: todayISO(),
    valid_to: "",
    is_active: true,
  };
}

// The unit-type constants mirror ServicesAdminPage; kept local here to
// avoid a cross-page export churn (three tiny literals, no behaviour).
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

function formatDateOnly(value: string, locale: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}

export function CustomerPricingPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation("common");
  const numericId = useMemo(() => {
    if (!id) return null;
    const n = Number(id);
    return Number.isFinite(n) ? n : null;
  }, [id]);

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [prices, setPrices] = useState<CustomerServicePrice[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  // RF-2 — one selection / modal / delete-dialog for both price kinds.
  const [selected, setSelected] = useState<PricingRow | null>(null);

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [form, setForm] = useState<PriceFormState>(buildEmptyForm);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<PricingRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // M5 C / #108 Part C — bulk-adjust modal state (catalog-price
  // section only). `bulkDirection` picks raise vs lower.
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkSelectedIds, setBulkSelectedIds] = useState<number[]>([]);
  const [bulkMode, setBulkMode] = useState<"percent" | "fixed">("percent");
  const [bulkDirection, setBulkDirection] = useState<"raise" | "lower">(
    "raise",
  );
  const [bulkAmount, setBulkAmount] = useState("");
  const [bulkValidFrom, setBulkValidFrom] = useState(todayISO);
  const [bulkError, setBulkError] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

  // Sprint 8B — copy-from-default modal state. Seeds contract prices for
  // this customer from the provider catalog defaults (active services
  // only). `copyResult` holds the created/skipped summary after a
  // successful run so the per-service skip outcome stays visible.
  const [copyOpen, setCopyOpen] = useState(false);
  const [copySelectedServiceIds, setCopySelectedServiceIds] = useState<
    number[]
  >([]);
  const [copyValidFrom, setCopyValidFrom] = useState(todayISO);
  const [copyValidTo, setCopyValidTo] = useState("");
  const [copyError, setCopyError] = useState("");
  const [copyBusy, setCopyBusy] = useState(false);
  const [copyResult, setCopyResult] =
    useState<CustomerPriceCopyFromDefaultResult | null>(null);

  // Custom (non-catalog) price lines — rendered in the same unified
  // list as the contract rows above; only the source list is separate
  // (they live on their own endpoint).
  const [customPrices, setCustomPrices] = useState<CustomerCustomPrice[]>([]);

  // Initial parallel load — customer (for title), pricing list,
  // service list (for the modal dropdown — filtered to active so
  // admins do not accidentally price a retired service).
  useEffect(() => {
    const cancelled = { current: false };
    async function load(customerId: number) {
      try {
        const [customerData, pricesData, servicesData, customPricesData] =
          await Promise.all([
            getCustomer(customerId),
            listCustomerPrices(customerId),
            // Full catalog (active + inactive). The Default-price column must
            // resolve for pricing rows whose service was later archived, so
            // serviceById is built from every service; the dropdown + create
            // defaults filter down to active-only (see activeServices).
            listServices(),
            // M5 A — custom (non-catalog) price lines for this customer.
            listCustomerCustomPrices(customerId),
          ]);
        if (cancelled.current) return;
        setCustomer(customerData);
        setPrices(pricesData);
        setServices(servicesData);
        setCustomPrices(customPricesData);
        setLoading(false);
      } catch (err) {
        if (!cancelled.current) {
          setLoadError(getApiError(err));
          setLoading(false);
        }
      }
    }
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled.current) {
          setLoadError(t("customer_pricing.load_error"));
          setLoading(false);
        }
      });
    } else {
      load(numericId);
    }
    return () => {
      cancelled.current = true;
    };
  }, [numericId, t]);

  function openCreateModal() {
    setMode("create");
    // Prefill the editable contract price + VAT from the initially-selected
    // service's catalog defaults (the admin can still override before
    // saving). Previously only VAT was prefilled; unit_price stayed at 0.00.
    const first = activeServices.length > 0 ? activeServices[0] : null;
    setForm({
      ...buildEmptyForm(),
      service: first ? first.id : "",
      unit_price: first ? first.default_unit_price : "0.00",
      vat_pct: first ? first.default_vat_pct : "21.00",
    });
    setFormError("");
  }

  function openEditModal(entry: PricingRow) {
    setMode("edit");
    if (entry.kind === "custom") {
      const price = entry.row;
      setForm({
        ...buildEmptyForm(),
        service: CUSTOM_SERVICE_SENTINEL,
        custom_name: price.custom_name,
        unit_type: price.unit_type,
        custom_unit_label: price.custom_unit_label,
        unit_price: price.unit_price,
        vat_pct: price.vat_pct,
        valid_from: price.valid_from,
        valid_to: price.valid_to ?? "",
        is_active: price.is_active,
      });
    } else {
      const price = entry.row;
      setForm({
        ...buildEmptyForm(),
        service: price.service,
        unit_price: price.unit_price,
        vat_pct: price.vat_pct,
        valid_from: price.valid_from,
        valid_to: price.valid_to ?? "",
        is_active: price.is_active,
      });
    }
    setFormError("");
  }

  function closeFormModal() {
    setMode(null);
    setForm(buildEmptyForm());
    setFormError("");
  }

  async function handleSubmitForm(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    if (form.service === "") {
      setFormError(t("customer_pricing.error_service_required"));
      return;
    }
    const isCustom = form.service === CUSTOM_SERVICE_SENTINEL;
    if (isCustom) {
      if (!form.custom_name.trim()) {
        setFormError(t("customer_custom_pricing.error_name_required"));
        return;
      }
      if (!form.unit_type) {
        setFormError(t("customer_custom_pricing.error_unit_type_required"));
        return;
      }
      // A bare "Other" unit renders as nothing on the price line, so the
      // label is required exactly when OTHER is chosen. The backend
      // blanks it for every other unit type, so it is not sent then.
      if (form.unit_type === "OTHER" && !form.custom_unit_label.trim()) {
        setFormError(t("customer_custom_pricing.error_unit_label_required"));
        return;
      }
    }
    const priceNumber = Number(form.unit_price);
    if (!Number.isFinite(priceNumber) || priceNumber < 0) {
      setFormError(t("customer_pricing.error_price_invalid"));
      return;
    }
    const vatNumber = Number(form.vat_pct);
    if (!Number.isFinite(vatNumber) || vatNumber < 0) {
      setFormError(t("customer_pricing.error_vat_invalid"));
      return;
    }
    if (!form.valid_from) {
      setFormError(t("customer_pricing.error_valid_from_required"));
      return;
    }
    // Client-side check matches the backend validator: valid_to (when
    // provided) must be >= valid_from. The backend still owns the
    // hard rule — this only short-circuits the round-trip.
    if (form.valid_to && form.valid_to < form.valid_from) {
      setFormError(t("customer_pricing.error_valid_to_before_valid_from"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    // Shared across both payload shapes — these fields were already
    // identical in the two flows this form replaces.
    const shared = {
      unit_price: form.unit_price.trim(),
      vat_pct: form.vat_pct.trim(),
      valid_from: form.valid_from,
      valid_to: form.valid_to === "" ? null : form.valid_to,
      is_active: form.is_active,
    };
    try {
      if (isCustom) {
        const payload: CustomerCustomPriceCreatePayload = {
          ...shared,
          custom_name: form.custom_name.trim(),
          unit_type: form.unit_type,
          // Only OTHER carries a label; the backend forces it blank for
          // every concrete unit type, so send it only where meaningful.
          custom_unit_label:
            form.unit_type === "OTHER" ? form.custom_unit_label.trim() : "",
        };
        if (mode === "create") {
          const created = await createCustomerCustomPrice(numericId, payload);
          setCustomPrices((prev) => [created, ...prev]);
          closeFormModal();
        } else if (mode === "edit" && selected?.kind === "custom") {
          const updated = await updateCustomerCustomPrice(
            numericId,
            selected.row.id,
            payload,
          );
          setCustomPrices((prev) =>
            prev.map((p) => (p.id === updated.id ? updated : p)),
          );
          setSelected({ kind: "custom", row: updated });
          closeFormModal();
        }
      } else {
        const payload: CustomerServicePriceCreatePayload = {
          ...shared,
          service: Number(form.service),
        };
        if (mode === "create") {
          const created = await createCustomerPrice(numericId, payload);
          setPrices((prev) => [created, ...prev]);
          closeFormModal();
        } else if (mode === "edit" && selected?.kind === "contract") {
          const updated = await updateCustomerPrice(
            numericId,
            selected.row.id,
            payload,
          );
          setPrices((prev) =>
            prev.map((p) => (p.id === updated.id ? updated : p)),
          );
          setSelected({ kind: "contract", row: updated });
          closeFormModal();
        }
      }
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
    }
  }

  function openDeleteDialog(entry: PricingRow) {
    setDeleteTarget(entry);
    deleteDialogRef.current?.open();
  }

  async function handleConfirmDelete() {
    if (numericId === null || !deleteTarget) return;
    setDeleteBusy(true);
    const targetId = deleteTarget.row.id;
    try {
      if (deleteTarget.kind === "custom") {
        await deleteCustomerCustomPrice(numericId, targetId);
        setCustomPrices((prev) => prev.filter((p) => p.id !== targetId));
      } else {
        await deleteCustomerPrice(numericId, targetId);
        setPrices((prev) => prev.filter((p) => p.id !== targetId));
      }
      if (selected?.kind === deleteTarget.kind && selected.row.id === targetId) {
        setSelected(null);
      }
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  // ---- M5 C / #108 Part C — bulk-adjust handlers (catalog-price
  // section) ----------------
  function openBulkRaise() {
    setBulkSelectedIds(activePrices.map((p) => p.id));
    setBulkMode("percent");
    setBulkDirection("raise");
    setBulkAmount("");
    setBulkValidFrom(todayISO());
    setBulkError("");
    setBulkOpen(true);
  }

  function closeBulkRaise() {
    setBulkOpen(false);
    setBulkError("");
  }

  function toggleBulkAll(checked: boolean) {
    setBulkSelectedIds(checked ? activePrices.map((p) => p.id) : []);
  }

  function toggleBulkRow(priceId: number, checked: boolean) {
    setBulkSelectedIds((prev) =>
      checked ? [...prev, priceId] : prev.filter((id) => id !== priceId),
    );
  }

  async function handleBulkRaise() {
    if (numericId === null) return;
    if (bulkSelectedIds.length === 0) {
      setBulkError(t("customer_pricing.bulk_raise_error_no_selection"));
      return;
    }
    const amountNumber = Number(bulkAmount);
    if (!Number.isFinite(amountNumber) || amountNumber <= 0) {
      setBulkError(t("customer_pricing.bulk_raise_error_amount"));
      return;
    }
    // #108 Part C — client mirrors of the backend guards (the server
    // re-checks both): a percent lower must stay below 100.
    if (
      bulkDirection === "lower" &&
      bulkMode === "percent" &&
      amountNumber >= 100
    ) {
      setBulkError(t("customer_pricing.bulk_raise_error_percent_lower"));
      return;
    }
    if (!bulkValidFrom) {
      setBulkError(t("customer_pricing.error_valid_from_required"));
      return;
    }
    setBulkBusy(true);
    setBulkError("");
    try {
      await bulkRaiseCustomerPrices(numericId, {
        prices: bulkSelectedIds,
        mode: bulkMode,
        amount: bulkAmount.trim(),
        direction: bulkDirection,
        valid_from: bulkValidFrom,
      });
      // Re-fetch the catalog price list so the new validity-window rows
      // surface (existing rows stay — history preserved server-side).
      const refreshed = await listCustomerPrices(numericId);
      setPrices(refreshed);
      closeBulkRaise();
    } catch (err) {
      setBulkError(getApiError(err));
    } finally {
      setBulkBusy(false);
    }
  }

  // ---- Sprint 8B — copy-from-default handlers ---------------------------
  function openCopyDefault() {
    setCopySelectedServiceIds([]);
    setCopyValidFrom(todayISO());
    setCopyValidTo("");
    setCopyError("");
    setCopyResult(null);
    setCopyOpen(true);
  }

  function closeCopyDefault() {
    setCopyOpen(false);
    setCopyError("");
    setCopyResult(null);
  }

  function toggleCopyAll(checked: boolean) {
    setCopySelectedServiceIds(
      checked ? activeServices.map((s) => s.id) : [],
    );
  }

  function toggleCopyService(serviceId: number, checked: boolean) {
    setCopySelectedServiceIds((prev) =>
      checked ? [...prev, serviceId] : prev.filter((id) => id !== serviceId),
    );
  }

  async function handleCopyDefault() {
    if (numericId === null) return;
    if (copySelectedServiceIds.length === 0) {
      setCopyError(t("customer_pricing.copy_from_default_error_no_selection"));
      return;
    }
    if (!copyValidFrom) {
      setCopyError(t("customer_pricing.error_valid_from_required"));
      return;
    }
    if (copyValidTo && copyValidTo < copyValidFrom) {
      setCopyError(t("customer_pricing.error_valid_to_before_valid_from"));
      return;
    }
    setCopyBusy(true);
    setCopyError("");
    try {
      const result = await copyDefaultPricesToCustomer(numericId, {
        services: copySelectedServiceIds,
        valid_from: copyValidFrom,
        valid_to: copyValidTo || null,
      });
      // Refresh the catalog price list so the seeded rows surface; keep
      // the modal open so the created/skipped summary stays visible.
      const refreshed = await listCustomerPrices(numericId);
      setPrices(refreshed);
      setCopyResult(result);
      setCopySelectedServiceIds([]);
    } catch (err) {
      setCopyError(getApiError(err));
    } finally {
      setCopyBusy(false);
    }
  }

  const serviceNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const s of services) {
      map.set(s.id, s.name);
    }
    return map;
  }, [services]);

  // Full service lookup (id -> Service) so we can surface each catalog
  // service's reference `default_unit_price` next to the contract price
  // (table column) and re-default the form on a service change.
  const serviceById = useMemo(() => {
    const map = new Map<number, Service>();
    for (const s of services) {
      map.set(s.id, s);
    }
    return map;
  }, [services]);

  // Active-only subset for the create dropdown + create defaults — a retired
  // service must never be offered for a NEW contract price (existing rows on
  // an archived service still resolve via serviceById / the full catalog).
  // Plain derived value (the filter is cheap and the React Compiler memoizes
  // it): a manual useMemo here trips react-hooks/preserve-manual-memoization
  // because the earlier-defined openCreateModal captures it.
  const activeServices = services.filter((s) => s.is_active);

  // M5 C — active catalog prices are the only rows the bulk-raise modal
  // can act on. Plain derived value (same rationale as activeServices:
  // the earlier-defined openBulkRaise captures it).
  const activePrices = prices.filter((p) => p.is_active);

  // Build the service name shown in the table — prefer the embedded
  // `service_name` (always present) but fall back to the dropdown
  // lookup if a stale row references a now-renamed service.
  function resolveServiceName(price: CustomerServicePrice): string {
    if (price.service_name) return price.service_name;
    return serviceNameById.get(price.service) ?? `#${price.service}`;
  }

  // RF-2 — the display name for either row kind.
  function resolveRowName(entry: PricingRow): string {
    return entry.kind === "custom"
      ? entry.row.custom_name
      : resolveServiceName(entry.row);
  }

  /**
   * RF-2 — the unit a row is priced in. A custom OTHER row renders its
   * operator-supplied `custom_unit_label` ("m3"); every other row falls
   * back to the translated unit-type label. A contract row takes its
   * unit from the catalog service (archived services still resolve via
   * the full `serviceById` map).
   */
  function resolveUnitLabel(entry: PricingRow): string {
    if (entry.kind === "custom") {
      if (entry.row.unit_type === "OTHER" && entry.row.custom_unit_label) {
        return entry.row.custom_unit_label;
      }
      return t(UNIT_TYPE_I18N_KEY[entry.row.unit_type]);
    }
    const unitType = serviceById.get(entry.row.service)?.unit_type;
    return unitType ? t(UNIT_TYPE_I18N_KEY[unitType]) : "—";
  }

  // RF-2 — the single list backing the unified table. Contract rows
  // first, then custom rows; each source list keeps its own API
  // ordering. Plain derived value (same rationale as activeServices).
  const unifiedRows: PricingRow[] = [
    ...prices.map((row): PricingRow => ({ kind: "contract", row })),
    ...customPrices.map((row): PricingRow => ({ kind: "custom", row })),
  ];

  const isCustomForm = form.service === CUSTOM_SERVICE_SENTINEL;

  // RF-2 — the modal title follows the chosen kind: with "Other /
  // Custom…" selected the form is no longer adding a contract price,
  // so the contract copy would be actively wrong.
  const formModalTitle = isCustomForm
    ? mode === "create"
      ? t("customer_custom_pricing.add_modal_title")
      : t("customer_custom_pricing.edit_modal_title")
    : mode === "create"
      ? t("customer_pricing.add_modal_title")
      : t("customer_pricing.edit_modal_title");

  const customerName = customer?.name ?? "";

  return (
    <div data-testid="customer-pricing-page">
      <Link
        to={`/admin/customers/${numericId ?? ""}`}
        className="link-back"
        data-testid="customer-pricing-back"
      >
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("customer_form.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">
            {customerName
              ? `${customerName} · ${t("customer_pricing.page_title")}`
              : t("customer_pricing.page_title")}
          </h2>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="customer-pricing-copy-default-button"
            onClick={openCopyDefault}
            disabled={loading || numericId === null}
          >
            {t("customer_pricing.copy_from_default_button")}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="customer-pricing-bulk-raise-button"
            onClick={openBulkRaise}
            disabled={loading || numericId === null}
          >
            {t("customer_pricing.bulk_raise_button")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="customer-pricing-add-button"
            onClick={openCreateModal}
            // RF-2 — no longer gated on the catalog having services: the
            // "Other / Custom…" option is always available, so an empty
            // catalog must not block adding a custom price line.
            disabled={loading || numericId === null}
          >
            {t("customer_pricing.add_button")}
          </button>
        </div>
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
      ) : (
        <>
          <div className="card" data-testid="customer-pricing-list">
            {unifiedRows.length === 0 ? (
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="customer-pricing-empty"
              >
                <h3 style={{ marginBottom: 8 }}>
                  {t("customer_pricing.empty_title")}
                </h3>
                <p className="muted" style={{ margin: 0 }}>
                  {t("customer_pricing.empty_description")}
                </p>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("customer_pricing.col_service")}</th>
                      <th>{t("customer_pricing.col_unit")}</th>
                      <th>{t("customer_pricing.col_unit_price")}</th>
                      <th>{t("customer_pricing.col_default_price")}</th>
                      <th>{t("customer_pricing.col_vat_pct")}</th>
                      <th>{t("customer_pricing.col_valid_from")}</th>
                      <th>{t("customer_pricing.col_valid_to")}</th>
                      <th>{t("customer_pricing.col_active")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unifiedRows.map((entry) => (
                      <tr
                        key={`${entry.kind}-${entry.row.id}`}
                        data-testid="customer-pricing-row"
                        data-price-id={entry.row.id}
                        data-price-kind={entry.kind}
                        onClick={() => setSelected(entry)}
                      >
                        <td>
                          {resolveRowName(entry)}
                          {entry.kind === "custom" && (
                            <span
                              className="badge badge-muted"
                              style={{ marginLeft: 8 }}
                              data-testid="customer-pricing-custom-tag"
                            >
                              {t("customer_pricing.tag_custom")}
                            </span>
                          )}
                        </td>
                        <td>{resolveUnitLabel(entry)}</td>
                        <td>{entry.row.unit_price}</td>
                        <td>
                          {entry.kind === "custom"
                            ? "—"
                            : (serviceById.get(entry.row.service)
                                ?.default_unit_price ?? "—")}
                        </td>
                        <td>{entry.row.vat_pct}</td>
                        <td>
                          {formatDateOnly(entry.row.valid_from, dateLocale)}
                        </td>
                        <td>
                          {entry.row.valid_to === null
                            ? t("customer_pricing.valid_to_open_ended")
                            : formatDateOnly(entry.row.valid_to, dateLocale)}
                        </td>
                        <td>
                          {entry.row.is_active
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

          {selected && (
            <section
              className="card"
              data-testid="customer-pricing-detail"
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
                    {selected.kind === "custom"
                      ? t("customer_custom_pricing.detail_title")
                      : t("customer_pricing.detail_title")}
                  </div>
                  <h3 className="section-title" style={{ margin: 0 }}>
                    {resolveRowName(selected)}
                  </h3>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-pricing-edit-button"
                    onClick={() => openEditModal(selected)}
                  >
                    {t("customer_pricing.edit_button")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-pricing-delete-button"
                    onClick={() => openDeleteDialog(selected)}
                  >
                    {t("customer_pricing.delete_button")}
                  </button>
                </div>
              </div>

              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_unit")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-pricing-detail-unit"
                  >
                    {resolveUnitLabel(selected)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_unit_price")}
                  </span>
                  <span
                    className="detail-kv-val"
                    data-testid="customer-pricing-detail-unit-price"
                  >
                    {selected.row.unit_price}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_vat_pct")}
                  </span>
                  <span className="detail-kv-val">{selected.row.vat_pct}</span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_valid_from")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDateOnly(selected.row.valid_from, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_valid_to")}
                  </span>
                  <span className="detail-kv-val">
                    {selected.row.valid_to === null
                      ? t("customer_pricing.valid_to_open_ended")
                      : formatDateOnly(selected.row.valid_to, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.col_active")}
                  </span>
                  <span className="detail-kv-val">
                    {selected.row.is_active
                      ? t("admin.status_active")
                      : t("admin.status_inactive")}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.field_created_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selected.row.created_at, dateLocale)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">
                    {t("customer_pricing.field_updated_at")}
                  </span>
                  <span className="detail-kv-val">
                    {formatDate(selected.row.updated_at, dateLocale)}
                  </span>
                </div>
              </div>
            </section>
          )}

        </>
      )}

      {/* Create / edit modal. Single component used for both flows;
          `mode` drives the title + submit handler. */}
      {mode !== null && (
        <div
          data-testid="customer-pricing-modal"
          role="dialog"
          aria-modal="true"
          aria-label={formModalTitle}
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
            onSubmit={handleSubmitForm}
            className="card"
            style={{
              maxWidth: 600,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3
              style={{ marginTop: 0, marginBottom: 12 }}
              data-testid="customer-pricing-modal-title"
            >
              {formModalTitle}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-pricing-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="price-service">
                {t("customer_pricing.field_service")} *
              </label>
              <select
                id="price-service"
                className="field-select"
                value={form.service === "" ? "" : String(form.service)}
                onChange={(event) => {
                  const v = event.target.value;
                  if (v === "") {
                    setForm((prev) => ({ ...prev, service: "" }));
                    return;
                  }
                  // RF-2 — the "Other / Custom…" sentinel swaps the form
                  // to the custom shape. Leave the price + VAT the admin
                  // may already have typed; there is no catalog default
                  // to re-default from.
                  if (v === CUSTOM_SERVICE_SENTINEL) {
                    setForm((prev) => ({
                      ...prev,
                      service: CUSTOM_SERVICE_SENTINEL,
                    }));
                    return;
                  }
                  const nextId = Number(v);
                  const svc = serviceById.get(nextId);
                  setForm((prev) => ({
                    ...prev,
                    service: nextId,
                    // Re-default the editable price + VAT to the newly
                    // selected service's catalog defaults (still overridable).
                    // Only reachable in create mode — the select is disabled
                    // in edit mode, so an existing row's price is never reset.
                    unit_price: svc ? svc.default_unit_price : prev.unit_price,
                    vat_pct: svc ? svc.default_vat_pct : prev.vat_pct,
                  }));
                }}
                data-testid="customer-pricing-input-service"
                required
                disabled={formBusy || mode === "edit"}
              >
                <option value="">
                  {t("customer_pricing.field_service_placeholder")}
                </option>
                {activeServices.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} — {s.default_unit_price}
                  </option>
                ))}
                {/* RF-2 — always last: the escape hatch for work that is
                    not in the catalog. */}
                <option value={CUSTOM_SERVICE_SENTINEL}>
                  {t("customer_pricing.option_custom")}
                </option>
              </select>
              {mode === "edit" && (
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_pricing.field_service_locked_hint")}
                </div>
              )}
            </div>

            {/* RF-2 — the custom-price fields. Only rendered once the
                "Other / Custom…" option is chosen, so the common
                catalog path is unchanged. */}
            {isCustomForm && (
              <>
                <div className="field">
                  <label className="field-label" htmlFor="price-custom-name">
                    {t("customer_custom_pricing.field_name")} *
                  </label>
                  <input
                    id="price-custom-name"
                    className="field-input"
                    type="text"
                    maxLength={200}
                    value={form.custom_name}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        custom_name: event.target.value,
                      }))
                    }
                    placeholder={t(
                      "customer_custom_pricing.field_name_placeholder",
                    )}
                    data-testid="customer-pricing-input-custom-name"
                    required
                    disabled={formBusy}
                  />
                </div>

                <div className="field">
                  <label className="field-label" htmlFor="price-unit-type">
                    {t("services.field_unit_type")} *
                  </label>
                  <select
                    id="price-unit-type"
                    className="field-select"
                    value={form.unit_type}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        unit_type: event.target.value as ServiceUnitType,
                      }))
                    }
                    data-testid="customer-pricing-input-unit-type"
                    required
                    disabled={formBusy}
                  >
                    {UNIT_TYPES.map((ut) => (
                      <option key={ut} value={ut}>
                        {t(UNIT_TYPE_I18N_KEY[ut])}
                      </option>
                    ))}
                  </select>
                </div>

                {/* "Other" is an opaque unit with nothing to render, so
                    it takes an operator-supplied name ("m3", "pallet"). */}
                {form.unit_type === "OTHER" && (
                  <div className="field">
                    <label
                      className="field-label"
                      htmlFor="price-custom-unit-label"
                    >
                      {t("customer_custom_pricing.field_unit_label")} *
                    </label>
                    <input
                      id="price-custom-unit-label"
                      className="field-input"
                      type="text"
                      maxLength={50}
                      value={form.custom_unit_label}
                      onChange={(event) =>
                        setForm((prev) => ({
                          ...prev,
                          custom_unit_label: event.target.value,
                        }))
                      }
                      placeholder={t(
                        "customer_custom_pricing.field_unit_label_placeholder",
                      )}
                      data-testid="customer-pricing-input-custom-unit-label"
                      required
                      disabled={formBusy}
                    />
                  </div>
                )}
              </>
            )}

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="price-unit-price">
                  {t("customer_pricing.field_unit_price")} *
                </label>
                <input
                  id="price-unit-price"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.unit_price}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      unit_price: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-unit-price"
                  required
                  disabled={formBusy}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="price-vat-pct">
                  {t("customer_pricing.field_vat_pct")} *
                </label>
                <input
                  id="price-vat-pct"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={form.vat_pct}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      vat_pct: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-vat-pct"
                  required
                  disabled={formBusy}
                />
              </div>
            </div>

            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="price-valid-from">
                  {t("customer_pricing.field_valid_from")} *
                </label>
                <input
                  id="price-valid-from"
                  className="field-input"
                  type="date"
                  value={form.valid_from}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      valid_from: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-valid-from"
                  required
                  disabled={formBusy}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="price-valid-to">
                  {t("customer_pricing.field_valid_to")}
                </label>
                <input
                  id="price-valid-to"
                  className="field-input"
                  type="date"
                  value={form.valid_to}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      valid_to: event.target.value,
                    }))
                  }
                  data-testid="customer-pricing-input-valid-to"
                  disabled={formBusy}
                />
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_pricing.field_valid_to_hint")}
                </div>
              </div>
            </div>

            <div className="field">
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      is_active: event.target.checked,
                    }))
                  }
                  data-testid="customer-pricing-input-is-active"
                  disabled={formBusy}
                />
                <span>{t("customer_pricing.field_is_active")}</span>
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
                onClick={closeFormModal}
                disabled={formBusy}
                data-testid="customer-pricing-modal-cancel"
              >
                {t("customer_pricing.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="customer-pricing-modal-save"
              >
                {formBusy
                  ? t("admin_form.saving")
                  : t("customer_pricing.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* M5 C — bulk-raise modal (catalog-price section). */}
      {bulkOpen && (
        <div
          data-testid="customer-pricing-bulk-raise-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("customer_pricing.bulk_raise_button")}
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
              maxWidth: 600,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {t("customer_pricing.bulk_raise_button")}
            </h3>

            <p className="muted" style={{ marginTop: 0, marginBottom: 16 }}>
              {t("customer_pricing.bulk_raise_intro")}
            </p>

            {bulkError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-pricing-bulk-raise-error"
              >
                {bulkError}
              </div>
            )}

            {activePrices.length === 0 ? (
              <div className="muted" style={{ marginBottom: 16 }}>
                {t("customer_pricing.bulk_raise_empty")}
              </div>
            ) : (
              <>
                <div className="field">
                  <label
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <input
                      type="checkbox"
                      data-testid="customer-pricing-bulk-raise-select-all"
                      checked={bulkSelectedIds.length === activePrices.length}
                      onChange={(event) => toggleBulkAll(event.target.checked)}
                      disabled={bulkBusy}
                    />
                    <span>
                      {t("customer_pricing.bulk_raise_select_all")}
                    </span>
                  </label>
                </div>

                <div
                  style={{
                    border: "1px solid var(--border, #e5e7eb)",
                    borderRadius: 8,
                    padding: "8px 12px",
                    marginBottom: 16,
                    maxHeight: 220,
                    overflowY: "auto",
                  }}
                >
                  {activePrices.map((price) => (
                    <label
                      key={price.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "4px 0",
                      }}
                    >
                      <input
                        type="checkbox"
                        data-testid="customer-pricing-bulk-raise-row"
                        data-price-id={price.id}
                        checked={bulkSelectedIds.includes(price.id)}
                        onChange={(event) =>
                          toggleBulkRow(price.id, event.target.checked)
                        }
                        disabled={bulkBusy}
                      />
                      <span>
                        {resolveServiceName(price)} — {price.unit_price}
                        {/* #108 Part C — live effect preview. Backend
                            HALF_UP is authoritative; a result at or
                            below zero shows red (the server rejects
                            the whole batch). */}
                        {bulkSelectedIds.includes(price.id) &&
                          (() => {
                            const next = previewAdjustedPrice(
                              price.unit_price,
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
                                data-testid="customer-pricing-bulk-raise-preview"
                              >
                                {" "}
                                → {next.toFixed(2)}
                              </span>
                            );
                          })()}
                      </span>
                    </label>
                  ))}
                </div>
              </>
            )}

            <div className="form-2col">
              <div className="field">
                <label
                  className="field-label"
                  htmlFor="bulk-raise-direction"
                >
                  {t("customer_pricing.bulk_raise_direction_label")}
                </label>
                <select
                  id="bulk-raise-direction"
                  className="field-select"
                  value={bulkDirection}
                  onChange={(event) =>
                    setBulkDirection(
                      event.target.value === "lower" ? "lower" : "raise",
                    )
                  }
                  data-testid="customer-pricing-bulk-raise-direction"
                  disabled={bulkBusy}
                >
                  <option value="raise">
                    {t("customer_pricing.bulk_raise_direction_raise")}
                  </option>
                  <option value="lower">
                    {t("customer_pricing.bulk_raise_direction_lower")}
                  </option>
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="bulk-raise-mode">
                  {t("customer_pricing.bulk_raise_mode_label")}
                </label>
                <select
                  id="bulk-raise-mode"
                  className="field-select"
                  value={bulkMode}
                  onChange={(event) =>
                    setBulkMode(
                      event.target.value === "fixed" ? "fixed" : "percent",
                    )
                  }
                  data-testid="customer-pricing-bulk-raise-mode"
                  disabled={bulkBusy}
                >
                  <option value="percent">
                    {t("customer_pricing.bulk_raise_mode_percent")}
                  </option>
                  <option value="fixed">
                    {t("customer_pricing.bulk_raise_mode_fixed")}
                  </option>
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="bulk-raise-amount">
                  {t("customer_pricing.bulk_raise_amount_label")}
                </label>
                <input
                  id="bulk-raise-amount"
                  className="field-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={bulkAmount}
                  onChange={(event) => setBulkAmount(event.target.value)}
                  data-testid="customer-pricing-bulk-raise-amount"
                  disabled={bulkBusy}
                />
                <div className="muted small" style={{ marginTop: 4 }}>
                  {bulkMode === "percent"
                    ? t("customer_pricing.bulk_raise_amount_percent_hint")
                    : t("customer_pricing.bulk_raise_amount_fixed_hint")}
                </div>
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="bulk-raise-valid-from">
                {t("customer_pricing.bulk_raise_valid_from_label")}
              </label>
              <input
                id="bulk-raise-valid-from"
                className="field-input"
                type="date"
                value={bulkValidFrom}
                onChange={(event) => setBulkValidFrom(event.target.value)}
                data-testid="customer-pricing-bulk-raise-valid-from"
                disabled={bulkBusy}
              />
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
                data-testid="customer-pricing-bulk-raise-cancel"
              >
                {t("customer_pricing.cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleBulkRaise}
                disabled={bulkBusy || activePrices.length === 0}
                data-testid="customer-pricing-bulk-raise-apply"
              >
                {bulkBusy
                  ? t("admin_form.saving")
                  : t("customer_pricing.bulk_raise_apply")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sprint 8B — copy-from-default modal. Seeds contract prices from
          the provider catalog defaults for the selected ACTIVE services.
          Mirrors the bulk-raise modal shell. */}
      {copyOpen && (
        <div
          data-testid="customer-pricing-copy-default-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("customer_pricing.copy_from_default_title")}
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
              maxWidth: 600,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {t("customer_pricing.copy_from_default_title")}
            </h3>

            <p className="muted" style={{ marginTop: 0, marginBottom: 16 }}>
              {t("customer_pricing.copy_from_default_intro")}
            </p>

            {copyError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-pricing-copy-default-error"
              >
                {copyError}
              </div>
            )}

            {copyResult && (
              <div
                className="alert-info"
                role="status"
                style={{ marginBottom: 12 }}
                data-testid="customer-pricing-copy-default-result"
              >
                {t("customer_pricing.copy_from_default_result", {
                  created: copyResult.created_count,
                  skipped: copyResult.skipped_count,
                })}
              </div>
            )}

            {activeServices.length === 0 ? (
              <div className="muted" style={{ marginBottom: 16 }}>
                {t("customer_pricing.copy_from_default_empty")}
              </div>
            ) : (
              <>
                <div className="field">
                  <label
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <input
                      type="checkbox"
                      data-testid="customer-pricing-copy-default-select-all"
                      checked={
                        copySelectedServiceIds.length === activeServices.length
                      }
                      onChange={(event) => toggleCopyAll(event.target.checked)}
                      disabled={copyBusy}
                    />
                    <span>
                      {t("customer_pricing.copy_from_default_select_all")}
                    </span>
                  </label>
                </div>

                <div
                  style={{
                    border: "1px solid var(--border, #e5e7eb)",
                    borderRadius: 8,
                    padding: "8px 12px",
                    marginBottom: 16,
                    maxHeight: 220,
                    overflowY: "auto",
                  }}
                >
                  {activeServices.map((service) => (
                    <label
                      key={service.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "4px 0",
                      }}
                    >
                      <input
                        type="checkbox"
                        data-testid="customer-pricing-copy-default-row"
                        data-service-id={service.id}
                        checked={copySelectedServiceIds.includes(service.id)}
                        onChange={(event) =>
                          toggleCopyService(service.id, event.target.checked)
                        }
                        disabled={copyBusy}
                      />
                      <span>
                        {service.name} — {service.default_unit_price}
                      </span>
                    </label>
                  ))}
                </div>
              </>
            )}

            <div className="form-2col">
              <div className="field">
                <label
                  className="field-label"
                  htmlFor="copy-default-valid-from"
                >
                  {t("customer_pricing.copy_from_default_valid_from_label")}
                </label>
                <input
                  id="copy-default-valid-from"
                  className="field-input"
                  type="date"
                  value={copyValidFrom}
                  onChange={(event) => setCopyValidFrom(event.target.value)}
                  data-testid="customer-pricing-copy-default-valid-from"
                  disabled={copyBusy}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="copy-default-valid-to">
                  {t("customer_pricing.copy_from_default_valid_to_label")}
                </label>
                <input
                  id="copy-default-valid-to"
                  className="field-input"
                  type="date"
                  value={copyValidTo}
                  onChange={(event) => setCopyValidTo(event.target.value)}
                  data-testid="customer-pricing-copy-default-valid-to"
                  disabled={copyBusy}
                />
                <div className="muted small" style={{ marginTop: 4 }}>
                  {t("customer_pricing.field_valid_to_hint")}
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
                onClick={closeCopyDefault}
                disabled={copyBusy}
                data-testid="customer-pricing-copy-default-cancel"
              >
                {t("customer_pricing.cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleCopyDefault}
                disabled={copyBusy || activeServices.length === 0}
                data-testid="customer-pricing-copy-default-apply"
              >
                {copyBusy
                  ? t("admin_form.saving")
                  : t("customer_pricing.copy_from_default_apply")}
              </button>
            </div>
          </div>
        </div>
      )}


      {/* RF-2 — one dialog for both kinds; the copy follows the target
          because the two deletes differ (a custom line is archived). */}
      <ConfirmDialog
        ref={deleteDialogRef}
        title={
          deleteTarget?.kind === "custom"
            ? t("customer_custom_pricing.delete_confirm_title")
            : t("customer_pricing.delete_confirm_title")
        }
        body={
          deleteTarget?.kind === "custom"
            ? t("customer_custom_pricing.delete_confirm_body")
            : t("customer_pricing.delete_confirm_body")
        }
        confirmLabel={t("customer_pricing.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
        busy={deleteBusy}
        destructive
      />
    </div>
  );
}
