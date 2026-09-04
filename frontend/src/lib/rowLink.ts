/**
 * P-13 D (O3, §D.22 rule 9) — rows are links, everywhere. The pure
 * half of the row-link layer: per-table href resolvers, so the whole
 * row and the name link inside it can never point at different pages,
 * and the inner-control selector every row-click guard shares.
 *
 * The interactive half is `useRowLink` (the ONE hook); `ClickableRow`
 * is its `<tr>` packaging. New tables use `ClickableRow`; a table that
 * cannot (a row that is not a `<tr>`) uses the hook directly.
 */

/** A click that starts on one of these keeps its own behaviour — the
 *  row ignores it. One selector, shared by every row-click guard. */
export const ROW_INNER_CONTROL_SELECTOR =
  "a,button,input,select,textarea,label";

/** An at-risk row opens the job: the spawned ticket when one exists,
 *  else the extra-work request (same target as its name link). */
export function atRiskRowHref(row: {
  ticket_id: number | null;
  extra_work_id: number;
}): string {
  return row.ticket_id !== null
    ? `/tickets/${row.ticket_id}`
    : `/extra-work/${row.extra_work_id}`;
}

/** A due row's object is the customer's billing: their own invoices
 *  surface. */
export function dueRowHref(row: { customer: number }): string {
  return `/admin/customers/${row.customer}/invoices`;
}
