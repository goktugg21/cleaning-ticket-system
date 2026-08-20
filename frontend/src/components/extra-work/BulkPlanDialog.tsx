/**
 * W3-F / W4-O — plan a selection of works, each with its own values.
 *
 * WHAT CHANGED, AND WHY THE OLD DIALOG COULD NOT DO IT
 * ----------------------------------------------------
 * The first version of this dialog collected ONE budget, ONE window and
 * ONE pair of completion flags and said plainly that they went to every
 * selected work — because that was the only thing the endpoint could
 * do. Two consequences the owner asked us to remove:
 *
 *   * work A could not be given four hours while work B got six; and
 *   * PLANNED HOURS PER PERSON were absent entirely, because the server
 *     validates a distribution against the crew of EACH work and a
 *     shared distribution is only ever valid when the identical crew is
 *     on every selected job. Offering the field then would have
 *     produced a 400 that reads as a bug in the dialog.
 *
 * `POST /api/extra-work/bulk-plan/` now takes `{"items": [...]}` — one
 * plan per work, still ONE transaction and still all-or-nothing, so a
 * partial result is not a state this dialog has to render. Hours are
 * therefore per work and per person, and they are here.
 *
 * SEEDED, NOT BLANK. Every row opens showing what that work plans NOW,
 * from `GET /api/extra-work/bulk-plan/?requests=...` — the whole
 * selection in one request. A blank table over existing plans is not a
 * neutral starting point: the operator cannot tell "no budget" from
 * "the dialog did not load it", and a save would read as a wipe.
 *
 * WHAT IS SENT IS WHAT CHANGED, FIELD BY FIELD, ROW BY ROW
 * --------------------------------------------------------
 * The payload is read by KEY PRESENCE at the far end (absent -> leave
 * exactly as it was), so every field is compared against its own seed
 * and omitted when equal. That is a stronger version of the
 * one-touched-flag-per-switch rule wave 3 landed here, and it is the
 * same defect being guarded: with a single shared "touched" flag,
 * flipping "photo required" also sent `completion_notes_required:
 * false`, which over a batch would clear the notes flag on every
 * selected work in silence. That is the reference system's live bug —
 * 0 of their 78 records carries either flag. Here each switch on each
 * row carries its own seed and its own value, so nothing can ride along
 * with anything else. That was verified by reading the ACTUAL request
 * body off the wire in a browser (flip one switch on one row of three,
 * submit, intercept the POST) rather than by trusting this comment —
 * the numbers are in the W4-O entry of docs/planning/sprint-checklist.md.
 *
 * BLANK IS NOT ZERO. An empty budget cell means "this work has no
 * budget" and sends `null`; `0` means somebody budgeted zero hours.
 * Same for a person's hours: no value is "no line for them", `0` is "on
 * the crew, nothing budgeted yet". Rendering those the same would be
 * the hours version of showing an unpriced job as free.
 *
 * OVERRUN WARNS. IT NEVER BLOCKS. No disabled button, no refused
 * submit, no cap on what can be typed. The reference system built
 * exactly that block — `validateTotalHours()` still sits in their code,
 * uncalled, beside the comment `// Hours validation removed per user
 * request`. Somebody built it and the business had it removed.
 *
 * JSON, never FormData — the endpoint is pinned to `JSONParser` and
 * answers 415, because DRF reads an absent boolean out of form input as
 * `false`, which is the same wipe by another route. With per-work rows
 * there is no form-data spelling of the body at all.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getBulkPlanContext } from "../../api/extraWork";
import { getApiError } from "../../api/client";
import type {
  ExtraWorkBulkPlanContextRow,
  ExtraWorkBulkPlanItem,
  ExtraWorkRequestList,
} from "../../api/types";
import { Toggle } from "../Toggle";
import { BoundedList } from "../BoundedList";

/** One editable row. Mirrors the seed exactly, so "changed" is a
 *  comparison and never a flag somebody has to remember to set. */
interface RowState {
  /** "" is a real value here: no budget on this work. Not zero. */
  budget: string;
  start: string;
  end: string;
  photo: boolean;
  notes: boolean;
  /** user id -> hours as typed. A missing/"" entry is "no line for this
   *  person", which is not the same as "0". */
  hours: Record<number, string>;
}

/** Two decimals, or null for "no value". The ONE comparison used for
 *  every numeric field, so "4" and "4.00" are the same edit and neither
 *  is confused with "". */
function norm(value: string | null | undefined): string | null {
  const raw = (value ?? "").trim();
  if (raw === "") return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return null;
  return parsed.toFixed(2);
}

function seedRow(work: ExtraWorkBulkPlanContextRow): RowState {
  const hours: Record<number, string> = {};
  for (const row of work.planned_hours) {
    hours[row.user_id] = row.hours;
  }
  return {
    budget: work.budget_hours ?? "",
    start: work.provider_planned_date ?? "",
    end: work.provider_planned_end_date ?? "",
    photo: work.file_upload_required,
    notes: work.completion_notes_required,
    hours,
  };
}

/** The distribution this row would send: the ASSIGNED crew only.
 *
 *  The server refuses hours for anybody not currently assigned, so a
 *  line belonging to somebody taken off the job is not re-sendable. It
 *  stays visible in the expander, flagged, with a warning that saving
 *  hours here removes it — the alternative is dropping it silently from
 *  the screen while it still counts in the total, which is exactly the
 *  reference system's §4.4 defect. */
function distribution(
  work: ExtraWorkBulkPlanContextRow,
  state: RowState,
): { user: number; hours: string }[] {
  const out: { user: number; hours: string }[] = [];
  for (const member of work.crew) {
    const value = norm(state.hours[member.user_id]);
    if (value !== null) out.push({ user: member.user_id, hours: value });
  }
  return out;
}

function sameDistribution(
  a: { user: number; hours: string }[],
  b: { user: number; hours: string }[],
): boolean {
  if (a.length !== b.length) return false;
  const left = new Map(a.map((row) => [row.user, row.hours]));
  for (const row of b) {
    if (left.get(row.user) !== row.hours) return false;
  }
  return true;
}

function sumHours(
  work: ExtraWorkBulkPlanContextRow,
  state: RowState,
): number {
  return distribution(work, state).reduce(
    (total, row) => total + Number(row.hours),
    0,
  );
}

/** Frozen empty selection — a stable identity, so the derived `works`
 *  below does not hand the `seeds` memo a new array every render. */
const NO_WORKS: ExtraWorkBulkPlanContextRow[] = [];

/** The three states a bulk switch instruction can be in. `""` — the
 *  default — is "leave every row's own value alone", which a plain
 *  toggle cannot express and which is the whole point. */
type FlagIntent = "" | "yes" | "no";

export function BulkPlanDialog({
  rows,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  /** The selected works, already on screen, so the table has titles to
   *  render while the planning context loads. */
  rows: ExtraWorkRequestList[];
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: (items: ExtraWorkBulkPlanItem[]) => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);

  // A STRING, not an array. `rows` is rebuilt by the parent on every
  // render (it is a `.filter()` of the list), so an array dependency
  // would be a new identity each time and the context fetch would
  // refire on every keystroke the parent re-renders through. The
  // selection's identity is its ids, and a joined string compares by
  // value.
  const idKey = rows.map((row) => row.id).join(",");
  const [fetched, setFetched] = useState<
    ExtraWorkBulkPlanContextRow[] | null
  >(null);
  // DERIVED, not stored. An empty selection has nothing to fetch and so
  // never resolves `fetched`; writing `[]` into state from the effect
  // body to cover that is a synchronous setState in an effect, which is
  // both a render the user pays for and the lint rule CLAUDE.md names.
  // A constant identity so the `seeds` memo below does not recompute on
  // every render.
  const works = fetched ?? (idKey === "" ? NO_WORKS : null);
  const [loadError, setLoadError] = useState("");
  const [state, setState] = useState<Record<number, RowState>>({});
  const [expanded, setExpanded] = useState<number | null>(null);

  // Plan and start are ONE action, as they are in the reference system
  // where the button reads "Start Work". This is the one dialog-level
  // control, defaulted on, and it is materialised into EVERY row — so a
  // row the operator never edited still carries `start`, which is what
  // keeps it from being refused as `nothing_to_plan`.
  const [startWorks, setStartWorks] = useState(true);

  // The fill-down strip. Its own state, never sent: pressing Apply
  // writes these values INTO the rows. Nothing here reaches the wire,
  // because a shared field beside per-work rows would need a precedence
  // rule and the server refuses that mixture outright.
  const [allBudget, setAllBudget] = useState("");
  const [allStart, setAllStart] = useState("");
  const [allEnd, setAllEnd] = useState("");
  const [allPhoto, setAllPhoto] = useState<FlagIntent>("");
  const [allNotes, setAllNotes] = useState<FlagIntent>("");

  useEffect(() => {
    let live = true;
    const ids = idKey
      .split(",")
      .filter((part) => part !== "")
      .map(Number);
    if (ids.length > 0) {
      getBulkPlanContext(ids)
        .then((data) => {
          if (!live) return;
          setFetched(data.works);
          const seeded: Record<number, RowState> = {};
          for (const work of data.works) {
            seeded[work.extra_work] = seedRow(work);
          }
          setState(seeded);
        })
        .catch((err) => {
          if (!live) return;
          setLoadError(getApiError(err));
        });
    }
    return () => {
      live = false;
    };
  }, [idKey]);

  const seeds = useMemo(() => {
    const out: Record<number, RowState> = {};
    for (const work of works ?? []) out[work.extra_work] = seedRow(work);
    return out;
  }, [works]);

  function patch(id: number, change: Partial<RowState>) {
    setState((prev) => ({ ...prev, [id]: { ...prev[id], ...change } }));
  }

  function setPersonHours(id: number, userId: number, value: string) {
    setState((prev) => ({
      ...prev,
      [id]: { ...prev[id], hours: { ...prev[id].hours, [userId]: value } },
    }));
  }

  function applyToAll() {
    setState((prev) => {
      const next: Record<number, RowState> = {};
      for (const work of works ?? []) {
        const row = prev[work.extra_work];
        next[work.extra_work] = {
          ...row,
          // Only NON-EMPTY entries fill down. A blank cell in the strip
          // means "I am not saying anything about this field", not
          // "clear it everywhere" — clearing a field on twelve works is
          // a thing somebody must do deliberately, per row.
          budget: allBudget.trim() === "" ? row.budget : allBudget.trim(),
          start: allStart === "" ? row.start : allStart,
          end: allEnd === "" ? row.end : allEnd,
          photo: allPhoto === "" ? row.photo : allPhoto === "yes",
          notes: allNotes === "" ? row.notes : allNotes === "yes",
        };
      }
      return next;
    });
  }

  /** The payload. Every field compared against its own seed, per row —
   *  see the header comment on why this is the switch-independence rule
   *  rather than a set of touched flags. */
  function buildItems(): ExtraWorkBulkPlanItem[] {
    const items: ExtraWorkBulkPlanItem[] = [];
    for (const work of works ?? []) {
      const id = work.extra_work;
      const row = state[id];
      const seed = seeds[id];
      if (!row || !seed) continue;
      const item: ExtraWorkBulkPlanItem = { request: id };

      if (norm(row.budget) !== norm(seed.budget)) {
        item.budget_hours = row.budget.trim() === "" ? null : norm(row.budget);
      }
      if (row.start !== seed.start) {
        item.provider_planned_date = row.start === "" ? null : row.start;
      }
      if (row.end !== seed.end) {
        item.provider_planned_end_date = row.end === "" ? null : row.end;
      }
      if (row.photo !== seed.photo) item.file_upload_required = row.photo;
      if (row.notes !== seed.notes) item.completion_notes_required = row.notes;

      const next = distribution(work, row);
      if (!sameDistribution(next, distribution(work, seed))) {
        item.planned_hours = next;
      }

      // Always present, so no row is ever refused as `nothing_to_plan`
      // and an untouched row still starts — which is exactly what bulk
      // plan did before per-work values existed.
      item.start = startWorks;
      items.push(item);
    }
    return items;
  }

  // Plain call, not a memo. It walks the selection once per render and
  // the selection is bounded by the table above it; a memo here would
  // need a dependency list that repeats what `buildItems` already
  // reads, and getting that list wrong is how a dialog starts sending
  // yesterday's values. An item carries `request` and `start` even when
  // nothing changed, so "more than two keys" is "this row has an edit".
  const changedCount = buildItems().filter(
    (item) => Object.keys(item).length > 2,
  ).length;

  const loading = works === null && loadError === "";
  const nothingToSend =
    loading || loadError !== "" || (changedCount === 0 && !startWorks);

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("plan.bulk_title")}
      data-testid="extra-work-bulk-plan-dialog"
    >
      <div className="card ew-plan-dialog ew-plan-dialog-wide">
        <h3 className="section-title ew-plan-dialog-title">
          {t("plan.bulk_title")}
        </h3>
        {/* The one-line statement of what is about to happen to how
            many things. Never omit it. */}
        <p
          className="muted small ew-plan-dialog-sub"
          data-testid="extra-work-bulk-plan-summary"
        >
          {t("plan.bulk_summary_per_work", { count: rows.length })}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-bulk-plan-error"
          >
            {error}
          </div>
        )}
        {loadError && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-bulk-plan-load-error"
          >
            {t("plan.bulk_load_failed")} {loadError}
          </div>
        )}

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            {t("plan.bulk_apply_all_title")}
          </div>
          <p className="muted small ew-plan-section-hint">
            {t("plan.bulk_apply_all_hint")}
          </p>
          <div className="ew-bulk-plan-fill">
            <label className="field">
              <span className="muted small">{t("plan.bulk_col_budget")}</span>
              <input
                type="number"
                min="0"
                step="0.25"
                inputMode="decimal"
                className="field-input"
                value={allBudget}
                onChange={(e) => setAllBudget(e.target.value)}
                data-testid="extra-work-bulk-plan-fill-budget"
              />
            </label>
            <label className="field">
              <span className="muted small">{t("plan.our_start_label")}</span>
              <input
                type="date"
                className="field-input"
                value={allStart}
                onChange={(e) => setAllStart(e.target.value)}
                data-testid="extra-work-bulk-plan-fill-start"
              />
            </label>
            <label className="field">
              <span className="muted small">{t("plan.our_end_label")}</span>
              <input
                type="date"
                className="field-input"
                value={allEnd}
                onChange={(e) => setAllEnd(e.target.value)}
                data-testid="extra-work-bulk-plan-fill-end"
              />
            </label>
            {/* A SELECT, not a toggle, and deliberately: a bulk
                instruction about a boolean has THREE states and "leave
                every row alone" is the default one. A toggle can only
                say yes or no, which is how a control that nobody moved
                ends up writing `false` everywhere. */}
            <label className="field">
              <span className="muted small">{t("plan.bulk_col_photo")}</span>
              <select
                className="field-input"
                value={allPhoto}
                onChange={(e) => setAllPhoto(e.target.value as FlagIntent)}
                data-testid="extra-work-bulk-plan-fill-photo"
              >
                <option value="">{t("plan.bulk_flag_leave")}</option>
                <option value="yes">{t("plan.bulk_flag_yes")}</option>
                <option value="no">{t("plan.bulk_flag_no")}</option>
              </select>
            </label>
            <label className="field">
              <span className="muted small">{t("plan.bulk_col_notes")}</span>
              <select
                className="field-input"
                value={allNotes}
                onChange={(e) => setAllNotes(e.target.value as FlagIntent)}
                data-testid="extra-work-bulk-plan-fill-notes"
              >
                <option value="">{t("plan.bulk_flag_leave")}</option>
                <option value="yes">{t("plan.bulk_flag_yes")}</option>
                <option value="no">{t("plan.bulk_flag_no")}</option>
              </select>
            </label>
            <button
              type="button"
              className="btn btn-ghost btn-sm ew-bulk-plan-fill-apply"
              onClick={applyToAll}
              disabled={loading || busy}
              data-testid="extra-work-bulk-plan-fill-apply"
            >
              {t("plan.bulk_apply_all_button")}
            </button>
          </div>
        </div>

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            {t("plan.bulk_table_title")}
          </div>
          {loading && (
            <p className="muted small" data-testid="extra-work-bulk-plan-loading">
              {t("plan.bulk_loading")}
            </p>
          )}
          {/* Bounded — a selection can be the whole page of results, and
              CLAUDE.md's no-unbounded-server-list rule points at exactly
              this primitive. `table-wrap` layers the horizontal scroll
              the seven columns need on narrow screens; the work column
              is sticky so a scrolled row is still identifiable. */}
          <BoundedList
            size="lg"
            count={(works ?? []).length}
            ariaLabel={t("plan.bulk_table_title")}
            testIdPrefix="extra-work-bulk-plan-rows"
            className="table-wrap"
          >
            <table className="data-table ew-bulk-plan-table">
              <thead>
                <tr>
                  <th className="ew-bulk-plan-work-col">
                    {t("plan.bulk_col_work")}
                  </th>
                  <th>{t("plan.bulk_col_budget")}</th>
                  <th>{t("plan.our_start_label")}</th>
                  <th>{t("plan.our_end_label")}</th>
                  <th>{t("plan.bulk_col_photo")}</th>
                  <th>{t("plan.bulk_col_notes")}</th>
                  <th>{t("plan.bulk_col_hours")}</th>
                </tr>
              </thead>
              <tbody>
                {(works ?? []).map((work) => {
                  const row = state[work.extra_work];
                  if (!row) return null;
                  const budget = norm(row.budget);
                  const distributed = sumHours(work, row);
                  const over =
                    budget !== null && distributed > Number(budget)
                      ? distributed - Number(budget)
                      : 0;
                  const stale = work.planned_hours.filter(
                    (line) => !line.is_assigned,
                  );
                  const isOpen = expanded === work.extra_work;
                  return [
                    <tr
                      key={work.extra_work}
                      data-testid="extra-work-bulk-plan-row"
                      data-extra-work={work.extra_work}
                    >
                      <td className="ew-bulk-plan-work-col">
                        <div className="ew-bulk-plan-work-title">
                          {work.title}
                        </div>
                        <div className="muted small">{work.building_name}</div>
                        {/* What the CUSTOMER asked for. A plan never
                            writes it, and committing a window without
                            seeing the deadline it is measured against is
                            planning blind. */}
                        {work.deadline && (
                          <div
                            className="muted small"
                            data-testid="extra-work-bulk-plan-deadline"
                          >
                            {t("plan.customer_deadline", {
                              date: work.deadline,
                            })}
                          </div>
                        )}
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="0.25"
                          inputMode="decimal"
                          className="field-input ew-bulk-plan-num"
                          value={row.budget}
                          aria-label={`${t("plan.bulk_col_budget")} — ${work.title}`}
                          onChange={(e) =>
                            patch(work.extra_work, { budget: e.target.value })
                          }
                          data-testid="extra-work-bulk-plan-budget"
                        />
                      </td>
                      <td>
                        <input
                          type="date"
                          className="field-input ew-bulk-plan-date"
                          value={row.start}
                          aria-label={`${t("plan.our_start_label")} — ${work.title}`}
                          onChange={(e) =>
                            patch(work.extra_work, { start: e.target.value })
                          }
                          data-testid="extra-work-bulk-plan-start"
                        />
                      </td>
                      <td>
                        <input
                          type="date"
                          className="field-input ew-bulk-plan-date"
                          value={row.end}
                          aria-label={`${t("plan.our_end_label")} — ${work.title}`}
                          onChange={(e) =>
                            patch(work.extra_work, { end: e.target.value })
                          }
                          data-testid="extra-work-bulk-plan-end"
                        />
                      </td>
                      <td>
                        {/* WRAPPED IN A LABEL, and it is not decoration.
                            `.toggle-switch input` is `opacity: 0; width:
                            0; height: 0`, so the only thing a mouse can
                            reach is the slider SPAN beside it — and a
                            span is not a control. Without this label the
                            switch renders perfectly and does nothing,
                            which measuring caught and reading would not
                            have: Playwright refused the click with
                            "element is outside of the viewport", because
                            the real input is a zero-size box. The
                            component's own docstring says to render it
                            inside or next to a <label>; the row cells
                            have no caption text to be that label, so the
                            label IS the cell's click target.

                            Seeded from THIS work, and compared against
                            THIS work's seed on submit — which is why one
                            switch can never send the other's value. */}
                        <label className="ew-bulk-plan-switch">
                          <Toggle
                            checked={row.photo}
                            aria-label={`${t("plan.photo_required_label")} — ${work.title}`}
                            onChange={(e) =>
                              patch(work.extra_work, {
                                photo: e.target.checked,
                              })
                            }
                            data-testid="extra-work-bulk-plan-photo-required"
                          />
                        </label>
                      </td>
                      <td>
                        <label className="ew-bulk-plan-switch">
                          <Toggle
                            checked={row.notes}
                            aria-label={`${t("plan.notes_required_label")} — ${work.title}`}
                            onChange={(e) =>
                              patch(work.extra_work, {
                                notes: e.target.checked,
                              })
                            }
                            data-testid="extra-work-bulk-plan-notes-required"
                          />
                        </label>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm ew-bulk-plan-hours-btn"
                          aria-expanded={isOpen}
                          onClick={() =>
                            setExpanded(isOpen ? null : work.extra_work)
                          }
                          data-testid="extra-work-bulk-plan-hours-toggle"
                        >
                          {work.crew.length === 0
                            ? t("plan.bulk_hours_no_crew")
                            : t("plan.bulk_hours_summary", {
                                people: work.crew.length,
                                hours: distributed.toFixed(2),
                              })}
                        </button>
                        {over > 0 && (
                          <div
                            className="ew-bulk-plan-overrun"
                            data-testid="extra-work-bulk-plan-overrun"
                          >
                            {/* WARNS. Never blocks — nothing here
                                disables the submit button or caps what
                                can be typed. */}
                            {t("plan.overrun_title", {
                              over: over.toFixed(2),
                            })}
                          </div>
                        )}
                      </td>
                    </tr>,
                    isOpen ? (
                      <tr
                        key={`${work.extra_work}-hours`}
                        data-testid="extra-work-bulk-plan-hours-panel"
                        data-extra-work={work.extra_work}
                      >
                        <td colSpan={7} className="ew-bulk-plan-hours-cell">
                          {work.crew.length === 0 ? (
                            <p className="muted small">
                              {t("plan.no_crew_hint")}
                            </p>
                          ) : (
                            <ul className="ew-bulk-plan-crew">
                              {work.crew.map((member) => (
                                <li
                                  key={member.user_id}
                                  className="ew-bulk-plan-crew-row"
                                  data-testid="extra-work-bulk-plan-crew-row"
                                  data-user-id={member.user_id}
                                >
                                  <span className="ew-bulk-plan-crew-name">
                                    {member.user_full_name || member.user_email}
                                  </span>
                                  <input
                                    type="number"
                                    min="0"
                                    step="0.25"
                                    inputMode="decimal"
                                    className="field-input ew-bulk-plan-num"
                                    value={row.hours[member.user_id] ?? ""}
                                    aria-label={t("plan.hours_for", {
                                      name:
                                        member.user_full_name ||
                                        member.user_email,
                                    })}
                                    onChange={(e) =>
                                      setPersonHours(
                                        work.extra_work,
                                        member.user_id,
                                        e.target.value,
                                      )
                                    }
                                    data-testid="extra-work-bulk-plan-person-hours"
                                  />
                                </li>
                              ))}
                            </ul>
                          )}
                          {/* A line belonging to somebody taken off the
                              job cannot be re-sent (the server refuses
                              hours for anyone not assigned), so it is
                              shown and explained rather than dropped
                              from the screen while still counting. */}
                          {stale.length > 0 && (
                            <p
                              className="ew-bulk-plan-stale"
                              data-testid="extra-work-bulk-plan-stale"
                            >
                              {t("plan.bulk_hours_stale", {
                                count: stale.length,
                              })}
                            </p>
                          )}
                        </td>
                      </tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </BoundedList>
        </div>

        <div className="ew-plan-section">
          <label className="ew-plan-switch">
            <Toggle
              checked={startWorks}
              onChange={(e) => setStartWorks(e.target.checked)}
              data-testid="extra-work-bulk-plan-start-works"
            />
            <span>{t("plan.bulk_start_all_label")}</span>
          </label>
          <p className="muted small ew-plan-section-hint">
            {t("plan.bulk_start_all_hint")}
          </p>
          <p className="muted small ew-plan-section-hint">
            {t("plan.bulk_unchanged_hint")}
          </p>
        </div>

        <div className="ew-plan-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid="extra-work-bulk-plan-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            /* Disabled ONLY while the table has nothing loaded, or when
               there is literally nothing to write. NEVER for an overrun
               — see the header comment for the evidence behind that. */
            disabled={busy || nothingToSend}
            title={nothingToSend ? t("plan.bulk_nothing_to_send") : undefined}
            onClick={() => onConfirm(buildItems())}
            data-testid="extra-work-bulk-plan-confirm"
          >
            {busy ? t("plan.submitting") : t("plan.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}
