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
import { describeExtraWorkRefusal } from "../lib/extraWorkRefusal";
import type { ExtraWorkRefusal } from "../lib/extraWorkRefusal";
import {
  createProposalLine,
  deleteProposalLine,
  fetchProposalPdf,
  transitionProposal,
  updateProposalLine,
  type ProposalLineWritePayload,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import type { ExtraWorkUnitType, ProposalDetail, ProposalLine } from "../api/types";
import { formatMoney } from "../lib/intl";
import { CollapsibleCard } from "./CollapsibleCard";
import { ConfirmDialog } from "./ConfirmDialog";
import type { ConfirmDialogHandle } from "./ConfirmDialog";
import { InvoiceLineRow, InvoiceLineTotalsRow } from "./InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "./invoiceLineColumns";
import { NoteEditorDialog } from "./NoteEditorDialog";
import { RejectReasonDialog } from "./RejectReasonDialog";

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

export interface RequestLineSeed {
  id: number;
  label: string;
  quantity: string;
  unit_type: ExtraWorkUnitType;
}

const EMPTY_LINE_FORM: LineFormState = {
  description: "",
  unit_type: "FIXED",
  custom_unit_label: "",
  quantity: "1.00",
  // W-FIX1 A3 (audit F3) — EMPTY, not "0.00". Zero is a legal price the
  // operator types on purpose; a default of 0.00 made a price nobody
  // entered indistinguishable from free work, and EW 28 went to the
  // customer at €0.00 that way.
  unit_price: "",
  vat_pct: "21.00",
  customer_explanation: "",
  internal_note: "",
};

/** Sprint 187 §2c — a SAVED line's values, back in the composer's shape.
 *
 *  `unit_type` is `OTHER` on the wire whenever the operator typed a
 *  custom unit, so the round trip has to put the label back in
 *  `custom_unit_label` — otherwise reopening a "per pallet" line and
 *  pressing Save would silently rewrite it to a bare "Other". */
function formFromLine(line: ProposalLine): LineFormState {
  return {
    description: line.description ?? "",
    unit_type: line.unit_type,
    custom_unit_label: line.custom_unit_label ?? "",
    quantity: String(line.quantity),
    unit_price: String(line.unit_price),
    vat_pct: String(line.vat_pct),
    customer_explanation: line.customer_explanation ?? "",
    internal_note: line.internal_note ?? "",
  };
}

/**
 * The composer, used for BOTH add and edit.
 *
 * Sprint 187 §2c — `PATCH .../lines/<id>/` and its typed client wrapper
 * `updateProposalLine` have both existed since the endpoint shipped, with
 * ZERO importers: the builder was add/delete only, so correcting one
 * price meant deleting the line and retyping every field of it. Edit is
 * wired now, and it reuses this component rather than growing a second
 * form — one set of fields, one validation rule, one place a unit-type
 * change has to be handled.
 */
/** W-FIX1 A3 — a price is "entered" when the box holds a number, 0.00
 *  included. An empty box is not a price. */
function priceEntered(form: LineFormState): boolean {
  const raw = form.unit_price.trim();
  return raw !== "" && Number.isFinite(Number(raw)) && Number(raw) >= 0;
}

function ProposalLineComposer({
  disabled,
  initial,
  submitLabel,
  testIdPrefix,
  onSubmit,
  onCancel,
}: {
  disabled: boolean;
  initial: LineFormState;
  submitLabel: string;
  testIdPrefix: string;
  onSubmit: (payload: ProposalLineWritePayload) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [form, setForm] = useState<LineFormState>(initial);
  return (
    <div
      className="ew-line-row-card proposal-addline"
      data-testid={`${testIdPrefix}-form`}
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
              disabled={
                disabled || !form.description.trim() || !priceEntered(form)
              }
              onClick={() => onSubmit(payloadFromForm(form, true))}
              data-testid={`${testIdPrefix}-submit`}
            >
              {submitLabel}
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
      {form.description.trim() !== "" && !priceEntered(form) && (
        /* W-FIX1 A3 — the reason a line cannot be saved yet. P-7 S3.2
           — UNDER the row rather than inside the buttons' cell: as a
           third flex child there it widened the actions column while
           the operator typed, and the buttons walked sideways. */
        <p
          className="muted small proposal-addline-note"
          data-testid={`${testIdPrefix}-price-required`}
        >
          {t("detail.pricing_form_unit_price_required")}
        </p>
      )}
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
  parentAdvanceBlocked = false,
  noCustomerApproval = false,
  requestLines,
  customerName = null,
  onOpenPlan,
}: {
  ewId: number | string;
  proposal: ProposalDetail;
  onChanged: () => Promise<void> | void;
  // Sprint 188 — creating this proposal was meant to start the review,
  // and did not. Without this the builder shows the generic "Send is not
  // available yet" line, which is true but useless: the operator cannot
  // tell that ONE click on the workflow card above fixes it.
  parentAdvanceBlocked?: boolean;
  /** W-FIX4 §2 — the parent request has NO customer-approval step
   *  (DIRECT_AGREED_PRICE_ORDER / AUTO_START_AFTER_PRICING). On those
   *  routes every visible string loses "proposal" / "send to customer":
   *  the SAME send action reads "Start the work", because for this
   *  request that is literally what SEND does (DRAFT→SENT
   *  auto-approves and spawns — `proposal_state_machine.py:667`).
   *  MECHANICS UNTOUCHED: same handler, same endpoint, same statuses.
   *  The page owns the predicate; this component only words itself. */
  noCustomerApproval?: boolean;
  /** W-FIX1 A3 — the request's own lines, offered as one-click seeds
   *  for the composer so the proposal line inherits the requested name. */
  requestLines?: RequestLineSeed[];
  /** P-8R A4 — who the price goes to; the send confirm names them. */
  customerName?: string | null;
  /** P-8R A3 — a `plan_requirements_unmet` refusal offers "Complete the
   *  plan"; the page owns the plan modal, so it opens it (at the first
   *  gap the server named). */
  onOpenPlan?: (unmet: string[]) => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // P-8R A3 — the refusal's kind rides with the sentence so the render
  // site can offer its door; the sentence scrolls into view at the
  // action buttons it belongs to.
  const [refusal, setRefusal] = useState<ExtraWorkRefusal | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [error]);
  // P-8R A4 — sending a price asks once, showing the lines and the total.
  const sendDialogRef = useRef<ConfirmDialogHandle>(null);
  const [addOpen, setAddOpen] = useState(false);
  /* W-FIX1 A3 — what the add composer opens with; a request-line chip
     re-seeds it (the key remounts the composer's own form state). */
  const [addSeed, setAddSeed] = useState<{ key: number; form: LineFormState }>({
    key: 0,
    form: EMPTY_LINE_FORM,
  });
  const unseededRequestLines = (requestLines ?? []).filter(
    (line) =>
      !proposal.lines.some(
        (saved) =>
          (saved.description ?? "").trim().toLowerCase() ===
            line.label.trim().toLowerCase() ||
          (saved.service_name ?? "").trim().toLowerCase() ===
            line.label.trim().toLowerCase(),
      ),
  );
  // Provider override-decision modal (SENT proposal). A customer decides
  // without a reason; a PROVIDER driving the customer decision is an
  // override and the backend coerces is_override + REQUIRES a non-blank
  // override_reason (400 `override_reason_required`). null = closed.
  const [overridePrompt, setOverridePrompt] = useState<
    "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED" | null
  >(null);
  // Sprint 187 §2c — the id of the saved line currently open for edit,
  // or null. One at a time: two open editors on the same table is two
  // sources of truth for a row.
  const [editingLineId, setEditingLineId] = useState<number | null>(null);
  // Sprint 187 §2b — discard a DRAFT / withdraw a SENT quote.
  // Rendered UNCONDITIONALLY and driven through the ref (CLAUDE.md §3):
  // wrapping a native <dialog> in `{cond && ...}` mounts an invisible
  // dialog and the trigger button looks dead.
  const cancelDialogRef = useRef<ConfirmDialogHandle>(null);
  // The SENT leg is coerced to `is_override=True` by
  // `provider_driven_sent_cancel` and REQUIRES a reason; the DRAFT leg
  // is a plain transition. One dialog, one flag, rather than two.
  const cancelNeedsReason = proposal.status === "SENT";
  const [cancelReason, setCancelReason] = useState("");
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
  // Sprint 187 §2b — the serializer has advertised this for DRAFT and
  // SENT since the endpoint shipped and nothing read it, so a sent quote
  // had no non-override way back and a draft could not be thrown away.
  const canCancel = proposal.actions?.can_cancel === true;

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
      const described = describeExtraWorkRefusal(err, t);
      setError(described.sentence);
      setRefusal(described);
    } finally {
      setBusy(false);
    }
  }

  const removeLine = (lineId: number) =>
    void run(async () => {
      await deleteProposalLine(ewId, proposal.id, lineId);
      // Sprint 187C — Remove stays rendered on every row INCLUDING the
      // one being edited, so deleting that row left `editingLineId`
      // pointing at a line that no longer exists: the edit block's
      // find() returns undefined and renders nothing, so the composer
      // vanishes with no way back except reloading the page.
      setEditingLineId((current) => (current === lineId ? null : current));
    });
  const addLine = (payload: ProposalLineWritePayload) =>
    void run(async () => {
      await createProposalLine(ewId, proposal.id, payload);
      setAddOpen(false);
    });
  // Sprint 187 §2c — the PATCH that had no caller. Same `run()` helper
  // as every other mutation here, so it gets the same refetch and the
  // same live-preview refresh rather than a second refresh path.
  const saveLine = (lineId: number, payload: ProposalLineWritePayload) =>
    void run(async () => {
      await updateProposalLine(ewId, proposal.id, lineId, payload);
      setEditingLineId(null);
    });
  // Sprint 187 §2b — discard (DRAFT) / withdraw (SENT). The reason is
  // sent ONLY on the SENT leg: the backend coerces `is_override` there
  // and 400s `override_reason_required` without one, while the DRAFT leg
  // takes neither.
  const confirmCancel = () =>
    void run(async () => {
      await transitionProposal(ewId, proposal.id, {
        to_status: "CANCELLED",
        ...(cancelNeedsReason
          ? { is_override: true, override_reason: cancelReason.trim() }
          : {}),
      });
      cancelDialogRef.current?.close();
      setCancelReason("");
    });
  // P-8R A4 — Send asks first (the lines, the total, the customer);
  // the confirm runs the same transition it always did.
  const send = () => {
    setError("");
    sendDialogRef.current?.open();
  };
  const confirmSend = () =>
    void run(async () => {
      await transitionProposal(ewId, proposal.id, { to_status: "SENT" });
      sendDialogRef.current?.close();
    });
  const approve = () => {
    if (isProvider) {
      // Provider approval of a SENT proposal is an override — collect the
      // mandatory reason before firing the transition.
      setOverridePrompt("CUSTOMER_APPROVED");
      return;
    }
    void run(() =>
      transitionProposal(ewId, proposal.id, { to_status: "CUSTOMER_APPROVED" }),
    );
  };
  const reject = () => {
    if (isProvider) {
      setOverridePrompt("CUSTOMER_REJECTED");
      return;
    }
    void run(() =>
      transitionProposal(ewId, proposal.id, { to_status: "CUSTOMER_REJECTED" }),
    );
  };
  const submitOverride = (reason: string) => {
    const to = overridePrompt;
    if (to === null || reason.trim() === "") return;
    // The modal closes on confirm; a refusal lands under the decision
    // buttons (the acting control), scrolled into view.
    setOverridePrompt(null);
    void run(async () => {
      await transitionProposal(ewId, proposal.id, {
        to_status: to,
        is_override: true,
        override_reason: reason.trim(),
      });
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
      title={t(
        noCustomerApproval
          ? "detail.proposal_builder_title_start"
          : "detail.proposal_builder_title",
      )}
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
        {/* W-UX F16 -- the "set a price" instruction is only true while
            the lines can still be edited. */}
        {canEdit && (
          <p className="muted small" style={{ marginTop: 0 }}>
            {t(
              noCustomerApproval
                ? "detail.proposal_builder_helper_start"
                : "detail.proposal_builder_helper",
            )}
          </p>
        )}
        {/* Saved proposal lines render read-only in the same table layout
            as the cart's "Requested services" (InvoiceLineRow). When the
            viewer can edit, each row carries a Remove action — there is no
            inline edit; a line is changed by removing it and re-adding it
            through the composer below (legacy composer behavior). */}
        {proposal.lines.length === 0 ? (
          <p className="muted small">
            {t(
              noCustomerApproval
                ? "detail.proposal_builder_empty_start"
                : "detail.proposal_builder_empty",
            )}
          </p>
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
                    // Sprint 187 §2c — `InvoiceLineRow` has rendered an
                    // Edit button whenever `onEdit` is passed since it
                    // was written; the builder simply never passed one.
                    onEdit={
                      canEdit ? () => setEditingLineId(line.id) : undefined
                    }
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

        {/* Sprint 187 §2c — the edit composer for ONE saved line, opened
            from that line's Edit button. Keyed by line id so switching
            rows re-seeds the form rather than carrying the previous
            line's values into the next one. */}
        {canEdit && editingLineId !== null && (
          <div className="ew-pricing-add-form">
            {(() => {
              const line = proposal.lines.find((l) => l.id === editingLineId);
              if (!line) return null;
              return (
                <ProposalLineComposer
                  key={line.id}
                  disabled={busy}
                  initial={formFromLine(line)}
                  submitLabel={t("common:save")}
                  testIdPrefix="proposal-edit-line"
                  onSubmit={(payload) => saveLine(line.id, payload)}
                  onCancel={() => setEditingLineId(null)}
                />
              );
            })()}
          </div>
        )}

        {/* Add-line composer. Live per-line Subtotal / VAT / Total + the
            note modals live in here; on save the line drops into the
            read-only table above. */}
        {canEdit && editingLineId === null && (
          <div className="ew-pricing-add-form">
            {addOpen ? (
              <>
                {/* W-FIX1 A3 (audit F3) — the requested line's NAME
                    comes across. The server seeds only contract-priced
                    lines (a custom line has no price to seed and the
                    line row cannot hold "no price yet"), so the
                    operator retyped the name — EW 28 went out as "g"
                    for "Waste removal — small van". One click seeds
                    the composer with the request's own words, unit and
                    quantity; the price stays theirs to enter. */}
                {unseededRequestLines.length > 0 && (
                  <div
                    className="proposal-request-lines"
                    data-testid="proposal-add-from-request"
                    style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}
                  >
                    <span className="muted small">{t("detail.add_from_request")}</span>
                    {unseededRequestLines.map((line) => (
                      <button
                        key={line.id}
                        type="button"
                        className="btn btn-secondary btn-sm"
                        disabled={busy}
                        onClick={() =>
                          setAddSeed({
                            key: addSeed.key + 1,
                            form: {
                              ...EMPTY_LINE_FORM,
                              description: line.label,
                              quantity: line.quantity,
                              unit_type: line.unit_type,
                            },
                          })
                        }
                        data-testid={`proposal-add-from-request-${line.id}`}
                      >
                        {line.label}
                      </button>
                    ))}
                  </div>
                )}
                <ProposalLineComposer
                  key={addSeed.key}
                  disabled={busy}
                  initial={addSeed.form}
                  submitLabel={t("detail.proposal_add_line")}
                  testIdPrefix="proposal-add-line"
                  onSubmit={addLine}
                  onCancel={() => setAddOpen(false)}
                />
              </>
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

        {/* Sprint 187 §2a — Send is never simply ABSENT on a draft the
            operator may edit.
            This used to be a bare `{canSend && (...)}` with no else
            branch: an operator who reached the builder from a REQUESTED
            parent built a whole quote and found no Send button, no
            message and no tooltip — and since `can_direct_publish` is
            derived from `can_send`, the escape hatch was hidden too, so
            BOTH terminal actions on the screen were dead.
            The backend has always carried a stable code for exactly this
            (`proposal_send_requires_under_review`, whose own comment
            says it exists "so the UI can explain the precondition"); the
            UI never reached it because it hid the button instead of
            pressing it. Creating a proposal now advances the parent, so
            the case should not arise at all — but a disabled button with
            the reason beside it is what any REMAINING case gets, rather
            than silence. */}
        {canSend ? (
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy}
              onClick={send}
              data-testid="extra-work-proposal-send"
            >
              {busy
                ? t(
                    noCustomerApproval
                      ? "detail.proposal_sending_start"
                      : "detail.proposal_sending",
                  )
                : t(
                    noCustomerApproval
                      ? "detail.proposal_send_start"
                      : "detail.proposal_send",
                  )}
            </button>
            
          </div>
        ) : (
          canEdit && (
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled
                data-testid="extra-work-proposal-send-blocked"
              >
                {t(
                  noCustomerApproval
                    ? "detail.proposal_send_start"
                    : "detail.proposal_send",
                )}
              </button>
              <p
                className="muted small"
                style={{ margin: "6px 0 0" }}
                data-testid="extra-work-proposal-send-blocked-reason"
              >
                {proposal.lines.length === 0
                  ? /* W-FIX1 A3 — nothing to send without a line; the
                       server's `can_send` says the same. */
                    t("detail.proposal_send_blocked_no_lines")
                  : parentAdvanceBlocked
                  ? t(
                      noCustomerApproval
                        ? "detail.proposal_send_blocked_parent_start"
                        : "detail.proposal_send_blocked_parent",
                    )
                  : t(
                      noCustomerApproval
                        ? "detail.proposal_send_blocked_reason_start"
                        : "detail.proposal_send_blocked_reason",
                    )}
              </p>
            </div>
          )
        )}

        {(canApprove || canReject) && (
          <div
            style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}
            data-testid="extra-work-proposal-decision"
          >
            {canApprove && (
              <button
                type="button"
                /* P-8R A4 — a provider deciding on the customer's behalf
                   is an override: amber, never green. The customer's own
                   approve stays the primary green. */
                className={isProvider ? "btn btn-warning btn-sm" : "btn btn-primary btn-sm"}
                disabled={busy}
                onClick={approve}
                data-testid="extra-work-proposal-approve"
              >
                {t(
                  noCustomerApproval
                    ? "detail.proposal_approve_start"
                    : "detail.proposal_approve",
                )}
              </button>
            )}
            {canReject && (
              <button
                type="button"
                className={isProvider ? "btn btn-danger btn-sm" : "btn btn-secondary btn-sm"}
                disabled={busy}
                onClick={reject}
                data-testid="extra-work-proposal-reject"
              >
                {t(
                  noCustomerApproval
                    ? "detail.proposal_reject_start"
                    : "detail.proposal_reject",
                )}
              </button>
            )}
          </div>
        )}

        {/* Sprint 187 §2b — the way OUT of a quote.
            A DRAFT could not be thrown away and a SENT quote could not
            be withdrawn: `can_cancel` was advertised for both and read by
            nothing, so the only exit from a sent quote was an override
            approve/reject of a price nobody wanted. Live consequence:
            proposal 13 on EW 58, SENT since 20 July with no way back.
            One control, worded for the state it is in — discarding a
            draft nobody has seen and withdrawing a quote a customer is
            holding are not the same act. */}
        {canCancel && (
          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => {
                setCancelReason("");
                cancelDialogRef.current?.open();
              }}
              data-testid="extra-work-proposal-cancel"
            >
              {cancelNeedsReason
                ? t(
                    noCustomerApproval
                      ? "detail.proposal_withdraw_start"
                      : "detail.proposal_withdraw",
                  )
                : t("detail.proposal_discard")}
            </button>
          </div>
        )}

        {/* P-8R A3 — the refusal, AT the buttons it answers, in the
            reader's words, with its door. */}
        {error && (
          <div
            ref={errorRef}
            className="alert-error"
            role="alert"
            style={{ marginTop: 12 }}
            data-testid="extra-work-proposal-error"
            data-refusal-kind={refusal?.kind ?? "generic"}
          >
            <div>{error}</div>
            {refusal?.kind === "plan_gap" && onOpenPlan && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ marginTop: 8 }}
                onClick={() => onOpenPlan(refusal.unmet)}
                data-testid="extra-work-proposal-complete-plan"
              >
                {t("refused.complete_plan")}
              </button>
            )}
          </div>
        )}

        {/* P-8R A4 — the provider's decision on the customer's behalf:
            the amber reason modal (the drawer's pattern). */}
        <RejectReasonDialog
          open={overridePrompt !== null}
          tone="warning"
          title={
            overridePrompt === "CUSTOMER_APPROVED"
              ? t("detail.proposal_override_approve_title")
              : t("detail.proposal_override_reject_title")
          }
          description={t("detail.proposal_override_desc")}
          placeholder={t("detail.proposal_override_reason_placeholder")}
          confirmLabel={t("detail.proposal_override_confirm")}
          cancelLabel={t("detail.note_modal_cancel")}
          onCancel={() => setOverridePrompt(null)}
          onConfirm={(reason) => submitOverride(reason)}
        />
        {/* P-8R A4 — Send asks once: the lines, the total, the customer. */}
        <ConfirmDialog
          ref={sendDialogRef}
          title={t(
            noCustomerApproval
              ? "detail.send_dialog_title_start"
              : "detail.send_dialog_title",
          )}
          body={
            <div data-testid="extra-work-proposal-send-dialog">
              <ul className="ew-send-dialog-lines" style={{ margin: "0 0 8px", paddingLeft: 18 }}>
                {proposal.lines.map((line) => (
                  <li key={line.id} data-testid="extra-work-proposal-send-dialog-line">
                    {(line.service_name || line.description || "").trim() || `#${line.id}`}
                    {" — "}
                    {line.quantity} × {formatMoney(line.unit_price)}
                  </li>
                ))}
              </ul>
              <p style={{ fontWeight: 600 }} data-testid="extra-work-proposal-send-dialog-total">
                {t("detail.pricing_column_total")}: {formatMoney(proposal.total_amount)}
              </p>
              <p className="muted small">
                {t(
                  noCustomerApproval
                    ? "detail.send_dialog_question_start"
                    : "detail.send_dialog_question",
                  { customer: customerName ?? t("detail.send_dialog_customer_fallback") },
                )}
              </p>
            </div>
          }
          confirmLabel={t(
            noCustomerApproval ? "detail.proposal_send_start" : "detail.proposal_send",
          )}
          busy={busy}
          busyLabel={t(
            noCustomerApproval ? "detail.proposal_sending_start" : "detail.proposal_sending",
          )}
          onConfirm={confirmSend}
        />
        {/* Sprint 187 §2b — UNCONDITIONAL, ref-driven (CLAUDE.md §3).
            `{canCancel && <ConfirmDialog/>}` would mount an invisible
            native <dialog> and the trigger above would look dead — the
            Sprint 128 bug, restated. */}
        <ConfirmDialog
          ref={cancelDialogRef}
          title={
            cancelNeedsReason
              ? t(
                  noCustomerApproval
                    ? "detail.proposal_withdraw_confirm_title_start"
                    : "detail.proposal_withdraw_confirm_title",
                )
              : t(
                  noCustomerApproval
                    ? "detail.proposal_discard_confirm_title_start"
                    : "detail.proposal_discard_confirm_title",
                )
          }
          body={
            <>
              <p style={{ marginTop: 0 }}>
                {cancelNeedsReason
                  ? t(
                      noCustomerApproval
                        ? "detail.proposal_withdraw_confirm_body_start"
                        : "detail.proposal_withdraw_confirm_body",
                    )
                  : t(
                      noCustomerApproval
                        ? "detail.proposal_discard_confirm_body_start"
                        : "detail.proposal_discard_confirm_body",
                    )}
              </p>
              {cancelNeedsReason && (
                <textarea
                  className="field-textarea"
                  data-testid="extra-work-proposal-cancel-reason"
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  placeholder={t(
                    noCustomerApproval
                      ? "detail.proposal_withdraw_reason_placeholder_start"
                      : "detail.proposal_withdraw_reason_placeholder",
                  )}
                  rows={3}
                  aria-label={t(
                    noCustomerApproval
                      ? "detail.proposal_withdraw_reason_placeholder_start"
                      : "detail.proposal_withdraw_reason_placeholder",
                  )}
                />
              )}
            </>
          }
          confirmLabel={
            cancelNeedsReason
              ? t(
                  noCustomerApproval
                    ? "detail.proposal_withdraw_start"
                    : "detail.proposal_withdraw",
                )
              : t("detail.proposal_discard")
          }
          onConfirm={confirmCancel}
          onCancel={() => setCancelReason("")}
          busy={busy}
          // The backend 400s `override_reason_required` on the SENT leg
          // without a reason; disabling here says so before the round
          // trip rather than after it.
          confirmDisabled={cancelNeedsReason && cancelReason.trim() === ""}
          destructive
        />
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
