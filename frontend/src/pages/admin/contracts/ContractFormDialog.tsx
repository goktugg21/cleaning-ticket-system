import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { contractTypeLabel } from "../../../lib/contractTypeLabel";

import { listAllCompanies, listCustomerBuildings } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import { readApiErrorDetail } from "../../../lib/apiFieldErrors";
import {
  createContract,
  getContractOptions,
  updateContract,
} from "../../../api/contracts";
import type {
  BillingPeriod,
  BillingType,
  Contract,
  ContractLifecycle,
  ContractOptions,
} from "../../../api/contracts.types";
import type { CompanyAdmin } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";

/**
 * Sprint 149/150 settled how a SUPER_ADMIN picks the ONE company they
 * are working in, and Sprint 152 gave the hours module its own
 * remembered key. This is the contracts module's key, in the same
 * `osius.<module>.company` shape rather than a third convention.
 */
const CONTRACT_COMPANY_STORAGE_KEY = "osius.contracts.company";

interface FormState {
  customer: number | "";
  contract_type: number | "";
  start_date: string;
  end_date: string;
  lifecycle: ContractLifecycle;
  description: string;
  notes: string;
  billing_period: BillingPeriod;
  billing_day: number;
  billing_type: BillingType;
  payment_terms_days: number;
  start_proration: boolean;
  building_ids: number[];
}

function initialState(contract?: Contract | null): FormState {
  return {
    customer: contract?.customer ?? "",
    contract_type: contract?.contract_type ?? "",
    start_date: contract?.start_date ?? "",
    end_date: contract?.end_date ?? "",
    lifecycle: contract?.lifecycle ?? "DRAFT",
    description: contract?.description ?? "",
    notes: contract?.notes ?? "",
    billing_period: contract?.billing_period ?? "MONTHLY",
    billing_day: contract?.billing_day ?? 1,
    billing_type: contract?.billing_type ?? "ADVANCE",
    payment_terms_days: contract?.payment_terms_days ?? 30,
    start_proration: contract?.start_proration ?? true,
    building_ids: contract?.buildings.map((building) => building.id) ?? [],
  };
}

/**
 * Sprint 160 §4 / Sprint 161 §5b — the New / Edit Contract modal.
 *
 * **Sprint 161 fixed the defect that made this form unusable.** As
 * shipped it contained no company field at all, while the backend
 * refuses to guess one whenever more than one provider Company exists
 * (`views_common.resolve_target_company`). On crmtest, which has three,
 * every save returned `company is required when more than one provider
 * Company exists`, and the locations picker was empty for the same
 * reason: with no company resolved there was nothing to scope buildings
 * to. That is the Sprint 152.1 §2 defect class exactly — a page that
 * sends no company against a resolver that will not invent one.
 *
 * The company is resolved the way Sprints 149/150 settled and Sprint
 * 152 followed:
 *
 *  * COMPANY_ADMIN, or a SUPER_ADMIN on a single-company deployment:
 *    resolved silently, no picker. `/contracts/options/` answers with
 *    the one company in scope and the payload omits the field, which
 *    the backend then fills in itself.
 *  * SUPER_ADMIN with several: a picker, defaulting to the remembered
 *    company and otherwise the lowest id, and the choice is remembered
 *    under this module's own key.
 *
 * Changing the company CLEARS the customer, type and locations rather
 * than carrying them across tenants — a stale id from the previous
 * company would be rejected as `does_not_exist`, which reads to an
 * operator as the form losing their work for no reason.
 *
 * On EDIT there is no picker: a contract's company is fixed, and moving
 * one between tenants is not an edit, it is a different operation
 * nobody has asked for.
 */
const FIELD_ORDER = [
  "customer",
  "contract_type",
  "building_ids",
  "start_date",
  "end_date",
  "lifecycle",
  "billing_period",
  "billing_day",
  "billing_type",
  "payment_terms_days",
];

function scrollToFirstField(errors: Record<string, string>): void {
  const first = FIELD_ORDER.find((key) => errors[key]);
  if (!first) return;
  const el = document.querySelector<HTMLElement>(
    `[data-testid="contract-form-dialog"] [data-contract-field="${first}"]`,
  );
  el?.scrollIntoView({ block: "center", behavior: "smooth" });
}

export function ContractFormDialog({
  open,
  contract,
  fixedCustomerId,
  onClose,
  onCreated,
  onSaved,
}: {
  open: boolean;
  /** Present for edit, absent for create. */
  contract?: Contract | null;
  /** Sprint 169 §7 — opened from INSIDE a customer: that customer is
   *  pre-filled and not changeable, and the location picker offers only
   *  their buildings. The SAME dialog as the main list uses, not a
   *  second form — a second create form is how two screens end up
   *  disagreeing about what a contract needs. */
  fixedCustomerId?: number;
  onClose: () => void;
  onCreated?: (contract: Contract) => void;
  onSaved?: (contract: Contract) => void;
}) {
  const { t } = useTranslation("contracts");
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [form, setForm] = useState<FormState>(() => initialState(contract));
  const [options, setOptions] = useState<ContractOptions | null>(null);
  /** `null` until the customer's buildings are known — until then the
   *  picker offers the unnarrowed list rather than an empty one, which
   *  would read as "this customer has no locations". */
  const [customerBuildingIds, setCustomerBuildingIds] = useState<Set<
    number
  > | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  /* P-4 (Part F) — one sentence per field, the first scrolled into view. */
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesResolved, setCompaniesResolved] = useState(false);
  const [company, setCompany] = useState<number | "">(
    contract?.company ?? "",
  );

  // A SUPER_ADMIN on a multi-company deployment picks one; everyone
  // else never sees the control.
  const showCompanySelector =
    isSuperAdmin && !contract && companies.length > 1;
  // True while a SUPER_ADMIN's company is still unknown. The options
  // fetch waits on it, so the pickers are never populated from the
  // wrong tenant.
  const companyPending =
    isSuperAdmin &&
    !contract &&
    (!companiesResolved || (companies.length > 1 && company === ""));

  useEffect(() => {
    if (!open || !isSuperAdmin || contract) {
      return;
    }
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
        if (response.length > 1) {
          const stored = Number(
            window.localStorage.getItem(CONTRACT_COMPANY_STORAGE_KEY),
          );
          const remembered = response.some((c) => c.id === stored)
            ? stored
            : null;
          const primary = response.reduce(
            (lowest, c) => (c.id < lowest.id ? c : lowest),
            response[0],
          );
          setCompany((current) =>
            current === "" ? (remembered ?? primary.id) : current,
          );
        }
        setCompaniesResolved(true);
      })
      .catch(() => {
        // Fail loudly. A silently absent selector is what shipped in
        // Sprint 160 and it left the operator with a 400 they could do
        // nothing about.
        if (cancelled) return;
        setError(t("errors.companyLoadFailed"));
        setCompaniesResolved(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, isSuperAdmin, contract, t]);

  // The pickers. Refetched when the company changes so a SUPER_ADMIN
  // switching tenants never sees the previous one's customers.
  useEffect(() => {
    if (!open || companyPending) return;
    let cancelled = false;
    getContractOptions(contract ? contract.company : company)
      .then((data) => {
        if (!cancelled) setOptions(data);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open, company, companyPending, contract]);

  /**
   * The locations on offer. With a fixed customer that is THEIR
   * buildings only — you are standing inside one customer, and offering
   * another customer's locations there is an invitation to a mistake
   * the server would not catch, because a provider admin may legitimately
   * link either.
   *
   * The narrowing is a UI convenience and nothing more: the server
   * decides what may be linked, and this dialog posts the same payload
   * from both entry points.
   */
  useEffect(() => {
    if (!open || fixedCustomerId === undefined) return;
    let cancelled = false;
    listCustomerBuildings(fixedCustomerId)
      .then((page) => {
        if (cancelled) return;
        setCustomerBuildingIds(
          new Set(page.results.map((row) => row.building_id)),
        );
      })
      .catch(() => {
        // A failed narrowing falls back to the unnarrowed list rather
        // than to an empty picker: the server is the authority on what
        // may be linked, and an empty picker would look like "this
        // customer has no locations".
        if (!cancelled) setCustomerBuildingIds(null);
      });
    return () => {
      cancelled = true;
    };
  }, [open, fixedCustomerId]);

  const buildings = useMemo(() => {
    const all = options?.buildings ?? [];
    if (fixedCustomerId === undefined || customerBuildingIds === null) {
      return all;
    }
    return all.filter((row) => customerBuildingIds.has(row.id));
  }, [options, fixedCustomerId, customerBuildingIds]);

  if (!open) return null;

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const changeCompany = (next: number | "") => {
    setCompany(next);
    if (next !== "") {
      window.localStorage.setItem(
        CONTRACT_COMPANY_STORAGE_KEY,
        String(next),
      );
    }
    // Everything scoped to the old company goes, rather than being
    // carried across and rejected as nonexistent on save.
    setForm((current) => ({
      ...current,
      customer: "",
      contract_type: "",
      building_ids: [],
    }));
    setOptions(null);
  };

  const bind = (key: string) => ({ "data-contract-field": key });

  const submit = async () => {
    // The fixed customer is what gets SUBMITTED, not merely what is
    // displayed: a disabled <select> shows a value but `form.customer`
    // was never set by an onChange that cannot fire.
    const customerId = fixedCustomerId ?? form.customer;
    /* P-4 (Part F) — errors live where the person is: one sentence per
       field, the first one scrolled into view. */
    const clientErrors: Record<string, string> = {};
    if (customerId === "") clientErrors.customer = t("errors.customerRequired");
    if (!form.start_date) clientErrors.start_date = t("errors.startRequired");
    if (form.end_date && form.start_date && form.end_date < form.start_date) {
      clientErrors.end_date = t("errors.endBeforeStart");
    }
    if (form.billing_day < 1 || form.billing_day > 28) {
      clientErrors.billing_day = t("errors.billingDayRange");
    }
    setFieldErrors(clientErrors);
    if (Object.keys(clientErrors).length > 0) {
      setError("");
      scrollToFirstField(clientErrors);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = {
        customer: customerId as number,
        contract_type: form.contract_type === "" ? null : form.contract_type,
        start_date: form.start_date,
        end_date: form.end_date || null,
        lifecycle: form.lifecycle,
        description: form.description,
        notes: form.notes,
        billing_period: form.billing_period,
        billing_day: form.billing_day,
        billing_type: form.billing_type,
        payment_terms_days: form.payment_terms_days,
        start_proration: form.start_proration,
        building_ids: form.building_ids,
      };
      if (contract) {
        const saved = await updateContract(contract.id, payload);
        onSaved?.(saved);
      } else {
        const created = await createContract({
          ...payload,
          // Sent whenever it is known. Omitted only on a single-company
          // deployment, where the backend resolves it itself.
          ...(company === "" ? {} : { company: company as number }),
          // Sent in the viewer's language so the first revision reads
          // naturally; the backend falls back to the Dutch default when
          // it is absent.
          initial_revision_label: t("revisions.initialLabel"),
        });
        onCreated?.(created);
      }
    } catch (err) {
      // DRF per-field entries land at their fields; the banner shows
      // the generic sentence only when the server named no field.
      const detail = readApiErrorDetail(err);
      const serverErrors: Record<string, string> = {};
      for (const name of Object.keys(detail.fields)) {
        serverErrors[name] = t("errors.fieldRejected");
      }
      setFieldErrors(serverErrors);
      if (Object.keys(serverErrors).length > 0) {
        setError("");
        scrollToFirstField(serverErrors);
      } else {
        setError(getApiError(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const fieldError = (key: string) =>
    fieldErrors[key] ? (
      <span className="field-error" role="alert" data-testid={`contract-form-error-${key}`}>
        {fieldErrors[key]}
      </span>
    ) : null;

  /* The consequence, in the form's own numbers (the contract list's
     click-to-teach sentences, said here where the values are chosen). */
  const billingConsequence = t(`teach.billingType.${form.billing_type}`, { day: form.billing_day });
  const periodConsequence = t(`teach.billingPeriod.${form.billing_period}`);
  const termsConsequence = t("form.paymentTermsSentence", { days: form.payment_terms_days });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={contract ? t("form.editTitle") : t("form.createTitle")}
      data-testid="contract-form-dialog"
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
          maxWidth: 760,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {contract ? t("form.editTitle") : t("form.createTitle")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {contract ? t("form.editIntro") : t("form.createIntro")}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="contract-form-error"
          >
            {error}
          </div>
        )}

        {/* P-4 (Part F) — FOUR STAGES, one thing at a time. Rules frozen
            (§D.15): every field, value and endpoint is what it was; only
            the order, the words at the point of choice and where an
            error lands changed. */}
        <div className="form-section" data-testid="contract-form-stage-who">
          <div className="form-section-title">
            <span className="ew-plan-step">1</span>
            {t("form.stage_who")}
          </div>
        {showCompanySelector && (
          <div className="field">
            <label className="field-label" htmlFor="contract-company">
              {t("form.company")}
            </label>
            <select
              id="contract-company"
              className="field-select"
              value={company === "" ? "" : String(company)}
              onChange={(event) =>
                changeCompany(
                  event.target.value === ""
                    ? ""
                    : Number(event.target.value),
                )
              }
              disabled={busy}
              data-testid="contract-form-company"
            >
              {companies.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
            <span className="muted small">{t("form.companyHint")}</span>
          </div>
        )}
          <div className="form-2col">
          <div className="field" {...bind("customer")}>
            <label className="field-label" htmlFor="contract-customer">
              {t("form.customer")} *
            </label>
            <select
              id="contract-customer"
              className="field-select"
              value={fixedCustomerId ?? form.customer}
              disabled={
                Boolean(contract) ||
                fixedCustomerId !== undefined ||
                busy ||
                companyPending
              }
              onChange={(event) =>
                set(
                  "customer",
                  event.target.value === "" ? "" : Number(event.target.value),
                )
              }
              data-testid="contract-form-customer"
            >
              <option value="">{t("form.choose")}</option>
              {(options?.customers ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          {fieldError("customer")}
          </div>
          <div className="field" {...bind("contract_type")}>
            <label className="field-label" htmlFor="contract-type">
              {t("form.type")}
            </label>
            <select
              id="contract-type"
              className="field-select"
              value={form.contract_type}
              disabled={busy || companyPending}
              onChange={(event) =>
                set(
                  "contract_type",
                  event.target.value === "" ? "" : Number(event.target.value),
                )
              }
              data-testid="contract-form-type"
            >
              <option value="">{t("form.none")}</option>
              {(options?.contract_types ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {contractTypeLabel(row.name, row.standard_slot, t)}
                </option>
              ))}
            </select>
          {fieldError("contract_type")}
          </div>
          </div>
        <div className="field" {...bind("building_ids")}>
          <span className="field-label">{t("form.locations")}</span>
          {/* Scrollable rather than unbounded: a provider with two
              hundred buildings would otherwise render two hundred
              checkboxes into the dialog (CLAUDE.md §8). */}
          <div className="multi-select-list entity-picker-list">
            {buildings.map((building) => (
              <label
                key={building.id}
                className="entity-picker-row"
                htmlFor={`contract-building-${building.id}`}
              >
                <input
                  id={`contract-building-${building.id}`}
                  type="checkbox"
                  checked={form.building_ids.includes(building.id)}
                  disabled={busy}
                  onChange={() =>
                    set(
                      "building_ids",
                      form.building_ids.includes(building.id)
                        ? form.building_ids.filter((id) => id !== building.id)
                        : [...form.building_ids, building.id],
                    )
                  }
                  data-testid={`contract-form-building-${building.id}`}
                />
                <span className="entity-picker-text">{building.name}</span>
              </label>
            ))}
            {buildings.length === 0 && (
              <p className="muted small" style={{ margin: 4 }}>
                {companyPending || !options
                  ? t("form.loadingOptions")
                  : t("form.noBuildings")}
              </p>
            )}
          </div>
        {fieldError("building_ids")}
        </div>
        </div>

        <div className="form-section" data-testid="contract-form-stage-when">
          <div className="form-section-title">
            <span className="ew-plan-step">2</span>
            {t("form.stage_when")}
          </div>
          <div className="form-2col">
          <div className="field" {...bind("start_date")}>
            <label className="field-label" htmlFor="contract-start">
              {t("form.startDate")} *
            </label>
            <input
              id="contract-start"
              type="date"
              className="field-input"
              value={form.start_date}
              disabled={busy}
              onChange={(event) => set("start_date", event.target.value)}
              data-testid="contract-form-start"
            />
          {fieldError("start_date")}
          </div>
          <div className="field" {...bind("end_date")}>
            <label className="field-label" htmlFor="contract-end">
              {t("form.endDate")}
            </label>
            <input
              id="contract-end"
              type="date"
              className="field-input"
              value={form.end_date}
              disabled={busy}
              onChange={(event) => set("end_date", event.target.value)}
              data-testid="contract-form-end"
            />
            <span className="muted small">{t("form.endDateHint")}</span>
          {fieldError("end_date")}
          </div>
          <div className="field" {...bind("lifecycle")}>
            <label className="field-label" htmlFor="contract-lifecycle">
              {t("form.status")}
            </label>
            <select
              id="contract-lifecycle"
              className="field-select"
              value={form.lifecycle}
              disabled={busy}
              onChange={(event) =>
                set("lifecycle", event.target.value as ContractLifecycle)
              }
              data-testid="contract-form-lifecycle"
            >
              <option value="DRAFT">{t("status.DRAFT")}</option>
              <option value="ACTIVE">{t("status.ACTIVE")}</option>
              <option value="CANCELLED">{t("status.CANCELLED")}</option>
            </select>
            {/* Sprint 170 §6 — why this list has three entries and the
                filter has four. Expired is DERIVED from the end date
                and is deliberately not choosable: a stored EXPIRED
                could contradict the dates, and then the list, the
                tiles and the badge would each be able to answer
                differently about the same contract. */}
            <p className="muted small" style={{ margin: "6px 0 0" }}>
              {t("form.statusDerivedHint")}
            </p>
            {contract && (
              <p
                className="muted small"
                style={{ margin: "2px 0 0" }}
                data-testid="contract-form-derived-status"
              >
                {t("form.statusNow", { status: t(`status.${contract.status}`) })}
              </p>
            )}
            {/* EXPIRED is deliberately absent: it follows from the end
                date and is not a choice. */}
            <span className="muted small">{t("form.statusHint")}</span>
          {fieldError("lifecycle")}
          </div>
          </div>
        </div>

        <div className="form-section" data-testid="contract-form-stage-billing">
          <div className="form-section-title">
            <span className="ew-plan-step">3</span>
            {t("form.stage_billing")}
          </div>
          <div className="form-2col">
          <div className="field" {...bind("billing_period")}>
            <label className="field-label" htmlFor="contract-period">
              {t("form.billingPeriod")}
            </label>
            <select
              id="contract-period"
              className="field-select"
              value={form.billing_period}
              disabled={busy}
              onChange={(event) =>
                set("billing_period", event.target.value as BillingPeriod)
              }
              data-testid="contract-form-period"
            >
              <option value="MONTHLY">{t("billingPeriod.MONTHLY")}</option>
              <option value="QUARTERLY">{t("billingPeriod.QUARTERLY")}</option>
              <option value="YEARLY">{t("billingPeriod.YEARLY")}</option>
            </select>
          {fieldError("billing_period")}
          </div>
          <div className="field" {...bind("billing_day")}>
            <label className="field-label" htmlFor="contract-billing-day">
              {t("form.billingDay")}
            </label>
            <input
              id="contract-billing-day"
              type="number"
              min={1}
              max={28}
              className="field-input"
              value={form.billing_day}
              disabled={busy}
              onChange={(event) =>
                set("billing_day", Number(event.target.value))
              }
              data-testid="contract-form-billing-day"
            />
            <span className="muted small">{t("form.billingDayHint")}</span>
          {fieldError("billing_day")}
          </div>
          <div className="field" {...bind("billing_type")}>
            <label className="field-label" htmlFor="contract-billing-type">
              {t("form.billingType")}
            </label>
            <select
              id="contract-billing-type"
              className="field-select"
              value={form.billing_type}
              disabled={busy}
              onChange={(event) =>
                set("billing_type", event.target.value as BillingType)
              }
              data-testid="contract-form-billing-type"
            >
              <option value="ADVANCE">{t("billingType.ADVANCE")}</option>
              <option value="ARREARS">{t("billingType.ARREARS")}</option>
            </select>
          {fieldError("billing_type")}
          </div>
          <div className="field" {...bind("payment_terms_days")}>
            <label className="field-label" htmlFor="contract-terms">
              {t("form.paymentTerms")}
            </label>
            <input
              id="contract-terms"
              type="number"
              min={0}
              max={365}
              className="field-input"
              value={form.payment_terms_days}
              disabled={busy}
              onChange={(event) =>
                set("payment_terms_days", Number(event.target.value))
              }
              data-testid="contract-form-terms"
            />
          {fieldError("payment_terms_days")}
          </div>
          <div className="field">
            <label className="field-label" htmlFor="contract-proration">
              {t("form.proration")}
            </label>
            <label className="entity-picker-row" htmlFor="contract-proration">
              <input
                id="contract-proration"
                type="checkbox"
                checked={form.start_proration}
                disabled={busy}
                onChange={(event) =>
                  set("start_proration", event.target.checked)
                }
                data-testid="contract-form-proration"
              />
              <span className="entity-picker-text">
                {t("form.prorationHint")}
              </span>
            </label>
          </div>
          </div>
          {/* The consequence in this contract's own numbers, ONE line. */}
          <p className="muted small" data-testid="contract-form-billing-sentence">
            {periodConsequence} {billingConsequence} {termsConsequence}
          </p>
        </div>

        <div className="form-section" data-testid="contract-form-stage-notes">
          <div className="form-section-title">
            <span className="ew-plan-step">4</span>
            {t("form.stage_notes")}
          </div>
        <div className="field">
          <label className="field-label" htmlFor="contract-description">
            {t("form.description")}
          </label>
          <textarea
            id="contract-description"
            className="field-input"
            rows={2}
            value={form.description}
            disabled={busy}
            onChange={(event) => set("description", event.target.value)}
            data-testid="contract-form-description"
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="contract-notes">
            {t("form.notes")}
          </label>
          <textarea
            id="contract-notes"
            className="field-input"
            rows={2}
            value={form.notes}
            disabled={busy}
            onChange={(event) => set("notes", event.target.value)}
            data-testid="contract-form-notes"
          />
        </div>
        </div>

        <div className="filter-actions" style={{ justifyContent: "flex-end", alignItems: "center" }}>
          {Object.keys(fieldErrors).length > 0 && (
            <span className="form-error" role="alert" style={{ marginRight: "auto" }} data-testid="contract-form-summary-error">
              {t("errors.fixMarked", { count: Object.keys(fieldErrors).length })}
            </span>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onClose}
            disabled={busy}
          >
            {t("actions.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void submit()}
            disabled={busy || companyPending}
            data-testid="contract-form-save"
          >
            {busy ? t("actions.saving") : t("actions.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
