import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * Sprint 28 Batch 13 — shared header for the customer-scoped admin
 * sub-pages (Overview / Permissions / Buildings / Users / Settings).
 *
 * View-first per the 2026-05-15 stakeholder doc §3: every customer
 * sub-page lands on a read-only home with an explicit back link, the
 * customer name as the page title, and a small active/inactive
 * indicator. Mutable actions (Edit basics, Edit permissions, etc.)
 * live on the individual page bodies, not in this header.
 */
export interface CustomerSubPageHeaderProps {
  customerName: string;
  isActive: boolean;
  eyebrow?: string;
  /** Optional right-aligned action slot (e.g. "Edit basics"). */
  actions?: React.ReactNode;
}

export function CustomerSubPageHeader({
  customerName,
  isActive,
  eyebrow,
  actions,
}: CustomerSubPageHeaderProps) {
  const { t } = useTranslation("common");

  return (
    <>
      <Link
        to="/admin/customers"
        className="link-back"
        data-testid="customer-subpage-back"
      >
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("customer_view.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {eyebrow ?? t("nav.admin_group")}
          </div>
          <h2 className="page-title">
            {customerName || t("customer_form.fallback")}
            {!isActive && (
              <span style={{ marginLeft: 12 }}>
                <span className="cell-tag cell-tag-closed">
                  <i />
                  {t("admin.status_inactive")}
                </span>
              </span>
            )}
          </h2>
        </div>
        {actions && <div className="page-header-actions">{actions}</div>}
      </div>
    </>
  );
}
