// Sprint 11/12 frontend — RecurringJob create + edit (shared form).
//
// Bespoke submit/load skeleton (mirrors the useEntityForm shape) rather
// than the hook itself, because the backend serializes create/update
// RESPONSES with the WRITE serializer: no `id`, crew lists write-only.
// So create cannot route to a detail page (navigates to the list) and
// edit re-GETs the full read object via the api helper.
//
// Option sources reuse the established conventions:
//   - buildings / customers : GET /buildings/ + /customers/ (CreateTicketPage)
//   - default staff / managers : GET /buildings/<id>/eligible-crew/
// The eligible-crew endpoint is building-scoped and reachable by an
// in-scope BUILDING_MANAGER, so the crew pickers work for every provider
// role (it replaced the earlier listUsers({role}) workaround that 403'd
// BMs). Crew is fetched per selected building; the backend still validates
// per-building eligibility on write.
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";
import { extractAdminFieldErrors, getBuildingEligibleCrew } from "../../api/admin";
import type { AdminFieldErrors, CrewUser } from "../../api/admin";
import {
  createRecurringJob,
  getRecurringJob,
  updateRecurringJob,
} from "../../api/plannedWork";
import type {
  RecurringJobFrequency,
  RecurringJobWritePayload,
  SelectablePricingMode,
} from "../../api/plannedWork.types";
import type { Building, Customer, PaginatedResponse } from "../../api/types";
import { useToast } from "../../components/ToastProvider";

const FREQUENCIES: RecurringJobFrequency[] = ["WEEKLY", "BIWEEKLY", "MONTHLY"];
const PRICING_MODES: SelectablePricingMode[] = ["CONTRACT_INCLUDED", "FIXED"];

function customerMatchesBuilding(customer: Customer, buildingId: number): boolean {
  return (
    customer.building === buildingId ||
    (customer.linked_building_ids?.includes(buildingId) ?? false)
  );
}

export function RecurringJobFormPage() {
  const { id } = useParams();
  const isCreate = id === undefined;
  const navigate = useNavigate();
  const { push } = useToast();
  const { t } = useTranslation(["planned_work", "common"]);

  // Option lists.
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  // Eligible crew for the SELECTED building (building-scoped endpoint).
  const [eligibleStaff, setEligibleStaff] = useState<CrewUser[]>([]);
  const [eligibleManagers, setEligibleManagers] = useState<CrewUser[]>([]);
  const [crewLoading, setCrewLoading] = useState(false);
  const [crewError, setCrewError] = useState(false);
  // True once a successful eligible-crew fetch has resolved for the
  // current building. Gates whether the crew lists are sent on submit:
  // if the fetch failed (or no building yet) we OMIT the crew keys so an
  // edit never wipes a job's existing crew on a transient error.
  const [crewLoaded, setCrewLoaded] = useState(false);

  // Form fields.
  const [building, setBuilding] = useState<number | "">("");
  const [customer, setCustomer] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [frequency, setFrequency] = useState<RecurringJobFrequency>("WEEKLY");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [preferredStartTime, setPreferredStartTime] = useState("");
  const [timeWindowLabel, setTimeWindowLabel] = useState("");
  const [pricingMode, setPricingMode] =
    useState<SelectablePricingMode>("CONTRACT_INCLUDED");
  const [fixedPrice, setFixedPrice] = useState("");
  const [vatPct, setVatPct] = useState("21");
  const [defaultStaffIds, setDefaultStaffIds] = useState<number[]>([]);
  const [defaultManagerIds, setDefaultManagerIds] = useState<number[]>([]);

  // Fallback labels so a building/customer outside the fetched page still
  // renders a sensible option in edit mode.
  const [loadedJobTitle, setLoadedJobTitle] = useState("");
  const [fallbackBuilding, setFallbackBuilding] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [fallbackCustomer, setFallbackCustomer] = useState<{
    id: number;
    name: string;
  } | null>(null);

  const [loading, setLoading] = useState(!isCreate);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<AdminFieldErrors>({});

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [buildingsResp, customersResp] = await Promise.all([
          api.get<PaginatedResponse<Building>>("/buildings/", {
            params: { page_size: 200 },
          }),
          api.get<PaginatedResponse<Customer>>("/customers/", {
            params: { page_size: 200 },
          }),
        ]);
        if (cancelled) return;
        setBuildings(buildingsResp.data.results);
        setCustomers(customersResp.data.results);

        // Eligible crew is loaded per-building by the [building] effect
        // below; in edit mode that effect fires once `building` is set
        // from the loaded job here.
        if (!isCreate && id !== undefined) {
          const job = await getRecurringJob(id);
          if (cancelled) return;
          // Apply the loaded job to form state. Inlined (rather than a
          // helper) so it sits after the await — keeping it out of the
          // effect's synchronous body and free of forward-reference lint.
          setLoadedJobTitle(job.title);
          setBuilding(job.building);
          setCustomer(job.customer);
          setTitle(job.title);
          setDescription(job.description);
          setFrequency(job.frequency);
          setStartDate(job.start_date);
          setEndDate(job.end_date ?? "");
          setPreferredStartTime(job.preferred_start_time?.slice(0, 5) ?? "");
          setTimeWindowLabel(job.time_window_label);
          // HOURLY is not selectable; coerce any legacy value to CONTRACT_INCLUDED.
          setPricingMode(
            job.pricing_mode === "FIXED" ? "FIXED" : "CONTRACT_INCLUDED",
          );
          setFixedPrice(job.fixed_price ?? "");
          setVatPct(job.vat_pct ?? "21");
          setDefaultStaffIds(job.default_staff_ids);
          setDefaultManagerIds(job.default_manager_ids);
          setFallbackBuilding({ id: job.building, name: job.building_name });
          setFallbackCustomer({ id: job.customer, name: job.customer_name });
        }
      } catch (err) {
        if (!cancelled) setGeneralError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id, isCreate]);

  // Load the building-scoped eligible crew whenever the selected building
  // changes. Fires on a manual building pick AND on the initial edit load
  // (once the job's building is applied above). With no building selected
  // the lists clear and the pickers show a "select a building" placeholder.
  useEffect(() => {
    let cancelled = false;
    async function loadCrew() {
      if (building === "") {
        setEligibleStaff([]);
        setEligibleManagers([]);
        setCrewLoaded(false);
        setCrewError(false);
        setCrewLoading(false);
        return;
      }
      setCrewLoading(true);
      setCrewError(false);
      try {
        const crew = await getBuildingEligibleCrew(Number(building));
        if (cancelled) return;
        setEligibleStaff(crew.staff);
        setEligibleManagers(crew.managers);
        setCrewLoaded(true);
      } catch {
        if (cancelled) return;
        setEligibleStaff([]);
        setEligibleManagers([]);
        setCrewLoaded(false);
        setCrewError(true);
      } finally {
        if (!cancelled) setCrewLoading(false);
      }
    }
    loadCrew();
    return () => {
      cancelled = true;
    };
  }, [building]);

  const filteredCustomers = useMemo(() => {
    if (building === "") return customers;
    return customers.filter((c) => customerMatchesBuilding(c, Number(building)));
  }, [customers, building]);

  function toggleId(list: number[], value: number): number[] {
    return list.includes(value)
      ? list.filter((x) => x !== value)
      : [...list, value];
  }

  function handleBuildingChange(value: string) {
    const next = value === "" ? "" : Number(value);
    setBuilding(next);
    // Eligibility is per-building; drop a customer that no longer matches
    // and reset crew so stale picks can't ride along.
    if (next !== "" && customer !== "") {
      const stillValid = customers.some(
        (c) => c.id === customer && customerMatchesBuilding(c, Number(next)),
      );
      if (!stillValid) setCustomer("");
    }
    setDefaultStaffIds([]);
    setDefaultManagerIds([]);
  }

  function validate(): boolean {
    const errs: AdminFieldErrors = {};
    if (building === "") errs.building = t("form.error_building_required");
    if (customer === "") errs.customer = t("form.error_customer_required");
    if (!title.trim()) errs.title = t("form.error_title_required");
    if (!startDate) errs.start_date = t("form.error_start_date_required");
    if (pricingMode === "FIXED" && !fixedPrice.trim()) {
      errs.fixed_price = t("form.error_fixed_price_required");
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function buildPayload(): RecurringJobWritePayload {
    const payload: RecurringJobWritePayload = {
      building: Number(building),
      customer: Number(customer),
      title: title.trim(),
      description: description.trim(),
      frequency,
      start_date: startDate,
      end_date: endDate || null,
      preferred_start_time: preferredStartTime || null,
      time_window_label: timeWindowLabel.trim(),
      pricing_mode: pricingMode,
      vat_pct: vatPct || "21",
      fixed_price: pricingMode === "FIXED" ? fixedPrice.trim() : null,
    };
    // Only touch crew when eligible crew loaded for this building, so a
    // transient fetch error on edit does not wipe the job's existing crew
    // (omitted key = untouched). Send only ids still in the eligible lists:
    // a pre-selected default that lost eligibility is dropped rather than
    // re-sent (the backend would reject re-adding it).
    if (crewLoaded) {
      const staffIds = new Set(eligibleStaff.map((u) => u.id));
      const managerIds = new Set(eligibleManagers.map((u) => u.id));
      payload.default_staff_ids = defaultStaffIds.filter((uid) =>
        staffIds.has(uid),
      );
      payload.default_manager_ids = defaultManagerIds.filter((uid) =>
        managerIds.has(uid),
      );
    }
    return payload;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneralError("");
    if (!validate()) return;
    setSubmitting(true);
    try {
      const payload = buildPayload();
      if (isCreate) {
        await createRecurringJob(payload);
        push({
          variant: "success",
          title: t("form.created_toast_title"),
          description: t("form.created_toast_desc"),
        });
        navigate("/planned-work");
        return;
      }
      if (id === undefined) return;
      await updateRecurringJob(id, payload);
      push({
        variant: "success",
        title: t("form.saved_toast_title"),
        description: t("form.saved_toast_desc"),
      });
      navigate(`/planned-work/${id}`);
    } catch (err) {
      const fields = extractAdminFieldErrors(err);
      if (Object.keys(fields).length > 0) {
        setFieldErrors(fields);
        if (fields.detail) setGeneralError(fields.detail);
      } else {
        setGeneralError(getApiError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const backHref =
    isCreate || id === undefined ? "/planned-work" : `/planned-work/${id}`;
  const backLabel = isCreate
    ? t("form.back_to_list")
    : t("form.back_to_detail");

  const buildingOptions: { id: number; name: string }[] = useMemo(() => {
    const opts = buildings.map((b) => ({ id: b.id, name: b.name }));
    if (fallbackBuilding && !opts.some((o) => o.id === fallbackBuilding.id)) {
      opts.unshift(fallbackBuilding);
    }
    return opts;
  }, [buildings, fallbackBuilding]);

  const customerOptions: { id: number; name: string }[] = useMemo(() => {
    const opts = filteredCustomers.map((c) => ({ id: c.id, name: c.name }));
    if (
      fallbackCustomer &&
      customer === fallbackCustomer.id &&
      !opts.some((o) => o.id === fallbackCustomer.id)
    ) {
      opts.unshift(fallbackCustomer);
    }
    return opts;
  }, [filteredCustomers, fallbackCustomer, customer]);

  return (
    <div data-testid="recurring-job-form-page">
      <Link to={backHref} className="link-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {backLabel}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("common:ops")}
          </div>
          <h2 className="page-title">
            {isCreate
              ? t("form.create_title")
              : t("form.edit_title", { title: loadedJobTitle })}
          </h2>
        </div>
      </div>

      {generalError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {generalError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <form className="card" onSubmit={handleSubmit}>
          {/* Basics */}
          <div className="form-section">
            <div className="form-section-title">
              {t("form.section_basics_title")}
            </div>
            <div className="form-section-helper">
              {t("form.section_basics_desc")}
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="rj-building">
                  {t("form.field_building")} *
                </label>
                <select
                  id="rj-building"
                  className="field-select"
                  value={building === "" ? "" : String(building)}
                  onChange={(event) => handleBuildingChange(event.target.value)}
                  required
                >
                  <option value="" disabled>
                    {t("form.field_building_placeholder")}
                  </option>
                  {buildingOptions.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
                {fieldErrors.building && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.building}
                  </div>
                )}
              </div>
              <div className="field">
                <label className="field-label" htmlFor="rj-customer">
                  {t("form.field_customer")} *
                </label>
                <select
                  id="rj-customer"
                  className="field-select"
                  value={customer === "" ? "" : String(customer)}
                  onChange={(event) =>
                    setCustomer(
                      event.target.value === ""
                        ? ""
                        : Number(event.target.value),
                    )
                  }
                  disabled={customerOptions.length === 0}
                  required
                >
                  <option value="" disabled>
                    {customerOptions.length === 0
                      ? t("form.field_customer_no_options")
                      : t("form.field_customer_placeholder")}
                  </option>
                  {customerOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                {fieldErrors.customer && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.customer}
                  </div>
                )}
              </div>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="rj-title">
                {t("form.field_title")} *
              </label>
              <input
                id="rj-title"
                className="field-input"
                type="text"
                maxLength={255}
                placeholder={t("form.field_title_placeholder")}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required
              />
              {fieldErrors.title && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.title}
                </div>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="rj-description">
                {t("form.field_description")}
              </label>
              <textarea
                id="rj-description"
                className="field-textarea"
                placeholder={t("form.field_description_placeholder")}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
          </div>

          {/* Schedule */}
          <div className="form-section">
            <div className="form-section-title">
              {t("form.section_schedule_title")}
            </div>
            <div className="form-section-helper">
              {t("form.section_schedule_desc")}
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="rj-frequency">
                  {t("form.field_frequency")} *
                </label>
                <select
                  id="rj-frequency"
                  className="field-select"
                  value={frequency}
                  onChange={(event) =>
                    setFrequency(event.target.value as RecurringJobFrequency)
                  }
                >
                  {FREQUENCIES.map((f) => (
                    <option key={f} value={f}>
                      {t(`frequency.${f}`)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="rj-start">
                  {t("form.field_start_date")} *
                </label>
                <input
                  id="rj-start"
                  className="field-input"
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                  required
                />
                {fieldErrors.start_date && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.start_date}
                  </div>
                )}
              </div>
            </div>
            <div className="form-2col">
              <div className="field">
                <label className="field-label" htmlFor="rj-end">
                  {t("form.field_end_date")}
                </label>
                <input
                  id="rj-end"
                  className="field-input"
                  type="date"
                  value={endDate}
                  onChange={(event) => setEndDate(event.target.value)}
                />
                <div className="form-section-helper">
                  {t("form.field_end_date_hint")}
                </div>
                {fieldErrors.end_date && (
                  <div className="alert-error login-error" role="alert">
                    {fieldErrors.end_date}
                  </div>
                )}
              </div>
              <div className="field">
                <label className="field-label" htmlFor="rj-time">
                  {t("form.field_preferred_start_time")}
                </label>
                <input
                  id="rj-time"
                  className="field-input"
                  type="time"
                  value={preferredStartTime}
                  onChange={(event) =>
                    setPreferredStartTime(event.target.value)
                  }
                />
                <div className="form-section-helper">
                  {t("form.field_preferred_start_time_hint")}
                </div>
              </div>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="rj-window">
                {t("form.field_time_window_label")}
              </label>
              <input
                id="rj-window"
                className="field-input"
                type="text"
                maxLength={64}
                placeholder={t("form.field_time_window_placeholder")}
                value={timeWindowLabel}
                onChange={(event) => setTimeWindowLabel(event.target.value)}
              />
              <div className="form-section-helper">
                {t("form.field_time_window_hint")}
              </div>
            </div>
          </div>

          {/* Pricing */}
          <div className="form-section">
            <div className="form-section-title">
              {t("form.section_pricing_title")}
            </div>
            <div className="form-section-helper">
              {t("form.section_pricing_desc")}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="rj-pricing-mode">
                {t("form.field_pricing_mode")} *
              </label>
              <select
                id="rj-pricing-mode"
                className="field-select"
                value={pricingMode}
                onChange={(event) =>
                  setPricingMode(event.target.value as SelectablePricingMode)
                }
              >
                {PRICING_MODES.map((m) => (
                  <option key={m} value={m}>
                    {t(`pricing_mode.${m}`)}
                  </option>
                ))}
              </select>
              {fieldErrors.pricing_mode && (
                <div className="alert-error login-error" role="alert">
                  {fieldErrors.pricing_mode}
                </div>
              )}
            </div>
            {pricingMode === "FIXED" && (
              <div className="form-2col">
                <div className="field">
                  <label className="field-label" htmlFor="rj-fixed-price">
                    {t("form.field_fixed_price")} *
                  </label>
                  <input
                    id="rj-fixed-price"
                    className="field-input"
                    type="number"
                    min="0"
                    step="0.01"
                    inputMode="decimal"
                    value={fixedPrice}
                    onChange={(event) => setFixedPrice(event.target.value)}
                  />
                  <div className="form-section-helper">
                    {t("form.field_fixed_price_hint")}
                  </div>
                  {fieldErrors.fixed_price && (
                    <div className="alert-error login-error" role="alert">
                      {fieldErrors.fixed_price}
                    </div>
                  )}
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="rj-vat">
                    {t("form.field_vat_pct")}
                  </label>
                  <input
                    id="rj-vat"
                    className="field-input"
                    type="number"
                    min="0"
                    step="0.01"
                    inputMode="decimal"
                    value={vatPct}
                    onChange={(event) => setVatPct(event.target.value)}
                  />
                  {fieldErrors.vat_pct && (
                    <div className="alert-error login-error" role="alert">
                      {fieldErrors.vat_pct}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Default crew */}
          <div className="form-section">
            <div className="form-section-title">
              {t("form.section_crew_title")}
            </div>
            <div className="form-section-helper">
              {t("form.section_crew_desc")}
            </div>
            {building === "" ? (
              <p className="muted small">
                {t("form.crew_select_building_first")}
              </p>
            ) : crewLoading ? (
              <p className="muted small">{t("form.crew_loading")}</p>
            ) : crewError ? (
              <p className="muted small">{t("form.crew_load_failed")}</p>
            ) : (
              <div className="form-2col">
                <div className="field">
                  <label className="field-label">
                    {t("form.field_default_staff")}
                  </label>
                  <div className="form-section-helper">
                    {t("form.field_default_staff_hint")}
                  </div>
                  <CrewPicker
                    candidates={eligibleStaff}
                    selected={defaultStaffIds}
                    onToggle={(uid) =>
                      setDefaultStaffIds((prev) => toggleId(prev, uid))
                    }
                    emptyLabel={t("form.no_staff_options")}
                    selectedLabel={t("form.selected_count", {
                      count: defaultStaffIds.length,
                    })}
                    testId="rj-staff-picker"
                  />
                  {fieldErrors.default_staff_ids && (
                    <div className="alert-error login-error" role="alert">
                      {fieldErrors.default_staff_ids}
                    </div>
                  )}
                </div>
                <div className="field">
                  <label className="field-label">
                    {t("form.field_default_managers")}
                  </label>
                  <div className="form-section-helper">
                    {t("form.field_default_managers_hint")}
                  </div>
                  <CrewPicker
                    candidates={eligibleManagers}
                    selected={defaultManagerIds}
                    onToggle={(uid) =>
                      setDefaultManagerIds((prev) => toggleId(prev, uid))
                    }
                    emptyLabel={t("form.no_manager_options")}
                    selectedLabel={t("form.selected_count", {
                      count: defaultManagerIds.length,
                    })}
                    testId="rj-manager-picker"
                  />
                  {fieldErrors.default_manager_ids && (
                    <div className="alert-error login-error" role="alert">
                      {fieldErrors.default_manager_ids}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="form-actions">
            <Link to={backHref} className="btn btn-secondary">
              {t("form.cancel")}
            </Link>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting}
              data-testid="recurring-job-submit"
            >
              {submitting
                ? t("form.saving")
                : isCreate
                  ? t("form.submit_create")
                  : t("form.submit_edit")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function CrewPicker({
  candidates,
  selected,
  onToggle,
  emptyLabel,
  selectedLabel,
  testId,
}: {
  candidates: CrewUser[];
  selected: number[];
  onToggle: (userId: number) => void;
  emptyLabel: string;
  selectedLabel: string;
  testId: string;
}) {
  if (candidates.length === 0) {
    return <p className="muted small">{emptyLabel}</p>;
  }
  return (
    <div className="crew-picker" data-testid={testId}>
      <div
        className="crew-picker-list"
        style={{
          maxHeight: 180,
          overflowY: "auto",
          border: "1px solid var(--border)",
          borderRadius: 8,
          padding: 8,
        }}
      >
        {candidates.map((user) => (
          <label
            key={user.id}
            className="crew-picker-row"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "4px 2px",
            }}
          >
            <input
              type="checkbox"
              checked={selected.includes(user.id)}
              onChange={() => onToggle(user.id)}
            />
            <span>
              {user.email}
              {user.full_name ? ` — ${user.full_name}` : ""}
            </span>
          </label>
        ))}
      </div>
      <div className="muted small" style={{ marginTop: 6 }}>
        {selectedLabel}
      </div>
    </div>
  );
}
