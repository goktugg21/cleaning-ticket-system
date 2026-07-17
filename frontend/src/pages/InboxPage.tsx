// RF-1 — WhatsApp-style aggregated message inbox.
//
// A conversation list over ticket + Extra Work threads. Each row shows
// the customer logo (author photo overlaid), title, the last visible
// message's snippet + relative time, an unread badge, and — for provider
// management only — a "who hasn't read" line (the backend omits that
// field entirely for customer viewers). Filters: kind, date range,
// search, unread-only. Clicking a row marks it read and opens the
// thread's detail.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessagesSquare, Search } from "lucide-react";

import { getApiError } from "../api/client";
import {
  listInbox,
  markThreadRead,
  notifyInboxUnreadChanged,
} from "../api/inbox";
import type { InboxRow, InboxThreadKind } from "../api/types";
import { InboxThreadAvatar } from "../components/Avatar";
import { formatRelative, useLocaleCode } from "../lib/intl";

type KindFilter = "all" | InboxThreadKind;

export function InboxPage() {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  const locale = useLocaleCode();

  const [rows, setRows] = useState<InboxRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [kind, setKind] = useState<KindFilter>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");

  // Debounce the search box into `query` (the value the fetch depends on).
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const filters = useMemo(
    () => ({
      kind: kind === "all" ? undefined : kind,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      q: query || undefined,
      unread_only: unreadOnly,
    }),
    [kind, dateFrom, dateTo, query, unreadOnly],
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!cancelled) {
        setLoading(true);
        setError("");
      }
      try {
        const data = await listInbox(filters);
        if (!cancelled) {
          setRows(data.results);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(getApiError(err));
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [filters]);

  async function openThread(row: InboxRow) {
    // Optimistically clear the row's unread badge + refresh the nav badge,
    // then open the detail. The detail page also marks read (idempotent).
    if (row.unread_count > 0) {
      setRows((prev) =>
        prev.map((r) =>
          r.kind === row.kind && r.id === row.id
            ? { ...r, unread_count: 0, unread_by: undefined }
            : r,
        ),
      );
      try {
        await markThreadRead(row.kind, row.id);
        notifyInboxUnreadChanged();
      } catch {
        // Non-fatal — the detail page will mark it read on render.
      }
    }
    navigate(row.kind === "ticket" ? `/tickets/${row.id}` : `/extra-work/${row.id}`);
  }

  return (
    <div className="inbox-page" data-testid="inbox-page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.messages_group")}
          </div>
          <h2 className="page-title">{t("inbox.title")}</h2>
        </div>
      </div>

      <div className="inbox-filters" data-testid="inbox-filters">
        <div className="inbox-kind-toggle" role="group" aria-label={t("inbox.filter_kind")}>
          {(["all", "ticket", "extra_work"] as KindFilter[]).map((k) => (
            <button
              key={k}
              type="button"
              className={`inbox-kind-btn${kind === k ? " active" : ""}`}
              onClick={() => setKind(k)}
              data-testid={`inbox-kind-${k}`}
            >
              {t(`inbox.kind_${k}`)}
            </button>
          ))}
        </div>

        <div className="inbox-search">
          <Search size={15} strokeWidth={2} />
          <input
            type="search"
            className="field-input"
            placeholder={t("inbox.search_placeholder")}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            data-testid="inbox-search"
          />
        </div>

        <label className="inbox-date">
          <span>{t("inbox.date_from")}</span>
          <input
            type="date"
            className="field-input"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            data-testid="inbox-date-from"
          />
        </label>
        <label className="inbox-date">
          <span>{t("inbox.date_to")}</span>
          <input
            type="date"
            className="field-input"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            data-testid="inbox-date-to"
          />
        </label>

        <label className="inbox-unread-toggle">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
            data-testid="inbox-unread-only"
          />
          {t("inbox.unread_only")}
        </label>
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : rows.length === 0 ? (
        <div className="inbox-empty" data-testid="inbox-empty">
          <MessagesSquare size={40} strokeWidth={1.5} />
          <h3>{t("inbox.empty_title")}</h3>
          <p className="muted">{t("inbox.empty_description")}</p>
        </div>
      ) : (
        <ul className="inbox-list" data-testid="inbox-list">
          {rows.map((row) => (
            <InboxRowItem
              key={`${row.kind}-${row.id}`}
              row={row}
              locale={locale}
              onOpen={() => openThread(row)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function InboxRowItem({
  row,
  locale,
  onOpen,
}: {
  row: InboxRow;
  locale: string;
  onOpen: () => void;
}) {
  const { t } = useTranslation("common");
  const last = row.last_message;
  const authorName = last?.author.name ?? null;

  return (
    <li>
      <button
        type="button"
        className={`inbox-row${row.unread_count > 0 ? " unread" : ""}`}
        onClick={onOpen}
        data-testid="inbox-row"
        data-kind={row.kind}
        data-thread-id={row.id}
      >
        <InboxThreadAvatar
          logoUrl={row.customer?.logo_url}
          customerName={row.customer?.name}
          authorPhotoUrl={last?.author.photo_url}
          authorName={authorName}
        />
        <div className="inbox-row-main">
          <div className="inbox-row-top">
            <span className="inbox-row-title">{row.title}</span>
            <span className="inbox-row-time">
              {last ? formatRelative(last.created_at, locale) : ""}
            </span>
          </div>
          <div className="inbox-row-sub">
            <span className={`inbox-kind-tag inbox-kind-tag-${row.kind}`}>
              {t(`inbox.kind_${row.kind}`)}
            </span>
            {row.customer && (
              <span className="inbox-row-customer">{row.customer.name}</span>
            )}
          </div>
          <div className="inbox-row-snippet">
            {authorName && (
              <span className="inbox-row-author">{authorName}: </span>
            )}
            {last?.snippet ?? t("inbox.no_messages")}
          </div>
          {row.unread_by !== undefined && row.unread_by.length > 0 && (
            <div className="inbox-row-receipts" data-testid="inbox-row-receipts">
              {t("inbox.unread_by")}{" "}
              {row.unread_by.map((u) => u.name).join(", ")}
            </div>
          )}
        </div>
        {row.unread_count > 0 && (
          <span className="inbox-row-badge" data-testid="inbox-row-badge">
            {row.unread_count > 99 ? "99+" : row.unread_count}
          </span>
        )}
      </button>
    </li>
  );
}
