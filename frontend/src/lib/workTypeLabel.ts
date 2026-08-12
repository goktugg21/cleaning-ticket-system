// Sprint 170 §5 — the work-type label, on the shared rule.
//
// Sprint 168 shipped this catalog with a standard set and NO slot, so an
// English operator saw four Dutch words with nothing able to translate
// them. The owner's instruction covers every standard set, not only the
// one that was asked about.

import { standardSlotLabel } from "./standardSlotLabel";
import type { Translate } from "./standardSlotLabel";

/**
 * The four slot keys, mirroring
 * `backend/timesheets/serializers_work_types.py::STANDARD_WORK_TYPE_SLOTS`.
 * A key here and not there (or vice versa) means a row renders its raw
 * Dutch name to an English reader, so the two lists move together.
 */
export const STANDARD_WORK_TYPE_KEYS = [
  "fixed_work",
  "extra_work",
  "machine",
  "other",
] as const;

const KNOWN = new Set<string>(STANDARD_WORK_TYPE_KEYS);

export function workTypeLabel(
  name: string | null | undefined,
  standardSlot: string | null | undefined,
  t: Translate,
): string {
  return standardSlotLabel(name, standardSlot, "work_type_slot", KNOWN, t);
}
