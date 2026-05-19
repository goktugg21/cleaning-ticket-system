/**
 * Sprint 28 Batch 15.1 — shared page header.
 *
 * Replaces ad-hoc `<div class="page-header">` + breadcrumb + eyebrow
 * + back-link combos that diverged page-by-page. Every page-level
 * route should mount one of these and never roll its own.
 *
 * Slots (top-to-bottom):
 *   - backLink:    inline "← Back to …" link (optional)
 *   - breadcrumbs: nav row (optional, takes precedence over eyebrow if both set)
 *   - eyebrow:     small caps category label (optional)
 *   - title:       required
 *   - statusPill:  inline next to title (optional; renders via <StatusBadge/>)
 *   - subtitle:    one-line context under the title (optional)
 *   - actions:     right-aligned slot for buttons / links (optional)
 *
 * The component preserves the existing `.page-header / .page-title /
 * .page-sub / .breadcrumb / .eyebrow / .link-back` classes so the
 * existing CSS keeps working; nothing else changes visually for pages
 * that already used those classes.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";

export interface PageHeaderBreadcrumb {
  label: string;
  to?: string;
}

export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  breadcrumbs?: PageHeaderBreadcrumb[];
  backLink?: { to: string; label: string };
  statusPill?: ReactNode;
  actions?: ReactNode;
  /** Optional test id attached to the wrapping div. */
  testId?: string;
}

export function PageHeader({
  title,
  subtitle,
  eyebrow,
  breadcrumbs,
  backLink,
  statusPill,
  actions,
  testId,
}: PageHeaderProps) {
  return (
    <div className="page-header" data-testid={testId}>
      <div className="page-header-text">
        {backLink && (
          <Link to={backLink.to} className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {backLink.label}
          </Link>
        )}
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav className="breadcrumb" aria-label="Breadcrumb">
            {breadcrumbs.map((crumb, i) => {
              const isLast = i === breadcrumbs.length - 1;
              return (
                <span key={`${crumb.label}-${i}`} className="breadcrumb-item">
                  {crumb.to && !isLast ? (
                    <Link to={crumb.to}>{crumb.label}</Link>
                  ) : (
                    <span
                      className={isLast ? "breadcrumb-current" : undefined}
                    >
                      {crumb.label}
                    </span>
                  )}
                  {!isLast && <span className="breadcrumb-sep">›</span>}
                </span>
              );
            })}
          </nav>
        )}
        {eyebrow && !breadcrumbs && <div className="eyebrow">{eyebrow}</div>}
        <div className="page-title-row">
          <h2 className="page-title">{title}</h2>
          {statusPill && <span className="page-title-pill">{statusPill}</span>}
        </div>
        {subtitle && <p className="page-sub">{subtitle}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}

