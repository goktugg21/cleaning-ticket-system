/**
 * W-H §1 — the archive modal. Rule 3: a transition asks for what it
 * needs, before it happens, and the server enforces the same thing.
 *
 * ONE component for both directions because they are one decision seen
 * from two sides, and the asymmetry is the whole design:
 *
 *   archiving   - a note, OPTIONAL. The work is finished; the status
 *                 already says why.
 *   unarchiving - a reason, REQUIRED. Pulling something back out of the
 *                 archive is a decision somebody has to answer for, and
 *                 the reason lands on the AuditLog.
 *
 * The confirm button is disabled until the required field is filled, so
 * the requirement is visible in the control rather than explained in a
 * sentence above it. The system we are closing the gap against puts
 * both of these in the browser only; ours re-checks in
 * `TicketViewSet.archive` / `.unarchive`, so a hand-made request is
 * refused the same way.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import { archiveTicket, unarchiveTicket } from "../api/tickets";
import type { TicketDetail } from "../api/types";

export function TicketArchiveDialog({
  ticketId,
  mode,
  onCancel,
  onDone,
  moneyNotice,
}: {
  ticketId: number | string;
  mode: "archive" | "unarchive";
  onCancel: () => void;
  onDone: (ticket: TicketDetail, mode: "archive" | "unarchive") => void;
  /** P-13 C2 — the money fact on an unbilled job's archive confirm:
   *  archiving hides the ticket, never the money. Composed by the
   *  page from `ticket.extra_work_billing`; absent when nothing
   *  waits. */
  moneyNotice?: string;
}) {
  const { t } = useTranslation("common");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const needsText = mode === "unarchive";
  const ready = !needsText || text.trim().length > 0;

  async function submit() {
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      const updated =
        mode === "archive"
          ? await archiveTicket(ticketId, text.trim())
          : await unarchiveTicket(ticketId, text.trim());
      onDone(updated, mode);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="reject-modal-backdrop"
      role="dialog"
      aria-modal="true"
      data-testid="ticket-archive-dialog"
    >
      <div className="reject-modal" style={{ maxWidth: 460 }}>
        <h3 className="reject-modal-title">
          {t(mode === "archive" ? "archive.dialog_title" : "archive.unarchive_title")}
        </h3>

        {error && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        {mode === "archive" && moneyNotice && (
          <div
            className="alert-warning"
            style={{ marginBottom: 12 }}
            data-testid="ticket-archive-money-notice"
          >
            {moneyNotice}
          </div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="ticket-archive-text">
            {t(
              mode === "archive"
                ? "archive.note_label"
                : "archive.unarchive_reason_label",
            )}
          </label>
          <textarea
            id="ticket-archive-text"
            className="field-textarea"
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
            data-testid="ticket-archive-text"
          />
        </div>

        <div className="reject-modal-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={submit}
            disabled={busy || !ready}
            data-testid="ticket-archive-confirm"
          >
            {t(
              mode === "archive" ? "archive.confirm" : "archive.unarchive_confirm",
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
