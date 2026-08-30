import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Building2, Plus, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import { bulkDeactivateCompanies, listCompanies } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useSavedBanner } from "../../hooks/useSavedBanner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EditModeToggle } from "../../components/EditModeToggle";
import { EmptyState } from "../../components/EmptyState";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { PageHeader } from "../../components/PageHeader";
import { SortableHeader } from "../../components/SortableHeader";
import type { SortState } from "../../components/SortableHeader";
import { useEditMode } from "../../lib/useEditMode";

/** Every value here MUST exist in `CompanyViewSet.ordering_fields`;
 *  the backend allowlist is the authority and rejects anything else.
 *  P-6 V3 — `slug` left the list (it is an Advanced value on the detail
 *  page, §D.6 rule 12), so it is no longer a column to sort by. */
type SortField = "name" | "is_active" | "created_at";

type ActiveFilter = "true" | "false" | "all";

const DEBOUNCE_MS = 300;

function formatDate(value: string, locale: string): string {
  try {
    return new Date(value).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}

export function CompaniesAdminPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("common");
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Sprint 157 §3 — sorting, selection and bulk deactivate, brought to
  // the same standard as the buildings list.
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const bulkDialogRef = useRef<ConfirmDialogHandle>(null);
  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("true");

  const [savedBanner] = useSavedBanner({
    saved: t("companies.banner_saved"),
    deactivated: t("companies.banner_deactivated"),
    reactivated: t("companies.banner_reactivated"),
  });

  // Debounce the search input.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearchActive(searchInput.trim());
      setPage(1);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const queryParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { page };
    if (searchActive) params.search = searchActive;
    if (activeFilter !== "all") params.is_active = activeFilter;
    // The backend allowlist is the authority — `CompanyViewSet
    // .ordering_fields` was extended additively in the same sprint, and
    // a value it does not know is a 400 rather than a soft fallback.
    params.ordering = sortDirection === "desc" ? `-${sortField}` : sortField;
    return params;
  }, [page, searchActive, activeFilter, sortField, sortDirection]);

  const pageIds = useMemo(() => companies.map((c) => c.id), [companies]);
  const edit = useEditMode(pageIds, { onExit: () => setSelectedIds([]) });

  const allOnPageSelected =
    pageIds.length > 0 &&
    pageIds.every((id) => selectedIds.includes(id));

  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      } else {
        setSortField(field);
        setSortDirection("asc");
      }
      setPage(1);
    },
    [sortField],
  );

  const sortStateFor = (field: SortField): SortState =>
    sortField !== field
      ? "none"
      : sortDirection === "asc"
        ? "ascending"
        : "descending";

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listCompanies(queryParams);
      setCompanies(response.results);
      setCount(response.count);
      setNext(response.next);
      setPrevious(response.previous);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [queryParams]);

  useEffect(() => {
    load();
  }, [load]);

  const hasActiveFilters = Boolean(searchActive || activeFilter !== "true");

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  // P-6 V3 (§D.6 rule 12) — the language as a word, never the raw code.
  // The detail page says "Nederlands (nl)"; a list column has room for
  // the word only.
  const languageLabel = (code: string): string => {
    if (code === "nl") return t("language_dutch");
    if (code === "en") return t("language_english");
    return code;
  };

  const statusLabel = (active: boolean) =>
    active ? t("admin.status_active") : t("admin.status_inactive");

  // P-6 V3 — the filters behind ONE Filter fold with the active ones as
  // chips (the contracts / tickets pattern); the search stays outside.
  const activeFilterChips: string[] = [];
  if (activeFilter === "false") activeFilterChips.push(t("admin.status_inactive"));
  if (activeFilter === "all") activeFilterChips.push(t("admin.status_all"));

  const previousLocked = loading
    ? t("admin_list.page_loading")
    : !previous || page <= 1
      ? t("admin_list.page_first")
      : undefined;
  const nextLocked = loading
    ? t("admin_list.page_loading")
    : !next
      ? t("admin_list.page_last")
      : undefined;

  const createLink = isSuperAdmin ? (
    <Link
      className="btn btn-primary btn-sm"
      to="/admin/companies/new"
      data-testid="companies-create-link"
    >
      <Plus size={14} strokeWidth={2.5} />
      {t("admin.create_new")}
    </Link>
  ) : undefined;

  return (
    <div>
      {/* P-6 V3 — the shared header; "+ New" is the one primary action
          (§D.6 rule 3). The Refresh button is gone: the list reloads on
          every filter, sort and save, so it only ever repeated what the
          page had just done. */}
      <PageHeader
        eyebrow={t("nav.admin_group")}
        title={t("nav.companies")}
        subtitle={
          loading ? t("companies.loading") : t("companies.count", { count })
        }
        actions={createLink}
      />

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            setSearchActive(searchInput.trim());
            setPage(1);
          }}
        >
          <div className="filter-field search">
            <span className="filter-label">{t("search")}</span>
            <input
              className="filter-control"
              type="search"
              placeholder={t("companies.search_placeholder")}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </div>
          <div className="filter-actions">
            {hasActiveFilters && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="filters-clear"
                onClick={() => {
                  setSearchInput("");
                  setActiveFilter("true");
                  setPage(1);
                }}
              >
                {t("clear")}
              </button>
            )}
            {pageIds.length > 0 && (
              /* §D.6 rule 14 — the toggle has no title of its own, so the
                 reason it is off rides on the wrapper. */
              <span title={bulkBusy ? t("admin_list.edit_busy") : undefined}>
                <EditModeToggle
                  editMode={edit.editMode}
                  onToggle={edit.toggleMode}
                  disabled={bulkBusy}
                  testId="companies-edit-mode-toggle"
                />
              </span>
            )}
          </div>
          <details
            className="filter-fold"
            open={activeFilterChips.length > 0}
            data-testid="companies-filter-fold"
          >
            <summary className="filter-fold-summary" data-testid="companies-filter-toggle">
              <SlidersHorizontal size={14} strokeWidth={2.4} aria-hidden="true" />
              {t("admin_list.filter_fold")}
              {activeFilterChips.length > 0 && (
                <span className="filter-fold-count">
                  {t("admin_list.filter_active", { count: activeFilterChips.length })}
                </span>
              )}
              {activeFilterChips.map((label) => (
                <span className="filter-fold-chip" key={label}>
                  {label}
                </span>
              ))}
            </summary>
            <div className="filter-fold-body">
              <div className="filter-field">
                <span className="filter-label">{t("status")}</span>
                <select
                  className="filter-control"
                  value={activeFilter}
                  onChange={(event) => {
                    setActiveFilter(event.target.value as ActiveFilter);
                    setPage(1);
                  }}
                >
                  <option value="true">{t("admin.status_active")}</option>
                  <option value="false">{t("admin.status_inactive")}</option>
                  <option value="all">{t("admin.status_all")}</option>
                </select>
              </div>
            </div>
          </details>
        </form>

        {edit.editMode && (
          <MultiSelectToolbar
            selectedCount={selectedIds.length}
            onSelectAll={() =>
              setSelectedIds((current) => [...new Set([...current, ...pageIds])])
            }
            onClearAll={() => setSelectedIds([])}
            disabled={bulkBusy}
            actions={[
              {
                key: "deactivate",
                label: t("companies.bulk_deactivate"),
                destructive: true,
                onClick: () => bulkDialogRef.current?.open(),
              },
            ]}
            testIdPrefix="companies-bulk"
          />
        )}

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                {edit.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={() =>
                        setSelectedIds((current) =>
                          allOnPageSelected
                            ? current.filter((id) => !pageIds.includes(id))
                            : [...new Set([...current, ...pageIds])],
                        )
                      }
                      disabled={pageIds.length === 0 || bulkBusy}
                      aria-label={t("companies.select_page")}
                      data-testid="companies-select-page"
                    />
                  </th>
                )}
                <SortableHeader
                  label={t("admin.col_name")}
                  sort={sortStateFor("name")}
                  testId="companies-sort-name"
                  onSort={() => handleSort("name")}
                  sortByLabel={t("companies.sort_by", {
                    column: t("admin.col_name"),
                  })}
                />
                <th>{t("companies.col_default_language")}</th>
                <SortableHeader
                  label={t("created")}
                  sort={sortStateFor("created_at")}
                  testId="companies-sort-created_at"
                  onSort={() => handleSort("created_at")}
                  sortByLabel={t("companies.sort_by", { column: t("created") })}
                />
                <SortableHeader
                  label={t("status")}
                  sort={sortStateFor("is_active")}
                  testId="companies-sort-is_active"
                  onSort={() => handleSort("is_active")}
                  sortByLabel={t("companies.sort_by", { column: t("status") })}
                />
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => {
                const detailPath = `/admin/companies/${company.id}`;
                const editPath = `${detailPath}/edit`;
                const openDetail = () => navigate(detailPath);
                return (
                  <tr
                    key={company.id}
                    className="admin-row-clickable"
                    role="link"
                    tabIndex={0}
                    aria-label={t("admin.view") + ": " + company.name}
                    /* W14 §3 — one click, one history entry. The row
                       navigates AND contains a `<Link>` to the same
                       place, so a click on the link pushed twice and
                       the browser's Back then landed on the page it was
                       pressed from. Same defect, same fix, as the
                       tickets list. */
                    onClick={(event) => {
                      if ((event.target as HTMLElement).closest("a,button")) {
                        return;
                      }
                      openDetail();
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openDetail();
                      }
                    }}
                  >
                    {edit.editMode && (
                      <td
                        className="td-select"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(company.id)}
                          onChange={() =>
                            setSelectedIds((current) =>
                              current.includes(company.id)
                                ? current.filter((id) => id !== company.id)
                                : [...current, company.id],
                            )
                          }
                          disabled={bulkBusy}
                          aria-label={company.name}
                          data-testid={`companies-select-${company.id}`}
                        />
                      </td>
                    )}
                    <td className="td-subject">
                      <Link to={detailPath}>{company.name}</Link>
                    </td>
                    <td>{languageLabel(company.default_language)}</td>
                    <td className="td-date">{formatDate(company.created_at, dateLocale)}</td>
                    <td>
                      <span
                        className={`cell-tag cell-tag-${company.is_active ? "open" : "closed"}`}
                      >
                        <i />
                        {statusLabel(company.is_active)}
                      </span>
                    </td>
                    <td>
                      <Link
                        className="btn btn-ghost btn-sm"
                        to={editPath}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {t("admin.edit")}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Sprint 22 final polish: phone-width parallel card list.
            Hidden via CSS @media (min-width: 601px). The desktop
            table above stays in the DOM at all widths so Playwright
            tablet/desktop assertions still resolve. */}
        <ul
          className="admin-card-list"
          data-testid="admin-card-list"
          aria-label={t("nav.companies")}
        >
          {companies.map((company) => {
            const detailPath = `/admin/companies/${company.id}`;
            return (
              <li key={company.id} className="admin-card">
                <Link
                  to={detailPath}
                  className="admin-card-link"
                  aria-label={`${t("admin.edit")}: ${company.name}`}
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{company.name}</span>
                    <span
                      className={`cell-tag cell-tag-${company.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {statusLabel(company.is_active)}
                    </span>
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("companies.col_default_language")}</dt>
                      <dd>{languageLabel(company.default_language)}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("created")}</dt>
                      <dd>{formatDate(company.created_at, dateLocale)}</dd>
                    </div>
                  </dl>
                  <div className="admin-card-actions">
                    <span className="btn btn-ghost btn-sm">
                      {t("admin.edit")}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>

        {!loading && companies.length === 0 && (
          <EmptyState
            icon={Building2}
            title={
              hasActiveFilters
                ? t("companies.empty_filtered_title")
                : t("companies.empty_initial_title")
            }
            description={
              hasActiveFilters
                ? t("admin.empty_filtered_desc")
                : isSuperAdmin
                  ? t("companies.empty_initial_desc_admin")
                  : t("companies.empty_initial_desc_other")
            }
            action={
              isSuperAdmin && !hasActiveFilters ? (
                <Link className="btn btn-primary btn-sm" to="/admin/companies/new">
                  {t("companies.create")}
                </Link>
              ) : undefined
            }
            testId="companies-empty"
          />
        )}

        {(previous || next) && (
          <div className="pagination">
            <span className="pagination-info">
              {t("admin.pagination_page", { page, total: count })}
            </span>
            <div className="pagination-controls">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={previousLocked !== undefined}
                title={previousLocked}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("previous")}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={nextLocked !== undefined}
                title={nextLocked}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("next")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Rendered UNCONDITIONALLY and ref-driven (CLAUDE.md §3). */}
      <ConfirmDialog
        ref={bulkDialogRef}
        title={t("companies.bulk_deactivate_title")}
        body={t("companies.bulk_deactivate_body", {
          count: selectedIds.length,
        })}
        confirmLabel={t("companies.bulk_deactivate")}
        onConfirm={async () => {
          if (selectedIds.length === 0) return;
          setBulkBusy(true);
          setError("");
          try {
            await bulkDeactivateCompanies(selectedIds);
            bulkDialogRef.current?.close();
            edit.exit();
            await load();
          } catch (err) {
            setError(getApiError(err));
            bulkDialogRef.current?.close();
          } finally {
            setBulkBusy(false);
          }
        }}
        busy={bulkBusy}
        destructive
      />
    </div>
  );
}
