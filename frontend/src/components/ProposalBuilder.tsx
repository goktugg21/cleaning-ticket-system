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
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Pencil, Plus, Trash2 } from "lucide-react";

import { getApiError } from "../api/client";
import {
  createProposalLine,
  deleteProposalLine,
  transitionProposal,
  updateProposalLine,
  type ProposalLineWritePayload,
} from "../api/extraWork";
import { useAuth } from "../auth/AuthContext";
import type { ExtraWorkUnitType, ProposalDetail, ProposalLine } from "../api/types";
import { formatMoney } from "../lib/intl";
import { InvoiceLineRow, InvoiceLineTotalsRow } from "./InvoiceLineRow";
import { INVOICE_LINE_COLUMN_KEYS } from "./invoiceLineColumns";
import { NoteEditorDialog } from "./NoteEditorDialog";

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

// A note trigger: a button styled as a field box. Shows a check + the
// note text when filled, a muted dash when empty. Clicking opens the
// shared NoteEditorDialog (caller wires onOpen).
function NoteBox({
  label,
  value,
  onOpen,
  disabled,
  testId,
}: {
  label: string;
  value: string;
  onOpen: () => void;
  disabled: boolean;
  testId: string;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const filled = value.trim() !== "";
  return (
    <div className="field ew-line-field-note">
      <span className="field-label">{label}</span>
      <button
        type="button"
        className="field-input ew-pricing-note-box"
        onClick={onOpen}
        disabled={disabled}
        data-testid={testId}
        data-filled={filled ? "true" : "false"}
      >
        {filled ? (
          <>
            <Check size={13} strokeWidth={2.4} />
            <span className="ew-pricing-note-box-text">{value}</span>
          </>
        ) : (
          <span className="muted">{t("detail.empty_dash")}</span>
        )}
      </button>
    </div>
  );
}

// Read-only note display for the saved-line card: same field-box look as
// NoteBox but non-interactive (no modal). Shows a check + text when filled,
// a muted dash when empty.
function ReadonlyNote({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation(["extra_work", "common"]);
  const filled = value.trim() !== "";
  return (
    <div className="field ew-line-field-note">
      <span className="field-label">{label}</span>
      <div
        className="field-input ew-pricing-note-box ew-line-readonly"
        data-filled={filled ? "true" : "false"}
      >
        {filled ? (
          <>
            <Check size={13} strokeWidth={2.4} />
            <span className="ew-pricing-note-box-text">{value}</span>
          </>
        ) : (
          <span className="muted">{t("detail.empty_dash")}</span>
        )}
      </div>
    </div>
  );
}

// Shared field cluster for both the edit and add forms.
function LineFields({
  form,
  setForm,
  disabled,
  showInternal,
}: {
  form: LineFormState;
  setForm: (next: LineFormState) => void;
  disabled: boolean;
  showInternal: boolean;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  // Which note modal (if any) is open for THIS line editor instance.
  const [noteModal, setNoteModal] = useState<"customer" | "internal" | null>(
    null,
  );
  const set = <K extends keyof LineFormState>(key: K, value: LineFormState[K]) =>
    setForm({ ...form, [key]: value });
  const money = liveLineMoney(form.quantity, form.unit_price, form.vat_pct);
  return (
    <>
      <div className="field ew-line-field-grow">
        <span className="field-label">{t("detail.pricing_form_description")}</span>
        <input
          className="field-input"
          type="text"
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          disabled={disabled}
        />
      </div>
      <div className="field ew-line-field-medium">
        <span className="field-label">{t("detail.pricing_form_unit")}</span>
        <select
          className="field-select"
          value={form.unit_type}
          onChange={(e) => set("unit_type", e.target.value as ExtraWorkUnitType)}
          disabled={disabled}
        >
          {UNIT_TYPE_VALUES.map((u) => (
            <option key={u} value={u}>
              {t(UNIT_TYPE_KEY[u])}
            </option>
          ))}
        </select>
      </div>
      <div className="field ew-line-field-compact">
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
      <div className="field ew-line-field-compact">
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
      <div className="field ew-line-field-compact">
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
      <NoteBox
        label={t("detail.pricing_customer_note_button")}
        value={form.customer_explanation}
        onOpen={() => setNoteModal("customer")}
        disabled={disabled}
        testId="proposal-line-customer-note-box"
      />
      {showInternal && (
        <NoteBox
          label={t("detail.pricing_internal_note_button")}
          value={form.internal_note}
          onOpen={() => setNoteModal("internal")}
          disabled={disabled}
          testId="proposal-line-internal-note-box"
        />
      )}
      {noteModal === "customer" && (
        <NoteEditorDialog
          title={t("detail.pricing_customer_note_modal_title")}
          initialValue={form.customer_explanation}
          placeholder={t("detail.pricing_form_customer_note_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            set("customer_explanation", value);
            setNoteModal(null);
          }}
          onCancel={() => setNoteModal(null)}
          testId="proposal-line-customer-note-dialog"
        />
      )}
      {showInternal && noteModal === "internal" && (
        <NoteEditorDialog
          title={t("detail.pricing_internal_note_modal_title")}
          initialValue={form.internal_note}
          placeholder={t("detail.pricing_form_internal_note_placeholder")}
          saveLabel={t("detail.note_modal_save")}
          cancelLabel={t("detail.note_modal_cancel")}
          onSave={(value) => {
            set("internal_note", value);
            setNoteModal(null);
          }}
          onCancel={() => setNoteModal(null)}
          testId="proposal-line-internal-note-dialog"
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
    quantity: form.quantity,
    unit_price: form.unit_price,
    vat_pct: form.vat_pct,
    customer_explanation: form.customer_explanation,
    ...(showInternal ? { internal_note: form.internal_note } : {}),
  };
}

// One editable existing line. Seeded from the line on mount; the parent
// keys it by `${id}:${updated_at}` so a Save (which bumps updated_at)
// remounts it with the persisted values.
function ProposalLineEditor({
  line,
  disabled,
  onSave,
  onCancel,
  onRemove,
}: {
  line: ProposalLine;
  disabled: boolean;
  onSave: (payload: ProposalLineWritePayload) => void;
  onCancel: () => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const showInternal = Object.prototype.hasOwnProperty.call(
    line,
    "internal_note",
  );
  const [form, setForm] = useState<LineFormState>({
    description: line.description,
    unit_type: line.unit_type,
    quantity: line.quantity,
    unit_price: line.unit_price,
    vat_pct: line.vat_pct,
    customer_explanation: line.customer_explanation,
    internal_note: line.internal_note ?? "",
  });
  return (
    <div
      className="ew-line-row ew-line-row-card"
      data-testid="proposal-line-editor"
      data-line-id={line.id}
    >
      <LineFields
        form={form}
        setForm={setForm}
        disabled={disabled}
        showInternal={showInternal}
      />
      <div className="ew-line-row-actions" style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={disabled || !form.description.trim()}
          onClick={() => onSave(payloadFromForm(form, showInternal))}
          data-testid="proposal-line-save"
        >
          {t("common:save")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={disabled}
          onClick={onCancel}
          data-testid="proposal-line-cancel"
        >
          {t("common:cancel")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={disabled}
          onClick={onRemove}
          data-testid="proposal-line-remove"
        >
          <Trash2 size={13} strokeWidth={2} />
          {t("detail.pricing_remove_button")}
        </button>
      </div>
    </div>
  );
}

// A SAVED line, collapsed to a non-editable card (mirrors the editor's
// column layout but read-only). The persisted backend totals are shown
// verbatim. "Edit" reopens the line in ProposalLineEditor; "Remove"
// deletes it.
function ProposalLineCard({
  line,
  disabled,
  onEdit,
  onRemove,
}: {
  line: ProposalLine;
  disabled: boolean;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const showInternal = Object.prototype.hasOwnProperty.call(
    line,
    "internal_note",
  );
  return (
    <div
      className="ew-line-row ew-line-row-card"
      data-testid="proposal-line-card"
      data-line-id={line.id}
    >
      <div className="field ew-line-field-grow">
        <span className="field-label">{t("detail.pricing_form_description")}</span>
        <div className="field-input ew-line-readonly">
          {line.description || line.service_name || t("detail.empty_dash")}
        </div>
      </div>
      <div className="field ew-line-field-medium">
        <span className="field-label">{t("detail.pricing_form_unit")}</span>
        <div className="field-input ew-line-readonly">
          {t(UNIT_TYPE_KEY[line.unit_type])}
        </div>
      </div>
      <div className="field ew-line-field-compact">
        <span className="field-label">{t("detail.pricing_form_quantity")}</span>
        <div className="field-input ew-line-readonly">{line.quantity}</div>
      </div>
      <div className="field ew-line-field-compact">
        <span className="field-label">{t("detail.pricing_form_unit_price")}</span>
        <div className="field-input ew-line-readonly">
          {formatMoney(Number(line.unit_price))}
        </div>
      </div>
      <div className="field ew-line-field-compact">
        <span className="field-label">{t("detail.pricing_form_vat")}</span>
        <div className="field-input ew-line-readonly">{line.vat_pct}</div>
      </div>
      <MoneyBox
        label={t("detail.pricing_column_subtotal")}
        value={Number(line.line_subtotal)}
      />
      <MoneyBox
        label={t("detail.pricing_column_vat")}
        value={Number(line.line_vat)}
      />
      <MoneyBox
        label={t("detail.pricing_column_total")}
        value={Number(line.line_total)}
      />
      <ReadonlyNote
        label={t("detail.pricing_customer_note_button")}
        value={line.customer_explanation}
      />
      {showInternal && (
        <ReadonlyNote
          label={t("detail.pricing_internal_note_button")}
          value={line.internal_note ?? ""}
        />
      )}
      <div className="ew-line-row-actions" style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={disabled}
          onClick={onEdit}
          data-testid="proposal-line-edit"
        >
          <Pencil size={13} strokeWidth={2} />
          {t("common:edit")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={disabled}
          onClick={onRemove}
          data-testid="proposal-line-card-remove"
        >
          <Trash2 size={13} strokeWidth={2} />
          {t("detail.pricing_remove_button")}
        </button>
      </div>
    </div>
  );
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
    quantity: "1.00",
    unit_price: "0.00",
    vat_pct: "21.00",
    customer_explanation: "",
    internal_note: "",
  });
  return (
    <div
      className="ew-line-row ew-line-row-card"
      data-testid="proposal-add-line-form"
      style={{ marginTop: 12 }}
    >
      <LineFields
        form={form}
        setForm={setForm}
        disabled={disabled}
        showInternal
      />
      <div className="ew-line-row-actions" style={{ display: "flex", gap: 8 }}>
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
  // Which saved line is currently open in the editor. null = every line
  // shows as a read-only card; clicking a card's "Edit" opens it here, and
  // a successful Save (or Cancel) collapses it back to the card.
  const [editingId, setEditingId] = useState<number | null>(null);
  // Provider override-decision modal (SENT proposal). A customer decides
  // without a reason; a PROVIDER driving the customer decision is an
  // override and the backend coerces is_override + REQUIRES a non-blank
  // override_reason (400 `override_reason_required`). null = closed.
  const [overridePrompt, setOverridePrompt] = useState<
    "CUSTOMER_APPROVED" | "CUSTOMER_REJECTED" | null
  >(null);
  const [overrideReason, setOverrideReason] = useState("");

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

  // Returns true on success so callers (e.g. the line editor) can collapse
  // back to the read-only card only when the save actually landed.
  async function run(fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setError("");
    try {
      await fn();
      await onChanged();
      return true;
    } catch (err) {
      setError(getApiError(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const saveLine = (lineId: number, payload: ProposalLineWritePayload) =>
    run(() => updateProposalLine(ewId, proposal.id, lineId, payload));
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

  return (
    <div
      className="card"
      style={{ marginBottom: 16 }}
      data-testid="extra-work-proposal-builder"
    >
      <div className="form-section">
        <div className="form-section-title">
          {t("detail.proposal_builder_title")}
        </div>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("detail.proposal_builder_helper")}
        </p>
        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        {canEdit ? (
          <div className="ew-pricing-add-form">
            {proposal.lines.length === 0 && (
              <p className="muted small">{t("detail.proposal_builder_empty")}</p>
            )}
            {proposal.lines.map((line) =>
              editingId === line.id ? (
                <ProposalLineEditor
                  key={`${line.id}:${line.updated_at}`}
                  line={line}
                  disabled={busy}
                  onSave={(payload) => {
                    void saveLine(line.id, payload).then((ok) => {
                      if (ok) setEditingId(null);
                    });
                  }}
                  onCancel={() => setEditingId(null)}
                  onRemove={() => removeLine(line.id)}
                />
              ) : (
                <ProposalLineCard
                  key={line.id}
                  line={line}
                  disabled={busy}
                  onEdit={() => setEditingId(line.id)}
                  onRemove={() => removeLine(line.id)}
                />
              ),
            )}
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
                <span style={{ marginLeft: 6 }}>{t("detail.proposal_add_line")}</span>
              </button>
            )}
          </div>
        ) : (
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
                  editable={false}
                  rowTestId="extra-work-proposal-line-row"
                />
              ))}
              <InvoiceLineTotalsRow
                subtotal={proposal.subtotal_amount}
                vatAmount={proposal.vat_amount}
                total={proposal.total_amount}
              />
            </tbody>
          </table>
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
    </div>
  );
}
