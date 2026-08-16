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
import { createExtraWork, getExtraWorkPreview } from "../api/extraWork";
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
} from "../api/types";
import { InvoiceLineRow } from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { formatMoney, formatNumber } from "../lib/intl";


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
  requestedDate: string;
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
  // Sprint 180 §3 — who the finished work is charged to. Seeded to
  // BUILDING, which is both the model default and the owner's own
  // "99% of the time", so an operator who ignores the control gets the
  // right answer rather than an empty one.
  const [billedTo, setBilledTo] = useState<ExtraWorkBilledTo>("BUILDING");
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
  // Free-text service search. Deliberately searches the WHOLE catalog,
  // never the filtered subset, so a category filter can never hide a
  // service the operator is explicitly looking for.
  const [serviceSearch, setServiceSearch] = useState("");

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
  const effectiveDepartmentId = currentDepartments.some(
    (d) => String(d.id) === departmentId,
  )
    ? departmentId
    : "";
  const effectiveWorkTypeId = currentWorkTypes.some(
    (w) => String(w.id) === workTypeId,
  )
    ? workTypeId
    : "";

  // The cart is "previewable" once a building + customer are chosen and
  // every line carries a service, a positive quantity, and a date —
  // exactly what the preview serializer requires.
  const previewable = useMemo(() => {
    if (!effectiveBuilding || !form.customer) return false;
    if (cartLines.length === 0) return false;
    return cartLines.every((line) => {
      // A line is previewable when it is a catalog service (a chosen
      // numeric serviceId), an ordered custom price, OR a custom line
      // with non-empty text. An empty line, or a custom line with blank
      // text, is not.
      if (line.serviceId === CUSTOM_SERVICE_VALUE) {
        if (!line.customDescription.trim()) return false;
      } else if (!line.serviceId) {
        return false;
      }
      const q = Number(line.quantity);
      if (!Number.isFinite(q) || q <= 0) return false;
      return Boolean(line.requestedDate);
    });
  }, [effectiveBuilding, form.customer, cartLines]);

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
      l: cartLines.map((line) => {
        const isCustom = line.serviceId === CUSTOM_SERVICE_VALUE;
        const customPriceId = parseCustomPriceId(line.serviceId);
        return {
          s: isCustom || customPriceId !== null ? null : Number(line.serviceId),
          c: isCustom ? line.customDescription.trim() : null,
          // Sprint 137 item 6 — a custom-price line's identity is the
          // price row id; it belongs in the signature so changing the
          // ordered price re-fetches the preview.
          p: customPriceId,
          q: line.quantity,
          d: line.requestedDate,
        };
      }),
    });
  }, [previewable, effectiveBuilding, form.customer, cartLines]);

  // Debounced live preview. All state writes happen inside the timer's
  // async callback (deferred), never synchronously in the effect body.
  useEffect(() => {
    if (!previewKey) return;
    const parsed = JSON.parse(previewKey) as {
      b: number;
      c: number;
      l: {
        s: number | null;
        c: string | null;
        p: number | null;
        q: string;
        d: string;
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
            // Catalog lines send `service`; free-text lines send
            // `custom_description`; Sprint 137 item 6 custom-price
            // lines send `custom_price`. Exactly one of the three per
            // line — the preview serializer enforces the same rule.
            line_items: parsed.l.map((line) => {
              if (line.p !== null) {
                return {
                  custom_price: line.p,
                  quantity: line.q,
                  requested_date: line.d,
                };
              }
              return line.c !== null
                ? {
                    custom_description: line.c,
                    quantity: line.q,
                    requested_date: line.d,
                  }
                : {
                    service: line.s ?? undefined,
                    quantity: line.q,
                    requested_date: line.d,
                  };
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

  const serviceSearchTerm = serviceSearch.trim().toLowerCase();

  // Search results span the ENTIRE catalog — the category filter is
  // deliberately ignored while searching. Every option label already
  // carries its category name, so a match from outside the current
  // filter is self-describing.
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

  const searchMatches = useMemo(() => {
    if (!serviceSearchTerm) return null;
    return catalogForActor.filter((svc) =>
      `${svc.category_name} ${svc.name}`
        .toLowerCase()
        .includes(serviceSearchTerm),
    );
  }, [catalogForActor, serviceSearchTerm]);

  const categoryFilteredServices = useMemo(() => {
    if (!categoryFilter) return catalogForActor;
    if (categoryFilter.startsWith("cat:")) {
      const id = Number(categoryFilter.slice(4));
      return catalogForActor.filter((svc) => svc.category === id);
    }
    if (categoryFilter.startsWith("fol:")) {
      const id = Number(categoryFilter.slice(4));
      const ids = serviceIdsByFolder.get(id);
      if (!ids) return [];
      return catalogForActor.filter((svc) => ids.has(svc.id));
    }
    return catalogForActor;
  }, [catalogForActor, categoryFilter, serviceIdsByFolder]);

  // What the per-line pickers offer right now: search wins over the
  // category filter when one is typed.
  const offeredServices = searchMatches ?? categoryFilteredServices;
  const narrowingActive = Boolean(categoryFilter) || Boolean(serviceSearchTerm);
  const hiddenServiceCount = catalogForActor.length - offeredServices.length;

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

  function clearServiceNarrowing() {
    setCategoryFilter("");
    setServiceSearch("");
  }

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

  /**
   * The option list for ONE cart line. The line's currently-selected
   * service is ALWAYS included even when the active filter/search
   * excludes it — otherwise narrowing the catalog would blank out a
   * `<select>` that already had a value, silently dropping a line the
   * user had already added to the cart.
   */
  function optionsForLine(line: CartLineState): Service[] {
    if (!line.serviceId || line.serviceId === CUSTOM_SERVICE_VALUE) {
      return offeredServices;
    }
    const selectedId = Number(line.serviceId);
    if (offeredServices.some((svc) => svc.id === selectedId)) {
      return offeredServices;
    }
    const selected = services.find((svc) => svc.id === selectedId);
    return selected ? [selected, ...offeredServices] : offeredServices;
  }

  /**
   * Picking a service from OUTSIDE the active category filter clears
   * that filter (per the "selecting a match outside the current
   * category clears the filter" rule) — leaving it on would show the
   * operator a cart line whose service is not in the list they are
   * looking at.
   */
  function onLineServiceChange(tempId: string, value: string) {
    updateCartLine(tempId, "serviceId", value);
    // A custom price has no catalog category, so it can neither match
    // nor contradict the active filter — leave the filter alone.
    if (parseCustomPriceId(value) !== null) return;
    if (!categoryFilter || value === CUSTOM_SERVICE_VALUE || !value) return;
    const picked = services.find((svc) => svc.id === Number(value));
    if (!picked) return;
    // Sprint 143 §4 — the same guard, taught the two key shapes. A
    // service picked from OUTSIDE the active filter clears that filter,
    // so the list the operator is looking at never contradicts the line
    // they just built.
    const stillMatches = categoryFilter.startsWith("cat:")
      ? picked.category === Number(categoryFilter.slice(4))
      : categoryFilter.startsWith("fol:")
        ? (serviceIdsByFolder.get(Number(categoryFilter.slice(4))) ?? new Set()).has(picked.id)
        : true;
    if (!stillMatches) {
      setCategoryFilter("");
    }
  }

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
        if (!line.requestedDate) {
          setError(t("create.error_line_requested_date_required"));
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
        // Sprint 180 §3 — always sent (never omitted): the control has
        // no unset state, so there is no case where "leave it to the
        // server" and "the operator chose BUILDING" mean different
        // things.
        billed_to: billedTo,
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
              requested_date: line.requestedDate,
              customer_note: line.customerNote.trim() || undefined,
            };
          }
          return line.serviceId === CUSTOM_SERVICE_VALUE
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
              };
        }),
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
                  {t("create.field_department")}
                </label>
                <select
                  id="ew-department"
                  data-testid="extra-work-create-department"
                  className="field-select"
                  value={effectiveDepartmentId}
                  onChange={(event) => setDepartmentId(event.target.value)}
                  disabled={currentDepartments.length === 0}
                >
                  <option value="">{t("create.field_department_none")}</option>
                  {currentDepartments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
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
                  {t("create.field_work_type")}
                </label>
                <select
                  id="ew-work-type"
                  data-testid="extra-work-create-work-type"
                  className="field-select"
                  value={effectiveWorkTypeId}
                  onChange={(event) => setWorkTypeId(event.target.value)}
                  disabled={currentWorkTypes.length === 0}
                >
                  <option value="">{t("create.field_work_type_none")}</option>
                  {currentWorkTypes.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
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
            {/* Sprint 180 §3 — who pays for this one.
                Asked HERE, in the parent section next to the building
                and the customer, because those are the two things it
                chooses between: the answer is only meaningful once you
                can see both names on screen.
                This page IS both create surfaces — the customer-facing
                one (a CUSTOMER_USER, customer and building fixed by
                their own access) and the provider-facing one (the
                pickers above) — so a single control serves both, and
                both post the same `billed_to` to the same endpoint.
                Two options and no empty first option, because there is
                no "unset": the field is non-null server-side with
                BUILDING as its default, which is the honest answer 99%
                of the time rather than a placeholder. */}
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="ew-billed-to">
                  {t("create.field_billed_to")}
                </label>
                <select
                  id="ew-billed-to"
                  data-testid="extra-work-create-billed-to"
                  className="field-select"
                  value={billedTo}
                  onChange={(event) =>
                    setBilledTo(event.target.value as ExtraWorkBilledTo)
                  }
                >
                  <option value="BUILDING">{t("billed_to.building")}</option>
                  <option value="CUSTOMER">{t("billed_to.customer")}</option>
                </select>
                <span className="muted small">
                  {t("create.field_billed_to_hint")}
                </span>
              </div>
            </div>
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
                  <option value="">
                    {t("create.catalog_filter.all_categories")}
                  </option>
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
                value={form.planned_end_date}
                onChange={(event) =>
                  update("planned_end_date", event.target.value)
                }
              />
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                {t("create.plannedEndHint")}
              </p>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="ew-deadline">
                {t("detail.deadline")}
              </label>
              <input
                id="ew-deadline"
                className="field-input"
                type="date"
                value={form.deadline}
                onChange={(event) => update("deadline", event.target.value)}
              />
              <p className="muted small" style={{ margin: "4px 0 0" }}>
                {t("create.deadlineHint")}
              </p>
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

            {/* Sprint 137 item 5 — narrow the service pickers by REAL
                catalog category, plus a catalog-wide search. Both are
                opt-in: the default is "All categories" with no search,
                which is byte-identical to the pre-137 picker. */}
            {/* Sprint 144 §1 — the category half of this bar MOVED UP
                into the single "Category" control under "What needs to
                happen". Only the search box is left here, beside the
                lines it searches. */}
            {services.length > 0 && (
              <div
                className="form-2col"
                data-testid="extra-work-create-catalog-filter"
                style={{ marginBottom: 12 }}
              >
                <div className="field">
                  <label className="field-label" htmlFor="ew-catalog-search">
                    {t("create.catalog_filter.search_label")}
                  </label>
                  <input
                    id="ew-catalog-search"
                    className="field-input"
                    type="search"
                    data-testid="extra-work-create-catalog-search"
                    placeholder={t("create.catalog_filter.search_placeholder")}
                    value={serviceSearch}
                    onChange={(event) => setServiceSearch(event.target.value)}
                  />
                  <div className="muted small" style={{ marginTop: 4 }}>
                    {t("create.catalog_filter.search_hint")}
                  </div>
                </div>
                {/* Sprint 147 — say plainly what this list is, and
                    where to go for anything else, so an absent service
                    reads as "not agreed with you" rather than as a
                    broken search. */}
                {isCustomerActor && (
                  <div className="field">
                    <div className="muted small">
                      {t("create.catalog_filter.customer_scope_note")}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Never a bare empty list: name what is hiding the
                results, give the count OUTSIDE the narrowing, and
                offer one click back to the full catalog. */}
            {narrowingActive && offeredServices.length === 0 && (
              <div
                className="alert-warning"
                role="status"
                style={{ marginBottom: 12 }}
                data-testid="extra-work-create-catalog-filter-empty"
              >
                {serviceSearchTerm
                  ? t("create.catalog_filter.no_search_match", {
                      search: serviceSearch.trim(),
                      total: services.length,
                    })
                  : t("create.catalog_filter.category_empty", {
                      total: services.length,
                    })}{" "}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="extra-work-create-catalog-filter-clear"
                  onClick={clearServiceNarrowing}
                >
                  {t("create.catalog_filter.clear")}
                </button>
              </div>
            )}

            {/* Narrowing is active but still showing something: say how
                many services are hidden so the picker is never silently
                partial. */}
            {narrowingActive &&
              offeredServices.length > 0 &&
              hiddenServiceCount > 0 && (
                <div
                  className="muted small"
                  style={{ marginBottom: 12 }}
                  data-testid="extra-work-create-catalog-filter-note"
                >
                  {t("create.catalog_filter.hidden_note", {
                    shown: offeredServices.length,
                    total: services.length,
                  })}{" "}
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={clearServiceNarrowing}
                  >
                    {t("create.catalog_filter.clear")}
                  </button>
                </div>
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
                      onLineServiceChange(line.tempId, event.target.value)
                    }
                    required
                  >
                    <option value="" disabled>
                      {t("create.line_field_service_placeholder")}
                    </option>
                    {optionsForLine(line).map((svc) => {
                      const baseLabel = svc.category_name
                        ? `${svc.category_name} — ${svc.name}`
                        : svc.name;
                      return (
                        <option key={svc.id} value={svc.id}>
                          {`${baseLabel}${agreedPriceSuffix(svc.id)}`}
                        </option>
                      );
                    })}
                    {/* Sprint 137 item 6 — the customer's own custom
                        price lines, orderable at last. Grouped so they
                        read as a distinct kind of thing rather than
                        blending into the catalog, and never filtered by
                        the catalog-category filter: a custom price has
                        no category to filter by. */}
                    {orderableCustomPrices.length > 0 && (
                      <optgroup
                        label={t("create.line_custom_price_group")}
                      >
                        {orderableCustomPrices.map((price) => (
                          <option
                            key={price.id}
                            value={customPriceValue(price.id)}
                          >
                            {`${price.custom_name} — ${formatMoney(
                              price.unit_price,
                            )} / ${customPriceUnitLabel(price)}`}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    {/* A custom price belongs to ONE customer. Switching
                        customer mid-compose can therefore strand a line
                        whose price row is not on the new customer's list
                        — the backend rejects it (tenant guard), but the
                        <select> would first go blank and hide WHY. Keep
                        the value visible and labelled instead of
                        silently emptying the line. */}
                    {staleCustomPriceLine(line) && (
                      <option value={line.serviceId}>
                        {t("create.line_custom_price_unavailable")}
                      </option>
                    )}
                    {/* Custom line: no agreed-price suffix — it has no
                        catalog service to price against. Re-picking a
                        catalog service from this still-visible dropdown
                        switches back. */}
                    <option value={CUSTOM_SERVICE_VALUE}>
                      {t("create.line_custom_option")}
                    </option>
                  </select>
                  {/* A custom-price line is priced from an agreed
                      per-customer row, but it still has no catalog
                      service, so the provider confirms it in the
                      pricing step. Say so on the line rather than
                      letting the source pill be the only clue. */}
                  {parseCustomPriceId(line.serviceId) !== null &&
                    (staleCustomPriceLine(line) ? (
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
                          // Sprint 137 item 6 — "priced" now covers an
                          // agreed contract line AND a line ordered
                          // from a custom price. Both numbers are
                          // backend-provided; the source pill still
                          // reflects the backend's `price_source`
                          // verbatim (a custom price stays AD_HOC).
                          const known = knownLinePrice(line);
                          const unit = known ? known.unit : null;
                          const pct = known ? known.vatPct : null;
                          const qty = Number(line.quantity);
                          const isAgreed = known !== null;
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
                      {t(
                        isCustomerActor
                          ? "create.preview.totals_display_only_customer"
                          : "create.preview.totals_display_only",
                      )}
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
