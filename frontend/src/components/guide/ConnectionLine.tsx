/**
 * P-12 §D.24 rule 6 — connections in words, on the object, with one
 * link to the other end: "From contract CNT-2026-0002 · line 'Weekly
 * office clean' · invoiced with the contract, monthly". The sentence
 * is the page's (through t()); this piece only gives it the one shape
 * so every connection reads the same.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import "./guide.css";

export function ConnectionLine({
  children,
  to,
  linkLabel,
  testId = "guide-connection",
}: {
  /** The sentence, minus the link. */
  children: ReactNode;
  to?: string;
  linkLabel?: string;
  testId?: string;
}) {
  return (
    <p className="guide-connection" data-testid={testId}>
      {children}
      {to && linkLabel && (
        <>
          {" "}
          <Link to={to} data-testid={`${testId}-link`}>
            {linkLabel}
          </Link>
        </>
      )}
    </p>
  );
}
