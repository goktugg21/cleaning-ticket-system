import { useCallback, useEffect, useState } from "react";

import { listAllCompanies } from "../api/admin";
import type { CompanyAdmin } from "../api/types";

/**
 * P-12 §D.24.2 — one company at a time on the Finance pages (Invoices,
 * Contracts, Hours, Reports). SUPER_ADMIN picks a company top right;
 * the choice is remembered per session and SHARED across the four
 * pages (walking Invoices → Contracts keeps the company). Provider
 * admins never see the selector — their server scope already is their
 * company, so `enabled` is false and `companyId` stays "".
 *
 * The DEFAULT is the page's to give: §D.24.2 says "the company with
 * something waiting", and only the page knows what waits. When the
 * session holds no choice the page calls `seedCompany` once its counts
 * are in (seeding is not remembered — a different page may default
 * differently); an explicit `chooseCompany` is what writes the session
 * memory.
 *
 * In `lib/` for the `useCatalogCompanies` reason: a module exporting a
 * hook and a component trips the fast-refresh rule.
 */
const SCOPE_KEY = "guide.company";

/** The session's shared Finance-pages company, or null. Exported for a
 *  page (Hours) that manages its own company state but must share the
 *  memory. */
export function readScopeCompany(): number | null {
  try {
    const raw = window.sessionStorage.getItem(SCOPE_KEY);
    const id = raw == null ? NaN : Number(raw);
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

/** Remember a company for the session — the shared key. */
export function rememberScopeCompany(id: number): void {
  try {
    window.sessionStorage.setItem(SCOPE_KEY, String(id));
  } catch {
    // Session memory is a courtesy; the page still works without it.
  }
}

export function useCompanyScope(enabled: boolean): {
  companies: CompanyAdmin[];
  companyId: number | "";
  /** The person picked one — remembered for the session. */
  chooseCompany: (id: number) => void;
  /** The page's default when nothing is stored — not remembered. */
  seedCompany: (id: number) => void;
  /** Companies fetched (or the selector disabled). */
  ready: boolean;
} {
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companyId, setCompanyId] = useState<number | "">("");
  const [ready, setReady] = useState(!enabled);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    listAllCompanies()
      .then((all) => {
        if (cancelled) return;
        setCompanies(all);
        setCompanyId((current) => {
          if (current !== "") return current;
          const stored = readScopeCompany();
          if (stored != null && all.some((c) => c.id === stored)) return stored;
          // One company: there is no choice to make (and no selector).
          if (all.length === 1) return all[0].id;
          return "";
        });
        setReady(true);
      })
      .catch(() => {
        if (!cancelled) {
          setCompanies([]);
          setReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const chooseCompany = useCallback((id: number) => {
    setCompanyId(id);
    rememberScopeCompany(id);
  }, []);

  const seedCompany = useCallback((id: number) => {
    setCompanyId((current) => (current === "" ? id : current));
  }, []);

  return { companies, companyId, chooseCompany, seedCompany, ready };
}
