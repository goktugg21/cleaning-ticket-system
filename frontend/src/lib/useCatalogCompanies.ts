import { useEffect, useState } from "react";

import { listAllCompanies } from "../api/admin";
import type { CompanyAdmin } from "../api/types";

/**
 * Sprint 186 §3 — the company state behind the ONE catalog company
 * selector, so a catalog tab that cannot use `CatalogTab` itself can
 * still use the same control.
 *
 * The five per-company catalogs are built two ways: three of them (work
 * types, contract types, building types) ARE a `CatalogTab`, and two
 * (`HourTypesTab`, `ManagedUnitsTab`) carry real domain columns —
 * multiplier and sort order, bulk delete and a detail panel — that
 * `CatalogTab` does not have and should not grow. Those two took the
 * selected company as PROPS from the page that hosted them, which was
 * fine while their only host rendered a selector, and became "no
 * selector at all" the moment `CatalogsAdminPage` mounted them without
 * one. This hook is the fix that does not add a third implementation:
 * the same fetch, the same seeding rule, offered to any caller.
 *
 * It lives in `lib/` rather than beside `CatalogCompanySelect` for the
 * reason `useEditMode` does: a module that exports a component and a
 * hook fails the fast-refresh lint rule, and the rule is right — the
 * hook has no markup and three consumers.
 *
 * `enabled: false` skips the fetch entirely, for a tab whose host still
 * owns the choice — the Hours and Services pages already fetch the
 * company list for the selector they render themselves and must not
 * fetch it a second time.
 */
export function useCatalogCompanies(enabled = true) {
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companyId, setCompanyId] = useState<number | "">("");

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    listAllCompanies()
      .then((all) => {
        if (cancelled) return;
        setCompanies(all);
        // Seeded inside the .then(), never in an effect body. The
        // LOWEST id is the deployment's first tenant, not an
        // alphabetical accident.
        setCompanyId((current) =>
          current === "" && all.length > 0
            ? [...all].sort((a, b) => a.id - b.id)[0].id
            : current,
        );
      })
      .catch(() => {
        if (!cancelled) setCompanies([]);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { companies, companyId, setCompanyId };
}
