import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import type { CustomerAdmin } from "../../../api/types";
import { InvoicesPage } from "../../InvoicesPage";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * #108 Part E — the customer-detail Invoices tab: the Facturen view
 * scoped to THIS customer (month picker, per-building breakdown,
 * totals via lib/billing, status filter), strictly VIEW-ONLY. The
 * mark/clear-invoiced endpoints act at company+month granularity —
 * running them from a customer page would mark other customers' work
 * too — so this tab renders a pointer link to the Facturen page
 * instead of the actions. All rendering is the shared InvoicesPage
 * with `customerId` + `embedded` (reuse, not a copy).
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
        {t("admin.load_error")}
      </div>
    );
  }

  return (
    <div data-testid="customer-invoices-page">
      <CustomerSubPageHeader
        customerName={customer?.name ?? ""}
        isActive={customer?.is_active ?? true}
        eyebrow={t("nav.customer_submenu.invoices")}
      />
      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}
      <InvoicesPage customerId={numericId} embedded />
    </div>
  );
}
