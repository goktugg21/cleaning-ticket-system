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

/**
 * P-15 4.5(b) — the pattern dialog's DEFAULT kind of work.
 *
 * A standing pattern is usually "Vast werk": the default is the
 * company's fixed-work entry (the standard set's first), recognised by
 * its slot in either language — NEVER "Extra work", which is what the
 * bare first-option dropdown used to land on. A company with no
 * fixed-work entry gets no default (the dialog then asks), and a
 * company with no kinds of work at all hides the field.
 */
export function defaultWorkTypeId(
  workTypes: { id: number; standard_slot?: string | null }[],
): number | null {
  return (
    workTypes.find((type) => type.standard_slot === "fixed_work")?.id ?? null
  );
}
