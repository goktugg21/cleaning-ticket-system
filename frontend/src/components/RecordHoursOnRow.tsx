/**
 * W9 — record hours from the row that shows the gap.
 *
 * The owner counted fifteen hops to plan a job and book its hours, and
 * eight of them existed only to enter hours. Every one of those eight
 * asked him for something the screen he came from already knew: which
 * person, which job, which building.
 *
 *     "The backend may be correctly designed and the underlying
 *     relationships may actually be very good, but the frontend is
 *     forcing the user to understand those relationships themselves.
 *     That should not happen."
 *
 * So this asks for the three things nobody can know — the day, how long,
 * and which kind of hour — and nothing else. Person, job and building
 * arrive as props from the row and are never shown as questions.
 *
 * ## It is not a second way to record hours
 *
 * It POSTs to `timesheets/entries/`, the same endpoint the Hours module
 * writes through, with `source_type: "EXTRA_WORK"`. Every rule about
 * who may write for whom, which company the entry lands in, and whether
 * the week is open lives there and is not restated here. This component
 * cannot drift from the Hours module because it IS the Hours module's
 * write path with three fields pre-filled.
 *
 * ## The closed week is answered before it is hit, not after
 *
 * A closed week refuses the write with a 400 whatever the UI does. But
 * "you cannot, and here is who can reopen it" is only useful before
 * somebody types a number, so the week is checked when the date changes
 * and the row says so with the Save disabled.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import {
  createTimeEntry,
  fetchWeekStatus,
  listHourTypes,
} from "../api/timesheets";
import type { HourType } from "../api/timesheets.types";
import { isoWeekOf, fromDateString, toDateString } from "../lib/isoWeek";
import { useToast } from "./ToastProvider";
import { hourTypeLabel } from "../lib/hourTypeLabel";

/** The hour type a day of ordinary work is, when the company has one.
 *  `standard_slot` is stored lower-case (`normal_hours`) — the same
 *  spelling `lib/hourTypeLabel`'s KNOWN_SLOTS uses. Falling back to the
 *  first active type keeps the control usable for a company that has
 *  renamed its way out of the standard set. */
function defaultHourTypeId(types: HourType[]): string {
  const normal = types.find((h) => h.standard_slot === "normal_hours");
  return String((normal ?? types[0])?.id ?? "");
}

export function RecordHoursOnRow({
  employeeId,
  employeeName,
  extraWorkId,
  buildingId,
  companyId,
  onSaved,
  onCancel,
  testId,
}: {
  employeeId: number;
  employeeName: string;
  extraWorkId: number;
  buildingId: number | null;
  companyId: number | null;
  onSaved: () => void;
  onCancel: () => void;
  testId: string;
}) {
  const { t } = useTranslation("common");
  const { push: pushToast } = useToast();

  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  const [date, setDate] = useState(() => toDateString(new Date()));
  const [hours, setHours] = useState("");
  const [hourTypeId, setHourTypeId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  /** Non-null once a week has been checked: true = closed. */
  const [weekClosed, setWeekClosed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listHourTypes({ company: companyId ?? undefined, is_active: true })
      .then((rows) => {
        if (cancelled) return;
        setHourTypes(rows);
        setHourTypeId(defaultHourTypeId(rows));
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const checkWeek = useCallback(
    (value: string) => {
      if (!value) return;
      const week = isoWeekOf(fromDateString(value));
      fetchWeekStatus({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company: companyId ?? undefined,
      })
        .then((status) => setWeekClosed(status.is_closed))
        // A failed check must not block a write the server would accept;
        // the endpoint enforces the lock regardless.
        .catch(() => setWeekClosed(false));
    },
    [companyId],
  );

  useEffect(() => {
    checkWeek(date);
  }, [date, checkWeek]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      await createTimeEntry({
        employee: employeeId,
        date,
        hour_type: Number(hourTypeId),
        hours: hours.trim().replace(",", "."),
        building: buildingId,
        // The whole point: this hour belongs to THIS job, recorded
        // without anybody being asked which job they are looking at.
        source_type: "EXTRA_WORK",
        source_id: extraWorkId,
      });
      pushToast({
        variant: "success",
        // Says what changed and who it changed for. The row underneath
        // then re-reads and its Worked and Difference move, which is
        // the rest of the answer.
        title: t("record_hours.saved", {
          hours: hours.trim().replace(",", "."),
          name: employeeName,
        }),
      });
      onSaved();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const ready =
    hours.trim() !== "" && hourTypeId !== "" && date !== "" && !weekClosed;

  return (
    <div className="pva-record" data-testid={testId}>
      <label className="pva-record-field">
        <span className="pva-record-label">{t("record_hours.date")}</span>
        <input
          type="date"
          className="field-input"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          data-testid={`${testId}-date`}
        />
      </label>
      <label className="pva-record-field">
        <span className="pva-record-label">{t("record_hours.hours")}</span>
        <input
          type="number"
          min="0"
          step="0.25"
          inputMode="decimal"
          className="field-input"
          value={hours}
          onChange={(e) => setHours(e.target.value)}
          data-testid={`${testId}-hours`}
        />
      </label>
      <label className="pva-record-field">
        <span className="pva-record-label">{t("record_hours.hour_type")}</span>
        <select
          className="field-select"
          value={hourTypeId}
          onChange={(e) => setHourTypeId(e.target.value)}
          data-testid={`${testId}-hour-type`}
        >
          {hourTypes.map((type) => (
            <option key={type.id} value={String(type.id)}>
              {hourTypeLabel(type, t)}
            </option>
          ))}
        </select>
      </label>
      <div className="pva-record-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void save()}
          disabled={!ready || saving}
          data-testid={`${testId}-save`}
        >
          {t("record_hours.save")}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onCancel}
          disabled={saving}
          data-testid={`${testId}-cancel`}
        >
          {t("cancel")}
        </button>
      </div>
      {/* The week lock, said on the row before a number is typed, with
          the way out named. */}
      {weekClosed && (
        <p className="pva-record-blocked" data-testid={`${testId}-week-closed`}>
          {t("record_hours.week_closed")}
        </p>
      )}
      {error && (
        <p className="pva-record-error" role="alert" data-testid={`${testId}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}
