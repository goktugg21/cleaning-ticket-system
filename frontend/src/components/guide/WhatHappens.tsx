/**
 * P-13 H (§D.24 rule 8) — the one visible line under a primary button
 * or destructive control, in the Permissions voice: "Freezes the
 * lines; the number comes at Send." Never hover-only. A control
 * already covered by a confirm keeps the confirm; this is the
 * pre-read.
 */
import type { ReactNode } from "react";

export function WhatHappens({
  children,
  testId = "guide-what",
}: {
  children: ReactNode;
  testId?: string;
}) {
  return (
    <p className="guide-what muted small" data-testid={testId}>
      {children}
    </p>
  );
}
