// Sprint 126 — provider-side customer Documents sub-tab. SUPER_ADMIN /
// COMPANY_ADMIN only (the route sits behind AdminRoute and the backend 404s
// everyone else; the sidebar entry is hidden for BUILDING_MANAGER). Renders
// the shared explorer in provider mode.
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getCustomer } from "../../../api/admin";
import type { CustomerAdmin } from "../../../api/types";
import { DocumentsExplorer } from "../../../components/documents/DocumentsExplorer";
import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

export function CustomerDocumentsPage() {
  const { t } = useTranslation("common");
  const { id } = useParams();
  const numericId = Number(id);
  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCustomer(numericId)
      .then((data) => {
        if (!cancelled) setCustomer(data);
      })
      .catch(() => {
        // Header falls back to the empty name; the explorer surfaces its own
        // load error if the documents fetch fails.
      });
    return () => {
      cancelled = true;
    };
  }, [numericId]);

  return (
    <div className="page">
      <CustomerSubPageHeader
        customerName={customer?.name ?? ""}
        isActive={customer?.is_active ?? true}
        eyebrow={t("nav.customer_submenu.documents")}
      />
      <DocumentsExplorer customerId={numericId} side="provider" />
    </div>
  );
}
