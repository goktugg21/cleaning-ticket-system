/**
 * P-13 H (§D.24 rule 8) — "How this page works": the capabilities
 * layer. A fold under the purpose line, 3–5 lines, one per
 * capability, verb first, in the order things happen, each naming
 * what it does and what it does NOT do.
 *
 * P-14 A3 — CLOSED by default, everywhere; a person who opens it is
 * remembered open (`howStore`, localStorage). The summary line IS
 * the "How this page works" link beside the title — collapsed, it
 * stays one click away. The lines come from the page's locale files,
 * both languages, in the Permissions voice.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { howOpen, rememberHow, safeLocalStorage } from "./howStore";

export function HowThisWorks({
  pageKey,
  lines,
  testId = "guide-how",
}: {
  /** Stable per-page key for the remembered-closed state. */
  pageKey: string;
  /** The 3–5 capability lines, already translated. */
  lines: string[];
  testId?: string;
}) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(
    () => howOpen(safeLocalStorage(), pageKey),
  );

  if (lines.length === 0) return null;

  return (
    <details
      className="guide-how"
      open={open}
      data-testid={testId}
      onToggle={(event) => {
        const next = (event.target as HTMLDetailsElement).open;
        setOpen(next);
        rememberHow(safeLocalStorage(), pageKey, next);
      }}
    >
      <summary className="guide-how-summary">
        {t("guide.how_this_works")}
      </summary>
      <ul className="guide-how-lines">
        {lines.map((line, index) => (
          <li key={index} className="guide-how-line">
            {line}
          </li>
        ))}
      </ul>
    </details>
  );
}
