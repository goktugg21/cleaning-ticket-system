// The display name of a customer's own Department / Work type.
//
// Every customer is seeded one of each when it is created
// (`backend/customers/signals.py`, DEFAULT_LABEL_NAME = "Algemeen"), so
// an operator who never opened the labels screen still has somewhere for
// an unclassified job to land. The name is STORED, not translated —
// which is right for the ones an operator typed, and wrong for the one
// nobody chose: an English reader sees a Dutch word for a row they never
// created.
//
// So exactly one name is translated: the seeded default, matched the
// same case-insensitive way the backend matches it. Everything an
// operator typed renders verbatim, including a name that happens to
// collide — in which case the reader sees the same word in their own
// language, which is the right answer anyway.
//
// Deliberately NOT a `standard_slot` (the mechanism hour types and work
// types use): those catalogs offer a fixed standard SET and derive the
// slot in `save()`. A customer label list has no standard set — one
// seeded row and then whatever the operator wants — so a whole slot
// column for a single value would be machinery for its own sake.

/** Mirrors `DEFAULT_LABEL_NAME` in `backend/customers/signals.py`. */
export const SEEDED_LABEL_NAME = "algemeen";

export type Translate = (key: string) => string;

export function customerLabelName(
  name: string | null | undefined,
  t: Translate,
): string {
  const stored = (name ?? "").trim();
  if (!stored) return "";
  if (stored.toLowerCase() !== SEEDED_LABEL_NAME) return stored;
  const translated = t("common:customer_labels.seeded_default");
  // i18next returns the key itself when a translation is missing; the
  // stored name is the honest fallback, never a blank.
  return translated.includes(".") ? stored : translated;
}
