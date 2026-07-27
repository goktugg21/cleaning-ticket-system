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
// download URL and keeps the original test ids. Behaviour is unchanged.
import type { ReactNode } from "react";

import type { TicketAttachment } from "../api/types";
import { DocumentThumb } from "./DocumentThumb";

export function AttachmentThumb({
  ticketId,
  attachment,
  fallback,
}: {
  ticketId: number | string;
  attachment: TicketAttachment;
  fallback: ReactNode;
}) {
  return (
    <DocumentThumb
      url={`/tickets/${ticketId}/attachments/${attachment.id}/download/`}
      mimeType={attachment.mime_type}
      fallback={fallback}
      imgTestId="attachment-thumb-image"
      pdfTestId="attachment-thumb-pdf"
    />
  );
}
