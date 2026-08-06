import type { ExtraWorkRequestList } from "../api/types";

/**
 * Sprint 144 §1 — what to show in a request's "Category" cell, across
 * the TWO shapes that now coexist.
 *
 * A request created from Sprint 144 onward carries either a
 * `service_category` (a company catalog category) or a `price_folder`
 * (the customer's own folder) — at most one — and its `category` enum
 * is just the untouched `default=OTHER`. A request created BEFORE this
 * sprint has neither FK and only the enum, which is the real answer for
 * it.
 *
 * So: the FK name wins when present, the enum label is the fallback.
 * Returning `null` (rather than a translated string) keeps this helper
 * free of `t()` — the caller already has the i18n key map and the
 * `category.other_text` suffix rule, and both differ per surface.
 *
 * Fully migrating the enum away is `## NEXT` item 18; this is not that.
 * It only stops the two shapes from rendering inconsistently while both
 * exist.
 */
export function extraWorkCategoryName(
  row: Pick<
    ExtraWorkRequestList,
    "service_category_name" | "price_folder_name"
  >,
): string | null {
  return row.service_category_name ?? row.price_folder_name ?? null;
}
