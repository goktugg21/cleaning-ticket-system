// Sprint 170 §5 — THE standard-set label rule, once.
//
// Three catalogs in this system offer a "standard set": hour types,
// work types and contract types. Each stores ONE operator-typed `name`
// and derives a `standard_slot` from it in `save()`, and each sends the
// pair on every payload so the CLIENT renders a recognised slot in the
// reader's language. That is the Sprint 152.3 decision, and it is the
// same decision three times.
//
// The rendering rule was also written three times. It is two lines, so
// three copies looked harmless — but a rule copied is a rule that
// drifts, which is the failure CLAUDE.md names and which this codebase
// keeps recording. What genuinely differs between the three is a KEY
// PREFIX and a SET OF SLOTS, so those are parameters and the rule is
// here.
//
// Each catalog keeps a named wrapper (`hourTypeLabel`,
// `workTypeLabel`, `contractTypeLabel`) so call sites read as what they
// render and so the slot list stays next to the catalog it mirrors.

/** The minimum this needs. Narrower than `TFunction` on purpose: some
 *  list pages pass a deliberately narrowed translator down to their row
 *  renderers, and widening THAT to satisfy a helper would be the tail
 *  wagging the dog. Any `TFunction` satisfies this. */
export type Translate = (
  key: string,
  options?: Record<string, unknown>,
) => string;

/**
 * The display label for a row from a standard-set catalog.
 *
 * Falls back to the stored `name` for a custom type, for an unknown slot
 * key (a backend that grew a fifth kind before this build learned about
 * it), and for a missing translation. Every fallback lands on the same
 * value — the thing an admin actually typed — so the worst case is
 * "untranslated", never "blank".
 */
export function standardSlotLabel(
  name: string | null | undefined,
  standardSlot: string | null | undefined,
  keyPrefix: string,
  knownSlots: ReadonlySet<string>,
  t: Translate,
): string {
  const stored = name ?? "";
  const slot = standardSlot ?? "";
  if (!slot || !knownSlots.has(slot)) return stored;
  const key = `${keyPrefix}.${slot}`;
  const translated = t(key);
  // i18next returns the KEY itself when a translation is missing.
  return translated === key ? stored : translated;
}
