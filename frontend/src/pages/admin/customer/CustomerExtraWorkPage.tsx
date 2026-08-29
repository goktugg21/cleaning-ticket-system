import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getCustomer } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import { ExtraWorkList } from "../../ExtraWorkListPage";
import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 169 §8 — one customer's Extra Work, using THE extra-work list.
 *
 * This file used to be a 296-line re-implementation of a 1202-line
 * page: a read-only table with no checkbox column, no
 * `MultiSelectToolbar`, no `useEditMode`, no bulk assignment and no
 * bulk status action. Everything Sprints 158-164 built on the
 * standalone list was missing here, because the two were independently
 * maintained copies of the same list.
 *
 * The owner's rule, and it is a good one: a list must behave the same
 * whether you reach it from the sidebar or from inside a customer. So
 * this page is now a header plus the real list with its customer fixed
 * — not a copy of the features, which would drift again.
 *
 * Extra Work is deliberately NOT one of the pages that redirects to the
 * main list with a filter applied. That option is on the table for
 * Buildings and Users, where the customer-scoped view really is just a
 * filtered look. Extra Work is where the daily work happens and has to
 * carry its full function in place, inside the customer.
 */
export function CustomerExtraWorkPage() {
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
    <div data-testid="customer-extra-work-page">
      <CustomerSubPageHeader tab="work" subTab="extra_work" customerName={customerName} isActive={isActive} />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {/* Keyed by customer id: navigating between two customers remounts
          the list rather than syncing a changed prop into its state
          through an effect, which is the pattern CLAUDE.md bans. */}
      <ExtraWorkList key={id} customerId={id} hideHeader />
    </div>
  );
}
