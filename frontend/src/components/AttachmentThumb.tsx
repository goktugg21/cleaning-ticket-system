// RF-12 (Göktuğ 2026-06-24) — attachment card thumbnail with no click.
//
// Renders a real preview inside the attachment tile: images show the actual
// image; PDFs show a first-page thumbnail rendered client-side via pdfjs-dist.
// Any failure or unsupported type falls back to `fallback` (the extension-
// badge card) — never a broken card. The tile's click-to-view + the Download
// action are unchanged (this only replaces the badge glyph with a preview).
//
// Sprint 121 — the fetch/render/fallback machinery moved to the shared
// <DocumentThumb> (also used by the staff-credential row thumbnail); this is
// now a thin ticket-attachment adapter that supplies the authenticated
// download URL and keeps the original test ids.
//
// Sprint 191 §2.5 — the tile also carries the CUSTOMER WALL: which side of it
// this file is on, and (for a provider manager) the one action that moves it.
// A staff upload lands INTERNAL, so without a visible state here a worker
// cannot tell whether the customer is seeing their photo and a manager has
// nothing to click.
//
// W4-P — and WHY it is on that side. With standing and per-ticket permissions
// in play, "internal" is no longer one rule with one cause: it can be the
// default, a per-job setting, a standing permission or a per-ticket refusal.
// A manager who cannot tell those apart promotes photo by photo against a rule
// that already decided, or worse, assumes a rule where there is none. The
// server records the deciding rung at upload (`visibility_source`) and the
// pill's tooltip reads it back in words. It is a tooltip and not a second pill
// because it explains a state the pill already names — two pills per tile would
// be shouting.
import { useState } from "react";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type {
  AttachmentVisibility,
  TicketAttachment,
  UploadVisibilitySource,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { isProviderManagementRole, isStaffRole } from "../auth/permissions";
import { DocumentThumb } from "./DocumentThumb";

// One record keyed by the full union, so adding a source to
// `UPLOAD_VISIBILITY_SOURCES` fails the typecheck here instead of rendering a
// raw enum value at a manager (the Sprint 130 lesson, applied to a map rather
// than an array).
const SOURCE_LABEL_KEYS: Record<UploadVisibilitySource, string> = {
  "": "attachment_visibility.source_unrecorded",
  UPLOADER_CHOICE: "attachment_visibility.source_uploader_choice",
  CUSTOMER_UPLOAD: "attachment_visibility.source_customer_upload",
  TICKET_GRANT: "attachment_visibility.source_ticket_grant",
  STANDING_GRANT: "attachment_visibility.source_standing_grant",
  WORK_SETTING: "attachment_visibility.source_work_setting",
  DEFAULT_INTERNAL: "attachment_visibility.source_default_internal",
  MANUAL: "attachment_visibility.source_manual",
};

export function AttachmentThumb({
  ticketId,
  attachment,
  fallback,
}: {
  ticketId: number | string;
  attachment: TicketAttachment;
  fallback: ReactNode;
}) {
  // The inner component holds the visibility the user is currently looking
  // at, which the promote action changes without the page refetching. Keying
  // by id AND by the server's values means a later refetch always wins: a
  // changed prop remounts the inner component instead of being shadowed by
  // stale local state (the prop-derived-state rule in CLAUDE.md). W4-P adds
  // `visibility_source` to the key for the same reason it added the state:
  // the pair moves together and a refetch must be able to correct both.
  return (
    <AttachmentThumbInner
      key={`${attachment.id}:${attachment.visibility}:${attachment.visibility_source}`}
      ticketId={ticketId}
      attachment={attachment}
      fallback={fallback}
    />
  );
}

function AttachmentThumbInner({
  ticketId,
  attachment,
  fallback,
}: {
  ticketId: number | string;
  attachment: TicketAttachment;
  fallback: ReactNode;
}) {
  const { t } = useTranslation();
  const { me } = useAuth();
  const [visibility, setVisibility] = useState<AttachmentVisibility>(
    attachment.visibility,
  );
  // W4-P — the rung that decided, kept beside the value it decided. The
  // promote endpoint answers with the row it wrote (source MANUAL), so the
  // tooltip stops claiming a rule the moment a human overrode it.
  const [source, setSource] = useState<UploadVisibilitySource>(
    attachment.visibility_source,
  );
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const isInternal = visibility === "INTERNAL";
  // The wall only means something to the provider side. A customer sees
  // exclusively customer-visible files (the server does not serve them any
  // other kind), so a pill saying so on every tile would be pure noise.
  const showState = isStaffRole(me?.role);
  const canPromote = isProviderManagementRole(me?.role);
  const nextVisibility: AttachmentVisibility = isInternal
    ? "CUSTOMER"
    : "INTERNAL";

  async function toggleVisibility(
    event: MouseEvent<HTMLSpanElement> | KeyboardEvent<HTMLSpanElement>,
  ) {
    // The tile itself is a <button> that opens the preview, so this control
    // must not let its click reach it. It is a role="button" span rather than
    // a real <button> for the same reason: a <button> inside a <button> is
    // invalid HTML, and the tile element belongs to TicketDetailPage.
    event.preventDefault();
    event.stopPropagation();
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const { data } = await api.patch<TicketAttachment>(
        `/tickets/${ticketId}/attachments/${attachment.id}/visibility/`,
        { visibility: nextVisibility },
      );
      setVisibility(data.visibility);
      setSource(data.visibility_source);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLSpanElement>) {
    if (event.key === "Enter" || event.key === " ") {
      void toggleVisibility(event);
    }
  }

  return (
    <>
      <DocumentThumb
        url={`/tickets/${ticketId}/attachments/${attachment.id}/download/`}
        mimeType={attachment.mime_type}
        fallback={fallback}
        imgTestId="attachment-thumb-image"
        pdfTestId="attachment-thumb-pdf"
      />
      {showState && (
        <span
          className={`att-vis-pill ${isInternal ? "is-internal" : "is-customer"}`}
          data-testid="attachment-visibility-pill"
          data-visibility={visibility}
          data-visibility-source={source}
          title={t(SOURCE_LABEL_KEYS[source])}
        >
          {t(
            isInternal
              ? "attachment_visibility.internal"
              : "attachment_visibility.customer",
          )}
        </span>
      )}
      {attachment.phase !== "UNSPECIFIED" && (
        <span className="att-phase-pill" data-testid="attachment-phase-pill">
          {t(
            attachment.phase === "BEFORE"
              ? "attachment_visibility.phase_before"
              : "attachment_visibility.phase_after",
          )}
        </span>
      )}
      {canPromote && (
        <span
          role="button"
          tabIndex={0}
          className="att-vis-action"
          data-testid="attachment-visibility-toggle"
          aria-label={t(
            isInternal
              ? "attachment_visibility.promote_aria"
              : "attachment_visibility.demote_aria",
            { name: attachment.original_filename },
          )}
          aria-busy={busy}
          onClick={toggleVisibility}
          onKeyDown={onKeyDown}
        >
          {busy
            ? t("attachment_visibility.busy")
            : failed
              ? t("attachment_visibility.failed")
              : t(
                  isInternal
                    ? "attachment_visibility.promote"
                    : "attachment_visibility.demote",
                )}
        </span>
      )}
    </>
  );
}
