/**
 * FE-2/FE-5 — the outcome sentence: the system STATES what happens
 * next, derived from the server's own preview of the cart (§D.5.2).
 * Green when everything has an agreed price and the work goes straight
 * to planning; amber when a price has to come first. The customer's
 * wording and the provider's wording differ by who does what, so the
 * audience picks the key; the colours are the same.
 */
import { useTranslation } from "react-i18next";

import { outcomeKey, type MeerwerkOutcomeKind } from "./cart";

export function MeerwerkOutcome({
  kind,
  audience,
  testId = "meerwerk-outcome",
}: {
  kind: MeerwerkOutcomeKind;
  audience: "customer" | "provider";
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <p
      className={`meerwerk-outcome meerwerk-outcome-${kind === "instant" ? "instant" : "quote"}`}
      data-testid={testId}
      data-kind={kind}
      role="status"
    >
      {t(outcomeKey(kind, audience))}
    </p>
  );
}
