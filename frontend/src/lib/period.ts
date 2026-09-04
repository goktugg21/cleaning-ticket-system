/**
 * W-H §3 — THE PERIOD VOCABULARY. One owner, for every list of dated
 * work.
 *
 * The owner: "I need to be able to see this month's jobs, a selected
 * period's jobs." Four answers, and the same four everywhere:
 *
 *   this month  -  last 3 months  -  this year  -  all time  -  a range
 *   you pick
 *
 * Learning it once has to be enough, so the KEYS, the RESOLUTION to two
 * dates, and the DEFAULT live here rather than in each page. A page
 * chooses which default it opens on and nothing else; if a page needed
 * a fifth option it would belong in this list, not beside it.
 *
 * Resolution is to two inclusive ISO dates because that is what every
 * list endpoint takes (`?date_from=&date_to=`) — the server compares
 * calendar days, so "31 March" includes the whole of 31 March. No
 * endpoint receives the key itself: a server that had to know what
 * "this year" means would be a second place the vocabulary is defined.
 */

export const PERIOD_KEYS = [
  "this_month",
  "last_3_months",
  "this_year",
  // W13-FIX 5 — "all time". The three dated options could not answer
  // "show me everything", so anything older than January was invisible
  // and there was no way to ask for it. It resolves to NO dates, which
  // is what every list endpoint already treats as unbounded, so no
  // endpoint changes. It is deliberately NOT the default: a page still
  // opens on its own chosen period.
  "all_time",
  "custom",
] as const;

export type PeriodKey = (typeof PERIOD_KEYS)[number];

/** The i18n key for each option, keyed by the union so a fifth period
 *  fails the compiler here instead of rendering a blank option
 *  (CLAUDE.md — a second array literal defeats exhaustiveness). */
export const PERIOD_LABEL_KEY: Record<PeriodKey, string> = {
  this_month: "period.this_month",
  last_3_months: "period.last_3_months",
  this_year: "period.this_year",
  all_time: "period.all_time",
  custom: "period.custom",
};

export interface PeriodState {
  key: PeriodKey;
  /** Only meaningful while `key` is "custom". Kept across a switch away
   *  and back so picking This month to glance at it does not throw away
   *  the range somebody typed. */
  from: string;
  to: string;
}

function iso(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/**
 * The two dates a period means TODAY, inclusive at both ends.
 *
 * `custom` with an empty side returns "" for that side, which every
 * caller drops from the query — a half-filled range is an open end, not
 * an error, so typing the start date narrows the list immediately
 * instead of waiting for the second field.
 */
export function resolvePeriod(state: PeriodState): { from: string; to: string } {
  const now = new Date();
  switch (state.key) {
    case "this_month":
      return {
        from: iso(new Date(now.getFullYear(), now.getMonth(), 1)),
        to: iso(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
      };
    case "last_3_months":
      // The two whole months before this one, plus this one. A rolling
      // 90 days would answer a different question and would not line up
      // with anybody's month-end.
      return {
        from: iso(new Date(now.getFullYear(), now.getMonth() - 2, 1)),
        to: iso(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
      };
    case "this_year":
      return {
        from: iso(new Date(now.getFullYear(), 0, 1)),
        to: iso(new Date(now.getFullYear(), 11, 31)),
      };
    case "all_time":
      // Both ends open. `periodParams` drops empty sides, so the request
      // carries neither date_from nor date_to and the server returns the
      // unfiltered set.
      return { from: "", to: "" };
    case "custom":
      return { from: state.from, to: state.to };
  }
}

/** The query pair, with empty sides dropped. Every list builds its
 *  request through this, so no page invents its own parameter names. */
export function periodParams(
  state: PeriodState,
): { date_from?: string; date_to?: string } {
  const { from, to } = resolvePeriod(state);
  return {
    ...(from ? { date_from: from } : {}),
    ...(to ? { date_to: to } : {}),
  };
}

export function periodState(key: PeriodKey, from = "", to = ""): PeriodState {
  return { key, from, to };
}
