// Sprint 169 §4 — THE contract-type label rule. One helper, every call
// site through it.
//
// The rule is two lines: a row whose `standard_slot` is one of the four
// known kinds renders a translated label; anything else renders its
// stored `name` verbatim. It lives here for the reason `hourTypeLabel`
// does — CLAUDE.md's frontend conventions name this exact failure, and
// a second, independently-maintained copy of a rendering rule is what
// drifts.
//
// `name` is deliberately NOT multilingual on the backend: `ContractType`
// has one operator-typed `name` column, and the API sends the stored
// name PLUS the slot on every payload and lets this decide.

import { standardSlotLabel } from "./standardSlotLabel";
import type { Translate } from "./standardSlotLabel";

/**
 * The four slot keys, mirroring
 * `backend/contracts/standard_types.py::STANDARD_CONTRACT_TYPES`. A key
 * that exists here and not there (or vice versa) means a row renders its
 * raw Dutch name to an English reader, so the two lists move together.
 */
export const STANDARD_CONTRACT_TYPE_KEYS = [
  "cleaning",
  "extra_work",
  "machine",
  "other",
] as const;

export type StandardContractTypeSlot =
  (typeof STANDARD_CONTRACT_TYPE_KEYS)[number];

const KNOWN = new Set<string>(STANDARD_CONTRACT_TYPE_KEYS);

/** The i18n key for a slot. The translations MUST match what
 *  `standard-set` writes, in both bundles — a mismatch would mean the
 *  button writes one wording and the UI shows another, which reads as
 *  data corruption rather than as a translation. */
export function standardContractTypeKey(slot: string): string {
  return `contract_type_slot.${slot}`;
}

/**
 * The display label for a contract type.
 *
 * Falls back to the stored `name` for a custom type, for an unknown slot
 * key (a backend that grew a fifth kind before this build learned about
 * it), and for a missing translation. Every fallback lands on the same
 * value — the thing an admin actually typed — so the worst case is
 * "untranslated", never "blank".
 */
export function contractTypeLabel(
  name: string | null | undefined,
  standardSlot: string | null | undefined,
  t: Translate,
): string {
  // Sprint 170 §5 — the rule lives in `standardSlotLabel`; this keeps
  // the slot list beside the catalog it mirrors and gives the call
  // sites a name that says what they render.
  return standardSlotLabel(name, standardSlot, "contract_type_slot", KNOWN, t);
}
