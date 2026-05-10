import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getApiError } from "../../api/client";
import { listAuditLogs } from "../../api/admin";
import type { AuditLogListParams } from "../../api/admin";
import type { AuditAction, AuditLog } from "../../api/types";

/**
 * Sprint 18 — read-only audit log viewer for SUPER_ADMIN.
 *
 * Mirrors the filter shape of `backend/audit/filters.py::AuditLogFilter`:
 *
 *   target_model  exact CharFilter (e.g. "accounts.User")
 *   target_id     exact NumberFilter
 *   actor         exact NumberFilter (user id)
 *   date_from     ISO datetime (gte on created_at)
 *   date_to       ISO datetime (lte on created_at)
 *
 * The backend does NOT expose a ?action= filter, so the action column
 * is read-only (no dropdown filter). If a future sprint adds it, this
 * page can grow a select without touching the rest of the UX.
 *
 * The `changes` payload is rendered as JSON inside a <details> block
 * so the schema can drift (Sprint 14 added customer-building-link
 * shapes; Sprint 7 added membership shapes) without this page hiding
 * any field.
 */

const PAGE_SIZE = 25;

const ACTION_LABEL: Record<AuditAction, string> = {
  CREATE: "Create",
  UPDATE: "Update",
  DELETE: "Delete",
};

const ACTION_CLASS: Record<AuditAction, string> = {
  CREATE: "cell-tag-open",
  UPDATE: "cell-tag-in_progress",
  DELETE: "cell-tag-rejected",
};

function formatTimestamp(value: string): string {
  try {
    return new Date(value).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return value;
  }
}

function isoStartOfDay(value: string): string {
  // Convert a "YYYY-MM-DD" picker value into the timezone-aware ISO
  // datetime the backend filter expects. Browser timezone is fine —
  // the audit log records absolute UTC and DRF converts on read.
  return new Date(`${value}T00:00:00`).toISOString();
}

function isoEndOfDay(value: string): string {
  return new Date(`${value}T23:59:59.999`).toISOString();
}

export function AuditLogsAdminPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Local form state. Numeric fields are kept as strings so an empty
  // input is distinguishable from a literal 0 — only sent to the API
  // when valid.
  const [targetModelInput, setTargetModelInput] = useState("");
  const [targetIdInput, setTargetIdInput] = useState("");
  const [actorInput, setActorInput] = useState("");
  const [dateFromInput, setDateFromInput] = useState("");
  const [dateToInput, setDateToInput] = useState("");
  // The "applied" copies are what the API actually sees. Updating them
  // resets the page to 1.
  const [applied, setApplied] = useState<{
    target_model?: string;
    target_id?: number;
    actor?: number;
    date_from?: string;
    date_to?: string;
  }>({});

  const queryParams = useMemo<AuditLogListParams>(() => {
    return { page, ...applied };
  }, [page, applied]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listAuditLogs(queryParams);
      setLogs(response.results);
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

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));
  const hasActiveFilters = Object.keys(applied).length > 0;

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    const next: typeof applied = {};
    if (targetModelInput.trim()) next.target_model = targetModelInput.trim();
    if (targetIdInput.trim()) {
      const parsed = Number.parseInt(targetIdInput, 10);
      if (Number.isFinite(parsed) && parsed > 0) next.target_id = parsed;
    }
    if (actorInput.trim()) {
      const parsed = Number.parseInt(actorInput, 10);
      if (Number.isFinite(parsed) && parsed > 0) next.actor = parsed;
    }
    if (dateFromInput) next.date_from = isoStartOfDay(dateFromInput);
    if (dateToInput) next.date_to = isoEndOfDay(dateToInput);
    setApplied(next);
    setPage(1);
  }

  function clearFilters() {
    setTargetModelInput("");
    setTargetIdInput("");
    setActorInput("");
    setDateFromInput("");
    setDateToInput("");
    setApplied({});
    setPage(1);
  }

  return (
    <div data-testid="audit-logs-page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">Audit log</h2>
          <p className="page-sub">
            {loading
              ? "Loading audit log…"
              : `${count} audit ${count === 1 ? "entry" : "entries"}`}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <form className="filter-bar" onSubmit={applyFilters}>
          <div className="filter-field">
            <span className="filter-label">Target model</span>
            <input
              className="filter-control"
              type="text"
              placeholder="e.g. accounts.User"
              value={targetModelInput}
              onChange={(event) => setTargetModelInput(event.target.value)}
              data-testid="audit-filter-target-model"
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">Target id</span>
            <input
              className="filter-control"
              type="number"
              min={1}
              placeholder="e.g. 42"
              value={targetIdInput}
              onChange={(event) => setTargetIdInput(event.target.value)}
              data-testid="audit-filter-target-id"
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">Actor id</span>
            <input
              className="filter-control"
              type="number"
              min={1}
              placeholder="user id"
              value={actorInput}
              onChange={(event) => setActorInput(event.target.value)}
              data-testid="audit-filter-actor"
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">From</span>
            <input
              className="filter-control"
              type="date"
              value={dateFromInput}
              onChange={(event) => setDateFromInput(event.target.value)}
              data-testid="audit-filter-from"
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">To</span>
            <input
              className="filter-control"
              type="date"
              value={dateToInput}
              onChange={(event) => setDateToInput(event.target.value)}
              data-testid="audit-filter-to"
            />
          </div>
          <div className="filter-actions">
            <button type="submit" className="btn btn-secondary btn-sm">
              Apply
            </button>
            {hasActiveFilters && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={clearFilters}
              >
                Clear
              </button>
            )}
          </div>
        </form>

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Request</th>
                <th aria-label="Changes" />
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} data-testid="audit-row">
                  <td className="td-date">{formatTimestamp(log.created_at)}</td>
                  <td>
                    {log.actor_email ? (
                      <span title={log.actor_email}>{log.actor_email}</span>
                    ) : (
                      <span className="muted">system</span>
                    )}
                  </td>
                  <td>
                    <span className={`cell-tag ${ACTION_CLASS[log.action]}`}>
                      <i />
                      {ACTION_LABEL[log.action]}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontFamily: "var(--f-mono, monospace)" }}>
                      {log.target_model}#{log.target_id}
                    </span>
                  </td>
                  <td>
                    <span className="muted small">
                      {log.request_ip || "—"}
                      {log.request_id ? ` · ${log.request_id}` : ""}
                    </span>
                  </td>
                  <td>
                    <details>
                      <summary
                        style={{ cursor: "pointer" }}
                        data-testid="audit-row-changes-summary"
                      >
                        Changes
                      </summary>
                      <pre
                        // Sprint 20: max-width handled via the
                        // [data-testid="audit-logs-page"] selector
                        // in index.css so it can clamp to the
                        // viewport on phones; keep inline styles for
                        // the per-cell box only.
                        style={{
                          background: "var(--bg-soft, #f7f7f7)",
                          padding: "8px 10px",
                          borderRadius: 4,
                          fontSize: 12,
                          maxHeight: 280,
                          overflow: "auto",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          marginTop: 6,
                        }}
                      >
                        {JSON.stringify(log.changes, null, 2)}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!loading && logs.length === 0 && (
            <div className="empty-state" data-testid="audit-empty">
              <div className="empty-icon">·</div>
              <div className="empty-title">
                {hasActiveFilters
                  ? "No audit entries match your filters"
                  : "No audit entries yet"}
              </div>
              <p className="empty-sub">
                {hasActiveFilters
                  ? "Try widening the date range or clearing filters."
                  : "Audit rows appear here as soon as a tracked entity is created, updated, or deleted."}
              </p>
              {hasActiveFilters && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={clearFilters}
                >
                  Clear filters
                </button>
              )}
            </div>
          )}
        </div>

        <div className="pagination">
          <span className="pagination-info">
            {`Page ${page} of ${pageCount} · ${count} total`}
          </span>
          <div className="pagination-controls">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={loading || !previous || page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={loading || !next}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
