/**
 * FE-5 (Addendum D §D.5.2 / §D.6 rule 12) — the provider's meerwerk
 * create page: ONE page, staged, dense.
 *
 *   Voor wie   — customer + building. Choosing them fills afdeling,
 *                werktype and the invoice target from the customer's
 *                own defaults, shown as facts with a pencil.
 *   Wat        — the SAME cart the customer flow uses: their agreed
 *                prices with amounts, "iets anders" lines with "prijs
 *                volgt", a note per line. Folder is a filter inside
 *                the picker. Title and notes fold; left empty, they are
 *                derived from the cart like the customer flow does.
 *   Wanneer    — ONE wish date. Planned end, deadline, a multi-day
 *                series and the completion proof live behind "Planning".
 *   Urgentie   — Normaal by default, one "spoed" control.
 *   The end    — the cart as it will be created, the sums, and the
 *                SYSTEM's sentence about what happens next (the server's
 *                preview), with a choice only when the server offers
 *                more than one intent for this actor (SoT §5.3).
 *
 * The old "Request a quote" page folded in here: which intent applies
 * is derived at the bottom, never by which nav entry was clicked.
 *
 * Server contract UNCHANGED: the existing create / batch-create /
 * preview endpoints with the existing fields.
 */
import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Pencil, Siren } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  listAllBuildings,
  listAllCustomers,
  listCustomerCustomPrices,
  listCustomerPriceFolders,
  listCustomerPrices,
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
  ExtraWorkPreviewResponse,
  ExtraWorkRequestDetail,
  ExtraWorkRequestIntent,
  ExtraWorkSlot,
} from "../api/types";
import { InvoiceLineRow } from "../components/InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "../components/invoiceLineColumns";
import { PageHeader } from "../components/PageHeader";
import {
  cartLineItemsPayload,
  derivedDescription,
  derivedTitle,
  emptyOtherLine,
  lineAmounts,
  otherLinesToCart,
  outcomeKey,
  type MeerwerkCartLine,
  type MeerwerkOutcomeKind,
  type OtherLineDraft,
} from "../components/meerwerk/cart";
import { CartSummaryList } from "../components/meerwerk/CartSummaryList";
import { MeerwerkOutcome } from "../components/meerwerk/MeerwerkOutcome";
import { OtherLinesEditor } from "../components/meerwerk/OtherLinesEditor";
import { PricedServicePicker } from "../components/meerwerk/PricedServicePicker";
import { formatMoney } from "../lib/intl";
import { customerLabelName } from "../lib/customerLabelName";

interface ParentFormState {
  building: string;
  customer: string;
  title: string;
  description: string;
  urgent: boolean;
  preferred_date: string;
  planned_end_date: string;
  deadline: string;
}

const EMPTY_PARENT: ParentFormState = {
  building: "",
  customer: "",
  title: "",
  description: "",
  urgent: false,
  preferred_date: "",
  planned_end_date: "",
  deadline: "",
};

type FactKey = "department" | "work_type" | "billed_to";

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

/** Whole days from today to `iso` (local midnights), or null. */
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

/** The server's seeded default: the customer's lowest-id label — the
 *  same row `ExtraWorkRequestCreateSerializer.validate` fills in when a
 *  caller omits the field, so the fact on screen is the fact stored. */
function defaultLabel(rows: CustomerLabel[]): CustomerLabel | null {
  if (rows.length === 0) return null;
  return rows.reduce((low, row) => (row.id < low.id ? row : low), rows[0]);
}

const PREVIEW_DEBOUNCE_MS = 350;

const INTENT_OUTCOME: Record<ExtraWorkRequestIntent, MeerwerkOutcomeKind> = {
  DIRECT_AGREED_PRICE_ORDER: "instant",
  AUTO_START_AFTER_PRICING: "auto_start",
  REQUEST_QUOTE: "quote",
};

const INTENT_ERROR_KEY: Record<ExtraWorkIntentErrorCode, string> = {
  intent_requires_all_agreed: "create.intent.error.requires_all_agreed",
  intent_requires_non_agreed_line:
    "create.intent.error.requires_non_agreed_line",
  intent_forbidden_for_role: "create.intent.error.forbidden_for_role",
  intent_forbidden_for_provider: "create.intent.error.forbidden_for_provider",
  intent_required: "create.intent.error.required",
};

// True when a create rejection is an intent rejection (DRF does not put
// the stable code on the wire; the field name is the tell).
function isIntentSubmitError(err: unknown): boolean {
  const data = (err as { response?: { data?: unknown } } | null)?.response
    ?.data;
  return (
    !!data &&
    typeof data === "object" &&
    "request_intent" in (data as Record<string, unknown>)
  );
}

export function CreateExtraWorkPage() {
  const { t } = useTranslation(["extra_work", "common"]);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<ParentFormState>(EMPTY_PARENT);

  /* W-EW1 §1b — the wish date fills planned end and deadline until the
     user takes one of them over; a taken-over field is never rewritten. */
  const [dateTakenOver, setDateTakenOver] = useState<{
    plannedEnd: boolean;
    deadline: boolean;
  }>({ plannedEnd: false, deadline: false });

  /* W5-B — SINGLE or MULTIPLE (a series: one real meerwerk per chosen
     day, same content). One idempotency key per series submission. */
  const [entryMode, setEntryMode] = useState<"SINGLE" | "MULTIPLE">("SINGLE");
  const [slots, setSlots] = useState<ExtraWorkSlot[]>([]);
  const batchKeyRef = useRef<string>(crypto.randomUUID());
  const [batchResult, setBatchResult] = useState<{
    group: { id: number; standard_title: string };
    created: number;
  } | null>(null);
  const [result, setResult] = useState<ExtraWorkRequestDetail | null>(null);

  /* W12 — the explicit invoice-target pick, or null for "left alone"
     (posts null = follow the customer's own setting). */
  const [billedTo, setBilledTo] = useState<ExtraWorkBilledTo | null>(null);
  /* W13 asked "what must be there before this may be called done?" on
     this form; P-1 §4 moved the question to the plan dialog, which is
     where the planner answers it. The create payload no longer sends a
     choice, so the server default (nothing required) stands until the
     plan says otherwise. */
  /* Sprint 128/186 — the explicit label picks; "" = the seeded default. */
  const [departmentId, setDepartmentId] = useState("");
  const [workTypeId, setWorkTypeId] = useState("");
  /** Which derived fact is open for editing, at most one. */
  const [editingFact, setEditingFact] = useState<FactKey | null>(null);

  // Per-customer lists, each tagged with the customer it was fetched
  // for so a stale list is never shown against the current one.
  const [customerPrices, setCustomerPrices] = useState<{
    customerId: number;
    rows: CustomerServicePrice[];
  } | null>(null);
  const [customCustomPrices, setCustomCustomPrices] = useState<{
    customerId: number;
    rows: CustomerCustomPrice[];
  } | null>(null);
  const [customerFolders, setCustomerFolders] = useState<{
    customerId: number;
    rows: CustomerPriceFolder[];
  } | null>(null);
  const [labelLists, setLabelLists] = useState<{
    customerId: number;
    departments: CustomerLabel[];
    workTypes: CustomerLabel[];
  } | null>(null);

  /* The cart — the FE-2 shape, shared with the customer flow. */
  const [cart, setCart] = useState<MeerwerkCartLine[]>([]);
  const [others, setOthers] = useState<OtherLineDraft[]>([emptyOtherLine(1)]);

  /* The server's preview, tagged with the cart key it answers for. */
  const [selectedIntent, setSelectedIntent] =
    useState<ExtraWorkRequestIntent | null>(null);
  const [preview, setPreview] = useState<
    | { key: string; data: ExtraWorkPreviewResponse }
    | { key: string; error: string }
    | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listAllBuildings(), listAllCustomers()])
      .then(([buildingRows, customerRows]) => {
        if (cancelled) return;
        setBuildings(buildingRows);
        setCustomers(customerRows);
        setLoadingOptions(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(getApiError(err));
        setLoadingOptions(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The chosen customer's prices, custom prices, folders and labels.
  // Load-only effects (no setState in the effect body); a 403 on the
  // provider-only lists degrades to an empty list.
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
    listCustomerCustomPrices(customerId)
      .then((rows) => {
        if (!cancelled) setCustomCustomPrices({ customerId, rows });
      })
      .catch(() => {
        if (!cancelled) setCustomCustomPrices({ customerId, rows: [] });
      });
    listCustomerPriceFolders(customerId, { is_active: true })
      .then((rows) => {
        if (!cancelled) setCustomerFolders({ customerId, rows });
      })
      .catch(() => {
        if (!cancelled) setCustomerFolders({ customerId, rows: [] });
      });
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

  // ----- derived: who -----------------------------------------------
  const chosenCustomer = useMemo(
    () => customers.find((c) => String(c.id) === form.customer) ?? null,
    [customers, form.customer],
  );
  const filteredBuildings = useMemo(() => {
    if (!chosenCustomer) return buildings;
    return buildings.filter((b) => customerMatchesBuilding(chosenCustomer, b.id));
  }, [buildings, chosenCustomer]);
  // A building chosen before the customer changed may not belong to the
  // new customer; it collapses to "" at the point of use. When the
  // customer has exactly one building it is the answer without a click.
  const effectiveBuilding = filteredBuildings.some(
    (b) => String(b.id) === form.building,
  )
    ? form.building
    : chosenCustomer && filteredBuildings.length === 1
      ? String(filteredBuildings[0].id)
      : "";
  const chosenBuilding = useMemo(
    () => buildings.find((b) => String(b.id) === effectiveBuilding) ?? null,
    [buildings, effectiveBuilding],
  );

  const resolvedBilledTo: ExtraWorkBilledTo =
    chosenCustomer?.invoice_billing_target === "BUILDING"
      ? "BUILDING"
      : "CUSTOMER";
  const selectedBilledTo: ExtraWorkBilledTo = billedTo ?? resolvedBilledTo;
  /** Matching the customer's own setting stores NULL (follow the
   *  customer); only a divergence is written down. */
  const billedToPayload: ExtraWorkBilledTo | null =
    selectedBilledTo === resolvedBilledTo ? null : selectedBilledTo;

  const currentDepartments =
    labelLists && String(labelLists.customerId) === form.customer
      ? labelLists.departments
      : [];
  const currentWorkTypes =
    labelLists && String(labelLists.customerId) === form.customer
      ? labelLists.workTypes
      : [];
  const effectiveDepartment =
    currentDepartments.find((d) => String(d.id) === departmentId) ??
    defaultLabel(currentDepartments);
  const effectiveWorkType =
    currentWorkTypes.find((w) => String(w.id) === workTypeId) ??
    defaultLabel(currentWorkTypes);

  // ----- derived: what ------------------------------------------------
  /** The date the cart is priced on: the wish date, else today — the
   *  same day `ExtraWorkPreviewSerializer.validate` resolves prices on. */
  const cartDate = form.preferred_date || todayISO();
  const agreedPrices = useMemo(() => {
    if (
      customerPrices === null ||
      !form.customer ||
      customerPrices.customerId !== Number(form.customer)
    ) {
      return [] as CustomerServicePrice[];
    }
    // One current row per service: the latest `valid_from` on or before
    // the cart date, ties by highest id — `pricing.resolve_price`'s rule.
    const byService = new Map<number, CustomerServicePrice>();
    for (const price of customerPrices.rows) {
      if (
        !price.is_active ||
        price.valid_from > cartDate ||
        (price.valid_to !== null && price.valid_to < cartDate)
      ) {
        continue;
      }
      const current = byService.get(price.service);
      if (
        !current ||
        price.valid_from > current.valid_from ||
        (price.valid_from === current.valid_from && price.id > current.id)
      ) {
        byService.set(price.service, price);
      }
    }
    return [...byService.values()].sort((a, b) =>
      a.service_name.localeCompare(b.service_name),
    );
  }, [customerPrices, form.customer, cartDate]);
  const orderableCustomPrices = useMemo(() => {
    if (
      customCustomPrices === null ||
      !form.customer ||
      customCustomPrices.customerId !== Number(form.customer)
    ) {
      return [] as CustomerCustomPrice[];
    }
    return customCustomPrices.rows
      .filter(
        (p) =>
          p.is_active &&
          p.valid_from <= cartDate &&
          (p.valid_to === null || p.valid_to >= cartDate),
      )
      .sort((a, b) => a.custom_name.localeCompare(b.custom_name));
  }, [customCustomPrices, form.customer, cartDate]);
  const currentFolders =
    customerFolders && String(customerFolders.customerId) === form.customer
      ? customerFolders.rows.filter((f) => f.is_active)
      : [];

  const cartWithOther = useMemo(
    () => [...cart, ...otherLinesToCart(others)],
    [cart, others],
  );
  /** A custom-price line whose row is no longer orderable on the cart's
   *  date: kept and blocked at submit rather than silently dropped. */
  const staleCustomPriceLines = cartWithOther.filter(
    (line) =>
      line.kind === "custom_price" &&
      !orderableCustomPrices.some((p) => p.id === line.id),
  );

  const previewable =
    !!effectiveBuilding && !!form.customer && cartWithOther.length > 0;
  const previewKey = useMemo(() => {
    if (!previewable) return null;
    return JSON.stringify({
      b: Number(effectiveBuilding),
      c: Number(form.customer),
      pd: form.preferred_date || null,
      l: cartLineItemsPayload(cartWithOther),
    });
  }, [previewable, effectiveBuilding, form.customer, form.preferred_date, cartWithOther]);

  // Debounced live preview. State writes happen inside the timer's
  // async callback, never synchronously in the effect body.
  useEffect(() => {
    if (!previewKey) return;
    const parsed = JSON.parse(previewKey) as {
      b: number;
      c: number;
      pd: string | null;
      l: ReturnType<typeof cartLineItemsPayload>;
    };
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const data = await getExtraWorkPreview({
            building: parsed.b,
            customer: parsed.c,
            request_intent: selectedIntent ?? undefined,
            preferred_date: parsed.pd ?? undefined,
            line_items: parsed.l,
          });
          if (cancelled) return;
          setPreview({ key: previewKey, data });
          // Keep the pick when still allowed; else the server's default
          // when allowed; else the first allowed; else null.
          setSelectedIntent((current) => {
            if (current && data.allowed_intents.includes(current)) {
              return current;
            }
            if (data.allowed_intents.includes(data.default_intent)) {
              return data.default_intent;
            }
            return data.allowed_intents[0] ?? null;
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
  }, [previewKey, selectedIntent]);

  const previewData =
    previewable && preview !== null && preview.key === previewKey && "data" in preview
      ? preview.data
      : null;
  const previewFailed =
    previewable &&
    preview !== null &&
    preview.key === previewKey &&
    "error" in preview;
  const previewLoading =
    previewable && (preview === null || preview.key !== previewKey);

  /** The cart as the server prices it: a line the preview says needs
   *  provider pricing (an agreed price that is not valid on the cart's
   *  date) loses its money and reads "prijs volgt". The preview is the
   *  authority; nothing here argues with it. `cartLineItemsPayload`
   *  sends every line in cart order, so position i answers line i. */
  const confirmLines = useMemo((): MeerwerkCartLine[] => {
    if (!previewData) return cartWithOther;
    return cartWithOther.map((line, index) => {
      const row = previewData.lines[index];
      if (row && row.price_source === "NEEDS_PROVIDER_PRICING") {
        return { ...line, unitPrice: null, vatPct: null };
      }
      return line;
    });
  }, [cartWithOther, previewData]);

  const totals = useMemo(() => {
    let subtotal = 0;
    let vat = 0;
    let priced = 0;
    let unpriced = 0;
    for (const line of confirmLines) {
      const amounts = lineAmounts(line);
      if (amounts) {
        subtotal += amounts.subtotal;
        vat += amounts.vat;
        priced += 1;
      } else {
        unpriced += 1;
      }
    }
    const cents = (n: number) => Math.round(n * 100) / 100;
    return {
      subtotal: cents(subtotal),
      total: cents(cents(subtotal) + cents(vat)),
      priced,
      unpriced,
    };
  }, [confirmLines]);

  const offeredIntents = previewData?.allowed_intents ?? [];
  const outcomeKind: MeerwerkOutcomeKind | null = previewData
    ? selectedIntent
      ? INTENT_OUTCOME[selectedIntent]
      : previewData.cart.all_agreed
        ? "instant"
        : "quote"
    : null;
  const intentErrorText = (err: { code: string; detail: string }): string => {
    const key = INTENT_ERROR_KEY[err.code as ExtraWorkIntentErrorCode];
    return key ? t(key) : err.detail;
  };
  const deadlineDaysLeft = useMemo(
    () => daysUntil(form.deadline),
    [form.deadline],
  );

  // ----- handlers --------------------------------------------------
  function update<K extends keyof ParentFormState>(
    name: K,
    value: ParentFormState[K],
  ) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function toggleLine(line: MeerwerkCartLine) {
    setCart((prev) =>
      prev.some((row) => row.key === line.key)
        ? prev.filter((row) => row.key !== line.key)
        : [...prev, line],
    );
  }
  function setQuantity(key: string, quantity: number) {
    setCart((prev) =>
      prev.map((row) =>
        row.key === key ? { ...row, quantity: Math.max(1, quantity) } : row,
      ),
    );
  }
  function setOther(key: string, patch: Partial<Pick<OtherLineDraft, "text" | "note">>) {
    setOthers((prev) =>
      prev.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    );
  }
  function addOther() {
    setOthers((prev) => [
      ...prev,
      { key: `other-${prev.length + 1}-${Date.now().toString(36)}`, text: "", note: "" },
    ]);
  }
  function removeOther(key: string) {
    setOthers((prev) => {
      const next = prev.filter((row) => row.key !== key);
      return next.length === 0 ? [emptyOtherLine(1)] : next;
    });
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!effectiveBuilding || !form.customer) {
      setError(t("create.error_building_customer_required"));
      return;
    }
    if (cartWithOther.length === 0) {
      setError(t("create.error_empty_cart"));
      return;
    }
    if (staleCustomPriceLines.length > 0) {
      setError(t("create.error_stale_custom_price"));
      return;
    }
    if (entryMode === "MULTIPLE" && slots.length === 0) {
      setError(t("series.slot_none"));
      return;
    }
    // A fresh preview must allow the chosen intent; when the server
    // already knows why it does not, say that reason.
    if (
      previewData &&
      previewData.requested_intent === selectedIntent &&
      previewData.requested_intent_allowed === false &&
      previewData.requested_intent_error
    ) {
      setError(intentErrorText(previewData.requested_intent_error));
      return;
    }
    if (
      previewData &&
      (!selectedIntent || !previewData.allowed_intents.includes(selectedIntent))
    ) {
      setError(t("create.intent.error.none_selected"));
      return;
    }
    const intentToSend =
      previewData &&
      selectedIntent &&
      previewData.allowed_intents.includes(selectedIntent)
        ? selectedIntent
        : undefined;

    setSubmitting(true);
    try {
      // ONE payload, both modes: a series member is created from
      // exactly this object, with only the title and the slot's date
      // differing per member (composed server-side).
      const payload = {
        building: Number(effectiveBuilding),
        customer: Number(form.customer),
        title: form.title.trim() || derivedTitle(cartWithOther),
        description:
          form.description.trim() ||
          derivedDescription(cartWithOther, t("common:meerwerk_flow.other_prefix")),
        urgency: form.urgent ? ("URGENT" as const) : ("NORMAL" as const),
        preferred_date: form.preferred_date || null,
        planned_end_date: form.planned_end_date || null,
        deadline: form.deadline || null,
        ...(effectiveDepartment ? { department: effectiveDepartment.id } : {}),
        ...(effectiveWorkType ? { work_type: effectiveWorkType.id } : {}),
        billed_to: billedToPayload,
        ...(intentToSend ? { request_intent: intentToSend } : {}),
        line_items: cartLineItemsPayload(cartWithOther),
      };
      if (entryMode === "MULTIPLE") {
        const batch = await batchCreateExtraWork(
          payload,
          slots,
          batchKeyRef.current,
        );
        batchKeyRef.current = crypto.randomUUID();
        setBatchResult({ group: batch.group, created: batch.created });
      } else {
        setResult(await createExtraWork(payload));
      }
    } catch (err) {
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

  // ----- W5-B: the series confirmation ------------------------------
  if (batchResult) {
    return (
      <div data-testid="extra-work-batch-result">
        <PageHeader
          eyebrow={t("common:meerwerk_flow.eyebrow")}
          title={t("series.created_title")}
        />
        <section className="card" style={{ padding: 20, maxWidth: 640 }}>
          <p style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CheckCircle2 size={18} strokeWidth={2} />
            <strong data-testid="extra-work-batch-created-count">
              {t("series.created_body", { count: batchResult.created })}
            </strong>
          </p>
          <p className="muted">{batchResult.group.standard_title}</p>
          <div className="form-actions">
            <Link
              to="/extra-work"
              className="btn btn-primary"
              data-testid="extra-work-batch-to-list"
            >
              {t("series.created_open_list")}
            </Link>
          </div>
        </section>
      </div>
    );
  }

  // ----- the confirmation --------------------------------------------
  if (result) {
    const isInstant = result.routing_decision === "INSTANT";
    const cartLineList = result.line_items ?? [];
    return (
      <div data-testid="extra-work-create-result">
        <PageHeader
          eyebrow={t("common:meerwerk_flow.eyebrow")}
          title={t("result.heading")}
          backLink={{ to: "/extra-work", label: t("back_to_extra_work") }}
        />
        <section className="card" style={{ padding: 20, marginBottom: 16 }}>
          <p
            style={{ display: "flex", alignItems: "center", gap: 8 }}
            role="status"
            data-testid={
              isInstant
                ? "extra-work-result-instant"
                : "extra-work-result-proposal"
            }
          >
            <CheckCircle2 size={18} strokeWidth={2} />
            {isInstant
              ? t("result.instant_processing")
              : t(
                  result.request_intent === "AUTO_START_AFTER_PRICING"
                    ? "result.auto_start_pending"
                    : "result.proposal_pending",
                )}
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
            <Link
              to={`/extra-work/${result.id}`}
              className="btn btn-primary btn-sm"
              data-testid="extra-work-result-view-link"
            >
              {t("result.view_request")}
            </Link>
            <Link to="/extra-work" className="btn btn-ghost btn-sm">
              {t("result.back_to_list")}
            </Link>
          </div>
        </section>
        {cartLineList.length > 0 && (
          <section className="card">
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
          </section>
        )}
      </div>
    );
  }

  // ----- the form ------------------------------------------------------
  const planningSummary = [
    form.planned_end_date &&
      `${t("detail.plannedEnd")} ${form.planned_end_date}`,
    form.deadline && `${t("detail.deadline")} ${form.deadline}`,
    entryMode === "MULTIPLE" &&
      t("create.series_summary", { count: slots.length }),
  ].filter(Boolean) as string[];

  const factValue = (key: FactKey): string => {
    if (key === "department") {
      return effectiveDepartment
        ? customerLabelName(effectiveDepartment.name, t)
        : "—";
    }
    if (key === "work_type") {
      return effectiveWorkType
        ? customerLabelName(effectiveWorkType.name, t)
        : "—";
    }
    return selectedBilledTo === "BUILDING"
      ? t("create.fact_billed_building", {
          building: chosenBuilding?.name ?? "",
        })
      : t("create.fact_billed_customer", {
          customer: chosenCustomer?.name ?? "",
        });
  };
  const factLabel: Record<FactKey, string> = {
    department: t("create.field_department"),
    work_type: t("create.field_work_type"),
    billed_to: t("create.fact_billed_to"),
  };

  return (
    <div data-testid="extra-work-create-page">
      <PageHeader
        eyebrow={t("common:meerwerk_flow.eyebrow")}
        title={t("create.page_title")}
        subtitle={t("create.page_sub")}
        backLink={{ to: "/extra-work", label: t("back_to_extra_work") }}
      />

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

      <form onSubmit={handleSubmit}>
        <div className="card create-main">
          {/* ----- Voor wie ----- */}
          <div className="form-section" data-testid="extra-work-create-who">
            <div className="form-section-title">{t("create.s_who")}</div>
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
                  onChange={(event) => {
                    // A cart belongs to a customer: their prices, their
                    // folders. A new customer starts with an empty one.
                    update("customer", event.target.value);
                    setCart([]);
                    setDepartmentId("");
                    setWorkTypeId("");
                    setBilledTo(null);
                    setEditingFact(null);
                  }}
                  disabled={customers.length === 0}
                  required
                >
                  <option value="" disabled>
                    {t("create.field_customer_placeholder")}
                  </option>
                  {customers.map((c) => (
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

            {/* The facts the choice above filled in — quiet values with
                a pencil, not four open questions. */}
            {chosenCustomer && chosenBuilding && (
              <div data-testid="extra-work-create-facts">
                <div className="ew-facts">
                  {(["department", "work_type", "billed_to"] as FactKey[]).map(
                    (key) => (
                      <button
                        key={key}
                        type="button"
                        className="ew-fact"
                        aria-expanded={editingFact === key}
                        aria-label={`${factLabel[key]}: ${factValue(key)} — ${t("create.fact_edit")}`}
                        onClick={() =>
                          setEditingFact((current) =>
                            current === key ? null : key,
                          )
                        }
                        data-testid={`extra-work-create-fact-${key}`}
                      >
                        <span className="ew-fact-key">{factLabel[key]}:</span>
                        <span>{factValue(key)}</span>
                        <span className="ew-fact-pencil">
                          <Pencil size={13} strokeWidth={2} aria-hidden />
                        </span>
                      </button>
                    ),
                  )}
                </div>
                {editingFact === "department" && (
                  <div className="ew-fact-editor field">
                    <label className="field-label" htmlFor="ew-department">
                      {t("create.field_department")}
                    </label>
                    <select
                      id="ew-department"
                      data-testid="extra-work-create-department"
                      className="field-select"
                      value={effectiveDepartment ? String(effectiveDepartment.id) : ""}
                      onChange={(event) => setDepartmentId(event.target.value)}
                      disabled={currentDepartments.length === 0}
                    >
                      {currentDepartments.map((d) => (
                        <option key={d.id} value={d.id}>
                          {customerLabelName(d.name, t)}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {editingFact === "work_type" && (
                  <div className="ew-fact-editor field">
                    <label className="field-label" htmlFor="ew-work-type">
                      {t("create.field_work_type")}
                    </label>
                    <select
                      id="ew-work-type"
                      data-testid="extra-work-create-work-type"
                      className="field-select"
                      value={effectiveWorkType ? String(effectiveWorkType.id) : ""}
                      onChange={(event) => setWorkTypeId(event.target.value)}
                      disabled={currentWorkTypes.length === 0}
                    >
                      {currentWorkTypes.map((w) => (
                        <option key={w.id} value={w.id}>
                          {customerLabelName(w.name, t)}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {editingFact === "billed_to" && (
                  <fieldset
                    className="ew-fact-editor field"
                    style={{ border: 0, padding: 0, margin: "8px 0 0" }}
                    data-testid="extra-work-create-billed-to"
                  >
                    <span className="field-label">
                      {t("create.billed_to_question")}
                    </span>
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
                          {t("create.billed_to_building_named", {
                            building: chosenBuilding.name,
                          })}
                        </strong>
                        {resolvedBilledTo === "BUILDING" && (
                          <span className="ew-billed-to-default">
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
                          <span className="ew-billed-to-default">
                            {t("create.billed_to_customer_setting")}
                          </span>
                        )}
                      </span>
                    </label>
                  </fieldset>
                )}
              </div>
            )}
          </div>

          {/* ----- Wat ----- */}
          <div className="form-section" data-testid="extra-work-create-what">
            <div className="form-section-title">{t("create.s_what")}</div>
            {!form.customer ? (
              <p className="muted small">{t("create.pick_customer_first")}</p>
            ) : (
              <>
                <PricedServicePicker
                  prices={agreedPrices}
                  customPrices={orderableCustomPrices}
                  folders={currentFolders}
                  cart={cart}
                  onToggle={toggleLine}
                  onQuantity={setQuantity}
                  showAmounts
                  emptyLabel={t("create.no_agreed_prices")}
                  testIdPrefix="extra-work-create"
                />
                <OtherLinesEditor
                  others={others}
                  onChange={setOther}
                  onAdd={addOther}
                  onRemove={removeOther}
                  helper={t("create.other_helper_provider")}
                  testIdPrefix="extra-work-create"
                />
              </>
            )}
            <details className="form-fold" data-testid="extra-work-create-fold-title">
              <summary className="form-fold-summary">
                {t("create.fold_title")}
                {form.title.trim() && (
                  <span className="form-fold-summary-value">{form.title.trim()}</span>
                )}
              </summary>
              <div className="form-fold-body">
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
                    placeholder={
                      derivedTitle(cartWithOther) || t("create.field_title_placeholder")
                    }
                    value={form.title}
                    onChange={(event) => update("title", event.target.value)}
                  />
                  <span className="muted small">{t("create.fold_title_hint")}</span>
                </div>
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
                  />
                </div>
              </div>
            </details>
          </div>

          {/* ----- Wanneer ----- */}
          <div className="form-section" data-testid="extra-work-create-when">
            <div className="form-section-title">{t("create.s_when")}</div>
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
                  const value = event.target.value;
                  setForm((current) => ({
                    ...current,
                    preferred_date: value,
                    planned_end_date: dateTakenOver.plannedEnd
                      ? current.planned_end_date
                      : value,
                    deadline: dateTakenOver.deadline ? current.deadline : value,
                  }));
                }}
              />
              <span className="muted small">{t("create.preferred_date_hint")}</span>
            </div>

            <details className="form-fold" data-testid="extra-work-create-fold-planning">
              <summary className="form-fold-summary">
                {t("create.fold_planning")}
                <span className="form-fold-summary-value">
                  {planningSummary.length > 0
                    ? planningSummary.join(" · ")
                    : t("create.fold_planning_empty")}
                </span>
              </summary>
              <div className="form-fold-body form-fold-body-planning">
                <div className="form-2col">
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
                    <span className="muted small">{t("create.plannedEndHint")}</span>
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
                    <span className="muted small">{t("create.deadlineHint")}</span>
                  </div>
                </div>

                {/* W5-B — a series: one real meerwerk per chosen day. P-1 §4:
                    one clear line of air around it. */}
                <div className="field form-fold-series">
                  <label className="ew-billed-to-option">
                    <input
                      type="checkbox"
                      checked={entryMode === "MULTIPLE"}
                      onChange={(event) =>
                        setEntryMode(event.target.checked ? "MULTIPLE" : "SINGLE")
                      }
                      data-testid="extra-work-entry-mode-multiple"
                    />
                    <span>
                      <strong>{t("create.series_toggle")}</strong>
                      <span className="muted small" style={{ display: "block" }}>
                        {t("create.series_hint")}
                      </span>
                    </span>
                  </label>
                  {entryMode === "MULTIPLE" && (
                    <div style={{ marginTop: 8 }}>
                      <span className="field-label">{t("series.slot_list")}</span>
                      <SlotPicker slots={slots} onChange={setSlots} />
                    </div>
                  )}
                </div>

              </div>
            </details>
          </div>

          {/* ----- Urgentie ----- */}
          <div className="form-section" data-testid="extra-work-create-urgency">
            <div className="form-section-title">{t("create.s_urgency")}</div>
            <label
              className="field"
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 10,
              }}
            >
              <input
                type="checkbox"
                checked={form.urgent}
                onChange={(event) => update("urgent", event.target.checked)}
                data-testid="extra-work-create-urgent"
              />
              <Siren size={14} strokeWidth={2} />
              <span>{t("create.urgent_label")}</span>
            </label>
            {form.urgent && (
              <p className="muted small" style={{ marginTop: -6 }}>
                {t("create.urgent_helper")}
              </p>
            )}
          </div>

          {/* ----- What you are creating, and what happens next ----- */}
          <div className="form-section" data-testid="extra-work-create-confirm">
            <div className="form-section-title">{t("create.confirm_title")}</div>
            {cartWithOther.length === 0 ? (
              <p className="muted small" data-testid="extra-work-create-cart-empty">
                {t("create.cart_empty")}
              </p>
            ) : (
              <>
                <CartSummaryList
                  lines={confirmLines}
                  showAmounts
                  testIdPrefix="extra-work-create"
                />
                {staleCustomPriceLines.length > 0 && (
                  <div className="alert-warning" role="status" style={{ marginTop: 8 }}>
                    {t("create.line_custom_price_stale")}
                  </div>
                )}
                <div className="meerwerk-totals" data-testid="extra-work-create-totals">
                  {totals.priced > 0 && (
                    <span>
                      {t("create.totals_line", {
                        subtotal: formatMoney(totals.subtotal),
                        total: formatMoney(totals.total),
                      })}
                    </span>
                  )}
                  {totals.unpriced > 0 && (
                    <span className="muted">
                      {t("create.price_follows_count", { count: totals.unpriced })}
                    </span>
                  )}
                </div>
                {chosenBuilding && (
                  <p className="muted small">
                    {t("common:meerwerk_flow.confirm_where_when", {
                      building: chosenBuilding.name,
                      date:
                        form.preferred_date ||
                        t("common:meerwerk_flow.no_date_wish"),
                    })}
                  </p>
                )}

                {previewLoading && (
                  <div className="loading-bar" data-testid="extra-work-create-preview-loading">
                    <div className="loading-bar-fill" />
                  </div>
                )}
                {previewFailed && (
                  <div
                    className="alert-warning"
                    role="status"
                    data-testid="extra-work-create-preview-unavailable"
                  >
                    {t("create.preview_unavailable")}
                  </div>
                )}
                {previewData && offeredIntents.length > 1 && (
                  <div
                    role="radiogroup"
                    aria-label={t("create.intent.choose")}
                    data-testid="extra-work-create-intent"
                  >
                    <div className="field-label" style={{ marginTop: 10 }}>
                      {t("create.intent.choose")}
                    </div>
                    {offeredIntents.map((intent) => (
                      <label
                        key={intent}
                        className={`meerwerk-intent-option${
                          selectedIntent === intent ? " selected" : ""
                        }`}
                        data-testid={`extra-work-create-intent-${intent}`}
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
                          {t(`common:${outcomeKey(INTENT_OUTCOME[intent], "provider")}`)}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
                {previewData && offeredIntents.length <= 1 && outcomeKind && (
                  <MeerwerkOutcome
                    audience="provider"
                    kind={outcomeKind}
                    testId="extra-work-create-outcome"
                  />
                )}
                {previewData &&
                  previewData.requested_intent === selectedIntent &&
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
              </>
            )}
          </div>

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
                cartWithOther.length === 0 ||
                !effectiveBuilding ||
                !form.customer
              }
            >
              {submitting ? t("create.submitting") : t("create.submit_button")}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
