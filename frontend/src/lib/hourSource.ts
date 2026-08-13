/**
 * Sprint 178 §4a — encoding an hour's source for a `<select>`.
 *
 * A source is a PAIR — `(source_type, source_id)` — and a select's value
 * is one string, so the pair travels as `"TYPE:id"`, or bare `"TYPE"` for
 * a type-only source like CONTRACT or OTHER (Sprint 178 §4b) which names
 * a kind of work rather than pointing at a record.
 *
 * Both directions live here, in `lib/` beside the other pure helpers,
 * for two reasons: they are the kind of thing two screens will want (the
 * entries table already does, the week grid may), and a component file
 * that exports non-components breaks fast refresh — which is how this
 * ended up here rather than inline.
 *
 * One encoder and one decoder, so the two halves can never be
 * recombined differently in two places.
 *
 * Sprint 179B §2 — and one LABELLER, `hourSourceLabel` below, for the
 * same reason and in the same place.
 */

import type { TFunction } from "i18next";

import type { HourSourceOption } from "../api/reports";

export function encodeSource(
  sourceType: string | null | undefined,
  sourceId: number | null | undefined,
): string {
  if (!sourceType) return "";
  return sourceId ? `${sourceType}:${sourceId}` : sourceType;
}

export function decodeSource(value: string): {
  source_type: string;
  source_id: number | null;
} {
  // An empty value means "no source recorded", which is OTHER with no id
  // — the model's own default, so clearing the cell restores exactly the
  // state an untouched row has.
  if (!value) return { source_type: "OTHER", source_id: null };
  const [type, id] = value.split(":");
  return { source_type: type, source_id: id ? Number(id) : null };
}

/**
 * Sprint 179B §2 — the pair, in words.
 *
 * The owner picked four jobs in the week wizard, got four rows, and
 * every one of them read "Worker / Building / Normale uren". The rows
 * were right — `(source_type, source_id)` is part of the row identity,
 * so the hours never merged onto one line — but nothing on screen said
 * which row was which job, so four correct rows looked like four
 * duplicates.
 *
 * Fixing that means printing a job in several places at once, and a
 * ternary repeated four times is a second copy four times over — the
 * exact failure CLAUDE.md's frontend conventions name. So the rule is
 * written once, here, beside the encoder it belongs with.
 *
 * ## Why the caller passes the options in
 *
 * A `TimeEntry` stores a TYPE and an ID and resolves neither:
 * `timesheets` may not import `tickets` or `extra_work`, so turning an
 * id into a title is `reports/`'s job — `backend/reports/hour_sources.py`
 * argues this at length, and `source_label()` there is the function this
 * one mirrors. The frontend keeps the same line: nothing here fetches
 * anything. The caller hands over whatever
 * `GET /api/reports/hour-sources/` returned.
 *
 * Three cases, and they are genuinely different things:
 *
 *  - **a job with a record behind it** (a ticket, an extra-work
 *    request): its title, taken from `options`;
 *  - **a record that cannot be named right now** — the id no longer
 *    resolves, the actor may not read it, or the picker never listed it
 *    (it offers OPEN work only, so hours logged against a ticket that
 *    has since closed land here): `"Ticket #41"`, exactly the fallback
 *    `hour_sources.py::source_label` produces for the same case;
 *  - **no record at all**: `CONTRACT` names a KIND of work and carries
 *    no id, so it prints as "Contract". `OTHER` and an untagged row both
 *    mean nobody said — `OTHER` is the column's default — so both print
 *    the neutral label. Those two are indistinguishable in the data, and
 *    a UI that pretended otherwise would be inventing a fact.
 */
export function hourSourceLabel(
  sourceType: string | null | undefined,
  sourceId: number | null | undefined,
  options: HourSourceOption[],
  t: TFunction,
  /** What "no job" reads as. Passed in because the surfaces that need
   *  this sit in tables with different conventions for an empty cell —
   *  the grid names it, a dense admin table prints an em dash. */
  neutralLabel: string,
): string {
  if (!sourceId) {
    return sourceType && sourceType !== "OTHER"
      ? t(`hour_source.${sourceType}`)
      : neutralLabel;
  }
  const match = options.find(
    (option) =>
      option.source_type === sourceType && option.source_id === sourceId,
  );
  return match ? match.title : `${t(`hour_source.${sourceType}`)} #${sourceId}`;
}
