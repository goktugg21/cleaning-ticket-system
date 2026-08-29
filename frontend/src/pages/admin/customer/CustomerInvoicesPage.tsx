import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import type { CustomerAdmin } from "../../../api/types";
import { FacturenPage } from "../../FacturenPage";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Invoicing Phase 4b — the customer-detail Invoices tab. All rendering is
 * the shared `FacturenPage` with `customerId` + `embedded` (reuse, not a
 * copy).
 *
 * Sprint 186 §2 — it is now THE Facturen page with this customer pinned,
 * not a view-only slice of it. The due panel, the preview and Generate
 * were all suppressed here and replaced by a link back to the standalone
 * page; an operator who was already standing on the customer had to leave
 * and find them again in a provider-wide list to invoice them. The pin
 * itself is unchanged and still not removable: no customer picker, no
 * clear button, and the due panel narrows to this customer rather than
 * listing everyone else's on their page.
 */
export function CustomerInvoicesPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (numericId === null) return;
    let cancelled = false;
    getCustomer(numericId)
      .then((data) => {
        if (!cancelled) setCustomer(data);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [numericId]);

  if (numericId === null) {
    return (
      <div className="alert-error" role="alert">
        {/* Sprint 179B §5 — `admin.load_error` is in no bundle and this
            box rendered that string verbatim. The branch is not a load
            failure at all: it fires only when the `:id` in the URL is
            not a positive number, which is what the four sibling
            customer tabs already call `bm_customer_detail.invalid_id`. */}
        {t("bm_customer_detail.invalid_id")}
      </div>
    );
  }

  return (
    <div data-testid="customer-invoices-page">
      <CustomerSubPageHeader tab="invoices" subTab="invoices"
        customerName={customer?.name ?? ""}
        isActive={customer?.is_active ?? true}
      />
      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}
      {/* Sprint 184 §3b — keyed by customer id, like the three sibling
          sub-pages. Two routes rendering one component do not remount,
          so without this the previous customer's status filter and
          billing period survive into the next customer's invoices. */}
      <FacturenPage key={numericId} customerId={numericId} embedded />
    </div>
  );
}
