// Sprint 152.3 — THE hour-type label rule. One helper, twelve call
// sites, no local re-implementations.
//
// The rule itself is two lines: a row whose `standard_slot` is one of
// the six known kinds renders a translated label; anything else renders
// its stored `name` verbatim. It lives here rather than being inlined
// because CLAUDE.md's frontend conventions name exactly this failure —
// a second, independently-maintained copy of a rendering rule is what
// drifts, and Sprint 126's headerless permission column survived three
// sprints on precisely that. A ternary repeated twelve times is a second
// copy twelve times over.
//
// `name` is deliberately NOT multilingual on the backend (`HourType`
// has one operator-typed `name` column; see
// `backend/timesheets/standard_set.py` for why the `label_nl` /
// `label_en` shape was rejected). The API therefore sends the stored
// name PLUS the slot on every payload and lets this decide — the JSON is
// never translated server-side. The one exception is the CSV export,
// which has no client and resolves the label itself.

import type { TFunction } from "i18next";

/**
 * The six slot keys, mirroring
 * `backend/timesheets/standard_set.py::STANDARD_SLOTS`. A key that
 * exists here and not there (or vice versa) means a row renders its raw
 * Dutch name to an English reader, so the two lists must move together.
 */
export const STANDARD_SLOT_KEYS = [
  "normal_hours",
  "overtime",
  "weekend",
  "public_holiday",
  "sick_leave",
  "vacation",
] as const;

export type StandardSlot = (typeof STANDARD_SLOT_KEYS)[number];

const KNOWN_SLOTS = new Set<string>(STANDARD_SLOT_KEYS);

/**
 * The i18n key for a slot. The translated strings MUST match what
 * `STANDARD_SLOTS` creates, in both bundles — a mismatch would mean the
 * "Add standard set" button writes one wording and the UI shows another,
 * which reads as data corruption rather than as a translation.
 */
export function standardSlotLabelKey(slot: string): string {
  return `hour_type_slot.${slot}`;
}

/** The minimum shape this helper needs: a stored name and a slot. */
export interface HourTypeLabelSource {
  name: string;
  standard_slot: string;
}

/**
 * The display label for an hour type.
 *
 * Falls back to the stored `name` for a custom type, for an unknown slot
 * key (a backend that grew a seventh kind before this build learned
 * about it), and for a missing translation. Every fallback lands on the
 * same value — the thing an admin actually typed — so the worst case is
 * "untranslated", never "blank".
 */
export function hourTypeLabel(
  source: HourTypeLabelSource,
  t: TFunction,
): string {
  const slot = source.standard_slot;
  if (!slot || !KNOWN_SLOTS.has(slot)) return source.name;
  const key = standardSlotLabelKey(slot);
  const translated = t(key);
  // i18next returns the KEY itself when a translation is missing.
  return translated === key ? source.name : translated;
}

/**
 * The same rule for a payload that carries the pair under different
 * names — `TimeEntry` sends `hour_type_name` / `hour_type_standard_slot`,
 * and a summary bucket sends `hour_type_name` / `standard_slot`. Both
 * route here rather than each unpacking the rule again.
 */
export function hourTypeLabelFrom(
  name: string,
  standardSlot: string | undefined,
  t: TFunction,
): string {
  return hourTypeLabel({ name, standard_slot: standardSlot ?? "" }, t);
}

/** True for a row the system recognises as one of the six standard kinds. */
export function isStandardHourType(source: { standard_slot: string }): boolean {
  return Boolean(source.standard_slot) && KNOWN_SLOTS.has(source.standard_slot);
}
