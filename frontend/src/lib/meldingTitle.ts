/**
 * FE-2/FE-5 — the ONE description's mapping onto the ticket contract.
 *
 * `POST /tickets/` requires a `title` and a `description`; both the
 * customer's melding form and the provider's ticket form ask ONE
 * question, so the title is the description's first line, clipped.
 * Shared so the two forms can never map the same text two ways.
 */
export const TITLE_CLIP = 120;

/** The description's first line, clipped, as the ticket title. */
export function titleFrom(description: string): string {
  const firstLine = description.trim().split("\n")[0].trim();
  if (firstLine.length <= TITLE_CLIP) return firstLine;
  return `${firstLine.slice(0, TITLE_CLIP - 1)}…`;
}
