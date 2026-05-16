import { useTranslation } from "react-i18next";

/**
 * Sprint 28 Batch 3 — Sidebar refactor foundation.
 *
 * Minimal placeholder rendered at every customer-scoped sub-route
 * whose real implementation is parked for a later batch. The
 * customer-scoped sidebar (see `AppShell.tsx`) deep-links to each
 * of:
 *   - `/admin/customers/:id/buildings`
 *   - `/admin/customers/:id/users`
 *   - `/admin/customers/:id/extra-work`
 *   - `/admin/customers/:id/contacts`
 *   - `/admin/customers/:id/settings`
 *
 * The `Permissions` sub-route is the deliberate exception — it
 * re-renders the Sprint 27E permission editor (`CustomerFormPage`)
 * so the existing editor remains reachable without refactoring it.
 * The `Overview` sub-route is the existing `CustomerFormPage` parent.
 *
 * Per the Batch 3 brief ("placeholder strategy"): one component,
 * shared across all five placeholder sub-routes, returns an empty
 * "coming soon" state. View-first per spec §3 — no editing surface.
 */
export function CustomerSubPagePlaceholder() {
  const { t } = useTranslation("common");

  return (
    <section
      className="page-canvas-card"
      data-testid="customer-subpage-placeholder"
      style={{
        padding: "32px",
        textAlign: "center",
        maxWidth: 640,
        margin: "32px auto",
      }}
    >
      <h2 style={{ marginBottom: 12 }}>
        {t("customer_subpage_placeholder.title")}
      </h2>
      <p className="muted" style={{ margin: 0 }}>
        {t("customer_subpage_placeholder.description")}
      </p>
    </section>
  );
}
