/**
 * P-5 S0 — THE REFUSAL, IN THE READER'S WORDS.
 *
 * The error-body law says a server refusal always names its reason in
 * the body. This turns that body into the one sentence the transition
 * modal shows: the stable `code` (or the `unmet` list, or the field the
 * server named) maps to an i18n key; the generic "not accepted"
 * sentence from `getApiError` is left for a truly detail-less failure.
 * Server text is never rendered as-is (P-2 §8).
 */
import type { TFunction } from "i18next";

import { getApiError } from "../api/client";
import { readApiErrorDetail } from "./apiFieldErrors";

const CODE_KEYS: Record<string, string> = {
  actual_hours_required: "transition.refused.actual_hours_required",
  completion_evidence_required: "transition.refused.completion_evidence_required",
  stale_status: "transition.refused.stale_status",
  forbidden_transition: "transition.refused.forbidden_transition",
  no_op_transition: "transition.refused.no_op_transition",
  rejection_note_required: "transition.refused.rejection_note_required",
  override_reason_required: "transition.reason_required",
  staff_completion_route_mismatch: "transition.refused.staff_completion_route_mismatch",
  bm_override_disabled: "transition.refused.bm_override_disabled",
  schedule_forbidden_for_role: "transition.refused.schedule_forbidden",
  schedule_forbidden_scope: "transition.refused.schedule_forbidden",
  staff_already_assigned: "transition.refused.staff_already_assigned",
  unknown_status: "transition.refused.to_status",
};

const NEED_KEYS = new Set([
  "assignee",
  "schedule",
  "completion_evidence",
  "override_reason",
  "actual_hours",
]);

export function describeTransitionRefusal(error: unknown, t: TFunction): string {
  const detail = readApiErrorDetail(error);
  if (detail.code === "transition_requirements_unmet") {
    const body = (error as { response?: { data?: { unmet?: unknown } } })
      .response?.data;
    const unmet = Array.isArray(body?.unmet)
      ? body.unmet.filter((k): k is string => typeof k === "string" && NEED_KEYS.has(k))
      : [];
    if (unmet.length > 0) {
      return t("transition.refused.requirements", {
        list: unmet.map((k) => t(`transition.need.${k}`)).join(", "),
      });
    }
  }
  if (detail.code && CODE_KEYS[detail.code]) return t(CODE_KEYS[detail.code]);
  if (detail.fields.note) return t("transition.refused.note");
  if (detail.fields.to_status) return t("transition.refused.to_status");
  if (detail.fields.scheduled_start_at) return t("transition.refused.schedule_forbidden");
  return getApiError(error);
}
