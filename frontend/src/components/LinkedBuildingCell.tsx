/**
 * Sprint 156 §3 — ONE definition of how a customer's linked building is
 * rendered.
 *
 * Sprint 155 §2 enriched this row on the customer OVERVIEW card and left
 * the customer's Buildings sub-page showing a bare name and city, so the
 * owner saw the same list looking half-empty in one place and full in
 * another. The fix is not to copy the markup across — a second
 * independently maintained copy of a rendering rule is exactly what
 * drifts (CLAUDE.md's frontend rule; Sprint 126's headerless permission
 * column went unnoticed for three sprints because of it).
 *
 * The two consumers have genuinely different SHAPES — the overview is a
 * flex link row, the sub-page is a `<table>` with an edit-mode checkbox
 * column — so what is shared here is the CONTENT of the cells, not the
 * row element. That keeps the rule in one place (which fields, in what
 * order, with what fallbacks) while letting each page lay it out the way
 * its surroundings demand.
 */
import { useTranslation } from "react-i18next";

import type { CustomerBuildingMembership } from "../api/types";

/** Name, an inactive marker, and the full address line. */
export function LinkedBuildingIdentity({
  link,
  testId,
}: {
  link: CustomerBuildingMembership;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  // City AND postal code on one line — a Dutch city alone does not
  // locate a building, "Amsterdam · 1012 AB" does. Falls back to the
  // street address, then an em dash: a blank cell reads as a rendering
  // bug, an em dash reads as "nothing on file".
  const address =
    [link.building_city, link.building_postal_code].filter(Boolean).join(" · ") ||
    link.building_address ||
    "—";

  return (
    <span
      style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}
      data-testid={testId}
    >
      <span className="bld-row-name">
        {link.building_name}
        {!link.building_is_active && (
          <span
            className="badge badge-normal"
            style={{ marginLeft: 8 }}
            data-testid="linked-building-inactive"
          >
            {t("admin.status_inactive")}
          </span>
        )}
      </span>
      <span className="muted small">{address}</span>
    </span>
  );
}

/** How many customers and managers are at that building. */
export function LinkedBuildingCounts({
  link,
  align = "end",
}: {
  link: CustomerBuildingMembership;
  align?: "start" | "end";
}) {
  const { t } = useTranslation("common");
  return (
    <span
      className="linked-building-counts"
      style={align === "start" ? { alignItems: "flex-start", textAlign: "left" } : undefined}
    >
      <span>
        {t("customer_view.overview.building_customer_count", {
          count: link.building_customer_count,
        })}
      </span>
      <span>
        {t("customer_view.overview.building_manager_count", {
          count: link.building_manager_count,
        })}
      </span>
    </span>
  );
}
