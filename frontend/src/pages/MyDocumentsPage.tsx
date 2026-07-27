// Sprint 126 — customer-side Documents page. Same shared explorer as the
// provider sub-tab, in `customer` mode: the caller's own customer via
// `me.customer_ids[0]`, no picker. Reached from the customer sidebar, gated on
// `customer.documents.manage`; the backend 404s a user without the key, so the
// explorer's own load-error state is the backstop if the nav is ever reached
// without it.
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";
import { DocumentsExplorer } from "../components/documents/DocumentsExplorer";

export function MyDocumentsPage() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const customerId = me?.customer_ids?.[0] ?? null;

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
      {customerId === null ? (
        <p className="muted">{t("documents.no_customer")}</p>
      ) : (
        <DocumentsExplorer customerId={customerId} side="customer" />
      )}
    </div>
  );
}
