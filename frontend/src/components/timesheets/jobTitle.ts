/**
 * W-HOURS6 — a job's NAME first; its number second.
 *
 * People remember titles, not numbers. Every read the hours flows use
 * hands a job over as ONE string, `"TCK-2026-000373 — final test"`
 * (`reports/week_assignments.py::_job`, `reports/hour_sources.py::
 * available_sources` and `resolve_sources` all build it the same way,
 * and `Ticket.ticket_no` is `TCK-{year}-{id:06d}`). Nothing here fetches
 * anything: the string is split on that prefix, so the picker can show
 * the number small above the name, and a tag or a grid cell can read
 * "final test · TCK-373" with the full string as its tooltip.
 *
 * The short code drops the year and the zero padding. It is still
 * unambiguous: the number IS the ticket's primary key, unique across
 * years, and the full code always travels along as the tooltip.
 *
 * A pure module beside the picker on purpose: a component file that
 * exports a helper breaks fast refresh (`react-refresh/only-export-
 * components`), and `lib/hourSource.ts` — where `hourSourceLabel` lives
 * — is not this wave's territory.
 */

/** `^TCK-YYYY-NNNNNN — rest` — the one shape the reports build. */
const JOB_TITLE = /^(TCK-\d{4}-(\d+))\s+—\s+(.+)$/su;

export interface JobTitleParts {
  /** The full number ("TCK-2026-000373"), or null for a label without one. */
  code: string | null;
  /** The number people say ("TCK-373"), or null. */
  short: string | null;
  /** The title alone, or the whole label when it carries no number. */
  name: string;
}

export function splitJobTitle(title: string): JobTitleParts {
  const match = JOB_TITLE.exec(title.trim());
  if (!match) return { code: null, short: null, name: title };
  const [, code, digits, name] = match;
  return {
    code,
    short: `TCK-${Number.parseInt(digits, 10)}`,
    name: name.trim(),
  };
}

/** "TCK-2026-000373 — final test" -> "final test · TCK-373"; a label
 *  without a number is returned as it is. */
export function jobTitleFirst(title: string): string {
  const parts = splitJobTitle(title);
  return parts.short ? `${parts.name} · ${parts.short}` : parts.name;
}
