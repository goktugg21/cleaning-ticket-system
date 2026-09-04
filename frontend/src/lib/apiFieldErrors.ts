/**
 * P-4 (Part B) — WHAT THE SERVER SAID, FIELD BY FIELD.
 *
 * `getApiError` (P-2 §8) hands the screen ONE human sentence per status
 * and logs the body; that is right for a toast and wrong for a form,
 * where "That was not accepted" in a corner is the invisible error the
 * owner walked into. This reads the body the same call already
 * logged and returns its SHAPE — the stable `code`, the `detail`, a
 * `field` the server named, the `days` it listed, and every DRF
 * per-field entry — so a dialog can put each message AT its field and
 * fall back to the generic sentence only when the server truly gave no
 * field detail. Server text is never rendered as-is: the caller maps
 * codes and field names to its own i18n sentences.
 */
import axios from "axios";

export interface ApiErrorDetail {
  status: number | null;
  /** The stable machine code, when the server sent one. */
  code: string | null;
  /** The server's own English sentence — for the console, not the screen. */
  detail: string | null;
  /** The field a coded refusal points at (`{"field": "planned_hours"}`). */
  field: string | null;
  /** Days a coded refusal lists (`plan_past_day_locked`, outside-window). */
  days: string[];
  /** DRF per-field validation entries: `{field: ["msg", ...]}`. */
  fields: Record<string, string[]>;
}

const META_KEYS = new Set([
  "detail",
  "code",
  "field",
  "days",
  "window",
  "extra_work",
  "extra_work_title",
  "user",
  "non_field_errors",
]);

export function readApiErrorDetail(error: unknown): ApiErrorDetail {
  const out: ApiErrorDetail = {
    status: null,
    code: null,
    detail: null,
    field: null,
    days: [],
    fields: {},
  };
  if (!axios.isAxiosError(error)) return out;
  out.status = error.response?.status ?? null;
  const data = error.response?.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return out;
  const body = data as Record<string, unknown>;
  if (typeof body.code === "string") out.code = body.code;
  if (typeof body.detail === "string") out.detail = body.detail;
  if (typeof body.field === "string") out.field = body.field;
  if (Array.isArray(body.days)) {
    out.days = body.days.filter((d): d is string => typeof d === "string");
  }
  for (const [key, value] of Object.entries(body)) {
    if (META_KEYS.has(key)) continue;
    if (typeof value === "string") out.fields[key] = [value];
    else if (Array.isArray(value)) {
      const strings = value.filter((v): v is string => typeof v === "string");
      if (strings.length > 0) out.fields[key] = strings;
    } else if (value && typeof value === "object") {
      // A nested list serializer error (`planned_hours: [{}, {hours: [..]}]`)
      // arrives as an array of objects; anything object-shaped under a
      // field name still means "this field was refused".
      out.fields[key] = [];
    }
  }
  return out;
}
