// Sprint 7B (frontend) — Convert-to-Extra-Work dialog.
//
// Drives the DEDICATED POST /tickets/<id>/convert-to-extra-work/
// endpoint (NOT a status transition — see api/tickets.ts). The source
// ticket's customer + building come from the ticket itself, so this
// dialog only collects: the request intent (restricted to the
// provider-creatable set — REQUEST_QUOTE is excluded, mirroring how
// CreateExtraWorkPage never offers it to a provider), a small cart of
// line items (each a catalog service XOR a custom description, with a
// quantity, requested date, and optional customer note — mirrors
// ExtraWorkPreviewLineSerializer / the CreateExtraWorkPage cart line),
// and optional customer-visible / internal notes.
//
// On success the parent navigates to the new ExtraWorkRequest. Backend
// field/validation errors are surfaced via getApiError. This file owns
// ONLY this component (no other module exports) to satisfy
// react-refresh/only-export-components.
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  listCustomerPriceFolders,
  listCustomerPrices,
  listServiceCategories,
  listServices,
} from "../api/admin";
import { getApiError } from "../api/client";
import { convertTicketToExtraWork } from "../api/tickets";
import type {
  CustomerPriceFolder,
  ExtraWorkRequestIntent,
  Service,
  ServiceCategory,
  TicketConvertLinePayload,
} from "../api/types";

// Provider-creatable intents only. The backend convert endpoint
// technically also accepts REQUEST_QUOTE on conversion, but the product
// rule (and the CreateExtraWorkPage provider experience) is that
// providers compose either a direct agreed-price order or an
// auto-start-after-pricing request — quoting is a customer-initiated
// flow. Mirror that restriction here.
const PROVIDER_CONVERT_INTENTS: ExtraWorkRequestIntent[] = [
  "DIRECT_AGREED_PRICE_ORDER",
  "AUTO_START_AFTER_PRICING",
];

const INTENT_LABEL_KEY: Record<ExtraWorkRequestIntent, string> = {
  DIRECT_AGREED_PRICE_ORDER: "convert.intent_direct_label",
  AUTO_START_AFTER_PRICING: "convert.intent_auto_start_label",
  REQUEST_QUOTE: "convert.intent_request_quote_label",
};
const INTENT_DESC_KEY: Record<ExtraWorkRequestIntent, string> = {
  DIRECT_AGREED_PRICE_ORDER: "convert.intent_direct_desc",
  AUTO_START_AFTER_PRICING: "convert.intent_auto_start_desc",
  REQUEST_QUOTE: "convert.intent_request_quote_desc",
};

type LineMode = "service" | "custom";

interface ConvertLineState {
  tempId: string;
  mode: LineMode;
  serviceId: string;
  customDescription: string;
  quantity: string;
  requestedDate: string;
  customerNote: string;
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function nextTempId(): string {
  return `cline-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function emptyLine(): ConvertLineState {
  return {
    tempId: nextTempId(),
    mode: "service",
    serviceId: "",
    customDescription: "",
    quantity: "1",
    requestedDate: todayISO(),
    customerNote: "",
  };
}

// A line is valid when it carries exactly one of service / custom
// description, a positive quantity, and a date — exactly what the
// backend ExtraWorkPreviewLineSerializer requires per line.
function lineIsValid(line: ConvertLineState): boolean {
  const q = Number(line.quantity);
  if (!Number.isFinite(q) || q <= 0) return false;
  if (!line.requestedDate) return false;
  if (line.mode === "service") return Boolean(line.serviceId);
  return Boolean(line.customDescription.trim());
}

export interface ConvertToExtraWorkDialogProps {
  ticketId: number;
  // Sprint 143 §5 — the ticket's customer. Always known here, which
  // makes this the "customer chosen" case of the Extra Work form's
  // filter: company categories PLUS that customer's price folders.
  customerId: number;
  /** Sprint 187 §6b — the ticket's PROVIDER company, used to scope the
   *  service + category pickers. `TicketDetail` inherits `company` from
   *  `TicketList`, so the caller already has it and nothing extra is
   *  fetched. Without it a SUPER_ADMIN was offered every company's
   *  services and the save was rejected server-side. */
  companyId: number;
  onClose: () => void;
  // Called with the new ExtraWorkRequest id after a successful convert
  // so the parent can navigate to /extra-work/<id>.
  onConverted: (extraWorkRequestId: number) => void;
}

export function ConvertToExtraWorkDialog({
  ticketId,
  customerId,
  companyId,
  onClose,
  onConverted,
}: ConvertToExtraWorkDialogProps) {
  const { t } = useTranslation(["ticket_detail", "common", "extra_work"]);

  const [services, setServices] = useState<Service[]>([]);
  const [servicesLoading, setServicesLoading] = useState(true);
  // Sprint 143 §5 — the same catalog filter `CreateExtraWorkPage` has,
  // and the same guards. This dialog was a flat list with neither: the
  // provider converting a ticket for a customer needs to narrow by the
  // same groupings the customer-facing form offers.
  //
  // Prefixed values so one control offers two kinds of grouping without
  // their ids colliding: "" | "cat:<id>" | "fol:<id>".
  const [categoryFilter, setCategoryFilter] = useState("");
  const [serviceSearch, setServiceSearch] = useState("");
  const [categories, setCategories] = useState<ServiceCategory[]>([]);
  const [folders, setFolders] = useState<CustomerPriceFolder[]>([]);
  const [folderServiceIds, setFolderServiceIds] = useState<
    Map<number, Set<number>>
  >(new Map());
  const [intent, setIntent] = useState<ExtraWorkRequestIntent>(
    PROVIDER_CONVERT_INTENTS[0],
  );
  const [lines, setLines] = useState<ConvertLineState[]>([emptyLine()]);
  const [customerVisibleNote, setCustomerVisibleNote] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    // Sprint 187 §6b — scoped to the TICKET's provider company. This
    // picker offered every company's services to a SUPER_ADMIN (and to
    // a COMPANY_ADMIN with two memberships), and choosing one from
    // another company failed the save with "Service belongs to a
    // different provider company than the customer" — one layer below
    // where Sprint 186 fixed the same shape. No backend change:
    // `ServiceListParams.company` and the endpoint's `?company=` have
    // both existed since the catalog was made per-company.
    listServices({ is_active: true, company: companyId })
      .then((list) => {
        if (cancelled) return;
        setServices(list);
        setServicesLoading(false);
      })
      .catch(() => {
        // Services are soft-required: without the catalog the operator
        // can still convert using custom-description lines. Degrade to
        // an empty list rather than blocking the dialog.
        if (cancelled) return;
        setServices([]);
        setServicesLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Sprint 187 §6b — `companyId` is a real dependency now: the catalog
    // fetched is the one belonging to THIS ticket's provider company.
  }, [companyId]);

  // Sprint 143 §5 — the filter's two option groups. ACTIVE only on both
  // sides: the form offers what can be ordered NOW, so an archived
  // category or folder must not appear. Every branch degrades to an
  // empty list rather than blocking the dialog — losing the filter is
  // recoverable, losing the convert is not.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listServiceCategories({ is_active: true, company: companyId }).catch(
        () => [] as ServiceCategory[],
      ),
      listCustomerPriceFolders(customerId, { is_active: true }).catch(
        () => [] as CustomerPriceFolder[],
      ),
      listCustomerPrices(customerId).catch(() => []),
    ]).then(([categoryRows, folderRows, priceRows]) => {
      if (cancelled) return;
      setCategories(categoryRows);
      setFolders(folderRows);
      const map = new Map<number, Set<number>>();
      for (const row of priceRows) {
        if (row.folder === null) continue;
        const bucket = map.get(row.folder);
        if (bucket) bucket.add(row.service);
        else map.set(row.folder, new Set([row.service]));
      }
      setFolderServiceIds(map);
    });
    return () => {
      cancelled = true;
    };
  }, [customerId, companyId]);

  const serviceSearchTerm = serviceSearch.trim().toLowerCase();

  // GUARD 3 — search spans the ENTIRE catalog; the category filter is
  // deliberately ignored while searching. Every option label carries its
  // category name, so a match from outside the filter is self-describing.
  const searchMatches = useMemo(() => {
    if (!serviceSearchTerm) return null;
    return services.filter((svc) =>
      `${svc.category_name} ${svc.name}`.toLowerCase().includes(
        serviceSearchTerm,
      ),
    );
  }, [services, serviceSearchTerm]);

  const categoryFilteredServices = useMemo(() => {
    if (!categoryFilter) return services;
    if (categoryFilter.startsWith("cat:")) {
      const id = Number(categoryFilter.slice(4));
      return services.filter((svc) => svc.category === id);
    }
    if (categoryFilter.startsWith("fol:")) {
      const ids = folderServiceIds.get(Number(categoryFilter.slice(4)));
      if (!ids) return [];
      return services.filter((svc) => ids.has(svc.id));
    }
    return services;
  }, [services, categoryFilter, folderServiceIds]);

  const offeredServices = searchMatches ?? categoryFilteredServices;
  const narrowingActive =
    Boolean(categoryFilter) || Boolean(serviceSearchTerm);
  const hiddenServiceCount = services.length - offeredServices.length;

  /**
   * GUARD 1 — the service a line ALREADY holds is always in that line's
   * own options, even when the active filter would exclude it.
   * Otherwise narrowing the filter silently blanks a line the operator
   * has already built, which is the failure this whole guard set exists
   * to prevent.
   *
   * GUARD 4 — and the list is never bare: with a filter that matches
   * nothing, the line still offers its own selection.
   */
  function optionsForLine(line: ConvertLineState): Service[] {
    if (!line.serviceId) return offeredServices;
    const selectedId = Number(line.serviceId);
    if (offeredServices.some((svc) => svc.id === selectedId)) {
      return offeredServices;
    }
    const selected = services.find((svc) => svc.id === selectedId);
    return selected ? [selected, ...offeredServices] : offeredServices;
  }

  /**
   * GUARD 2 — picking a service from OUTSIDE the active filter clears
   * that filter, so the list on screen never contradicts the line just
   * built.
   */
  function onLineServiceChange(tempId: string, value: string) {
    updateLine(tempId, "serviceId", value);
    if (!categoryFilter || !value) return;
    const picked = services.find((svc) => svc.id === Number(value));
    if (!picked) return;
    const stillMatches = categoryFilter.startsWith("cat:")
      ? picked.category === Number(categoryFilter.slice(4))
      : categoryFilter.startsWith("fol:")
        ? (
            folderServiceIds.get(Number(categoryFilter.slice(4))) ??
            new Set<number>()
          ).has(picked.id)
        : true;
    if (!stillMatches) setCategoryFilter("");
  }

  const canSubmit = useMemo(
    () => lines.length > 0 && lines.every(lineIsValid),
    [lines],
  );

  function addLine() {
    setLines((current) => [...current, emptyLine()]);
  }

  function removeLine(tempId: string) {
    setLines((current) => current.filter((l) => l.tempId !== tempId));
  }

  function updateLine<K extends keyof ConvertLineState>(
    tempId: string,
    field: K,
    value: ConvertLineState[K],
  ) {
    setLines((current) =>
      current.map((line) =>
        line.tempId === tempId ? { ...line, [field]: value } : line,
      ),
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!canSubmit) {
      setError(t("convert.error_line_invalid"));
      return;
    }
    const lineItems: TicketConvertLinePayload[] = lines.map((line) =>
      line.mode === "service"
        ? {
            service: Number(line.serviceId),
            quantity: line.quantity,
            requested_date: line.requestedDate,
            customer_note: line.customerNote.trim() || undefined,
          }
        : {
            custom_description: line.customDescription.trim(),
            quantity: line.quantity,
            requested_date: line.requestedDate,
            customer_note: line.customerNote.trim() || undefined,
          },
    );
    setSubmitting(true);
    try {
      const result = await convertTicketToExtraWork(ticketId, {
        request_intent: intent,
        line_items: lineItems,
        customer_visible_note: customerVisibleNote.trim() || undefined,
        internal_note: internalNote.trim() || undefined,
      });
      onConverted(result.extra_work_request.id);
    } catch (err) {
      setError(getApiError(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="reject-modal-backdrop" data-testid="convert-to-ew-modal">
      <div
        className="reject-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t("convert.dialog_title")}
        style={{ maxWidth: 640 }}
      >
        <h3 className="reject-modal-title">{t("convert.dialog_title")}</h3>
        <p className="reject-modal-desc">{t("convert.dialog_desc")}</p>

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: 14 }}
        >
          {/* ----- Intent selector (restricted) ----- */}
          <div
            role="radiogroup"
            aria-label={t("convert.intent_section_title")}
            data-testid="convert-to-ew-intent"
          >
            <span
              className="field-label"
              style={{ display: "block", marginBottom: 8 }}
            >
              {t("convert.intent_section_title")}
            </span>
            {PROVIDER_CONVERT_INTENTS.map((option) => (
              <label
                key={option}
                className="login-check"
                data-testid={`convert-to-ew-intent-${option}`}
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "flex-start",
                  marginBottom: 8,
                  cursor: "pointer",
                }}
              >
                <input
                  type="radio"
                  name="convert-request-intent"
                  value={option}
                  checked={intent === option}
                  onChange={() => setIntent(option)}
                  style={{ marginTop: 3 }}
                />
                <span>
                  <span
                    className="field-label"
                    style={{ display: "block", marginBottom: 2 }}
                  >
                    {t(INTENT_LABEL_KEY[option])}
                  </span>
                  <span className="muted small">
                    {t(INTENT_DESC_KEY[option])}
                  </span>
                </span>
              </label>
            ))}
          </div>

          {/* ----- Line items composer ----- */}
          <div data-testid="convert-to-ew-lines">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <span className="field-label" style={{ margin: 0 }}>
                {t("convert.lines_section_title")}
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={addLine}
                data-testid="convert-to-ew-add-line"
              >
                <Plus size={14} strokeWidth={2.2} />
                <span style={{ marginLeft: 6 }}>
                  {t("convert.add_line_button")}
                </span>
              </button>
            </div>
            {servicesLoading && (
              <p className="muted small" style={{ margin: "0 0 8px" }}>
                {t("convert.services_loading")}
              </p>
            )}

            {/* Sprint 143 §5 — the catalog filter, mirroring
                CreateExtraWorkPage's. */}
            <div className="form-2col" style={{ marginBottom: 12 }}>
              <div className="field">
                <label
                  className="field-label"
                  htmlFor="convert-catalog-category"
                >
                  {t("extra_work:create.catalog_filter.category_label")}
                </label>
                <select
                  id="convert-catalog-category"
                  className="field-select"
                  data-testid="convert-to-ew-catalog-category"
                  value={categoryFilter}
                  onChange={(event) => setCategoryFilter(event.target.value)}
                >
                  <option value="">
                    {t("extra_work:create.catalog_filter.all_categories")}
                  </option>
                  {categories.length > 0 && (
                    <optgroup
                      label={t("extra_work:create.catalog_filter.group_categories")}
                    >
                      {categories.map((c) => (
                        <option key={`cat-${c.id}`} value={`cat:${c.id}`}>
                          {c.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {folders.length > 0 && (
                    <optgroup
                      label={t("extra_work:create.catalog_filter.group_folders")}
                    >
                      {folders.map((f) => (
                        <option key={`fol-${f.id}`} value={`fol:${f.id}`}>
                          {f.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="convert-catalog-search">
                  {t("extra_work:create.catalog_filter.search_label")}
                </label>
                <input
                  id="convert-catalog-search"
                  className="field-input"
                  type="search"
                  data-testid="convert-to-ew-catalog-search"
                  placeholder={t(
                    "extra_work:create.catalog_filter.search_placeholder",
                  )}
                  value={serviceSearch}
                  onChange={(event) => setServiceSearch(event.target.value)}
                />
              </div>
            </div>
            {narrowingActive && hiddenServiceCount > 0 && (
              <p
                className="muted small"
                style={{ margin: "0 0 8px" }}
                data-testid="convert-to-ew-catalog-narrowed"
              >
                {t("extra_work:create.catalog_filter.hidden_note", {
                  shown: offeredServices.length,
                  total: services.length,
                })}{" "}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="convert-to-ew-catalog-clear"
                  onClick={() => {
                    setCategoryFilter("");
                    setServiceSearch("");
                  }}
                >
                  {t("extra_work:create.catalog_filter.clear")}
                </button>
              </p>
            )}

            {lines.map((line, index) => (
              <div
                key={line.tempId}
                className="field"
                data-testid="convert-to-ew-line"
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: 12,
                  marginBottom: 10,
                  gap: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <select
                    className="field-select"
                    aria-label={t("convert.line_mode_label")}
                    data-testid={`convert-to-ew-line-mode-${index}`}
                    value={line.mode}
                    onChange={(event) =>
                      updateLine(
                        line.tempId,
                        "mode",
                        event.target.value as LineMode,
                      )
                    }
                    style={{ flex: "0 0 auto", width: "auto" }}
                  >
                    <option value="service">
                      {t("convert.line_mode_service")}
                    </option>
                    <option value="custom">
                      {t("convert.line_mode_custom")}
                    </option>
                  </select>
                  {lines.length > 1 && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => removeLine(line.tempId)}
                      data-testid={`convert-to-ew-remove-line-${index}`}
                      style={{ marginLeft: "auto" }}
                    >
                      <Trash2 size={14} strokeWidth={2.2} />
                      <span style={{ marginLeft: 6 }}>
                        {t("convert.remove_line_button")}
                      </span>
                    </button>
                  )}
                </div>

                {line.mode === "service" ? (
                  <select
                    className="field-select"
                    aria-label={t("convert.line_service_label")}
                    data-testid={`convert-to-ew-line-service-${index}`}
                    value={line.serviceId}
                    onChange={(event) =>
                      onLineServiceChange(line.tempId, event.target.value)
                    }
                  >
                    <option value="" disabled>
                      {t("convert.line_service_placeholder")}
                    </option>
                    {optionsForLine(line).map((svc) => (
                      <option key={svc.id} value={svc.id}>
                        {svc.category_name
                          ? `${svc.category_name} — ${svc.name}`
                          : svc.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="field-input"
                    type="text"
                    maxLength={255}
                    aria-label={t("convert.line_custom_label")}
                    data-testid={`convert-to-ew-line-custom-${index}`}
                    placeholder={t("convert.line_custom_placeholder")}
                    value={line.customDescription}
                    onChange={(event) =>
                      updateLine(
                        line.tempId,
                        "customDescription",
                        event.target.value,
                      )
                    }
                  />
                )}

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <input
                    className="field-input"
                    type="number"
                    step="0.01"
                    min="0"
                    aria-label={t("convert.line_quantity_label")}
                    data-testid={`convert-to-ew-line-quantity-${index}`}
                    placeholder={t("convert.line_quantity_label")}
                    value={line.quantity}
                    onChange={(event) =>
                      updateLine(line.tempId, "quantity", event.target.value)
                    }
                    style={{ flex: "1 1 90px", minWidth: 80 }}
                  />
                  <input
                    className="field-input"
                    type="date"
                    aria-label={t("convert.line_date_label")}
                    data-testid={`convert-to-ew-line-date-${index}`}
                    value={line.requestedDate}
                    onChange={(event) =>
                      updateLine(
                        line.tempId,
                        "requestedDate",
                        event.target.value,
                      )
                    }
                    style={{ flex: "1 1 140px", minWidth: 130 }}
                  />
                </div>

                <input
                  className="field-input"
                  type="text"
                  maxLength={500}
                  aria-label={t("convert.line_note_label")}
                  data-testid={`convert-to-ew-line-note-${index}`}
                  placeholder={t("convert.line_note_placeholder")}
                  value={line.customerNote}
                  onChange={(event) =>
                    updateLine(line.tempId, "customerNote", event.target.value)
                  }
                />
              </div>
            ))}
          </div>

          {/* ----- Optional notes ----- */}
          <div className="field">
            <label
              className="field-label"
              htmlFor="convert-to-ew-customer-note"
            >
              {t("convert.customer_visible_note_label")}
            </label>
            <textarea
              id="convert-to-ew-customer-note"
              className="field-textarea"
              data-testid="convert-to-ew-customer-note"
              rows={2}
              placeholder={t("convert.customer_visible_note_placeholder")}
              value={customerVisibleNote}
              onChange={(event) => setCustomerVisibleNote(event.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="convert-to-ew-internal-note">
              {t("convert.internal_note_label")}
            </label>
            <textarea
              id="convert-to-ew-internal-note"
              className="field-textarea"
              data-testid="convert-to-ew-internal-note"
              rows={2}
              placeholder={t("convert.internal_note_placeholder")}
              value={internalNote}
              onChange={(event) => setInternalNote(event.target.value)}
            />
          </div>

          {error && (
            <div
              className="alert-error"
              role="alert"
              data-testid="convert-to-ew-error"
            >
              {error}
            </div>
          )}

          <div className="reject-modal-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              disabled={submitting}
              data-testid="convert-to-ew-cancel"
            >
              {t("convert.cancel_button")}
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm reject-modal-confirm"
              disabled={submitting || !canSubmit}
              data-testid="convert-to-ew-submit"
            >
              {submitting
                ? t("convert.submitting")
                : t("convert.submit_button")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
