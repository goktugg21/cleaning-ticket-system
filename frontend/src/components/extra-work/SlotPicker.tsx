/**
 * W5-B — pick the days and times a series runs on.
 *
 * Each pick becomes ONE real Extra Work. That is stated on the screen,
 * next to the count, because "3 slots" and "3 separate jobs, each with
 * its own price and its own invoice line" are not the same thought and
 * the operator is about to create the second one.
 *
 * TWO WAYS IN, because the two real cases are different shapes:
 *   - ADD ONE — three slots on a handover day, each at its own time.
 *   - REPEAT WEEKLY — every Tuesday for eight weeks, one click.
 * Weekly repeat is the case the reference system's week/day grid exists
 * for, and it is the one that makes a fat-fingered range dangerous, so
 * the count and the ceiling are always on screen.
 *
 * THE CEILING IS SHOWN, NOT JUST ENFORCED. The server refuses more than
 * `MAX_SLOTS` and that refusal is the rule; this control simply will
 * not let the operator build a list it knows will be rejected, and says
 * why while they are still choosing rather than after they submit.
 *
 * NO TIME AND NO CONDITION ARE REAL ANSWERS. Both fields may be left
 * blank and blank is sent as absent, not as midnight and not as "at
 * handover". The reference system collapses the second pair —
 * `match($entry['condition'] ?? 'at')` — so an unanswered slot is
 * indistinguishable from an explicit one forever after.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ExtraWorkCondition, ExtraWorkSlot } from "../../api/types";
import { BoundedList } from "../BoundedList";

/** Mirrors `groups.MAX_BATCH_SLOTS`. The SERVER's value is the rule;
 *  this one keeps the picker from building a list it knows will be
 *  refused. If they ever disagree the server wins and says so. */
export const MAX_SLOTS = 60;

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

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
  const [condition, setCondition] = useState<"" | ExtraWorkCondition>(
    "AT_HANDOVER",
  );
  const [repeats, setRepeats] = useState("8");
  const [error, setError] = useState("");

  function makeSlot(on: string): ExtraWorkSlot {
    const slot: ExtraWorkSlot = { date: on };
    // OMITTED, not defaulted — see the header comment.
    if (time !== "") slot.time = time;
    if (condition !== "") slot.condition = condition;
    return slot;
  }

  function isDuplicate(candidate: ExtraWorkSlot, list: ExtraWorkSlot[]) {
    return list.some(
      (s) => s.date === candidate.date && (s.time ?? "") === (candidate.time ?? ""),
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

  function addWeekly() {
    setError("");
    if (date === "") return;
    const count = Number(repeats);
    if (!Number.isFinite(count) || count < 1) return;
    const next = [...slots];
    for (let i = 0; i < count; i += 1) {
      const candidate = makeSlot(addDays(date, i * 7));
      if (isDuplicate(candidate, next)) continue;
      if (next.length + 1 > MAX_SLOTS) {
        setError(t("series.slot_limit", { limit: MAX_SLOTS }));
        break;
      }
      next.push(candidate);
    }
    onChange(next);
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
        <label className="field">
          <span className="muted small">{t("series.col_condition")}</span>
          <select
            className="field-input"
            value={condition}
            onChange={(e) =>
              setCondition(e.target.value as "" | ExtraWorkCondition)
            }
            data-testid="extra-work-slot-condition"
          >
            <option value="">{t("series.condition_unset")}</option>
            <option value="AT_HANDOVER">{t("series.condition_at")}</option>
            <option value="BEFORE_HANDOVER">
              {t("series.condition_before")}
            </option>
            <option value="AFTER_HANDOVER">{t("series.condition_after")}</option>
          </select>
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

      <div className="ew-slot-controls">
        <label className="field ew-slot-repeat">
          <span className="muted small">{t("series.slot_weeks")}</span>
          <input
            type="number"
            min="1"
            max={String(MAX_SLOTS)}
            className="field-input"
            value={repeats}
            onChange={(e) => setRepeats(e.target.value)}
            data-testid="extra-work-slot-weeks"
          />
        </label>
        <button
          type="button"
          className="btn btn-ghost btn-sm ew-slot-add"
          onClick={addWeekly}
          disabled={date === ""}
          data-testid="extra-work-slot-weekly"
        >
          {t("series.slot_weekly")}
        </button>
        <p className="muted small ew-slot-hint">{t("series.slot_hint")}</p>
      </div>

      {error && (
        <div className="alert-error" role="alert" data-testid="extra-work-slot-error">
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
              <span className="muted small">
                {slot.condition
                  ? t(`series.condition_${CONDITION_KEY[slot.condition]}`)
                  : t("series.condition_unset")}
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

const CONDITION_KEY: Record<ExtraWorkCondition, string> = {
  AT_HANDOVER: "at",
  BEFORE_HANDOVER: "before",
  AFTER_HANDOVER: "after",
};
