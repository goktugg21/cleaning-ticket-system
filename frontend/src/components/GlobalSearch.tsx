/**
 * P-6 V4 — the header search box.
 *
 * One input in the top bar; results in a popover anchored to it
 * (Addendum D §D.6 rule 2: actions appear where you clicked), grouped
 * the way the sidebar groups the system — work first, then places and
 * people. Every row is a link only where the viewer may go: a STAFF
 * reader never gets a meerwerk door (`canAccessExtraWork`), and the
 * admin pages are offered only to admin roles — the same predicates the
 * sidebar uses, so the box can never open a door the nav hides.
 *
 * Nothing fuzzy, nothing stored: the server answers `icontains` over
 * the viewer's own scope; the box debounces typing and drops a stale
 * answer that lands after a newer query.
 */
import { useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Search, X } from "lucide-react";

import { getApiError } from "../api/client";
import {
  globalSearch,
  SEARCH_GROUP_ORDER,
  type GlobalSearchResponse,
  type SearchGroupKey,
} from "../api/search";
import { useAuth } from "../auth/AuthContext";
import {
  canAccessAdminArea,
  canAccessExtraWork,
  canReadCustomerArea,
} from "../auth/permissions";

const MIN_QUERY = 2;
const DEBOUNCE_MS = 250;

interface ResultRow {
  key: string;
  to: string | null;
  primary: string;
  secondary: string;
}

export function GlobalSearch() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const navigate = useNavigate();
  const role = me?.role ?? null;
  const listId = useId();

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<GlobalSearchResponse | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestSeq = useRef(0);

  // Debounced fetch; a stale answer never overwrites a newer one.
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY) {
      return;
    }
    const seq = ++requestSeq.current;
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const data = await globalSearch(trimmed);
        if (seq !== requestSeq.current) return;
        setResult(data);
        setError("");
      } catch (err) {
        if (seq !== requestSeq.current) return;
        setError(getApiError(err));
      } finally {
        if (seq === requestSeq.current) setBusy(false);
      }
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  // Click outside / Escape closes the popover.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        inputRef.current?.blur();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const trimmed = query.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_QUERY;
  const showing = result && result.q === trimmed ? result : null;

  function rowsFor(group: SearchGroupKey): ResultRow[] {
    if (!showing) return [];
    switch (group) {
      case "tickets":
        return showing.groups.tickets.map((hit) => ({
          key: `t-${hit.id}`,
          to: `/tickets/${hit.id}`,
          primary: hit.ticket_no ? `${hit.ticket_no} · ${hit.title}` : hit.title,
          secondary: [hit.building_name, hit.customer_name].filter(Boolean).join(" · "),
        }));
      case "extra_work":
        return showing.groups.extra_work.map((hit) => ({
          key: `e-${hit.id}`,
          to: canAccessExtraWork(role) ? `/extra-work/${hit.id}` : null,
          primary: hit.title,
          secondary: [hit.building_name, hit.customer_name].filter(Boolean).join(" · "),
        }));
      case "customers":
        return showing.groups.customers.map((hit) => ({
          key: `c-${hit.id}`,
          to: canReadCustomerArea(role) ? `/admin/customers/${hit.id}` : null,
          primary: hit.name,
          secondary: hit.company_name ?? "",
        }));
      case "buildings":
        return showing.groups.buildings.map((hit) => ({
          key: `b-${hit.id}`,
          to: canAccessAdminArea(role) ? `/admin/buildings/${hit.id}` : null,
          primary: hit.name,
          secondary: [hit.city, hit.company_name].filter(Boolean).join(" · "),
        }));
      case "people":
        return showing.groups.people.map((hit) => ({
          key: `p-${hit.id}`,
          to: canAccessAdminArea(role) ? `/admin/users/${hit.id}` : null,
          primary: hit.full_name || hit.email,
          secondary: hit.full_name ? hit.email : "",
        }));
      default:
        return [];
    }
  }

  const groups = SEARCH_GROUP_ORDER.map((group) => ({
    group,
    rows: rowsFor(group),
    truncated: showing?.truncated[group] ?? false,
  })).filter((entry) => entry.rows.length > 0);
  const total = groups.reduce((sum, entry) => sum + entry.rows.length, 0);

  function go(to: string) {
    setOpen(false);
    navigate(to);
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    // Enter opens the first result that has a door.
    const first = groups.flatMap((entry) => entry.rows).find((row) => row.to);
    if (first?.to) go(first.to);
  }

  return (
    <div className="topbar-search" ref={wrapRef} data-testid="global-search">
      <form className="topbar-search-form" role="search" onSubmit={onSubmit}>
        <Search size={15} strokeWidth={2.2} aria-hidden="true" className="topbar-search-icon" />
        <input
          ref={inputRef}
          type="search"
          className="topbar-search-input"
          value={query}
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
          aria-controls={listId}
          aria-expanded={open}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          data-testid="global-search-input"
        />
        {query && (
          <button
            type="button"
            className="topbar-search-clear"
            aria-label={t("search.clear")}
            onClick={() => {
              setQuery("");
              setResult(null);
              inputRef.current?.focus();
            }}
          >
            <X size={14} strokeWidth={2.4} aria-hidden="true" />
          </button>
        )}
      </form>

      {open && trimmed.length > 0 && (
        <div className="topbar-search-panel" id={listId} data-testid="global-search-panel">
          {tooShort && (
            <div className="topbar-search-note">{t("search.too_short", { count: MIN_QUERY })}</div>
          )}
          {!tooShort && error && (
            <div className="topbar-search-note" role="alert">{error}</div>
          )}
          {!tooShort && !error && busy && !showing && (
            <div className="topbar-search-note">{t("search.searching")}</div>
          )}
          {!tooShort && !error && showing && total === 0 && (
            <div className="topbar-search-note" data-testid="global-search-empty">
              {t("search.empty", { q: showing.q })}
            </div>
          )}
          {!tooShort && !error && showing && total > 0 && (
            <div className="topbar-search-groups">
              {groups.map((entry) => (
                <section
                  key={entry.group}
                  className="topbar-search-group"
                  data-testid={`global-search-group-${entry.group}`}
                >
                  <div className="topbar-search-group-title">
                    {t(`search.group_${entry.group}`)}
                    {entry.truncated && (
                      <span className="topbar-search-more">{t("search.more")}</span>
                    )}
                  </div>
                  <ul className="topbar-search-list">
                    {entry.rows.map((row) => (
                      <li key={row.key}>
                        {row.to ? (
                          <Link
                            to={row.to}
                            className="topbar-search-row"
                            onClick={(event) => {
                              event.preventDefault();
                              go(row.to as string);
                            }}
                            data-testid="global-search-row"
                          >
                            <span className="topbar-search-primary">{row.primary}</span>
                            {row.secondary && (
                              <span className="topbar-search-secondary">{row.secondary}</span>
                            )}
                          </Link>
                        ) : (
                          <span className="topbar-search-row topbar-search-row-inert" data-testid="global-search-row">
                            <span className="topbar-search-primary">{row.primary}</span>
                            {row.secondary && (
                              <span className="topbar-search-secondary">{row.secondary}</span>
                            )}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
