// Sprint 126 — customer-side Documents page. Same shared explorer as the
// provider sub-tab, in `customer` mode. Reached from the customer sidebar,
// gated on `customer.documents.manage`; the backend 404s a user without the
// key, so the explorer's own load-error state is the backstop if the nav is
// ever reached without it.
//
// Sprint 135 — a user belonging to more than one customer used to silently
// see only `customer_ids[0]`'s documents, with no way to reach the others.
// Now: exactly one customer -> unchanged, no picker. More than one -> a
// picker (names resolved via listAllCustomers, scoped server-side to the
// actor's own memberships) gates the explorer until one is chosen.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { listAllCustomers } from "../api/admin";
import type { CustomerAdmin } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DocumentsExplorer } from "../components/documents/DocumentsExplorer";

export function MyDocumentsPage() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const customerIds = me?.customer_ids ?? [];
  const showPicker = customerIds.length > 1;

  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(
    customerIds.length === 1 ? customerIds[0] : null,
  );

  useEffect(() => {
    if (!me || me.customer_ids.length <= 1) return;
    let cancelled = false;
    listAllCustomers().then((response) => {
      if (!cancelled) setCustomers(response);
    });
    return () => {
      cancelled = true;
    };
  }, [me]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("documents.my_eyebrow")}
          </div>
          <h2 className="page-title">{t("documents.my_title")}</h2>
        </div>
      </div>
      {customerIds.length === 0 ? (
        <p className="muted">{t("documents.no_customer")}</p>
      ) : (
        <>
          {showPicker && (
            <div className="field" style={{ maxWidth: 320, marginBottom: 16 }}>
              <label
                className="field-label"
                htmlFor="my-documents-customer-picker"
              >
                {t("documents.customer_picker_label")}
              </label>
              <select
                id="my-documents-customer-picker"
                className="field-select"
                data-testid="my-documents-customer-picker"
                value={selectedCustomerId ?? ""}
                onChange={(event) => {
                  const v = event.target.value;
                  setSelectedCustomerId(v === "" ? null : Number(v));
                }}
              >
                <option value="" disabled>
                  {t("documents.customer_picker_placeholder")}
                </option>
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>
                    {customer.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {selectedCustomerId !== null ? (
            <DocumentsExplorer customerId={selectedCustomerId} side="customer" />
          ) : (
            showPicker && (
              <p className="muted" data-testid="my-documents-picker-hint">
                {t("documents.customer_picker_hint")}
              </p>
            )
          )}
        </>
      )}
    </div>
  );
}
