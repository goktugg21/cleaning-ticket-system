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
import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronLeft, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";

import {
  listAllBuildings,
  listAllCustomers,
  listCustomerCustomPrices,
  listCustomerPriceFolders,
  listCustomerPrices,
  listServices,
} from "../api/admin";
import { getApiError } from "../api/client";
import { listLabels } from "../api/customerLabels";
import {
  batchCreateExtraWork,
  createExtraWork,
  getExtraWorkPreview,
} from "../api/extraWork";
import { SlotPicker } from "../components/extra-work/SlotPicker";
import type {
  Building,
  Customer,
  CustomerCustomPrice,
  CustomerLabel,
  CustomerPriceFolder,
  CustomerServicePrice,
  ExtraWorkBilledTo,
  ExtraWorkIntentErrorCode,
  ExtraWorkPreviewLine,
  ExtraWorkPreviewPriceSource,
  ExtraWorkPreviewResponse,
  ExtraWorkRequestDetail,
  ExtraWorkRequestIntent,
  ExtraWorkUrgency,
  Service,
  ServiceUnitType,
  ExtraWorkSlot,
} from "../api/types";
import { BoundedList } from "../components/BoundedList";
import { InvoiceLineRow } from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { formatMoney, formatNumber } from "../lib/intl";
import { customerLabelName } from "../lib/customerLabelName";


interface ParentFormState {
  building: string;
  customer: string;
  title: string;
  description: string;
  // Sprint 144 §1 — `category` / `category_other_text` are GONE from the
  // form. The operator classifies with `categoryFilter` (a catalog
  // category or a customer folder) instead; the enum column keeps its
  // `default=OTHER` server-side.
  urgency: ExtraWorkUrgency;
  preferred_date: string;
  planned_end_date: string;
  deadline: string;
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
  // W-EW1 §2 — a line no longer carries a date. The request-level
  // Preferred Date is the one date for the whole cart, and the server
  // stamps every line from it.
  customerNote: string;
}

// Sentinel serviceId for the "Custom…" option in the per-line service
// dropdown. A cart line is "custom" iff line.serviceId === this value.
// It is never a real service id (numeric), so it never collides with a
// catalog service or the agreed-price lookups.
const CUSTOM_SERVICE_VALUE = "__custom__";

/**
 * Sprint 137 item 6 — prefix for the "order a per-customer custom
 * price" options in the same per-line dropdown. `CustomerCustomPrice`
 * rows carry a name, a unit and an amount but deliberately have NO
 * `service` FK, so they could never be selected before: the owner
 * priced his customer's real work types through that path and was then
 * baffled they never appeared here.
 *
 * A prefixed string keeps ONE control (no second picker to keep in
 * sync) and can never collide with a numeric service id or with
 * CUSTOM_SERVICE_VALUE.
 */
const CUSTOM_PRICE_PREFIX = "custom-price:";

/**
 * W-EW2 §1 — one row of the combobox popover.
 *
 * A discriminated union rather than three parallel arrays: the
 * keyboard walks ONE list, so the thing Enter commits and the thing
 * the confirm button commits are the same value, and a new row kind
 * added here is a compile error at `commitAddRow` until it is handled.
 */
type AddRow =
  | { kind: "service"; id: number; key: string }
  | { kind: "custom_price"; id: number; key: string }
  | { kind: "custom_text"; key: string };

function customPriceValue(id: number): string {
  return `${CUSTOM_PRICE_PREFIX}${id}`;
}

/** The CustomerCustomPrice id a cart line orders, or null. */
function parseCustomPriceId(serviceId: string): number | null {
  if (!serviceId.startsWith(CUSTOM_PRICE_PREFIX)) return null;
  const parsed = Number(serviceId.slice(CUSTOM_PRICE_PREFIX.length));
  return Number.isFinite(parsed) ? parsed : null;
}

const EMPTY_PARENT: ParentFormState = {
  building: "",
  customer: "",
  title: "",
  description: "",
  urgency: "NORMAL",
  preferred_date: "",
  planned_end_date: "",
  deadline: "",
};

const URGENCY_VALUES: ExtraWorkUrgency[] = ["NORMAL", "HIGH", "URGENT"];

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
    customerNote: "",
  };
}

/**
 * W-EW2 §3 — can this ONE line be sent to the preview endpoint?
 *
 * Module scope on purpose: it is a pure function of its argument, and
 * a function re-created each render would have to be a dependency of
 * the memo that calls it.
 */
function isPreviewableLine(line: CartLineState): boolean {
  if (line.serviceId === CUSTOM_SERVICE_VALUE) {
    if (!line.customDescription.trim()) return false;
  } else if (!line.serviceId) {
    return false;
  }
  const q = Number(line.quantity);
  return Number.isFinite(q) && q > 0;
}

// Sprint 5 (frontend) — debounce window for the live preview re-fetch.
const PREVIEW_DEBOUNCE_MS = 350;

/**
 * W-EW1 §1c — whole days from today to `iso`, or null when `iso` is
 * empty or unparseable.
 *
 * Both ends are normalised to LOCAL midnight before subtracting, so the
 * answer is a count of calendar days and never drifts by one because the
 * page happened to be open in the evening. A deadline of tomorrow reads
 * 1 whether it is computed at 09:00 or at 23:30.
 */
function daysUntil(iso: string): number | null {
  if (!iso) return null;
  const parts = iso.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) {
    return null;
  }
  const [y, m, d] = parts;
  const target = new Date(y, m - 1, d);
  if (Number.isNaN(target.getTime())) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round(
    (target.getTime() - today.getTime()) / (24 * 60 * 60 * 1000),
  );
}

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
/**
 * Sprint 137 item 6 — the unit price + VAT a preview line is KNOWN to
 * carry, from whichever backend-provided channel supplied it:
 * `agreed_*` on an AGREED_CUSTOMER_PRICE line, `custom_price_*` on a
 * line ordered from a CustomerCustomPrice. Still zero client-side
 * inference — both numbers come from the backend, and `price_source`
 * is never second-guessed here.
 */
function knownLinePrice(
  line: ExtraWorkPreviewLine,
): { unit: number; vatPct: number } | null {
  const rawUnit =
    line.price_source === "AGREED_CUSTOMER_PRICE"
      ? line.agreed_unit_price
      : line.custom_price !== null
        ? line.custom_price_unit_price
        : null;
  if (rawUnit === null) return null;
  const unit = Number(rawUnit);
  if (!Number.isFinite(unit)) return null;
  const rawVat =
    line.price_source === "AGREED_CUSTOMER_PRICE"
      ? line.agreed_vat_pct
      : line.custom_price_vat_pct;
  const vatPct = rawVat !== null ? Number(rawVat) : 0;
  return { unit, vatPct: Number.isFinite(vatPct) ? vatPct : 0 };
}

function computeAgreedTotals(lines: ExtraWorkPreviewLine[]): AgreedTotals {
  let subtotal = 0;
  let vat = 0;
  let agreedCount = 0;
  let unpricedCount = 0;
  for (const line of lines) {
    const qty = Number(line.quantity);
    const known = knownLinePrice(line);
    const unit = known ? known.unit : null;
    if (known !== null && unit !== null && Number.isFinite(qty)) {
      const lineSubtotal = qty * unit;
      subtotal += lineSubtotal;
      vat += lineSubtotal * (known.vatPct / 100);
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
  const { me } = useAuth();
  // Sprint 147 — a customer sees ONLY the services they have an agreed
  // price for (see `catalogForActor`).
  const isCustomerActor = me?.role === "CUSTOMER_USER";
  const isQuoteMode = intentMode === "quote";

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  // W5-B — SINGLE or MULTIPLE, the reference system's "entry mode".
  //
  // In MULTIPLE the title becomes a STANDARD title and every picked day
  // creates its own real Extra Work, sharing customer, building,
  // description, labels and cart. The whole form below is unchanged in
  // either mode — that is the point: a member is created by the same
  // payload and the same serializer as a single work, so the two paths
  // cannot drift apart the way the reference system's did.
  const [entryMode, setEntryMode] = useState<"SINGLE" | "MULTIPLE">("SINGLE");
  const [slots, setSlots] = useState<ExtraWorkSlot[]>([]);
  const [batchResult, setBatchResult] = useState<{
    group: { id: number; standard_title: string };
    created: number;
  } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Sprint 29 Batch 29.8.5 — soft warning channel used when the service
  // catalog endpoint succeeds but is empty, OR when it errors. Either
  // case still lets the form render (buildings + customers carry the
  // hard scope contract); without a service the user cannot submit
  // the cart, but the dropdowns still appear so they can see what they
  // would normally pick from.
  // Sprint 147 — the KIND of catalog problem, not its wording. The
  // load effect classifies; the message is chosen at render, where the
  // actor's role is already in scope. Keeping the role out of the
  // effect keeps its dep array honest — pulling `isCustomerActor` in
  // would re-run the whole mount-time load when `me` resolves.
  const [catalogWarningKind, setCatalogWarningKind] = useState<
    "" | "empty" | "unavailable"
  >("");
  const [form, setForm] = useState<ParentFormState>(EMPTY_PARENT);
  /**
   * W-EW2 §1 — THE CART STARTS EMPTY.
   *
   * It used to start with one BLANK line, and the "Add service line"
   * button appended more of them. A blank line is a line with no
   * service and no text, which is exactly what `previewable` below
   * refuses — and `previewable` is a whole-cart gate, so one blank row
   * used to silence the prices of every finished row beside it. That
   * is the dash-instead-of-€31.48 the owner photographed.
   *
   * Nothing appends a blank line any more: the combobox below the
   * table adds a line that is already complete, or adds nothing.
   */
  const [cartLines, setCartLines] = useState<CartLineState[]>([]);

  // W-EW1 §1b — which of the two derived dates the user has taken over.
  //
  // Preferred Date fills Planned End and Deadline so the common case
  // ("all on one day") costs one keystroke instead of three. The moment
  // the user types in one of them it is THEIRS: a later change to
  // Preferred Date must never silently overwrite a date somebody chose
  // on purpose. One flag per field, set on that field's own onChange,
  // never cleared — taking a field over is not something you undo by
  // emptying it.
  const [dateTakenOver, setDateTakenOver] = useState<{
    plannedEnd: boolean;
    deadline: boolean;
  }>({ plannedEnd: false, deadline: false });

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
  // Sprint 137 item 6 — the customer's orderable CUSTOM price lines.
  // Tagged with customerId like the contract rows above so a stale
  // list is never offered. The endpoint is provider-only
  // (backend/extra_work/views_pricing.py::CustomerCustomPriceListCreateView
  // is gated on IsSuperAdminOrCompanyAdmin), so a customer-side actor
  // gets a 403 and simply sees no custom-price options — the same
  // graceful degradation the contract-price fetch already uses.
  const [customCustomPrices, setCustomCustomPrices] = useState<{
    customerId: number;
    rows: CustomerCustomPrice[];
  } | null>(null);
  // Sprint 128 — the selected customer's active Department / Work Type lists
  // for the two optional pickers. Tagged with customerId so a stale list from
  // the previously chosen customer is never shown, and the selection is
  // cleared on customer change so a stale id can never reach the payload.
  const [labelLists, setLabelLists] = useState<{
    customerId: number;
    departments: CustomerLabel[];
    workTypes: CustomerLabel[];
  } | null>(null);
  const [departmentId, setDepartmentId] = useState("");
  const [workTypeId, setWorkTypeId] = useState("");
  // W-E §2 — which invoice this work lands on. `""` is the DEFAULT and
  // is a real answer, not an empty one: it posts null, which the server
  // reads as "follow this customer's own invoicing setting"
  // (`invoicing/billing_target.py`). Seeding it to BUILDING, as this
  // form did, wrote a per-building override onto every extra work an
  // operator created without looking — overruling the setting of every
  // customer who is invoiced at organisation level. Sprint 182 §6 had
  // already removed that default server-side and migration 0032 nulled
  // the whole table; the form was the last place still writing it.
  /* W12 — the user's EXPLICIT pick, or null for "did not touch it".
     Not the value that gets posted: see `billedToPayload` below. The
     two are different on purpose, because "I left it alone" and "I
     chose the same thing the customer already has" must not both pin
     the job to a value the customer can no longer move. */
  const [billedTo, setBilledTo] = useState<ExtraWorkBilledTo | null>(null);
  // W13 — what the requester wants to see before this may be called
  // done. Off by default: asking for proof is a decision.
  const [requirePhoto, setRequirePhoto] = useState(false);
  const [requireNote, setRequireNote] = useState(false);
  // Search filter for the agreed-prices dropdown (scales to long
  // contract lists — the list scrolls and filters rather than dumping
  // every row inline).
  const [priceSearch, setPriceSearch] = useState("");

  // Sprint 137 item 5 — REAL service-catalog category filter over the
  // cart's service pickers. Note this is a different axis from the
  // `category` field on the request itself (`ExtraWorkCategory`, the
  // fixed DEEP_CLEANING/WINDOW_CLEANING/... enum): that classifies the
  // REQUEST, this narrows the CATALOG. They were always two unrelated
  // things; the form now says so instead of implying one.
  //
  // "" is "All categories" and is the DEFAULT — filtering is opt-in,
  // per the hard requirement that there is never a loop where a
  // service cannot be found.
  // Sprint 143 §4 — the value is PREFIXED so one control can offer two
  // different kinds of grouping without their ids colliding:
  //   ""          = no filter
  //   "cat:<id>"  = a company `ServiceCategory`
  //   "fol:<id>"  = this customer's `CustomerPriceFolder`
  const [categoryFilter, setCategoryFilter] = useState("");
  // The chosen customer's folders, tagged with the customer id so a set
  // fetched for a previously chosen customer is never offered against
  // the current one (same guard shape as `labelLists`).
  const [customerFolders, setCustomerFolders] = useState<{
    customerId: number;
    rows: CustomerPriceFolder[];
  } | null>(null);
  /**
   * W-EW2 §1 — THE ONE CONTROL THAT ADDS A LINE.
   *
   * `addQuery` is what is typed in the combobox that sits as the last
   * row of the pricing table. It filters the customer's agreed-price
   * services live, and when it matches nothing it becomes the text of
   * a custom line.
   *
   * `addOpen` is whether the popover is showing. It is a popover
   * ATTACHED to the input, not a block under the table: the block was
   * the clutter the owner asked us to remove.
   *
   * `addHighlight` is the index into `addRows` that Enter and the
   * confirm button commit. Clamped on every render against the current
   * row count, so a shrinking result list can never leave it pointing
   * past the end.
   */
  const [addQuery, setAddQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addHighlight, setAddHighlight] = useState(0);

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
          listAllBuildings(),
          listAllCustomers(),
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

      const buildingResults = buildingResult.value;
      const customerResults = customerResult.value;
      setBuildings(buildingResults);
      setCustomers(customerResults);

      // Soft-required: services.
      if (servicesResult.status === "fulfilled") {
        setServices(servicesResult.value);
        if (servicesResult.value.length === 0) {
          setCatalogWarningKind("empty");
        }
      } else {
        setServices([]);
        setCatalogWarningKind("unavailable");
      }

      // Sprint 143 §1 — NOTHING is pre-selected here any more.
      //
      // This block used to default `building` to the first building and
      // then `customer` to the one customer linked to it. Together with
      // the two effects below (now gone) that made the customer field
      // effectively read-only: a building was always set, so the customer
      // list was always filtered to that building, and any attempt to
      // pick another customer was snapped straight back. The operator
      // could only ever create Extra Work for B Amsterdam.
      //
      // Customer is the PRIMARY choice and building follows from it, so
      // there is nothing sensible to pre-select: guessing the building
      // first is what inverted the relationship in the first place.
      setLoadingOptions(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  // Sprint 143 §1 — CUSTOMER IS THE PRIMARY CHOICE. Every customer the
  // operator has access to is always offerable; the building list is what
  // narrows, from the customer, never the other way round.
  //
  // What this replaces: `filteredCustomers` used to be the customers
  // linked to `form.building`, and two effects kept `form.customer`
  // pinned inside that list — one auto-selecting the sole match, one
  // snapping any other choice back to `filteredCustomers[0]`. With a
  // building pre-selected on load the customer field was unusable: pick
  // anyone else and the effect immediately undid it. Reported as a
  // regression that had been fixed once before, which is exactly what a
  // setState-in-an-effect resync invites — it re-creates itself the
  // moment anyone touches the filter it depends on.
  //
  // Both effects are DERIVED away rather than reordered. CLAUDE.md bans
  // a synchronous setState in an effect body, and the ban is the point
  // here: the "stale" value is not state to be corrected, it is a
  // selection that no longer applies, so it collapses to "" at the point
  // of use and the operator picks again. Same pattern the department /
  // work-type fields below already use (`effectiveDepartmentId`).
  const selectableCustomers = customers;

  // W-E §2 — the two names the billing choice is ABOUT. The choice is
  // between two invoice documents, so the options name the documents:
  // "the invoice for B1 Amsterdam" and "one invoice for Acme B.V." are
  // a choice a reader can make; "Building" and "Customer" are a glossary
  // they have to have read first.
  const chosenCustomer = useMemo(
    () => customers.find((c) => String(c.id) === form.customer) ?? null,
    [customers, form.customer],
  );

  /* W12 — what the customer's own setting resolves to, and therefore
     what happens if nobody touches the control.

     `invoice_billing_target` is NOT NULL on `Customer` with a CUSTOMER
     default, so a customer always HAS a setting; the optional `?` on the
     type is about whether this response carried it, not about whether
     one exists. When it did not arrive we fall back to the same CUSTOMER
     the model defaults to, so the screen and the server agree. */
  const resolvedBilledTo: ExtraWorkBilledTo =
    chosenCustomer?.invoice_billing_target === "BUILDING"
      ? "BUILDING"
      : "CUSTOMER";
  /** The radio that is on. Untouched shows the customer's own answer. */
  const selectedBilledTo: ExtraWorkBilledTo = billedTo ?? resolvedBilledTo;
  /** What is POSTED. Matching the customer stores NULL, so a customer
     who later changes their setting moves every job that never
     disagreed with them. Only a divergence is written down. */
  const billedToPayload: ExtraWorkBilledTo | null =
    selectedBilledTo === resolvedBilledTo ? null : selectedBilledTo;

  const chosenBuilding = useMemo(
    () => buildings.find((b) => String(b.id) === form.building) ?? null,
    [buildings, form.building],
  );

  const filteredBuildings = useMemo(() => {
    if (!form.customer) return buildings;
    const c = customers.find((x) => String(x.id) === form.customer);
    if (!c) return buildings;
    return buildings.filter((b) => customerMatchesBuilding(c, b.id));
  }, [buildings, customers, form.customer]);

  // A building chosen before the customer changed may not belong to the
  // new customer. It collapses to "" — the select falls back to its
  // placeholder and `previewable` / submit already require a building,
  // so nothing downstream can consume the stale id.
  const effectiveBuilding = filteredBuildings.some(
    (b) => String(b.id) === form.building,
  )
    ? form.building
    : "";

  // Sprint 128 — the label lists to OFFER right now, guarded inline (so TS
  // narrows `labelLists` and a list fetched for a previously selected
  // customer is never shown against the current one).
  const currentDepartments =
    labelLists && String(labelLists.customerId) === form.customer
      ? labelLists.departments
      : [];
  const currentWorkTypes =
    labelLists && String(labelLists.customerId) === form.customer
      ? labelLists.workTypes
      : [];
  // Neutralise a stale selection (from a previously chosen customer) without
  // a setState-in-effect: an id not in the current customer's active list
  // collapses to "" for both the dropdown value and the payload.
  // Sprint 186 — both are REQUIRED now, so an id that does not belong to
  // the current customer falls back to that customer's FIRST label
  // rather than to "". Every customer is seeded one of each when it is
  // created, so the fallback always exists; "" would render a blank
  // select on a field that cannot be left blank.
  const effectiveDepartmentId = currentDepartments.some(
    (d) => String(d.id) === departmentId,
  )
    ? departmentId
    : currentDepartments.length > 0
      ? String(currentDepartments[0].id)
      : "";
  const effectiveWorkTypeId = currentWorkTypes.some(
    (w) => String(w.id) === workTypeId,
  )
    ? workTypeId
    : currentWorkTypes.length > 0
      ? String(currentWorkTypes[0].id)
      : "";

  /**
   * W-EW2 §3 — ONE LINE'S PRICE IS ONE LINE'S BUSINESS.
   *
   * A line can be sent to the preview endpoint when it names a catalog
   * service, orders a custom price, or is a custom line with non-empty
   * text — and carries a quantity above zero. That is exactly what the
   * preview serializer requires of it.
   *
   * This USED to be folded into a whole-cart `cartLines.every(...)`
   * gate. It was the bug: `previewData` went null the moment ANY row
   * failed, and the render below reads the priced columns off
   * `previewData`, so one unfinished row printed "—" and "to be priced
   * by the provider" across every finished row in the table — agreed
   * prices included. Two ordinary actions reached it: adding a second
   * line (the old button appended a BLANK one), and clearing a
   * quantity field to retype it.
   *
   * Now the incomplete rows are simply left out of the request, and
   * the complete ones are priced regardless of what sits beside them.
   */
  /** The cart lines worth pricing, IN CART ORDER. The server answers
   *  positionally, so position i of this array is position i of
   *  `previewData.lines` — which is what lets the render below match a
   *  row to its price by tempId instead of by raw cart index. */
  const previewableLines = useMemo(
    () => cartLines.filter(isPreviewableLine),
    [cartLines],
  );

  const previewable =
    !!effectiveBuilding && !!form.customer && previewableLines.length > 0;

  // W-EW1 §1c — the deadline chip's value. `null` (render nothing)
  // whenever there is no deadline to count down to.
  const deadlineDaysLeft = useMemo(
    () => daysUntil(form.deadline),
    [form.deadline],
  );

  // Stable signature of ONLY the pricing-relevant fields (note text is
  // excluded so editing a note never re-fetches). `null` when the cart
  // is not previewable. The effect re-fetches exactly when this value
  // changes; the payload is reconstructed by parsing it, so the effect
  // reads no other reactive cart state.
  const previewKey = useMemo(() => {
    if (!previewable) return null;
    return JSON.stringify({
      b: Number(effectiveBuilding),
      c: Number(form.customer),
      // W-EW1 §2 — the cart's one date is pricing-relevant (it picks
      // the agreed-price window), so it belongs in the signature:
      // changing it must re-fetch.
      pd: form.preferred_date || null,
      // W-EW2 §3 — only the lines that can be priced, and each one
      // carries its `tempId` so the answer can be matched back to the
      // row it belongs to rather than to a cart position that the
      // skipped rows have already shifted.
      l: previewableLines.map((line) => {
        const isCustom = line.serviceId === CUSTOM_SERVICE_VALUE;
        const customPriceId = parseCustomPriceId(line.serviceId);
        return {
          t: line.tempId,
          s: isCustom || customPriceId !== null ? null : Number(line.serviceId),
          c: isCustom ? line.customDescription.trim() : null,
          // Sprint 137 item 6 — a custom-price line's identity is the
          // price row id; it belongs in the signature so changing the
          // ordered price re-fetches the preview.
          p: customPriceId,
          q: line.quantity,
        };
      }),
    });
  }, [
    previewable,
    effectiveBuilding,
    form.customer,
    form.preferred_date,
    previewableLines,
  ]);

  // Debounced live preview. All state writes happen inside the timer's
  // async callback (deferred), never synchronously in the effect body.
  useEffect(() => {
    if (!previewKey) return;
    const parsed = JSON.parse(previewKey) as {
      b: number;
      c: number;
      pd: string | null;
      l: {
        t: string;
        s: number | null;
        c: string | null;
        p: number | null;
        q: string;
      }[];
    };
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const data = await getExtraWorkPreview({
            building: parsed.b,
            customer: parsed.c,
            request_intent: selectedIntent ?? undefined,
            // W-EW1 §2 — the cart's one date. The backend stamps every
            // line from it and prices on it, so sending it here is what
            // keeps the previewed amount equal to the amount create
            // will store.
            preferred_date: parsed.pd ?? undefined,
            // Catalog lines send `service`; free-text lines send
            // `custom_description`; Sprint 137 item 6 custom-price
            // lines send `custom_price`. Exactly one of the three per
            // line — the preview serializer enforces the same rule.
            line_items: parsed.l.map((line) => {
              if (line.p !== null) {
                return { custom_price: line.p, quantity: line.q };
              }
              return line.c !== null
                ? { custom_description: line.c, quantity: line.q }
                : { service: line.s ?? undefined, quantity: line.q };
            }),
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

  // Sprint 137 item 6 — load the customer's orderable custom prices.
  // Same shape as the contract-price effect above (writes deferred into
  // the promise resolution, never in the effect body). A 403 for a
  // customer-side actor degrades to an empty list rather than an error.
  useEffect(() => {
    const customerId = form.customer ? Number(form.customer) : null;
    if (!customerId) return;
    let cancelled = false;
    listCustomerCustomPrices(customerId)
      .then((rows) => {
        if (!cancelled) setCustomCustomPrices({ customerId, rows });
      })
      .catch(() => {
        if (!cancelled) setCustomCustomPrices({ customerId, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [form.customer]);

  // Sprint 143 §4 — the chosen customer's ACTIVE folders. Load-only, no
  // setState in the effect body; a stale set is neutralised by the
  // customer-id tag when it is read. A 403 (customer-side actor)
  // degrades to an empty list: the company categories still stand, so
  // the picker is never left with nothing.
  useEffect(() => {
    const customerId = form.customer ? Number(form.customer) : null;
    if (!customerId) return;
    let cancelled = false;
    listCustomerPriceFolders(customerId, { is_active: true })
      .then((rows) => {
        if (!cancelled) setCustomerFolders({ customerId, rows });
      })
      .catch(() => {
        if (!cancelled) setCustomerFolders({ customerId, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [form.customer]);

  // Sprint 128 — (re)load the per-customer Department / Work Type picker
  // lists when the customer changes (only active labels). This effect is
  // LOAD-ONLY (no synchronous setState — CLAUDE.md §3): a stale selection is
  // neutralised by the `effectiveDepartmentId` / `effectiveWorkTypeId`
  // derivations below (they collapse to "" unless the id belongs to the
  // currently-loaded customer), so a department from a previously selected
  // customer can never reach the dropdown value OR the payload.
  useEffect(() => {
    const customerId = form.customer ? Number(form.customer) : null;
    if (!customerId) return;
    let cancelled = false;
    Promise.all([
      listLabels(customerId, "department", { is_active: true }),
      listLabels(customerId, "work_type", { is_active: true }),
    ])
      .then(([departments, workTypes]) => {
        if (!cancelled) setLabelLists({ customerId, departments, workTypes });
      })
      .catch(() => {
        if (!cancelled) {
          setLabelLists({ customerId, departments: [], workTypes: [] });
        }
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

  /**
   * W-EW2 §3 — each cart row's own priced answer, BY IDENTITY.
   *
   * The render used to read `previewData.lines[index]` with `index`
   * taken from the cart. That was only ever correct while every cart
   * row was sent; now the unfinished ones are skipped, so a raw cart
   * index would point at another row's money.
   *
   * `previewData` is non-null only while `preview.key === previewKey`,
   * and `previewKey` is built from THIS `previewableLines` array, so
   * position i here is position i there. That invariant is what makes
   * the pairing below safe — and it is stated in one place instead of
   * being assumed at the call site.
   */
  const previewByTempId = useMemo(() => {
    const map = new Map<string, ExtraWorkPreviewLine>();
    if (!previewData) return map;
    previewableLines.forEach((line, i) => {
      const row = previewData.lines[i];
      if (row) map.set(line.tempId, row);
    });
    return map;
  }, [previewData, previewableLines]);

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
  // Sprint 137 item 6 — the custom prices that are orderable RIGHT NOW:
  // active and inside their validity window, exactly the rule the
  // backend re-enforces in `_validate_custom_price_orderable`. Offering
  // an archived or expired row would only produce a 400 on submit.
  const orderableCustomPrices = useMemo(() => {
    if (
      customCustomPrices === null ||
      !form.customer ||
      customCustomPrices.customerId !== Number(form.customer)
    ) {
      return [] as CustomerCustomPrice[];
    }
    const today = todayISO();
    return customCustomPrices.rows
      .filter(
        (p) =>
          p.is_active &&
          p.valid_from <= today &&
          (p.valid_to === null || p.valid_to >= today),
      )
      .sort((a, b) => a.custom_name.localeCompare(b.custom_name));
  }, [customCustomPrices, form.customer]);

  // The unit a custom price is quoted in — its operator-supplied label
  // for OTHER, the translated unit type otherwise. Mirrors
  // CustomerPricingPage.resolveUnitLabel.
  const customPriceUnitLabel = (price: CustomerCustomPrice): string => {
    if (price.unit_type === "OTHER" && price.custom_unit_label) {
      return price.custom_unit_label;
    }
    return t(UNIT_TYPE_I18N_KEY[price.unit_type]);
  };

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
    return unitLabel ? ` — ${money} / ${unitLabel}` : ` — ${money}`;
  };

  // Sprint 145 — the Category control offers ONE thing: the categories
  // that belong to the SELECTED CUSTOMER. Nothing before a customer is
  // chosen (the select is disabled with a note saying so).
  //
  // It used to also offer the provider's own catalog groupings in a
  // "your company's categories" group. That was wrong twice over: the
  // owner never asked for it, and it put the provider's whole catalog
  // in front of a CUSTOMER_USER — Amanda saw categories that have
  // nothing to do with her customer.
  //
  // Nothing becomes unreachable: "All categories" is still the default
  // and still shows the entire orderable catalog, so a service with no
  // agreed price for this customer can still be ordered — which is what
  // routes the request into the proposal flow (`resolve_price` has no
  // fallback to a company default).
  //
  // ARCHIVED categories are excluded: the form offers only what can be
  // ordered now.

  // Guarded inline so TS narrows and a folder set fetched for a
  // previously chosen customer is never shown against the current one.
  const currentFolders =
    customerFolders && String(customerFolders.customerId) === form.customer
      ? customerFolders.rows.filter((f) => f.is_active)
      : [];

  // Which service ids each folder holds a price row for. Contract rows
  // only — a `CustomerCustomPrice` has no `service` FK by construction,
  // so it cannot narrow a catalog picker.
  const serviceIdsByFolder = useMemo(() => {
    const map = new Map<number, Set<number>>();
    const rows =
      customerPrices && String(customerPrices.customerId) === form.customer
        ? customerPrices.rows
        : [];
    for (const row of rows) {
      if (row.folder === null) continue;
      const bucket = map.get(row.folder);
      if (bucket) bucket.add(row.service);
      else map.set(row.folder, new Set([row.service]));
    }
    return map;
  }, [customerPrices, form.customer]);

  // Sprint 147 — what a CUSTOMER may pick from.
  //
  // Owner's rule: a customer sees ONLY the services a price has been
  // agreed with them for, and those are the ones they can put in the
  // cart. The rest of the provider's catalog is not theirs to browse.
  //
  // This does not close the door on asking for something new — the
  // free-text custom line is still open to them, and a custom line is
  // what routes the request into the pricing-proposal flow. So the
  // proposal path survives; it is just reached by writing what you want
  // rather than by shopping in someone else's catalog.
  //
  // Applied upstream of BOTH the category filter and the search, so a
  // customer cannot reach past it by typing a name.
  const catalogForActor = useMemo(() => {
    // A service with no agreed price for THIS customer is not orderable:
    // it has no price to order at. The provider used to see the whole
    // catalog here, so a customer with no price list at all still showed
    // a full dropdown of things that could not be ordered -- the owner
    // hit exactly that on City Office Rotterdam.
    //
    // NO exception, not even in quote mode, and the owner was explicit
    // about why: a customer must never be shown something that was not
    // entered for them. Either there is an agreement with a price, or
    // the line is written as Custom -- which is exactly what the Custom
    // option at the bottom of this picker is for, and what carries an
    // unpriced request into the proposal flow.
    //
    // The SAME rule applies to the provider and the super admin. Two
    // different catalogs for two audiences is how the two of them end up
    // discussing different lists on one phone call.
    return services.filter((svc) => agreedPriceByServiceId.has(svc.id));
  }, [services, agreedPriceByServiceId]);

  /**
   * W-EW2 §1 — WHAT THE COMBOBOX OFFERS RIGHT NOW.
   *
   * One list, in the order it is read: the customer's agreed-price
   * services, then their orderable custom prices, then — only when
   * something has been typed — the row that turns that text into a
   * custom line.
   *
   * Matching is a substring of "<category> <name>", the same rule the
   * old search row used, so typing "e" finds every service with an e
   * in its name OR its category and typing "win" finds Window
   * cleaning. Empty box: everything is offered, because the box is
   * permanently visible and opening it must show what there is.
   *
   * Lines already in the cart are still listed but marked, rather than
   * hidden: a list that silently shrinks as you use it is harder to
   * search than one that does not.
   */
  const addRows = useMemo((): AddRow[] => {
    const q = addQuery.trim().toLowerCase();
    const matches = (haystack: string) =>
      !q || haystack.toLowerCase().includes(q);
    const rows: AddRow[] = [];
    for (const svc of catalogForActor) {
      if (!matches(`${svc.category_name ?? ""} ${svc.name}`)) continue;
      rows.push({ kind: "service", id: svc.id, key: `svc-${svc.id}` });
    }
    for (const price of orderableCustomPrices) {
      if (!matches(price.custom_name)) continue;
      rows.push({
        kind: "custom_price",
        id: price.id,
        key: `cp-${price.id}`,
      });
    }
    if (q) rows.push({ kind: "custom_text", key: "custom-text" });
    return rows;
  }, [addQuery, catalogForActor, orderableCustomPrices]);

  /* A shrinking result list must not leave the highlight pointing past
     the end — Enter would then commit nothing and read as a dead key.
     Clamped at render rather than in an effect: it is derived state,
     and `setState` from an effect body is what the lint baseline
     forbids. */
  const addIndex = addRows.length === 0
    ? -1
    : Math.min(addHighlight, addRows.length - 1);
  const addRowInCart = (row: AddRow): boolean =>
    row.kind === "service"
      ? cartLines.some((l) => Number(l.serviceId) === row.id)
      : row.kind === "custom_price"
        ? cartLines.some((l) => l.serviceId === customPriceValue(row.id))
        : false;

  // Sprint 145 — the agreed-prices browse panel obeys the SAME category
  // choice as the service pickers. Picking a category and still being
  // shown every agreed price underneath it is the "the screen
  // contradicts itself" defect this series keeps removing.
  //
  // Defined here, below `serviceIdsByFolder`, because it reads it: a
  // `const` is in the temporal dead zone until its own initialiser
  // runs, so this cannot live further up the component.
  //
  // Search still wins over the category filter, exactly as it does for
  // the service pickers, so a price the operator types the name of is
  // never hidden by a filter they forgot was on.
  const filteredAgreedPrices = useMemo(() => {
    const q = priceSearch.trim().toLowerCase();
    if (q) {
      return agreedPrices.filter((p) => {
        const svc = serviceById.get(p.service);
        const label = svc
          ? `${svc.category_name} ${svc.name}`
          : p.service_name;
        return label.toLowerCase().includes(q);
      });
    }
    if (!categoryFilter) return agreedPrices;
    if (categoryFilter.startsWith("fol:")) {
      const ids = serviceIdsByFolder.get(Number(categoryFilter.slice(4)));
      if (!ids) return [];
      return agreedPrices.filter((p) => ids.has(p.service));
    }
    if (categoryFilter.startsWith("cat:")) {
      const id = Number(categoryFilter.slice(4));
      return agreedPrices.filter(
        (p) => serviceById.get(p.service)?.category === id,
      );
    }
    return agreedPrices;
  }, [
    agreedPrices,
    priceSearch,
    serviceById,
    categoryFilter,
    serviceIdsByFolder,
  ]);

  /**
   * True when a cart line orders a custom price that is NOT on the
   * currently-selected customer's orderable list — the customer was
   * switched (or the row archived) after the line was added. The line
   * is kept, labelled and blocked at submit rather than silently reset:
   * quietly emptying a line the user added is the failure mode this
   * sprint keeps finding.
   */
  function staleCustomPriceLine(line: CartLineState): boolean {
    const customPriceId = parseCustomPriceId(line.serviceId);
    if (customPriceId === null) return false;
    return !orderableCustomPrices.some((p) => p.id === customPriceId);
  }

  function update<K extends keyof ParentFormState>(
    name: K,
    value: ParentFormState[K],
  ) {
    setForm((current) => ({ ...current, [name]: value }));
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

  // Sprint 137 item 6 — mirror of addServiceFromContract for a custom
  // price: fill the first empty line, else append. No-op when the price
  // is already in the cart (submit rejects duplicates).
  function addCustomPriceToCart(customPriceId: number) {
    const value = customPriceValue(customPriceId);
    setCartLines((current) => {
      if (current.some((l) => l.serviceId === value)) {
        return current;
      }
      const emptyIdx = current.findIndex((l) => !l.serviceId);
      if (emptyIdx >= 0) {
        return current.map((l, i) =>
          i === emptyIdx ? { ...l, serviceId: value } : l,
        );
      }
      return [...current, { ...emptyCartLine(), serviceId: value }];
    });
  }

  /**
   * W-EW2 §1 — COMMITTING THE COMBOBOX.
   *
   * Every one of these appends a line that is ALREADY COMPLETE. That
   * is the whole discipline: there is no longer any way for this page
   * to put a half-finished row in the cart, which is what used to take
   * the prices off every other row (see §3 on `previewableLines`).
   *
   * The box is then cleared and left focused, so the next line is
   * typed without reaching for anything.
   */
  function resetAddBox() {
    setAddQuery("");
    setAddHighlight(0);
    setAddOpen(false);
  }

  function addServiceLine(serviceId: number) {
    setCartLines((current) =>
      current.some((l) => Number(l.serviceId) === serviceId)
        ? current
        : [...current, { ...emptyCartLine(), serviceId: String(serviceId) }],
    );
    resetAddBox();
  }

  function addCustomPriceLine(customPriceId: number) {
    const value = customPriceValue(customPriceId);
    setCartLines((current) =>
      current.some((l) => l.serviceId === value)
        ? current
        : [...current, { ...emptyCartLine(), serviceId: value }],
    );
    resetAddBox();
  }

  /** The typed text becomes a custom line. Trimmed here, so a line can
   *  never enter the cart holding only spaces — which would be an
   *  unpreviewable row, the very thing §3 is about. */
  function addCustomTextLine(text: string) {
    const description = text.trim();
    if (!description) return;
    setCartLines((current) => [
      ...current,
      {
        ...emptyCartLine(),
        serviceId: CUSTOM_SERVICE_VALUE,
        customDescription: description,
      },
    ]);
    resetAddBox();
  }

  /** Commit whichever popover row is highlighted. Shared by Enter, by
   *  a click, and by the confirm button, so the three can never mean
   *  three different things. */
  function commitAddRow(row: AddRow | undefined) {
    if (!row) return;
    if (row.kind === "service") addServiceLine(row.id);
    else if (row.kind === "custom_price") addCustomPriceLine(row.id);
    else addCustomTextLine(addQuery);
  }

  /** What a cart line's service cell reads as before it is priced. */
  function cartLineLabel(line: CartLineState): string {
    if (line.serviceId === CUSTOM_SERVICE_VALUE) {
      return t("create.line_custom_option");
    }
    const customPriceId = parseCustomPriceId(line.serviceId);
    if (customPriceId !== null) {
      const price = orderableCustomPrices.find((p) => p.id === customPriceId);
      return price
        ? price.custom_name
        : t("create.line_custom_price_unavailable");
    }
    if (!line.serviceId) return t("create.line_field_service_placeholder");
    const svc = services.find((s) => s.id === Number(line.serviceId));
    if (!svc) return t("create.line_field_service_placeholder");
    return svc.category_name
      ? `${svc.category_name} — ${svc.name}`
      : svc.name;
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
    if (entryMode === "MULTIPLE" && slots.length === 0) {
      setError(t("series.slot_none"));
      return;
    }
    if (!form.title.trim()) {
      setError(t("create.error_title_required"));
      return;
    }
    if (!form.description.trim()) {
      setError(t("create.error_description_required"));
      return;
    }
    if (!effectiveBuilding || !form.customer) {
      setError(t("create.error_building_customer_required"));
      return;
    }
    // Cart validation.
    if (cartLines.length === 0) {
      setError(t("create.error_empty_cart"));
      return;
    }
    const seenServiceIds = new Set<number>();
    // Sprint 137 item 6 — custom-price lines dedupe on their own id
    // space; a price row is no more orderable twice than a service is.
    const seenCustomPriceIds = new Set<number>();
    for (const line of cartLines) {
      const isCustom = line.serviceId === CUSTOM_SERVICE_VALUE;
      const customPriceId = parseCustomPriceId(line.serviceId);
      if (customPriceId !== null) {
        // A price row stranded by a customer switch would be rejected
        // by the backend's tenant guard anyway — fail here with a
        // message that says what to do instead.
        if (staleCustomPriceLine(line)) {
          setError(t("create.error_stale_custom_price"));
          return;
        }
        if (seenCustomPriceIds.has(customPriceId)) {
          setError(t("create.error_duplicate_custom_price"));
          return;
        }
        seenCustomPriceIds.add(customPriceId);
        const qtyNum = Number(line.quantity);
        if (!Number.isFinite(qtyNum) || qtyNum <= 0) {
          setError(t("create.error_line_quantity_invalid"));
          return;
        }
        continue;
      }
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
      // ONE payload, both modes. A series member is created from
      // exactly this object — same fields, same serializer, same
      // validation — with only the title and the slot's date differing
      // per member, which the server composes. That is what stops the
      // batch path from drifting away from the single path the way the
      // reference system's did (its batch writer sets `requested_at` to
      // the scheduled slot and never sets `requested_by` at all).
      const payload = {
        building: Number(effectiveBuilding),
        customer: Number(form.customer),
        title: form.title.trim(),
        description: form.description.trim(),
        // Sprint 144 §1 — the single Category control writes ONE of
        // these two (at most): a company catalog category, or this
        // customer's price folder. `category` (the enum) is deliberately
        // NOT sent — the server default (OTHER) applies, which is what
        // "the form stopped asking" means.
        ...(categoryFilter.startsWith("cat:")
          ? { service_category: Number(categoryFilter.slice(4)) }
          : {}),
        ...(categoryFilter.startsWith("fol:")
          ? { price_folder: Number(categoryFilter.slice(4)) }
          : {}),
        urgency: form.urgency,
        preferred_date: form.preferred_date || null,
        planned_end_date: form.planned_end_date || null,
        deadline: form.deadline || null,
        // Sprint 128 — optional per-customer labels. `effective*` collapses a
        // stale (foreign-customer) selection to "" so it can never reach here.
        ...(effectiveDepartmentId
          ? { department: Number(effectiveDepartmentId) }
          : {}),
        ...(effectiveWorkTypeId
          ? { work_type: Number(effectiveWorkTypeId) }
          : {}),
        // Null is a real answer ("follow the customer"), so it is sent
        // rather than omitted — the server treats the two identically
        // and sending it keeps the payload a full statement of the form.
        billed_to: billedToPayload,
        // W13 — the customer's own asks. Always sent, both values, so
        // the payload is a full statement of the form rather than a
        // list of the boxes that happened to be ticked.
        customer_requires_photo: requirePhoto,
        customer_requires_note: requireNote,
        // Send the validated intent (a member of the latest preview's
        // allowed_intents). Omitted when no fresh preview exists: the
        // backend then derives a safe default — identical to the
        // pre-intent-layer graceful-degradation behaviour.
        ...(intentToSend ? { request_intent: intentToSend } : {}),
        // Catalog lines send `service`; free-text lines send
        // `custom_description`; Sprint 137 item 6 custom-price lines
        // send `custom_price`. Exactly one of the three per line,
        // validated above and re-enforced by the backend.
        line_items: cartLines.map((line) => {
          const customPriceId = parseCustomPriceId(line.serviceId);
          if (customPriceId !== null) {
            return {
              custom_price: customPriceId,
              quantity: line.quantity,
              customer_note: line.customerNote.trim() || undefined,
            };
          }
          return line.serviceId === CUSTOM_SERVICE_VALUE
            ? {
                custom_description: line.customDescription.trim(),
                quantity: line.quantity,
                customer_note: line.customerNote.trim() || undefined,
              }
            : {
                service: Number(line.serviceId),
                quantity: line.quantity,
                customer_note: line.customerNote.trim() || undefined,
              };
        }),
      };

      if (entryMode === "MULTIPLE") {
        const batch = await batchCreateExtraWork(payload, slots);
        setBatchResult({ group: batch.group, created: batch.created });
      } else {
        setResult(await createExtraWork(payload));
      }
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

  // ----- W5-B: the series confirmation -----
  //
  // A batch has no single record to show, so it gets its own panel
  // rather than pretending one member is "the" result. It states how
  // many REAL works were created, because that is the fact somebody
  // needs to check against what they expected to pick.
  if (batchResult) {
    // `.page-wrap` was on this div and is defined in no stylesheet in
    // the app — the css gate flags it and it contributes nothing.
    // Dropped rather than invented: adding the rule would be designing
    // a layout nobody asked for.
    return (
      <div data-testid="extra-work-batch-result">
        <div className="card">
          <h2 className="section-title">{t("series.created_title")}</h2>
          <p>{batchResult.group.standard_title}</p>
          <p>
            <strong data-testid="extra-work-batch-created-count">
              {t("series.created_body", { count: batchResult.created })}
            </strong>
          </p>
          <div className="form-actions">
            <Link
              to="/extra-work"
              className="btn btn-primary"
              data-testid="extra-work-batch-to-list"
            >
              {t("series.created_open_list")}
            </Link>
          </div>
        </div>
      </div>
    );
  }

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

      {/* Sprint 147 — "empty" means two different things. The endpoint
          returns a CUSTOMER only the services a price has been agreed
          with them for, so empty means "nothing agreed with you yet",
          NOT "the provider has no catalog". Telling a customer an admin
          must go and set the catalog up is false and unactionable. */}
      {catalogWarningKind && (
        <div
          className="alert-warning"
          style={{ marginBottom: 16 }}
          role="status"
          data-testid="create-ew-catalog-warning"
        >
          {t(
            catalogWarningKind === "unavailable"
              ? "create.warning_catalog_unavailable"
              : isCustomerActor
                ? "create.warning_no_agreed_services"
                : "create.warning_catalog_empty",
          )}
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
                  disabled={selectableCustomers.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("create.field_customer_placeholder")}
                  </option>
                  {selectableCustomers.map((c) => (
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
                  value={effectiveBuilding}
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
            {/* Sprint 128 — optional per-customer labels. Empty first option
                (they are optional); disabled with a hint when the chosen
                customer has no labels of that kind (one real customer has
                twelve departments and zero work types). */}
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-department">
                  {t("create.field_department")} *
                </label>
                <select
                  id="ew-department"
                  data-testid="extra-work-create-department"
                  className="field-select"
                  value={effectiveDepartmentId}
                  onChange={(event) => setDepartmentId(event.target.value)}
                  disabled={currentDepartments.length === 0}
                >
                  {/* Sprint 186 — the field is required, so there is no
                      empty CHOICE; but until a customer is picked there is
                      nothing to choose from, and an empty dropdown reads
                      as broken. A disabled placeholder says which step
                      comes first instead. */}
                  {currentDepartments.length === 0 && (
                    <option value="">
                      {t("create.field_label_pick_customer")}
                    </option>
                  )}
                  {currentDepartments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {customerLabelName(d.name, t)}
                    </option>
                  ))}
                </select>
                {form.customer && currentDepartments.length === 0 && (
                  <span className="muted small">
                    {t("create.field_department_empty")}
                  </span>
                )}
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ew-work-type">
                  {t("create.field_work_type")} *
                </label>
                <select
                  id="ew-work-type"
                  data-testid="extra-work-create-work-type"
                  className="field-select"
                  value={effectiveWorkTypeId}
                  onChange={(event) => setWorkTypeId(event.target.value)}
                  disabled={currentWorkTypes.length === 0}
                >
                  {currentWorkTypes.length === 0 && (
                    <option value="">
                      {t("create.field_label_pick_customer")}
                    </option>
                  )}
                  {currentWorkTypes.map((w) => (
                    <option key={w.id} value={w.id}>
                      {customerLabelName(w.name, t)}
                    </option>
                  ))}
                </select>
                {form.customer && currentWorkTypes.length === 0 && (
                  <span className="muted small">
                    {t("create.field_work_type_empty")}
                  </span>
                )}
              </div>
            </div>
            {/* W-E §2 — THE CHOICE CARRIES ITS OWN MEANING.
                It used to be a two-option dropdown labelled "Billed to"
                with a hint under it, and the owner's questions about it
                were "what does it control, what does changing it affect,
                does it affect the invoice, the amount, the hours, the
                customer". Every one of those is answered by naming the
                thing the control actually moves, which is WHICH INVOICE
                the amount lands on — nothing else. So the label is that
                question and each option is the resulting document, by
                name.

                W12 — TWO options. The column still has three states,
                and the third one is not a thing to choose: NULL is what
                is stored when the answer matches the customer, which is
                what the server already reads it as
                (`invoicing/billing_target.py`).

                Asked HERE, next to the building and the customer,
                because those are the two names it chooses between.

                Rendered only once a customer is resolved: the marker
                below states THAT customer's own setting, so before one
                is picked there is no setting to state and the question
                would have to hedge. Every role resolves the customer
                the same way — through the (scoped) customer select —
                so this gate behaves identically for a CUSTOMER_USER. */}
            {chosenCustomer && (
              <fieldset
                className="field"
                style={{ border: 0, padding: 0, margin: 0 }}
                data-testid="extra-work-create-billed-to"
              >
                <span className="field-label">
                  {t("create.billed_to_question")}
                </span>

                {/* W12 — TWO options, and the one the customer's own
                    setting produces is already on, and says so on itself.

                    "Follow the customer's setting" was a third radio. It
                    deferred the question instead of answering it: you
                    could not tell what you had chosen without leaving the
                    page to look the customer up. The marker below carries
                    that fact ON the option it applies to, so choosing the
                    other one is a visible disagreement with a visible
                    default rather than a jump into the unknown.

                    Leaving it alone posts NULL, not this value — see
                    `billedToPayload`. */}
                <label className="ew-billed-to-option">
                  <input
                    type="radio"
                    name="ew-billed-to"
                    checked={selectedBilledTo === "BUILDING"}
                    onChange={() => setBilledTo("BUILDING")}
                    data-testid="extra-work-create-billed-to-building"
                  />
                  <span>
                    <strong>
                      {chosenBuilding
                        ? t("create.billed_to_building_named", {
                            building: chosenBuilding.name,
                          })
                        : t("create.billed_to_building_unnamed")}
                    </strong>
                    {resolvedBilledTo === "BUILDING" && (
                      <span
                        className="ew-billed-to-default"
                        data-testid="extra-work-create-billed-to-default-marker"
                      >
                        {t("create.billed_to_customer_setting")}
                      </span>
                    )}
                  </span>
                </label>

                <label className="ew-billed-to-option">
                  <input
                    type="radio"
                    name="ew-billed-to"
                    checked={selectedBilledTo === "CUSTOMER"}
                    onChange={() => setBilledTo("CUSTOMER")}
                    data-testid="extra-work-create-billed-to-customer"
                  />
                  <span>
                    <strong>
                      {t("create.billed_to_customer_named", {
                        customer: chosenCustomer.name,
                      })}
                    </strong>
                    {resolvedBilledTo === "CUSTOMER" && (
                      <span
                        className="ew-billed-to-default"
                        data-testid="extra-work-create-billed-to-default-marker"
                      >
                        {t("create.billed_to_customer_setting")}
                      </span>
                    )}
                  </span>
                </label>

              </fieldset>
            )}

            {/* W13 — WHAT THE CUSTOMER WANTS TO SEE BEFORE THIS IS DONE.
                The owner's father's case: "the person says I will see
                it, I want proof by photo. Then you cannot say finished
                without adding a photo."

                Two checkboxes, no prose. Each label is the whole
                instruction, written as what the asker gets rather than
                as a rule about a flag, and off is the honest default -
                asking for proof is a decision, not a form somebody
                clicks through. The provider can add its own ask when
                planning; the two are independent and the completion
                gate requires whatever either side asked for. */}
            <fieldset
              className="field"
              style={{ border: 0, padding: 0, margin: 0 }}
              data-testid="extra-work-create-proof"
            >
              <span className="field-label">{t("create.proof_question")}</span>
              <label className="ew-billed-to-option">
                <input
                  type="checkbox"
                  checked={requirePhoto}
                  onChange={(e) => setRequirePhoto(e.target.checked)}
                  data-testid="extra-work-create-require-photo"
                />
                <span>{t("create.proof_photo")}</span>
              </label>
              <label className="ew-billed-to-option">
                <input
                  type="checkbox"
                  checked={requireNote}
                  onChange={(e) => setRequireNote(e.target.checked)}
                  data-testid="extra-work-create-require-note"
                />
                <span>{t("create.proof_note")}</span>
              </label>
            </fieldset>
          </div>

          <div className="form-section">
            <div className="form-section-title">
              {t("create.what_section_title")}
            </div>
            <div className="form-2col">
              {/* Sprint 144 §1 — ONE "Category" on the page.
                  This used to be `ExtraWorkRequest.category`, the fixed
                  generic enum (Deep cleaning / Window cleaning / …),
                  while the REAL picker — the company's catalog
                  categories plus this customer's price folders — sat
                  separately above the cart as a filter. Two controls
                  called "Category", one of which had nothing to do with
                  the operator's catalog.
                  They are now the same control: choosing here both
                  CLASSIFIES the request (`service_category` /
                  `price_folder` on the model) and FILTERS the service
                  lines below. The enum column is untouched and keeps its
                  `default=OTHER` — the form simply stops asking, so old
                  rows keep their value and new ones take the default.
                  Fully migrating the enum away is `## NEXT` item 18. */}
              <div className="field">
                <label className="field-label" htmlFor="ew-catalog-category">
                  {t("create.field_category")}
                </label>
                <select
                  id="ew-catalog-category"
                  className="field-select"
                  data-testid="extra-work-create-catalog-category"
                  value={categoryFilter}
                  onChange={(event) => setCategoryFilter(event.target.value)}
                  // Sprint 145 — a category belongs to a CUSTOMER, so
                  // there is nothing to choose from before one is
                  // picked. Disabled rather than showing the provider's
                  // own catalog groupings: those are not the customer's
                  // categories, and offering them here put a foreign
                  // provider's headings in front of a customer user.
                  disabled={!form.customer}
                >
                  {/* Sprint 186 §1 — "All categories" is filter wording
                      on a field that files the request. There is no
                      "General" ROW to select: `service_category` and
                      `price_folder` are both nullable and nothing
                      provisions a default one, so the empty value stays
                      empty on the wire and only its LABEL changes. The
                      word is the one this system already uses for the
                      unclassified case — `customers/signals.py` seeds
                      every customer an "Algemeen" department and work
                      type — rather than a second name for one idea. */}
                  <option value="">{t("create.field_category_none")}</option>
                  {/* Sprint 145 — ONE flat list: the categories that
                      belong to the selected customer. Archived ones are
                      excluded upstream (`currentFolders`), so the form
                      only ever offers what can be ordered now. */}
                  {currentFolders.map((folder) => (
                    <option key={`fol-${folder.id}`} value={`fol:${folder.id}`}>
                      {folder.name}
                    </option>
                  ))}
                </select>
                <div className="muted small" style={{ marginTop: 4 }}>
                  {!form.customer
                    ? t("create.field_category_pick_customer_first")
                    : currentFolders.length === 0
                      ? t("create.field_category_customer_has_none")
                      : t("create.field_category_hint")}
                </div>
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

            {/* W5-B — the entry mode. Above the title deliberately:
                it changes what the title MEANS, and a control that
                changes the meaning of the field below it belongs above
                that field. */}
            <div className="field">
              <span className="field-label">{t("series.mode_label")}</span>
              <div className="ew-entry-mode" role="radiogroup"
                   aria-label={t("series.mode_label")}>
                <label className="ew-entry-mode-option">
                  <input
                    type="radio"
                    name="ew-entry-mode"
                    checked={entryMode === "SINGLE"}
                    onChange={() => setEntryMode("SINGLE")}
                    data-testid="extra-work-entry-mode-single"
                  />
                  <span>{t("series.mode_single")}</span>
                </label>
                <label className="ew-entry-mode-option">
                  <input
                    type="radio"
                    name="ew-entry-mode"
                    checked={entryMode === "MULTIPLE"}
                    onChange={() => setEntryMode("MULTIPLE")}
                    data-testid="extra-work-entry-mode-multiple"
                  />
                  <span>{t("series.mode_multiple")}</span>
                </label>
              </div>
              <p className="muted small">{t("series.mode_hint")}</p>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-title">
                {entryMode === "MULTIPLE"
                  ? t("series.standard_title_label")
                  : t("create.field_title")}
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

            {entryMode === "MULTIPLE" && (
              <div className="field">
                <span className="field-label">{t("series.slot_list")}</span>
                <SlotPicker slots={slots} onChange={setSlots} />
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="ew-description">
                {t("create.field_description")}
              </label>
              <textarea
                id="ew-description"
                data-testid="extra-work-create-description"
                className="field-textarea"
                placeholder={t("create.field_description_placeholder")}
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
                data-testid="extra-work-create-preferred-date"
                value={form.preferred_date}
                onChange={(event) => {
                  // W-EW1 §1b — one date, three fields. Fill the two
                  // that the user has not taken over; leave the ones
                  // they have. All three stay editable either way.
                  const value = event.target.value;
                  setForm((current) => ({
                    ...current,
                    preferred_date: value,
                    planned_end_date: dateTakenOver.plannedEnd
                      ? current.planned_end_date
                      : value,
                    deadline: dateTakenOver.deadline
                      ? current.deadline
                      : value,
                  }));
                }}
              />
            </div>

            {/* Sprint 174 §1 — the planned WINDOW's end and the
                DEADLINE. Sprint 173 added both fields and no form ever
                offered them, so every record was created with them
                empty. */}
            <div className="field">
              <label className="field-label" htmlFor="ew-planned-end">
                {t("detail.plannedEnd")}
              </label>
              <input
                id="ew-planned-end"
                className="field-input"
                type="date"
                data-testid="extra-work-create-planned-end"
                value={form.planned_end_date}
                onChange={(event) => {
                  setDateTakenOver((c) => ({ ...c, plannedEnd: true }));
                  update("planned_end_date", event.target.value);
                }}
              />
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                {t("create.plannedEndHint")}
              </p>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-deadline">
                {t("detail.deadline")}
              </label>
              <div className="ew-deadline-row">
                <input
                  id="ew-deadline"
                  className="field-input"
                  type="date"
                  data-testid="extra-work-create-deadline"
                  value={form.deadline}
                  onChange={(event) => {
                    setDateTakenOver((c) => ({ ...c, deadline: true }));
                    update("deadline", event.target.value);
                  }}
                />
                {/* W-EW1 §1c — the time the deadline leaves, as a
                    VALUE. No deadline, no chip: an absent deadline is
                    not "unlimited time", it is a question nobody has
                    answered, and inventing a number here would be the
                    company-default-SLA feature that is deliberately
                    NOT in this change. */}
                {deadlineDaysLeft !== null && (
                  <span
                    className={`ew-deadline-chip${
                      deadlineDaysLeft < 0 ? " ew-deadline-chip-late" : ""
                    }`}
                    data-testid="extra-work-create-deadline-chip"
                  >
                    {deadlineDaysLeft < 0
                      ? t("create.deadline_chip_overdue", {
                          count: Math.abs(deadlineDaysLeft),
                        })
                      : deadlineDaysLeft === 0
                        ? t("create.deadline_chip_today")
                        : t("create.deadline_chip_left", {
                            count: deadlineDaysLeft,
                          })}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* ----- Agreed prices (browse) -----

              W-EW1 §3 — what is LEFT of the old Cart section. The two
              service pickers that used to live here (Search Services and
              the Service Line Items rows) are gone: the pricing preview
              below is now the one place a line is added, swapped, or
              edited.

              This card stays because it is the only place a
              `CustomerCustomPrice` is BROWSABLE with its amount before it
              is ordered — those rows have no `service` FK, so they appear
              in no catalog list anywhere in the app — and because it
              answers "which of my services already have an agreed price,
              and what is it?" before any line exists to preview. The
              preview shows the price of a line you already added; this
              shows the price of one you have not. */}
          <div className="form-section" data-testid="extra-work-create-cart">
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
                      {t(
                        isCustomerActor
                          ? "create.prices.empty_customer"
                          : "create.prices.empty",
                      )}
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
                  {/* Sprint 137 item 6 — the customer's custom price
                      lines, in the SAME browse panel as the contract
                      prices. This panel is where the owner looked for
                      the work types he had priced; before item 6 they
                      were not here (nor anywhere else in this form)
                      because a CustomerCustomPrice has no service FK
                      and so could never be ordered at all. */}
                  {orderableCustomPrices.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div
                        className="form-section-title"
                        style={{ margin: "0 0 6px" }}
                      >
                        {t("create.prices.custom_section_title")}
                      </div>
                      <div
                        className="ew-agreed-prices-list"
                        data-testid="extra-work-create-custom-prices-list"
                      >
                        {orderableCustomPrices.map((price) => {
                          const inCart = cartLines.some(
                            (l) => parseCustomPriceId(l.serviceId) === price.id,
                          );
                          return (
                            <button
                              type="button"
                              key={price.id}
                              className="ew-agreed-price-item"
                              data-testid="extra-work-create-custom-price-item"
                              data-in-cart={inCart ? "true" : "false"}
                              disabled={inCart}
                              onClick={() => addCustomPriceToCart(price.id)}
                            >
                              <span className="ew-agreed-price-item-label">
                                {price.custom_name}
                                <span className="muted small">
                                  {" · "}
                                  {customPriceUnitLabel(price)}
                                </span>
                              </span>
                              <span className="ew-agreed-price-item-price">
                                {formatMoney(price.unit_price)}
                                <span className="muted small">
                                  {" · "}
                                  {formatNumber(price.vat_pct, {
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
                        })}
                      </div>
                      <div className="muted small" style={{ marginTop: 6 }}>
                        {t("create.prices.custom_helper")}
                      </div>
                    </div>
                  )}
                  <div className="muted small" style={{ marginTop: 8 }}>
                    {t("create.prices.helper")}
                  </div>
                </div>
              </details>
            )}

          </div>

          {/* ----- The pricing preview IS the service-line interface -----

              W-EW1 §3. Until now this table was a read-only projection
              of a cart built somewhere else on the page, which meant a
              line's numbers and a line's controls were never in the same
              place: you edited a quantity in one section and scrolled to
              another to find out what it cost.

              Now the table is the cart. Lines are added from its own
              header, swapped and edited in its own rows, and priced in
              the same row you are editing.

              Rendered UNCONDITIONALLY, unlike the old block, which was
              behind `previewable` — the one control that adds the first
              line now lives inside it, so gating the section on the cart
              already being valid would have made an empty cart
              unfillable. The PRICED columns still wait for the server. */}
          <div
            className="form-section"
            data-testid="extra-work-create-preview"
          >
            {/* W-EW2 §1 — the header carries the title and NOTHING
                else. The "Add service line" button that used to sit
                here appended a blank row and unfolded a search block
                under the table; the one control that adds a line is
                now the combobox in the table's own last row. */}
            <div className="ew-preview-head">
              <div className="form-section-title" style={{ margin: 0 }}>
                {t("create.preview.section_title")}
              </div>
            </div>

            {previewErrorMsg && (
              <div
                className="alert-warning"
                role="status"
                style={{ marginBottom: 12 }}
                data-testid="extra-work-create-preview-unavailable"
              >
                {t("create.preview.unavailable")}
              </div>
            )}

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
                    <th aria-label={t("create.preview.col_actions")} />
                  </tr>
                </thead>
                <tbody>
                  {cartLines.length === 0 && (
                    <tr data-testid="extra-work-create-cart-empty">
                      <td colSpan={7} className="muted small">
                        {t("create.cart_empty")}
                      </td>
                    </tr>
                  )}
                  {cartLines.map((line, index) => {
                    // W-EW2 §3 — the server's row for THIS cart line,
                    // matched by identity (see `previewByTempId`).
                    // `null` while a fetch is in flight, or for a row
                    // that is not finished enough to price — and now
                    // ONLY for that row: an unfinished neighbour no
                    // longer takes this row's price down with it.
                    const priced = previewByTempId.get(line.tempId) ?? null;
                    const known = priced ? knownLinePrice(priced) : null;
                    const qty = Number(line.quantity);
                    const lineTotal =
                      known && Number.isFinite(qty)
                        ? qty * known.unit * (1 + known.vatPct / 100)
                        : null;
                    const isCustom = line.serviceId === CUSTOM_SERVICE_VALUE;
                    const customPriceId = parseCustomPriceId(line.serviceId);
                    const stale = staleCustomPriceLine(line);
                    return (
                      <Fragment key={line.tempId}>
                        <tr
                          data-testid="extra-work-create-preview-row"
                          data-price-source={priced?.price_source ?? ""}
                        >
                          <td>
                            {/* W-EW2 §1 — the service cell STATES the
                                line; it no longer opens a picker under
                                the table. Changing a line's service is
                                removing it and typing the other one
                                into the box below, which with one
                                control is fewer actions than the swap
                                it replaces. */}
                            <div
                              className="ew-line-service-button"
                              data-testid={`extra-work-create-line-service-${index}`}
                            >
                              {cartLineLabel(line)}
                            </div>
                            {isCustom && (
                              <input
                                data-testid={`extra-work-create-line-custom-${index}`}
                                className="field-input"
                                style={{ marginTop: 6 }}
                                type="text"
                                maxLength={255}
                                placeholder={t(
                                  "create.line_custom_placeholder",
                                )}
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
                            {customPriceId !== null &&
                              (stale ? (
                                <div
                                  className="alert-warning"
                                  role="status"
                                  style={{ marginTop: 6 }}
                                  data-testid={`extra-work-create-line-custom-price-stale-${index}`}
                                >
                                  {t("create.line_custom_price_stale")}
                                </div>
                              ) : (
                                <div
                                  className="muted small"
                                  style={{ marginTop: 6 }}
                                  data-testid={`extra-work-create-line-custom-price-${index}`}
                                >
                                  {t("create.line_custom_price_hint")}
                                </div>
                              ))}
                            {/* The per-line note moved here with its
                                line rather than being dropped when the
                                Service Line Items section went. */}
                            <input
                              id={`ew-line-note-${index}`}
                              data-testid={`extra-work-create-line-note-${index}`}
                              className="field-input ew-line-note-input"
                              aria-label={t("create.line_field_customer_note")}
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
                          </td>
                          <td>
                            {priced ? (
                              <span
                                className={`invoice-line-row-source-tag invoice-line-row-source-${PREVIEW_SOURCE_TAG[priced.price_source]}`}
                                data-testid="extra-work-create-preview-source"
                              >
                                {t(PREVIEW_SOURCE_KEY[priced.price_source])}
                              </span>
                            ) : (
                              <span className="muted small">—</span>
                            )}
                          </td>
                          <td>
                            <input
                              id={`ew-line-quantity-${index}`}
                              data-testid={`extra-work-create-line-quantity-${index}`}
                              className="field-input ew-line-qty-input"
                              aria-label={t("create.line_field_quantity")}
                              type="number"
                              /* W-EW1 §3 — one arrow press is one whole
                                 unit. Typing a decimal is still allowed:
                                 `step` constrains the STEPPER, and the
                                 field carries no HTML validation that
                                 would reject 1.5, because half an hour
                                 is a real quantity. */
                              step="1"
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
                          </td>
                          {/* Unit price and VAT are the AGREEMENT's
                              numbers, resolved server-side. They are
                              rendered, never typed — see §3. */}
                          <td>{known ? formatMoney(known.unit) : "—"}</td>
                          <td>
                            {known
                              ? `${formatNumber(known.vatPct, {
                                  maximumFractionDigits: 2,
                                })}%`
                              : "—"}
                          </td>
                          <td>
                            {known ? (
                              formatMoney(lineTotal)
                            ) : (
                              <span className="muted small">
                                {t("create.preview.to_be_priced")}
                              </span>
                            )}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() => removeCartLine(line.tempId)}
                              data-testid={`extra-work-create-remove-line-${index}`}
                              aria-label={t("create.remove_line_button")}
                            >
                              <Trash2 size={14} strokeWidth={2.2} />
                            </button>
                          </td>
                        </tr>
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* ----- W-EW2 §1 — THE ONE CONTROL -----

                The table's add row. It sits flush under the last line,
                reads as the next row of the table, and is the only way
                this page puts a line in the cart.

                It is OUTSIDE `.table-wrap` on purpose. That wrapper is
                `overflow-x: auto`, and a CSS box with `overflow-x: auto`
                and `overflow-y: visible` computes to `overflow-y: auto`
                — so a popover rendered from inside the table would be
                clipped by the wrapper, or would put a scrollbar on it.
                The requirement is a popover attached to the input, and
                an attached popover is what this placement buys.

                The list is BOUNDED (`BoundedList`): it renders a server
                collection, and this customer may have hundreds of
                agreed prices. */}
            <div
              className="ew-agreed-prices"
              style={{ position: "relative", marginTop: 0, marginBottom: 12 }}
              data-testid="extra-work-create-add-box"
            >
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  type="text"
                  role="combobox"
                  aria-expanded={addOpen}
                  aria-controls="ew-add-popover"
                  aria-autocomplete="list"
                  className="field-input"
                  style={{ flex: "1 1 auto", minWidth: 0 }}
                  placeholder={t("create.add_box.placeholder")}
                  aria-label={t("create.add_box.placeholder")}
                  data-testid="extra-work-create-add-input"
                  value={addQuery}
                  onFocus={() => setAddOpen(true)}
                  onChange={(event) => {
                    setAddQuery(event.target.value);
                    setAddHighlight(0);
                    setAddOpen(true);
                  }}
                  /* Blur closes the popover, but only after the click
                     that caused it has landed — a `mousedown` on a
                     suggestion blurs the input before its `click`
                     fires, and closing synchronously would unmount the
                     row being clicked. The popover rows use
                     `onMouseDown preventDefault` instead, so the input
                     never loses focus and this only runs on a real
                     move away. */
                  onBlur={() => setAddOpen(false)}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowDown") {
                      event.preventDefault();
                      setAddOpen(true);
                      setAddHighlight((current) =>
                        addRows.length === 0
                          ? 0
                          : Math.min(current + 1, addRows.length - 1),
                      );
                    } else if (event.key === "ArrowUp") {
                      event.preventDefault();
                      setAddHighlight((current) => Math.max(current - 1, 0));
                    } else if (event.key === "Enter") {
                      // The box lives inside the create <form>; without
                      // this, Enter submits the request instead of
                      // adding the line.
                      event.preventDefault();
                      commitAddRow(addRows[addIndex]);
                    } else if (event.key === "Escape") {
                      setAddOpen(false);
                    }
                  }}
                />
                {/* The explicit act. Finishing a custom line by
                    pressing Enter and hoping is what this replaces.

                    Enabled only while something is TYPED. With an empty
                    box there is nothing to confirm — the highlight is
                    then just the first suggestion, and a button that
                    silently added it would be a trap. Pick from the
                    list in that case; confirm what you wrote in this
                    one. */}
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={!addQuery.trim() || addIndex < 0}
                  onClick={() => commitAddRow(addRows[addIndex])}
                  data-testid="extra-work-create-add-confirm"
                >
                  <Plus size={14} strokeWidth={2.2} />
                  <span style={{ marginLeft: 6 }}>
                    {t("create.add_box.confirm")}
                  </span>
                </button>
              </div>

              {addOpen && (
                <div
                  id="ew-add-popover"
                  role="listbox"
                  aria-label={t("create.preview.picker_label")}
                  data-testid="extra-work-create-add-popover"
                  style={{
                    position: "absolute",
                    top: "100%",
                    left: 12,
                    right: 12,
                    zIndex: 30,
                    marginTop: 4,
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
                  }}
                >
                  <BoundedList
                    size="md"
                    count={addRows.length}
                    ariaLabel={t("create.preview.picker_label")}
                    testIdPrefix="extra-work-create-add-list"
                    emptyState={
                      <div className="muted small" style={{ padding: 8 }}>
                        {t("create.prices.no_match")}
                      </div>
                    }
                  >
                    <div
                      className="ew-agreed-prices-list"
                      style={{ marginTop: 0, border: "none" }}
                    >
                      {addRows.map((row, rowIndex) => {
                        const active = rowIndex === addIndex;
                        const inCart = addRowInCart(row);
                        const svc =
                          row.kind === "service"
                            ? serviceById.get(row.id)
                            : undefined;
                        const price =
                          row.kind === "custom_price"
                            ? orderableCustomPrices.find(
                                (p) => p.id === row.id,
                              )
                            : undefined;
                        return (
                          <button
                            key={row.key}
                            type="button"
                            role="option"
                            aria-selected={active}
                            className="ew-agreed-price-item"
                            style={
                              active
                                ? {
                                    background: "rgba(11, 107, 66, 0.10)",
                                    borderColor: "var(--border)",
                                  }
                                : undefined
                            }
                            data-testid={
                              row.kind === "custom_text"
                                ? "extra-work-create-add-option-custom"
                                : "extra-work-create-add-option"
                            }
                            /* Keeps focus in the input so the blur
                               above cannot unmount this row mid-click. */
                            onMouseDown={(event) => event.preventDefault()}
                            onMouseEnter={() => setAddHighlight(rowIndex)}
                            onClick={() => commitAddRow(row)}
                          >
                            {row.kind === "custom_text" ? (
                              <span className="ew-agreed-price-item-label">
                                {t("create.add_box.add_custom", {
                                  text: addQuery.trim(),
                                })}
                              </span>
                            ) : (
                              <>
                                <span className="ew-agreed-price-item-label">
                                  {row.kind === "service"
                                    ? svc && svc.category_name
                                      ? `${svc.category_name} — ${svc.name}`
                                      : (svc?.name ?? "")
                                    : (price?.custom_name ?? "")}
                                  {inCart && (
                                    <Check
                                      size={14}
                                      strokeWidth={2.5}
                                      aria-hidden
                                      style={{ marginLeft: 6 }}
                                    />
                                  )}
                                </span>
                                <span className="ew-agreed-price-item-price">
                                  {row.kind === "service"
                                    ? agreedPriceSuffix(row.id).replace(
                                        /^ — /,
                                        "",
                                      )
                                    : price
                                      ? `${formatMoney(price.unit_price)} / ${customPriceUnitLabel(price)}`
                                      : ""}
                                </span>
                              </>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </BoundedList>
                </div>
              )}
            </div>

            {previewLoading && (
              <div
                className="muted small"
                role="status"
                style={{ marginTop: 8 }}
                data-testid="extra-work-create-preview-loading"
              >
                {t("create.preview.loading")}
              </div>
            )}

            {previewData && previewTotals && (
              <div
                className="alert-info"
                style={{ marginTop: 12 }}
                data-testid="extra-work-create-preview-totals"
              >
                <div className="form-section-title" style={{ margin: 0 }}>
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
                  {t(
                    isCustomerActor
                      ? "create.preview.totals_display_only_customer"
                      : "create.preview.totals_display_only",
                  )}
                </div>
              </div>
            )}
          </div>

          {previewable && (
            <>

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

          {/* W-EW1 — the submit error belongs AT the action.
              Page-top was the wrong place for it on a form this tall:
              the button that produced the message could be a screen and
              a half below the message, so a refused submit looked like
              a dead button. It sits above the actions row, in the same
              field of view as the control that caused it. */}
          {error && (
            <div
              className="alert-error"
              style={{ marginTop: 16 }}
              role="alert"
              data-testid="extra-work-create-error"
            >
              {error}
            </div>
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
