import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getCustomer } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import { DashboardPage } from "../../DashboardPage";
import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 169 §8 — one customer's tickets, using THE ticket list.
 *
 * This file used to be a 295-line read-only re-implementation of the
 * Tickets page: no checkbox column, no `MultiSelectToolbar`, no
 * `useEditMode`, no bulk assignment, no bulk status action. Everything
 * Sprints 158-164 built on the standalone list was missing here.
 *
 * Copying the features across would have produced two copies that drift
 * again, which is exactly how this pair got here. The Tickets list is
 * `DashboardPage`'s `tickets-page` variant, so the page now mounts that
 * with the customer fixed.
 *
 * Tickets are deliberately NOT one of the pages that redirects to the
 * main list with a filter applied — that option is on the table for
 * Buildings and Users, where the customer-scoped view really is just a
 * filtered look. Tickets are where the daily work happens and must
 * carry their full function in place, inside the customer.
 */
export function CustomerTicketsPage() {
  const { id: customerId } = useParams<{ id: string }>();
  const id = Number(customerId);

  const [customerName, setCustomerName] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!Number.isFinite(id)) return;
    let cancelled = false;
    getCustomer(id)
      .then((customer) => {
        if (cancelled) return;
        setCustomerName(customer.name);
        setIsActive(customer.is_active);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (!Number.isFinite(id)) return null;

  return (
    <div data-testid="customer-tickets-page">
      <CustomerSubPageHeader customerName={customerName} isActive={isActive} />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {/* Keyed by customer id: navigating between two customers remounts
          the list rather than syncing a changed prop into its state
          through an effect. */}
      <DashboardPage
        key={id}
        variant="tickets-page"
        customerId={id}
        hideHeader
      />
    </div>
  );
}
