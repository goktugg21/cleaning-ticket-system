import type { ReactNode } from "react";

/**
 * Sprint 28 Batch 15.2 — small caption above each zone of the
 * Permissions page. Title + optional one-paragraph helper so the
 * operator can scan the page top-to-bottom and know what each
 * section controls before they touch a control.
 */
export function ZoneHeader({
  title,
  helper,
}: {
  title: ReactNode;
  helper?: ReactNode;
}) {
  return (
    <header className="permissions-zone-header">
      <h3 className="permissions-zone-title">{title}</h3>
      {helper && <p className="permissions-zone-helper">{helper}</p>}
    </header>
  );
}

