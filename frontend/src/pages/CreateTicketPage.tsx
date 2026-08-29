/**
 * FE-5 (Addendum D §D.7 "Ticket create (provider)") — the provider's
 * ticket form, trimmed.
 *
 * Voor wie (customer + building), ONE description (its first line is
 * the title — the same `titleFrom` mapping the customer's melding form
 * uses; the endpoint is unchanged), the priority cards (providers live
 * by SLA), photos and files. Type, room/zone and the customer's wished
 * date fold under "Meer details". The side column keeps three lines
 * that earn their place and nothing else.
 */
import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CircleCheck,
  Info,
  TriangleAlert,
  UploadCloud,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { listAllBuildings, listAllCustomers } from "../api/admin";
import { api, getApiError } from "../api/client";
import type { Building, Customer, TicketCategory } from "../api/types";
import { listTicketCategories } from "../api/tickets";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { titleFrom } from "../lib/meldingTitle";

interface CreateTicketForm {
  description: string;
  room_label: string;
  priority: string;
  building: string;
  customer: string;
  /** Sprint 184 §3 — the date the CUSTOMER would like this done. A WISH,
   *  never a deadline. */
  customer_wanted_date: string;
  /** W13 — THE classification; "" means "not yet classified". */
  category: string;
}

type PriorityValue = "NORMAL" | "HIGH" | "URGENT";

interface PriorityCard {
  value: PriorityValue;
  labelKey: string;
  helperKey: string;
  icon: typeof Info;
}

const PRIORITY_CARDS: PriorityCard[] = [
  {
    value: "NORMAL",
    labelKey: "priority_normal_label",
    helperKey: "priority_normal_helper",
    icon: CircleCheck,
  },
  {
    value: "HIGH",
    labelKey: "priority_high_label",
    helperKey: "priority_high_helper",
    icon: TriangleAlert,
  },
  {
    value: "URGENT",
    labelKey: "priority_urgent_label",
    helperKey: "priority_urgent_helper",
    icon: AlertTriangle,
  },
];

const EMPTY_FORM: CreateTicketForm = {
  description: "",
  room_label: "",
  priority: "NORMAL",
  building: "",
  customer: "",
  customer_wanted_date: "",
  category: "",
};

// Mirrors the backend per-file cap in
// `tickets/serializers.py::TicketAttachmentSerializer.validate_file`.
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

const ATTACHMENT_ACCEPT = ".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf";

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

const TIP_KEYS = ["tip_1", "tip_2", "tip_3"] as const;

/** W13 — what `/new` already asked, as a category SLUG in the URL. */
function readCategoryParam(): string | null {
  return new URLSearchParams(window.location.search).get("category");
}

export function CreateTicketPage() {
  const navigate = useNavigate();
  const { t } = useTranslation(["create_ticket", "common"]);
  const { me } = useAuth();

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<CreateTicketForm>(EMPTY_FORM);
  /** W13 — the company's categories, ACTIVE and AVAILABLE AT INTAKE. */
  const [categories, setCategories] = useState<TicketCategory[]>([]);
  /** W13 — what `/new` already asked, as a category SLUG; applied once
   *  the catalog has loaded. */
  const preselectSlug = useRef(readCategoryParam());
  /** The "Meer details" fold opens by itself when the door already
   *  answered the Type question, so the answer is on screen. */
  const [detailsOpen, setDetailsOpen] = useState(
    () => readCategoryParam() !== null,
  );
  const [stagedAttachments, setStagedAttachments] = useState<File[]>([]);
  const [partialUpload, setPartialUpload] = useState<{
    ticketId: number;
    failed: string[];
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadOptions() {
      try {
        const [buildingResponse, customerResponse] = await Promise.all([
          listAllBuildings(),
          listAllCustomers(),
        ]);
        if (cancelled) return;
        setBuildings(buildingResponse);
        setCustomers(customerResponse);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoadingOptions(false);
      }
    }
    loadOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  const customerMatchesBuilding = (
    customer: Customer,
    buildingId: number,
  ): boolean =>
    customer.building === buildingId ||
    (customer.linked_building_ids?.includes(buildingId) ?? false);

  const filteredBuildings = useMemo(() => {
    if (!form.customer) return buildings;
    const c = customers.find((x) => String(x.id) === form.customer);
    if (!c) return buildings;
    return buildings.filter((b) => customerMatchesBuilding(c, b.id));
  }, [buildings, customers, form.customer]);

  // A building chosen before the customer changed may not belong to
  // the new customer; it collapses to "" at the point of use (no
  // resync effect — CLAUDE.md's setState-in-effect rule).
  const effectiveBuilding = filteredBuildings.some(
    (b) => String(b.id) === form.building,
  )
    ? form.building
    : "";

  /** Building picked first with exactly one customer on it: fill the
   *  customer, save the click. In the change handler, not an effect. */
  function pickBuilding(value: string) {
    setForm((current) => {
      if (current.customer || !value) return { ...current, building: value };
      const buildingId = Number(value);
      const matches = customers.filter((c) =>
        customerMatchesBuilding(c, buildingId),
      );
      return {
        ...current,
        building: value,
        customer: matches.length === 1 ? String(matches[0].id) : "",
      };
    });
  }

  // W14 §1 — the categories of THE company this ticket will belong to,
  // resolved from the building, else the customer's building, else the
  // author's own single company. No company, no list — never every
  // tenant's.
  const intakeCompanyId = useMemo(() => {
    if (effectiveBuilding) {
      const fromBuilding = buildings.find(
        (b) => b.id === Number(effectiveBuilding),
      )?.company;
      if (fromBuilding) return fromBuilding;
    }
    if (form.customer) {
      const customer = customers.find((c) => String(c.id) === form.customer);
      const fromCustomer = customer
        ? buildings.find((b) => customerMatchesBuilding(customer, b.id))
            ?.company
        : undefined;
      if (fromCustomer) return fromCustomer;
    }
    if (me?.company_ids?.length === 1) return me.company_ids[0];
    return undefined;
  }, [buildings, customers, effectiveBuilding, form.customer, me]);

  useEffect(() => {
    let cancelled = false;
    if (!intakeCompanyId) return;
    listTicketCategories({
      is_active: "true",
      available_at_intake: "true",
      company: intakeCompanyId,
    })
      .then((rows) => {
        if (cancelled) return;
        setCategories(rows);
        const slug = preselectSlug.current;
        preselectSlug.current = null;
        if (!slug) return;
        const match = rows.find((row) => row.slug === slug);
        if (match) {
          setForm((current) =>
            current.category === ""
              ? { ...current, category: String(match.id) }
              : current,
          );
        }
      })
      .catch(() => {
        /* non-fatal: the ticket can be opened uncategorised */
      });
    return () => {
      cancelled = true;
    };
  }, [intakeCompanyId]);

  const categoryOptions = useMemo(
    () =>
      intakeCompanyId
        ? categories.filter((row) => row.company === intakeCompanyId)
        : [],
    [categories, intakeCompanyId],
  );
  const selectedCategory = useMemo(
    () =>
      categoryOptions.find((row) => String(row.id) === form.category) ?? null,
    [categoryOptions, form.category],
  );

  function update<K extends keyof CreateTicketForm>(
    name: K,
    value: CreateTicketForm[K],
  ) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const text = form.description.trim();
    if (!text) {
      setError(t("validation_description_required"));
      return;
    }
    if (!form.customer) {
      setError(t("validation_customer_required"));
      return;
    }
    if (!effectiveBuilding) {
      setError(t("validation_location_required"));
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.post<{ id: number }>("/tickets/", {
        title: titleFrom(text),
        description: text,
        room_label: form.room_label.trim(),
        priority: form.priority,
        building: Number(effectiveBuilding),
        customer: Number(form.customer),
        customer_wanted_date: form.customer_wanted_date || null,
        ...(selectedCategory ? { category: selectedCategory.id } : {}),
      });
      const newId = response.data.id;

      // ONE file per request; sequential so a failure names its file.
      // The ticket is never rolled back.
      const failed: string[] = [];
      for (const file of stagedAttachments) {
        try {
          const formData = new FormData();
          formData.append("file", file);
          await api.post(`/tickets/${newId}/attachments/`, formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch {
          failed.push(file.name);
        }
      }
      if (failed.length > 0) {
        setPartialUpload({ ticketId: newId, failed });
        setError("");
        return;
      }
      navigate(`/tickets/${newId}`);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const noOptions =
    !loadingOptions && (buildings.length === 0 || customers.length === 0);

  const detailsSummary = [
    selectedCategory?.label,
    form.room_label.trim(),
    form.customer_wanted_date,
  ].filter(Boolean) as string[];

  return (
    <div data-testid="create-ticket-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        subtitle={t("subtitle")}
        backLink={{ to: "/tickets", label: t("back_to_tickets") }}
      />

      {loadingOptions && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}
      {noOptions && !error && (
        <div className="alert-error" style={{ marginBottom: 16 }}>
          {t("no_access_message")}
        </div>
      )}

      <form className="create-layout" onSubmit={handleSubmit}>
        <div className="card create-main">
          {/* Voor wie */}
          <div className="form-section">
            <div className="form-section-title">{t("section_who")}</div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="f-customer">
                  {t("field_customer_label")}
                </label>
                <select
                  id="f-customer"
                  className="field-select"
                  value={form.customer}
                  onChange={(event) => update("customer", event.target.value)}
                  disabled={customers.length === 0}
                  required
                  data-testid="create-ticket-customer"
                >
                  <option value="" disabled>
                    {customers.length === 0
                      ? t("field_customer_no_options")
                      : t("field_customer_placeholder")}
                  </option>
                  {customers.map((customer) => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="f-building">
                  {t("field_location_label")}
                </label>
                <select
                  id="f-building"
                  className="field-select"
                  value={effectiveBuilding}
                  onChange={(event) => pickBuilding(event.target.value)}
                  disabled={filteredBuildings.length === 0}
                  required
                  data-testid="create-ticket-building"
                >
                  <option value="" disabled>
                    {t("field_location_placeholder")}
                  </option>
                  {filteredBuildings.map((building) => (
                    <option key={building.id} value={building.id}>
                      {building.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Wat is er aan de hand — the one description */}
          <div className="form-section">
            <div className="form-section-title">{t("section_what")}</div>
            <div className="field">
              <label className="field-label" htmlFor="f-desc">
                {t("field_description_label")}
              </label>
              <textarea
                id="f-desc"
                className="field-textarea"
                rows={5}
                placeholder={t("field_description_placeholder")}
                value={form.description}
                onChange={(event) => update("description", event.target.value)}
                required
                data-testid="create-ticket-description"
              />
            </div>

            <details
              className="form-fold"
              open={detailsOpen}
              onToggle={(event) =>
                setDetailsOpen((event.target as HTMLDetailsElement).open)
              }
              data-testid="create-ticket-fold-details"
            >
              <summary className="form-fold-summary">
                {t("fold_details")}
                <span className="form-fold-summary-value">
                  {detailsSummary.length > 0
                    ? detailsSummary.join(" · ")
                    : t("fold_details_empty")}
                </span>
              </summary>
              <div className="form-fold-body">
                <div className="form-2col">
                  {categoryOptions.length > 0 && (
                    <div className="field">
                      <label className="field-label" htmlFor="f-category">
                        {t("field_category_label")}
                      </label>
                      <select
                        id="f-category"
                        className="field-select"
                        value={selectedCategory === null ? "" : form.category}
                        onChange={(event) => update("category", event.target.value)}
                        data-testid="create-ticket-category"
                      >
                        <option value="">
                          {t("common:ticket_categories.none")}
                        </option>
                        {categoryOptions.map((row) => (
                          <option key={row.id} value={row.id}>
                            {row.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <div className="field">
                    <label className="field-label" htmlFor="f-room">
                      {t("field_room_label")}
                    </label>
                    <input
                      id="f-room"
                      className="field-input"
                      type="text"
                      placeholder={t("field_room_placeholder")}
                      value={form.room_label}
                      onChange={(event) => update("room_label", event.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label className="field-label" htmlFor="f-wanted-date">
                      {t("field_wanted_date_label")}
                    </label>
                    <input
                      id="f-wanted-date"
                      className="field-input"
                      type="date"
                      value={form.customer_wanted_date}
                      onChange={(event) =>
                        update("customer_wanted_date", event.target.value)
                      }
                      data-testid="create-ticket-wanted-date"
                    />
                    <span className="muted small">
                      {t("field_wanted_date_helper")}
                    </span>
                  </div>
                </div>
              </div>
            </details>
          </div>

          {/* Prioriteit */}
          <div className="form-section">
            <div className="form-section-title">
              {t("section_priority_title")}
            </div>
            <div className="form-section-helper">
              {t("section_priority_helper")}
            </div>
            <div className="priority-grid">
              {PRIORITY_CARDS.map((card) => {
                const Icon = card.icon;
                const isSelected = form.priority === card.value;
                return (
                  <button
                    type="button"
                    key={card.value}
                    data-prio={card.value}
                    className={`priority-card ${isSelected ? "selected" : ""}`}
                    onClick={() => update("priority", card.value)}
                  >
                    <span className="priority-card-icon">
                      <Icon size={16} strokeWidth={2} />
                    </span>
                    <span className="priority-card-label">
                      {t(card.labelKey)}
                    </span>
                    <span className="priority-card-helper">
                      {t(card.helperKey)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Foto's en bestanden */}
          <div className="form-section">
            <div className="form-section-title">
              {t("section_attachments_title")}
            </div>
            <label className="upload-zone">
              <UploadCloud className="upload-icon" size={22} strokeWidth={2} />
              <span className="upload-title">{t("attachment_drop_hint")}</span>
              <span className="upload-hint">{t("attachment_size_hint")}</span>
              <input
                type="file"
                accept={ATTACHMENT_ACCEPT}
                multiple
                onChange={(event) => {
                  const picked = Array.from(event.target.files ?? []);
                  event.target.value = "";
                  if (picked.length === 0) return;
                  const tooLarge = picked.filter(
                    (file) => file.size > MAX_ATTACHMENT_BYTES,
                  );
                  const accepted = picked.filter(
                    (file) => file.size <= MAX_ATTACHMENT_BYTES,
                  );
                  setError(
                    tooLarge.length > 0
                      ? `${t("attachment_too_large")} ${tooLarge
                          .map((file) => file.name)
                          .join(", ")}`
                      : "",
                  );
                  if (accepted.length > 0) {
                    setStagedAttachments((current) => {
                      const seen = new Set(current.map(fileKey));
                      return [
                        ...current,
                        ...accepted.filter((file) => !seen.has(fileKey(file))),
                      ];
                    });
                  }
                }}
              />
            </label>
            {stagedAttachments.length > 0 && (
              <ul className="staged-attachment-list">
                {stagedAttachments.map((file) => (
                  <li key={fileKey(file)} className="staged-attachment-row">
                    <span className="staged-attachment-name">{file.name}</span>
                    <span className="staged-attachment-size">
                      {(file.size / 1024 / 1024).toFixed(2)} MB
                    </span>
                    <button
                      type="button"
                      className="staged-attachment-remove"
                      onClick={() =>
                        setStagedAttachments((current) =>
                          current.filter(
                            (candidate) => fileKey(candidate) !== fileKey(file),
                          ),
                        )
                      }
                      aria-label={`${t("attachment_remove")} ${file.name}`}
                    >
                      <X size={15} strokeWidth={2} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {error && (
            <div
              className="alert-error"
              style={{ margin: "0 22px 18px" }}
              role="alert"
              data-testid="create-ticket-error"
            >
              {error}
            </div>
          )}

          {partialUpload && (
            <div
              className="alert-error"
              style={{ margin: "0 22px 18px" }}
              role="alert"
              data-testid="create-ticket-partial-upload"
            >
              <div>
                {t("attachment_partial_failure", {
                  count: partialUpload.failed.length,
                })}
              </div>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {partialUpload.failed.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="form-actions">
            <Link to="/tickets" className="btn btn-secondary">
              {t("cancel")}
            </Link>
            {partialUpload ? (
              <Link
                to={`/tickets/${partialUpload.ticketId}`}
                className="btn btn-primary"
                data-testid="create-ticket-goto-ticket"
              >
                {t("attachment_partial_goto_ticket")}
                <ArrowRight size={14} strokeWidth={2.5} />
              </Link>
            ) : (
              <button
                type="submit"
                className="btn btn-primary"
                disabled={submitting || loadingOptions || noOptions}
                data-testid="create-ticket-submit"
              >
                {submitting ? t("creating") : t("submit")}
                <ArrowRight size={14} strokeWidth={2.5} />
              </button>
            )}
          </div>
        </div>

        {/* The side column: three lines that earn their place. */}
        <aside className="create-side">
          <div className="card">
            <div className="section-head">
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <Info size={16} strokeWidth={2} color="var(--green-2)" />
                <div className="section-head-title">{t("tips_title")}</div>
              </div>
            </div>
            <div className="create-side-tips">
              <ul className="guideline-list">
                {TIP_KEYS.map((key) => (
                  <li key={key} className="guideline-item">
                    <CircleCheck size={14} strokeWidth={2.5} />
                    <span>{t(key)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </aside>
      </form>
    </div>
  );
}
