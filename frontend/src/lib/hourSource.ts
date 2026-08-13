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
 */

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
