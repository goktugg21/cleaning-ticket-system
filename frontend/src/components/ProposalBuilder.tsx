// Sprint 31 (frontend) — provider-side proposal builder.
//
// Renders a DRAFT proposal's lines (auto-seeded from the cart by the
// backend, with contract prices pre-filled — SoT §8.3) as an EDITABLE +
// REMOVABLE table: the provider prices the custom lines, can add ad-hoc
// lines, and sends the proposal to the customer. When the viewer cannot
// edit (e.g. a BM whose prepare key is revoked) the rows render
// read-only. Every mutation calls the DRAFT-only line CRUD / transition
// endpoints, then asks the parent to refetch via `onChanged`.
//
// Only `ProposalBuilder` is exported (react-refresh/only-export-
// components); the row/add-line helpers stay local to this file.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FileText, Plus, RefreshCw, X } from "lucide-react";

import { getApiError } from "../api/client";
import {
  createProposalLine,
  deleteProposalLine,
  fetchProposalPdf,
  transitionProposal,
  type ProposalLineWritePayload,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import type { ExtraWorkUnitType, ProposalDetail, ProposalLine } from "../api/types";
import { formatMoney } from "../lib/intl";
import { CollapsibleCard } from "./CollapsibleCard";
import { InvoiceLineRow, InvoiceLineTotalsRow } from "./InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "./invoiceLineColumns";
import { NoteEditorDialog } from "./NoteEditorDialog";

// RF-14 — the live preview pane's visibility survives navigation within
// a tab session (sessionStorage), so an operator who prefers the full-
// width builder is not forced to re-hide the pane on every EW.
const PREVIEW_OPEN_KEY = "ew-proposal-preview-open";

const UNIT_TYPE_VALUES: ExtraWorkUnitType[] = [
  "HOURS",
  "SQUARE_METERS",
  "FIXED",
  "ITEM",
  "OTHER",
];
const UNIT_TYPE_KEY: Record<ExtraWorkUnitType, string> = {
  HOURS: "unit_type.hours",
  SQUARE_METERS: "unit_type.square_meters",
  FIXED: "unit_type.fixed",
  ITEM: "unit_type.item",
  OTHER: "unit_type.other",
};

// Banker's rounding (ROUND_HALF_EVEN) to 2dp — mirrors the backend
// Decimal quantisation so the live editor boxes match the persisted
// totals byte-for-byte. (Ported from the legacy ExtraWorkDetailPage
// `round2`: scale by 100, snap exact halves to the nearest even, else
// Math.round, then unscale.)
function round2(n: number): number {
  const scaled = n * 100;
  const floor = Math.floor(scaled);
  const frac = scaled - floor;
  let rounded: number;
  if (Math.abs(frac - 0.5) < 1e-9) {
    // Exact half: round to the nearest even integer.
    rounded = floor % 2 === 0 ? floor : floor + 1;
  } else {
    rounded = Math.round(scaled);
  }
  return rounded / 100;
}

// Display-only live subtotal / VAT / total for the editor row (the
// persisted line's backend totals appear after Save reloads the
// proposal). Empty / non-numeric inputs collapse to 0. The subtotal is
// rounded FIRST, then VAT and total are derived from the rounded
// subtotal — matching the backend's staged quantisation.
function liveLineMoney(
  quantity: string,
  unitPrice: string,
  vatPct: string,
): { subtotal: number; vat: number; total: number } {
  const q = Number(quantity);
  const u = Number(unitPrice);
  const v = Number(vatPct);
  const qn = Number.isFinite(q) ? q : 0;
  const un = Number.isFinite(u) ? u : 0;
  const vn = Number.isFinite(v) ? v : 0;
  const subtotal = round2(qn * un);
  const vat = round2((subtotal * vn) / 100);
  const total = round2(subtotal + vat);
  return { subtotal, vat, total };
}

interface LineFormState {
  description: string;
  unit_type: ExtraWorkUnitType;
  // #108 Part B — non-empty when the unit was entered via "Custom…"
  // (unit_type is then OTHER on the wire). Cleared whenever a standard
  // unit — including plain Other — is picked.
  custom_unit_label: string;
  quantity: string;
  unit_price: string;
  vat_pct: string;
  customer_explanation: string;
  internal_note: string;
}

// A money box: display-only, right-aligned, tabular numbers. Mirrors the
// legacy composer's three live boxes (Subtotal / VAT / Total).
function MoneyBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="field ew-line-field-money">
      <span className="field-label">{label}</span>
      <div
        className="field-input"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {formatMoney(value)}
      </div>
    </div>
  );
}

// #108 Part B — a modal-trigger box: a button styled as a field box
// showing a filled-dot indicator + a one-line preview of the current
// value (the placeholder when empty). Clicking opens the caller's
// modal editor — there is no inline editing (Description is
// strict-modal per owner; the two notes follow the same pattern).
function ModalFieldBox({
  label,
  value,
  placeholder,
  onOpen,
  disabled,
  testId,
}: {
  label: string;
  value: string;
  placeholder: string;
  onOpen: () => void;
  disabled: boolean;
  testId: string;
}) {
  const filled = value.trim() !== "";
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <button
        type="button"
        className="field-input ew-pricing-note-box"
        onClick={onOpen}
        disabled={disabled}
        data-testid={testId}
        data-filled={filled ? "true" : "false"}
      >
        <span
          className={
            filled ? "ew-note-dot ew-note-dot-filled" : "ew-note-dot"
          }
          aria-hidden
        />
        <span
          className={
            filled
              ? "ew-pricing-note-box-text"
              : "ew-pricing-note-box-text muted"
          }
        >
          {filled ? value : placeholder}
        </span>
      </button>
    </div>
  );
}

// #108 Part B — the "Custom…" unit modal: a single-line, REQUIRED unit
// name (max 50 chars, mirroring the backend column + the RF-2 rule on
// the pricing page). Save is disabled until a non-blank name is typed.
function CustomUnitDialog({
  initialValue,
  onSave,
  onCancel,
}: {
  initialValue: string;
  onSave: (value: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [value, setValue] = useState(initialValue);
  const trimmed = value.trim();
  return (
    <div
      className="reject-modal-backdrop"
      data-testid="proposal-custom-unit-dialog"
      role="dialog"
      aria-modal="true"
    >
      <div className="reject-modal">
        <h3 className="reject-modal-title">
          {t("detail.custom_unit_modal_title")}
        </h3>
        <p className="reject-modal-desc">{t("detail.custom_unit_modal_desc")}</p>
        <input
          className="field-input"
          type="text"
          maxLength={50}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t("detail.custom_unit_placeholder")}
          autoFocus
          data-testid="proposal-custom-unit-input"
        />
        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            data-testid="proposal-custom-unit-cancel"
          >
            {t("detail.note_modal_cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={trimmed === ""}
            onClick={() => onSave(trimmed)}
            data-testid="proposal-custom-unit-save"
          >
            {t("detail.note_modal_save")}
          </button>
        </div>
      </div>
    </div>
  );
}

// Shared field cluster for the add-line form.
//
// #108 Part B — ONE fixed grid row (replaces the RF-19 two-row grid):
// description (modal box) / unit / qty / unit price / VAT % / computed
// subtotal-VAT-total / customer note (modal box) / internal note
// (modal box) / actions. Description and both notes are strict-modal
// (a compact trigger box with a filled-dot indicator + one-line
// preview); the Unit dropdown carries a "Custom…" entry below Other
// that opens a required unit-name modal. Cells compress via the grid
// template as the builder column narrows (preview open vs collapsed) —
// the row NEVER re-wraps, so nothing jumps when values change.
function LineFields({
  form,
  setForm,
  disabled,
  showInternal,
  actionsSlot,
}: {
  form: LineFormState;
  setForm: (next: LineFormState) => void;
  disabled: boolean;
  showInternal: boolean;
  actionsSlot?: ReactNode;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  // Which modal (if any) is open for THIS line editor instance.
  const [modal, setModal] = useState<
    "description" | "customer" | "internal" | "custom_unit" | null
  >(null);
  const set = <K extends keyof LineFormState>(key: K, value: LineFormState[K]) =>
    setForm({ ...form, [key]: value });
  const money = liveLineMoney(form.quantity, form.unit_price, form.vat_pct);
  // The select surfaces the stored custom unit name as its own option
  // ("shown as the unit afterwards"); picking any standard unit —
  // including plain Other — clears the custom name (mirrors the RF-2
  // concrete-unit-forces-blank rule).
  const hasCustomUnit = form.custom_unit_label.trim() !== "";
  const unitValue = hasCustomUnit ? "__custom" : form.unit_type;
  return (
    <>
    <div className="proposal-addline-row">
      <ModalFieldBox
        label={t("detail.pricing_form_description")}
        value={form.description}
        placeholder={t("detail.pricing_form_description_placeholder")}
        onOpen={() => setModal("description")}
        disabled={disabled}
        testId="proposal-line-description-box"
      />
      <div className="field">
        <span className="field-label">{t("detail.pricing_form_unit")}</span>
        <select
          className="field-select"
          value={unitValue}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "__custom_new") {
              setModal("custom_unit");
              return;
            }
            if (v === "__custom") return;
            setForm({
              ...form,
              unit_type: v as ExtraWorkUnitType,
              custom_unit_label: "",
            });
          }}
          disabled={disabled}
          data-testid="proposal-line-unit-select"
        >
          {UNIT_TYPE_VALUES.map((u) => (
            <option key={u} value={u}>
              {t(UNIT_TYPE_KEY[u])}
            </option>
          ))}
          {hasCustomUnit && (
            <option value="__custom">{form.custom_unit_label}</option>
          )}
          <option value="__custom_new">{t("detail.unit_custom_option")}</option>
        </select>
      </div>
      <div className="field">
        <span className="field-label">{t("detail.pricing_form_quantity")}</span>
        <input
          className="field-input"
          type="number"
          step="0.01"
          min="0"
          value={form.quantity}
          onChange={(e) => set("quantity", e.target.value)}
          disabled={disabled}
        />
      </div>
      <div className="field">
        <span className="field-label">{t("detail.pricing_form_unit_price")}</span>
        <input
          className="field-input"
          type="number"
          step="0.01"
          min="0"
          value={form.unit_price}
          onChange={(e) => set("unit_price", e.target.value)}
          disabled={disabled}
        />
      </div>
      <div className="field">
        <span className="field-label">{t("detail.pricing_form_vat")}</span>
        <input
          className="field-input"
          type="number"
          step="0.01"
          min="0"
          value={form.vat_pct}
          onChange={(e) => set("vat_pct", e.target.value)}
          disabled={disabled}
        />
      </div>
      <MoneyBox label={t("detail.pricing_column_subtotal")} value={money.subtotal} />
      <MoneyBox label={t("detail.pricing_column_vat")} value={money.vat} />
      <MoneyBox label={t("detail.pricing_column_total")} value={money.total} />
      <ModalFieldBox
        label={t("detail.pricing_customer_note_button")}
        value={form.customer_explanation}
        placeholder={t("detail.pricing_form_customer_note_placeholder")}
        onOpen={() => setModal("customer")}
        disabled={disabled}
        testId="proposal-line-customer-note-box"
      />
      {showInternal && (
        <ModalFieldBox
          label={t("detail.pricing_internal_note_button")}
          value={form.internal_note}
          placeholder={t("detail.pricing_form_internal_note_placeholder")}
          onOpen={() => setModal("internal")}
          disabled={disabled}
          testId="proposal-line-internal-note-box"
        />
      )}
      {actionsSlot}
    </div>
      {modal === "description" && (
        <NoteEditorDialog
          title={t("detail.pricing_form_description")}
          initialValue={form.description}
          placeholder={t("detail.pricing_form_description_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            set("description", value);
            setModal(null);
          }}
          onCancel={() => setModal(null)}
          testId="proposal-line-description-dialog"
        />
      )}
      {modal === "customer" && (
        <NoteEditorDialog
          title={t("detail.pricing_customer_note_modal_title")}
          initialValue={form.customer_explanation}
          placeholder={t("detail.pricing_form_customer_note_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            set("customer_explanation", value);
            setModal(null);
          }}
          onCancel={() => setModal(null)}
          testId="proposal-line-customer-note-dialog"
        />
      )}
      {showInternal && modal === "internal" && (
        <NoteEditorDialog
          title={t("detail.pricing_internal_note_modal_title")}
          initialValue={form.internal_note}
          placeholder={t("detail.pricing_form_internal_note_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            set("internal_note", value);
            setModal(null);
          }}
          onCancel={() => setModal(null)}
          testId="proposal-line-internal-note-dialog"
        />
      )}
      {modal === "custom_unit" && (
        <CustomUnitDialog
          initialValue={form.custom_unit_label}
          onSave={(name) => {
            setForm({ ...form, unit_type: "OTHER", custom_unit_label: name });
            setModal(null);
          }}
          onCancel={() => setModal(null)}
        />
      )}
    </>
  );
}

function payloadFromForm(
  form: LineFormState,
  showInternal: boolean,
): ProposalLineWritePayload {
  return {
    description: form.description.trim(),
    unit_type: form.unit_type,
    // Only meaningful for OTHER (the backend forces it blank for any
    // concrete unit type anyway — RF-2 mirror).
    custom_unit_label:
      form.unit_type === "OTHER" ? form.custom_unit_label.trim() : "",
    quantity: form.quantity,
    unit_price: form.unit_price,
    vat_pct: form.vat_pct,
    customer_explanation: form.customer_explanation,
    ...(showInternal ? { internal_note: form.internal_note } : {}),
  };
}

function ProposalAddLine({
  disabled,
  onAdd,
  onCancel,
}: {
  disabled: boolean;
  onAdd: (payload: ProposalLineWritePayload) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [form, setForm] = useState<LineFormState>({
    description: "",
    unit_type: "FIXED",
    custom_unit_label: "",
    quantity: "1.00",
    unit_price: "0.00",
    vat_pct: "21.00",
    customer_explanation: "",
    internal_note: "",
  });
  return (
    <div
      className="ew-line-row-card proposal-addline"
      data-testid="proposal-add-line-form"
      style={{ marginTop: 12 }}
    >
      <LineFields
        form={form}
        setForm={setForm}
        disabled={disabled}
        showInternal
        actionsSlot={
          // #109 Part E — the pre-#108 LABELED buttons restored (owner
          // point 1): the preview now lives BELOW the composer, so the
          // single row has the full card width and the labels fit.
          <div className="proposal-addline-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={disabled || !form.description.trim()}
              onClick={() => onAdd(payloadFromForm(form, true))}
              data-testid="proposal-add-line-submit"
            >
              {t("detail.proposal_add_line")}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={disabled}
              onClick={onCancel}
            >
              {t("common:cancel")}
            </button>
          </div>
        }
      />
    </div>
  );
}

// RF-6 (Ramazan 2026-06-24) — split-screen live PDF preview. Fetches the
// proposal PDF as an authenticated blob and shows it in an iframe next to the
// builder. Refreshes when `refreshNonce` changes (bumped after each saved
// mutation) plus a manual button — never per keystroke. The DRAFT PDF is
// already served to provider roles (backend `_resolve_proposal_or_404` only
// 404s DRAFT for customers), so no backend change is needed. Object URL is
// revoked on refresh + unmount; the fetch is cancelled-guarded.
function ProposalPreviewPane({
  ewId,
  proposalId,
  refreshNonce,
  onHide,
}: {
  ewId: number | string;
  proposalId: number;
  refreshNonce: number;
  // RF-14 — hides the pane entirely (builder takes the full width).
  onHide: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [manualNonce, setManualNonce] = useState(0);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const blob = await fetchProposalPdf(ewId, proposalId);
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = objectUrl;
        setUrl(objectUrl);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [ewId, proposalId, refreshNonce, manualNonce]);

  // Revoke the object URL on unmount (ref avoids a stale closure).
  useEffect(() => {
    return () => {
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, []);

  return (
    <div className="proposal-preview-pane" data-testid="proposal-live-preview">
      <div className="proposal-preview-head">
        <span className="proposal-preview-title">
          <FileText size={14} strokeWidth={2.2} />
          <span style={{ marginLeft: 6 }}>{t("detail.live_preview_title")}</span>
        </span>
        <span className="proposal-preview-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setManualNonce((n) => n + 1)}
            disabled={loading}
            data-testid="proposal-live-preview-refresh"
          >
            <RefreshCw size={13} strokeWidth={2.2} />
            <span style={{ marginLeft: 6 }}>
              {t("detail.live_preview_refresh")}
            </span>
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onHide}
            aria-label={t("detail.live_preview_hide")}
            title={t("detail.live_preview_hide")}
            data-testid="proposal-live-preview-hide"
          >
            <X size={14} strokeWidth={2.2} />
          </button>
        </span>
      </div>
      <div className="proposal-preview-body">
        {error ? (
          <div className="proposal-preview-status proposal-preview-status-error">
            {error}
          </div>
        ) : (
          <>
            {loading && !url && (
              <div className="proposal-preview-status">
                {t("detail.live_preview_loading")}
              </div>
            )}
            {url && (
              <iframe
                className="proposal-preview-frame"
                src={url}
                title={t("detail.live_preview_title")}
                data-testid="proposal-live-preview-frame"
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function ProposalBuilder({
  ewId,
  proposal,
  onChanged,
}: {
  ewId: number | string;
  proposal: ProposalDetail;
  onChanged: () => Promise<void> | void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  // Provider override-decision modal (SENT proposal). A customer decides
  // without a reason; a PROVIDER driving the customer decision is an
  // override and the backend coerces is_override + REQUIRES a non-blank
  // override_reason (400 `override_reason_required`). null = closed.
  const [overridePrompt, setOverridePrompt] = useState<
    "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED" | null
  >(null);
  const [overrideReason, setOverrideReason] = useState("");
  // RF-6 — bumped after every successful mutation (via `run`) so the live
  // PDF preview refetches. Not per-keystroke: only settled saves move it.
  const [previewNonce, setPreviewNonce] = useState(0);
  // RF-14 — whether the live preview pane is shown at all. Hidden, the
  // builder takes the full card width and the PDF is not fetched.
  const [previewOpen, setPreviewOpen] = useState(
    () => sessionStorage.getItem(PREVIEW_OPEN_KEY) !== "0",
  );
  const togglePreview = () =>
    setPreviewOpen((o) => {
      const next = !o;
      sessionStorage.setItem(PREVIEW_OPEN_KEY, next ? "1" : "0");
      return next;
    });

  const { me } = useAuth();
  const isProvider =
    me?.role === "SUPER_ADMIN" ||
    me?.role === "COMPANY_ADMIN" ||
    me?.role === "BUILDING_MANAGER";

  const canEdit = proposal.actions?.can_edit_lines === true;
  const canSend = proposal.actions?.can_send === true;
  // Sprint 31 — customer decision on a SENT proposal (and provider
  // override). The backend syncs the parent EW + spawns from the
  // proposal lines on approve.
  const canApprove = proposal.actions?.can_approve === true;
  const canReject = proposal.actions?.can_reject === true;

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await onChanged();
      // RF-6 — a settled mutation (line add/edit/remove, transition) is the
      // signal to refresh the live PDF preview.
      setPreviewNonce((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const removeLine = (lineId: number) =>
    void run(() => deleteProposalLine(ewId, proposal.id, lineId));
  const addLine = (payload: ProposalLineWritePayload) =>
    void run(async () => {
      await createProposalLine(ewId, proposal.id, payload);
      setAddOpen(false);
    });
  const send = () =>
    void run(() => transitionProposal(ewId, proposal.id, { to_status: "SENT" }));
  const approve = () => {
    if (isProvider) {
      // Provider approval of a SENT proposal is an override — collect the
      // mandatory reason before firing the transition.
      setOverrideReason("");
      setOverridePrompt("CUSTOMER_APPROVED");
      return;
    }
    void run(() =>
      transitionProposal(ewId, proposal.id, { to_status: "CUSTOMER_APPROVED" }),
    );
  };
  const reject = () => {
    if (isProvider) {
      setOverrideReason("");
      setOverridePrompt("CUSTOMER_REJECTED");
      return;
    }
    void run(() =>
      transitionProposal(ewId, proposal.id, { to_status: "CUSTOMER_REJECTED" }),
    );
  };
  const submitOverride = () => {
    const to = overridePrompt;
    if (to === null || overrideReason.trim() === "") return;
    void run(async () => {
      await transitionProposal(ewId, proposal.id, {
        to_status: to,
        is_override: true,
        override_reason: overrideReason.trim(),
      });
      setOverridePrompt(null);
      setOverrideReason("");
    });
  };

  // Per-line notes shown under the service label in the read-only table
  // (mirrors the cart table's "date + customer note" sub-line). Internal
  // note appears only when the serializer included it (provider reads).
  const renderNoteSub = (line: ProposalLine) => {
    const showInternal = Object.prototype.hasOwnProperty.call(
      line,
      "internal_note",
    );
    const cust = line.customer_explanation.trim();
    const intl = showInternal ? (line.internal_note ?? "").trim() : "";
    if (!cust && !intl) return undefined;
    return (
      <>
        {cust && <div className="muted small">{cust}</div>}
        {intl && (
          <div className="muted small" style={{ fontStyle: "italic" }}>
            {t("detail.pricing_internal_note_button")}: {intl}
          </div>
        )}
      </>
    );
  };

  // RF-14 — the whole pricing area (builder + preview) is a collapsible
  // card: open while the proposal still needs action (pricing a DRAFT,
  // deciding a SENT one), collapsed for anything historical.
  const actionPending =
    proposal.status === "DRAFT" || proposal.status === "SENT";

  return (
    <CollapsibleCard
      title={t("detail.proposal_builder_title")}
      meta={
        <>
          {t("detail.card_lines_count", { count: proposal.lines.length })}
          {" · "}
          {t("detail.pricing_column_total")}:{" "}
          {formatMoney(proposal.total_amount)}
        </>
      }
      defaultOpen={actionPending}
      testId="extra-work-proposal-card"
    >
    <div
      className={
        previewOpen ? "proposal-split" : "proposal-split proposal-split-single"
      }
      data-testid="extra-work-proposal-split"
    >
      <div
        className="proposal-builder-main"
        data-testid="extra-work-proposal-builder"
      >
        {!previewOpen && (
          <div className="proposal-preview-show-row">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={togglePreview}
              data-testid="proposal-live-preview-show"
            >
              <FileText size={13} strokeWidth={2.2} />
              <span style={{ marginLeft: 6 }}>
                {t("detail.live_preview_show")}
              </span>
            </button>
          </div>
        )}
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("detail.proposal_builder_helper")}
        </p>
        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        {/* Saved proposal lines render read-only in the same table layout
            as the cart's "Requested services" (InvoiceLineRow). When the
            viewer can edit, each row carries a Remove action — there is no
            inline edit; a line is changed by removing it and re-adding it
            through the composer below (legacy composer behavior). */}
        {proposal.lines.length === 0 ? (
          <p className="muted small">{t("detail.proposal_builder_empty")}</p>
        ) : (
          <div className="ew-table-scroll">
            <table className="data-table ew-pricing-table">
              <thead>
                <tr>
                  {INVOICE_LINE_COLUMN_KEYS.map((key) => (
                    <th key={key}>{t(key)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {proposal.lines.map((line) => (
                  <InvoiceLineRow
                    key={line.id}
                    lineKind="proposal"
                    line={line}
                    editable={canEdit}
                    onRemove={canEdit ? () => removeLine(line.id) : undefined}
                    rowTestId="extra-work-proposal-line-row"
                    subLabel={renderNoteSub(line)}
                  />
                ))}
                <InvoiceLineTotalsRow
                  subtotal={proposal.subtotal_amount}
                  vatAmount={proposal.vat_amount}
                  total={proposal.total_amount}
                />
              </tbody>
            </table>
          </div>
        )}

        {/* Add-line composer — the ONLY editing surface. Live per-line
            Subtotal / VAT / Total + the note modals live in here; on save
            the line drops into the read-only table above. */}
        {canEdit && (
          <div className="ew-pricing-add-form">
            {addOpen ? (
              <ProposalAddLine
                disabled={busy}
                onAdd={addLine}
                onCancel={() => setAddOpen(false)}
              />
            ) : (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ marginTop: 12 }}
                disabled={busy}
                onClick={() => setAddOpen(true)}
                data-testid="proposal-add-line-toggle"
              >
                <Plus size={14} strokeWidth={2.2} />
                <span style={{ marginLeft: 6 }}>
                  {t("detail.proposal_add_line")}
                </span>
              </button>
            )}
          </div>
        )}

        <div
          className="alert-info"
          style={{ marginTop: 12 }}
          data-testid="extra-work-proposal-totals"
        >
          {t("detail.pricing_column_subtotal")}: {formatMoney(proposal.subtotal_amount)}
          {" · "}
          {t("detail.pricing_column_vat")}: {formatMoney(proposal.vat_amount)}
          {" · "}
          {t("detail.pricing_column_total")}:{" "}
          <strong>{formatMoney(proposal.total_amount)}</strong>
        </div>

        {canSend && (
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy}
              onClick={send}
              data-testid="extra-work-proposal-send"
            >
              {busy ? t("detail.proposal_sending") : t("detail.proposal_send")}
            </button>
            <p className="muted small" style={{ margin: "6px 0 0" }}>
              {t("detail.proposal_send_hint")}
            </p>
          </div>
        )}

        {(canApprove || canReject) && (
          <div
            style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}
            data-testid="extra-work-proposal-decision"
          >
            {canApprove && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={busy}
                onClick={approve}
                data-testid="extra-work-proposal-approve"
              >
                {t("detail.proposal_approve")}
              </button>
            )}
            {canReject && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={busy}
                onClick={reject}
                data-testid="extra-work-proposal-reject"
              >
                {t("detail.proposal_reject")}
              </button>
            )}
          </div>
        )}

        {/* Provider override-decision modal. The confirm button stays
            disabled until a non-blank reason is typed, mirroring the
            backend's `override_reason_required` guard. */}
        {overridePrompt !== null && (
          <div
            className="reject-modal-backdrop"
            data-testid="extra-work-proposal-override-dialog"
            role="dialog"
            aria-modal="true"
          >
            <div className="reject-modal">
              <h3 className="reject-modal-title">
                {overridePrompt === "CUSTOMER_APPROVED"
                  ? t("detail.proposal_override_approve_title")
                  : t("detail.proposal_override_reject_title")}
              </h3>
              <p className="reject-modal-desc">
                {t("detail.proposal_override_desc")}
              </p>
              <textarea
                className="field-textarea reject-modal-textarea"
                data-testid="extra-work-proposal-override-reason"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder={t("detail.proposal_override_reason_placeholder")}
                rows={4}
                autoFocus
              />
              <div className="reject-modal-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={() => {
                    setOverridePrompt(null);
                    setOverrideReason("");
                  }}
                  data-testid="extra-work-proposal-override-cancel"
                >
                  {t("detail.note_modal_cancel")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={busy || overrideReason.trim() === ""}
                  onClick={submitOverride}
                  data-testid="extra-work-proposal-override-confirm"
                >
                  {busy
                    ? t("detail.proposal_override_submitting")
                    : t("detail.proposal_override_confirm")}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
      {previewOpen && (
        <ProposalPreviewPane
          ewId={ewId}
          proposalId={proposal.id}
          refreshNonce={previewNonce}
          onHide={togglePreview}
        />
      )}
    </div>
    </CollapsibleCard>
  );
}
