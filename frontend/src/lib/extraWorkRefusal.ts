/**
 * P-8R A3 — THE REFUSAL, IN THE READER'S WORDS, ON THE MEERWERK DOORS.
 *
 * `transitionRefusal.ts` (P-5) does this for the ticket transition
 * modal. This is its twin for every Extra Work door — the request
 * transition, the proposal doors (create / lines / send / decide /
 * direct-publish), the plan door and bulk plan — so a 400 with a stable
 * `code` never reaches a screen as "That was not accepted".
 *
 * The result carries a KIND, because two refusals are not sentences but
 * doors: `plan_gap` (the server named the missing plan pieces; the
 * screen offers "Complete the plan", opening the modal at the first
 * gap) and `reason_required` (the act is an override; the screen
 * offers the amber reason ceremony). Everything else is a sentence at
 * the acting control. Server text is never rendered as-is (P-2 §8):
 * only `getApiError`'s status sentence survives, and only for a body
 * with no detail at all (a 5xx).
 */
import type { TFunction } from "i18next";

import { getApiError } from "../api/client";
import { readApiErrorDetail } from "./apiFieldErrors";

export type ExtraWorkRefusalKind =
  | "plan_gap"
  | "reason_required"
  | "field"
  | "sentence"
  | "generic";

export interface ExtraWorkRefusal {
  kind: ExtraWorkRefusalKind;
  /** The one sentence to show. */
  sentence: string;
  /** `plan_gap` only — the server's unmet keys (`plan_staff`, ...). */
  unmet: string[];
  /** The stable code, for a test or a console line. */
  code: string | null;
}

/** Stable code -> `extra_work` namespace key. Every code the EW,
 *  proposal, pricing, plan and spawn doors can answer with. */
const CODE_KEYS: Record<string, string> = {
  invalid_transition: "refused.invalid_transition",
  forbidden_transition: "refused.forbidden_transition",
  no_op_transition: "refused.no_op_transition",
  unknown_status: "refused.unknown_status",
  stale_status: "refused.stale_status",
  operational_status_follows_ticket: "refused.operational_status_follows_ticket",
  pricing_line_items_required: "refused.pricing_line_items_required",
  bm_override_disabled: "refused.bm_override_disabled",
  bm_proposal_preparation_disabled: "refused.bm_proposal_preparation_disabled",
  quote_override_not_permitted: "refused.quote_override_not_permitted",
  quote_bypass_requires_quote_request: "refused.quote_bypass_requires_quote_request",
  direct_publish_requires_draft: "refused.direct_publish_requires_draft",
  proposal_not_draft: "refused.proposal_not_draft",
  proposal_open_already_exists: "refused.proposal_open_already_exists",
  preview_lines_required: "refused.preview_lines_required",
  nothing_to_plan: "refused.nothing_to_plan",
  plan_provider_only: "refused.plan_provider_only",
  planned_hours_invalid: "refused.planned_hours_invalid",
  planned_hours_duplicate_user: "refused.planned_hours_invalid",
  planned_hours_hour_type_invalid: "refused.planned_hours_invalid",
  planned_hours_outside_window: "refused.planned_hours_outside_window",
  plan_past_day_locked: "refused.plan_past_day_locked",
  provider_planned_end_before_start: "refused.provider_planned_end_before_start",
  provider_planned_end_without_start: "refused.provider_planned_end_without_start",
  extra_work_bulk_plan_invalid: "refused.bulk_plan_invalid",
  extra_work_bulk_plan_shape_invalid: "refused.bulk_plan_invalid",
  actual_hours_forbidden: "refused.actual_hours_forbidden",
  actual_hours_invalid: "refused.actual_hours_invalid",
  actual_hours_not_hourly: "refused.actual_hours_not_hourly",
  actual_hours_invoice_locked: "refused.final_amount_locked",
  final_amount_locked: "refused.final_amount_locked",
  spawn_forbidden_role: "refused.spawn_forbidden",
  spawn_forbidden_scope: "refused.spawn_forbidden",
  spawn_wrong_status: "refused.spawn_wrong_status",
  labels_locked_by_invoice: "refused.labels_locked_by_invoice",
  thread_frozen: "refused.thread_frozen",
};

/** A DRF per-field validation the doors answer with, by field name. */
const FIELD_KEYS: Record<string, string> = {
  to_status: "refused.field_to_status",
  override_reason: "refused.override_reason_required",
  customer_reject_reason: "refused.field_customer_reject_reason",
  note: "refused.field_note",
  lines: "refused.field_lines",
  planned_hours: "refused.planned_hours_invalid",
  budget_hours: "refused.field_budget_hours",
  provider_planned_date: "refused.field_provider_planned_date",
  provider_planned_end_date: "refused.field_provider_planned_date",
  items: "refused.bulk_plan_invalid",
  requests: "refused.bulk_plan_invalid",
};

const PLAN_GAP_KEYS: Record<string, string> = {
  plan_staff: "plan_gate.missing_staff",
  plan_manager: "plan_gate.missing_manager",
  plan_start_date: "plan_gate.missing_start_date",
  plan_hours: "plan_gate.missing_hours",
};

export function describeExtraWorkRefusal(
  error: unknown,
  t: TFunction,
): ExtraWorkRefusal {
  const detail = readApiErrorDetail(error);
  const body = (error as { response?: { data?: { unmet?: unknown } } })
    ?.response?.data;
  if (detail.code === "plan_requirements_unmet") {
    const unmet = Array.isArray(body?.unmet)
      ? body.unmet.filter(
          (k): k is string => typeof k === "string" && k in PLAN_GAP_KEYS,
        )
      : [];
    return {
      kind: "plan_gap",
      code: detail.code,
      unmet,
      sentence: t("refused.plan_requirements_unmet", {
        list: unmet.map((k) => t(PLAN_GAP_KEYS[k])).join(", "),
      }),
    };
  }
  if (detail.code === "override_reason_required" || detail.fields.override_reason) {
    return {
      kind: "reason_required",
      code: "override_reason_required",
      unmet: [],
      sentence: t("refused.override_reason_required"),
    };
  }
  if (detail.code && CODE_KEYS[detail.code]) {
    return {
      kind: "sentence",
      code: detail.code,
      unmet: [],
      sentence: t(CODE_KEYS[detail.code]),
    };
  }
  for (const field of Object.keys(detail.fields)) {
    if (FIELD_KEYS[field]) {
      return {
        kind: "field",
        code: detail.code,
        unmet: [],
        sentence: t(FIELD_KEYS[field]),
      };
    }
  }
  if (detail.status !== null && detail.status < 500 && Object.keys(detail.fields).length > 0) {
    // A field the map does not know: still say WHICH field, never
    // "not accepted".
    return {
      kind: "field",
      code: detail.code,
      unmet: [],
      sentence: t("refused.field_unknown", {
        field: Object.keys(detail.fields)[0],
      }),
    };
  }
  return {
    kind: "generic",
    code: detail.code,
    unmet: [],
    sentence: getApiError(error),
  };
}
