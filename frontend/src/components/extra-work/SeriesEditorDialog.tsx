/**
 * W5-B — edit a day-by-day series: one value across every member, with
 * per-row override.
 *
 * WHAT THIS DIALOG OWNS, AND WHAT IT DELIBERATELY DOES NOT
 * --------------------------------------------------------
 * It owns the three things about a member that are neither a workflow
 * transition nor a planning value: the TITLE, the TIME OF DAY and the
 * CONDITION (at / before / after handover).
 *
 * It does NOT own the planned date, the budget hours or the assigned
 * people, and that is the point rather than an omission. Those already
 * have per-work endpoints — `bulk-plan` since W4-O and `bulk-assign` —
 * and routing them through a series-shaped endpoint would be a third
 * planning path, which is exactly how a completion flag ends up
 * silently cleared on a whole batch. The footer says so out loud and
 * points at the buttons that do own them, because a control that is
 * absent without explanation reads as a missing feature.
 *
 * It does NOT offer "set the status of every member". The reference
 * system does, and its endpoint is a query-builder mass update that
 * "bypasses Eloquent events entirely: no `*_by` stamp, no `*_at` stamp,
 * no system comment, no broadcast, no FCM, no activity row, no draft
 * publication". Live group 17 shows the result: eight members sitting
 * in the invoicing pool with `approved_at` null, having skipped
 * approval altogether. A status change here is a transition, one work
 * at a time, through the state machine.
 *
 * APPLY-TO-ALL FILLS THE ROWS; IT NEVER BECOMES A SHARED FIELD
 * ------------------------------------------------------------
 * Pressing Apply writes the chosen value INTO every row, where it can
 * still be changed one by one before saving. Nothing about "I applied
 * this to all" reaches the wire — the request is always a list of
 * per-member rows. That keeps one meaning for one payload and matches
 * what W4-O's bulk plan dialog does.
 *
 * WHAT IS SENT IS WHAT CHANGED, per row and per field, compared against
 * the value the server gave us. A field nobody touched is omitted, and
 * the server reads the payload by key presence, so an untouched
 * condition cannot be cleared by a save that was about something else.
 *
 * THE TITLE IS COMPOSED, NEVER PARSED. "Rebuild titles from the slot"
 * asks the SERVER to recompose each title from that member's own
 * columns. Nothing here reads a title to work out what its slot was —
 * see `groups.py` for the two separate ways the reference system pays
 * for doing exactly that.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  getExtraWorkGroup,
  updateExtraWorkGroupMembers,
} from "../../api/extraWork";
import type {
  ExtraWorkCondition,
  ExtraWorkGroupMember,
  ExtraWorkGroupMemberEdit,
} from "../../api/types";
import { BoundedList } from "../BoundedList";
import { StatusBadge } from "../StatusBadge";

/** `HH:MM:SS` from the API, `HH:MM` in an `<input type="time">`. */
function toInputTime(value: string | null): string {
  if (!value) return "";
  return value.slice(0, 5);
}

interface RowState {
  title: string;
  /** "" is a real value: no time given. Not midnight. */
  time: string;
  /** "" is a real value: nobody was asked. Not "at handover". */
  condition: "" | ExtraWorkCondition;
}

function seedRow(member: ExtraWorkGroupMember): RowState {
  return {
    title: member.title,
    time: toInputTime(member.scheduled_time),
    condition: member.condition ?? "",
  };
}

export function SeriesEditorDialog({
  groupId,
  onClose,
  onSaved,
}: {
  groupId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);

  const [members, setMembers] = useState<ExtraWorkGroupMember[] | null>(null);
  const [standardTitle, setStandardTitle] = useState("");
  const [state, setState] = useState<Record<number, RowState>>({});
  const [seeds, setSeeds] = useState<Record<number, RowState>>({});
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [busy, setBusy] = useState(false);

  // The fill-down strip. Never sent — pressing Apply writes these into
  // the rows. "" means "I am not saying anything about this field",
  // which is why the condition control is a select with a leave-alone
  // option rather than a set of buttons.
  const [allTime, setAllTime] = useState("");
  const [allCondition, setAllCondition] = useState<"" | ExtraWorkCondition>("");
  const [regenerate, setRegenerate] = useState(false);

  useEffect(() => {
    let live = true;
    getExtraWorkGroup(groupId)
      .then((data) => {
        if (!live) return;
        setMembers(data.members);
        setStandardTitle(data.group.standard_title);
        const seeded: Record<number, RowState> = {};
        for (const member of data.members) {
          seeded[member.extra_work] = seedRow(member);
        }
        setState(seeded);
        setSeeds(seeded);
      })
      .catch((err) => {
        if (!live) return;
        setLoadError(getApiError(err));
      });
    return () => {
      live = false;
    };
  }, [groupId]);

  function patch(id: number, change: Partial<RowState>) {
    setState((prev) => ({ ...prev, [id]: { ...prev[id], ...change } }));
  }

  function applyToAll() {
    setState((prev) => {
      const next: Record<number, RowState> = {};
      for (const member of members ?? []) {
        const row = prev[member.extra_work];
        next[member.extra_work] = {
          ...row,
          // Only a non-empty entry fills down. A blank strip field means
          // "not saying anything", never "clear it on every member" —
          // clearing a value across a whole series is something somebody
          // must do deliberately, row by row.
          time: allTime === "" ? row.time : allTime,
          condition: allCondition === "" ? row.condition : allCondition,
        };
      }
      return next;
    });
  }

  /** Per row, per field, compared against what the server gave us. */
  function buildEdits(): ExtraWorkGroupMemberEdit[] {
    const edits: ExtraWorkGroupMemberEdit[] = [];
    for (const member of members ?? []) {
      const id = member.extra_work;
      const row = state[id];
      const seed = seeds[id];
      if (!row || !seed) continue;
      const edit: ExtraWorkGroupMemberEdit = { extra_work: id };
      let touched = false;

      if (row.title !== seed.title) {
        edit.title = row.title;
        touched = true;
      }
      if (row.time !== seed.time) {
        edit.scheduled_time = row.time === "" ? null : row.time;
        touched = true;
      }
      if (row.condition !== seed.condition) {
        edit.condition = row.condition === "" ? null : row.condition;
        touched = true;
      }
      if (regenerate) {
        edit.regenerate_title = true;
        touched = true;
      }
      if (touched) edits.push(edit);
    }
    return edits;
  }

  async function save() {
    const edits = buildEdits();
    if (edits.length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    setSaveError("");
    try {
      await updateExtraWorkGroupMembers(groupId, edits);
      onSaved();
    } catch (err) {
      setSaveError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const loading = members === null && loadError === "";
  const changed = buildEdits().length;

  return (
    <div
      className="ew-plan-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t("series.editor_title")}
      data-testid="extra-work-series-editor"
    >
      <div className="card ew-plan-dialog ew-plan-dialog-wide">
        <h3 className="section-title ew-plan-dialog-title">
          {t("series.editor_title")}
        </h3>
        <p className="muted small ew-plan-dialog-sub">
          {standardTitle}
        </p>

        {loadError && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-series-load-error"
          >
            {loadError}
          </div>
        )}
        {saveError && (
          <div
            className="alert-error"
            role="alert"
            data-testid="extra-work-series-save-error"
          >
            {saveError}
          </div>
        )}
        {loading && (
          <p className="muted small" data-testid="extra-work-series-loading">
            {t("series.loading")}
          </p>
        )}

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">
            {t("series.apply_all_title")}
          </div>
          <p className="muted small ew-plan-section-hint">
            {t("series.apply_all_hint")}
          </p>
          <div className="ew-bulk-plan-fill">
            <label className="field">
              <span className="muted small">{t("series.col_time")}</span>
              <input
                type="time"
                className="field-input"
                value={allTime}
                onChange={(e) => setAllTime(e.target.value)}
                data-testid="extra-work-series-fill-time"
              />
            </label>
            <label className="field">
              <span className="muted small">{t("series.col_condition")}</span>
              <select
                className="field-input"
                value={allCondition}
                onChange={(e) =>
                  setAllCondition(e.target.value as "" | ExtraWorkCondition)
                }
                data-testid="extra-work-series-fill-condition"
              >
                <option value="">{t("series.condition_leave")}</option>
                <option value="AT_HANDOVER">{t("series.condition_at")}</option>
                <option value="BEFORE_HANDOVER">
                  {t("series.condition_before")}
                </option>
                <option value="AFTER_HANDOVER">
                  {t("series.condition_after")}
                </option>
              </select>
            </label>
            <button
              type="button"
              className="btn btn-ghost btn-sm ew-bulk-plan-fill-apply"
              onClick={applyToAll}
              disabled={loading || busy}
              data-testid="extra-work-series-fill-apply"
            >
              {t("series.apply_all_button")}
            </button>
          </div>
        </div>

        <div className="ew-plan-section">
          <div className="ew-plan-section-title">{t("series.rows_title")}</div>
          <BoundedList
            size="lg"
            count={(members ?? []).length}
            ariaLabel={t("series.rows_title")}
            testIdPrefix="extra-work-series-rows"
            className="table-wrap"
          >
            <table className="data-table ew-series-table">
              <thead>
                <tr>
                  <th>{t("series.col_when")}</th>
                  <th>{t("series.col_title")}</th>
                  <th>{t("series.col_time")}</th>
                  <th>{t("series.col_condition")}</th>
                  <th>{t("series.col_status")}</th>
                </tr>
              </thead>
              <tbody>
                {(members ?? []).map((member) => {
                  const row = state[member.extra_work];
                  if (!row) return null;
                  return (
                    <tr
                      key={member.extra_work}
                      data-testid="extra-work-series-row"
                      data-extra-work={member.extra_work}
                    >
                      <td className="ew-series-when">
                        {member.preferred_date ?? "-"}
                      </td>
                      <td>
                        <input
                          type="text"
                          className="field-input"
                          value={row.title}
                          aria-label={`${t("series.col_title")} ${member.extra_work}`}
                          onChange={(e) =>
                            patch(member.extra_work, { title: e.target.value })
                          }
                          data-testid="extra-work-series-title"
                        />
                      </td>
                      <td>
                        <input
                          type="time"
                          className="field-input ew-series-time"
                          value={row.time}
                          aria-label={`${t("series.col_time")} ${member.extra_work}`}
                          onChange={(e) =>
                            patch(member.extra_work, { time: e.target.value })
                          }
                          data-testid="extra-work-series-time"
                        />
                      </td>
                      <td>
                        <select
                          className="field-input"
                          value={row.condition}
                          aria-label={`${t("series.col_condition")} ${member.extra_work}`}
                          onChange={(e) =>
                            patch(member.extra_work, {
                              condition: e.target.value as
                                | ""
                                | ExtraWorkCondition,
                            })
                          }
                          data-testid="extra-work-series-condition"
                        >
                          {/* "Not specified" is a REAL option, not a
                              placeholder. The reference system cannot
                              express it and defaults everything to "at
                              handover". */}
                          <option value="">
                            {t("series.condition_unset")}
                          </option>
                          <option value="AT_HANDOVER">
                            {t("series.condition_at")}
                          </option>
                          <option value="BEFORE_HANDOVER">
                            {t("series.condition_before")}
                          </option>
                          <option value="AFTER_HANDOVER">
                            {t("series.condition_after")}
                          </option>
                        </select>
                      </td>
                      <td>
                        <StatusBadge
                          status={{ kind: "extra-work", value: member.status }}
                          testId={`ew-series-member-status-${member.extra_work}`}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </BoundedList>
        </div>

        <div className="ew-plan-section">
          <label className="ew-plan-switch">
            <input
              type="checkbox"
              className="checkbox-input"
              checked={regenerate}
              onChange={(e) => setRegenerate(e.target.checked)}
              data-testid="extra-work-series-regenerate"
            />
            <span>{t("series.regenerate_label")}</span>
          </label>
          <p className="muted small ew-plan-section-hint">
            {t("series.regenerate_hint")}
          </p>
          {/* The controls that are deliberately NOT here, named, with
              where they live. An absent control without an explanation
              reads as a missing feature. */}
          <p className="muted small ew-plan-section-hint">
            {t("series.elsewhere_hint")}
          </p>
        </div>

        <div className="ew-plan-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            disabled={busy}
            data-testid="extra-work-series-cancel"
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || loading || loadError !== ""}
            onClick={() => void save()}
            data-testid="extra-work-series-save"
          >
            {busy
              ? t("series.saving")
              : t("series.save", { count: changed })}
          </button>
        </div>
      </div>
    </div>
  );
}
