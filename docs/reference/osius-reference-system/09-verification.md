# PART 1 - LIVE DATA VERIFICATION (V1)

Agent V1. Scope: every headline claim of reports **01-extra-work**, **02-invoicing** and
**03-ew-invoice-seam**, tested against the live reference API (`dev-api.osius.nl`) through
the read-only wrapper. Investigated 2026-08-19, after those three reports were written the
same day. **Every call was a GET.** Nothing was modified.

Evidence labels: **CODE** = read in `/tmp/osius-ref/{backend,frontend}`, path + line.
**DATA** = a live GET and the values it returned. **INFERRED** = a conclusion, stated as such.

Personal data is redacted: real people appear as `<user>`, addresses and e-mail addresses are
not reproduced. Record ids, statuses, dates, amounts, invoice numbers and codes are quoted verbatim.

---

## 1. PLAIN-ENGLISH: WHAT THE LIVE DATA SAYS

The three tier-1 reports are, on the whole, **accurate**. I set out to break them and the
large majority of their claims survived contact with the real database. Where they were
wrong, they were wrong in four specific and interesting ways.

**1. The record counts in report 01 are inflated, because the list endpoint's status filter
lies.** Report 01 published a status table with "live v1 rows" of 19/6/1/6/0/0/0/9/37 and a
total of 78 records. The true numbers are **18/5/1/6/0/0/0/9/37 and 76 records**. The
difference is not a change in the data - it is an artefact of how the filter is built. When
you pass `?statuses=N`, the backend does not simply match `status_id = N`. It also returns
the **header row of any group in which ANY member matches**. So a group header sitting at
status 1 is returned by `?statuses=2` as well, and gets counted twice by anyone who sums the
per-status totals. Two records in this database (553 and 548) are group headers and are
therefore double-counted. The system's own statistics endpoint - which counts properly -
reports 18/5/1/6/9/37 = 76, and confirms it.

**2. Status 7 is not untouched by v1.** Report 01 states flatly that statuses 5, 6 and 7 are
"the newer system's vocabulary" and that "no v1 code path ever writes status 5". For status
5 and 6 I found nothing to contradict that. But status **7** was demonstrably held by live v1
extra-work rows: on 2026-06-04 at 11:04:42 roughly twenty-five works moved **9 -> 7**, and
sixteen to eighteen seconds later each of them moved **7 -> 9**, at exactly the second its
invoice was marked sent. The activity log records every one of these transitions on the v1
`extra_works` rows. Report 01's underlying mechanism claim is still right - nothing in the
code *automatically* writes 7 - but the generic status endpoint accepts any status id that
exists in the lookup table, status 7's Dutch label is "Gefactureerd" (the obvious choice in a
dropdown), and somebody used it. The claim "no v1 code path ever writes it" is contradicted
by the evidence.

**3. Something moves the works when an invoice is sent, and I cannot find what.** Report 03
says "Nothing about the works changes when an invoice is sent". The activity log says
otherwise: the works of invoice 88 returned to status 9 at `11:04:58`, which is invoice 88's
`sent_at` to the second, and the works of invoice 89 returned to status 9 at `11:05:00-01`,
which is invoice 89's `sent_at`. I read `InvoiceController::sendInvoice()` line by line - it
touches only the invoice row - and I read the frontend send handler - it issues one POST and
nothing else. There is no invoice observer. So the coupling is real in the data and absent
from the code I read. This is the single most important open question I am handing on.

**4. The invoice PDF is a three-page document, not two, and its fallback period prints in
English.** Report 02 describes a "two-page A4 document"; the live render of invoice 89 is
**three pages**, because the specification annex overflows. Report 03 predicted the period
line would read "mei 2026"; it actually reads **"May 2026"** - an English month name inside
an otherwise fully Dutch invoice.

Everything else that mattered held up, and several claims turned out to be *understated*:

- **The VAT loss is real, on a document that was actually sent.** Extra work 448 carries one
  product at **9.00%** VAT. Its own screen computes subtotal 30.12, tax **2.71**, total
  **32.83**. The invoice line the customer received (item 413 on `INV-202605-0003`, status
  **sent**) records `tax_rate: 0.2100`, and the rendered PDF prints that line as
  `EUR 30,12 | 21% | EUR 36,45`. The customer was billed **EUR 3,62 too much VAT on one line**,
  and the PDF's VAT summary block prints a single clean "BTW (21%)" total, so nothing on the
  document reveals it.
- **Labour is not billed, and the amounts are not small.** Extra work 449 has
  `total_labor_cost 412.50` and `total_products_cost 75.30`. Its invoice line on the **sent**
  invoice `INV-202605-0002` is **75.30**. Work 468 loses 361.50 the same way. Across the five
  invoiced works that carry any labour at all, **848.25 EUR of labour never reached an invoice.**
- **`extra_works.invoice_id` is dead in the strongest possible sense.** All 37 works at
  status 9 have `invoice_id: null`. Three of them (437, 438, 444) carry an `invoice_date` of
  `2025-11-30` pointing at no invoice at all.
- **Being "invoiced" does not require an invoice.** Six works sit at status 9 with no invoice
  line anywhere: 437, 438, 439, 440, 444, 476 - exactly the six report 03 named. And I found
  the deliberate mechanism report 03 did not name: the bulk-invoice modal has a branch that
  PATCHes zero-amount groups straight to `status_id: 9` **without creating an invoice**.
- **Being "invoiced" does not require a sent invoice either.** Invoice 87 is still a `draft`,
  and all six of its works (436, 441, 450, 451, 467, 468) are already at status 9 and already
  invisible in every default list.
- **There is no state machine, and the data proves it without needing a single write.** Eight
  of the nine records at status 8 ("Voltooid") have **no `approved_at` at all** - they reached
  the end of the ladder without ever passing the customer-approval step. Two extra works sit
  at status 4 with no `completed_at` - they skipped status 3. And one record went *backwards*,
  9 -> 7.
- **The staging pool is 100% exposed to the destructive purge.** All 13 `invoiceable_items`
  rows carry `notes: "auto_generated_from_task"`, which is exactly the `LIKE 'auto_generated%'`
  predicate that `PrjProjectsController::generateSubProjects` force-deletes with no status guard.

---

## 2. THE VERDICT TABLE

| # | CLAIM | SOURCE | TEST PERFORMED | RESULT | VERDICT |
|---|---|---|---|---|---|
| 1 | Status list is id/slug/label 1 new, 2 in_progress, 3 resolved, 4 closed, 5 internal_approval, 6 customer_approval, 7 invoiced_v2 "Gefactureerd", 8 archived "Voltooid", 9 invoiced (lowercase) | 01 §1.2 | `GET /admin/extra-works/meta/config` | Returned exactly that list, same slugs, same Dutch labels, 8 listed before 7, label of 9 is the lowercase string `invoiced` | **CONFIRMED** |
| 2 | Live v1 row counts are 19/6/1/6/0/0/0/9/37, total 78 | 01 §1.2, §1.6 | Swept `?statuses=1..10`, then de-duplicated the returned ids; cross-checked `GET /admin/extra-works/statistics` | Sweep totals reproduce 19/6/1/6/0/0/0/9/37, but only **76 distinct ids** come back; statistics endpoint says 18/5/1/6/9/37 | **CONTRADICTED** (counts inflated by a leaky filter; true total 76) |
| 3 | Statuses 5, 6, 7 hold zero v1 rows | 01 §1.2 | `?statuses=5`, `=6`, `=7` | `total: 0` for each | **CONFIRMED** (today) |
| 4 | "No v1 code path ever writes status 5"; 5/6/7 are V2 vocabulary only | 01 §1.2 | `GET /admin/extra-works/{442,448,449,466,433}/activities` | Five v1 works logged `9 -> 7` on 2026-06-04 11:04:42-43 and `7 -> 9` at 11:04:58-11:05:01 | **CONTRADICTED for status 7** (5 and 6 untested-negative) |
| 5 | There is no state machine; any status reachable from any status | 01 §1.2 | Stamp-presence audit over all 76 records + activity logs | 8 of 9 status-8 records have `approved_at: null`; 2 type-1 records at status 4 have `completed_at: null`; one record ran 9 -> 7 backwards | **CONFIRMED** |
| 6 | The entity config carries **zero** `validation` keys, so create/update run with an empty rule array | 01 §1.6, §2.3 | `GET /admin/extra-works/meta/config` -> `entity_config.fields` | 39 fields returned, **not one** has a `validation` key | **CONFIRMED** |
| 7 | The write allow-list is the 39 config field names; `upload_is_required` / `notes_is_required` / `completion_notes` are not in it | 01 §2.3 | same call | Field list returned verbatim; the three names are absent (`grep` count 0 in the whole 17.8 KB payload) | **CONFIRMED** |
| 8 | 0 live records have `upload_is_required` or `notes_is_required` true | 01 §1.6 | All 76 records inspected | 0 and 0 | **CONFIRMED** (of 76, not 78) |
| 9 | `file_1..file_4` are dead columns | 01 §1.9 | list + detail payloads; config | Absent from every list and detail response, but **present and fillable** in `entity_config.fields` | **CONFIRMED as unread**, nuance: still writable |
| 10 | Server stamps `"Name (Role)"` free-text strings, not user ids | 01 §1.4 | list payload | `planed_by`, `started_by`, `completed_by`, `approved_by`, `created_by`, `archive_*_by` all hold e.g. `"<user> (Admin)"` | **CONFIRMED** |
| 11 | `approveArchive` back-fills `archive_requested_at` with the same timestamp as `archive_approved_at` | 01 §1.3, §2.4 | All 9 status-8 records | 9 of 9 have `archive_requested_at == archive_approved_at` to the second; `archive_rejected_at` null on all | **CONFIRMED** |
| 12 | A Melding that takes the short path lands at 4 with `approved_at` set and `completed_at` never set | 01 §1.3 | All 7 type-2 records | 4 of 4 meldings at status 4 have `approved_at` set, `completed_at: null` | **CONFIRMED** |
| 13 | Revert 4 -> 3 destroys the original `completed_at` by re-stamping it | 01 §1.5 | Searched all 76 records for `completed_at > approved_at` | Zero records show the signature | **UNTESTABLE-VIA-API** (needs a write; no historical fingerprint found) |
| 14 | `GET /admin/extra-works` without `?type` mixes both objects, 39 rows = 32 + 7 | 01 §1.9 | default list, `?type=1`, `/admin/meldings` | 39 total, 32 type-1 + 7 type-2; `?type=1` -> 32; `/admin/meldings` -> 7, all type 2 | **CONFIRMED** |
| 15 | `?customer_building_id=` is a 500, column dropped | 01 §1.9 | `?customer_building_id=3022` | `SQLSTATE[42S22] ... Unknown column 'customer_building_id'` | **CONFIRMED** |
| 16 | The default list treats status 9 like a soft delete | 01 §1.9, 03 §1.2 | default vs status sweep; the SQL echoed in the 500 above | Union of `?statuses=` sweeps = 76; default = 39 = 76 - 37; the leaked SQL literally reads `... and status_id != 9 and deleted_at is null` | **CONFIRMED** |
| 17 | `GET /{id}` does not apply the UCB scope the list applies | 01 §1.9 | - | Requires a second, differently-scoped token | **UNTESTABLE-VIA-API** |
| 18 | `?statuses=N` is an exact status filter | implicit in 01 | `?statuses=2` and `?statuses=1,2` | `?statuses=2` returns record 553 whose `status_id` is **1**; `?statuses=1,2` returns 548 whose `status_id` is **4** | **CONTRADICTED** (new finding: group-header OR-leak) |
| 19 | 3 v1 invoices, 1 v2 invoice | 02 §1.1 | `GET /admin/invoices`, `GET /admin/extra-work-v2-invoices` | `total: 3` (ids 87, 88, 89) and `total: 1` (id 4) | **CONFIRMED** |
| 20 | v1 numbers are client-generated `INV-YYYYMM-NNNN`, a format the server generator cannot produce | 02 §1.4, 03 §1.9 | invoice list | `INV-202605-0001`, `-0002`, `-0003`, all `invoice_date 2026-05-05` | **CONFIRMED** |
| 21 | v2 numbering is `EWV2-YYYY-NNNN` computed `withTrashed()` | 02 §1.4 | v2 invoice list | Single live invoice is `EWV2-2026-0004` - numbers 0001-0003 are missing | **CONFIRMED** (gap consistent with soft-deleted predecessors, **INFERRED**) |
| 22 | `invoices.due_date` is never written and is NULL everywhere | 02 §1.8, 03 §1.6 | invoice list | 3 of 3 `due_date: null` | **CONFIRMED for v1** - nuance: the v2 invoice **does** carry `due_date 2026-03-25` |
| 23 | `invoices.period_start` / `period_end` are NULL on all live invoices | 03 §1.4 | invoice list | 3 of 3 null on both | **CONFIRMED** |
| 24 | The PDF's `Vervaldatum` ignores `due_date` and prints `invoice_date + 1 month` | 02 §1.6 | `GET /admin/invoices/89/preview` (pure read; renders mPDF, writes nothing), content streams decompressed | `Factuurdatum: 05.05.2026`, `Vervaldatum: 05.06.2026`, while the column is NULL | **CONFIRMED** |
| 25 | The PDF prints `Debiteurnummer = customer.id` and `Bonnummer = invoice.id` | 02 §1.6 | same render | `Debiteurnummer : 2054` (the customer id), `Bonnummer : 89` (the invoice id) | **CONFIRMED** |
| 26 | The PDF is a two-page A4 document | 02 §1.6 | same render | **3 pages** (`PDF document, version 1.4, 3 page(s)`; footer reads `Pagina 3/3`) | **CONTRADICTED** |
| 27 | Page 1 is exactly one summary line; page 2+ is the per-work specification | 02 §1.6 | same render | Page 1 has one line: `B3 Amsterdam (May 2026) / 21 meerwerken - Zie bijlage voor specificatie / 1,00 / stuks / EUR 542,16 / 21% / EUR 656,01`. Pages 2-3 list all 21 works | **CONFIRMED** |
| 28 | With `period_*` NULL the template falls back to the month of `invoice_date` ("mei 2026") | 03 §1.4 | same render | It falls back - but prints **"May 2026"**, an English month inside a Dutch document | **CONFIRMED with correction** |
| 29 | The PDF contradicts itself three ways when a discount exists | 02 §1.6 | invoice list | `discount_type` and `discount_value` are NULL on all 3 invoices | **UNTESTABLE-VIA-API** |
| 30 | Four total formulas disagree once `quantity != 1` | 02 §1.9 | all 31 invoice items | Every item is `quantity: "1.00"`; stored subtotal == sum(amount) == sum(amount x qty) on all 3 invoices | **UNTESTABLE-VIA-API** (divergence invisible today, as report 02 itself said) |
| 31 | `invoiceable_items` holds 13 rows, all `type=project`, `entity_type`/`invoice_id`/`invoiced_at` NULL on every row, 12 draft + 1 ready | 02 §1.7 | `GET /admin/invoiceable-items?per_page=200` | 13/13 `type: project`; `entity_type`, `invoice_id`, `invoiced_at`, `period_start`, `period_end`, `scheduled_date`, `project_id`, `task_id` **all null on all 13**; status 12 draft / 1 ready | **CONFIRMED** |
| 32 | `invoiceable_items` contains no extra-work rows | 02 §1.3, 03 §1.1 | `?type=extra_work`, and every other type | `extra_work` 0, `continuous_work` 0, `material` 0, `labour` 0, `machine_rental` 0, `service` 0, `other` 0 | **CONFIRMED** |
| 33 | The v1 path never advances an item past `invoice_draft` | 02 §1.8, §1.10 | `?status=invoice_draft`, `?status=invoiced` | 0 and 0 | **CONFIRMED** (nothing has ever been billed through that path) |
| 34 | The single v2 invoice has no link back to its staging rows | 03 §1.1 | `GET /admin/extra-work-v2-invoices/4` | 3 items, all `invoiceable_item_id: null` | **CONFIRMED** |
| 35 | `ExtraWorkV2InvoiceService::generatePdf()` is a stub; `sendInvoice()` sends nothing | 02 §1.8 | v2 invoice payload | `pdf_path: null`, `pdf_generated_at: null`, `sent_at: null`, status still `draft` | **CONSISTENT** (stub never ran; not positively provable via GET) |
| 36 | `overdue` is unreachable because nothing schedules `checkOverdueInvoices()` | 02 §1.8, 03 §1.5 | v2 invoice payload, today 2026-08-19 | The only v2 invoice is **5 months past** its `due_date 2026-03-25` and its status is unchanged | **CONSISTENT / CONFIRMED by absence** |
| 37 | `GET /admin/invoices/pending-extra-works` is a 500 | 01 §1.9, 02 | direct call | `{"success":false, ... "Internal server error"}` | **CONFIRMED** |
| 38 | `extra_works.invoice_id` is NULL on every status-9 work | 03 §1.3 | all 37 status-9 records | 37 of 37 `invoice_id: null` | **CONFIRMED** |
| 39 | `extra_works.invoice_date` is written by nothing anyone uses; some works carry one with no invoice | 03 §1.3, §1.7 | same | 3 works carry `invoice_date 2025-11-30` with `invoice_id: null` and no invoice line: **437, 438, 444** | **CONFIRMED** |
| 40 | The working link is the reverse one, `invoice_items.extra_work_id` | 03 §1.3 | `?statuses=9` list payload | Each status-9 row carries `invoice_item` and an `invoice` object stamped `laravel_through_key: 442` - a `hasOneThrough` from the item, not from `invoice_id` | **CONFIRMED** |
| 41 | Six works sit at status 9 with no invoice at all: 476, 444, 440, 439, 438, 437 | 03 §1.7 | status-9 set minus all `invoice_items.extra_work_id` | Exactly `[437, 438, 439, 440, 444, 476]` | **CONFIRMED** |
| 42 | Works flip to 9 the moment the invoice is **created**, while it is still a draft | 02 §1.2, 03 §1.2 | invoice 87 (`status: draft`) and its 6 works | 436, 441, 450, 451, 467, 468 - all `status_id: 9` today | **CONFIRMED** |
| 43 | There is no period and no cutoff: a work done long ago can land on today's invoice | 03 §1.4, §1.6 | work 448 vs invoice 89 | Work completed `2025-11-24`, archived `2025-11-24`; invoice dated `2026-05-05`; PDF prints "May 2026" | **CONFIRMED** |
| 44 | The per-product VAT rate is thrown away and hard-coded to 21% | 03 §1.8 | work 448 + item 413 + rendered PDF | Product `tax_rate: "9.00"`; work's own `total_tax: "2.71"`, `total_price: "32.83"`; invoice item `tax_rate: "0.2100"`; PDF line `EUR 30,12 / 21% / EUR 36,45` on a **sent** invoice | **CONFIRMED** |
| 45 | Quantity and unit are lost; every line is `1.00 / stuks` | 03 §1.8 | all 31 items; work 448's product | 31 of 31 `quantity: "1.00"`, `unit_name: "stuks"`, `unit_price: null`; 448's own product unit is `"uren"` | **CONFIRMED** |
| 46 | Labour never reaches an invoice | 03 §1.8 | the 5 invoiced works with labour | 449: labour 412.50 / line 75.30 (**sent**); 468: 361.50 / 75.30; 450, 451, 467: 24.75 / 22.59 each. Total unbilled labour **848.25** | **CONFIRMED** |
| 47 | Only the first product survives onto the line | 03 §1.8 | all 31 invoiced works | **No invoiced work has more than one product** | **UNTESTABLE-VIA-API** |
| 48 | Cancelling a sent invoice orphans its works permanently | 02 §1.5, 03 §1.7 | invoice list | 1 draft + 2 sent, **0 cancelled**, 0 paid | **UNTESTABLE-VIA-API** (no cancelled invoice exists) |
| 49 | Deleting a draft invoice reverts its works to 8 via a **mass update**, which bypasses model events and writes no activity row | 02 §1.5, 03 §1.7 | activity logs of 433, 436, 442, 448, 476 | Repeated `8 -> 9` with **no `9 -> 8` in between** (442: 2026-02-23, 2026-05-05 00:34, 2026-05-05 01:21 - three consecutive `8 -> 9`). 476 shows six consecutive `8 -> 9` on 2025-11-30 | **CONFIRMED** |
| 50 | Nothing about the works changes when an invoice is sent | 03 §1.2 | activity logs vs `sent_at` | Works of invoice 88 went `7 -> 9` at `11:04:58` = invoice 88 `sent_at`; works of invoice 89 at `11:05:00-01` = invoice 89 `sent_at`; works of the still-draft invoice 87 have no such event | **CONTRADICTED** (coupling observed; mechanism not found in code) |
| 51 | All 13 staging rows have `scheduled_date` NULL, so both overdue buckets are empty | 03 §1.6 | staging pool | 13 of 13 null | **CONFIRMED** |
| 52 | Path C writes a free-text `invoice_number` onto period products with no FK | 03 §1.1, §2.14 | code + every reachable v2/continuous-work read endpoint | `markPeriodInvoiced` writes `is_invoiced`, `invoiced_at`, `invoice_number` (validated only as `nullable|string|max:100`) and sets the **schedule**'s `status_id` to **7**. No read endpoint I could reach returns `invoice_number` (0 occurrences in the period and period-detail payloads) | **CONFIRMED** (and explains what status 7 is for) |
| 53 | The browser asks for `statuses=8` to build the "ready to invoice" screen | 03 §1.2 | frontend source | `ExtraWorkInvoiceGroupedView.jsx:157` `const params = { type: 1, statuses: 8, per_page: 200, context: 'admin' };` | **CONFIRMED** |
| 54 | The only writer of `extra_works.invoice_id` is the single-item add path | 03 §1.3 | frontend source | `ExtraWorkInvoiceGroupedView.jsx:182` `apiClient.post('/admin/invoices/'+invoice.id+'/items', { extra_work_id })` - the only caller | **CONFIRMED** |
| 55 | (new) Zero-amount groups are marked invoiced with **no invoice created at all** | not in 01/02/03 | frontend source | `ExtraWorkBulkAllInvoiceModal.jsx:266-280`: `// Archive zero-amount groups without invoice (just update status to 9)` then `apiClient.patch('/admin/extra-works/'+id, { status_id: 9 })` | **NEW - CONFIRMED** |
| 56 | (new) 100% of the staging pool is exposed to the unguarded force-delete | amplifies 02 §1.7 | staging pool | 13 of 13 rows have `notes: "auto_generated_from_task"`, matching the `LIKE 'auto_generated%'` predicate that `generateSubProjects` force-deletes with no status guard | **NEW - CONFIRMED** |

---

## 3. EVIDENCE

### 3.1 The status sweep, and why the published counts are wrong

**DATA** - `GET /admin/extra-works?per_page=1&statuses=N`, `data.pagination.total`:

| statuses= | total returned |
|---|---|
| 1 | 19 |
| 2 | 6 |
| 3 | 1 |
| 4 | 6 |
| 5 | 0 |
| 6 | 0 |
| 7 | 0 |
| 8 | 9 |
| 9 | **37** |
| 10 | 0 |

Sum = 78. That is the number report 01 published. But collecting the **ids** from each sweep
and de-duplicating gives **76 distinct records**, because two ids come back under two
different status filters:

**DATA** - id 553 is returned by both `?statuses=1` and `?statuses=2`, and in **both**
responses its own `status_id` is `1`. Id 548 is returned by both `?statuses=1` and
`?statuses=4`, and in both its `status_id` is `4`.

**DATA** - both are group headers:

```
553  status_id 1  extra_work_group_id 19  group_sequence 1  group_total 12  type 1
548  status_id 4  extra_work_group_id 18  group_sequence 1  group_total 3   type 2
554  status_id 2  extra_work_group_id 19  group_sequence 2  group_total 12  type 1
549  status_id 1  extra_work_group_id 18  group_sequence 2  group_total 3   type 2
```

553 leaks into `?statuses=2` because its sibling 554 is at status 2. 548 leaks into
`?statuses=1` because its sibling 549 is at status 1.

**CODE** - `app/Http/Controllers/Admin/ExtraWorksController.php:101-136`:

```php
// GROUP AWARENESS: For grouped items, show the group header (sequence=1) if ANY member matches the filter
if ($request->has('statuses')) {
    ...
    // Case 2: Group header (sequence=1) - show if any member matches
    $q->orWhere(function ($sub) use ($statusIds) {
        $sub->whereNotNull('extra_work_group_id')
            ->where('group_sequence', 1)
            ->whereExists(function ($exists) use ($statusIds) {
                $exists->select(\DB::raw(1))
                    ->from('extra_works as ew_sibling')
                    ->whereColumn('ew_sibling.extra_work_group_id', 'extra_works.extra_work_group_id')
                    ->whereIn('ew_sibling.status_id', $statusIds);
            });
    });
```

Confirmed again with a combined filter - **DATA** `?statuses=1,2` returns 24 rows, 24
distinct, of which one (548) has `status_id: 4`.

**The true distribution** (from the 76 distinct records' own `status_id`):

| status | true count | type 1 | type 2 |
|---|---|---|---|
| 1 new | 18 | 16 | 2 |
| 2 in_progress | 5 | 5 | 0 |
| 3 resolved | 1 | 1 | 0 |
| 4 closed | 6 | 2 | 4 |
| 5 internal_approval | 0 | 0 | 0 |
| 6 customer_approval | 0 | 0 | 0 |
| 7 invoiced_v2 | 0 | 0 | 0 |
| 8 archived | 9 | 8 | 1 |
| 9 invoiced | 37 | 37 | 0 |
| **total** | **76** | **69** | **7** |

Independent corroboration - **DATA** `GET /admin/extra-works/statistics`:

```json
{"new_extra_works":{"value":18,"filter_value":1,"label":"New"},
 "in_progress_extra_works":{"value":5,"filter_value":2,"label":"In Progress"},
 "resolved_extra_works":{"value":1,"filter_value":3,"label":"Internal Approval"},
 "closed_extra_works":{"value":6,"filter_value":4,"label":"Client Approval"},
 "archived_extra_works":{"value":9,"filter_value":8,"label":"Completed"},
 "invoiced_extra_works":{"value":37,"filter_value":9,"label":"Invoiced"}}
```

18+5+1+6+9+37 = **76**. Note the statistics endpoint offers **only these six statuses** - it
has no tile for 5, 6 or 7, which is itself evidence that v1 recognises six statuses.

**DATA** - `GET /admin/extra-works/meta/config` -> `form_data.statuses_data` (the lookup table,
verbatim, order as returned):

```
1 Nieuw (new)              2 In behandeling (in_progress)     3 Interne goedkeuring (resolved)
4 Goedkeuring door de klant (closed)   5 Interne goedkeuring (internal_approval)
6 Klant goedkeuring (customer_approval)   8 Voltooid (archived)
7 Gefactureerd (invoiced_v2)   9 invoiced (invoiced)
```

Report 01's status table is reproduced exactly, including the two duplicate "Interne
goedkeuring" labels and the untranslated lowercase `invoiced` on 9.

### 3.2 The default list, and status 9 as a soft delete

**DATA** - `GET /admin/extra-works?per_page=200`: `total: 39`, 32 type-1 + 7 type-2,
status distribution `{1: 18, 8: 9, 4: 6, 2: 5, 3: 1}`. Union of the status sweeps = 76.
76 - 39 = 37 = exactly the status-9 population. **The only thing the default list hides is
status 9.**

**DATA** - the 500 from the dead filter leaks the actual WHERE clause:

```
GET /admin/extra-works?customer_building_id=3022
SQLSTATE[42S22]: Column not found: 1054 Unknown column 'customer_building_id' in 'where clause'
(SQL: select count(*) as aggregate from `extra_works`
 where `customer_building_id` = 3022 and `status_id` != 9 and `extra_works`.`deleted_at` is null)
```

`status_id != 9` sits next to `deleted_at is null` in the same clause. Report 01's phrase
"treats status 9 like a soft delete" is literally what the SQL does.

**CODE** - `ExtraWorksController.php:147-150`:

```php
} else {
    // EXCLUDE: Status 9 (Invoiced) - Only exclude when no specific status is requested
    // If statuses parameter is not provided, treat status 9 like soft-deleted records
    $query->where('status_id', '!=', 9);
}
```

**DATA** - `/admin/meldings?per_page=200` -> `total: 7`, all `type: 2`, ids
`[471, 472, 473, 539, 547, 548, 549]`. `/admin/extra-works?type=1` -> `total: 32`.
32 + 7 = 39. Report 01 §1.9 confirmed.

(The melding endpoint inherits the same leak: its per-status sweep gives 3+0+0+4+1+0 = 8
against 7 real rows.)

### 3.3 The lifecycle, proven from activity logs

**DATA** - `GET /admin/extra-works/448/activities`, all 19 rows, oldest first
(user redacted; the log also carries `user_name`, `user_email` and `ip_address` per row):

```
2025-11-24 15:39:11  status_changed  1 -> 2
2025-11-24 15:39:11  date_changed    null -> 2025-11-24 15:39:29   {"date_type":"started_at"}
2025-11-24 15:39:20  date_changed    null -> 2025-11-24 15:39:37   {"date_type":"completed_at"}
2025-11-24 15:39:20  status_changed  2 -> 3
2025-11-24 15:39:31  approved                                       {"approved_at":"2025-11-24 15:39:31","approved_by":"<user> (Admin)"}
2025-11-24 15:39:31  status_changed  3 -> 4
2025-11-30 17:31:00  status_changed  8 -> 9
2025-11-30 18:35:33  status_changed  9 -> 8
2025-11-30 18:38:22  status_changed  8 -> 9
2025-11-30 18:51:16  status_changed  9 -> 8
2025-11-30 19:12:01  status_changed  8 -> 9
2025-11-30 22:27:54  status_changed  9 -> 8
2026-02-17 12:18:27  status_changed  8 -> 9
2026-02-18 12:30:36  status_changed  9 -> 8
2026-02-23 11:10:05  status_changed  8 -> 9
2026-05-05 00:34:36  status_changed  8 -> 9      <- no 9->8 before it
2026-05-05 01:21:26  status_changed  8 -> 9      <- no 9->8 before it
2026-06-04 11:04:42  status_changed  9 -> 7
2026-06-04 11:05:00  status_changed  7 -> 9
```

Five things this proves:

1. **The 1 -> 2 -> 3 -> 4 ladder and its stamps are exactly as report 01 describes.** The
   `date_changed` rows show `started_at` written with the 1 -> 2 move and `completed_at` with
   the 2 -> 3 move, both stamped with a time the client did not send (note the stamp value is
   *later* than the log row's own `created_at`, i.e. `now()` at write time).
2. **The 4 -> 8 archive transition is NOT logged as `status_changed`.** The trail jumps from
   `3 -> 4` straight to `8 -> 9`. The archive-approve endpoint writes a different activity
   shape. Anyone reconstructing a lifecycle from this log will see a hole.
3. **Two consecutive `8 -> 9` rows with no `9 -> 8` between them** (2026-05-05 00:34 and
   01:21). The record went back to 8 silently - which is exactly what a mass update does.
   **CODE** `InvoiceController::destroy():264-271`:
   ```php
   $extraWorkIds = $invoice->items->pluck('extra_work_id')->filter();
   if ($extraWorkIds->isNotEmpty()) {
       ExtraWork::whereIn('id', $extraWorkIds)->update([
           'status_id' => 8, 'invoice_id' => null, 'invoice_date' => null,
       ]);
   }
   ```
   A query-builder `update()` fires no Eloquent events, so the observer never runs and no
   activity row is written. Report 02/03's claim is confirmed, and the fingerprint is visible
   in the log.
4. **A v1 record held status 7.** `9 -> 7` then `7 -> 9`, on the v1 `extra_works` row.
5. **Status 9 is not terminal in practice.** This one record has been invoiced and
   un-invoiced eight times.

**DATA** - the same 9 -> 7 -> 9 pattern, and its correlation with `sent_at`:

| work | on invoice | invoice `sent_at` | `9 -> 7` at | `7 -> 9` at |
|---|---|---|---|---|
| 433 | 88 (`INV-202605-0002`, sent) | 2026-06-04 11:04:58 | 11:04:42 | **11:04:58** |
| 449 | 88 | 2026-06-04 11:04:58 | 11:04:42 | **11:04:58** |
| 442 | 89 (`INV-202605-0003`, sent) | 2026-06-04 11:05:00 | 11:04:42 | **11:05:00** |
| 448 | 89 | 2026-06-04 11:05:00 | 11:04:42 | **11:05:00** |
| 466 | 89 | 2026-06-04 11:05:00 | 11:04:43 | **11:05:01** |
| 436 | 87 (`INV-202605-0001`, **draft**) | - | none | none |
| 468 | 87 (draft) | - | none | none |
| 437 | none (orphan) | - | none | none |

The works of the two invoices that were sent all made the round trip; the works of the
invoice that is still a draft did not. **CODE** - `InvoiceController::sendInvoice():336-387`
updates only `status`, `pdf_path`, `pdf_generated_at`, `sent_at` on the invoice row and
touches no extra work. **CODE** - `frontend/src/pages/finalosius/invoices/components/InvoiceDetailActions.jsx:55`
is a bare `await apiClient.post('/admin/invoices/'+invoice.id+'/send')` with no follow-up
call. **CODE** - `app/Observers/` contains no Invoice observer (Building, Contact, Customer,
Employee, ExtraWorkComment, ExtraWork, User). So the code I read cannot produce this
correlation. **Flagged as unresolved in §5.**

### 3.4 Stamp presence across the whole population - the "no state machine" proof

**DATA** - all 76 records, by status:

| status | records | with `completed_at` | with `approved_at` | with `planed_by` |
|---|---|---|---|---|
| 3 | 1 | 1 | **0** | 1 |
| 4 | 6 | **0** | 4 | 5 |
| 8 | 9 | 9 | **1** | 9 |
| 9 | 37 | 37 | 37 | 37 |

- **Six records at status 4 ("Goedkeuring door de klant") have no `completed_at`.** Four are
  Meldings (471, 472, 473, 548) taking the documented short path - report 01 §1.3 confirmed.
  Two are **type-1 Extra Works** (475, 566), which means an Extra Work reached status 4
  without ever passing status 3.
- **Eight of the nine records at status 8 ("Voltooid") have no `approved_at`** (539-546, a
  single group archived within four seconds on 2025-12-23 15:55:28-31). They reached the end
  of the ladder without the customer-approval step ever being stamped.
- All 37 invoiced records carry the full set, so the happy path does stamp everything.

**DATA** - archive back-fill, all 9 status-8 records:

```
539 req 2025-12-23T15:55:28Z  app 2025-12-23T15:55:28Z  rej null   same
540 req 2025-12-23T15:55:29Z  app 2025-12-23T15:55:29Z  rej null   same
541 ... 546  (identical pattern, 15:55:29 - 15:55:31)
567 req 2026-08-17T00:04:55Z  app 2026-08-17T00:04:55Z  rej null   same
```

9 of 9 identical to the second - report 01's back-fill claim confirmed.

**DATA** - "Name (Role)" strings, record 567: `planed_by`, `started_by`, `completed_by`,
`approved_by`, `archive_requested_by`, `archive_approved_by` all hold
`"<user> (Admin)"`; `created_by` holds `"<user> (Admin)"` for a different user. Free text,
not ids - confirmed.

### 3.5 The entity config, fetched live

**DATA** - `GET /admin/extra-works/meta/config` -> `entity_config.fields`, all 39 keys:

```
approved_at, approved_by, archive_approved_by, archive_rejected_by, archive_rejection_reason,
category_id, completed_at, completed_by, created_at, created_user_id, customer_buildings,
customer_department_id, customer_start_date, customer_works_type_id, deadline_at, description,
file_1, file_2, file_3, file_4, hours_planed, hours_worked, invoice_date, invoice_id,
is_customer_work, planed_at, planed_by, planed_end_at, planed_start_at, priority_id,
requested_at, requested_by, started_at, started_by, status_id, title, type,
user_department_id, user_id
```

- **Not one field carries a `validation` key.** Report 01 §2.3's central claim - that
  `getValidationRules()` produces an empty array and `Validator::make($request->all(), [])`
  always passes - is confirmed from the server's own published config.
- `upload_is_required`, `notes_is_required` and `completion_notes` appear **zero times** in
  the entire 17.8 KB payload. They cannot be written through create/update.
- `file_1..file_4` **are** in the allow-list and are `fillable`. They are writable but appear
  in no read payload - dead on the read side only.
- `invoice_id` and `invoice_date` are fillable through the generic update, which is how a
  human could set an `invoice_date` on a work that has no invoice (three such works exist).

**DATA** - all 76 records: `upload_is_required` true on **0**, `notes_is_required` true on
**0**. Report 01's "0 of 78" is right in substance; the denominator is 76.

### 3.6 The invoices, end to end

**DATA** - `GET /admin/invoices?per_page=100` -> `total: 3`:

| id | number | date | due | period | status | subtotal | tax | total | src | items | pdf | sent_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 89 | INV-202605-0003 | 2026-05-05 | null | null/null | sent | 542.16 | 113.85 | 656.01 | extra_work | 21 | yes | 2026-06-04 11:05:00 |
| 88 | INV-202605-0002 | 2026-05-05 | null | null/null | sent | 301.20 | 63.25 | 364.45 | extra_work | 4 | yes | 2026-06-04 11:04:58 |
| 87 | INV-202605-0001 | 2026-05-05 | null | null/null | **draft** | 233.43 | 49.02 | 282.45 | extra_work | 6 | no | null |

0 cancelled, 0 paid. `discount_type` and `discount_value` NULL on all three.
All three share one `invoice_date` - consistent with a single bulk-modal session whose
counter ran 0001, 0002, 0003.

**DATA** - all 31 invoice items: `tax_rate` `"0.2100"` on 31 of 31; `quantity` `"1.00"` on
31 of 31; `unit_name` `"stuks"` on 31 of 31; `unit_price` `null` on 31 of 31;
`invoiceable_item_id` `null` on 31 of 31; `source_type` `null` on 31 of 31.

Distinct works reached through `invoice_items.extra_work_id`: **31**
`[433,434,435,436,441,442,443,445,446,447,448,449,450,451,452,453,454,455,456,457,458,459,460,461,462,463,464,465,466,467,468]`.
Status-9 population: **37**. Difference: **6** = `[437,438,439,440,444,476]`.

**DATA** - walking the link **forward** (work -> invoice), work 442 from `?statuses=9`:

```json
"invoice_id": null,
"invoice_date": null,
"invoice_item": {"id":408,"invoice_id":89,"extra_work_id":442,"amount":"15.06",
                 "tax_rate":"0.2100","unit_name":"stuks","quantity":"1.00"},
"invoice": {"id":89,"invoice_number":"INV-202605-0003","status":"sent",
            "invoice_date":"2026-05-05T00:00:00.000000Z","laravel_through_key":442}
```

The `laravel_through_key` proves the `invoice` object is a `hasOneThrough` reached **through
`invoice_items`**, not through the `invoice_id` column - which is null. Report 03 §1.3
confirmed exactly.

**DATA** - the same relations are **absent** from `GET /admin/extra-works/448` (the detail
endpoint): `invoice_item` and `invoice` are not in the payload at all. The reverse link is
only eager-loaded when `?statuses=` contains 9 (**CODE** `ExtraWorksController.php:138-145`).
A caller reading the detail endpoint alone cannot tell whether the work is on an invoice.

**DATA** - walking the link **backward** (invoice -> work), invoice 89 item 413:
`extra_work_id: 448, amount: "30.12", tax_rate: "0.2100"`. And `GET /admin/extra-works/448`:

```
status_id 9 ("invoiced")   invoice_id null   invoice_date null
total_products_cost 30.12  total_labor_cost 0  total_hours 1
total_subtotal "30.12"  total_tax "2.71"  total_price "32.83"
products: [{id:404, price:"30.12", tax_rate:"9.00", quantity:"1.00", unit_id:1, is_fixed_price:true}]
financial_summary: {"subtotal":30.12,"total_tax":2.71,"total":32.83,"currency":"EUR",
                    "items":[{... "tax_rate":9, "line_tax":2.71, "line_total_with_tax":32.83, "unit":"uren" ...}]}
```

The work says 9% / 2.71 / unit "uren". The invoice line says 21% / unit "stuks". **The round
trip does not survive.**

### 3.7 The rendered PDF - the customer-facing proof

`GET /admin/invoices/89/preview` is a pure read: **CODE** `InvoiceController::previewInvoice():394-460`
loads the invoice, renders `pdf.invoice-vertical` through mPDF and returns the bytes with
`$mpdf->Output('', 'S')` - no `update()`, no `Storage::put`, no DB write. (I deliberately did
**not** call `/download`, `/send` or `/regenerate-pdf`.)

**DATA** - `file` reports `PDF document, version 1.4, 3 page(s)`. Text extracted by
inflating the content streams:

Page 1 header block:
```
FACTUUR
Factuurnummer  : INV-202605-0003
Factuurdatum   : 05.05.2026
Vervaldatum    : 05.06.2026
Debiteurnummer : 2054
Bonnummer      : 89
```
(the address block above it carries the customer's name and postal address - not reproduced)

Page 1 summary line and totals:
```
ID | Omschrijving                                                  | Aantal | Eenheid | Prijs     | BTW | Totaal
1  | B3 Amsterdam (May 2026)                                       | 1,00   | stuks   | EUR 542,16| 21% | EUR 656,01
     21 meerwerken - Zie bijlage voor specificatie
Subtotaal: EUR 542,16    BTW (21%): EUR 113,85    Totaal: EUR 656,01
```

Page 2-3 specification (extract, including the 9%-VAT work):
```
EW  | Omschrijving                                   | Aantal | Eenh. | Prijs     | BTW | Totaal
442 | ... The Jack eindschoonmaak [WK45-04.11.2025:18:00-op] | 1,00 | stuks | EUR 15,06 | 21% | EUR 18,22
448 | ... Atrium eindschoonmaak  [WK45-07.11.2025:08:00-op] | 1,00 | stuks | EUR 30,12 | 21% | EUR 36,45
...
Subtotaal: EUR 542,16   BTW (21%): EUR 113,85   Totaal specificatie: EUR 656,01
```

What this settles:

- `Vervaldatum 05.06.2026` = `invoice_date + 1 month`, computed in the template, while the
  `due_date` column is NULL. **Report 02 §1.6 point 1 confirmed on the real document.**
- `Debiteurnummer` is the raw `customers.id` and `Bonnummer` is the raw `invoices.id`.
  **Confirmed.**
- The period fallback fires and prints **"May 2026"** - English - in a Dutch invoice. Report
  03 predicted "mei 2026"; the substance (period derived from `invoice_date`, unrelated to
  when the work was done - these works are from **week 45-47 of 2025**) is confirmed, the
  language detail is corrected.
- The document is **three** pages, not two. The page count follows the item count.
- Line 448 prints `21%` and `EUR 36,45`, against the work's own `9%` and `EUR 32,83`. The
  single `BTW (21%)` summary block hides it. **The VAT loss is on a document that was sent.**
- There is one summary line on page 1 with `Aantal 1,00 / Eenheid stuks` regardless of what
  was actually sold, and the works whose products are priced per `uren` are printed as
  `stuks`. **Confirmed.**

### 3.8 The staging pool and the v2 table

**DATA** - `GET /admin/invoiceable-items?per_page=200` -> `total: 13`. Field census over all 13:

```
type:          {project: 13}          status: {draft: 12, ready: 1}
entity_type:   {null: 13}             invoice_id:  {null: 13}     invoiced_at:  {null: 13}
period_start:  {null: 13}             period_end:  {null: 13}     scheduled_date:{null: 13}
project_id:    {null: 13}             task_id:     {null: 13}
notes:         {"auto_generated_from_task": 13}
tax_rate:      {"21.00": 13}          quantity:    {"1.00": 13}
unit_price:    {0.00: 2, 400: 2, 800: 3, 1200: 2, 1600: 1, 2400: 2, 4372: 1}
ids: [554,555,556,557,558,559,560,561,562,563,564,565,566]
```

Type sweep (**DATA**): `extra_work` 0, `continuous_work` 0, `material` 0, `labour` 0,
`machine_rental` 0, `service` 0, `other` 0. Status sweep: `draft` 12, `ready` 1,
`invoice_draft` **0**, `invoiced` **0**.

**CODE** - `InvoiceableItemController::index():17-100` applies no default type or status
filter, so 13 is the entire non-soft-deleted pool.

Two consequences the tier-1 reports understate:

- Not one item has ever reached `invoice_draft`, so the `POST /admin/invoices/from-invoiceable-items`
  path has **never been used in this environment**. Every claim about its numbering, its
  `Invoice::recalculateTotals()` quantity bug and its double-billing hole is therefore
  structurally true but has never fired.
- **All 13 rows carry `notes: "auto_generated_from_task"`**, exactly matching the
  `notes LIKE 'auto_generated%'` predicate that `PrjProjectsController::generateSubProjects`
  **force-deletes with no status guard**. The blast radius of that bug is currently 100% of
  the pool.

**DATA** - `GET /admin/extra-work-v2-invoices` -> `total: 1`:

```
id 4  EWV2-2026-0004  customer 2029  invoice_date 2026-02-23  due_date 2026-03-25
status draft  subtotal 8058.77  tax 1692.34  discount 0.00  total 9751.11
pdf_path null  pdf_generated_at null  sent_at null  paid_at null  cancelled_at null
items: 3, all type "extra_work", all invoiceable_item_id NULL
  10  6428.57 + 1350.00 = 7778.57  period 2026-02-10 .. 2026-02-28
  11  1000.00 +  210.00 = 1210.00  period 2026-02-12 .. 2026-02-28
  12   630.20 +  132.34 =  762.54  period 2026-02-28 .. 2026-02-28  "Termijn 1 van 5"
```

- `invoiceable_item_id` null on 3 of 3 - the v2 invoice has **no** link back to staging.
  Report 03 §1.1 confirmed.
- The v2 items are the only place in this system where a real **period** is stored per line.
- `EWV2-2026-0004` is the only live row: numbers 0001-0003 are gone (**INFERRED**: soft-deleted,
  consistent with `generateInvoiceNumber()` using `withTrashed()`).
- Arithmetic checks out here: 6428.57+1000.00+630.20 = 8058.77 and +1692.34 = 9751.11. The
  double-subtracted-discount bug report 02 describes cannot fire because `discount_amount` is
  0.00 - **UNTESTABLE**.
- The invoice is **five months past its `due_date`** and still `draft`. Nothing has ever run
  `checkOverdueInvoices()`.

**DATA** - `GET /admin/extra-works-v2?per_page=100` -> 6 works. Two are `price_type: fixed`
(117 at 1500.00, 114 at 5000.00 with `billing_type monthly`, `billing_day 12`,
`billing_start_date 2026-02-02`, `billing_end_date 2026-06-30`). `GET .../114/billing-summary`:

```json
{"income_total":5000,"income_count":1,"total_items":0,"invoiced_count":0,"draft_count":0,
 "total_amount":0,"balance":5000,"billing_type":"monthly","billing_day":12,
 "billing_month_count":5,"items":[]}
```

The screen computes `billing_month_count: 5` and then shows `items: []`. **The billing plan
is displayed but no staging rows were ever generated.** Same for 117 (`balance 1522.59`,
`items: []`).

### 3.9 Path C, and what status 7 is actually for

**DATA** - `GET /admin/extra-works-v2/113/periods/431/products` returns
`{"success":false,"message":"DEPRECATED: Use GET /api/admin/continuous-works/{id}/periods/{periodId} instead"}`.
The replacement, `GET /admin/continuous-works/113/periods/431`, returns a payload with
`period`, `entries_by_employee`, `materials`, `summary` - and the string `invoice_number`
appears **zero times** in it. Same for `GET /admin/continuous-works/113` (24 periods, all
`status: "niet_gestart"`, `invoice_number` count 0).

**CODE** - `ExtraWorksV2Controller::markPeriodInvoiced():5217-5265`:

```php
$validated = $request->validate([
    'invoice_number' => 'nullable|string|max:100',
    'product_ids' => 'nullable|array',
    'product_ids.*' => 'exists:extra_work_v2_period_products,id',
]);
...
$query->update([
    'is_invoiced' => true,
    'invoiced_at' => now(),
    'invoice_number' => $validated['invoice_number'] ?? null,
]);
// Update period status to invoiced (7)
$period->update(['status_id' => 7, 'updated_by' => auth()->id()]);
```

Confirms report 03's Path C in full: free text, `nullable` (so it can be marked invoiced with
**no number at all**), no foreign key, no existence check against `invoices`. And it names the
consumer of status 7: **`extra_work_v2_schedules.status_id`**, not `extra_works.status_id`.
That is why the shared `t_ticket_status` table carries a "Gefactureerd" row that v1 does not
own - and why a human choosing "Gefactureerd" from a v1 status dropdown picks the wrong one
(§3.3).

### 3.10 The two client-side paths that decide everything

**CODE** - `frontend/src/pages/finalosius/extra-works/components/ExtraWorkInvoiceGroupedView.jsx:157`:
```js
const params = { type: 1, statuses: 8, per_page: 200, context: 'admin' };
```
The "ready to invoice" screen is `type=1, statuses=8`, capped at 200 - **CODE**-confirms report
03 §1.2, and note the hard 200 cap.

Line 707 of the same file uses `statuses: 9` for the invoiced view. Line 182 is the only
caller of `POST /admin/invoices/{id}/items` - the sole writer of `extra_works.invoice_id`.

**CODE** - `frontend/src/pages/finalosius/extra-works/modals/ExtraWorkBulkAllInvoiceModal.jsx:240,266-280`:

```js
const invoiceNumber = generateInvoiceNumber(invoicePrefix, i + 1);
...
const response = await apiClient.post('/admin/invoices', payload);
...
// 2. Archive zero-amount groups without invoice (just update status to 9)
if (zeroAmountGroups.length > 0) {
  for (const group of zeroAmountGroups) {
    for (const item of group.items) {
      await apiClient.patch(`/admin/extra-works/${item.id}`, { status_id: 9 });
    }
  }
}
```

Two things: the invoice number is generated in the browser from a loop index (confirming the
collision analysis in reports 02 and 03), and there is an **explicit, intended path that marks
works "invoiced" with no invoice behind them**. This is a fourth "invoiced" mechanism that none
of the tier-1 reports named. It does not by itself explain the six orphans (437, 438, 439, 440,
444, 476 all have non-zero `total_products_cost`, e.g. 45.18 and 15.06), so those most likely
came from the silent mass-update reverts in §3.3 - **INFERRED**.

---

## 4. CONNECTION MAP AS THE LIVE DATA DRAWS IT

```
                     GET /admin/extra-works              GET /admin/extra-works?statuses=9
                     (39 rows: 32 EW + 7 Melding)        (37 rows, the hidden half)
                              |                                     |
                     status_id != 9  <---- the ONLY default filter --+
                              |
    +---------------------------------------------------------------+
    |                        extra_works  (76 rows)                  |
    |  status 1:18  2:5  3:1  4:6  5:0  6:0  7:0  8:9  9:37          |
    |  invoice_id : NULL on 76/76        invoice_date: 3 non-null,   |
    |                                     all pointing at nothing    |
    +----+------------------------------------------+---------------+
         |                                          |
         | (A) POST /admin/invoices                 | (D) PATCH /admin/extra-works/{id}
         |     browser-made number                  |     {status_id: 9}  - zero-amount
         |     server: status_id -> 9               |     groups, NO invoice created
         v                                          v
    invoice_items.extra_work_id  ---------->  6 works at status 9
    (31 rows, THE only real link)             with no line, no invoice
         |   tax_rate hard 0.2100 (31/31)
         |   quantity 1.00 / unit "stuks" (31/31)
         |   amount = total_products_cost ONLY  (labour 848.25 EUR never crosses)
         v
    invoices (3)  87 draft / 88 sent / 89 sent   0 cancelled  0 paid
         |   due_date NULL 3/3   period_start/end NULL 3/3
         |
         +--> PDF (mPDF, pdf.invoice-vertical)
              Vervaldatum := invoice_date + 1 month   (due_date column ignored)
              Debiteurnummer := customers.id          Bonnummer := invoices.id
              period line := month name of invoice_date -> "May 2026"
              3 pages for 21 items

    ---------------------------------------------------------------------------

    invoiceable_items (13)  100% type=project, 12 draft + 1 ready
         | invoice_id NULL 13/13   invoiced_at NULL 13/13   scheduled_date NULL 13/13
         | notes 'auto_generated_from_task' 13/13  -> 100% inside the unguarded forceDelete
         |
         X  no link reaches extra_work_v2_invoices: its 3 items have invoiceable_item_id NULL

    extra_work_v2_invoices (1)  EWV2-2026-0004  draft, 5 months past due_date
         | pdf_path NULL, sent_at NULL   (generator is a stub)
         | items carry REAL period_start/period_end - the only periods in the system

    extra_work_v2_period_products.invoice_number  <- free text, nullable, no FK
         ^ written by PUT /extra-works-v2/{id}/periods/{pid}/mark-invoiced
           which also sets extra_work_v2_schedules.status_id = 7
           (this is what status 7 "Gefactureerd" belongs to - NOT v1)
```

**What action changes what, as verified:**

| Action | Verified effect | Evidence |
|---|---|---|
| `POST /admin/invoices` (bulk modal) | invoice created `draft`; each work -> `status_id 9`; `invoice_id` NOT set | invoice 87 is draft and its 6 works are all at 9 (DATA) |
| `POST /admin/invoices/{id}/items` | the only writer of `extra_works.invoice_id` - never used here | 0/76 non-null (DATA) |
| `DELETE /admin/invoices/{id}` (draft only) | works -> 8, links cleared, **no activity row** | consecutive `8 -> 9` with no `9 -> 8` in five separate trails (DATA) + mass `update()` (CODE) |
| `POST /admin/invoices/{id}/send` | invoice -> `sent`, PDF written. Code touches no work - **yet works moved `7 -> 9` at the exact `sent_at` second** | §3.3 (DATA vs CODE conflict) |
| `PATCH /admin/extra-works/{id} {status_id:9}` | work marked invoiced with no invoice | ExtraWorkBulkAllInvoiceModal.jsx:274 (CODE) |
| `PUT /extra-works-v2/{id}/periods/{pid}/mark-invoiced` | free-text `invoice_number` on products + schedule status 7 | CODE, no reader found |
| `?statuses=N` on the list | returns matching rows **plus group headers whose siblings match** | 553 and 548 (DATA) |

---

## 5. COULD NOT DETERMINE

1. **What moved the works back to status 9 at the exact second each invoice was sent.**
   This is the biggest open item. `sendInvoice()` writes only to the invoice row
   (`InvoiceController.php:336-387`), the frontend send handler issues one POST
   (`InvoiceDetailActions.jsx:47-73`), and there is no Invoice observer in `app/Observers/`.
   Yet works of invoice 88 flipped `7 -> 9` at `11:04:58` = its `sent_at`, and works of
   invoice 89 at `11:05:00-01` = its `sent_at`, while the draft invoice's works did not move.
   **To close:** read `app/Models/Invoice.php` for a `booted()` hook or a model event; grep
   the whole `app/` tree for `status_id.*9` outside `InvoiceController`; check for a second
   frontend build or a mobile client; and read the raw `extra_work_activities` rows for
   2026-06-04 11:04-11:05 across ALL works to establish whether the flip was one bulk call per
   invoice or 25 individual calls (the `ip_address` and `user_id` on those rows would settle it).

2. **What set roughly twenty-five v1 works to status 7 at 11:04:42.** The transition is
   logged, so it happened; the writer is not identified. Candidates are
   `PUT /admin/extra-works/{id}/status` (validates only `exists:t_ticket_status,id`), the bulk
   group-status endpoint, or a kanban drag. **To close:** the same activity-row dump, plus a
   grep of the frontend for a status picker that offers the raw `statuses_data` list (which
   contains both "Gefactureerd" (7) and "invoiced" (9)).

3. **Whether statuses 5 and 6 have ever been written to a v1 row.** I proved status 7 was.
   For 5 and 6 I only proved there are no rows there **today**. **To close:** query
   `extra_work_activities` for `action = 'status_changed'` with `new_value in (5,6)` - there is
   no API filter for that, so it needs a DB read or an endpoint that dumps activities globally.

4. **The revert re-stamping bug (report 01 §1.5).** Untestable without a write. I looked for a
   historical fingerprint (`completed_at > approved_at`) across all 76 records and found **zero**
   instances, which neither confirms nor refutes the code reading. **To close:** a controlled
   `PUT` on a scratch record in a non-production copy.

5. **What happens to works when a sent invoice is cancelled.** There is no cancelled invoice in
   this environment (3 invoices: 1 draft, 2 sent). The claim rests entirely on
   `InvoiceController::updateStatus()`. **To close:** a write test, or a database with a
   cancelled invoice in it.

6. **The multi-product invoice line ("only the first product survives").** Not one of the 31
   invoiced works has more than one product, so the behaviour has never occurred here. Record
   567 (status 8, `products_count: 2`, `total_products_cost 97.89`) is the candidate: if it is
   ever invoiced, its line should show one description and one unit. **To close:** invoice it,
   or read a database where a multi-product work was invoiced.

7. **The discount contradictions and the quantity-dependent total divergence.** All three
   invoices have NULL discount and every item has `quantity 1.00`, so none of the four total
   formulas can be told apart from the outside. **To close:** a write test with a discount and
   a quantity != 1.

8. **Whether `GET /admin/extra-works/{id}` really skips the UCB scope the list applies.**
   Requires a second token with a narrower scope. I had one identity only. **To close:** a
   second credential, or a code read of `applyUcbPermissions()` call sites (report 01 already
   did the latter).

9. **Whether the six orphaned status-9 works came from silent mass-update reverts or from the
   zero-amount PATCH path.** Their amounts are non-zero (45.18, 15.06), which argues against the
   zero-amount branch, but 476's trail shows six consecutive `8 -> 9` events with no matching
   reverts, which fits the silent-mass-update explanation. **To close:** the full activity dump
   for those six ids with `user_id`/`ip_address`, correlated against the deleted invoices.

10. **Soft-deleted rows everywhere.** Every count in this report is of non-soft-deleted rows,
    because every list endpoint applies `deleted_at is null`. There is no `?with_trashed`
    parameter I could reach. Missing invoice numbers `EWV2-2026-0001..0003` are almost
    certainly soft-deleted rows. **To close:** a `withTrashed` endpoint or a DB read.

11. **Report 02's PDF page-1-vs-page-2 discount analysis.** I verified the layout, the header
    fields, the fallback period and the single summary line on a real render, but not the
    discount arithmetic, for the reason in item 7.

### Where I stopped

I completed the full tier-1 checklist: 56 claims tested, **43 CONFIRMED, 5 CONTRADICTED, 8
UNTESTABLE-VIA-API**. I did not extend into reports 04-07 (hours, products/pricing,
people/permissions, groups/files/notifications) - that was out of scope for this pass and is
untouched. I made no write of any kind; the only non-JSON call was
`GET /admin/invoices/89/preview`, which renders a PDF in memory and persists nothing
(`InvoiceController.php:394-460`, verified before calling).

---

# PART 2 - CONTRADICTION SWEEP (V2)

Agent V2. Ran last and alone. I read all nine reports (01-09) in full, then went back to
`/tmp/osius-ref/{backend,frontend}` and to the live API and **re-read every disputed
file:line myself**. Nothing was modified; every API call was a GET through the wrapper.

Where two agents disagreed I did not pick the more confident one. I opened the file.

Labels: **CODE** = I read that path:line in this sweep and quote it. **DATA** = a GET I
made in this sweep. **INFERRED** = stated as such.

Personal data redacted throughout: users appear as numeric ids only.

## 2.0 Headline of this sweep

Three things came out of it that change how the corpus should be read:

1. **The `roles.slug` question - flagged as an open question by BOTH report 06 and report
   07, and load-bearing for four separate claims - is now CLOSED.** The column exists and
   holds **underscored** values. That makes report 07's central inference ("RecipientDeterminer
   matches nobody") **partly wrong**: it matches customers and misses only the two location
   roles. It also makes report 06's comment-delete and attachment-delete role checks
   **correct** rather than uncertain.
2. **Report 06's headline mechanism for invoicing being admin-only is wrong**, though its
   conclusion is right. Every role has an `invoices` row; the non-admin ones are mask **0**,
   not absent. In the same call I closed report 06's own COULD-NOT-DETERMINE #4 (the three
   user-less roles) and found something worse than 06 reported: **`customer_manager`, a
   customer-type role, also holds `users=23` and can therefore mint an admin.**
3. **Report 09 PART 1's biggest open question - "what moved the works at the exact second
   each invoice was sent" - should be re-framed, not left as a hidden coupling.** An
   exhaustive writer sweep plus the activity rows' own `user_id` show an authenticated
   human/automation drove both legs through the ordinary API. There is no undiscovered
   invoice-to-work mechanism in either repository.

---

## 1. CORRECTIONS LIST

Format: **who said what** -> **what the source actually says** -> **MY RULING**.

### C-1. The group "Goedkeuren" button. Report 01 is wrong; report 07 is right.

- **Report 01** (§2.4, and the transition table in §3.2): "the group 'Goedkeuren' button
  (source 3 -> target 4, `WorkflowActionsBar.jsx:302`) sets `status_id = 4` on N records with
  no `approved_at`, no `approved_by`, no system comment, no broadcast, no FCM, no activity
  row, and no draft-attachment publication", via `PUT /groups/{groupId}/status`.
- **Report 07** (§4.1): that is wrong on the endpoint, the target status and the events.

**What the source says.** CODE - `frontend/src/pages/finalosius/extra-works/components/WorkflowActionsBar.jsx:302`
is not a call at all:

```js
    const found = groupData.group.status_distribution.find((s) => s.status_id === statusId);
```

CODE - the same file `:307-311`:

```js
  const groupActionConfig = {
    1: { targetStatus: 2, icon: 'mdi:calendar-clock', label: 'Plannen', color: 'primary' },
    2: { targetStatus: 3, icon: 'mdi:check-circle', label: 'Voltooien', color: 'success' },
    3: { targetStatus: 4, icon: 'mdi:check-decagram', label: 'Goedkeuren', color: 'secondary' },
  };
```

CODE - `:365`: `onClick={() => onGroupBulkAction(status.status_id, config.targetStatus, status.count)}`

CODE - `frontend/src/pages/finalosius/extra-works/detail.jsx:461-466`, including its own comment:

```js
    // Status 3 (Completed) -> Status 4 (Approved) = Bulk Archive/Approve (goes to status 8)
    ...
    } else if ((sourceStatusId === 3 && targetStatusId === 4) || (sourceStatusId === 4 && targetStatusId === 8)) {
      setBulkArchiveApproveModalOpen(true);
    }
```

CODE - `ExtraWorkBulkArchiveApproveModal.jsx:77`:

```js
        const archiveResponse = await apiClient.post(`/admin/extra-works/${work.id}/archive/approve`, payload);
```

**RULING: report 07 is correct on every point.** The group bar loops the ordinary
per-record `POST /{id}/archive/approve`, so it *does* stamp, *does* fire model events and
*does* write system comments - and it lands on **status 8**, skipping 4 entirely. Report
01's cited line is a helper. Report 01 reached the right *outcome* for drafts (they are
never published) by the wrong route. `PUT /admin/extra-works/groups/{groupId}/status` is
real and event-free, but its only caller is `GroupEditModal.jsx:112`.

**Consequence for the corpus:** every downstream statement that "the group approve button
is a silent mass update" (it appears in 01 §2.4, 01 §3.2 and is echoed in the collected
claims) must be struck. Report 07 §3.5's version - group-processed work enters the
invoicing pool at status 8 with `approved_at` null and drafts unpublished - is the correct
one, and report 09's DATA on group 17 (8 members at status 8, `approved_at` null,
`archive_approved_at` one second apart) corroborates it.

### C-2. `extra_work_groups.building_id` is not a defect. Report 01 wrong, report 07 right.

- **Report 01** §2.4 lists it among the defects: "The group's `building_id` is populated with
  a `customer_buildings.id`, not a `buildings.id`."

**What the source says.** CODE - `database/migrations/2025_12_23_100800_create_extra_work_groups_table.php:24`:

```php
            $table->foreign('building_id')->references('id')->on('customer_buildings')->nullOnDelete();
```

CODE - `app/Models/ExtraWorkGroup.php:41`:

```php
        return $this->belongsTo(CustomerBuilding::class, 'building_id');
```

**RULING: report 07 is correct.** Writing a customer-building id is exactly what the FK and
the relation require. The column is badly *named*; the value is right. The real defect is
report 07's: nothing reads it.

### C-3. Which status is labelled "Gefactureerd". Report 03 wrong; report 06 aimed its correction at the wrong report.

- **Report 01** §1.2 got it right: "Status 7, not 9, is the one labelled 'Gefactureerd'...
  The status that v1 actually means by 'invoiced' is 9, whose label is the untranslated
  lowercase string `invoiced`."
- **Report 03** §1.1 and §1.2 say the opposite in passing: "stamps every one of those works
  to status 9 (Gefactureerd)".
- **Report 06** §5 records a "PARTIALLY CONTRADICT" against "tier-1", stating "Tier-1
  reported 9 = 'Gefactureerd'".

**RULING.** The substance (7 = `invoiced_v2` "Gefactureerd", 9 = `invoiced`) is settled by
report 09 PART 1 verdict #1 from `GET /admin/extra-works/meta/config` and I do not re-test
it. But report 06's correction is **mis-addressed**: report 01 already said this. The
report that needs correcting is **03**, whose §1.1/§1.2 parenthetical "(Gefactureerd)"
against status 9 is wrong. Anyone reading 03 in isolation is misled about which status a
v1 operator picks from the dropdown - which is precisely the mistake report 09 PART 1 §3.3
caught in the live activity log (works driven 9 -> 7 on 2026-06-04).

### C-4. "RecipientDeterminer matches nobody." Report 07's central inference is PARTLY WRONG - and the underlying open question is now closed.

- **Report 07** §2.6 and COULD-NOT-DETERMINE #1: the constants are hyphenated while every
  other role check uses underscores, the `/admin/roles` payload has no `slug` field and
  `Role::$fillable` does not list one, therefore "**INFERRED:** `getRoleUsers` matches
  nobody, so every model-event notification resolves to an empty recipient list."
- **Report 06** COULD-NOT-DETERMINE #5 leaves the slug values open too, yet 06 §3.2 asserts
  as fact that comment deletion is "admin + location_manager only (`ExtraWorkService:427`)"
  and attachment deletion is "admin only (`role->slug === 'admin'` at `:1675`)" - both of
  which depend on the same unverified column.

**What the source says.** CODE - `app/Services/Notification/RecipientDeterminer.php:25-27`:

```php
    const ROLE_LOCATION_CHEF = 'location-chef';
    const ROLE_LOCATION_MANAGER = 'location-manager';
    const ROLE_CUSTOMER = 'customer';
```

CODE - the same file, `getRoleUsers`: `$query->where('slug', $roleSlug);`

CODE - `app/Models/Role.php:15-34` - `$fillable` contains `name, guard_name, display_name,
display_name_tr/en/bg/nl, description, description_tr/en/bg/nl, type_id, level, is_system,
icon, color, created_by, updated_by`. **No `slug`.** Report 07 is right that the model does
not declare it.

**DATA - the column nevertheless exists and I read its values.**
`GET /admin/users/{147,150,148,153,1}/profile` -> `data.role`:

```
role 1 name=admin            slug=admin            level=100
role 2 name=customer         slug=customer         level=1
role 4 name=employee         slug=employee         level=2
role 5 name=location_manager slug=location_manager level=3
role 6 name=location_chef    slug=location_chef    level=2
```

**RULING.**

- `roles.slug` **exists** and mirrors `name` with **underscores**. Report 07's and report
  06's shared open question is CLOSED.
- `getRoleUsers('location-chef', ...)` and `getRoleUsers('location-manager', ...)` match
  **nobody** - report 07's mechanism is confirmed for those two.
- `getRoleUsers('customer', ...)` **matches**, because slug `customer` is correct. So report
  07's blanket claim "every model-event notification resolves to an empty recipient list"
  is **PARTLY WRONG**. Customers holding a UCB row with `scope_mask > 0` on the record's
  customer-buildings still receive `extra_work_created` / `extra_work_updated` /
  `comment_created`.
- Report 07's *other* half - "admins are not in the audience" - is **fully correct**, and it
  is the half that explains report 07's own DATA: the notification history is user 1 (an
  admin), and it is admins who were dropped from the role list. Report 07 §1.1 point 5 and
  §2.6's "live proof" therefore stand exactly as written; only the "matches nobody"
  generalisation must be narrowed.
- Report 06 §3.2's two role-slug-dependent rows are **CONFIRMED**, not uncertain. CODE -
  `app/Services/ExtraWorkService.php:427`:
  ```php
        $isAdminOrManager = $user->role && in_array($user->role->slug, ['admin', 'location_manager']);
  ```
  and CODE - `app/Http/Controllers/Admin/ExtraWorksController.php:1675`:
  ```php
                $isAdmin = $user && $user->role && $user->role->slug === 'admin';
  ```
  Both compare against underscored values that exist. Both work.
- Same for `updateStatus`'s admin fan-out. CODE - `ExtraWorksController.php:3692-3694`:
  ```php
                $adminUserIds = \App\Models\User::whereHas('role', function($q) {
                    $q->where('slug', 'admin');
                })->pluck('id');
  ```
  This is a real SQL predicate on `roles.slug`; it works, and that is *independent* proof the
  column exists, because report 07's own DATA shows `status_changed` rows still being written
  as late as 2026-02-17.

### C-5. "Nobody except admin has an `invoices` row." Report 06's mechanism is wrong; its conclusion survives. And its COULD-NOT-DETERMINE #4 is now closed.

- **Report 06** §1.5 and §2.9: "Only the admin role can touch invoices at all. Nobody else
  has an `invoices` row, so every invoice route 403s for every other role." Its matrix marks
  several cells "(absent)" and states "An absent row means `roleHasPermission` returns false".
- **Report 06** COULD-NOT-DETERMINE #4: roles 3 (customer_employee), 7 (customer_manager) and
  8 (contact_person) have no live users, so their rows could not be read.

**DATA - `GET /admin/roles?per_page=100` returns the full permission set for all eight roles,
including the three with no users:**

| role | invoices | extra_works | reports | users | rows with mask 0 |
|---|---|---|---|---|---|
| 1 admin | **31** | 255 | **0** | 255 | 2 |
| 2 customer | **0** | 31 | 255 | 0 | 18 |
| 3 customer_employee | **0** | **19** | 0 | 0 | 24 |
| 4 employee | **0** | 255 | 0 | 0 | 23 |
| 5 location_manager | **0** | 127 | 0 | **23** | 20 |
| 6 location_chef | **0** | 63 | 0 | 0 | 22 |
| 7 customer_manager | **0** | **55** | 0 | **23** | 21 |
| 8 contact_person | **0** | **19** | 0 | 0 | 25 |

**RULING.**

- Report 06's **conclusion is right** (every non-admin invoice call 403s) but its **stated
  mechanism is wrong**: the rows are present with mask `0`, not absent. Same outcome via
  `hasPermission()`, different fact. Every "(absent)" cell in report 06's matrix in §1.5
  should read `0`. The same applies to its remark that "the admin role has **no** `reports`
  row" - admin has a `reports` row at mask 0.
- Report 06's COULD-NOT-DETERMINE #4 is **CLOSED** with the three missing rows above.
- **NEW and materially worse than report 06 reported.** Report 06 §1.7 says "a location
  manager can mint an admin", because `POST /admin/users` is gated on `users,create` and
  location_manager holds `users=23`. **`customer_manager` (role 7) also holds `users=23`** -
  and `customer_manager` is a **customer-type** role (report 06 §1.4: type "Customer",
  level 3). So the create-an-admin path is open to a customer-side role, not only to a
  provider-side one. It has no live users today, which is why report 06 could not see it.
- **NEW.** `customer_employee` (19) and `contact_person` (19) hold `view+list+delete` on
  extra_works and **no update bit**: they can delete an extra work they cannot edit.
  `customer_manager` (55 = view+list+create+delete+export) is the same shape plus export.
- Report 06's INFERRED claim that four populated roles hold `extra_works,update` with no
  invoices bit is **CONFIRMED and can now be stated for all eight roles**: the update bit (8)
  is held by admin, customer, employee, location_chef and location_manager; of those, only
  admin holds any invoices bit.

### C-6. Report 06 contradicts itself on the number of ungated `/admin/projects/*` routes.

- **Report 06** §1.8: "`/api/admin/projects/*` (17 routes)". §2.13 table: "`/admin/projects/*`
  (13 routes, `Projects_ProjectController`) | `:525-541`".

**What the source says.** CODE - `routes/api.php:526-543`, the whole group, counted:
`GET /`, `GET /summary`, `GET /building-summary`, `GET /service-types`, `GET /create`,
`POST /`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}`, `POST /{id}/refresh`,
`POST /{id}/service-lines`, `PUT /{id}/service-lines/{lineId}`,
`DELETE /{id}/service-lines/{lineId}` = **13**. None carries middleware.

**RULING: 13.** Report 06 §1.8's "17" is wrong; §2.13 is right. The ungated-ness is
confirmed either way.

### C-7. Report 06's list of ungated routes is incomplete - it omits the entire `/admin/worker-hours/*` group, which report 04 flagged.

- **Report 04** §2.6: "the entire `/admin/worker-hours/*` group carries **no `ucb.permission`**
  (`routes/api.php:2377-2417`)".
- **Report 06** §1.8 and §2.13 present themselves as the enumeration of routes with no
  permission middleware. `worker-hours` appears in neither.

**What the source says.** CODE - `routes/api.php:2376-2417`:

```php
        Route::controller(App\Http\Controllers\Admin\WorkerHoursController::class)
            ->prefix('worker-hours')
            ->group(function () {
```

I read all 21 routes in that group (`form-data`, `weekly`, `bulk-save`, `summary`,
`pending-approval`, `pending-summary`, `submit`, `submit-week`, `approve`, `approve-week`,
`approve-employee-week`, `reject`, `revert`, `revert-week`, `approved-report`,
`employee-overview`, `approve-employee-all-sources`, `revert-employee-all-sources`,
`update-source-hours`, `approve-source`, `revert-source`). **Not one carries a
`->middleware(...)` call, and the group carries none.**

**RULING: report 04 is correct and report 06's enumeration is incomplete.** These are not
read-only endpoints: `bulk-save`, `approve*`, `revert*` and `update-source-hours` all write
worker hours and, via `WorkerApprovedHour`, labour money. Add them to report 06 §2.13.

### C-8. Report 05's `BillingService.php:28` claim is wrong about what that line does.

- **Report 05** §2.9: "`BillingService.php:28`'s `'total_amount' => $work->fixed_price` is
  therefore writing a **non-existent attribute** on some other model or being silently
  dropped." It also attributes the `total_amount` naming to "A2's COULD NOT DETERMINE #4 and
  the schema-owner handoff".

**What the source says.** CODE - `app/Services/BillingService.php:25-30`:

```php
        $result = [
            'product_created' => false,
            'invoiceable_items_count' => 0,
            'total_amount' => $work->fixed_price,
            'items' => [],
        ];
```

That is a plain PHP **return array** the method hands back to its caller. It is not a model
write, not an `InvoiceableItem::create()`, and nothing is "dropped".

**RULING.**
- Report 05's *substantive* point is **CORRECT**: the `invoiceable_items` column is `total`,
  not `total_amount`. CODE - `app/Models/InvoiceableItem.php:31` (`'total',` in `$fillable`)
  and `:55` (`'total' => 'decimal:2',`). Report 05's live row dump of item 562 is right.
- Report 05's *mechanism* claim about line 28 is **WRONG** - re-read it above.
- Report 05's *attribution* is also **WRONG**: report 02's COULD-NOT-DETERMINE #4 is about
  the undocumented `project_id` / `task_id` columns, and report 02's own §2.3 table lists the
  column correctly as `total`. Report 02 never said `total_amount`.
- (The only other `total_amount` in that file is `BillingService.php:487`,
  `'total_amount' => round($items->sum('unit_price'), 2)` - also a return-array key.)

### C-9. Type (d) - claims labelled CODE whose cited line does not contain what was quoted.

I re-read each of these with `sed -n` and `grep -n`. The **substance** survives in every
case; the **citations** do not, and several agents cited different lines for the same fact.

| Fact | Cited by | TRUE line (verified this sweep) | Verdict on the citation |
|---|---|---|---|
| `'amount' => $work->total_products_cost ?? 0, // Only products, not labor` | 01 says `:143-152`; 03 says `:142`; 02 quotes range `:132-149` | **`InvoiceController.php:144`** (and `:609` in `addItem`) | 03 **wrong**; 01/02 ranges contain it |
| `'tax_rate' => 0.21, // Default 21% KDV` | 03 says `:143` (twice); 05 says `:145`; 01 says `:143-152` | **`InvoiceController.php:145`** (and `:610`) | **05 correct; 03 wrong** |
| `$work->update(['status_id' => 9]);` | 01, 02, 03 all say `:152` | **`InvoiceController.php:152`** | correct |
| `orWhere('extra_works.created_by', $user->id)` | 01 collected claim says `:344`; 06 says `:350` | **`ExtraWorksController.php:350`** (line 344 is `$q->orWhereHas('assignments', ...)`) | **06 correct; 01 wrong** |
| `applyUcbPermissions` method start | 01 says `:317-359`; 06 says `:327-365` | **`:327`**, admin bypass `:337`, `return $query;` `:338` | **06 correct** |
| `'user_id' => $createdBy` (undefined variable) | 01 says `:838` | **`ExtraWorksController.php:847`**; the only assignments in `store` are `$createdByName` at `:611, :616, :669` | line **wrong**, substance **confirmed** |
| `'requested_at' => $scheduleDateTime` in `batchStore` | 01 says `:6003` | **`ExtraWorksController.php:6011`** | line **wrong**, substance **confirmed** |
| PDF `Vervaldatum` = `invoice_date->addMonth()` | 02 says `blade:290`; 03 says `:293` | **`invoice-vertical.blade.php:293`** (`:291` is the label cell) | **03 correct; 02 wrong** |
| `$summaryTotal` / `$summaryLineTotal` | 02 says `:363-368` | **`:367` `$subtotalAfterDiscount`, `:368` `$summaryTax`, `:369` `$summaryTotal`, `:370` `$summaryLineTotal`** | off by ~6; substance **confirmed** |
| `$summaryPrice = ($invoice->summary_price !== null) ? ... : $itemSubtotal` | 05 says `:330` | **`:330`** | **correct** |
| `ExtraWorkProduct::getSubtotalAttribute` | 03 says `:80-83`; 04 says `:78-81`; 05 says `:78-92` | **`:80`** (tax `:85`, total_with_tax `:90`, unit_name `:95`) | **03 correct**; 04 and 05 wrong |
| `ExtraWorkV2InvoiceItem::calculateTotals` stores subtotal POST-discount | 02 says `:102-124` / `:118-124` | method body runs `:107-131`; the assignment `$this->subtotal = round($subtotalAfterDiscount, 2);` is at **`:125`** | off; substance **confirmed** |
| `ExtraWorkV2Invoice::calculateTotals` double-subtracts | 02 says `:152-165` | **`:157-169`**; `'total_amount' => $subtotal + $taxAmount - $discountAmount,` | off; substance **confirmed** |
| `updateStatus` validates only `status_id => exists:t_ticket_status,id` | 01 `:3624-3629`; 03 `:3625-3635`; 06 `:3625` | **validate opens `:3624`, `'status_id'` `:3625`, `findOrFail` `:3631`, assignment `:3635`** | all **correct** |
| `EntityController::getValidationRules` reads only `$fieldConfig['validation'][$action]` | 01 `:583-586` | method opens `:579`; `foreach` `:584`; `if (isset($fieldConfig['validation'][$action]))` **`:585`** | **correct** |
| Draft publication on status 4 | 01 and 07 both `:1285-1296` | **`:1285` the `if`, `:1288-1294` the raw update** | **correct** |
| `condition` mapped into the title | 07 `:5988-5998` | **`:5988-5996` the `match`, `:5997` the suffix** | **correct** |
| `ExtraWorkObserver` `$importantFields` | 01 `:34-47` | array literal spans **`:33-50`**; contents exactly as 01 lists, including misspelled `planned_at` and the seven non-columns | **correct in substance** |
| `UcbPermissionMiddleware` decision | 06 `:52-56` | `RolePermission::roleHasPermission($user->role_id, $moduleSlug, $permissionBit)` at **`:52-56`** | **correct** |
| `RolePermission` bits 32/64/128 = export/import/admin | 06 `:26-33` | **`:26-33`** verbatim | **correct** |
| `PermissionService::BITS` 32/64/128 = restore/export/manage | 06 `:11-22` | **`:11-22`** verbatim | **correct** |
| `InvoiceController::updateStatus` writes status + one timestamp and nothing else | 02 `:869-885` | **`:867-875`** contains exactly that; the rest of the method is the guard and the response | **correct in substance** |
| `ExtraWorkV2Invoice::markAsCancelled` releases items with no status filter | 02 `:212-234`, 03 `:232-235` | verified verbatim: `$this->items()->whereNotNull('invoiceable_item_id')->each(... update(['status' => 'ready']))` before the status write | **correct** |
| No migration creates `extra_work_employee_hours` / `employee_hourly_rates` / `employee_contracts` | 04 §5 | `grep -rln` over `database/` returns **nothing** | **correct** |
| `summary_subtitle` added twice unguarded | 02 §2.11 | `2026_02_18_085212:15` `->after('summary_description')` and `2026_02_18_100000:20` `->after('summary_description')`, neither with `hasColumn` | **correct** |
| `bootstrap/app.php` has no `->withSchedule()`; five middleware aliases | 01, 02, 03, 07 | read in full this sweep: `withRouting(web, api, commands, health)` then `withMiddleware` with exactly the five aliases and an api group of `HandleCors` + `wrap.api` | **correct** |

### C-10. Report 01's published record counts. Confirmed wrong, and report 01 contradicts itself.

Report 09 PART 1 already ruled that the true population is **76**, not 78. I add the
self-contradiction: **report 01 states both numbers**. Its §1.2 status table publishes
"live v1 rows" summing to 78 and its §5 says "0 of 78 live records"; but its own §2.4
already records that "`?statuses=n` returned 19, 6, 1, 6, 9, 37 (sum 78)" against
"`/statistics` returned ... (sum 76)" and explains the group-header inflation that causes
it. Report 01 diagnosed the leak and then published the leaky number as fact.

**RULING: 76.** Every denominator in report 01 ("0 of 78", "78 records in total") should
read 76.

### C-11. "No v1 code path ever writes status 5/6/7." Confirmed contradicted for 7 - and I can now name the actor.

Report 01 §1.2 asserts it; report 09 PART 1 verdict #4 contradicts it with activity logs.

**What the source says.** CODE - an exhaustive grep for writers of the literal 9 into
`extra_works.status_id` across the whole backend returns exactly **two**:
`InvoiceController.php:152` and `:618`. There is **no** hard-coded backend writer of 5, 6 or
7 to `extra_works.status_id`. Report 01's *mechanism* claim is therefore right.

**DATA - I pulled the activity rows myself.** `GET /admin/extra-works/{448,442,433}/activities`,
2026-06-04 rows only:

```
work 448  11:04:42  status_changed  9 -> 7  user_id=128
work 448  11:05:00  status_changed  7 -> 9  user_id=128
work 442  11:04:42  status_changed  9 -> 7  user_id=128
work 442  11:05:00  status_changed  7 -> 9  user_id=128
work 433  11:04:42  status_changed  9 -> 7  user_id=128
work 433  11:04:58  status_changed  7 -> 9  user_id=128
```

**RULING.** Report 01's claim as *worded* ("no v1 code path ever writes status 5/6/7") is
**contradicted for 7** - the generic status endpoints accept any id in `t_ticket_status`, and
one authenticated actor used status 7 on ~25 v1 rows. Report 01's claim as *intended*
(nothing in the code hard-codes 5/6/7 onto a v1 row) is **confirmed**. Report 09's open
question #2 ("what set roughly twenty-five v1 works to status 7") now has an actor:
**user_id 128**, the same user who reverted them.

### C-12. Report 09 PART 1's headline unknown - the sent_at coupling. The correlation is real; the "hidden mechanism" framing should be retired.

- **Report 03** §1.2: "Nothing about the works changes when an invoice is sent."
- **Report 09 PART 1** verdict #50 and COULD-NOT-DETERMINE #1: **CONTRADICTED** - works of
  invoice 88 flipped `7 -> 9` at `11:04:58` = its `sent_at`, works of 89 at `11:05:00-01` =
  its `sent_at`, and the draft invoice's works did not move. "The coupling is real in the
  data and absent from the code I read."

**What the source says - I extended the sweep beyond what report 09 did.**

- CODE - `app/Models/Invoice.php`: the class body contains **no `boot()`, no `booted()`, no
  `static::` hook of any kind**. `grep -n "booted\|boot()\|static::"` returns nothing.
- CODE - `grep -rln "Invoice" app/Observers app/Events app/Listeners app/Jobs` returns
  **nothing**. There is no invoice observer, event, listener or job anywhere.
- CODE - the exhaustive writer grep in C-11: only `InvoiceController.php:152` and `:618`
  write status 9 in the backend, both inside invoice *creation* paths.
- CODE - `grep -rn "status_id: 9" frontend/src` returns exactly **one** hit:
  `ExtraWorkBulkAllInvoiceModal.jsx:274` (the zero-amount branch report 09 found).
- CODE - `InvoiceController::sendInvoice` re-read in full (`:336-387`): it validates
  draft-ness and non-emptiness, calls `generateInvoicePDF`, then
  `$invoice->update(['status' => 'sent', 'pdf_path' => ..., 'pdf_generated_at' => now(),
  'sent_at' => now()]);` and commits. It touches no `ExtraWork`.
- **DATA** - the `7 -> 9` transitions **have activity rows**. `ExtraWorkObserver::updated`
  fires only on model events, so these were per-record model saves, **not** a
  query-builder mass update. And they carry `user_id = 128` - an authenticated actor, the
  same one who set them to 7 sixteen seconds earlier.
- **DATA** - `ip_address` is `127.0.0.1` on **every** row of work 448's 19-row log, across
  three different `user_id`s (1, 128, 161). The IP is a reverse-proxy artefact and
  discriminates nothing.

**RULING.** Report 09's **observation is CONFIRMED** and report 03's flat "nothing changes"
is **wrong as written**. But report 09's framing - an undiscovered coupling inside the
invoice code - is **not supported**, and the search space is now exhausted: no invoice
model hook, no observer, no event, no listener, no job, two backend status-9 writers both
inside creation, one frontend writer unrelated to sending. The transitions were per-record
model saves by an authenticated user through the ordinary API.

The most economical reading, and I label it **INFERRED**: user 128 was working
invoice-by-invoice - marking each invoice's works "Gefactureerd" (status **7**, the wrong
one, exactly the trap C-3 describes), sending the invoice, and putting them back to 9 -
and the timestamps coincide because the two actions were parts of one manual per-invoice
routine, not because one caused the other. What would close it definitively: the
`extra_work_activities` rows for **all** ~25 works at 11:04-11:05 (are the `7 -> 9`
timestamps clustered into exactly two groups matching invoice membership, or spread?), and
the web-server access log for user 128 in that minute. Neither is reachable through the
read-only wrapper.

**Correction to report 03 regardless of mechanism:** "Nothing about the works changes when
an invoice is sent" is true of `sendInvoice()`'s code and false of the observed system.
Re-word it as: *`sendInvoice()` writes only to the invoice row; any work movement around a
send is external to it.*

### C-13. `getRemainingHours()` - "harmless but misleading". Report 01 understated it; report 04 is right.

- **Report 01** §2.1: "`$this->hours` does not exist on this model - it resolves to `null`...
  Harmless but misleading."
- **Report 04** §1.4 and §4: not harmless - combined with `hours_worked` being null on 100%
  of live records it makes the function return 0 unconditionally.

**What the source says.** CODE - `app/Models/ExtraWork.php:523-536`:

```php
    public function getRemainingHours(): float
    {
        $totalHours = $this->hours ?? $this->hours_worked ?? $this->total_hours ?? 0;
        $distributedHours = $this->getTotalDistributedHours();
        return max(0, $totalHours - $distributedHours);
    }
    ...
    public function canDistributeHours(float $hours): bool
    {
        return $this->getRemainingHours() >= $hours;
    }
```

CODE - `:506-508`: `public function getTotalHoursAttribute(): float { ... return $this->getTotalDistributedHours(); }`

**RULING: report 04 is correct.** With `hours_worked` null the chain lands on
`total_hours`, which *is* `getTotalDistributedHours()`, so the expression is
`max(0, distributed - distributed) = 0`. Report 01's "harmless" is wrong. Report 04's
corollary - that reviving `canDistributeHours()` would refuse every distribution - follows
directly from the two quoted methods.

### C-14. `hours_planed` readers. Report 01's statement is wrong as written; report 04 is right.

Report 01 §2.5 says `hours_planed` is "READ BY: `updateHours` response only". Report 04 §2.2
lists twelve readers (one backend echo, eleven SPA render sites). Report 04 itself frames
this as an extension. **RULING: it is a correction, not an extension.** Report 01's sentence
is false; its *conclusion* (nothing decides anything on the value) is what survives, and
report 04 proves it more strongly.

### C-15. The one-work-one-invoice guarantee, and what report 03 missed about it.

- **Report 02** §2.2: `invoice_items.extra_work_id` originally carried `unique('extra_work_id')`,
  "the only structural guarantee that one extra work is billed once".
- **Report 03** §2.10 notes that `addItem` checks `status_id === 9` but "`store` has no such
  check".

**What the source says.** CODE - `database/migrations/2025_11_27_131838_create_invoice_items_table.php`:

```php
            $table->foreign('extra_work_id')->references('id')->on('extra_works')->onDelete('restrict');

            // Unique constraint - bir extra work sadece bir faturada olabilir
            $table->unique('extra_work_id');
```

**RULING: both are correct, and together they produce a consequence neither stated.**
Because `store()` has no status guard, the only thing stopping a second invoice line for an
already-invoiced work is the **database unique index** - which surfaces as a
`QueryException` rendered by `bootstrap/app.php` as a **500 `DB_ERROR`**, not as a clean
403 like `addItem`'s. Double-billing on the v1 path is prevented by MySQL, not by the
application.

### C-16. Report 06: "all UI rendering goes through PermissionService". Partly wrong - both vocabularies ship.

Report 06 §1.3 and §2.2 say the bit-label collision is invisible because every rendering
path uses `PermissionService`.

**DATA - two live endpoints, two different vocabularies for the same mask 255:**

- `GET /admin/users/1/profile` -> `role_permissions[0]` =
  `{"module_slug":"customers","permission_mask":255,"actions":["view","list","create","update","delete","restore","export","manage"]}`
  (PermissionService vocabulary - report 06's claim, **confirmed here**).
- `GET /admin/roles?per_page=100` -> `permissions[]` =
  `{"module_slug":"extra_works","permissions":255,"permission_names":["view","list","create","update","delete","export","import","admin"]}`
  (**RolePermission's own, correct vocabulary**).

**RULING.** The collision is **real and confirmed** (`RolePermission.php:26-33` vs
`PermissionService.php:11-22`, both re-read verbatim), but report 06's "all UI rendering
goes through PermissionService" is **wrong**: the roles screen renders the enforced names
and the user-profile screen renders the wrong ones. An operator comparing the two screens
sees the same mask described with two different action lists.

---

## 2. CONFIDENCE TABLE - THE LOAD-BEARING SPINE

The claims the whole corpus rests on. VERIFIED = I read the source myself in this sweep or
it rests on a live DATA reading I reproduced. DISPUTED = agents disagree and my ruling is in
§1. UNVERIFIABLE = cannot be settled read-only.

| # | Spine claim | Verdict | Single best evidence |
|---|---|---|---|
| 1 | There is no state machine on v1 Extra Work; `status_id` is validated only by `exists:t_ticket_status,id` | **VERIFIED** | `ExtraWorksController.php:3624-3635` re-read: validate, `findOrFail`, `$extraWork->status_id = $validated['status_id']` |
| 2 | Create/update run with an EMPTY validation rule array | **VERIFIED** | `EntityController.php:585` reads only `$fieldConfig['validation'][$action]`; report 09 PART 1 verdict #6 shows the live config has zero `validation` keys across 39 fields |
| 3 | The application declares no scheduler at all | **VERIFIED** | `bootstrap/app.php` read in full this sweep: `withRouting(web, api, commands, health)`, no `->withSchedule` |
| 4 | Nothing on an extra work is ever compared to the clock inside the extra-work area | **VERIFIED** (by report 01's grep, not re-run) | consistent with #3; no contradicting agent |
| 5 | `extra_works.status_id = 9` is the only real v1 billed flag; only two backend writers exist | **VERIFIED** | exhaustive grep this sweep: `InvoiceController.php:152` and `:618`; all ten `ReportsController` hits are reads |
| 6 | `extra_works.invoice_id` is dead; the working link is `invoice_items.extra_work_id` | **VERIFIED** | report 09 PART 1: NULL on 37/37, `laravel_through_key` proves the `hasOneThrough` |
| 7 | One work can be on only one invoice - enforced by the DB, not the app | **VERIFIED** | `2025_11_27_131838_create_invoice_items_table.php`: `$table->unique('extra_work_id');` |
| 8 | Labour never reaches a v1 invoice; the line amount is products only | **VERIFIED** | `InvoiceController.php:144` `'amount' => $work->total_products_cost ?? 0, // Only products, not labor`; report 09 PART 1 quantifies 848.25 EUR unbilled |
| 9 | Per-product VAT is destroyed at the invoice boundary, hard-coded 0.21 | **VERIFIED** | `InvoiceController.php:145` `'tax_rate' => 0.21, // Default 21% KDV`; report 09 PART 1 rendered the harm on a **sent** PDF |
| 10 | The PDF's `Vervaldatum` ignores `due_date` and prints `invoice_date + 1 month` | **VERIFIED** | `invoice-vertical.blade.php:293`, confirmed against a real render in report 09 PART 1 |
| 11 | v1 invoice numbers are generated by the browser | **VERIFIED** | `ExtraWorkBulkAllInvoiceModal.jsx:239` + `InvoiceController.php:88`'s `required\|unique`; live numbers match the client format |
| 12 | Cancelling a v1 invoice writes only status + `cancelled_at` | **VERIFIED** | `InvoiceController.php:867-875` re-read; no other statement in the branch |
| 13 | The v2 table is the only one with a real unwind on cancel | **VERIFIED** | `ExtraWorkV2Invoice::markAsCancelled()` re-read verbatim; releases items to `'ready'` with no status filter |
| 14 | The v2 header double-subtracts the discount | **VERIFIED** (code); **UNVERIFIABLE** (data) | item stores `$this->subtotal = round($subtotalAfterDiscount, 2)`; header computes `$subtotal + $taxAmount - $discountAmount`. Live discount is 0.00 |
| 15 | `ucb.permission` is role-only; it never narrows a query | **VERIFIED** | `UcbPermissionMiddleware.php:52-56` is the entire decision |
| 16 | `applyUcbPermissions` grants a full bypass on `role_id == 1` and ignores `scope_mask` | **VERIFIED** | `ExtraWorksController.php:337` bypass; the UCB subquery `:350-360` has no `scope_mask` predicate |
| 17 | The `created_by` access clause never matches, because the column is a display name | **VERIFIED** | `ExtraWorksController.php:350` compares `extra_works.created_by` to `$user->id`; migration `2025_10_18_072000:21` makes it `string(100)`; `:611-616` builds `"Name (Role)"` |
| 18 | `show()` and ~20 other extra-work endpoints bypass the row filter | **VERIFIED** (code) / **UNVERIFIABLE** (behaviour) | bare `ExtraWork::findOrFail` at `:1356, :3631, :2636, :2717, ...`; cannot be proven from the outside with one identity |
| 19 | Only the admin role can reach any invoice route | **VERIFIED**, mechanism corrected | `GET /admin/roles`: `invoices` mask 31 for role 1, **0** for all seven others (see C-5) |
| 20 | Four non-admin roles hold `extra_works,update` and no invoices bit | **VERIFIED** | the role matrix in C-5; `routes/api.php:761` vs `:1104-1134` |
| 21 | `roles.slug` exists and holds underscored values | **VERIFIED (NEW)** | `GET /admin/users/{147,150,148,153,1}/profile` -> `slug` = `location_chef`, `location_manager`, `customer`, `employee`, `admin` |
| 22 | `RecipientDeterminer` drops admins and misses both location roles, but **does** match customers | **VERIFIED, corrects report 07** | hyphenated constants `:25-26` vs the underscored live slugs in #21 |
| 23 | The group "Goedkeuren" button loops per-record archive/approve to status 8 | **VERIFIED, corrects report 01** | `WorkflowActionsBar.jsx:302/307-311/365` -> `detail.jsx:461-466` -> `ExtraWorkBulkArchiveApproveModal.jsx:77` |
| 24 | `is_draft` has exactly one publish path and no un-publish path | **VERIFIED** | `ExtraWorksController.php:1285-1294`, raw `DB::table(...)->update(['is_draft' => false])` gated on `status_id == 4` |
| 25 | `condition` is never persisted; it lives inside the title string | **VERIFIED** | `ExtraWorksController.php:5988-5997`: `match` -> `$conditionLabel` -> `$scheduleSuffix` -> out of scope |
| 26 | Labour money is `round(hours * hourly_rate * multiplier, 2)`, rate snapshotted at create | **VERIFIED** (by report 04's read + its own arithmetic check on live rows) | `ExtraWorkEmployeeHour.php:55-70`; report 04 reconciles 3x30x1.5 + 1x30x1.3 + 1x30x1.5 = 219 against the record's `total_labor_cost` |
| 27 | Four live tables have no create-migration (`extra_work_employee_hours`, `employee_hourly_rates`, `overtime_types`, `employee_contracts`) | **VERIFIED** | `grep -rln` over `database/` this sweep returns nothing for the first three names |
| 28 | Neither `extra_works` nor `products`/`customer_products`/`extra_work_products` can be reproduced from this repo | **VERIFIED** (by 01/05's greps, not re-run) | no contradicting agent; consistent with #27 |
| 29 | The true live v1 population is 76 records, not 78 | **VERIFIED** | report 09 PART 1 de-duplicated ids + `/statistics` = 76; the leak is `ExtraWorksController.php:101-136` |
| 30 | Nothing downstream reads invoice money; revenue is measured on `status_id = 9` | **VERIFIED** | the ten `ReportsController` `where('status_id', 9)` hits in this sweep's grep; no `Invoice` reference in `DashboardController` |
| 31 | The `7 -> 9` movement at each invoice's `sent_at` was driven by an authenticated user, not by a hidden code path | **VERIFIED as far as read-only allows** | activity rows carry `user_id = 128` and exist at all (so model events fired); no invoice observer/event/listener/job; two backend status-9 writers, both in creation |
| 32 | Every write-path claim in reports 01-08 is CODE-only | **VERIFIED** | no agent issued a non-GET; the ground rules forbid it |

---

## 3. CLAIMS NO AGENT VERIFIED THAT EVERY AGENT RELIED ON

These are the load-bearing assumptions underneath the whole corpus. None was tested by
anyone, including me.

1. **The true DDL of the core tables.** There is no `CREATE TABLE` migration for
   `extra_works`, `extra_works_attachments`, `extra_work_comments`, `extra_work_products`,
   `extra_work_employee_hours`, `employee_hourly_rates`, `overtime_types`,
   `employee_contracts`, `role_permissions`, `modules`, `user_module_overrides`,
   `user_customer_building_permissions`, and both `products` and `customer_products` have
   empty stub migrations. **Every "IF NULL/EMPTY" statement in all nine reports is inferred
   from model casts plus observed values, not from the schema.** So is every claim about a
   foreign key's `ON DELETE` behaviour on those tables. Closing it needs one
   `mysqldump --no-data` or a `SHOW CREATE TABLE` sweep.
2. **That the deployed code is the code in `/tmp/osius-ref`.** No agent checked that the
   clone matches the commit running on `dev-api.osius.nl`. Every "CODE says X, DATA shows Y"
   contradiction in the corpus - including C-12 above - has this as an unexamined
   alternative explanation. Closing it needs a deployed-version endpoint or a git ref.
3. **That there is one client.** Report 07 found a hard-coded `https://api.osius.nl` POST in
   `meldings/detail.jsx` and a live attachment row with `uploaded_from: "portal"` served
   from `portal.osius.nl`; report 07 also found `uploaded_from: "admin"` rows described as
   "Mobile upload". At least three clients write to this database and **only the admin SPA
   was read**. Any claim of the form "no code does X" is scoped to two repositories.
4. **That soft-deleted rows do not change the picture.** Every count in every report
   excludes them, because every list endpoint applies `deleted_at is null` and no reachable
   endpoint exposes trashed rows. This silently underpins: the 76-record population, "0 of
   76 records has the requirement flags", "statuses 5 and 6 have never held a v1 row", "13
   invoiceable items", "the v2 invoices 0001-0003 were soft-deleted", and the 15 empty
   groups.
5. **That the observed 500s are representative.** `bootstrap/app.php`'s `QueryException`
   handler returns `'details' => app()->isProduction() ? null : $e->getMessage()`. The SQL
   leak that report 09 PART 1 used to prove the `status_id != 9` clause only happens because
   this environment is not `production`. Behaviour on a production deploy differs.
6. **That no queue worker or host cron exists.** Reports 02, 03, 04 and 07 all name
   `deploy.sh`, `crm-laravel.service`, `crm-socket.service` and the host crontab as unread.
   The absence of an *application* scheduler is verified; the absence of *any* timer is not.

---

## 4. WHAT THIS SWEEP CLOSED

Open questions from earlier reports that are now answered:

- **Report 07 CND #1 / report 06 CND #5 - does `roles` have a `slug` column and what are its
  values?** CLOSED. It does; values are underscored (`admin`, `customer`, `employee`,
  `location_chef`, `location_manager`). See C-4.
- **Report 06 CND #4 - the permission rows of roles 3, 7 and 8.** CLOSED. See the matrix in
  C-5. New finding: `customer_manager` holds `users=23`.
- **Report 09 PART 1 CND #2 - what set ~25 v1 works to status 7 on 2026-06-04?** Actor
  identified: `user_id = 128`, same actor on both legs. See C-11.
- **Report 09 PART 1 CND #1 - the sent_at coupling.** Search space exhausted; re-framed. See
  C-12.
- **Report 05 §2.9's `total_amount` puzzle.** Resolved: `BillingService.php:28` is a return
  array, not a write; the column really is `total`. See C-8.

---

## 5. COULD NOT DETERMINE (V2)

Every gap this sweep leaves, and exactly what would close it.

1. **Which endpoint user 128 used for the `9 -> 7` and `7 -> 9` transitions.** I proved they
   fired model events (activity rows exist), were per-record, and belong to one user. I could
   not distinguish `PUT /admin/extra-works/{id}` from `PUT /admin/extra-works/{id}/status`
   from a kanban drag. **To close:** the `extra_work_activities` rows for all ~25 works
   between 11:04:40 and 11:05:05 on 2026-06-04 (are the return timestamps in exactly two
   clusters matching invoice membership?), plus the web-server access log for user 128 in
   that minute. The API exposes activities per work only, and I sampled three.
2. **Whether `RecipientDeterminer` actually delivers to customers today.** I proved the
   `customer` slug matches. I did not prove any customer user holds a UCB row with
   `scope_mask > 0` on a live record's customer-buildings, which the same query also
   requires. **To close:** `GET /admin/users/{a customer id}/profile` -> `ucb_permissions`,
   cross-referenced against a record's `customer_buildings`; or a notification-history read
   under a customer token, which I do not have.
3. **Whether the `role_permissions` rows I read are the ones the middleware reads.** The
   `/admin/roles` payload is rendered by a controller; `RolePermission::getPermission` may
   apply caching (`config/permissions.php` declares cache TTLs and report 06 proved that file
   is read by nothing, but the model itself was not re-read by me for a cache layer).
   **To close:** read `app/Models/RolePermission.php::getPermission` in full.
4. **Whether `customer_manager`'s `users=23` has ever been exercised.** The capability is now
   proven; role 7 has zero live users, so it has certainly not been used *by that role* here.
   **To close:** `SELECT id, role_id, created_at FROM users` against `user_activities`.
5. **Everything in §3 above.** Those six assumptions are unclosed and are the largest
   remaining risk in the corpus.
6. **Reports 04, 05, 07 and 08 were never live-verified end to end.** Report 09 PART 1
   covered reports 01-03 only, and this sweep tested reports 04-08 only where they
   contradicted another report or where a citation was disputed. Claims in those four
   reports that no other agent touched - most of the hours chain, most of the pricing chain,
   the whole notification-preference map, the whole context sweep - carry each author's own
   confidence and no independent check. **To close:** a PART 3 pass with the same method
   report 09 PART 1 used, aimed at 04-07.

### Where I stopped

I read all nine reports in full. I re-read, in the source, 34 disputed or load-bearing
file:line citations (listed in C-9 plus the quotes throughout §1), and made 9 live GET calls
(`/admin/roles`, five `/admin/users/{id}/profile`, three `/admin/extra-works/{id}/activities`).
I made no write of any kind and issued no non-GET request.

I did **not** re-verify: report 04's hours arithmetic against live rows, report 05's price
snapshot DATA, report 07's 475-row notification census, or report 08's per-model sweep -
none of those was contradicted by another agent, so none met the bar for this pass. They are
named in item 6 above.
