import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
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
 * Sprint 160 §4 — the New / Edit Contract modal.
 *
 * The field set matches the reference screenshot's: customer,
 * locations, type, dates, status, and the five billing settings.
 *
 * Two conventions worth not undoing:
 *
 *  * **Keyed by contract id by the CALLER**, so the form seeds from its
 *    props on mount instead of resyncing through an effect. CLAUDE.md
 *    §3 forbids the synchronous-setState-in-an-effect shape this would
 *    otherwise take, and `react-hooks/set-state-in-effect` is already
 *    at its baseline.
 *  * **The pickers come from `/contracts/options/`**, which reads the
 *    same scoped querysets the write path validates against. Nothing
 *    offered here can be rejected as out of scope, and nothing rejected
 *    was offerable.
 */
export function ContractFormDialog({
  open,
  contract,
  onClose,
  onCreated,
  onSaved,
}: {
  open: boolean;
  /** Present for edit, absent for create. */
  contract?: Contract | null;
  onClose: () => void;
  onCreated?: (contract: Contract) => void;
  onSaved?: (contract: Contract) => void;
}) {
  const { t } = useTranslation("contracts");
  const [form, setForm] = useState<FormState>(() => initialState(contract));
  const [options, setOptions] = useState<ContractOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // The options are fetched once per opening. This effect performs an
  // async load and sets state in its CALLBACK, not synchronously in the
  // effect body — the distinction CLAUDE.md draws.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const data = await getContractOptions();
        if (!cancelled) setOptions(data);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, t]);

  if (!open) return null;

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    if (form.customer === "" || !form.start_date) {
      setError(t("errors.customerAndStartRequired"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = {
        customer: form.customer as number,
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
          // Sent in the viewer's language so the first revision reads
          // naturally; the backend falls back to the Dutch default when
          // it is absent.
          initial_revision_label: t("revisions.initialLabel"),
        });
        onCreated?.(created);
      }
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={contract ? t("form.editTitle") : t("form.createTitle")}
        data-testid="contract-form-dialog"
      >
        <h2>{contract ? t("form.editTitle") : t("form.createTitle")}</h2>

        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}

        <div className="form-grid">
          <label className="form-field">
            <span>{t("form.customer")}</span>
            <select
              className="input"
              value={form.customer}
              disabled={Boolean(contract)}
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
          </label>

          <label className="form-field">
            <span>{t("form.type")}</span>
            <select
              className="input"
              value={form.contract_type}
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
                  {row.name}
                </option>
              ))}
            </select>
          </label>

          <label className="form-field">
            <span>{t("form.startDate")}</span>
            <input
              type="date"
              className="input"
              value={form.start_date}
              onChange={(event) => set("start_date", event.target.value)}
              data-testid="contract-form-start"
            />
          </label>

          <label className="form-field">
            <span>{t("form.endDate")}</span>
            <input
              type="date"
              className="input"
              value={form.end_date}
              onChange={(event) => set("end_date", event.target.value)}
              data-testid="contract-form-end"
            />
            <small className="muted">{t("form.endDateHint")}</small>
          </label>

          <label className="form-field">
            <span>{t("form.status")}</span>
            <select
              className="input"
              value={form.lifecycle}
              onChange={(event) =>
                set("lifecycle", event.target.value as ContractLifecycle)
              }
              data-testid="contract-form-lifecycle"
            >
              <option value="DRAFT">{t("status.DRAFT")}</option>
              <option value="ACTIVE">{t("status.ACTIVE")}</option>
              <option value="CANCELLED">{t("status.CANCELLED")}</option>
            </select>
            {/* EXPIRED is deliberately absent: it follows from the end
                date and is not a choice. */}
            <small className="muted">{t("form.statusHint")}</small>
          </label>

          <label className="form-field">
            <span>{t("form.billingPeriod")}</span>
            <select
              className="input"
              value={form.billing_period}
              onChange={(event) =>
                set("billing_period", event.target.value as BillingPeriod)
              }
              data-testid="contract-form-period"
            >
              <option value="MONTHLY">{t("billingPeriod.MONTHLY")}</option>
              <option value="QUARTERLY">{t("billingPeriod.QUARTERLY")}</option>
              <option value="YEARLY">{t("billingPeriod.YEARLY")}</option>
            </select>
          </label>

          <label className="form-field">
            <span>{t("form.billingDay")}</span>
            <input
              type="number"
              min={1}
              max={28}
              className="input"
              value={form.billing_day}
              onChange={(event) =>
                set("billing_day", Number(event.target.value))
              }
              data-testid="contract-form-billing-day"
            />
            <small className="muted">{t("form.billingDayHint")}</small>
          </label>

          <label className="form-field">
            <span>{t("form.billingType")}</span>
            <select
              className="input"
              value={form.billing_type}
              onChange={(event) =>
                set("billing_type", event.target.value as BillingType)
              }
              data-testid="contract-form-billing-type"
            >
              <option value="ADVANCE">{t("billingType.ADVANCE")}</option>
              <option value="ARREARS">{t("billingType.ARREARS")}</option>
            </select>
          </label>

          <label className="form-field">
            <span>{t("form.paymentTerms")}</span>
            <input
              type="number"
              min={0}
              max={365}
              className="input"
              value={form.payment_terms_days}
              onChange={(event) =>
                set("payment_terms_days", Number(event.target.value))
              }
              data-testid="contract-form-terms"
            />
          </label>

          <label className="form-field form-field-inline">
            <input
              type="checkbox"
              checked={form.start_proration}
              onChange={(event) =>
                set("start_proration", event.target.checked)
              }
              data-testid="contract-form-proration"
            />
            <span>{t("form.proration")}</span>
            <small className="muted">{t("form.prorationHint")}</small>
          </label>

          <fieldset className="form-field form-field-wide">
            <legend>{t("form.locations")}</legend>
            {/* Scrollable rather than unbounded: a provider with two
                hundred buildings would otherwise render two hundred
                checkboxes into the dialog (CLAUDE.md §8). */}
            <div className="multi-select-list">
              {(options?.buildings ?? []).map((building) => (
                <label key={building.id} className="check-row">
                  <input
                    type="checkbox"
                    checked={form.building_ids.includes(building.id)}
                    onChange={() =>
                      set(
                        "building_ids",
                        form.building_ids.includes(building.id)
                          ? form.building_ids.filter(
                              (id) => id !== building.id,
                            )
                          : [...form.building_ids, building.id],
                      )
                    }
                    data-testid={`contract-form-building-${building.id}`}
                  />
                  <span>{building.name}</span>
                </label>
              ))}
              {(options?.buildings ?? []).length === 0 && (
                <p className="muted">{t("form.noBuildings")}</p>
              )}
            </div>
          </fieldset>

          <label className="form-field form-field-wide">
            <span>{t("form.description")}</span>
            <textarea
              className="input"
              rows={2}
              value={form.description}
              onChange={(event) => set("description", event.target.value)}
              data-testid="contract-form-description"
            />
          </label>

          <label className="form-field form-field-wide">
            <span>{t("form.notes")}</span>
            <textarea
              className="input"
              rows={2}
              value={form.notes}
              onChange={(event) => set("notes", event.target.value)}
              data-testid="contract-form-notes"
            />
          </label>
        </div>

        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onClose}
            disabled={busy}
          >
            {t("actions.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={busy}
            data-testid="contract-form-save"
          >
            {busy ? t("actions.saving") : t("actions.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
