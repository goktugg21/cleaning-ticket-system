/**
 * Sprint 28 Batch 15.4 — routing-decision pill.
 *
 * Surfaces the Extra Work request's `routing_decision` value as a
 * coloured badge. Two values: "INSTANT" (every cart line resolved to
 * an active contract price — operational tickets were spawned
 * immediately) and "PROPOSAL" (at least one line had no agreed price
 * so a provider proposal is required before any work begins).
 *
 * Used on:
 *   - the EW list (one per row, between Status and Category)
 *   - the EW detail page header
 *   - the Ticket detail "Spawned from" block (Sprint 28 Batch 15.4 M3)
 *
 * Duplicate `data-testid="extra-work-list-route-badge"` instances in
 * different page contexts are acceptable — the list spec counts them
 * per row to assert one badge per row.
 */
import { useTranslation } from "react-i18next";
import type { RoutingDecision } from "../api/types";

export interface RouteBadgeProps {
  value: RoutingDecision;
}

export function RouteBadge({ value }: RouteBadgeProps) {
  const { t } = useTranslation("common");
  // Sprint 28 Batch 15.5 — colour fix.
  //   The original mapping reused `badge-approved` (green) for INSTANT
  //   and `badge-waiting_customer_approval` (teal) for PROPOSAL. Both
  //   tones overlapped with the status badge palette, which made the
  //   EW list visually ambiguous — the PROPOSAL route badge sat next
  //   to a teal CUSTOMER-APPROVED status badge and an operator could
  //   not tell them apart at a glance. The route modifier classes
  //   `route-badge-proposal` / `route-badge-instant` now carry their
  //   own amber / green overrides defined in index.css (search
  //   "Sprint 28 Batch 15.5 — RouteBadge colour overrides"). We drop
  //   the status-badge tone classes so the override is the only
  //   colour source.
  const labelKey =
    value === "INSTANT" ? "route_badge.instant" : "route_badge.proposal";
  const helperKey =
    value === "INSTANT"
      ? "route_badge.instant_helper"
      : "route_badge.proposal_helper";
  return (
    <span
      className={`badge route-badge route-badge-${value.toLowerCase()}`}
      title={t(helperKey)}
      data-testid="extra-work-list-route-badge"
      data-route={value}
    >
      {t(labelKey)}
    </span>
  );
}


