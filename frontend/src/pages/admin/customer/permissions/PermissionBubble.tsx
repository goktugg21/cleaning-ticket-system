import type { ReactNode } from "react";
import { Check, Lock, X as XIcon } from "lucide-react";

import type { PanelResolution } from "./effectiveResolver";

/**
 * Sprint 31 Phase 6 — glyph bubble for the matrix.
 *
 * Pure presentation. Reads a `PanelResolution` produced by
 * `resolvePanelValue` (in `effectiveResolver.ts`) — never decides
 * grant / deny / policy itself.
 *
 * Three visual states, each carrying its own glyph inside the circle
 * so the answer is the GLYPH, not "filled vs empty":
 *
 *   granted === true
 *     -> circle with a CHECK inside    (.permission-bubble-granted)
 *
 *   granted === false  &&  reason !== "policy_denied"
 *     -> circle with a CROSS inside    (.permission-bubble-denied)
 *
 *   granted === false  &&  reason === "policy_denied"
 *     -> circle with a LOCK inside     (.permission-bubble-policy-blocked)
 *        + tooltip text. The lock keeps "blocked by company policy"
 *        visually distinct from a plain denied cross so the operator
 *        never confuses them.
 *
 * `data-effective` + `data-policy-blocked` data attributes are
 * preserved verbatim — e2e specs assert state via these attributes,
 * never the glyph.
 *
 * This component is consumed by `PermissionsMatrix` only. The modal's
 * tri-state Inherit/Allow/Deny control (`TriStateBubbleRadio`) does
 * NOT render through `PermissionBubble` — it draws its own plain
 * `<span className="permission-bubble tri-state-bubble…">` with no
 * glyph child — so adding glyphs here does not change the modal.
 */
export interface PermissionBubbleProps {
  resolution: PanelResolution;
  /** Tooltip text shown on the policy-blocked variant. */
  policyBlockedLabel: string;
  /** Accessible label (sr-only) describing the cell's effective state. */
  ariaLabel: string;
}

export function PermissionBubble({
  resolution,
  policyBlockedLabel,
  ariaLabel,
}: PermissionBubbleProps) {
  const isPolicyBlocked =
    !resolution.granted && resolution.reason === "policy_denied";
  let className: string;
  let glyph: ReactNode;
  if (resolution.granted) {
    className = "permission-bubble permission-bubble-granted";
    glyph = <Check size={12} strokeWidth={3} aria-hidden="true" />;
  } else if (isPolicyBlocked) {
    className = "permission-bubble permission-bubble-policy-blocked";
    glyph = <Lock size={11} strokeWidth={2.4} aria-hidden="true" />;
  } else {
    className = "permission-bubble permission-bubble-denied";
    glyph = <XIcon size={12} strokeWidth={3} aria-hidden="true" />;
  }
  return (
    <span
      className={className}
      role="img"
      aria-label={ariaLabel}
      title={isPolicyBlocked ? policyBlockedLabel : undefined}
      data-testid="permission-bubble"
      data-effective={resolution.granted ? "granted" : "denied"}
      data-policy-blocked={isPolicyBlocked ? "true" : "false"}
    >
      {glyph}
    </span>
  );
}
