// Column-key constants for the InvoiceLineRow table. Kept in a
// sibling file (not in `InvoiceLineRow.tsx`) so the component file
// only exports React components — required by the
// `react-refresh/only-export-components` lint rule that's enabled
// project-wide.
//
// A parent that owns the table's <thead> renders one <th> per key
// in display order and resolves each via the `extra_work` i18n
// namespace.

export const INVOICE_LINE_COLUMN_KEYS = [
  "invoice_row.col_service",
  "invoice_row.col_source",
  "invoice_row.col_quantity",
  "invoice_row.col_unit",
  "invoice_row.col_unit_price",
  "invoice_row.col_vat_pct",
  "invoice_row.col_subtotal",
  "invoice_row.col_vat",
  "invoice_row.col_total",
  "invoice_row.col_actions",
] as const;

export type InvoiceLineColumnKey = (typeof INVOICE_LINE_COLUMN_KEYS)[number];
