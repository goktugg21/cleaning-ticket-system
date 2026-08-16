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
  createCustomerPriceFolder,
  deleteCustomerCustomPrice,
  deleteCustomerPrice,
  deleteCustomerPriceFolder,
  getCustomer,
  listCustomerCustomPrices,
  listCustomerPriceFolders,
  listCustomerPrices,
  listServiceCategories,
  updateCustomerPriceFolder,
  listServices,
  updateCustomerCustomPrice,
  updateCustomerPrice,
} from "../../api/admin";
import type {
  CustomerAdmin,
  CustomerCustomPrice,
  CustomerCustomPriceCreatePayload,
  CustomerPriceCopyFromDefaultResult,
  CustomerPriceFolder,
  CustomerServicePrice,
  CustomerServicePriceCreatePayload,
  Service,
  ServiceCategory,
  ServiceUnitType,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { ManagedUnitPicker } from "../../components/ManagedUnitPicker";
import { CategoryGroupedPicker } from "../../components/CategoryGroupedPicker";
import { buildPickerGroups } from "../../lib/pickerGroups";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { useToast } from "../../components/ToastProvider";
import { previewAdjustedPrice } from "../../utils/bulkAdjust";
import { Toggle } from "../../components/Toggle";

/**
 * Sprint 28 Batch 5 — Per-customer contract pricing.
 *
 * Customer-scoped sidebar entry. The page lists every
 * `CustomerServicePrice` row for the URL's customer, grouped by
 * service for readability. View-first per
 * `docs/product/requirements-meeting-2026-05-15.md` §3:
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
  managed_unit: number | null;
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

/**
 * Sprint 137 item 4 — the bucket a pricing row is filed under in the
 * category view. A number is a real `ServiceCategory.id`; the two
 * string sentinels are synthetic buckets that exist so NO row can ever
 * be hidden by the drill-down:
 *
 *   "CUSTOM"  — `CustomerCustomPrice` rows. They have no `service` FK
 *               and therefore no category at all (see the model
 *               docstring); they still have to live somewhere.
 *   "UNKNOWN" — a contract row whose `service` is missing from the
 *               catalog map. Should not happen, but a row that silently
 *               vanished from every bucket is exactly the class of bug
 *               this sprint exists to kill, so it gets a visible home
 *               rather than a filter that drops it.
 *   "NO_FOLDER" — Sprint 143: a contract row that is in no folder.
 *               Folderless is LEGAL and permanent (every pre-143 row is
 *               one, and "delete the folder, keep the prices" makes
 *               more), so it is a first-class bucket, not an error case.
 *
 * A number is a `CustomerPriceFolder.id` since Sprint 143 — it was a
 * `ServiceCategory.id` before. The page is folder-first now: folders
 * belong to the CUSTOMER, catalog categories belong to the provider,
 * and it is the customer's own arrangement this page exists to show.
 */
type CategoryKey = number | "CUSTOM" | "UNKNOWN" | "NO_FOLDER";

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
    managed_unit: null,
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
  // Sprint 139 §2 — success toasts auto-dismiss; the failure list stays.
  const { push: pushToast } = useToast();
  const numericId = useMemo(() => {
    if (!id) return null;
    const n = Number(id);
    return Number.isFinite(n) ? n : null;
  }, [id]);

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [prices, setPrices] = useState<CustomerServicePrice[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  // Sprint 137 item 4 — the provider's real ServiceCategory catalog.
  // Loaded in FULL (not filtered to active) so a category that still
  // holds priced rows keeps rendering after it is deactivated, and so
  // an EMPTY category still shows up: the operator has to be able to
  // see that a category exists before pricing anything into it.
  const [categories, setCategories] = useState<ServiceCategory[]>([]);
  // Sprint 143 §3 — the customer's own folders. `categories` stays: the
  // "copy a company category with its services" flow picks from it.
  const [folders, setFolders] = useState<CustomerPriceFolder[]>([]);
  // null = the category-list (index) view; otherwise the drilled-into
  // bucket. The drill-down is a pure view concern — it never filters
  // what is fetched, so nothing is lost by navigating.
  const [activeCategory, setActiveCategory] = useState<CategoryKey | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  // Sprint 137 item 2 — off by default: a deleted (soft-archived) price
  // must not come back unasked. Flipping it refetches both price lists.
  const [showArchived, setShowArchived] = useState(false);

  // RF-2 — one selection / modal / delete-dialog for both price kinds.
  const [selected, setSelected] = useState<PricingRow | null>(null);

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [form, setForm] = useState<PriceFormState>(buildEmptyForm);
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<PricingRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // Sprint 137 item 7 — iOS-style list edit mode. Outside edit mode the
  // list is byte-identical to before: no checkbox column, no toolbar.
  // The bulk action ARCHIVES (see the delete-dialog copy and §0 of the
  // sprint brief) — DELETE on both pricing endpoints soft-archives, so
  // a button saying "Delete" would be the exact lie item 2 set out to
  // fix.
  // The operator's INTENT to be in edit mode. What the UI actually
  // renders is the derived `editMode` further down — see the note there.
  const [editModeRequested, setEditModeRequested] = useState(false);
  const [bulkSelection, setBulkSelection] = useState<string[]>([]);
  const bulkArchiveDialogRef = useRef<ConfirmDialogHandle>(null);
  const [bulkArchiveBusy, setBulkArchiveBusy] = useState(false);
  // Names of the rows a bulk run could NOT archive. Never cleared by a
  // later success on other rows — a partial run must not read as a
  // clean one.
  const [bulkFailures, setBulkFailures] = useState<string[]>([]);
  const [bulkDoneCount, setBulkDoneCount] = useState<number | null>(null);

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
  // #108 Part D — display-only row filter for the long service list;
  // hidden-but-selected rows stay selected (never changes submission).
  const [bulkFilter, setBulkFilter] = useState("");

  // Sprint 8B — copy-from-default modal state. Seeds contract prices for
  // this customer from the provider catalog defaults (active services
  // only). `copyResult` holds the created/skipped summary after a
  // successful run so the per-service skip outcome stays visible.
  const [copyOpen, setCopyOpen] = useState(false);

  // ---- Sprint 143 §3 — folder CRUD -------------------------------------
  // "New folder" / "Rename" share one modal; `folderEditTarget` null =
  // create.
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderEditTarget, setFolderEditTarget] =
    useState<CustomerPriceFolder | null>(null);
  const [folderName, setFolderName] = useState("");
  const [folderBusy, setFolderBusy] = useState(false);
  const [folderError, setFolderError] = useState("");

  // Delete offers TWO honest actions rather than one ambiguous one:
  // folder-only (rows survive, become folderless) or with-contents (rows
  // ARCHIVED, never destroyed — shipped Extra Work holds a live FK).
  const [folderDeleteTarget, setFolderDeleteTarget] =
    useState<CustomerPriceFolder | null>(null);
  const [folderDeleteBusy, setFolderDeleteBusy] = useState(false);

  // "Copy a company category, with its services" — the second way to
  // create a folder. Picks ONE category, then services from it (at least
  // one required); the folder name defaults to the category's and is
  // editable before confirming.
  const [fromCategoryOpen, setFromCategoryOpen] = useState(false);
  const [fromCategoryId, setFromCategoryId] = useState<number | "">("");
  const [fromCategoryName, setFromCategoryName] = useState("");
  const [fromCategoryServiceIds, setFromCategoryServiceIds] = useState<
    number[]
  >([]);
  const [fromCategoryBusy, setFromCategoryBusy] = useState(false);
  const [fromCategoryError, setFromCategoryError] = useState("");

  // Bulk "move to folder", the mechanism that fills and empties folders.
  const [moveFolderOpen, setMoveFolderOpen] = useState(false);
  const [moveFolderTarget, setMoveFolderTarget] = useState<number | "">("");
  const [moveFolderBusy, setMoveFolderBusy] = useState(false);
  const [moveFolderError, setMoveFolderError] = useState("");
  const [copySelectedServiceIds, setCopySelectedServiceIds] = useState<
    number[]
  >([]);
  const [copyValidFrom, setCopyValidFrom] = useState(todayISO);
  const [copyValidTo, setCopyValidTo] = useState("");
  const [copyFilter, setCopyFilter] = useState("");
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
        const [
          customerData,
          pricesData,
          servicesData,
          customPricesData,
          categoriesData,
          foldersData,
        ] = await Promise.all([
            getCustomer(customerId),
            // Sprint 137 item 2 — archived rows are hidden unless the
            // operator asks for them. DELETE soft-archives, and showing
            // archived rows by default made a deleted price reappear
            // greyed-out on the next load (and made one copy-from-default
            // run look like it had copied everything twice).
            listCustomerPrices(customerId, { includeArchived: showArchived }),
            // Full catalog (active + inactive). The Default-price column must
            // resolve for pricing rows whose service was later archived, so
            // serviceById is built from every service; the dropdown + create
            // defaults filter down to active-only (see activeServices).
            listServices(),
            // M5 A — custom (non-catalog) price lines for this customer.
            listCustomerCustomPrices(customerId, {
              includeArchived: showArchived,
            }),
            // Sprint 137 item 4 — every category, including the ones
            // with no priced rows yet (see the `categories` state).
            listServiceCategories(),
            // Sprint 143 §3 — the customer's own folders.
            listCustomerPriceFolders(customerId),
          ]);
        if (cancelled.current) return;
        setCustomer(customerData);
        setPrices(pricesData);
        setServices(servicesData);
        setCustomPrices(customPricesData);
        // Sprint 142 — narrow to THIS customer's provider company.
        // Categories gained a `company` FK this sprint, and "every
        // category" (Sprint 137 item 4) was the right call only while
        // they were global: for a SUPER_ADMIN on a multi-company tenant
        // it would now put ANOTHER provider's category headings on this
        // customer's pricing page, none of which can ever hold a row
        // that is priceable here. Filtered client-side rather than by a
        // `?company=` param because the customer's company is only known
        // once `getCustomer` resolves, and these six calls are
        // deliberately parallel — a serial round-trip to save a
        // one-line filter is the wrong trade.
        setCategories(
          categoriesData.filter((c) => c.company === customerData.company),
        );
        setFolders(foldersData);
        // Sprint 142 (#127 review carry-over) — clear a stale banner on
        // a successful (re)load. See `ServicesAdminPage`'s load effect.
        setLoadError("");
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
  }, [numericId, t, showArchived]);

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
        managed_unit: price.managed_unit,
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
    // Sprint 143 §3 — the folder a NEW row lands in: the one the
    // operator is currently inside, or none when they are on the index
    // or in a sentinel bucket (folderless / custom / unknown), where
    // "no folder" is the honest answer.
    const creatingInFolderId =
      typeof activeCategory === "number" ? activeCategory : null;
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
          managed_unit: form.unit_type === "OTHER" ? form.managed_unit : null,
        };
        if (mode === "create") {
          // Sprint 143 §3 — adding from INSIDE a folder files the new
          // row there. That is the "add a customer-only line to a
          // folder" flow: the operator drilled into the folder, so the
          // folder is what they meant.
          await createCustomerCustomPrice(numericId, {
            ...payload,
            folder: creatingInFolderId,
          });
          await refreshPricingRows(numericId);
          closeFormModal();
        } else if (mode === "edit" && selected?.kind === "custom") {
          const updated = await updateCustomerCustomPrice(
            numericId,
            selected.row.id,
            payload,
          );
          await refreshPricingRows(numericId);
          setSelected({ kind: "custom", row: updated });
          closeFormModal();
        }
      } else {
        const payload: CustomerServicePriceCreatePayload = {
          ...shared,
          service: Number(form.service),
        };
        if (mode === "create") {
          await createCustomerPrice(numericId, {
            ...payload,
            folder: creatingInFolderId,
          });
          await refreshPricingRows(numericId);
          closeFormModal();
        } else if (mode === "edit" && selected?.kind === "contract") {
          const updated = await updateCustomerPrice(
            numericId,
            selected.row.id,
            payload,
          );
          await refreshPricingRows(numericId);
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

  /**
   * Sprint 140 §4 — re-read BOTH price lists after any mutation,
   * honouring the archived toggle. The load effect already passed
   * `{ includeArchived: showArchived }`; every post-mutation path did
   * not, so the toggle silently lost its effect the moment the operator
   * did anything.
   *
   * The bug ran in both directions, which is why local merging was
   * abandoned here too rather than patched:
   *   - with the toggle OFF, creating or editing a row to INACTIVE
   *     inserted/kept a row that should not be listed (the form has its
   *     own Active toggle);
   *   - with the toggle ON, deleting or bulk-archiving a row REMOVED it
   *     from view, even though an archived row is exactly what that
   *     toggle exists to show.
   */
  async function refreshPricingRows(customerId: number) {
    // Sprint 141 §1/§2 — NEVER THROWS. Same contract as the catalog
    // helpers, and it matters MOST here.
    //
    // `CustomerServicePrice` and `CustomerCustomPrice` carry no
    // uniqueness constraint — only lookup indexes — because multiple
    // active rows per (customer, service) are legal by design and
    // `resolve_price` disambiguates by `valid_from` (latest wins).
    // So if a failed RE-READ were reported as a failed WRITE, the
    // operator's natural retry would submit the same price again and
    // the backend would accept it: a real duplicate active price row,
    // silently created by an error message that was wrong. Swallowing
    // the re-read failure here is what makes that impossible.
    try {
      const [pricesData, customPricesData, foldersData] = await Promise.all([
        listCustomerPrices(customerId, { includeArchived: showArchived }),
        listCustomerCustomPrices(customerId, {
          includeArchived: showArchived,
        }),
        // Sprint 143 §3 — folders move with the rows: a create, a
        // delete, or a bulk move changes a folder's `price_count`, which
        // is what every index card shows.
        listCustomerPriceFolders(customerId),
      ]);
      setPrices(pricesData);
      setCustomPrices(customPricesData);
      setFolders(foldersData);
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
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
      } else {
        await deleteCustomerPrice(numericId, targetId);
      }
      // DELETE archives rather than destroys, so with "Show archived"
      // on the row must REMAIN listed (greyed) instead of vanishing.
      await refreshPricingRows(numericId);
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

  // ---- Sprint 137 item 7 — bulk archive (list edit mode) ------------
  // Rows come from two endpoints, so the selection is keyed by
  // kind+id — the same composite the table already uses as its React
  // key. A bare id would collide between a contract row and a custom
  // row that happen to share one.
  function rowKey(entry: PricingRow): string {
    return `${entry.kind}-${entry.row.id}`;
  }

  /**
   * Sprint 138 §3 — an ARCHIVED price row is a read-only audit record,
   * not a manageable catalog row.
   *
   * Before this, "Show archived" plus edit mode let the operator select
   * an already-archived price and archive it AGAIN: the backend
   * returned 204 (it was already `is_active=false`), the row vanished
   * from the list, and it was back on the next load — a success
   * reported for something that never happened.
   *
   * Fixed BY CONSTRUCTION rather than by reporting: these rows carry no
   * checkbox and are not selectable, so the second archive cannot be
   * requested at all. There is deliberately no restore flow and no
   * permanent delete for prices — archived prices stay archived,
   * because `ExtraWorkRequestItem.snapshot_customer_service_price` is a
   * live FK into them.
   *
   * PRICES ONLY. Archived CATEGORIES and SERVICES are catalog rows, not
   * audit records, and keep their actions (see ServicesAdminPage).
   */
  function isArchivedRow(entry: PricingRow): boolean {
    return !entry.row.is_active;
  }

  function exitEditMode() {
    setEditModeRequested(false);
    setBulkSelection([]);
  }

  function toggleBulkRowSelection(key: string, checked: boolean) {
    setBulkSelection((prev) =>
      checked ? [...prev, key] : prev.filter((k) => k !== key),
    );
  }

  function openBulkArchive() {
    setBulkFailures([]);
    setBulkDoneCount(null);
    bulkArchiveDialogRef.current?.open();
  }

  /**
   * Archive every selected row. There is no bulk endpoint, so this is
   * N sequential DELETEs from the client — acceptable at the sizes this
   * page sees (a category's prices), and recorded as a `## NEXT` item
   * in the sprint checklist because a customer with hundreds of priced
   * rows would want a real bulk endpoint.
   *
   * Sequential rather than parallel on purpose: each DELETE writes an
   * AuditLog row, and a burst of parallel writes buys nothing here.
   *
   * Partial failure is reported per row and never rounded up to
   * success: the rows that DID archive leave the list, the ones that
   * did not are named and stay.
   */
  async function handleConfirmBulkArchive() {
    if (numericId === null) return;
    setBulkArchiveBusy(true);
    // Sprint 142 (#127 review carry-over) — `selectableRows`, and the
    // pruned `activeBulkSelection`: an archived row must never be a
    // bulk-archive target (Sprint 138 §3), and a stale key must not
    // resurrect one. See the note beside `activeBulkSelection`.
    const targets = selectableRows.filter((entry) =>
      activeBulkSelection.includes(rowKey(entry)),
    );
    const failed: string[] = [];
    const archivedContractIds: number[] = [];
    const archivedCustomIds: number[] = [];

    for (const entry of targets) {
      try {
        if (entry.kind === "custom") {
          await deleteCustomerCustomPrice(numericId, entry.row.id);
          archivedCustomIds.push(entry.row.id);
        } else {
          await deleteCustomerPrice(numericId, entry.row.id);
          archivedContractIds.push(entry.row.id);
        }
      } catch {
        failed.push(resolveRowName(entry));
      }
    }

    if (archivedContractIds.length > 0 || archivedCustomIds.length > 0) {
      // Same rule as the single delete: archived rows stay listed while
      // the toggle is on.
      await refreshPricingRows(numericId);
    }
    // Keep only the rows that failed selected, so a retry acts on
    // exactly what is left rather than on rows already archived.
    setBulkSelection(
      targets
        .filter((entry) => failed.includes(resolveRowName(entry)))
        .map(rowKey),
    );
    setSelected(null);
    const archivedCount =
      archivedContractIds.length + archivedCustomIds.length;
    setBulkFailures(failed);
    setBulkDoneCount(archivedCount);
    setBulkArchiveBusy(false);
    bulkArchiveDialogRef.current?.close();
    if (failed.length === 0 && archivedCount > 0) {
      pushToast({
        variant: "success",
        title: t("customer_pricing.bulk_archive_done", {
          count: archivedCount,
        }),
      });
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
    setBulkFilter("");
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
      // Re-fetch so the new validity-window rows surface (existing rows
      // stay — history preserved server-side). Sprint 140 §4: through
      // the helper, so the archived toggle survives the adjust.
      await refreshPricingRows(numericId);
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
    setCopyFilter("");
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

  /**
   * Sprint 138 §5 / Sprint 139 §3 — select or clear an ENTIRE category
   * in one action.
   *
   * Acts on the group's FULL item list, not on what the text filter
   * currently shows. The filter is display-only on every multi-select
   * list here — "hidden-but-selected rows stay selected" — and the
   * owner's ask was to select a whole category at once, which a
   * filter-narrowed select-all would quietly fail to do.
   */
  function toggleCopySelection(items: Service[], checked: boolean) {
    const ids = items.map((s) => s.id);
    setCopySelectedServiceIds((prev) =>
      checked
        ? [...new Set([...prev, ...ids])]
        : prev.filter((id) => !ids.includes(id)),
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
      // Refresh so the seeded rows surface; keep the modal open so the
      // created/skipped summary stays visible. Sprint 140 §4: through
      // the helper, so the archived toggle survives the copy.
      // Set the summary BEFORE the re-read (Sprint 141 §2): the
      // created/skipped counts are what this modal exists to show, and
      // they must not be discarded because a list refresh failed.
      setCopyResult(result);
      await refreshPricingRows(numericId);
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
  // Sprint 187 §6b — active AND belonging to THIS customer's provider
  // company.
  //
  // Sprint 142 narrowed the CATEGORY list to the customer's company for
  // exactly this reason (see the load effect above) and stopped there,
  // so the "add a price" dropdown beneath those headings still offered
  // every company's services to a SUPER_ADMIN. Choosing one was then
  // refused server-side with "Service belongs to a different provider
  // company than the customer" — a dropdown offering options the save
  // will reject.
  //
  // Narrowed client-side, not by `?company=`, for the reason the
  // category filter states: the customer's company is only known once
  // `getCustomer` resolves, and these six calls are deliberately
  // parallel. `services` itself deliberately keeps the FULL catalog so
  // the Default-price column still resolves for an archived service.
  const activeServices = services.filter(
    (s) => s.is_active && (!customer || s.company === customer.company),
  );

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

  // Sprint 143 §3 — the folder ids that actually HAVE an index card.
  // Same `knownIds` guard Sprint 142.1 introduced for categories, kept
  // because the rule it enforces has now bitten twice: NO PRICED ROW MAY
  // BE UNREACHABLE FROM THE INDEX. A row pointing at a folder the page
  // did not load falls back to a sentinel rather than into a numeric
  // bucket with no card.
  const knownFolderIds = new Set(folders.map((f) => f.id));

  /**
   * Sprint 143 §3 — which bucket a row is filed under. FOLDER FIRST:
   * the page groups by the customer's own folders, not by the provider's
   * catalog categories (a category is shared across the company's
   * customers; a folder is this customer's arrangement of what was
   * agreed with them).
   *
   * Precedence, and every branch lands on a key that has a card:
   *   1. its folder, when set AND loaded (`knownFolderIds`);
   *   2. "CUSTOM"    — a folderless customer-only line;
   *   3. "UNKNOWN"   — a contract row whose service is missing from the
   *                    catalog map;
   *   4. "NO_FOLDER" — a folderless contract row. The common case for
   *                    every pre-143 row.
   *
   * The `knownFolderIds` guard is Sprint 142.1's, kept deliberately: the
   * "row in a numeric bucket with no card" failure has now happened
   * twice, and it does not degrade — the row vanishes from the index and
   * from every count.
   */
  function categoryKeyOf(entry: PricingRow): CategoryKey {
    const folderId = entry.row.folder;
    if (folderId !== null && knownFolderIds.has(folderId)) return folderId;
    if (entry.kind === "custom") return "CUSTOM";
    if (serviceById.get(entry.row.service) === undefined) return "UNKNOWN";
    return "NO_FOLDER";
  }

  // Bucket EVERY row by category. Derived from `unifiedRows`, so the
  // index and the drill-down can never disagree about what exists: the
  // drill-down renders a slice of the same list, never a second fetch.
  const rowsByCategory = new Map<CategoryKey, PricingRow[]>();
  for (const entry of unifiedRows) {
    const key = categoryKeyOf(entry);
    const bucket = rowsByCategory.get(key);
    if (bucket) {
      bucket.push(entry);
    } else {
      rowsByCategory.set(key, [entry]);
    }
  }

  // The index cards: every FOLDER (including the empty ones — an
  // operator who just created one has to see it exists before filing
  // anything into it), then the three synthetic buckets, which appear
  // only when they actually hold rows.
  const bucketCount = (key: CategoryKey) =>
    (rowsByCategory.get(key) ?? []).length;
  const categoryCards: {
    key: CategoryKey;
    label: string;
    count: number;
    isActive: boolean;
  }[] = [
    ...folders.map((folder) => ({
      key: folder.id as CategoryKey,
      label: folder.name,
      count: bucketCount(folder.id),
      isActive: folder.is_active,
    })),
    ...(bucketCount("NO_FOLDER") > 0
      ? [
          {
            key: "NO_FOLDER" as CategoryKey,
            label: t("customer_pricing.folder_none"),
            count: bucketCount("NO_FOLDER"),
            isActive: true,
          },
        ]
      : []),
    ...(bucketCount("CUSTOM") > 0
      ? [
          {
            key: "CUSTOM" as CategoryKey,
            label: t("customer_pricing.category_custom"),
            count: bucketCount("CUSTOM"),
            isActive: true,
          },
        ]
      : []),
    ...(bucketCount("UNKNOWN") > 0
      ? [
          {
            key: "UNKNOWN" as CategoryKey,
            label: t("customer_pricing.category_unknown"),
            count: bucketCount("UNKNOWN"),
            isActive: true,
          },
        ]
      : []),
  ];

  // The folder the drill-down is currently inside, or null for a
  // sentinel bucket (which has no folder to rename or delete).
  const activeFolder =
    typeof activeCategory === "number"
      ? (folders.find((f) => f.id === activeCategory) ?? null)
      : null;

  // Rows shown by the drill-down. An `activeCategory` whose bucket
  // emptied out (e.g. the archived rows were just hidden again)
  // degrades to an empty category page with a working breadcrumb
  // rather than a crash or a silent bounce back to the index.
  const visibleRows =
    activeCategory === null ? [] : (rowsByCategory.get(activeCategory) ?? []);

  // Sprint 138 §3 — the rows edit mode may act on. Archived price rows
  // are read-only records, so they are excluded from selection entirely
  // rather than selected-then-skipped.
  const selectableRows = visibleRows.filter((entry) => !isArchivedRow(entry));

  // Sprint 142 (#127 review carry-over) — edit mode is only MEANINGFUL
  // while there is at least one selectable row, so what the UI renders
  // is DERIVED from the row set rather than read straight off the
  // operator's `editModeRequested` intent.
  //
  // The reported case: in a category where every row is archived,
  // `visibleRows` is non-empty but `selectableRows` is empty. The Edit
  // button was gated on `visibleRows.length === 0`, so it was enabled,
  // edit mode opened, and the operator got "0 of 0 selected" above a
  // dead "Archive selected" — archived rows carry no checkbox by
  // construction (Sprint 138 §3). The same state is reachable from the
  // other direction: archive the category's last active row WHILE in
  // edit mode, and the toolbar is left hanging over nothing.
  //
  // Deriving closes both at once and needs no effect — a resync effect
  // here would be a synchronous setState in an effect body, which this
  // codebase forbids (CLAUDE.md, and `react-hooks/set-state-in-effect`
  // is already at its ESLint baseline).
  const editMode = editModeRequested && selectableRows.length > 0;

  // ...and the SELECTION is derived the same way, for the same reason.
  // `bulkSelection` is raw state that nothing prunes, so a key can
  // outlive its row's selectability: select the only active row, archive
  // it (edit mode collapses, the key remains), then add a new price to
  // the category — edit mode resumes with a stale selection pointing at
  // an ARCHIVED row, and "Archive selected" would re-archive it for a
  // 204 and a phantom success. That is precisely the defect Sprint 138
  // §3 removed. Every count and the bulk handler read THIS, not the raw
  // array.
  const selectableKeys = new Set(selectableRows.map(rowKey));
  const activeBulkSelection = bulkSelection.filter((key) =>
    selectableKeys.has(key),
  );

  // Sprint 138 §5 — the copy-from-defaults picker, grouped by real
  // ServiceCategory. `services` holds every catalog row and `visible`
  // is only what the text filter currently shows: the per-category
  // select-all acts on the former, the rendered checkboxes on the
  // latter. Categories with no active services at all are dropped —
  // unlike the pricing INDEX (item 4), an empty group here would be a
  // dead end, since there is nothing in it to copy.
  // Sprint 139 §3 — the price bulk-adjust picker, grouped by the
  // category of the SERVICE each contract price points at. A price row
  // whose service is missing from the catalog map still gets a group.
  const bulkFilterTerm = bulkFilter.trim().toLowerCase();
  const bulkPriceGroups = buildPickerGroups<CustomerServicePrice>({
    rows: activePrices,
    categories,
    categoryOf: (price) => serviceById.get(price.service)?.category ?? null,
    matchesFilter: (price) =>
      !bulkFilterTerm ||
      resolveServiceName(price).toLowerCase().includes(bulkFilterTerm),
    fallbackName: t("customer_pricing.category_unknown"),
  });

  const copyFilterTerm = copyFilter.trim().toLowerCase();
  // Sprint 139 §3 — through the shared builder, so an active service
  // whose category is missing still gets a home instead of vanishing.
  const copyGroups = buildPickerGroups<Service>({
    rows: activeServices,
    categories,
    categoryOf: (service) => service.category,
    matchesFilter: (service) =>
      !copyFilterTerm || service.name.toLowerCase().includes(copyFilterTerm),
    fallbackName: t("customer_pricing.category_unknown"),
  });

  const activeCategoryLabel =
    activeCategory === null
      ? ""
      : (categoryCards.find((card) => card.key === activeCategory)?.label ??
        (typeof activeCategory === "number"
          ? (folders.find((f) => f.id === activeCategory)?.name ?? "")
          : ""));

  // Navigating between the index and a category clears the row detail
  // panel — a selected row from another category must not linger under
  // a list it is not part of.
  // Sprint 137 item 7 — navigating also leaves edit mode: a selection
  // made in one category must never be carried into another (or acted
  // on from the index, where those rows are not even on screen).
  function openCategory(key: CategoryKey) {
    setActiveCategory(key);
    setSelected(null);
    exitEditMode();
    setBulkFailures([]);
    setBulkDoneCount(null);
  }

  function backToCategories() {
    setActiveCategory(null);
    setSelected(null);
    exitEditMode();
    setBulkFailures([]);
    setBulkDoneCount(null);
  }

  // ---- Sprint 143 §3 — folder handlers ----------------------------------
  function openCreateFolder() {
    setFolderEditTarget(null);
    setFolderName("");
    setFolderError("");
    setFolderModalOpen(true);
  }

  function openRenameFolder(folder: CustomerPriceFolder) {
    setFolderEditTarget(folder);
    setFolderName(folder.name);
    setFolderError("");
    setFolderModalOpen(true);
  }

  /**
   * Create an empty folder, or rename an existing one. A rename touches
   * ONLY this customer's label — a folder copied from a company category
   * keeps no link back to it, so renaming can never reach the catalog.
   */
  async function submitFolder(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    const trimmed = folderName.trim();
    if (!trimmed) {
      setFolderError(t("customer_pricing.folder_error_name_required"));
      return;
    }
    setFolderBusy(true);
    setFolderError("");
    try {
      if (folderEditTarget) {
        await updateCustomerPriceFolder(numericId, folderEditTarget.id, {
          name: trimmed,
        });
      } else {
        await createCustomerPriceFolder(numericId, { name: trimmed });
      }
      // Non-throwing by contract (Sprint 141), so a failed re-read can
      // never report this committed write as a form error.
      await refreshPricingRows(numericId);
      setFolderModalOpen(false);
    } catch (err) {
      setFolderError(getApiError(err));
    } finally {
      setFolderBusy(false);
    }
  }

  async function confirmDeleteFolder(withContents: boolean) {
    if (numericId === null || !folderDeleteTarget) return;
    setFolderDeleteBusy(true);
    try {
      const result = await deleteCustomerPriceFolder(
        numericId,
        folderDeleteTarget.id,
        withContents,
      );
      // Leave the drill-down: the folder it was showing is gone.
      setActiveCategory(null);
      setSelected(null);
      exitEditMode();
      setFolderDeleteTarget(null);
      pushToast({
        variant: "success",
        title: withContents
          ? t("customer_pricing.folder_deleted_with_contents", {
              count: result.archived_price_count,
            })
          : t("customer_pricing.folder_deleted_only"),
      });
      await refreshPricingRows(numericId);
    } catch (err) {
      setLoadError(getApiError(err));
      setFolderDeleteTarget(null);
    } finally {
      setFolderDeleteBusy(false);
    }
  }

  // Services offered by the "copy a company category" modal: the chosen
  // category's ACTIVE rows only. An archived service must never be
  // seeded into a new agreed-price folder.
  const fromCategoryServices =
    fromCategoryId === ""
      ? []
      : services.filter(
          (svc) => svc.category === fromCategoryId && svc.is_active,
        );

  function openFromCategory() {
    setFromCategoryId("");
    setFromCategoryName("");
    setFromCategoryServiceIds([]);
    setFromCategoryError("");
    setFromCategoryOpen(true);
  }

  function pickFromCategory(rawId: string) {
    const id = rawId === "" ? "" : Number(rawId);
    setFromCategoryId(id);
    // Default the folder name to the category's, still editable. Select
    // every active service by default — the operator is copying a
    // category, so "all of it" is the expected starting point.
    const category = categories.find((c) => c.id === id);
    setFromCategoryName(category ? category.name : "");
    setFromCategoryServiceIds(
      id === ""
        ? []
        : services
            .filter((svc) => svc.category === id && svc.is_active)
            .map((svc) => svc.id),
    );
  }

  /**
   * Create a folder AND seed it with `CustomerServicePrice` rows copied
   * from the chosen catalog services' default prices.
   *
   * ONE request: `copy-from-default` takes `folder_name` and creates the
   * folder inside the same transaction as the rows, so a failed copy
   * cannot strand an empty folder nobody asked for. It also reuses that
   * endpoint's existing per-service skip/overlap rules verbatim rather
   * than re-implementing them, and returns the same "X copied, Y
   * skipped" summary this page already renders.
   *
   * The rows it creates ARE this customer's agreed prices — that is what
   * a `CustomerServicePrice` row IS to `resolve_price`; nothing extra is
   * needed to make it true, only care not to break it.
   */
  async function submitFromCategory(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    if (fromCategoryId === "") {
      setFromCategoryError(t("customer_pricing.folder_error_category"));
      return;
    }
    if (!fromCategoryName.trim()) {
      setFromCategoryError(t("customer_pricing.folder_error_name_required"));
      return;
    }
    if (fromCategoryServiceIds.length === 0) {
      setFromCategoryError(t("customer_pricing.folder_error_no_services"));
      return;
    }
    setFromCategoryBusy(true);
    setFromCategoryError("");
    try {
      const result = await copyDefaultPricesToCustomer(numericId, {
        services: fromCategoryServiceIds,
        valid_from: todayISO(),
        valid_to: null,
        folder_name: fromCategoryName.trim(),
      });
      setCopyResult(result);
      setFromCategoryOpen(false);
      pushToast({
        variant: "success",
        title: t("customer_pricing.copy_from_default_result", {
          created: result.created_count,
          skipped: result.skipped_count,
        }),
      });
      await refreshPricingRows(numericId);
      // Drill straight into the folder that was just created.
      if (result.folder) setActiveCategory(result.folder.id as CategoryKey);
    } catch (err) {
      setFromCategoryError(getApiError(err));
    } finally {
      setFromCategoryBusy(false);
    }
  }

  /**
   * Move every selected row into a folder, or out of all folders
   * ("" = no folder). N sequential PATCHes, like every other bulk action
   * on this page (no bulk endpoint — see `## NEXT`), with per-row
   * failure reporting so a partial run is never reported as clean.
   */
  async function confirmMoveToFolder() {
    if (numericId === null) return;
    setMoveFolderBusy(true);
    setMoveFolderError("");
    const targets = selectableRows.filter((entry) =>
      activeBulkSelection.includes(rowKey(entry)),
    );
    const target =
      moveFolderTarget === "" ? null : Number(moveFolderTarget);
    const failed: string[] = [];
    for (const entry of targets) {
      try {
        if (entry.kind === "custom") {
          await updateCustomerCustomPrice(numericId, entry.row.id, {
            folder: target,
          });
        } else {
          await updateCustomerPrice(numericId, entry.row.id, {
            folder: target,
          });
        }
      } catch {
        failed.push(
          entry.kind === "custom"
            ? entry.row.custom_name
            : entry.row.service_name,
        );
      }
    }
    setBulkFailures(failed);
    setBulkDoneCount(targets.length - failed.length);
    setMoveFolderOpen(false);
    exitEditMode();
    setMoveFolderBusy(false);
    await refreshPricingRows(numericId);
  }

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
            className={
              showArchived ? "btn btn-secondary btn-sm" : "btn btn-ghost btn-sm"
            }
            data-testid="customer-pricing-show-archived-toggle"
            aria-pressed={showArchived}
            onClick={() => setShowArchived((current) => !current)}
            disabled={loading || numericId === null}
          >
            {/* Sprint 138 §4 — the label reflects STATE. It used to
                read "Show archived" whether or not archived rows were
                already showing, so hiding them meant pressing a button
                that said "show". */}
            {showArchived
              ? t("customer_pricing.hide_archived_toggle")
              : t("customer_pricing.show_archived_toggle")}
          </button>
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
          {/* Sprint 137 item 4 — category index. The flat one-table
              page became unreadable at real contract sizes; this
              mirrors the shape of the owner's reference tool: pick a
              category, drill in, breadcrumb back. */}
          {activeCategory === null && (
            <div className="card" data-testid="customer-pricing-categories">
              {/* Sprint 143 §3 — the two ways to create a folder. Always
                  offered, including on a brand-new customer's empty page,
                  which is where they matter most: a new customer opens
                  with no folders and no prices (there is no fallback to
                  company defaults — `resolve_price` has none), so these
                  buttons are the whole starting point. */}
              <div
                className="page-header-actions"
                style={{ padding: "14px 20px 0", justifyContent: "flex-end" }}
              >
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  data-testid="customer-pricing-new-folder"
                  onClick={openCreateFolder}
                >
                  {t("customer_pricing.folder_new_button")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  data-testid="customer-pricing-folder-from-category"
                  onClick={openFromCategory}
                >
                  {t("customer_pricing.folder_from_category_button")}
                </button>
              </div>
              {categoryCards.length === 0 ? (
                <div
                  style={{ padding: "32px 24px", textAlign: "center" }}
                  data-testid="customer-pricing-empty"
                >
                  <h3 className="empty-title" style={{ marginBottom: 8 }}>
                    {t("customer_pricing.empty_title")}
                  </h3>
                  <p className="muted" style={{ margin: 0 }}>
                    {t("customer_pricing.empty_description")}
                  </p>
                </div>
              ) : (
                <div style={{ padding: "18px 20px" }}>
                  <div className="muted small" style={{ marginBottom: 12 }}>
                    {t("customer_pricing.folders_helper")}
                  </div>
                  <div className="pricing-category-grid">
                    {categoryCards.map((card) => (
                      <button
                        type="button"
                        key={String(card.key)}
                        className="pricing-category-card"
                        data-testid="customer-pricing-category-card"
                        data-category-key={String(card.key)}
                        data-category-count={card.count}
                        onClick={() => openCategory(card.key)}
                      >
                        <span className="pricing-category-card-name">
                          {card.label}
                          {!card.isActive && (
                            <span
                              className="badge badge-muted"
                              style={{ marginLeft: 8 }}
                            >
                              {t("admin.status_inactive")}
                            </span>
                          )}
                        </span>
                        {/* Sprint 154 §L.2 — the count is the card's
                            headline figure now, not a muted sub-line. */}
                        <span className="pricing-category-card-count">
                          {card.count}
                        </span>
                        <span className="pricing-category-card-count-label">
                          {card.count === 0
                            ? t("customer_pricing.category_card_empty")
                            : t("customer_pricing.category_card_count", {
                                count: card.count,
                              })}
                        </span>
                      </button>
                    ))}
                    {/* Sprint 154 §L.2 — a large "+" tile at the end of
                        the grid, opening the EXISTING create-folder flow.
                        Styled as a card so the grid reads as one row of
                        tiles rather than a row plus a stray button. */}
                    <button
                      type="button"
                      className="pricing-category-card pricing-category-card-add"
                      data-testid="customer-pricing-category-add-card"
                      onClick={openCreateFolder}
                    >
                      <span
                        className="pricing-category-card-add-plus"
                        aria-hidden="true"
                      >
                        +
                      </span>
                      <span className="pricing-category-card-name">
                        {t("customer_pricing.folder_new_button")}
                      </span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeCategory !== null && (
          <div className="card" data-testid="customer-pricing-list">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "14px 20px",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="customer-pricing-category-back"
                onClick={backToCategories}
              >
                <ChevronLeft size={14} strokeWidth={2.5} />
                {t("customer_pricing.breadcrumb_all")}
              </button>
              <span
                className="section-title"
                style={{ margin: 0 }}
                data-testid="customer-pricing-category-title"
              >
                {activeCategoryLabel}
              </span>
              {/* Sprint 143 §3 — a real folder can be renamed or
                  deleted; the sentinel buckets (folderless / custom /
                  unknown) are not folders and get neither. */}
              {activeFolder && (
                <>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    style={{ marginLeft: "auto" }}
                    data-testid="customer-pricing-folder-rename"
                    onClick={() => openRenameFolder(activeFolder)}
                  >
                    {t("customer_pricing.folder_rename_button")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-pricing-folder-delete"
                    onClick={() => setFolderDeleteTarget(activeFolder)}
                  >
                    {t("customer_pricing.folder_delete_button")}
                  </button>
                </>
              )}
              {/* Sprint 137 item 7 — Edit / Done. Outside edit mode the
                  table below looks exactly as it did before.

                  Sprint 143 §7 — HIDDEN, not disabled, when there is
                  nothing it could act on. Sprint 142 fixed the GATE
                  (`selectableRows`, not `visibleRows` — the latter
                  includes archived rows, which are read-only and carry
                  no checkbox) but left the button on screen greyed out
                  with a tooltip. The running theme of Sprints 138-141 is
                  that a control which cannot work should not be offered
                  at all: a disabled button still asks the operator to
                  hover it to find out why. */}
              {selectableRows.length > 0 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={activeFolder ? undefined : { marginLeft: "auto" }}
                  data-testid="customer-pricing-edit-mode-toggle"
                  aria-pressed={editMode}
                  onClick={() =>
                    editMode ? exitEditMode() : setEditModeRequested(true)
                  }
                >
                  {editMode
                    ? t("customer_pricing.list_edit_done")
                    : t("customer_pricing.list_edit_start")}
                </button>
              )}
            </div>

            {editMode && (
              <>
                <div className="list-edit-bar">
                  <MultiSelectToolbar
                    selectedCount={activeBulkSelection.length}
                    // Sprint 138 §3 — select-all covers ACTIVE rows
                    // only; archived rows are not selectable at all.
                    onSelectAll={() =>
                      setBulkSelection(selectableRows.map(rowKey))
                    }
                    onClearAll={() => setBulkSelection([])}
                    // ...and the count says so, so "select all" picking
                    // fewer rows than are on screen never looks broken.
                    countLabel={t("customer_pricing.bulk_selected_count", {
                      count: activeBulkSelection.length,
                      total: selectableRows.length,
                    })}
                    disabled={bulkArchiveBusy}
                    actions={[
                      // Sprint 143 §3 — the mechanism that fills and
                      // empties folders. "No folder" is a legitimate
                      // target, which is how a row leaves one.
                      {
                        key: "move-folder",
                        label: t("customer_pricing.folder_move_button"),
                        onClick: () => {
                          setMoveFolderTarget("");
                          setMoveFolderError("");
                          setMoveFolderOpen(true);
                        },
                      },
                      {
                        key: "archive",
                        label: t("customer_pricing.bulk_archive_button"),
                        onClick: openBulkArchive,
                        destructive: true,
                      },
                    ]}
                    testIdPrefix="customer-pricing-bulk-archive"
                  />
                </div>
                {/* "Delete" here archives. Say so on the screen that
                    does it, and put the way to SEE the archived rows
                    one click away rather than leaving the operator to
                    wonder where they went. */}
                <div
                  className="muted small"
                  style={{ padding: "8px 20px 0" }}
                  data-testid="customer-pricing-bulk-archive-explainer"
                >
                  {t("customer_pricing.bulk_archive_explainer")}{" "}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-pricing-bulk-archive-show-archived"
                    aria-pressed={showArchived}
                    onClick={() => setShowArchived((current) => !current)}
                  >
                    {showArchived
                      ? t("customer_pricing.hide_archived_toggle")
                      : t("customer_pricing.show_archived_toggle")}
                  </button>
                </div>
              </>
            )}

            {/* Partial-run reporting: name every row that failed and
                never claim a clean run. */}
            {bulkFailures.length > 0 && (
              <div
                className="alert-error"
                role="alert"
                style={{ margin: "12px 20px 0" }}
                data-testid="customer-pricing-bulk-archive-failures"
              >
                {t("customer_pricing.bulk_archive_partial", {
                  done: bulkDoneCount ?? 0,
                  failed: bulkFailures.length,
                })}
                <ul className="list-edit-failure-list">
                  {bulkFailures.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              </div>
            )}
            {/* Sprint 138 §4 — make it visible ON THE LIST that
                archived rows are included, so the extra greyed rows are
                never a mystery. */}
            {showArchived && (
              <div
                className="alert-info"
                role="status"
                style={{ margin: "12px 20px 0" }}
                data-testid="customer-pricing-archived-included-note"
              >
                {t("customer_pricing.archived_included_note", {
                  count: visibleRows.filter(isArchivedRow).length,
                })}
              </div>
            )}

            {visibleRows.length === 0 ? (
              <div
                style={{ padding: "32px 24px", textAlign: "center" }}
                data-testid="customer-pricing-category-empty"
              >
                <p className="muted" style={{ margin: 0 }}>
                  {t("customer_pricing.category_drill_empty")}
                </p>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {editMode && (
                        <th className="list-edit-checkbox-cell">
                          <span className="sr-only">
                            {t("customer_pricing.list_edit_select_column")}
                          </span>
                        </th>
                      )}
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
                    {visibleRows.map((entry) => (
                      <tr
                        key={`${entry.kind}-${entry.row.id}`}
                        data-testid="customer-pricing-row"
                        data-price-id={entry.row.id}
                        data-price-kind={entry.kind}
                        // In edit mode the row click selects rather
                        // than opening the read-only detail panel:
                        // two different meanings for one click would
                        // be worse than either.
                        data-archived={isArchivedRow(entry) ? "true" : "false"}
                        className={
                          isArchivedRow(entry) ? "list-row-archived" : ""
                        }
                        onClick={() => {
                          // An archived row is read-only: selecting it
                          // in edit mode could only ever request an
                          // archive that already happened.
                          if (editMode && isArchivedRow(entry)) return;
                          if (!editMode) {
                            setSelected(entry);
                            return;
                          }
                          toggleBulkRowSelection(
                            rowKey(entry),
                            !bulkSelection.includes(rowKey(entry)),
                          );
                        }}
                      >
                        {editMode && (
                          <td className="list-edit-checkbox-cell">
                            {/* No checkbox at all on an archived row —
                                the re-archive bug cannot be requested,
                                rather than being caught and reported. */}
                            {!isArchivedRow(entry) && (
                              <input
                                type="checkbox"
                                className="checkbox-input"
                                data-testid="customer-pricing-bulk-archive-row"
                                data-price-id={entry.row.id}
                                checked={bulkSelection.includes(rowKey(entry))}
                                onChange={(event) =>
                                  toggleBulkRowSelection(
                                    rowKey(entry),
                                    event.target.checked,
                                  )
                                }
                                onClick={(event) => event.stopPropagation()}
                                disabled={bulkArchiveBusy}
                                aria-label={resolveRowName(entry)}
                              />
                            )}
                          </td>
                        )}
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
                          {/* Quiet badge so read-only reads as
                              deliberate rather than broken. */}
                          {isArchivedRow(entry) && (
                            <span
                              className="badge badge-muted"
                              style={{ marginLeft: 8 }}
                              data-testid="customer-pricing-archived-tag"
                            >
                              {t("customer_pricing.tag_archived")}
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
          )}

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
                {/* Sprint 138 §3 — an archived price row carries NO row
                    actions. It is a record of what was once agreed, kept
                    because shipped Extra Work lines point at it. */}
                {isArchivedRow(selected) ? (
                  <span
                    className="badge badge-muted"
                    data-testid="customer-pricing-detail-archived-tag"
                  >
                    {t("customer_pricing.tag_archived")}
                  </span>
                ) : (
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
                )}
              </div>

              {isArchivedRow(selected) && (
                <div
                  className="muted small"
                  style={{ marginBottom: 12 }}
                  data-testid="customer-pricing-detail-archived-note"
                >
                  {t("customer_pricing.archived_readonly_note")}
                </div>
              )}

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
              className="section-title"
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

                {/* Sprint 123 — "Other" is an opaque unit backed by the
                    per-company managed unit catalog. Unlike ServicesAdminPage,
                    this page already tracks the customer's own provider
                    company (`customer.company`), so the picker can scope
                    both the active-unit list and any inline "add new" unit
                    to that company precisely instead of relying on the
                    backend's implicit CA-default. */}
                {form.unit_type === "OTHER" && (
                  <ManagedUnitPicker
                    key={customer?.company ?? "no-company"}
                    id="price-managed-unit"
                    companyId={customer?.company}
                    managedUnitId={form.managed_unit}
                    customUnitLabel={form.custom_unit_label}
                    onChange={(managedUnitId, label) =>
                      setForm((prev) => ({
                        ...prev,
                        managed_unit: managedUnitId,
                        custom_unit_label: label,
                      }))
                    }
                    disabled={formBusy}
                  />
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
                <Toggle
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
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
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
                {/* #108 Part D — shared multi-select treatment: Select
                    all / Clear all + count + filter, internal scroll. */}
                <MultiSelectToolbar
                  selectedCount={bulkSelectedIds.length}
                  onSelectAll={() => toggleBulkAll(true)}
                  onClearAll={() => toggleBulkAll(false)}
                  disabled={bulkBusy}
                  filterValue={bulkFilter}
                  onFilterChange={setBulkFilter}
                  testIdPrefix="customer-pricing-bulk-raise"
                />
                {/* Sprint 139 §3 — grouped by category, same shape
                    as the copy-from-defaults picker. The price rows
                    take their category from the catalog service they
                    price. */}
                <CategoryGroupedPicker
                  groups={bulkPriceGroups}
                  getId={(price) => price.id}
                  renderItem={(price) => (
                    <>
                      {resolveServiceName(price)} — {price.unit_price}
                      {/* #108 Part C — live effect preview. Backend
                          HALF_UP is authoritative; a result at or below
                          zero shows red (the server rejects the whole
                          batch). */}
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
                    </>
                  )}
                  selectedIds={bulkSelectedIds}
                  onToggleItem={toggleBulkRow}
                  onToggleGroup={(group, checked) =>
                    setBulkSelectedIds((prev) => {
                      const ids = group.items.map((p) => p.id);
                      return checked
                        ? [...new Set([...prev, ...ids])]
                        : prev.filter((id) => !ids.includes(id));
                    })
                  }
                  disabled={bulkBusy}
                  testIdPrefix="customer-pricing-bulk-raise"
                />
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
      {/* ---- Sprint 143 §3 — folder create / rename ---------------- */}
      {folderModalOpen && (
        <div
          data-testid="customer-pricing-folder-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            folderEditTarget
              ? t("customer_pricing.folder_rename_title")
              : t("customer_pricing.folder_new_title")
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
            className="card"
            style={{ maxWidth: 460, width: "100%", padding: 24 }}
            onSubmit={submitFolder}
          >
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
              {folderEditTarget
                ? t("customer_pricing.folder_rename_title")
                : t("customer_pricing.folder_new_title")}
            </h3>
            {folderError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
              >
                {folderError}
              </div>
            )}
            <div className="field">
              <label className="field-label" htmlFor="price-folder-name">
                {t("customer_pricing.folder_name_label")}
              </label>
              <input
                id="price-folder-name"
                className="field-input"
                data-testid="customer-pricing-folder-name"
                value={folderName}
                onChange={(event) => setFolderName(event.target.value)}
                autoFocus
              />
            </div>
            <div
              className="page-header-actions"
              style={{ marginTop: 16, justifyContent: "flex-end" }}
            >
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setFolderModalOpen(false)}
                disabled={folderBusy}
              >
                {t("cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                data-testid="customer-pricing-folder-submit"
                disabled={folderBusy}
              >
                {t("save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ---- Sprint 143 §3 — delete: TWO honest actions ------------- */}
      {folderDeleteTarget && (
        <div
          data-testid="customer-pricing-folder-delete-modal"
          role="dialog"
          aria-modal="true"
          // Sprint 187 §7.1 — the interpolation values, which were
          // missing. `role="dialog" aria-modal="true"` makes this the
          // dialog's ACCESSIBLE NAME, so a screen reader announced the
          // literal "Delete {{name}}" while the heading two lines below
          // read correctly.
          aria-label={t("customer_pricing.folder_delete_title", {
            name: folderDeleteTarget.name,
          })}
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
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
              {t("customer_pricing.folder_delete_title", {
                name: folderDeleteTarget.name,
              })}
            </h3>
            {/* Both outcomes named honestly, with the row count — the
                operator chooses between them rather than discovering
                which one a single "Delete" meant. */}
            <p className="muted" style={{ marginTop: 0 }}>
              {t("customer_pricing.folder_delete_body", {
                count: folderDeleteTarget.price_count,
              })}
            </p>
            <div
              style={{ display: "flex", flexDirection: "column", gap: 10 }}
            >
              <button
                type="button"
                className="btn btn-secondary"
                data-testid="customer-pricing-folder-delete-only"
                onClick={() => confirmDeleteFolder(false)}
                disabled={folderDeleteBusy}
              >
                {t("customer_pricing.folder_delete_only_action", {
                  count: folderDeleteTarget.price_count,
                })}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                data-testid="customer-pricing-folder-delete-with-contents"
                onClick={() => confirmDeleteFolder(true)}
                disabled={folderDeleteBusy}
              >
                {t("customer_pricing.folder_delete_with_contents_action", {
                  count: folderDeleteTarget.price_count,
                })}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setFolderDeleteTarget(null)}
                disabled={folderDeleteBusy}
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Sprint 143 §3 — copy a company category into a folder --- */}
      {fromCategoryOpen && (
        <div
          data-testid="customer-pricing-from-category-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("customer_pricing.folder_from_category_title")}
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
            className="card"
            style={{
              maxWidth: 620,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
            onSubmit={submitFromCategory}
          >
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
              {t("customer_pricing.folder_from_category_title")}
            </h3>
            <p className="muted" style={{ marginTop: 0, marginBottom: 16 }}>
              {t("customer_pricing.folder_from_category_intro")}
            </p>
            {fromCategoryError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
              >
                {fromCategoryError}
              </div>
            )}
            <div className="field">
              <label className="field-label" htmlFor="folder-from-category">
                {t("customer_pricing.folder_from_category_label")}
              </label>
              <select
                id="folder-from-category"
                className="field-select"
                data-testid="customer-pricing-from-category-select"
                value={fromCategoryId === "" ? "" : String(fromCategoryId)}
                onChange={(event) => pickFromCategory(event.target.value)}
              >
                <option value="">
                  {t("customer_pricing.folder_from_category_placeholder")}
                </option>
                {/* ACTIVE categories only: a retired category must not be
                    offered as the basis for a new agreed-price folder. */}
                {categories
                  .filter((c) => c.is_active)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </div>
            {fromCategoryId !== "" && (
              <>
                <div className="field">
                  <label
                    className="field-label"
                    htmlFor="folder-from-category-name"
                  >
                    {t("customer_pricing.folder_name_label")}
                  </label>
                  <input
                    id="folder-from-category-name"
                    className="field-input"
                    data-testid="customer-pricing-from-category-name"
                    value={fromCategoryName}
                    onChange={(event) =>
                      setFromCategoryName(event.target.value)
                    }
                  />
                </div>
                <div className="field">
                  <span className="field-label">
                    {t("customer_pricing.folder_from_category_services", {
                      count: fromCategoryServiceIds.length,
                      total: fromCategoryServices.length,
                    })}
                  </span>
                  {fromCategoryServices.length === 0 ? (
                    <p className="muted small" style={{ margin: 0 }}>
                      {t("customer_pricing.folder_from_category_no_services")}
                    </p>
                  ) : (
                    <div
                      style={{
                        maxHeight: 240,
                        overflowY: "auto",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        padding: 10,
                      }}
                    >
                      {fromCategoryServices.map((svc) => (
                        <label
                          key={svc.id}
                          style={{
                            display: "flex",
                            gap: 8,
                            alignItems: "center",
                            padding: "4px 0",
                          }}
                        >
                          <input
                            type="checkbox"
                            className="checkbox-input"
                            data-testid="customer-pricing-from-category-service"
                            checked={fromCategoryServiceIds.includes(svc.id)}
                            onChange={(event) =>
                              setFromCategoryServiceIds((current) =>
                                event.target.checked
                                  ? [...current, svc.id]
                                  : current.filter((id) => id !== svc.id),
                              )
                            }
                          />
                          <span>{svc.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
            <div
              className="page-header-actions"
              style={{ marginTop: 16, justifyContent: "flex-end" }}
            >
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setFromCategoryOpen(false)}
                disabled={fromCategoryBusy}
              >
                {t("cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                data-testid="customer-pricing-from-category-submit"
                disabled={fromCategoryBusy}
              >
                {t("customer_pricing.folder_from_category_confirm")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ---- Sprint 143 §3 — bulk move into / out of a folder -------- */}
      {moveFolderOpen && (
        <div
          data-testid="customer-pricing-move-folder-modal"
          role="dialog"
          aria-modal="true"
          // Sprint 187 §7.1 — same defect, same screen: announced as
          // "Move {{count}} row(s)".
          aria-label={t("customer_pricing.folder_move_title", {
            count: activeBulkSelection.length,
          })}
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
            style={{ maxWidth: 460, width: "100%", padding: 24 }}
          >
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
              {t("customer_pricing.folder_move_title", {
                count: activeBulkSelection.length,
              })}
            </h3>
            {moveFolderError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
              >
                {moveFolderError}
              </div>
            )}
            <div className="field">
              <label className="field-label" htmlFor="move-folder-target">
                {t("customer_pricing.folder_move_target_label")}
              </label>
              <select
                id="move-folder-target"
                className="field-select"
                data-testid="customer-pricing-move-folder-target"
                value={moveFolderTarget === "" ? "" : String(moveFolderTarget)}
                onChange={(event) =>
                  setMoveFolderTarget(
                    event.target.value === ""
                      ? ""
                      : Number(event.target.value),
                  )
                }
              >
                {/* "No folder" is a real destination — it is how a row
                    LEAVES a folder without being archived. */}
                <option value="">{t("customer_pricing.folder_none")}</option>
                {folders.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
            <div
              className="page-header-actions"
              style={{ marginTop: 16, justifyContent: "flex-end" }}
            >
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setMoveFolderOpen(false)}
                disabled={moveFolderBusy}
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                data-testid="customer-pricing-move-folder-confirm"
                onClick={confirmMoveToFolder}
                disabled={moveFolderBusy}
              >
                {t("customer_pricing.folder_move_confirm")}
              </button>
            </div>
          </div>
        </div>
      )}

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
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
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

            {/* Sprint 142 (#127 review carry-over) — `loadError` is a
                PAGE-level banner, and this modal is `position: fixed;
                inset: 0; zIndex: 100; aria-modal="true"`. So when the
                copy succeeded but the refresh that follows it failed,
                the "saved, but the list could not be refreshed" message
                rendered BEHIND this overlay: invisible on screen and,
                because `aria-modal` hides everything outside the dialog
                from the accessibility tree, unreachable to a screen
                reader as well. The modal stays open on purpose (the
                created/skipped summary below is what it exists to
                show), so the message is repeated INSIDE it rather than
                the modal being closed out from under that summary. */}
            {loadError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-pricing-copy-default-refresh-error"
              >
                {loadError}
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
                {/* #108 Part D — shared multi-select treatment. */}
                <MultiSelectToolbar
                  selectedCount={copySelectedServiceIds.length}
                  onSelectAll={() => toggleCopyAll(true)}
                  onClearAll={() => toggleCopyAll(false)}
                  disabled={copyBusy}
                  filterValue={copyFilter}
                  onFilterChange={setCopyFilter}
                  testIdPrefix="customer-pricing-copy-default"
                />
                {/* Sprint 138 §5 / Sprint 139 §3 — grouped by
                    ServiceCategory with a per-category select-all,
                    through the SHARED picker so this modal, the catalog
                    bulk-adjust and the price bulk-adjust cannot drift
                    into three different shapes. */}
                <CategoryGroupedPicker
                  groups={copyGroups}
                  getId={(service) => service.id}
                  renderItem={(service) =>
                    `${service.name} — ${service.default_unit_price}`
                  }
                  selectedIds={copySelectedServiceIds}
                  onToggleItem={toggleCopyService}
                  onToggleGroup={(group, checked) =>
                    toggleCopySelection(group.items, checked)
                  }
                  disabled={copyBusy}
                  testIdPrefix="customer-pricing-copy-default"
                />
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

      {/* Sprint 137 item 7 — ONE confirmation for the whole selection,
          naming the count. Rendered unconditionally and driven purely
          through the ref: a native <dialog> wrapped in `{cond && ...}`
          mounts invisible and the trigger looks dead (CLAUDE.md §3,
          Sprint 128). */}
      <ConfirmDialog
        ref={bulkArchiveDialogRef}
        title={t("customer_pricing.bulk_archive_confirm_title", {
          count: activeBulkSelection.length,
        })}
        body={t("customer_pricing.bulk_archive_confirm_body", {
          count: activeBulkSelection.length,
        })}
        confirmLabel={t("customer_pricing.bulk_archive_button")}
        onConfirm={handleConfirmBulkArchive}
        busy={bulkArchiveBusy}
        destructive
      />
    </div>
  );
}
