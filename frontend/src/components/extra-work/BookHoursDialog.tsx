/**
 * hours2 Part 2 — "Book hours", the job's own door into the hours record.
 *
 *    One record (`TimeEntry`), two doors. The admin week grid is one;
 *    this is the other.
 *
 * On the ticket's Plan tab, beside the planned-vs-worked comparison:
 * pick people FROM THE CREW (several at once), a date, an hour type and
 * a number of hours, and one ordinary `TimeEntry` row lands per person,
 * tagged `source_type=TICKET / source_id=<this ticket>` with the
 * ticket's building prefilled. Nothing here is a second write path:
 * every row goes through `POST /api/timesheets/entries/`, which owns
 * every rule — employee eligibility, the company anchor, the hour
 * type's ownership, and the week lock.
 *
 * ## Why one POST per person, not the bulk-week endpoint
 *
 * `bulk-week` treats a cell as AUTHORITATIVE: a cell addressing an
 * existing (person, day, type, building, job) row REPLACES its hours.
 * That is right for a grid that shows the row first, and wrong for a
 * form that does not — "book 2 more hours" would silently overwrite
 * the 3 already there. The single-entry create ADDS a row, which is
 * what booking means; multiple rows per person per day are allowed and
 * expected by the model.
 *
 * The writes are sequential and stop at the first refusal. Every
 * refusal that can differ per person (eligibility) is checked by the
 * server per row; the one that cannot (a closed week) refuses the FIRST
 * row before anything is written, so a locked week never half-books.
 * If a later row fails, the dialog says how many landed before it.
 *
 * ## Locked weeks
 *
 * The server answers 400 `week_closed` with its own sentence, and that
 * sentence is shown verbatim at the action. The dialog does not pre-ask
 * the lock: the answer would be one more request for a case the write
 * already handles, and a stale "open" would still be refused.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal here (`WeekEntryDialog`). CLAUDE.md's render-unconditionally
 * rule is about the native `<dialog>` element.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { createTimeEntry, listHourTypes } from "../../api/timesheets";
import type { HourType } from "../../api/timesheets.types";
import { ChipMultiSelect } from "../ChipMultiSelect";
import { hourTypeLabel } from "../../lib/hourTypeLabel";
import { toDateString } from "../../lib/isoWeek";

export interface BookHoursCrewMember {
  id: number;
  name: string;
  email?: string;
}

/** The same keystroke rule the week grid's cells apply: two integer
 *  digits, either decimal separator, two decimals. */
const HOURS_INPUT = /^\d{0,2}([.,]\d{0,2})?$/;

function parseHours(raw: string): number | null {
  const cleaned = raw.trim().replace(",", ".");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function BookHoursDialog({
  ticketId,
  ticketNo,
  companyId,
  buildingId,
  crew,
  onClose,
  onBooked,
}: {
  ticketId: number;
  ticketNo: string;
  companyId: number;
  buildingId: number | null;
  /** The ticket's crew — the only people offered. */
  crew: BookHoursCrewMember[];
  onClose: () => void;
  /** Called with how many rows landed. The page refreshes the
   *  comparison and closes this. */
  onBooked: (count: number) => void | Promise<void>;
}) {
  // Bound like every page: the page namespace first, `common` behind
  // it (`nsMode: "fallback"`), so the hour-type slot labels and the
  // shared verbs resolve from common.json.
  const { t } = useTranslation(["ticket_detail", "common"]);

  const [peopleIds, setPeopleIds] = useState<number[]>([]);
  const [date, setDate] = useState(() => toDateString(new Date()));
  const [hourTypeId, setHourTypeId] = useState<number | "">("");
  const [hoursText, setHoursText] = useState("");
  const [hourTypes, setHourTypes] = useState<HourType[] | null>(null);
  const [typesError, setTypesError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [landed, setLanded] = useState(0);

  // The company's ACTIVE hour types. The default is the first one,
  // which for every company that has run the standard set is "Normale
  // uren" — the same seed the week grid opens on.
  useEffect(() => {
    let cancelled = false;
    listHourTypes({ company: companyId, is_active: true })
      .then((types) => {
        if (cancelled) return;
        const active = types.filter((hourType) => hourType.is_active);
        setHourTypes(active);
        if (active.length > 0) {
          setHourTypeId((current) => (current === "" ? active[0].id : current));
        }
      })
      .catch((err) => {
        if (!cancelled) setTypesError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  const hoursValue = parseHours(hoursText);
  const canSubmit =
    !busy &&
    peopleIds.length > 0 &&
    date !== "" &&
    hourTypeId !== "" &&
    hoursValue !== null;

  async function submit() {
    // `canSubmit` is an aliased condition over consts, so TypeScript
    // narrows `hourTypeId` and `hoursValue` through it: past this line
    // the first is a number and the second is not null.
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    setLanded(0);
    let count = 0;
    try {
      for (const employee of peopleIds) {
        await createTimeEntry({
          company: companyId,
          employee,
          date,
          hour_type: hourTypeId,
          hours: hoursValue.toFixed(2),
          building: buildingId,
          source_type: "TICKET",
          source_id: ticketId,
        });
        count += 1;
      }
      await onBooked(count);
    } catch (err) {
      // Verbatim — including the server's own `week_closed` sentence.
      setError(getApiError(err));
      setLanded(count);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("book_hours.title", { ticket: ticketNo })}
      data-testid="ticket-book-hours-dialog"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
        paddingTop: "10vh",
        overflowY: "auto",
      }}
    >
      <div
        className="card book-hours-modal"
        style={{ width: "min(96vw, 560px)", padding: 24 }}
      >
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {t("book_hours.title", { ticket: ticketNo })}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("book_hours.subtitle")}
        </p>

        <div className="field">
          <span className="field-label">{t("book_hours.people_label")}</span>
          <ChipMultiSelect
            options={crew.map((member) => ({
              id: member.id,
              label: member.name,
              sublabel: member.email,
            }))}
            selectedIds={peopleIds}
            onChange={setPeopleIds}
            placeholder={t("book_hours.select_people")}
            removeLabel={(label) => t("book_hours.remove_person", { name: label })}
            emptyText={t("book_hours.no_crew")}
            disabled={busy}
            testIdPrefix="book-hours-people"
          />
        </div>

        <div className="book-hours-row">
          <div className="field">
            <label className="field-label" htmlFor="book-hours-date">
              {t("book_hours.date_label")}
            </label>
            <input
              id="book-hours-date"
              className="field-input"
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              disabled={busy}
              data-testid="book-hours-date"
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="book-hours-type">
              {t("book_hours.hour_type_label")}
            </label>
            <select
              id="book-hours-type"
              className="field-input"
              value={hourTypeId}
              onChange={(event) =>
                setHourTypeId(
                  event.target.value === "" ? "" : Number(event.target.value),
                )
              }
              disabled={busy || hourTypes === null || hourTypes.length === 0}
              data-testid="book-hours-type"
            >
              {hourTypes === null && (
                <option value="">{t("book_hours.types_loading")}</option>
              )}
              {hourTypes !== null && hourTypes.length === 0 && (
                <option value="">{t("book_hours.no_hour_types")}</option>
              )}
              {(hourTypes ?? []).map((hourType) => (
                <option key={hourType.id} value={hourType.id}>
                  {hourTypeLabel(hourType, t)}
                </option>
              ))}
            </select>
            {typesError && <p className="form-error">{typesError}</p>}
          </div>
          <div className="field">
            <label className="field-label" htmlFor="book-hours-hours">
              {t("book_hours.hours_label")}
            </label>
            <input
              id="book-hours-hours"
              className="field-input"
              type="text"
              inputMode="decimal"
              value={hoursText}
              onChange={(event) => {
                // A rejected keystroke leaves the state alone, so the
                // character never lands — the week grid's own rule.
                if (HOURS_INPUT.test(event.target.value)) {
                  setHoursText(event.target.value);
                }
              }}
              placeholder="8"
              disabled={busy}
              data-testid="book-hours-hours"
            />
          </div>
        </div>

        {/* Where the rows go, said once, so nobody wonders whether the
            building or the job has to be typed. */}
        <p className="muted small" style={{ marginTop: 4 }}>
          {peopleIds.length > 0
            ? t("book_hours.summary", {
                count: peopleIds.length,
                ticket: ticketNo,
              })
            : t("book_hours.summary_none", { ticket: ticketNo })}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginTop: 12 }}
            data-testid="book-hours-error"
          >
            {error}
            {landed > 0 && (
              <div className="small" style={{ marginTop: 4 }}>
                {t("book_hours.partial", { count: landed })}
              </div>
            )}
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 16,
          }}
        >
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onClose}
            disabled={busy}
            data-testid="book-hours-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={!canSubmit}
            data-testid="book-hours-submit"
          >
            {busy ? t("book_hours.saving") : t("book_hours.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
