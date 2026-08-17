import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getCustomer } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import { DashboardPage } from "../../DashboardPage";
import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 184 §3b — one customer's chargeable work, using THE ticket list.
 *
 * The fourth of the customer's work sub-pages, and the only one that did
 * not exist. Its three siblings were already built the right way —
 * Extra work mounts `ExtraWorkList`, Tickets mounts `DashboardPage`'s
 * `tickets-page` variant, Invoices mounts `FacturenPage` — so every fix
 * that landed on a main list this month reached them for free. This page
 * is the same arrangement with two pins instead of one.
 *
 * Two pins, both from the ROUTE, neither offered to the user:
 *
 *   customerId  narrows to this customer (`?customer=`, server-side).
 *   variant     `"chargeable-work"` narrows to tickets born from an
 *               extra work (`?is_extra_work=true`, server-side).
 *
 * Neither is removable, which is the point: a customer sub-page that can
 * be cleared back to every customer is a cross-tenant surprise, and the
 * ticket list renders no customer control at all when `customerId` is
 * set. The work-type strip is likewise not rendered on this variant —
 * the route IS the filter, so offering to turn it off would make the
 * page mean something other than its own name.
 *
 * `key={id}` for the reason CLAUDE.md gives and the reason this exact
 * bug shipped between Tickets and Chargeable work last week: two routes
 * rendering one component do NOT remount, so a `useState` initialiser
 * never re-runs and the previous page's filter leaks into the next
 * customer.
 */
export function CustomerChargeableWorkPage() {
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
    <div data-testid="customer-chargeable-work-page">
      <CustomerSubPageHeader customerName={customerName} isActive={isActive} />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <DashboardPage
        key={id}
        variant="chargeable-work"
        customerId={id}
        hideHeader
      />
    </div>
  );
}
