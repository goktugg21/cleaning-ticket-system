/**
 * W5-B / W-EW4 §1 — pick the days a series runs on.
 *
 * Each pick becomes ONE real Extra Work. That is stated on the screen,
 * next to the count, because "3 slots" and "3 separate jobs, each with
 * its own price and its own invoice line" are not the same thought and
 * the operator is about to create the second one.
 *
 * W-EW4 §1 — WHAT THIS CONTROL DELIBERATELY NO LONGER DOES.
 *
 * It used to offer "Repeat weekly" over "Number of weeks", which is a
 * schedule. A schedule that runs every week until somebody stops it is
 * Recurring Work — a different feature, with its own page, its own
 * template and its own generated executions. Having both meant one
 * question ("this happens every week") had two answers on two screens
 * that behave differently afterwards. The weekly repeat is gone; when
 * enough days pile up to suggest a schedule, the list says so once and
 * points at the page that actually models it.
 *
 * It also offered a "Moment" column — at / before / after handover.
 * That concept was taken out of this product's UI months ago and
 * reappeared here. The COLUMN on the model is untouched and still
 * nullable; this control simply stops sending the field, which the
 * batch endpoint already treats as a real answer (see
 * `extra_work/views_groups.py::_SlotSerializer` — `required=False`,
 * and `groups.create_batch` reads it with `slot.get("condition")`).
 * A slot with no condition is not "at handover"; it is a slot nobody
 * was asked about, and it now stays that way instead of being
 * defaulted to AT_HANDOVER by a select nobody wanted.
 *
 * THE CEILING IS SHOWN, NOT JUST ENFORCED. The server refuses more than
 * `MAX_SLOTS` and that refusal is the rule; this control simply will
 * not let the operator build a list it knows will be rejected, and says
 * why while they are still choosing rather than after they submit.
 *
 * NO TIME IS A REAL ANSWER. The time may be left blank and blank is
 * sent as absent, not as midnight.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { ExtraWorkSlot } from "../../api/types";
import { BoundedList } from "../BoundedList";

/** Mirrors `groups.MAX_BATCH_SLOTS`. The SERVER's value is the rule;
 *  this one keeps the picker from building a list it knows will be
 *  refused. If they ever disagree the server wins and says so. */
export const MAX_SLOTS = 60;

/** W-EW4 §1 — how many days it takes before "is this actually a
 *  schedule?" is worth asking out loud. Four is the first count that
 *  cannot be read as "a couple of visits this month". */
const RECURRING_HINT_AT = 4;

export function SlotPicker({
  slots,
  onChange,
}: {
  slots: ExtraWorkSlot[];
  onChange: (next: ExtraWorkSlot[]) => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);

  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [error, setError] = useState("");

  function makeSlot(on: string): ExtraWorkSlot {
    const slot: ExtraWorkSlot = { date: on };
    // OMITTED, not defaulted — see the header comment. `condition` is
    // never set here at all any more.
    if (time !== "") slot.time = time;
    return slot;
  }

  function isDuplicate(candidate: ExtraWorkSlot, list: ExtraWorkSlot[]) {
    return list.some(
      (s) =>
        s.date === candidate.date && (s.time ?? "") === (candidate.time ?? ""),
    );
  }

  function addOne() {
    setError("");
    if (date === "") return;
    const candidate = makeSlot(date);
    if (isDuplicate(candidate, slots)) {
      setError(t("series.slot_duplicate"));
      return;
    }
    if (slots.length + 1 > MAX_SLOTS) {
      setError(t("series.slot_limit", { limit: MAX_SLOTS }));
      return;
    }
    onChange([...slots, candidate]);
  }

  const sorted = [...slots].sort((a, b) =>
    `${a.date}${a.time ?? ""}`.localeCompare(`${b.date}${b.time ?? ""}`),
  );

  return (
    <div className="ew-slot-picker" data-testid="extra-work-slot-picker">
      <div className="ew-slot-controls">
        <label className="field">
          <span className="muted small">{t("series.slot_date")}</span>
          <input
            type="date"
            className="field-input"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            data-testid="extra-work-slot-date"
          />
        </label>
        <label className="field">
          <span className="muted small">{t("series.slot_time")}</span>
          <input
            type="time"
            className="field-input"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            data-testid="extra-work-slot-time"
          />
        </label>
        <button
          type="button"
          className="btn btn-secondary btn-sm ew-slot-add"
          onClick={addOne}
          disabled={date === ""}
          data-testid="extra-work-slot-add"
        >
          {t("series.slot_add")}
        </button>
      </div>

      {error && (
        <div
          className="alert-error"
          role="alert"
          data-testid="extra-work-slot-error"
        >
          {error}
        </div>
      )}

      {/* The count, and what it MEANS. "3 slots" and "3 separate jobs
          each with its own invoice" are different thoughts. */}
      <p className="ew-slot-count" data-testid="extra-work-slot-count">
        <strong>{t("series.slot_count", { count: slots.length })}</strong>{" "}
        <span className="muted small">
          {t("series.slot_ceiling", { limit: MAX_SLOTS })}
        </span>
      </p>

      {/* W-EW4 §1 — ONE LINE, and only once the list has grown enough to
          make the question real. Not a warning and not a block: picking
          six days on purpose is legitimate. It names the other feature
          and links straight to it, because "you may be on the wrong
          screen" is only useful with the right screen attached. */}
      {slots.length >= RECURRING_HINT_AT && (
        <p
          className="muted small"
          role="status"
          data-testid="extra-work-slot-recurring-hint"
        >
          {t("series.recurring_nudge")}{" "}
          {/* `.link` on purpose. Inside a `muted small` paragraph an
              unclassed <Link> inherits the paragraph's own colour and
              carries no underline — measured #5A6B61 against #5A6B61,
              `text-decoration: none` — so the one word that is supposed
              to take you to the other feature looked exactly like the
              sentence around it. A pointer cursor on hover is not an
              affordance; you have to already know it is there. */}
          <Link className="link" to="/planned-work/new">
            {t("series.recurring_nudge_link")}
          </Link>
        </p>
      )}

      <BoundedList
        size="sm"
        count={sorted.length}
        ariaLabel={t("series.slot_list")}
        testIdPrefix="extra-work-slot-list"
      >
        <ul className="ew-slot-list">
          {sorted.map((slot) => (
            <li
              key={`${slot.date}-${slot.time ?? ""}`}
              className="ew-slot-item"
              data-testid="extra-work-slot-item"
            >
              <span>{slot.date}</span>
              <span className="muted small">
                {slot.time ?? t("series.slot_no_time")}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() =>
                  onChange(
                    slots.filter(
                      (s) =>
                        !(
                          s.date === slot.date &&
                          (s.time ?? "") === (slot.time ?? "")
                        ),
                    ),
                  )
                }
                data-testid="extra-work-slot-remove"
              >
                {t("series.slot_remove")}
              </button>
            </li>
          ))}
        </ul>
      </BoundedList>
    </div>
  );
}
