/**
 * hours2 Part 2 — "Enter hours worked", the job's own door into the
 * hours record.
 *
 *    One record (`TimeEntry`), two doors. The admin week grid is one;
 *    this is the other.
 *
 * On the ticket's Plan tab, beside the planned-vs-worked comparison:
 * pick people (several at once), a date, an hour type and a number of
 * hours, and one ordinary `TimeEntry` row lands per person, tagged
 * `source_type=TICKET / source_id=<this ticket>` with the ticket's
 * building prefilled. Nothing here is a second write path: every row
 * goes through `POST /api/timesheets/entries/`, which owns every rule
 * — employee eligibility, the company anchor, the hour type's
 * ownership, and the week lock.
 *
 * ## W-HOURS4 Task 3 — who is offered
 *
 * Everyone ASSIGNED to the job: the crew (`ticket.assigned_staff`, the
 * `TicketStaffAssignment` slots) AND the responsible managers
 * (`TicketManagerAssignment`, read through
 * `GET /tickets/<id>/manager-assignments/`). The picker used to offer
 * the crew alone — not by decision but by data shape: the ticket
 * payload carries `assigned_staff` and nothing about managers, so the
 * page handed over the one list it had. The plan meanwhile puts
 * managers on jobs and the comparison beside this door listed them
 * with worked 0,00 — and the one dialog that could change that number
 * could not name them. The write path never had the restriction:
 * BUILDING_MANAGER and COMPANY_ADMIN are provider employees the entry
 * endpoint accepts (`timesheets.scope.PROVIDER_EMPLOYEE_ROLES`).
 *
 * ## W-HOURS4 Task 2 — the button that did nothing
 *
 * Driven on the deployed build, the happy path worked (201, close,
 * toast, refreshed comparison). What DID read as dead was the shape of
 * the form: the submit sat silently disabled until every input was
 * valid, with no sentence saying which one was not — and the person
 * the operator wanted (a planned manager) was not offerable at all, so
 * the button stayed grey for as long as they looked at it. Enter in
 * the hours box did nothing either (no form), and the crew list, which
 * stays open after a pick by design, could float over the actions for
 * a longer crew.
 *
 * So: it IS a form (Enter submits), the button is always pressable
 * when not busy, and pressing it with something missing says what is
 * missing AT THE BUTTON — the same place a server refusal lands. The
 * people list reports its open edge through `usePickerReserve`, and
 * the spacer sits ABOVE the actions row so the buttons are pushed
 * below the open list instead of under it.
 *
 * ## Why one POST per person, not the bulk-week endpoint
 *
 * `bulk-week` treats a cell as AUTHORITATIVE: a cell addressing an
 * existing (person, day, type, building, job) row REPLACES its hours.
 * That is right for a grid that shows the row first, and wrong for a
 * form that does not — "book 2 more hours" would silently overwrite
 * the 3 already there. The single-entry create ADDS a row, which is
 * what entering means; multiple rows per person per day are allowed
 * and expected by the model.
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
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listManagerAssignments } from "../../api/managerAssignments";
import { createTimeEntry, listHourTypes } from "../../api/timesheets";
import type { HourType } from "../../api/timesheets.types";
import { ChipMultiSelect } from "../ChipMultiSelect";
import { hourTypeLabel } from "../../lib/hourTypeLabel";
import { toDateString } from "../../lib/isoWeek";
import { usePickerReserve } from "../../lib/usePickerReserve";

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
  /** The ticket's crew (its staff slots). The responsible managers are
   *  read here and merged in — see the header comment. */
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
  /** Task 3 — the responsible managers, `null` until read. */
  const [managers, setManagers] = useState<BookHoursCrewMember[] | null>(
    null,
  );
  const [managersError, setManagersError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [landed, setLanded] = useState(0);

  // Task 2 — the modal grows to CONTAIN the open people list, and the
  // spacer sits above the actions so they move out from under it.
  const { modalRef, spacerRef, reserve, onPickerOpenChange } =
    usePickerReserve();

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

  // Task 3 — the responsible managers of THIS job. A failure keeps the
  // crew offerable and says the managers could not be read, rather
  // than emptying the picker over a list that half-loaded.
  useEffect(() => {
    let cancelled = false;
    listManagerAssignments(ticketId)
      .then((rows) => {
        if (cancelled) return;
        setManagers(
          rows.map((row) => ({
            id: row.user_id,
            name: row.user_full_name || row.user_email || `#${row.user_id}`,
            email: row.user_email,
          })),
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setManagers([]);
        setManagersError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [ticketId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  /** Everyone assigned: crew first, then the managers, each once. */
  const people = useMemo(() => {
    const seen = new Set<number>();
    const out: BookHoursCrewMember[] = [];
    for (const member of [...crew, ...(managers ?? [])]) {
      if (seen.has(member.id)) continue;
      seen.add(member.id);
      out.push(member);
    }
    return out;
  }, [crew, managers]);

  const hoursValue = parseHours(hoursText);

  async function submit() {
    if (busy) return;
    // Task 2 — refusals AT THE BUTTON, never a silently disabled
    // button. Each one names the input that is missing.
    if (peopleIds.length === 0) {
      setError(t("book_hours.need_people"));
      return;
    }
    if (date === "") {
      setError(t("book_hours.need_date"));
      return;
    }
    if (hourTypeId === "") {
      setError(t("book_hours.need_type"));
      return;
    }
    if (hoursValue === null) {
      setError(t("book_hours.need_hours"));
      return;
    }
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
        ref={modalRef}
        className="card book-hours-modal"
        style={{ width: "min(96vw, 560px)", padding: 24 }}
      >
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {t("book_hours.title", { ticket: ticketNo })}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("book_hours.subtitle")}
        </p>

        {/* Task 2 — a FORM, so Enter in the hours box submits exactly
            as the button does. */}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
          noValidate
          data-testid="book-hours-form"
        >
          <div className="field">
            <span className="field-label">{t("book_hours.people_label")}</span>
            {managers === null ? (
              <p
                className="muted small"
                style={{ margin: 0 }}
                data-testid="book-hours-people-loading"
              >
                {t("book_hours.people_loading")}
              </p>
            ) : (
              <ChipMultiSelect
                options={people.map((member) => ({
                  id: member.id,
                  label: member.name,
                  sublabel: member.email,
                }))}
                selectedIds={peopleIds}
                onChange={setPeopleIds}
                placeholder={t("book_hours.select_people")}
                removeLabel={(label) =>
                  t("book_hours.remove_person", { name: label })
                }
                emptyText={t("book_hours.no_crew")}
                disabled={busy}
                onOpenChange={onPickerOpenChange}
                testIdPrefix="book-hours-people"
              />
            )}
            {managersError && (
              <p
                className="form-error"
                style={{ marginTop: 4 }}
                data-testid="book-hours-managers-error"
              >
                {t("book_hours.managers_error")} {managersError}
              </p>
            )}
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

          {/* Task 2 — `usePickerReserve`'s spacer, placed ABOVE the
              actions on purpose (the hook's own note says "last child"
              because the week dialog only needs the modal to grow):
              the reserve is measured from this element's top, so the
              buttons below it are pushed past the open list's bottom
              edge instead of sitting under it. */}
          <div
            ref={spacerRef}
            style={{ height: reserve }}
            aria-hidden="true"
            data-testid="picker-reserve-spacer"
          />

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
              type="submit"
              className="btn btn-primary"
              disabled={busy}
              data-testid="book-hours-submit"
            >
              {busy ? t("book_hours.saving") : t("book_hours.submit")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
