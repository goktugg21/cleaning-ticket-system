// Sprint 28 Batch 6 — Create Extra Work cart UI.
//
// Replaces the Sprint 26B single-line form with a shopping-cart
// workflow per the 2026-05-15 stakeholder meeting (§4):
//   * Customer composes a request by adding multiple service catalog
//     items to a cart, each with its own quantity, requested date,
//     and optional note.
//   * Submission produces one parent request with N line items.
//   * Backend routes the request based on whether every line has an
//     active CustomerServicePrice (INSTANT) or not (PROPOSAL).
//
// View-first compliance: the form itself is the "Create" surface
// (an add page is intentionally a form). After submission the
// result panel is read-only.
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronLeft, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listCustomerPrices, listServices } from "../api/admin";
import { api, getApiError } from "../api/client";
import { createExtraWork, getExtraWorkPreview } from "../api/extraWork";
import type {
  Building,
  Customer,
  CustomerServicePrice,
  ExtraWorkCategory,
  ExtraWorkIntentErrorCode,
  ExtraWorkPreviewLine,
  ExtraWorkPreviewPriceSource,
  ExtraWorkPreviewResponse,
  ExtraWorkRequestDetail,
  ExtraWorkRequestIntent,
  ExtraWorkUrgency,
  PaginatedResponse,
  Service,
  ServiceUnitType,
} from "../api/types";
import { InvoiceLineRow } from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { formatMoney, formatNumber } from "../lib/intl";


interface ParentFormState {
  building: string;
  customer: string;
  title: string;
  description: string;
  category: ExtraWorkCategory;
  category_other_text: string;
  urgency: ExtraWorkUrgency;
  preferred_date: string;
}

interface CartLineState {
  tempId: string;
  serviceId: string;
  // Free-text service description, used ONLY when serviceId ===
  // CUSTOM_SERVICE_VALUE. A custom line is submitted with this text as
  // `custom_description` (and NO `service`); the backend treats it as
  // needs-provider-pricing and routes the request to a proposal.
  customDescription: string;
  quantity: string;
  requestedDate: string;
  customerNote: string;
}

// Sentinel serviceId for the "Custom…" option in the per-line service
// dropdown. A cart line is "custom" iff line.serviceId === this value.
// It is never a real service id (numeric), so it never collides with a
// catalog service or the agreed-price lookups.
const CUSTOM_SERVICE_VALUE = "__custom__";

const EMPTY_PARENT: ParentFormState = {
  building: "",
  customer: "",
  title: "",
  description: "",
  category: "DEEP_CLEANING",
  category_other_text: "",
  urgency: "NORMAL",
  preferred_date: "",
};

const CATEGORY_VALUES: ExtraWorkCategory[] = [
  "DEEP_CLEANING",
  "WINDOW_CLEANING",
  "FLOOR_MAINTENANCE",
  "SANITARY_SERVICE",
  "WASTE_REMOVAL",
  "FURNITURE_MOVING",
  "EVENT_CLEANING",
  "EMERGENCY_CLEANING",
  "OTHER",
];

const URGENCY_VALUES: ExtraWorkUrgency[] = ["NORMAL", "HIGH", "URGENT"];

const CATEGORY_I18N_KEY: Record<ExtraWorkCategory, string> = {
  DEEP_CLEANING: "category.deep_cleaning",
  WINDOW_CLEANING: "category.window_cleaning",
  FLOOR_MAINTENANCE: "category.floor_maintenance",
  SANITARY_SERVICE: "category.sanitary_service",
  WASTE_REMOVAL: "category.waste_removal",
  FURNITURE_MOVING: "category.furniture_moving",
  EVENT_CLEANING: "category.event_cleaning",
  EMERGENCY_CLEANING: "category.emergency_cleaning",
  OTHER: "category.other",
};

const URGENCY_I18N_KEY: Record<ExtraWorkUrgency, string> = {
  NORMAL: "urgency.normal",
  HIGH: "urgency.high",
  URGENT: "urgency.urgent",
};

// Sprint 5 — service unit-type label keys for the agreed-prices panel.
const UNIT_TYPE_I18N_KEY: Record<ServiceUnitType, string> = {
  HOURS: "unit_type.hours",
  SQUARE_METERS: "unit_type.square_meters",
  FIXED: "unit_type.fixed",
  ITEM: "unit_type.item",
  OTHER: "unit_type.other",
};

// Sprint 14 helper — match a customer to a building via legacy
// Customer.building OR the M:N linked_building_ids list.
function customerMatchesBuilding(
  customer: Customer,
  buildingId: number,
): boolean {
  return (
    customer.building === buildingId ||
    (customer.linked_building_ids?.includes(buildingId) ?? false)
  );
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function nextTempId(): string {
  // Lightweight client-only id — no crypto needed because this never
  // leaves the browser.
  return `line-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function emptyCartLine(): CartLineState {
  return {
    tempId: nextTempId(),
    serviceId: "",
    customDescription: "",
    quantity: "1",
    requestedDate: todayISO(),
    customerNote: "",
  };
}

// Sprint 5 (frontend) — debounce window for the live preview re-fetch.
const PREVIEW_DEBOUNCE_MS = 350;

// i18n keys for the intent options. The set of options actually shown
// is driven ENTIRELY by the backend's `allowed_intents`; these maps
// only provide the label/description copy for whichever intents the
// backend allows.
const INTENT_LABEL_KEY: Record<ExtraWorkRequestIntent, string> = {
  DIRECT_AGREED_PRICE_ORDER: "create.intent.direct.label",
  AUTO_START_AFTER_PRICING: "create.intent.auto_start.label",
  REQUEST_QUOTE: "create.intent.request_quote.label",
};
const INTENT_DESC_KEY: Record<ExtraWorkRequestIntent, string> = {
  DIRECT_AGREED_PRICE_ORDER: "create.intent.direct.desc",
  AUTO_START_AFTER_PRICING: "create.intent.auto_start.desc",
  REQUEST_QUOTE: "create.intent.request_quote.desc",
};

// Per-line price-source badge copy (preview vocabulary).
const PREVIEW_SOURCE_KEY: Record<ExtraWorkPreviewPriceSource, string> = {
  AGREED_CUSTOMER_PRICE: "create.preview.source_agreed",
  NEEDS_PROVIDER_PRICING: "create.preview.source_needs_pricing",
  AD_HOC: "create.preview.source_ad_hoc",
};
// Reuse InvoiceLineRow's existing source-pill CSS by mapping the
// preview vocabulary onto the closest persisted-line modifier class.
// This is purely a colour choice for a backend-provided source — NOT
// client-side inference of the source itself.
const PREVIEW_SOURCE_TAG: Record<ExtraWorkPreviewPriceSource, string> = {
  AGREED_CUSTOMER_PRICE: "contract",
  NEEDS_PROVIDER_PRICING: "needs_proposal",
  AD_HOC: "custom",
};

// Stable backend intent-rejection code -> i18n key. Unknown codes fall
// back to the backend-supplied `detail` string (see intentErrorText).
const INTENT_ERROR_KEY: Record<ExtraWorkIntentErrorCode, string> = {
  intent_requires_all_agreed: "create.intent.error.requires_all_agreed",
  intent_requires_non_agreed_line:
    "create.intent.error.requires_non_agreed_line",
  intent_forbidden_for_role: "create.intent.error.forbidden_for_role",
  intent_forbidden_for_provider: "create.intent.error.forbidden_for_provider",
  intent_required: "create.intent.error.required",
};

interface AgreedTotals {
  subtotal: number;
  vat: number;
  total: number;
  agreedCount: number;
  unpricedCount: number;
}

// DISPLAY-ONLY cosmetic arithmetic over the backend-provided agreed
// prices. NOT business logic: it never decides routing/intent and never
// touches non-agreed lines (those carry no price and are shown as
// "to be priced by the provider"). If the preview endpoint later
// returns server-computed totals, switch to those.
function computeAgreedTotals(lines: ExtraWorkPreviewLine[]): AgreedTotals {
  let subtotal = 0;
  let vat = 0;
  let agreedCount = 0;
  let unpricedCount = 0;
  for (const line of lines) {
    const qty = Number(line.quantity);
    const unit =
      line.agreed_unit_price !== null ? Number(line.agreed_unit_price) : null;
    if (
      line.price_source === "AGREED_CUSTOMER_PRICE" &&
      unit !== null &&
      Number.isFinite(qty) &&
      Number.isFinite(unit)
    ) {
      const lineSubtotal = qty * unit;
      const pct =
        line.agreed_vat_pct !== null ? Number(line.agreed_vat_pct) : 0;
      subtotal += lineSubtotal;
      vat += Number.isFinite(pct) ? lineSubtotal * (pct / 100) : 0;
      agreedCount += 1;
    } else {
      unpricedCount += 1;
    }
  }
  return { subtotal, vat, total: subtotal + vat, agreedCount, unpricedCount };
}

// True when a create rejection is an intent rejection. The backend
// emits `{ "request_intent": ["<message>"] }`; DRF does not serialize
// the stable error code on the wire, so we can only detect the field
// and fall back to a friendly generic message (the precise codes are
// surfaced via the preview channel).
function isIntentSubmitError(err: unknown): boolean {
  const data = (err as { response?: { data?: unknown } } | null)?.response
    ?.data;
  return (
    !!data &&
    typeof data === "object" &&
    "request_intent" in (data as Record<string, unknown>)
  );
}

export interface CreateExtraWorkPageProps {
  /** M3 (SoT Addendum A.5) — entry-point separation. "standard" is the
   *  generic /extra-work/new flow with REQUEST_QUOTE filtered OUT of
   *  the intent options; "quote" is the dedicated
   *  /extra-work/request-quote page with the intent picker hidden and
   *  the selection pinned to REQUEST_QUOTE (never silently another
   *  intent). All preview/cart/submit behaviour is otherwise shared. */
  intentMode?: "quote" | "standard";
}

export function CreateExtraWorkPage({
  intentMode = "standard",
}: CreateExtraWorkPageProps) {
  const { t } = useTranslation(["extra_work", "common"]);
  const isQuoteMode = intentMode === "quote";

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Sprint 29 Batch 29.8.5 — soft warning channel used when the service
  // catalog endpoint succeeds but is empty, OR when it errors. Either
  // case still lets the form render (buildings + customers carry the
  // hard scope contract); without a service the user cannot submit
  // the cart, but the dropdowns still appear so they can see what they
  // would normally pick from.
  const [catalogWarning, setCatalogWarning] = useState("");
  const [form, setForm] = useState<ParentFormState>(EMPTY_PARENT);
  const [cartLines, setCartLines] = useState<CartLineState[]>([emptyCartLine()]);

  // Post-submit result state — once present, the form is collapsed
  // into a read-only confirmation panel.
  const [result, setResult] = useState<ExtraWorkRequestDetail | null>(null);

  // Sprint 5 (frontend) — intent layer. `selectedIntent` is seeded from
  // the preview's `default_intent` and only ever holds an intent the
  // backend currently allows (reconciled on every preview). `preview`
  // is tagged with the cart `key` it was computed for so a stale
  // response is never rendered against a changed cart.
  const [selectedIntent, setSelectedIntent] =
    useState<ExtraWorkRequestIntent | null>(null);
  const [preview, setPreview] = useState<
    | { key: string; data: ExtraWorkPreviewResponse }
    | { key: string; error: string }
    | null
  >(null);

  // Sprint 5 — the selected customer's agreed contract prices, shown
  // upfront so the customer knows which services have an agreed price
  // (and what it is) BEFORE composing the cart. Tagged with the
  // customerId it was fetched for so a stale list is never shown.
  const [customerPrices, setCustomerPrices] = useState<{
    customerId: number;
    rows: CustomerServicePrice[];
  } | null>(null);
  // Search filter for the agreed-prices dropdown (scales to long
  // contract lists — the list scrolls and filters rather than dumping
  // every row inline).
  const [priceSearch, setPriceSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      // Sprint 29 Batch 29.8.5 — split the three mount fetches into
      // independent settle paths. Buildings and customers are the
      // hard scope contract: without them there is nothing to render.
      // Services are soft-required: a 4xx/5xx (e.g. an admin who hasn't
      // seeded the catalog yet) downgrades to a yellow warning instead
      // of blocking the form, so STAFF/CUSTOMER_USER personas don't get
      // stuck behind a backend hiccup.
      const [buildingResult, customerResult, servicesResult] =
        await Promise.allSettled([
          api.get<PaginatedResponse<Building>>("/buildings/", {
            params: { page_size: 200 },
          }),
          api.get<PaginatedResponse<Customer>>("/customers/", {
            params: { page_size: 200 },
          }),
          // Sprint 28 Batch 5 — reuse the catalog helper. Only active
          // services are eligible for the cart.
          listServices({ is_active: true }),
        ]);
      if (cancelled) return;

      // Hard-required: buildings.
      if (buildingResult.status === "rejected") {
        setError(getApiError(buildingResult.reason));
        setLoadingOptions(false);
        return;
      }
      // Hard-required: customers.
      if (customerResult.status === "rejected") {
        setError(getApiError(customerResult.reason));
        setLoadingOptions(false);
        return;
      }

      const buildingResults = buildingResult.value.data.results;
      const customerResults = customerResult.value.data.results;
      setBuildings(buildingResults);
      setCustomers(customerResults);

      // Soft-required: services.
      if (servicesResult.status === "fulfilled") {
        setServices(servicesResult.value);
        if (servicesResult.value.length === 0) {
          setCatalogWarning(t("create.warning_catalog_empty"));
        }
      } else {
        setServices([]);
        setCatalogWarning(t("create.warning_catalog_unavailable"));
      }

      const firstBuilding = buildingResults[0];
      const firstCustomer = firstBuilding
        ? customerResults.find((customer) =>
            customerMatchesBuilding(customer, firstBuilding.id),
          )
        : undefined;
      setForm((current) => ({
        ...current,
        building:
          current.building || (firstBuilding ? String(firstBuilding.id) : ""),
        customer:
          current.customer || (firstCustomer ? String(firstCustomer.id) : ""),
      }));
      setLoadingOptions(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const filteredCustomers = useMemo(() => {
    if (!form.building) return customers;
    const buildingId = Number(form.building);
    return customers.filter((customer) =>
      customerMatchesBuilding(customer, buildingId),
    );
  }, [customers, form.building]);

  const filteredBuildings = useMemo(() => {
    if (!form.customer) return buildings;
    const c = customers.find((x) => String(x.id) === form.customer);
    if (!c) return buildings;
    return buildings.filter((b) => customerMatchesBuilding(c, b.id));
  }, [buildings, customers, form.customer]);

  // Auto-select the only matching customer when there's exactly one.
  useEffect(() => {
    if (!form.building) return;
    if (form.customer) return;
    if (filteredCustomers.length === 1) {
      setForm((current) => ({
        ...current,
        customer: String(filteredCustomers[0].id),
      }));
    }
  }, [form.building, form.customer, filteredCustomers]);

  useEffect(() => {
    if (!form.customer) return;
    const stillValid = filteredCustomers.some(
      (customer) => String(customer.id) === form.customer,
    );
    if (!stillValid) {
      setForm((current) => ({
        ...current,
        customer: filteredCustomers[0]
          ? String(filteredCustomers[0].id)
          : "",
      }));
    }
  }, [filteredCustomers, form.customer]);

  useEffect(() => {
    if (!form.building) return;
    const stillValid = filteredBuildings.some(
      (b) => String(b.id) === form.building,
    );
    if (!stillValid) {
      setForm((current) => ({
        ...current,
        building: filteredBuildings[0]
          ? String(filteredBuildings[0].id)
          : "",
      }));
    }
  }, [filteredBuildings, form.building]);

  // The cart is "previewable" once a building + customer are chosen and
  // every line carries a service, a positive quantity, and a date —
  // exactly what the preview serializer requires.
  const previewable = useMemo(() => {
    if (!form.building || !form.customer) return false;
    if (cartLines.length === 0) return false;
    return cartLines.every((line) => {
      // A line is previewable when it is a catalog service (a chosen
      // numeric serviceId) OR a custom line with non-empty text. An
      // empty line, or a custom line with blank text, is not.
      if (line.serviceId === CUSTOM_SERVICE_VALUE) {
        if (!line.customDescription.trim()) return false;
      } else if (!line.serviceId) {
        return false;
      }
      const q = Number(line.quantity);
      if (!Number.isFinite(q) || q <= 0) return false;
      return Boolean(line.requestedDate);
    });
  }, [form.building, form.customer, cartLines]);

  // Stable signature of ONLY the pricing-relevant fields (note text is
  // excluded so editing a note never re-fetches). `null` when the cart
  // is not previewable. The effect re-fetches exactly when this value
  // changes; the payload is reconstructed by parsing it, so the effect
  // reads no other reactive cart state.
  const previewKey = useMemo(() => {
    if (!previewable) return null;
    return JSON.stringify({
      b: Number(form.building),
      c: Number(form.customer),
      l: cartLines.map((line) => {
        const isCustom = line.serviceId === CUSTOM_SERVICE_VALUE;
        return {
          s: isCustom ? null : Number(line.serviceId),
          c: isCustom ? line.customDescription.trim() : null,
          q: line.quantity,
          d: line.requestedDate,
        };
      }),
    });
  }, [previewable, form.building, form.customer, cartLines]);

  // Debounced live preview. All state writes happen inside the timer's
  // async callback (deferred), never synchronously in the effect body.
  useEffect(() => {
    if (!previewKey) return;
    const parsed = JSON.parse(previewKey) as {
      b: number;
      c: number;
      l: { s: number | null; c: string | null; q: string; d: string }[];
    };
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const data = await getExtraWorkPreview({
            building: parsed.b,
            customer: parsed.c,
            request_intent: selectedIntent ?? undefined,
            // Catalog lines send `service`; custom lines send
            // `custom_description` (and omit `service`). The preview
            // serializer accepts service XOR custom_description.
            line_items: parsed.l.map((line) =>
              line.c !== null
                ? {
                    custom_description: line.c,
                    quantity: line.q,
                    requested_date: line.d,
                  }
                : {
                    service: line.s ?? undefined,
                    quantity: line.q,
                    requested_date: line.d,
                  },
            ),
          });
          if (cancelled) return;
          setPreview({ key: previewKey, data });
          // Reconcile the selection against what the backend allows for
          // the (possibly changed) cart, in priority order:
          //   1. keep the current pick if it is still allowed;
          //   2. else the backend `default_intent` IF it is itself
          //      allowed;
          //   3. else the FIRST allowed intent — this is the PR #71
          //      Codex P2 fix: when the derived default is forbidden
          //      (e.g. provider + a non-agreed line ⇒ default_intent
          //      = REQUEST_QUOTE but allowed_intents = [AUTO_START_
          //      AFTER_PRICING]) we must still select an allowed
          //      option rather than leaving the radio unchecked and
          //      submitting with the backend's forbidden default;
          //   4. else null, only when the backend allows nothing.
          // Guarantees `selectedIntent` is always a member of
          // allowed_intents whenever the backend allows ≥1, so the
          // radio renders checked. Triggers at most ONE extra debounced
          // re-fetch (the new selection is re-validated) — bounded.
          setSelectedIntent((current) => {
            // M3 — quote page: the selection is PINNED to
            // REQUEST_QUOTE whenever the latest preview allows it;
            // when it does not (e.g. every line has an agreed price),
            // the selection is null and submit is blocked with an
            // inline notice. NEVER silently fall back to another
            // intent on the quote page.
            if (isQuoteMode) {
              return data.allowed_intents.includes("REQUEST_QUOTE")
                ? "REQUEST_QUOTE"
                : null;
            }
            // M3 — standard page: reconcile against the FILTERED set
            // (REQUEST_QUOTE removed) so the selection can never be
            // REQUEST_QUOTE here. Same priority order as before
            // (current pick → backend default → first offerable →
            // null when nothing is offerable).
            const offerable: ExtraWorkRequestIntent[] =
              data.allowed_intents.filter(
                (intent) => intent !== "REQUEST_QUOTE",
              );
            if (current && offerable.includes(current)) {
              return current;
            }
            if (offerable.includes(data.default_intent)) {
              return data.default_intent;
            }
            return offerable[0] ?? null;
          });
        } catch (err) {
          if (cancelled) return;
          setPreview({ key: previewKey, error: getApiError(err) });
        }
      })();
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [previewKey, selectedIntent, isQuoteMode]);

  // Fetch the selected customer's agreed contract prices. All state
  // writes are inside the async resolution (deferred), never in the
  // effect body, so this adds no set-state-in-effect violation. A 4xx
  // (e.g. a role without price-read access) degrades to an empty list.
  useEffect(() => {
    const customerId = form.customer ? Number(form.customer) : null;
    if (!customerId) return;
    let cancelled = false;
    listCustomerPrices(customerId)
      .then((rows) => {
        if (!cancelled) setCustomerPrices({ customerId, rows });
      })
      .catch(() => {
        if (!cancelled) setCustomerPrices({ customerId, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [form.customer]);

  // Render-time derived preview view-state. A `preview` is only honoured
  // when its `key` matches the CURRENT cart, so a stale response is
  // never shown (or acted on) against a changed cart.
  const previewData =
    previewable && preview !== null && preview.key === previewKey && "data" in preview
      ? preview.data
      : null;
  const previewErrorMsg =
    previewable &&
    preview !== null &&
    preview.key === previewKey &&
    "error" in preview
      ? preview.error
      : null;
  const previewLoading =
    previewable && (preview === null || preview.key !== previewKey);

  // Stable backend code -> localized text, falling back to the backend
  // detail string for any code we don't have copy for yet.
  const intentErrorText = (err: { code: string; detail: string }): string => {
    const key = INTENT_ERROR_KEY[err.code as ExtraWorkIntentErrorCode];
    return key ? t(key) : err.detail;
  };

  // DISPLAY-ONLY cart total over the agreed-price lines (see
  // computeAgreedTotals). Recomputed each render; trivially cheap.
  const previewTotals = previewData
    ? computeAgreedTotals(previewData.lines)
    : null;

  // M3 — mode-derived intent view-state.
  // Standard page: the picker renders the FILTERED set (REQUEST_QUOTE
  // removed); when the backend would ONLY allow REQUEST_QUOTE, nothing
  // is offerable here and the mirrored notice points at the quote page.
  // Quote page: no picker; when the latest preview does not allow
  // REQUEST_QUOTE the submit is disabled with an inline notice.
  const offeredIntents = previewData
    ? previewData.allowed_intents.filter(
        (intent) => intent !== "REQUEST_QUOTE",
      )
    : [];
  const quoteAllowed =
    previewData !== null &&
    previewData.allowed_intents.includes("REQUEST_QUOTE");
  const quoteUnavailable = isQuoteMode && previewData !== null && !quoteAllowed;
  const standardOnlyQuote =
    !isQuoteMode &&
    previewData !== null &&
    previewData.allowed_intents.length > 0 &&
    offeredIntents.length === 0;

  // Agreed-prices panel: catalog lookup (for category/unit labels the
  // pricing endpoint doesn't carry) + the current customer's currently-
  // valid agreed rows. We filter to active + in-window client-side so
  // the list matches what a customer is shown regardless of viewer role
  // (the backend already narrows for CUSTOMER_USER; providers get all
  // rows, so we narrow here too for a consistent "current prices" view).
  const serviceById = useMemo(
    () => new Map(services.map((svc) => [svc.id, svc])),
    [services],
  );
  const pricesLoading =
    !!form.customer &&
    (customerPrices === null ||
      customerPrices.customerId !== Number(form.customer));
  const agreedPrices = useMemo(() => {
    if (
      customerPrices === null ||
      !form.customer ||
      customerPrices.customerId !== Number(form.customer)
    ) {
      return [] as CustomerServicePrice[];
    }
    const today = todayISO();
    return customerPrices.rows
      .filter(
        (p) =>
          p.is_active &&
          p.valid_from <= today &&
          (p.valid_to === null || p.valid_to >= today),
      )
      .sort((a, b) => a.service_name.localeCompare(b.service_name));
  }, [customerPrices, form.customer]);
  const filteredAgreedPrices = useMemo(() => {
    const q = priceSearch.trim().toLowerCase();
    if (!q) return agreedPrices;
    return agreedPrices.filter((p) => {
      const svc = serviceById.get(p.service);
      const label = svc
        ? `${svc.category_name} ${svc.name}`
        : p.service_name;
      return label.toLowerCase().includes(q);
    });
  }, [agreedPrices, priceSearch, serviceById]);

  // Owner request: surface each service's AGREED/contract price inline in
  // the cart's service-select option label. Built from the SAME currently-
  // valid agreed rows the browse panel shows (active + in-window for the
  // selected customer). Empty when no customer is selected or prices are
  // still loading, so the select falls back to plain service names.
  const agreedPriceByServiceId = useMemo(
    () => new Map(agreedPrices.map((p) => [p.service, p])),
    [agreedPrices],
  );

  // Compose the " — €29,00 / m²" suffix for a service that has an agreed
  // price, reusing the existing money + unit-type formatting. Returns "" so
  // services without an agreed price show the plain name.
  const agreedPriceSuffix = (serviceId: number): string => {
    const price = agreedPriceByServiceId.get(serviceId);
    if (!price) return "";
    const svc = serviceById.get(serviceId);
    const unitLabel = svc ? t(UNIT_TYPE_I18N_KEY[svc.unit_type]) : "";
    const money = formatMoney(price.unit_price);
    return unitLabel
      ? ` — ${money} / ${unitLabel}`
      : ` — ${money}`;
  };

  function update<K extends keyof ParentFormState>(
    name: K,
    value: ParentFormState[K],
  ) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function addCartLine() {
    setCartLines((current) => [...current, emptyCartLine()]);
  }

  // Add a service picked from the agreed-prices dropdown into the cart:
  // fill the first empty line if there is one, otherwise append a new
  // line. No-op when the service is already in the cart (the cart
  // rejects duplicate services on submit).
  function addServiceFromContract(serviceId: number) {
    setCartLines((current) => {
      if (current.some((l) => Number(l.serviceId) === serviceId)) {
        return current;
      }
      const emptyIdx = current.findIndex((l) => !l.serviceId);
      if (emptyIdx >= 0) {
        return current.map((l, i) =>
          i === emptyIdx ? { ...l, serviceId: String(serviceId) } : l,
        );
      }
      return [...current, { ...emptyCartLine(), serviceId: String(serviceId) }];
    });
  }

  function removeCartLine(tempId: string) {
    setCartLines((current) => current.filter((l) => l.tempId !== tempId));
  }

  function updateCartLine<K extends keyof CartLineState>(
    tempId: string,
    field: K,
    value: CartLineState[K],
  ) {
    setCartLines((current) =>
      current.map((line) =>
        line.tempId === tempId ? { ...line, [field]: value } : line,
      ),
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!form.title.trim()) {
      setError(t("create.error_title_required"));
      return;
    }
    if (!form.description.trim()) {
      setError(t("create.error_description_required"));
      return;
    }
    if (!form.building || !form.customer) {
      setError(t("create.error_building_customer_required"));
      return;
    }
    if (form.category === "OTHER" && !form.category_other_text.trim()) {
      setError(t("create.error_category_other_required"));
      return;
    }

    // Cart validation.
    if (cartLines.length === 0) {
      setError(t("create.error_empty_cart"));
      return;
    }
    const seenServiceIds = new Set<number>();
    for (const line of cartLines) {
      const isCustom = line.serviceId === CUSTOM_SERVICE_VALUE;
      if (isCustom) {
        // Custom line: require non-empty free-text. Custom lines are
        // never deduped against catalog services and skip the
        // inactive-service check (they have no service FK).
        if (!line.customDescription.trim()) {
          setError(t("create.error_line_custom_required"));
          return;
        }
      } else {
        if (!line.serviceId) {
          setError(t("create.error_line_service_required"));
          return;
        }
        const svcId = Number(line.serviceId);
        if (seenServiceIds.has(svcId)) {
          setError(t("create.error_duplicate_service"));
          return;
        }
        seenServiceIds.add(svcId);
      }
      const qtyNum = Number(line.quantity);
      if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
        setError(t("create.error_line_quantity_invalid"));
        return;
      }
      if (!line.requestedDate) {
        setError(t("create.error_line_requested_date_required"));
        return;
      }
      if (!isCustom) {
        const svc = services.find((s) => s.id === Number(line.serviceId));
        if (svc && !svc.is_active) {
          setError(t("create.error_inactive_service"));
          return;
        }
      }
    }

    // M3 — quote page: submitting REQUIRES a fresh preview that allows
    // REQUEST_QUOTE and the pinned selection. Without it (preview
    // mid-flight, preview error, or an all-agreed-price cart) we block
    // rather than let the backend derive a NON-quote intent from an
    // omitted request_intent — the quote page must never create
    // anything but a quote request.
    if (
      isQuoteMode &&
      (!previewData || !quoteAllowed || selectedIntent !== "REQUEST_QUOTE")
    ) {
      setError(t("quote.error_not_ready"));
      return;
    }
    // M3 — standard page: REQUEST_QUOTE is filtered out of both the
    // options and the reconcile, so this is unreachable by
    // construction; belt-and-suspenders so the generic flow can never
    // submit a quote intent through any state race.
    if (!isQuoteMode && selectedIntent === "REQUEST_QUOTE") {
      setError(t("create.intent.error.none_selected"));
      return;
    }

    // PR #71 Codex P2 fix — when a fresh preview exists, REQUIRE a
    // selected intent the backend currently allows. The reconcile keeps
    // `selectedIntent` inside allowed_intents, so this only trips if the
    // backend allowed nothing for this cart/actor; block with a friendly
    // message rather than creating the request with the backend's
    // (possibly forbidden) derived default.
    if (
      previewData &&
      (!selectedIntent || !previewData.allowed_intents.includes(selectedIntent))
    ) {
      setError(t("create.intent.error.none_selected"));
      return;
    }

    // If the live preview already knows the chosen intent is invalid for
    // this cart, surface the precise (backend-coded) reason rather than
    // letting the create call fail with an un-localized field error.
    if (
      previewData &&
      previewData.requested_intent === selectedIntent &&
      previewData.requested_intent_allowed === false &&
      previewData.requested_intent_error
    ) {
      setError(intentErrorText(previewData.requested_intent_error));
      return;
    }

    // Never send a `request_intent` that isn't in the LATEST preview's
    // allowed_intents. When a fresh preview confirms the selection, send
    // it; when no fresh preview exists (preview unavailable / a refetch
    // is mid-flight), omit it and let the backend derive a safe default.
    const intentToSend =
      previewData &&
      selectedIntent &&
      previewData.allowed_intents.includes(selectedIntent)
        ? selectedIntent
        : undefined;

    setSubmitting(true);
    try {
      const created = await createExtraWork({
        building: Number(form.building),
        customer: Number(form.customer),
        title: form.title.trim(),
        description: form.description.trim(),
        category: form.category,
        category_other_text:
          form.category === "OTHER" ? form.category_other_text.trim() : "",
        urgency: form.urgency,
        preferred_date: form.preferred_date || null,
        // Send the validated intent (a member of the latest preview's
        // allowed_intents). Omitted when no fresh preview exists: the
        // backend then derives a safe default — identical to the
        // pre-intent-layer graceful-degradation behaviour.
        ...(intentToSend ? { request_intent: intentToSend } : {}),
        // Catalog lines send `service`; custom lines send
        // `custom_description` (and omit `service`) — service XOR
        // custom_description, validated above.
        line_items: cartLines.map((line) =>
          line.serviceId === CUSTOM_SERVICE_VALUE
            ? {
                custom_description: line.customDescription.trim(),
                quantity: line.quantity,
                requested_date: line.requestedDate,
                customer_note: line.customerNote.trim() || undefined,
              }
            : {
                service: Number(line.serviceId),
                quantity: line.quantity,
                requested_date: line.requestedDate,
                customer_note: line.customerNote.trim() || undefined,
              },
        ),
      });
      setResult(created);
    } catch (err) {
      // Intent rejections (the backend code is not on the wire) get a
      // friendly localized message; everything else surfaces the DRF
      // field/detail message verbatim as before.
      if (isIntentSubmitError(err)) {
        setError(t("create.intent.error.rejected_generic"));
      } else {
        setError(getApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const noOptions =
    !loadingOptions && (buildings.length === 0 || customers.length === 0);

  // ----- Result panel (read-only confirmation) -----
  if (result) {
    const isInstant = result.routing_decision === "INSTANT";
    // Per-line breakdown for the routing-explanation banner. Each
    // count is sourced from the BACKEND's per-line `price_source` —
    // never inferred from labels / category names / client math. Cart
    // lines only ever return "CONTRACT" or "NEEDS_PROPOSAL"
    // (backend/extra_work/serializers.py::ExtraWorkRequestItemSerializer
    // .get_price_source); any other value would be a bug.
    const cartLineList = result.line_items ?? [];
    const contractLineCount = cartLineList.filter(
      (line) => line.price_source === "CONTRACT",
    ).length;
    const needsProposalLineCount = cartLineList.filter(
      (line) => line.price_source === "NEEDS_PROPOSAL",
    ).length;
    return (
      <div data-testid="extra-work-create-result">
        <div className="page-header">
          <div>
            <Link to="/extra-work" className="link-back">
              <ChevronLeft size={14} strokeWidth={2.5} />
              {t("back_to_extra_work")}
            </Link>
            <h2 className="page-title">{t("result.heading")}</h2>
          </div>
        </div>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="form-section">
            <div
              className={isInstant ? "alert-info" : "alert-info"}
              role="status"
              data-testid={
                isInstant
                  ? "extra-work-result-instant"
                  : "extra-work-result-proposal"
              }
            >
              {isInstant
                ? t("result.instant_processing")
                : t("result.proposal_pending")}
              {cartLineList.length > 0 && (
                <div
                  className="muted small"
                  style={{ marginTop: 6 }}
                  data-testid="extra-work-result-routing-breakdown"
                >
                  {t("result.routing_breakdown", {
                    contract: contractLineCount,
                    needsProposal: needsProposalLineCount,
                    total: cartLineList.length,
                  })}
                </div>
              )}
            </div>
            <div
              className="status-actions"
              style={{ display: "flex", gap: 8, marginTop: 12 }}
            >
              <Link to="/extra-work" className="btn btn-secondary btn-sm">
                {t("result.back_to_list")}
              </Link>
              <Link
                to={`/extra-work/${result.id}`}
                className="btn btn-primary btn-sm"
                data-testid="extra-work-result-view-link"
              >
                {t("result.view_request")}
              </Link>
            </div>
          </div>
        </div>

        {/* Cart-line preview. First consumer of InvoiceLineRow — uses
            real persisted ExtraWorkRequestItem rows returned by the
            create endpoint, with backend-driven `price_source` /
            `contract_unit_price` / `contract_vat_pct`. NO frontend
            inference; the Source column is whatever the backend says.

            Totals row deliberately NOT rendered here: parent aggregates
            (`subtotal_amount`, `vat_amount`, `total_amount`) DO exist on
            the wire (backend/extra_work/serializers.py L461-463) but
            they aggregate from `pricing_line_items`, not from cart
            `line_items`. On a fresh post-submit cart they are
            therefore "0.00" until provider pricing is built. Surfacing
            zeros would mislead more than it informs; the EW-detail
            consumer (later task) renders totals when pricing exists. */}
        {cartLineList.length > 0 && (
          <div className="card">
            <div className="form-section">
              <div className="form-section-title">
                {t("result.cart_preview_title")}
              </div>
              <div className="table-wrap">
                <table
                  className="data-table ew-pricing-table"
                  data-testid="extra-work-result-cart-table"
                >
                  <thead>
                    <tr>
                      {INVOICE_LINE_COLUMN_KEYS.map((key) => (
                        <th key={key}>{t(key)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cartLineList.map((line) => (
                      <InvoiceLineRow
                        key={line.id}
                        lineKind="cart"
                        line={line}
                        editable={false}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ----- Form -----
  return (
    <div
      data-testid={
        isQuoteMode ? "extra-work-quote-page" : "extra-work-create-page"
      }
    >
      <div className="page-header">
        <div>
          <Link to="/extra-work" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_extra_work")}
          </Link>
          <h2 className="page-title">
            {isQuoteMode ? t("quote.page_title") : t("create.page_title")}
          </h2>
          <p className="page-sub">
            {isQuoteMode
              ? t("quote.page_subtitle")
              : t("create.page_subtitle")}
          </p>
        </div>
      </div>

      {loadingOptions && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {noOptions && !error && (
        <div className="alert-error" style={{ marginBottom: 16 }}>
          {t("create.error_no_access")}
        </div>
      )}

      {catalogWarning && (
        <div
          className="alert-warning"
          style={{ marginBottom: 16 }}
          role="status"
          data-testid="create-ew-catalog-warning"
        >
          {catalogWarning}
        </div>
      )}

      {error && (
        <div
          className="alert-error"
          style={{ marginBottom: 16 }}
          role="alert"
          data-testid="extra-work-create-error"
        >
          {error}
        </div>
      )}

      {/* Full-width form — the previous `.create-layout` class wrapped
          this form in a `1fr 300px` grid that reserved an empty right
          column (there is no `.create-side` on this page), leaving
          ~320px of grey space on the right of the form. The form is
          now a plain block; the inner `.create-main` card still owns
          the vertical flow of form-sections. */}
      <form onSubmit={handleSubmit}>
        <div className="card create-main">
          <div className="form-section">
            <div className="form-section-title">
              {t("create.parent_section_title")}
            </div>
            {/* Owner request: Customer leads (left column), Building
                follows (right column). The customer-drives-building
                filtering, auto-select, and disabled/required logic are
                unchanged — only the visual order is swapped. */}
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-customer">
                  {t("create.field_customer")}
                </label>
                <select
                  id="ew-customer"
                  data-testid="extra-work-create-customer"
                  className="field-select"
                  value={form.customer}
                  onChange={(event) => update("customer", event.target.value)}
                  disabled={filteredCustomers.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("create.field_customer_placeholder")}
                  </option>
                  {filteredCustomers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ew-building">
                  {t("create.field_building")}
                </label>
                <select
                  id="ew-building"
                  data-testid="extra-work-create-building"
                  className="field-select"
                  value={form.building}
                  onChange={(event) => update("building", event.target.value)}
                  disabled={filteredBuildings.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("create.field_building_placeholder")}
                  </option>
                  {filteredBuildings.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="form-section">
            <div className="form-section-title">
              {t("create.what_section_title")}
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-category">
                  {t("create.field_category")}
                </label>
                <select
                  id="ew-category"
                  className="field-select"
                  value={form.category}
                  onChange={(event) =>
                    update("category", event.target.value as ExtraWorkCategory)
                  }
                >
                  {CATEGORY_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {t(CATEGORY_I18N_KEY[value])}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ew-urgency">
                  {t("create.field_urgency")}
                </label>
                <select
                  id="ew-urgency"
                  className="field-select"
                  value={form.urgency}
                  onChange={(event) =>
                    update("urgency", event.target.value as ExtraWorkUrgency)
                  }
                >
                  {URGENCY_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {t(URGENCY_I18N_KEY[value])}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {form.category === "OTHER" && (
              <div className="field">
                <label className="field-label" htmlFor="ew-category-other">
                  {t("create.field_category_other_text")}
                </label>
                <input
                  id="ew-category-other"
                  className="field-input"
                  type="text"
                  maxLength={128}
                  placeholder={t(
                    "create.field_category_other_text_placeholder",
                  )}
                  value={form.category_other_text}
                  onChange={(event) =>
                    update("category_other_text", event.target.value)
                  }
                  required
                />
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="ew-title">
                {t("create.field_title")}
              </label>
              <input
                id="ew-title"
                data-testid="extra-work-create-title"
                className="field-input"
                type="text"
                maxLength={255}
                placeholder={t("create.field_title_placeholder")}
                value={form.title}
                onChange={(event) => update("title", event.target.value)}
                required
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-description">
                {t("create.field_description")}
              </label>
              <textarea
                id="ew-description"
                data-testid="extra-work-create-description"
                className="field-textarea"
                placeholder={t("create.field_description_helper")}
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                required
              />
              <div
                className="muted small"
                style={{ marginTop: 6, lineHeight: 1.4 }}
              >
                {t("create.field_description_helper")}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-preferred-date">
                {t("create.field_preferred_date")}
              </label>
              <input
                id="ew-preferred-date"
                className="field-input"
                type="date"
                value={form.preferred_date}
                onChange={(event) =>
                  update("preferred_date", event.target.value)
                }
              />
            </div>
          </div>

          {/* ----- Cart ----- */}
          <div className="form-section" data-testid="extra-work-create-cart">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <div className="form-section-title" style={{ margin: 0 }}>
                {t("create.cart_section_title")}
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={addCartLine}
                data-testid="extra-work-create-add-line"
              >
                <Plus size={14} strokeWidth={2.2} />
                <span style={{ marginLeft: 6 }}>
                  {t("create.add_line_button")}
                </span>
              </button>
            </div>
            <div className="muted small" style={{ marginBottom: 12 }}>
              {t("create.cart_section_helper")}
            </div>

            {/* Sprint 5 — agreed contract prices shown UPFRONT so the
                customer knows which services have a pre-agreed price (and
                what it is) before adding any line. Sourced from
                GET /customers/<id>/pricing/ (customer-readable; backend
                returns only the customer's OWN currently-valid rows for
                customer-side actors). Provider rows are narrowed to
                active + in-window here for a consistent "current" view. */}
            {form.customer && (
              <details
                className="ew-agreed-prices"
                data-testid="extra-work-create-agreed-prices"
                open
              >
                <summary className="ew-agreed-prices-summary">
                  <span className="form-section-title" style={{ margin: 0 }}>
                    {t("create.prices.section_title")}
                  </span>
                  {!pricesLoading && agreedPrices.length > 0 && (
                    <span className="muted small">({agreedPrices.length})</span>
                  )}
                </summary>
                <div className="ew-agreed-prices-body">
                  {pricesLoading ? (
                    <div className="muted small">
                      {t("create.prices.loading")}
                    </div>
                  ) : agreedPrices.length === 0 ? (
                    <div
                      className="muted small"
                      data-testid="extra-work-create-agreed-prices-empty"
                    >
                      {t("create.prices.empty")}
                    </div>
                  ) : (
                    <>
                      <input
                        type="text"
                        className="field-input"
                        data-testid="extra-work-create-agreed-prices-search"
                        placeholder={t("create.prices.search_placeholder")}
                        value={priceSearch}
                        onChange={(event) => setPriceSearch(event.target.value)}
                      />
                      <div
                        className="ew-agreed-prices-list"
                        data-testid="extra-work-create-agreed-prices-list"
                      >
                        {filteredAgreedPrices.length === 0 ? (
                          <div
                            className="muted small"
                            style={{ padding: "8px 10px" }}
                          >
                            {t("create.prices.no_match")}
                          </div>
                        ) : (
                          filteredAgreedPrices.map((p) => {
                            const svc = serviceById.get(p.service);
                            const label = svc
                              ? svc.category_name
                                ? `${svc.category_name} — ${svc.name}`
                                : svc.name
                              : p.service_name;
                            const unitLabel = svc
                              ? t(UNIT_TYPE_I18N_KEY[svc.unit_type])
                              : "";
                            const inCart = cartLines.some(
                              (l) => Number(l.serviceId) === p.service,
                            );
                            return (
                              <button
                                type="button"
                                key={p.id}
                                className="ew-agreed-price-item"
                                data-testid="extra-work-create-agreed-price-item"
                                data-in-cart={inCart ? "true" : "false"}
                                disabled={inCart}
                                onClick={() => addServiceFromContract(p.service)}
                              >
                                <span className="ew-agreed-price-item-label">
                                  {label}
                                  {unitLabel && (
                                    <span className="muted small">
                                      {" · "}
                                      {unitLabel}
                                    </span>
                                  )}
                                </span>
                                <span className="ew-agreed-price-item-price">
                                  {formatMoney(p.unit_price)}
                                  <span className="muted small">
                                    {" · "}
                                    {formatNumber(p.vat_pct, {
                                      maximumFractionDigits: 2,
                                    })}
                                    %
                                  </span>
                                  {inCart && (
                                    <Check
                                      size={14}
                                      strokeWidth={2.5}
                                      aria-hidden
                                      style={{ marginLeft: 6 }}
                                    />
                                  )}
                                </span>
                              </button>
                            );
                          })
                        )}
                      </div>
                    </>
                  )}
                  <div className="muted small" style={{ marginTop: 8 }}>
                    {t("create.prices.helper")}
                  </div>
                </div>
              </details>
            )}

            {cartLines.length === 0 && (
              <div
                className="muted small"
                data-testid="extra-work-create-cart-empty"
              >
                {t("create.cart_empty")}
              </div>
            )}

            {cartLines.map((line, index) => (
              <div
                key={line.tempId}
                data-testid="extra-work-create-cart-line"
                className="ew-line-row ew-line-row-card"
              >
                <div
                  className="field ew-line-field-grow"
                  data-testid={`extra-work-create-cart-line-${index}`}
                >
                  <label
                    className="field-label"
                    htmlFor={`ew-line-service-${index}`}
                  >
                    {t("create.line_field_service")}
                  </label>
                  <select
                    id={`ew-line-service-${index}`}
                    data-testid={`extra-work-create-line-service-${index}`}
                    className="field-select"
                    value={line.serviceId}
                    onChange={(event) =>
                      updateCartLine(
                        line.tempId,
                        "serviceId",
                        event.target.value,
                      )
                    }
                    required
                  >
                    <option value="" disabled>
                      {t("create.line_field_service_placeholder")}
                    </option>
                    {services.map((svc) => {
                      const baseLabel = svc.category_name
                        ? `${svc.category_name} — ${svc.name}`
                        : svc.name;
                      return (
                        <option key={svc.id} value={svc.id}>
                          {`${baseLabel}${agreedPriceSuffix(svc.id)}`}
                        </option>
                      );
                    })}
                    {/* Custom line: no agreed-price suffix — it has no
                        catalog service to price against. Re-picking a
                        catalog service from this still-visible dropdown
                        switches back. */}
                    <option value={CUSTOM_SERVICE_VALUE}>
                      {t("create.line_custom_option")}
                    </option>
                  </select>
                  {line.serviceId === CUSTOM_SERVICE_VALUE && (
                    <input
                      data-testid={`extra-work-create-line-custom-${index}`}
                      className="field-input"
                      style={{ marginTop: 8 }}
                      type="text"
                      maxLength={255}
                      placeholder={t("create.line_custom_placeholder")}
                      value={line.customDescription}
                      onChange={(event) =>
                        updateCartLine(
                          line.tempId,
                          "customDescription",
                          event.target.value,
                        )
                      }
                      required
                    />
                  )}
                </div>
                <div className="field ew-line-field-compact">
                  <label
                    className="field-label"
                    htmlFor={`ew-line-quantity-${index}`}
                  >
                    {t("create.line_field_quantity")}
                  </label>
                  <input
                    id={`ew-line-quantity-${index}`}
                    data-testid={`extra-work-create-line-quantity-${index}`}
                    className="field-input"
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.quantity}
                    onChange={(event) =>
                      updateCartLine(
                        line.tempId,
                        "quantity",
                        event.target.value,
                      )
                    }
                    required
                  />
                </div>
                <div className="field ew-line-field-medium">
                  <label
                    className="field-label"
                    htmlFor={`ew-line-date-${index}`}
                  >
                    {t("create.line_field_requested_date")}
                  </label>
                  <input
                    id={`ew-line-date-${index}`}
                    data-testid={`extra-work-create-line-date-${index}`}
                    className="field-input"
                    type="date"
                    value={line.requestedDate}
                    onChange={(event) =>
                      updateCartLine(
                        line.tempId,
                        "requestedDate",
                        event.target.value,
                      )
                    }
                    required
                  />
                </div>
                <div className="field ew-line-field-grow">
                  <label
                    className="field-label"
                    htmlFor={`ew-line-note-${index}`}
                  >
                    {t("create.line_field_customer_note")}
                  </label>
                  <input
                    id={`ew-line-note-${index}`}
                    data-testid={`extra-work-create-line-note-${index}`}
                    className="field-input"
                    type="text"
                    maxLength={500}
                    placeholder={t(
                      "create.line_field_customer_note_placeholder",
                    )}
                    value={line.customerNote}
                    onChange={(event) =>
                      updateCartLine(
                        line.tempId,
                        "customerNote",
                        event.target.value,
                      )
                    }
                  />
                </div>
                <div className="ew-line-row-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => removeCartLine(line.tempId)}
                    data-testid={`extra-work-create-remove-line-${index}`}
                  >
                    <Trash2 size={14} strokeWidth={2.2} />
                    <span style={{ marginLeft: 6 }}>
                      {t("create.remove_line_button")}
                    </span>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* ----- Pricing preview + intent (Sprint 5, SoT §5.1–5.4) ----- */}
          {previewable && (
            <>
              <div
                className="form-section"
                data-testid="extra-work-create-preview"
              >
                <div className="form-section-title">
                  {t("create.preview.section_title")}
                </div>
                <div className="muted small" style={{ marginBottom: 12 }}>
                  {t("create.preview.helper")}
                </div>

                {previewLoading && (
                  <div
                    className="muted small"
                    role="status"
                    data-testid="extra-work-create-preview-loading"
                  >
                    {t("create.preview.loading")}
                  </div>
                )}

                {previewErrorMsg && (
                  <div
                    className="alert-warning"
                    role="status"
                    data-testid="extra-work-create-preview-unavailable"
                  >
                    {t("create.preview.unavailable")}
                  </div>
                )}

                {previewData && (
                  <div className="table-wrap">
                    <table
                      className="data-table ew-pricing-table"
                      data-testid="extra-work-create-preview-table"
                    >
                      <thead>
                        <tr>
                          <th>{t("create.preview.col_service")}</th>
                          <th>{t("create.preview.col_source")}</th>
                          <th>{t("create.preview.col_quantity")}</th>
                          <th>{t("create.preview.col_unit_price")}</th>
                          <th>{t("create.preview.col_vat_pct")}</th>
                          <th>{t("create.preview.col_line_total")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {previewData.lines.map((line) => {
                          const unit =
                            line.agreed_unit_price !== null
                              ? Number(line.agreed_unit_price)
                              : null;
                          const pct =
                            line.agreed_vat_pct !== null
                              ? Number(line.agreed_vat_pct)
                              : null;
                          const qty = Number(line.quantity);
                          const isAgreed =
                            line.price_source === "AGREED_CUSTOMER_PRICE" &&
                            unit !== null &&
                            Number.isFinite(unit);
                          const lineTotal =
                            isAgreed && unit !== null && Number.isFinite(qty)
                              ? qty * unit * (1 + (pct ?? 0) / 100)
                              : null;
                          const serviceLabel = line.service_category_name
                            ? `${line.service_category_name} — ${line.service_name}`
                            : line.service_name ||
                              line.custom_description ||
                              "—";
                          return (
                            <tr
                              key={line.index}
                              data-testid="extra-work-create-preview-row"
                              data-price-source={line.price_source}
                            >
                              <td>{serviceLabel}</td>
                              <td>
                                <span
                                  className={`invoice-line-row-source-tag invoice-line-row-source-${PREVIEW_SOURCE_TAG[line.price_source]}`}
                                  data-testid="extra-work-create-preview-source"
                                >
                                  {t(PREVIEW_SOURCE_KEY[line.price_source])}
                                </span>
                              </td>
                              <td>
                                {formatNumber(line.quantity, {
                                  maximumFractionDigits: 2,
                                })}
                              </td>
                              <td>{isAgreed ? formatMoney(unit) : "—"}</td>
                              <td>
                                {isAgreed && pct !== null
                                  ? `${formatNumber(pct, {
                                      maximumFractionDigits: 2,
                                    })}%`
                                  : "—"}
                              </td>
                              <td>
                                {isAgreed ? (
                                  formatMoney(lineTotal)
                                ) : (
                                  <span className="muted small">
                                    {t("create.preview.to_be_priced")}
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {previewData && previewTotals && (
                  <div
                    className="alert-info"
                    style={{ marginTop: 12 }}
                    data-testid="extra-work-create-preview-totals"
                  >
                    <div
                      className="form-section-title"
                      style={{ margin: 0 }}
                    >
                      {t("create.preview.totals_title")}
                    </div>
                    <div style={{ marginTop: 6 }}>
                      {t("create.preview.totals_subtotal")}:{" "}
                      {formatMoney(previewTotals.subtotal)} ·{" "}
                      {t("create.preview.totals_vat")}:{" "}
                      {formatMoney(previewTotals.vat)} ·{" "}
                      {t("create.preview.totals_total")}:{" "}
                      <strong>{formatMoney(previewTotals.total)}</strong>
                    </div>
                    {previewTotals.unpricedCount > 0 && (
                      <div className="muted small" style={{ marginTop: 6 }}>
                        {t("create.preview.totals_unpriced", {
                          count: previewTotals.unpricedCount,
                        })}
                      </div>
                    )}
                    <div className="muted small" style={{ marginTop: 6 }}>
                      {t("create.preview.totals_display_only")}
                    </div>
                  </div>
                )}
              </div>

              {/* M3 — quote page: NO intent picker. A pinned-intent
                  info row when the quote is available; the inline
                  non-blocking notice (with a link to the standard
                  flow) when every line already has an agreed price. */}
              {isQuoteMode && previewData && (
                <div
                  className="form-section"
                  data-testid="extra-work-quote-intent"
                >
                  {quoteAllowed ? (
                    <div
                      className="alert-info"
                      role="status"
                      data-testid="extra-work-quote-pinned"
                    >
                      <span
                        className="field-label"
                        style={{ display: "block", marginBottom: 2 }}
                      >
                        {t(INTENT_LABEL_KEY.REQUEST_QUOTE)}
                      </span>
                      <span className="muted small">
                        {t(INTENT_DESC_KEY.REQUEST_QUOTE)}
                      </span>
                    </div>
                  ) : (
                    <div
                      className="alert-info"
                      role="status"
                      data-testid="extra-work-quote-unavailable"
                    >
                      {t("quote.unavailable_notice")}{" "}
                      <Link to="/extra-work/new">
                        {t("quote.unavailable_link")}
                      </Link>
                    </div>
                  )}
                </div>
              )}

              {/* M3 — standard page: the picker renders the FILTERED
                  intent set (REQUEST_QUOTE removed). When the backend
                  would only allow a quote, nothing is offerable here
                  and the mirrored notice links to the quote page. */}
              {!isQuoteMode && standardOnlyQuote && (
                <div
                  className="form-section"
                  data-testid="extra-work-standard-quote-only"
                >
                  <div className="alert-info" role="status">
                    {t("create.quote_only_notice")}{" "}
                    <Link to="/extra-work/request-quote">
                      {t("create.quote_only_link")}
                    </Link>
                  </div>
                </div>
              )}
              {!isQuoteMode && previewData && offeredIntents.length > 0 && (
                <div
                  className="form-section"
                  data-testid="extra-work-create-intent"
                >
                  <div className="form-section-title">
                    {t("create.intent.section_title")}
                  </div>
                  <div className="muted small" style={{ marginBottom: 12 }}>
                    {t("create.intent.section_helper")}
                  </div>
                  <div
                    role="radiogroup"
                    aria-label={t("create.intent.section_title")}
                  >
                    {offeredIntents.map((intent) => (
                      <label
                        key={intent}
                        className="ew-intent-option"
                        data-testid={`extra-work-create-intent-${intent}`}
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "flex-start",
                          marginBottom: 10,
                          cursor: "pointer",
                        }}
                      >
                        <input
                          type="radio"
                          name="ew-request-intent"
                          value={intent}
                          checked={selectedIntent === intent}
                          onChange={() => setSelectedIntent(intent)}
                          style={{ marginTop: 3 }}
                        />
                        <span>
                          <span
                            className="field-label"
                            style={{ display: "block", marginBottom: 2 }}
                          >
                            {t(INTENT_LABEL_KEY[intent])}
                          </span>
                          <span className="muted small">
                            {t(INTENT_DESC_KEY[intent])}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                  {previewData.requested_intent === selectedIntent &&
                    previewData.requested_intent_allowed === false &&
                    previewData.requested_intent_error && (
                      <div
                        className="alert-warning"
                        style={{ marginTop: 8 }}
                        role="status"
                        data-testid="extra-work-create-intent-error"
                      >
                        {intentErrorText(previewData.requested_intent_error)}
                      </div>
                    )}
                </div>
              )}
            </>
          )}

          <div
            className="form-actions"
            style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}
          >
            <Link to="/extra-work" className="btn btn-secondary btn-sm">
              {t("create.cancel_button")}
            </Link>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              data-testid="extra-work-create-submit"
              disabled={
                submitting ||
                loadingOptions ||
                noOptions ||
                // M3 — quote page with no quotable line / standard page
                // with a quote-only cart: blocked here AND in
                // handleSubmit (the notice explains the way out).
                quoteUnavailable ||
                standardOnlyQuote
              }
            >
              {submitting
                ? t("create.submitting")
                : isQuoteMode
                  ? t("quote.submit_button")
                  : t("create.submit_button")}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
