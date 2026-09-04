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
// P-10 B4 — edits happen IN the row and nothing saves itself: Edit turns
// a line into inputs with Save · Cancel, an unpriced request line is
// such a row from the start, and a new line is one at the foot of the
// table. The editor that used to sit below the table is gone. The rules
// (units, when Save is refused, the payload) are `lib/pricingRow`'s.
//
// Only `ProposalBuilder` is exported (react-refresh/only-export-
// components); the row helpers stay local to this file.
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  announceDone,
  safeSessionStorage,
} from "./guide/doneBannerStore";
import { FileText, Plus, RefreshCw, X } from "lucide-react";

import { getApiError } from "../api/client";
import {
  compareCoverage,
  coverageConfirmLabel,
  type CoverageLine,
} from "../lib/extraWorkCoverage";
import { describeExtraWorkRefusal } from "../lib/extraWorkRefusal";
import type { ExtraWorkRefusal } from "../lib/extraWorkRefusal";
import {
  createProposalLine,
  deleteProposalLine,
  fetchProposalPdf,
  transitionProposal,
  updateProposalLine,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import type { ExtraWorkUnitType, ProposalDetail, ProposalLine } from "../api/types";
import { formatMoney } from "../lib/intl";
import {
  PRICING_ROW_BLOCKER_KEY,
  PRICING_UNIT_LABEL_KEY,
  PRICING_UNIT_OPTIONS,
  emptyPricingRow,
  pricingRowBlocker,
  pricingRowEquals,
  pricingRowFromLine,
  pricingRowFromRequest,
  pricingRowMoney,
  pricingRowPayload,
  type PricingRowDraft,
} from "../lib/pricingRow";
import { unitSuffix } from "../lib/unitLabel";
import { CollapsibleCard } from "./CollapsibleCard";
import { CoverageNotice } from "./extra-work/CoverageNotice";
import { ConfirmDialog } from "./ConfirmDialog";
import type { ConfirmDialogHandle } from "./ConfirmDialog";
import { InvoiceLineRow, InvoiceLineTotalsRow } from "./InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "./invoiceLineColumns";
import { RejectReasonDialog } from "./RejectReasonDialog";

// RF-14 — the live preview pane's visibility survives navigation within
// a tab session (sessionStorage), so an operator who prefers the full-
// width builder is not forced to re-hide the pane on every EW.
const PREVIEW_OPEN_KEY = "ew-proposal-preview-open";

export interface RequestLineSeed {
  id: number;
  label: string;
  quantity: string;
  unit_type: ExtraWorkUnitType;
  /** The catalog service behind the line, or null for a free-text one. */
  service: number | null;
  /** The customer's note on the line, shown under its name. */
  note?: string;
}

/**
 * P-10 B4 — ONE ROW OF THE PRICING TABLE, IN EDIT MODE.
 *
 * The owner: edits happen in the row, and nothing saves itself. "Edit"
 * on a line turns THAT row into inputs — description (custom lines
 * only), quantity, unit (the catalogue's list plus "other", the one
 * door to a unit word of the operator's own), unit price, VAT — with
 * Save · Cancel in its actions cell; the notes sit in a second row under
 * it while editing. The same row prices a requested line the quote does
 * not cover yet (P-9 C3: pre-filled with what the customer asked for, so
 * the operator sees what will change before it changes; Save appears
 * once something is typed) and adds a new line (an empty row at the foot
 * of the table). Save is refused with its reason beside it while the
 * server would refuse it (§D.6 rule 14); the rules are `lib/pricingRow`'s.
 */
function PricingRowEditor({
  rowKey,
  initial,
  customLine,
  label,
  note,
  sourceTag,
  showNotes,
  showInternal,
  busy,
  saveWhenChangedOnly = false,
  focusPrice = false,
  autoFocus = null,
  priceAria,
  priceTestId,
  rowTestId,
  onSave,
  onCancel,
  extraActions,
}: {
  /** The row in every testid: a line id, `request-<id>` or `new`. */
  rowKey: string;
  initial: PricingRowDraft;
  /** A line without a catalogue service: its description is typed here. */
  customLine: boolean;
  /** The catalogue service's name, when the description is not typed. */
  label: string | null;
  /** The customer's note on a requested line, under the name. */
  note?: string;
  sourceTag: ReactNode;
  /** The notes row under the line: the customer note, and the internal
   *  note of a custom line on a provider read. */
  showNotes: boolean;
  showInternal: boolean;
  busy: boolean;
  /** An unpriced request row: Save · Cancel only once something is typed. */
  saveWhenChangedOnly?: boolean;
  /** The coverage notice's "Add a price for X" lands on the price box. */
  focusPrice?: boolean;
  autoFocus?: "description" | "unit_price" | null;
  priceAria?: string;
  priceTestId?: string;
  rowTestId: string;
  onSave: (draft: PricingRowDraft) => void;
  onCancel: () => void;
  /** Rendered after Save · Cancel ("Leave it out" on a request row). */
  extraActions?: ReactNode;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [draft, setDraft] = useState<PricingRowDraft>(initial);
  const priceRef = useRef<HTMLInputElement>(null);
  const descriptionRef = useRef<HTMLInputElement>(null);
  const set = <K extends keyof PricingRowDraft>(key: K, value: PricingRowDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const changed = !pricingRowEquals(draft, initial);
  const blocker = pricingRowBlocker(draft, { customLine });
  const showSave = !saveWhenChangedOnly || changed;
  const canSave = blocker === null && !busy;
  const money = pricingRowMoney(draft);
  const whyId = `pricing-row-why-${rowKey}`;
  useEffect(() => {
    if (autoFocus === "description") descriptionRef.current?.focus();
    else if (autoFocus === "unit_price") priceRef.current?.focus();
  }, [autoFocus]);
  useEffect(() => {
    if (!focusPrice) return;
    priceRef.current?.focus();
    priceRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusPrice]);
  const save = () => {
    if (canSave) onSave(draft);
  };
  const cancel = () => {
    setDraft(initial);
    onCancel();
  };
  // Enter in a box saves (never in the select — Enter opens it); Escape
  // cancels. Both stay inside the row: nothing submits a form.
  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key === "Enter" && (event.target as HTMLElement).tagName === "INPUT") {
      event.preventDefault();
      save();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  };
  const showWhy = showSave && blocker !== null;
  return (
    <>
      <tr
        className="invoice-line-row pricing-row-editing"
        data-testid={rowTestId}
        data-row-key={rowKey}
        onKeyDown={onKeyDown}
      >
        <td className="invoice-line-row-service">
          {customLine ? (
            <input
              ref={descriptionRef}
              className="field-input pricing-row-input"
              type="text"
              value={draft.description}
              onChange={(event) => set("description", event.target.value)}
              placeholder={t("detail.pricing_form_description_placeholder")}
              aria-label={t("detail.pricing_form_description")}
              disabled={busy}
              data-testid={`pricing-row-description-${rowKey}`}
            />
          ) : (
            <div className="invoice-line-row-service-label">{label}</div>
          )}
          {note && (
            <div className="invoice-line-row-service-sub">
              <span className="muted small">{note}</span>
            </div>
          )}
        </td>
        <td className="invoice-line-row-source">{sourceTag}</td>
        <td className="invoice-line-row-num invoice-line-row-qty">
          <input
            className="field-input pricing-row-input pricing-row-num"
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            value={draft.quantity}
            onChange={(event) => set("quantity", event.target.value)}
            aria-label={t("detail.pricing_form_quantity")}
            disabled={busy}
            data-testid={`pricing-row-quantity-${rowKey}`}
          />
        </td>
        <td className="invoice-line-row-unit">
          <select
            className="field-select pricing-row-input"
            value={draft.unit_type}
            onChange={(event) => {
              const next = event.target.value as ExtraWorkUnitType;
              // A concrete unit has no unit word; the word survives
              // only behind "other" (RF-2, the backend's own rule).
              setDraft((current) => ({
                ...current,
                unit_type: next,
                custom_unit_label: next === "OTHER" ? current.custom_unit_label : "",
              }));
            }}
            aria-label={t("detail.pricing_form_unit")}
            disabled={busy}
            data-testid={`pricing-row-unit-${rowKey}`}
          >
            {PRICING_UNIT_OPTIONS.map((unit) => (
              <option key={unit} value={unit}>
                {t(PRICING_UNIT_LABEL_KEY[unit])}
              </option>
            ))}
          </select>
          {draft.unit_type === "OTHER" && (
            <input
              className="field-input pricing-row-input pricing-row-unit-name"
              type="text"
              maxLength={50}
              value={draft.custom_unit_label}
              onChange={(event) => set("custom_unit_label", event.target.value)}
              placeholder={t("detail.custom_unit_placeholder")}
              aria-label={t("pricing_row.unit_name")}
              disabled={busy}
              data-testid={`pricing-row-unit-name-${rowKey}`}
            />
          )}
        </td>
        <td className="invoice-line-row-num invoice-line-row-money">
          <input
            ref={priceRef}
            className="field-input pricing-row-input pricing-row-num"
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            value={draft.unit_price}
            onChange={(event) => set("unit_price", event.target.value)}
            aria-label={priceAria ?? t("detail.pricing_form_unit_price")}
            disabled={busy}
            data-testid={priceTestId ?? `pricing-row-price-${rowKey}`}
          />
        </td>
        <td className="invoice-line-row-num invoice-line-row-vat-pct">
          <input
            className="field-input pricing-row-input pricing-row-num"
            type="number"
            min="0"
            max="100"
            step="0.01"
            inputMode="decimal"
            value={draft.vat_pct}
            onChange={(event) => set("vat_pct", event.target.value)}
            aria-label={t("detail.pricing_form_vat")}
            disabled={busy}
            data-testid={`pricing-row-vat-${rowKey}`}
          />
        </td>
        {/* Live, display-only: the totals line updates on Save. */}
        <td className="invoice-line-row-num invoice-line-row-money pricing-row-money">
          {money ? formatMoney(money.subtotal) : "—"}
        </td>
        <td className="invoice-line-row-num invoice-line-row-money pricing-row-money">
          {money ? formatMoney(money.vat) : "—"}
        </td>
        <td
          className="invoice-line-row-num invoice-line-row-money invoice-line-row-total pricing-row-money"
          data-testid={`pricing-row-total-${rowKey}`}
        >
          {money ? formatMoney(money.total) : "—"}
        </td>
        <td className="invoice-line-row-actions">
          <div className="invoice-line-row-actions-cluster pricing-row-actions">
            {showSave && (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={!canSave}
                  aria-describedby={showWhy ? whyId : undefined}
                  onClick={save}
                  data-testid={`pricing-row-save-${rowKey}`}
                >
                  {t("common:save")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={cancel}
                  data-testid={`pricing-row-cancel-${rowKey}`}
                >
                  {t("common:cancel")}
                </button>
              </>
            )}
            {extraActions}
          </div>
        </td>
      </tr>
      {(showNotes || showWhy) && (
        <tr className="pricing-row-notes" data-testid={`pricing-row-notes-${rowKey}`}>
          <td colSpan={INVOICE_LINE_COLUMN_KEYS.length}>
            <div className="pricing-row-notes-body">
              {showNotes && (
                <label className="pricing-row-note">
                  <span className="field-label">{t("detail.pricing_customer_note_button")}</span>
                  <input
                    className="field-input pricing-row-input"
                    type="text"
                    value={draft.customer_explanation}
                    onChange={(event) => set("customer_explanation", event.target.value)}
                    placeholder={t("detail.pricing_form_customer_note_placeholder")}
                    disabled={busy}
                    data-testid={`pricing-row-customer-note-${rowKey}`}
                  />
                </label>
              )}
              {showNotes && showInternal && customLine && (
                <label className="pricing-row-note">
                  <span className="field-label">{t("detail.pricing_internal_note_button")}</span>
                  <input
                    className="field-input pricing-row-input"
                    type="text"
                    value={draft.internal_note}
                    onChange={(event) => set("internal_note", event.target.value)}
                    placeholder={t("detail.pricing_form_internal_note_placeholder")}
                    disabled={busy}
                    data-testid={`pricing-row-internal-note-${rowKey}`}
                  />
                </label>
              )}
              {showWhy && (
                /* Rule 14 — the reason Save is refused, beside it. */
                <p
                  id={whyId}
                  className="pricing-row-why"
                  role="status"
                  data-testid={`pricing-row-why-${rowKey}`}
                >
                  {t(PRICING_ROW_BLOCKER_KEY[blocker])}
                </p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
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
  /** W-FIX1 A3, P-9 C3 — the request's own lines. Every one the quote
   *  does not cover renders in the Pricing table as an unpriced row;
   *  the send / start / approve confirms say what the price covers. */
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
  /* P-9 C3/C4 — what the customer asked for against what the quote
     prices. The comparison is `lib/extraWorkCoverage`'s; the unpriced
     rows are the cart lines it finds uncovered, minus the ones the
     operator chose to leave out (local — nothing is sent). */
  const cartCoverageLines: CoverageLine[] = (requestLines ?? []).map((line) => ({
    id: line.id,
    service: line.service,
    label: line.label,
    quantity: line.quantity,
    unit: unitSuffix({ type: line.unit_type, label: "" }, t),
  }));
  const quoteCoverageLines: CoverageLine[] = proposal.lines.map((line) => ({
    id: line.id,
    service: line.service,
    label: (line.service_name || line.description || "").trim(),
    quantity: line.quantity,
  }));
  const coverage = requestLines
    ? compareCoverage(cartCoverageLines, quoteCoverageLines)
    : null;
  const [leftOut, setLeftOut] = useState<ReadonlySet<number>>(() => new Set());
  const [focusUnpriced, setFocusUnpriced] = useState<number | null>(null);
  const unpricedRows: RequestLineSeed[] = (coverage?.uncovered ?? [])
    .map((line) => (requestLines ?? []).find((r) => r.id === line.id))
    .filter((line): line is RequestLineSeed => line !== undefined)
    .filter((line) => !leftOut.has(line.id));
  const hasContractLine = proposal.lines.some(
    (line) => line.price_source === "CONTRACT",
  );
  // Provider override-decision modal (SENT proposal). A customer decides
  // without a reason; a PROVIDER driving the customer decision is an
  // override and the backend coerces is_override + REQUIRES a non-blank
  // override_reason (400 `override_reason_required`). null = closed.
  const [overridePrompt, setOverridePrompt] = useState<
    "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED" | null
  >(null);
  // Sprint 187 §2c / P-10 B4 — the row open for edit: a saved line's
  // id, "new" for the line being added at the foot of the table, or
  // null. One at a time: two open editors on the same table is two
  // sources of truth for a row.
  const [editingLineId, setEditingLineId] = useState<number | "new" | null>(null);
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
  // P-10 B4 — a new line is the row at the foot of the table; Save
  // creates it, and only Save.
  const addLine = (draft: PricingRowDraft) =>
    void run(async () => {
      await createProposalLine(
        ewId,
        proposal.id,
        pricingRowPayload(draft, { includeInternal: isProvider }),
      );
      setEditingLineId(null);
    });
  // P-9 C3 / P-10 B4 — pricing an unpriced row creates the quote line
  // from the request's own words, with the quantity and unit as the
  // operator left them, through the SAME call "Add line" makes — on
  // Save, never on a keystroke.
  const priceRequestLine = (line: RequestLineSeed, draft: PricingRowDraft) =>
    void run(async () => {
      await createProposalLine(
        ewId,
        proposal.id,
        pricingRowPayload(draft, { service: line.service, includeInternal: isProvider }),
      );
      setFocusUnpriced((current) => (current === line.id ? null : current));
    });
  const leaveOut = (lineId: number) =>
    setLeftOut((prev) => new Set([...prev, lineId]));
  // The coverage notice's door: close the confirm, put the row back if
  // it was left out, and land on its price box (the focus itself runs
  // in the row's effect — a focus in the handler that closes a
  // <dialog> does nothing).
  const addPriceFor = (line: CoverageLine) => {
    sendDialogRef.current?.close();
    setLeftOut((prev) => {
      if (!prev.has(line.id)) return prev;
      const next = new Set(prev);
      next.delete(line.id);
      return next;
    });
    setFocusUnpriced(line.id);
  };
  // Sprint 187 §2c — the PATCH that had no caller. Same `run()` helper
  // as every other mutation here, so it gets the same refetch and the
  // same live-preview refresh rather than a second refresh path.
  const saveLine = (line: ProposalLine, draft: PricingRowDraft) =>
    void run(async () => {
      await updateProposalLine(
        ewId,
        proposal.id,
        line.id,
        pricingRowPayload(draft, { includeInternal: isProvider }),
      );
      setEditingLineId(null);
    });
  // The Source cell of a row in edit mode — the same tag the read-only
  // row shows (InvoiceLineRow's rule, restated for the three cases a
  // row editor has: a saved line, a requested line, a new line).
  const sourceTag = (source: string, labelKey: string) => (
    <span
      className={`invoice-line-row-source-tag invoice-line-row-source-${source}`}
      data-testid="invoice-line-row-source-tag"
    >
      {t(labelKey)}
    </span>
  );
  const lineSourceTag = (line: ProposalLine) =>
    line.price_source === "CONTRACT"
      ? sourceTag("contract", "invoice_row.source.contract_price")
      : Number.parseFloat(line.unit_price) > 0
        ? sourceTag("custom", "invoice_row.source.own_price")
        : sourceTag("custom", "invoice_row.source.needs_proposal");
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
      // P-12 F2 (§D.24 rule 4) — the ceremony ANSWERS: what happened,
      // what did not, and the next step. Written to the request's
      // banner slot; when the send auto-starts and the page redirects
      // to the spawned ticket, the detail page relays it there.
      announceDone(
        safeSessionStorage(),
        `ew-${ewId}`,
        noCustomerApproval
          ? {
              title: t("extra_work:proposal.banner_started_title"),
              body: t("extra_work:proposal.banner_started_body"),
            }
          : {
              title: t("extra_work:proposal.banner_sent_title"),
              body: t("extra_work:proposal.banner_sent_body"),
              actionLabel: t("extra_work:proposal.banner_sent_action"),
              actionTo: "/extra-work/with-customer",
            },
      );
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
            the lines can still be edited. P-9 C7 -- and each sentence
            only while what it names is on the table: "contract prices
            are filled in" when a contract line is, "give the other
            lines a price" when an unpriced row is. */}
        {canEdit && (hasContractLine || unpricedRows.length > 0) && (
          <p
            className="muted small"
            style={{ marginTop: 0 }}
            data-testid="extra-work-proposal-helper"
          >
            {[
              hasContractLine ? t("detail.proposal_builder_helper_contract") : null,
              unpricedRows.length > 0
                ? t("detail.proposal_builder_helper_unpriced")
                : null,
            ]
              .filter(Boolean)
              .join(" ")}
          </p>
        )}
        {/* P-10 B4 — THE PRICING TABLE. Saved lines render read-only
            (InvoiceLineRow); Edit turns that row into inputs in place;
            every requested line the quote does not cover yet is such a
            row from the start, pre-filled with what the customer asked
            for (P-9 C3); a new line is a row at the foot. One row edits
            at a time. */}
        {proposal.lines.length === 0 &&
        unpricedRows.length === 0 &&
        editingLineId !== "new" ? (
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
                {proposal.lines.map((line) =>
                  canEdit && editingLineId === line.id ? (
                    <PricingRowEditor
                      key={line.id}
                      rowKey={String(line.id)}
                      initial={pricingRowFromLine(line)}
                      customLine={line.service === null}
                      label={(line.service_name || line.description || "").trim() || "—"}
                      sourceTag={lineSourceTag(line)}
                      showNotes
                      showInternal={isProvider}
                      busy={busy}
                      autoFocus="unit_price"
                      rowTestId="extra-work-proposal-line-editing"
                      onSave={(draft) => saveLine(line, draft)}
                      onCancel={() => setEditingLineId(null)}
                    />
                  ) : (
                    <InvoiceLineRow
                      key={line.id}
                      lineKind="proposal"
                      line={line}
                      editable={canEdit}
                      onRemove={canEdit ? () => removeLine(line.id) : undefined}
                      onEdit={canEdit ? () => setEditingLineId(line.id) : undefined}
                      editTestId={`pricing-row-edit-${line.id}`}
                      rowTestId="extra-work-proposal-line-row"
                      subLabel={renderNoteSub(line)}
                      audience={isProvider ? "provider" : "customer"}
                    />
                  ),
                )}
                {/* P-9 C3 — every requested line is on the table. */}
                {canEdit &&
                  unpricedRows.map((line) => (
                    <PricingRowEditor
                      key={`request-${line.id}`}
                      rowKey={`request-${line.id}`}
                      initial={pricingRowFromRequest(line)}
                      customLine={line.service === null}
                      label={line.label}
                      note={line.note}
                      sourceTag={sourceTag(
                        "needs_proposal",
                        "invoice_row.source.needs_proposal",
                      )}
                      showNotes={false}
                      showInternal={isProvider}
                      busy={busy}
                      saveWhenChangedOnly
                      focusPrice={focusUnpriced === line.id}
                      priceAria={t("detail.pricing_unpriced_price_aria", { line: line.label })}
                      priceTestId={`extra-work-proposal-unpriced-price-${line.id}`}
                      rowTestId="extra-work-proposal-unpriced-row"
                      onSave={(draft) => priceRequestLine(line, draft)}
                      onCancel={() => undefined}
                      extraActions={
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={busy}
                          onClick={() => leaveOut(line.id)}
                          data-testid={`extra-work-proposal-unpriced-leave-out-${line.id}`}
                        >
                          {t("detail.pricing_leave_out")}
                        </button>
                      }
                    />
                  ))}
                {canEdit && editingLineId === "new" && (
                  <PricingRowEditor
                    key="new"
                    rowKey="new"
                    initial={emptyPricingRow()}
                    customLine
                    label={null}
                    sourceTag={sourceTag("custom", "invoice_row.source.own_price")}
                    showNotes
                    showInternal={isProvider}
                    busy={busy}
                    autoFocus="description"
                    rowTestId="extra-work-proposal-new-row"
                    onSave={addLine}
                    onCancel={() => setEditingLineId(null)}
                  />
                )}
                <InvoiceLineTotalsRow
                  subtotal={proposal.subtotal_amount}
                  vatAmount={proposal.vat_amount}
                  total={proposal.total_amount}
                />
              </tbody>
            </table>
          </div>
        )}

        {/* P-10 B4 — a new line is a row at the foot of the table (the
            editor-below-the-table is gone); this button only opens it,
            and only while no other row is being edited. */}
        {canEdit && editingLineId === null && (
          <div className="ew-pricing-add-form">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 12 }}
              disabled={busy}
              onClick={() => setEditingLineId("new")}
              data-testid="proposal-add-line-toggle"
            >
              <Plus size={14} strokeWidth={2.2} />
              <span style={{ marginLeft: 6 }}>
                {t("detail.proposal_add_line")}
              </span>
            </button>
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
          confirmLabel={
            overridePrompt === "CUSTOMER_APPROVED"
              ? coverageConfirmLabel(
                  t,
                  coverage,
                  "approve",
                  t("detail.proposal_override_confirm"),
                )
              : t("detail.proposal_override_confirm")
          }
          cancelLabel={t("detail.note_modal_cancel")}
          onCancel={() => setOverridePrompt(null)}
          onConfirm={(reason) => submitOverride(reason)}
        >
          {/* P-9 C4 — the same coverage block on the approve-on-behalf
              ceremony; approving fewer lines than asked is said here. */}
          {overridePrompt === "CUSTOMER_APPROVED" && (
            <CoverageNotice coverage={coverage} />
          )}
        </RejectReasonDialog>
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
              <ul style={{ margin: "0 0 8px", paddingLeft: 18 }}>
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
              {/* P-9 C4 — does this price cover what was asked? Amber
                  when not; a missing line is a door onto its row. */}
              <CoverageNotice coverage={coverage} onAddPrice={addPriceFor} />
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
          confirmLabel={coverageConfirmLabel(
            t,
            coverage,
            noCustomerApproval ? "start" : "send",
            t(noCustomerApproval ? "detail.proposal_send_start" : "detail.coverage_send_exact"),
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
