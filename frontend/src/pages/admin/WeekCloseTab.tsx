import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  closeWeek,
  fetchWeekStatus,
  listWeekLocks,
  reopenWeek,
} from "../../api/timesheets";
import type { WeekLock, WeekStatus } from "../../api/timesheets.types";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";
import {
  currentIsoWeek,
  formatIsoWeek,
  fromDateString,
  isoWeekDays,
  isoWeekOf,
  shiftIsoWeek,
  toDateString,
} from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";

interface WeekCloseTabProps {
  selectedCompany?: number | "";
}

/**
 * Sprint 152 — "Weken" tab: close and reopen a company-wide week.
 *
 * The state model is the backend's: ABSENCE of a `WeekLock` row means
 * the week is open. So this tab asks about ONE named week
 * (`/weeks/status/`) rather than deriving open/closed from the list of
 * locks — an open week appears in no collection at all, and neither does
 * an empty one.
 *
 * Reopen genuinely DELETES the lock row. That is deliberate and
 * owner-approved (corrections and late sick-leave entries are routine);
 * the AuditLog DELETE entry is the trail. Both actions sit behind a
 * ConfirmDialog because both change what an entire company may write.
 */
export function WeekCloseTab({ selectedCompany = "" }: WeekCloseTabProps) {
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const { push: pushToast } = useToast();

  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  const [status, setStatus] = useState<WeekStatus | null>(null);
  const [locks, setLocks] = useState<WeekLock[]>([]);
  const [loadError, setLoadError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  // Derived `loading` — see `MyHoursPage` for why it is not stored.
  const fetchKey = `${week.isoYear}-W${week.isoWeek}|${selectedCompany}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== fetchKey;

  const closeDialogRef = useRef<ConfirmDialogHandle>(null);
  const reopenDialogRef = useRef<ConfirmDialogHandle>(null);

  const weekDays = useMemo(() => isoWeekDays(week), [week]);
  const rangeLabel = useMemo(() => {
    const options: Intl.DateTimeFormatOptions = {
      day: "2-digit",
      month: "short",
      year: "numeric",
    };
    return `${weekDays[0].toLocaleDateString(dateLocale, options)} – ${weekDays[6].toLocaleDateString(dateLocale, options)}`;
  }, [weekDays, dateLocale]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchWeekStatus({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company: selectedCompany,
      }),
      listWeekLocks({ company: selectedCompany }),
    ])
      .then(([weekStatus, lockRows]) => {
        if (cancelled) return;
        setStatus(weekStatus);
        setLocks(lockRows);
        setLoadError("");
        setLoadedKey(fetchKey);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoadedKey(fetchKey);
      });
    return () => {
      cancelled = true;
    };
  }, [week, selectedCompany, fetchKey]);

  /** Re-read after an action. Never throws — see HourTypesTab.refresh. */
  async function refresh() {
    try {
      const [weekStatus, lockRows] = await Promise.all([
        fetchWeekStatus({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          company: selectedCompany,
        }),
        listWeekLocks({ company: selectedCompany }),
      ]);
      setStatus(weekStatus);
      setLocks(lockRows);
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }

  async function handleConfirmClose() {
    setActionBusy(true);
    try {
      await closeWeek({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company: selectedCompany,
      });
      await refresh();
      closeDialogRef.current?.close();
      pushToast({
        variant: "success",
        title: t("weeks.close_done", { week: formatIsoWeek(week) }),
      });
    } catch (err) {
      setLoadError(getApiError(err));
      closeDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReopen() {
    setActionBusy(true);
    try {
      await reopenWeek({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company: selectedCompany,
      });
      await refresh();
      reopenDialogRef.current?.close();
      pushToast({
        variant: "success",
        title: t("weeks.reopen_done", { week: formatIsoWeek(week) }),
      });
    } catch (err) {
      setLoadError(getApiError(err));
      reopenDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const isClosed = status?.is_closed ?? false;

  return (
    <>
      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      <div className="card" style={{ padding: "18px 22px", marginBottom: 16 }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>
          {t("weeks.picker_title")}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="weeks-prev-week"
            onClick={() => setWeek((current) => shiftIsoWeek(current, -1))}
          >
            {t("my_hours.previous_week")}
          </button>
          <div style={{ minWidth: 210, textAlign: "center" }}>
            <div style={{ fontWeight: 600 }} data-testid="weeks-week-label">
              {formatIsoWeek(week)}
            </div>
            <div className="muted small">{rangeLabel}</div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="weeks-next-week"
            onClick={() => setWeek((current) => shiftIsoWeek(current, 1))}
          >
            {t("my_hours.next_week")}
          </button>
          <div className="field" style={{ margin: 0, minWidth: 180 }}>
            <label className="sr-only" htmlFor="weeks-week-jump">
              {t("my_hours.jump_to_week")}
            </label>
            <input
              id="weeks-week-jump"
              className="field-input"
              type="date"
              data-testid="weeks-week-jump"
              value={toDateString(weekDays[0])}
              onChange={(event) => {
                if (!event.target.value) return;
                setWeek(isoWeekOf(fromDateString(event.target.value)));
              }}
            />
          </div>
        </div>

        <div
          style={{
            marginTop: 16,
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          {/* Existing badge modifiers only — no new CSS. `badge-closed`
              is literally the state it renders; `badge-approved` is the
              green "writes are allowed" one. */}
          <span
            className={isClosed ? "badge badge-closed" : "badge badge-approved"}
            data-testid="weeks-status-badge"
            data-closed={isClosed ? "true" : "false"}
          >
            {loading
              ? t("weeks.status_loading")
              : isClosed
                ? t("weeks.status_closed")
                : t("weeks.status_open")}
          </span>
          {isClosed && status?.lock && (
            <span className="muted small" data-testid="weeks-closed-by">
              {t("weeks.closed_by", {
                name: status.lock.closed_by_name,
                when: new Date(status.lock.closed_at).toLocaleString(
                  dateLocale,
                  {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  },
                ),
              })}
            </span>
          )}
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {isClosed ? (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                data-testid="weeks-reopen-button"
                onClick={() => reopenDialogRef.current?.open()}
                disabled={loading || actionBusy}
              >
                {t("weeks.reopen_button")}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                data-testid="weeks-close-button"
                onClick={() => closeDialogRef.current?.open()}
                disabled={loading || actionBusy}
              >
                {t("weeks.close_button")}
              </button>
            )}
          </div>
        </div>
        <p className="field-hint muted small" style={{ marginTop: 10 }}>
          {t("weeks.picker_hint")}
        </p>
      </div>

      <div className="card" data-testid="weeks-lock-list">
        <BoundedList
          size="md"
          count={locks.length}
          ariaLabel={t("weeks.list_aria")}
          testIdPrefix="weeks-locks"
          className="table-wrap"
          emptyState={
            <div
              style={{ padding: "32px 24px", textAlign: "center" }}
              data-testid="weeks-locks-empty"
            >
              <h3 style={{ marginBottom: 8 }}>{t("weeks.empty_title")}</h3>
              <p className="muted" style={{ margin: 0 }}>
                {t("weeks.empty_description")}
              </p>
            </div>
          }
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("weeks.col_week")}</th>
                <th>{t("weeks.col_company")}</th>
                <th>{t("weeks.col_closed_at")}</th>
                <th>{t("weeks.col_closed_by")}</th>
              </tr>
            </thead>
            <tbody>
              {locks.map((lock) => (
                <tr
                  key={lock.id}
                  data-testid="weeks-lock-row"
                  data-lock-id={lock.id}
                >
                  <td>
                    {formatIsoWeek({
                      isoYear: lock.iso_year,
                      isoWeek: lock.iso_week,
                    })}
                  </td>
                  <td className="muted small">{lock.company_name}</td>
                  <td className="muted small">
                    {new Date(lock.closed_at).toLocaleString(dateLocale, {
                      day: "2-digit",
                      month: "short",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="muted small">{lock.closed_by_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </BoundedList>
      </div>

      <ConfirmDialog
        ref={closeDialogRef}
        title={t("weeks.close_confirm_title", { week: formatIsoWeek(week) })}
        body={t("weeks.close_confirm_body")}
        confirmLabel={t("weeks.close_button")}
        onConfirm={handleConfirmClose}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reopenDialogRef}
        title={t("weeks.reopen_confirm_title", { week: formatIsoWeek(week) })}
        body={t("weeks.reopen_confirm_body")}
        confirmLabel={t("weeks.reopen_button")}
        onConfirm={handleConfirmReopen}
        busy={actionBusy}
        destructive
      />
    </>
  );
}
