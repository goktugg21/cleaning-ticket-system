/**
 * Sprint 28 Batch 15.1 — shared empty state.
 *
 * Pages previously rendered three different "nothing here" shapes:
 *   - styled .empty-state with icon+title+sub+CTA (Dashboard)
 *   - generic .alert-info banner (ExtraWorkListPage)
 *   - centered "Coming soon" panel (CustomerSubPagePlaceholder)
 *
 * One component, one visual, used everywhere a page (or section of
 * a page) genuinely has nothing to show. The CSS hook
 * `.empty-state-v2` is new and lives alongside the legacy
 * `.empty-state` class so we don't break the Dashboard's existing
 * empty state.
 */
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  /** When true, render a compact variant suitable for table-empty cells. */
  compact?: boolean;
  testId?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact,
  testId,
}: EmptyStateProps) {
  return (
    <div
      className={`empty-state-v2${compact ? " empty-state-v2-compact" : ""}`}
      role="status"
      data-testid={testId}
    >
      {Icon && (
        <div className="empty-state-v2-icon" aria-hidden="true">
          <Icon size={compact ? 18 : 22} strokeWidth={1.75} />
        </div>
      )}
      <div className="empty-state-v2-title">{title}</div>
      {description && (
        <p className="empty-state-v2-desc">{description}</p>
      )}
      {action && <div className="empty-state-v2-action">{action}</div>}
    </div>
  );
}

