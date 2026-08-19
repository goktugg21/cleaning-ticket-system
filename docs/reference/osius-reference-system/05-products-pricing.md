# Osius reference system — Agent A5: Products, pricing, and money on a work

Scope: `products`, `product_categories`, `product_units`, `product_price_history`,
`customer_products`, `customer_product_prices`, `customer_product_versions`,
`extra_work_products`, plus every place a price or a total is written, read, rounded
or hand-edited.

Their **Product** is our **Service**. Their names are kept throughout. Every place
where their Product concept touches money is flagged `[PRODUCT=SERVICE]`.

Nothing in the reference system was modified. Every API call was a GET through the
read-only wrapper.

Evidence labels:

- **CODE** — a file and line I read, with the line quoted.
- **DATA** — an endpoint I called, and the values that came back.
- **INFERRED** — a conclusion I drew, stated as such, with what would confirm it.

---

# 1. PLAIN-ENGLISH LOGIC — how pricing actually works

## 1.1 There are four price layers, and only two of them are connected

The system contains four separate places a price can live:

| # | Layer | Table | What it is |
|---|---|---|---|
| 1 | Global catalogue | `products` | 6 rows. A house price list: name, price, tax_rate, unit, category, and a `type_id` where 1 = "Service" and 2 = "Product". |
| 2 | Customer price list | `customer_products` | 15 rows. The per-customer (and optionally per-building) price list. This is the one operators actually use. |
| 3 | Dated price versions | `customer_product_versions` + `customer_product_prices` | A proper versioned price book: named versions with start/end dates, per-product prices, bulk percentage/fixed adjustments. 3 versions exist, for exactly **one** customer. |
| 4 | The line on the work | `extra_work_products` | The frozen copy that actually becomes money. |

Layer 1 → Layer 2 is **broken by omission**: the only code that would push a
catalogue price down into a customer price list is `CustomerProduct::syncFromMainProduct()`,
and **nothing anywhere calls it**. 14 of the 15 live customer products are not even
linked to a catalogue product.

Layer 3 → Layer 4 **does not exist at all**. The dated price-version book is read by
exactly one subsystem — the building-machine year plan, where it produces a *budget*
number. It is never consulted when a product is put on an extra work, and it never
reaches an invoice. On the one customer that uses versions, the active version says
one price and the customer price list says another, and the extra-work path uses the
customer price list.

Layer 2 → Layer 4 is the only live path, and it is a **copy**, not a reference.

## 1.2 How a line gets its price — the resolution order

There is no resolver function. There are **four independent copy sites**, and they
disagree with each other:

| Path | Where price comes from | Default tax_rate if source is NULL | Writes unit_id / category_id? | `is_fixed_price` |
|---|---|---|---|---|
| `POST /admin/extra-works` (create with `assignment_products`) | `customer_products.price` | **0.00** | yes / yes | hard-coded `true` |
| `PUT /admin/extra-works/{id}` (append `assignment_products`) | `customer_products.price` | **0.00** | **no / no** | hard-coded `true` |
| `POST /admin/extra-works/batch` | `customer_products.price` | **21** | no (writes `unit` string instead) | not set |
| `POST /admin/extra-works/{id}/products` | **whatever the client sends in `price`** | **0.00** | yes / yes | client, default `true` |

So the answer to "is there a customer-specific price that overrides the catalogue
price" is: the customer price list *is* the price, and the catalogue is decoration.
And the answer to "is there a price history" is: there is a `product_price_history`
table with a model, a schema and two API routes pointed at it — and **not one line
of code ever writes a row to it, and neither route works.**

## 1.3 WHAT HAPPENS TO AN OLD WORK WHEN A PRICE CHANGES — the high-value answer

**The price is snapshotted onto the line at add-time. Old works never re-price.**
Nothing re-reads, nothing back-fills, nothing warns.

This is not a code reading — it is visible in the live data. Extra work 476 carries a
line created from customer product 105. The line says name `"Extraschoonmaak"`, price
`45.18`. Customer product 105 today says name `"Opleverschoonmaak"`, price `37.020`.
Both the name and the price of the catalogue entry were changed after the work was
priced, and the work kept the old ones. The work is at status 9 (invoiced).

The snapshot is total: `name`, `price`, `tax_rate`, `unit_id`, `category_id` and
`quantity` are all copied as values. `customer_product_id` is stored, but it is used
only to render a link and to skip duplicates on re-save — **no total, no report and
no invoice ever follows it back to the customer product.**

The flip side is equally load-bearing: because the copy is by value, **changing a
customer product's price does not correct a mistake on an existing work.** The only
way to re-price an existing work is to hand-edit the line (see §1.6).

## 1.4 Where VAT comes from

VAT is **per line**, copied from `customer_products.tax_rate`, which itself defaults
to 21.00 at the customer-product form level. There is no global VAT setting in use:
`config/products.php` declares `'defaults' => ['tax_rate' => 21.00]` and nothing reads
it. There is no per-customer VAT.

Live data shows real mixed rates: 14 of 15 customer products at 21.00%, one at 9.00%;
extra-work line 404 (on work 448) carries 9.00%.

And then the invoice throws it away. `InvoiceController::store` writes
`'tax_rate' => 0.21` as a hard-coded literal on every invoice line, regardless of what
the underlying products said. Agent A3 already proved the harm on a *sent* invoice;
this report confirms the source side: the 9% rate exists, is correct on the work, and
is discarded exactly once, at the invoice boundary.

There is also a **units mismatch across tables that nothing normalises**:

| Column | Convention | Example |
|---|---|---|
| `products.tax_rate` | percent | `21.00` |
| `customer_products.tax_rate` | percent | `9.00` |
| `extra_work_products.tax_rate` | percent | `9.00` |
| `extra_work_v2_products.tax_rate` | percent | `21` |
| `invoiceable_items.tax_rate` | percent | `21.00` |
| `invoice_items.tax_rate` | **fraction** | `0.2100` |
| `invoices.summary_tax_rate` | **fraction** (validated `max:1`) | — |

Exactly one line of code converts between them (`InvoiceController.php:1210`,
`($itemData['tax_rate'] ?? 21) / 100`), on the from-invoiceable-items path only.

## 1.5 The work total is never stored. It is computed on read — six different ways.

`extra_works` has **no** total column. Every number you see is derived. There are six
formulas over the same `extra_work_products` rows, and they round at different steps:

| # | Where | Formula | Rounding | Labour? | VAT? |
|---|---|---|---|---|---|
| 1 | `ExtraWork::total_products_cost` | `Σ round(price × qty, 2)` | per line | no | excluded |
| 2 | `ExtraWork::total_cost` | `#1 + Σ employee_hours.total_cost` | per line | yes | excluded |
| 3 | `transformModelData` → `total_price` / `total_tax` / `total_subtotal` (the LIST) | round each line, round each line's tax, sum, round | per line **and** per line-tax | no | included |
| 4 | `calculateFinancialSummary` → `financial_summary` (the DETAIL and the approval modal) | sum unrounded, round at the end | on the total only | no | included |
| 5 | `priceBreakdown` endpoint | products unrounded + labour, then **flat 21%** | on the total only | **yes** | flat 21% |
| 6 | `ReportsController` (10 methods) | `Σ price × qty`, no rounding at all | none | no | excluded |

Formulas 3 and 4 can differ by cents on the same record — #3 rounds each line's tax
to 2dp before summing, #4 sums exact line taxes and rounds once. Formula 5 is the
only one that includes labour, and it is the only one a customer-facing screen calls
"grand total". Formula 6 is what the revenue reports print.

**Rounding happens per line in formulas 1–3 and on the total in 4–6.** There is no
single rounding policy.

## 1.6 EVERY place a total can be edited by hand — and which one the invoice uses

The prompt's premise ("the approval modal and the archive modal both show editable
totals") is **wrong**, and the real hand-edit surfaces are elsewhere. I checked all
of them:

| Screen | Shows money | Editable? | Writes what |
|---|---|---|---|
| Approval modal (`ExtraWorkApprovalModal.jsx`) | subtotal / VAT / total from `financial_summary` | **read-only** — its own file header says "editable", the state comment says "Financials state (READ-ONLY)" | only `hours_planed`, `approved_at`, `status_id`, `approval_notes` |
| Bulk approve / bulk complete / **bulk archive approve** / bulk archive reject modals | subtotal / tax / total per work | **read-only display** | status + notes only |
| Bulk invoice / bulk-all invoice modals | subtotal / tax / total per work | **read-only display** | invoice creation, or a bare `status_id: 9` for zero-amount groups |
| **Financials tab, inline edit** (`ExtraWorkFinancialsTab.jsx`) | the line grid | **YES — free-text `price`** | `PUT /admin/extra-works/{id}/products/{productId}` → rewrites `extra_work_products.price`, `name`, `quantity`, `unit_id`, `description` |
| Add-product modal (`EditProductModal.jsx`) | cart with live totals | quantity only; price is taken from the chosen customer product | `POST .../products` |
| **Invoice line edit** (`EditItemModal.jsx`, draft invoices only) | one invoice line | **YES — `amount`, `tax_rate`, `quantity`, `unit_name`, `description`** | `PUT /admin/invoices/{id}/items/{itemId}` → rewrites `invoice_items`, then recalculates `invoices.subtotal/tax_amount/total_amount` |
| **Invoice "Overzicht" editor** (`InvoiceContainer.jsx`, draft invoices only) | the whole invoice | **YES — `summary_price`, `summary_quantity`, `summary_tax_rate`, `summary_description`, `summary_subtitle`, `discount_type`, `discount_value`** | `PUT /admin/invoices/{id}` → writes `invoices.summary_*` and `discount_*` |

So the answer to "does it override the lines or rewrite them" is **both, at two
different levels, with two different answers**:

- **On the work:** there is no total to override. The only hand-edit *rewrites a
  line*. Every total is then recomputed from the rewritten lines. A hand-edited work
  total and the sum of its lines can never disagree, because the work total does not
  exist as a stored thing.
- **On the invoice:** `invoices.summary_price` is a pure **override**. It rewrites
  nothing. It does not touch the lines, and — critically — the `update()` endpoint
  **does not recalculate `invoices.subtotal` / `tax_amount` / `total_amount` after
  writing it**.

**Which one does the customer actually see?** Three different numbers, and the answer
depends on where you look:

| Consumer | Number shown |
|---|---|
| `invoices.total_amount` (the DB) | `Σ(amount × quantity) + Σ(amount × quantity × tax_rate)` — **ignores `summary_price` entirely** |
| PDF **page 1** ("Overzicht", the summary line and the totals block the customer reads first) | `summary_price` if set, else `Σ(amount × quantity)`; then minus discount; then × a **weighted-average** tax rate |
| PDF **page 2** ("SPECIFICATIE") | `Σ(amount × quantity)` per line, **discount not applied, `summary_price` not applied** |

So a hand-edited invoice total wins on page 1 of the document the customer receives,
loses on page 2 of the same document, and never reaches the database columns at all.
This answers A2's open question about whether `summary_*` and `discount_*` are
reachable from the UI: **they are, from the invoice detail page, on draft invoices.**

## 1.7 The status gate on money — and the admin bypass

Adding, editing or deleting a product on a work is refused with HTTP 403
`status_restriction` unless the work is at `status_id = 1` (New) — **unless the caller
is `role_id == 1`, who may change the money at any status, including status 9
(invoiced).** The three product endpoints each carry their own copy of this check.

Combined with the fact that `extra_works.status_id 8 ↔ 9` is the only real billed flag
(A3), this means an admin can silently change the priced lines of an already-invoiced
work, and nothing on the invoice moves.

## 1.8 There is no customer quote and no price approval. At all.

- `config/products.php` declares `'quotations' => env('FEATURE_QUOTATIONS', false)`
  and `'approval_workflow' => env('FEATURE_APPROVAL_WORKFLOW', false)`, plus a whole
  `'quotations'` config block (prefix `QUO`, validity 30 days, starting number 1000).
  **Nothing in the application reads either flag or that block.** The only config key
  from that file that is read anywhere is `products.features.enabled`.
- The original schema file `database/sql/create_products_system.sql` designed an
  approval workflow into both `products` and `customer_products`
  (`approval_status ENUM('draft','pending','approved','rejected')`, `approved_by`,
  `approved_at`, `rejection_reason`). **None of those columns exist on the live
  tables** and no model or controller mentions them.
- The only "quote" in the codebase is `BuildingServiceBudget::BUDGET_TYPE_QUOTE`
  (`budget_type` in `contract|new_price|quote`) — an internal budget classification
  on a building service budget, not a customer-facing offer. The Dutch UI string
  `"quote": "Offerte"` exists in the locale bundle for that field only.

**There is no quote object, no quote number, no sent-to-customer state, no customer
acceptance, and no approval gate on a price change.** A price is whatever the last
person to type it said it was.

## 1.9 The shortest list of what is broken or dead in this area

1. `product_price_history` — **DEAD TABLE.** No writer anywhere.
2. `GET /admin/products/{id}/price-history` — routed to `ProductController::priceHistory`, **which does not exist**.
3. `GET /admin/customer-products/{id}/price-history` — calls `$customerProduct->priceHistory()`, **a relation that does not exist on the model**.
4. `POST /admin/customer-product-versions/{id}/activate` — routed to a method that does not exist.
5. `CustomerProduct::syncFromMainProduct()` — **never called**.
6. `CustomerProductController::bulkAssign` writes `discount_type`, `discount_value`, `created_by` — **none of them are in `$fillable`**, and it writes no `name`, no `price`, no `tax_rate`. Every product it creates is nameless and priceless.
7. `product_units` and `product_categories` can be deleted while in live use, because the delete guards count only the global `products` catalogue.
8. The dated price-version book is invisible to extra works and to invoicing.
9. `customer_products.start_date` / `end_date` / `is_active` gate nothing in practice — no live row sets them.
10. `extra_work_products.hours_worked` is summed into a `total_hours` that no money formula uses.

---

# 2. EVIDENCE — read/write maps

## 2.0 The tables and where their schema really comes from

**The migrations do not create these tables.** Both create-migrations are empty stubs:

*CODE — `database/migrations/2025_10_10_100521_create_products_table.php:14-17`:*
```php
Schema::create('products', function (Blueprint $table) {
    $table->id();
    $table->timestamps();
});
```
*CODE — `database/migrations/2025_10_10_100521_create_customer_products_table.php:14-17`* — byte-identical, for `customer_products`.

The real schema lives in `database/sql/create_products_system.sql` (a raw MySQL file,
not a migration) — **and the live schema does not match that file either.** The SQL
file defines `products.slug/sku/base_price/cost_price/sale_price/category_id` and
`customer_products.custom_price/discount_type/discount_value/final_price/valid_from/valid_until/approval_status`.

*DATA — `GET /admin/products?per_page=3`*: the live row is
`{"id":1,"name":"uurtarief","price":"32.50","tax_rate":"9.00","product_category_id":2,"type_id":1,"unit_id":2,"is_active":true,...}`
— `price` not `base_price`, `product_category_id` not `category_id`, and no `slug`,
`sku`, `cost_price` or `approval_status`.

*DATA — `GET /admin/customer-products/117`*:
`{"id":117,"name":"2 dagen per week","price":"32.500","quantity":"1.00","tax_rate":"9.00","start_date":null,"end_date":null,"is_active":true,"is_fixed_priced":false,"customer_id":2112,"building_id":null,"visible_building_ids":null,"product_id":1,"category_id":15,"type_id":1,"unit_id":2}`
— `price`/`start_date`/`end_date`, not `custom_price`/`valid_from`/`valid_until`; no
`discount_*`, no `final_price`, no `approval_status`.

**INFERRED:** `products` and `customer_products` were created and then substantially
re-shaped outside `database/migrations`, and `create_products_system.sql` is a stale
design document, not the live DDL. *To close:* `SHOW CREATE TABLE products` and
`SHOW CREATE TABLE customer_products`, plus `SELECT migration, batch FROM migrations
WHERE migration LIKE '2025_10_10%'`.

**`extra_work_products` has no create-migration and no SQL file at all.** The only
migrations that mention it are two ALTERs:
`2025_10_23_133108_add_unit_id_to_extra_work_products_table.php` and
`2025_10_23_141439_add_category_id_to_extra_work_products_table.php`. The table's true
column types are therefore not reproducible from this repo.

Tables that DO have a real create-migration in this area:
`product_units` (`2025_10_10_100512`), `product_categories` (`2025_10_10_100521`),
`customer_product_versions` (`2026_01_10_100001`), `customer_product_prices`
(`2026_01_10_100002`).

### Decimal precision — three different contracts on one conceptual price

- `customer_products.price` → `decimal(10,3)`
  *CODE — `2026_01_11_100001_update_decimal_precision_to_3.php:56`*
  `$table->decimal('price', 10, 3)->nullable()->change();`
  Model cast `decimal:3` (`CustomerProduct.php:38`).
  But the **write validation only allows 2 decimals**:
  *CODE — `config/base/customer_products.php:145-148*: `'store' => ['required', 'decimal:0,2', 'min:0']`.
  *DATA:* every live `customer_products.price` is 2 significant decimals rendered as 3
  (`"22.590"`, `"45.180"`, `"32.500"`).
- `customer_product_prices.price` → **`decimal(10,5)`**
  *CODE — `2026_01_12_145616_update_decimal_precision_for_hours_and_prices.php:20`*
  `$table->decimal('price', 10, 5)->nullable()->change();`
  Model cast is `decimal:3` (`CustomerProductPrice.php:24`) — **the model truncates two
  digits the column can hold**. Its own write endpoint validates only `numeric|min:0`,
  so 5 decimals can be stored and then read back rounded to 3.
  *DATA:* version price `37.499` exists live.
- `extra_work_products.price` → model cast `decimal:2` (`ExtraWorkProduct.php:29`).
  *DATA:* line 404 = `"30.12"`, line 432 = `"45.18"`.

**So a 3-decimal customer price becomes a 2-decimal work line, silently.** No live row
exercises it today because the customer-product form refuses 3 decimals; the version
book does not.

## 2.1 `products` (the global catalogue) — Model `Product`

*CODE — `app/Models/Product.php:16-24`* `$fillable = ['name','description','price','tax_rate','is_active','product_category_id','type_id','unit_id']`.

*CODE — `app/Models/Product.php:61`* `return $this->type_id === 2 ? 'Product' : 'Service';`
**[PRODUCT=SERVICE]** — their own model says the default `type_id` (1) means *Service*.
So "Product" in this system is the union of our Service and an actual consumable, and
the discriminator is a bare integer with no lookup table.

| Field | WRITTEN BY | READ BY | IF NULL | GATES | DEAD? |
|---|---|---|---|---|---|
| `price` | `EntityController::store/update` via `POST/PUT /admin/products` (config allow-list, `config/base/products.php`) | `CustomerProduct::syncFromMainProduct()` — **never called**; the products list grid | list shows blank | nothing | **effectively DEAD as money** — it never reaches a line, a total or an invoice |
| `tax_rate` | same | same | — | nothing | same |
| `type_id` | same | `type_label` / `type_info` accessors (icon + colour only), `CustomerProductController::statistics` `by_type` | treated as 1 = Service | nothing | display only |
| `product_category_id` / `unit_id` | same | list grid, `ProductCategory::products_count`, `ProductUnit::products_count` | blank label | **yes** — the delete guards on category and unit count only these | live, and load-bearing for the wrong reason (§2.6) |
| `is_active` | same | `scopeActive` (defined, but no caller in the products area) | — | nothing | near-dead |

*DATA — `GET /admin/products?per_page=3`*: `pagination.total = 6`. Six catalogue rows
in the entire system.

*DATA — `GET /admin/customer-products?per_page=200`*: 15 rows, of which **1** has a
non-null `product_id`. The catalogue is bypassed for 14 of 15 customer prices.

The one linked pair proves the layers have already drifted:
*DATA:* customer product 117 name `"2 dagen per week"`, price `32.500`, `product_id 1`;
catalogue product 1 name `"uurtarief"`, price `32.50`. Same price, different name — and
the active price version for that customer says **45.47** for the same row (§2.4).
Three names and two prices for one thing.

## 2.2 `customer_products` — Model `CustomerProduct`

*CODE — `app/Models/CustomerProduct.php:17-33`* `$fillable = ['name','description','price','quantity','tax_rate','start_date','end_date','is_active','is_fixed_priced','customer_id','building_id','visible_building_ids','product_id','category_id','type_id','unit_id']`.

| Field | WRITTEN BY | READ BY | IF NULL/EMPTY | GATES | DEAD? |
|---|---|---|---|---|---|
| `price` | `CustomerProductController::store/update` (EntityController, `config/base/customer_products.php:138-149`, `required` on store); `CustomerProductVersion::copyPricesFrom()` reads it to seed a version | **the four extra-work copy sites** (§2.3); `transformModelData` `total`; `price_with_tax` accessor; `ExtraWorkV2Product::boot` creating hook; `CustomerProductVersion::copyPricesFrom` / `syncMissingProducts` | copy sites write `0.00`; `price_with_tax` computes on 0 | **yes — it is the price of every extra-work line** | live, load-bearing |
| `tax_rate` | same, default 21.00 (`config/base/customer_products.php:150-165`) | store/update copy sites (default 0.00 on NULL); batchStore (default 21); `price_with_tax` (default 21.00) | **three different NULL defaults** | **yes — sets the line's VAT, which the invoice then discards** | live |
| `quantity` | same, default 1.00 | `transformModelData` `total` only; `EditProductModal` edit-mode fallback | 1 | nothing — the extra-work copy sites use the **request's** quantity, not this one | near-dead |
| `is_fixed_priced` | same, default false | a list filter (`CustomerProductController.php:194`); `EditProductModal` sends it on as the line's `is_fixed_price` | false | nothing computes differently | **display/filter only.** *DATA:* false on all 15 live rows, while `store`/`update` hard-code `is_fixed_price = true` on the line they create — the flag on the work contradicts the flag on the source |
| `start_date` / `end_date` | same | `scopeValidNow()` (used by `forCustomer`/`forBuilding` only, `valid_only` defaulting to true); `isValidForDate()` (no caller) | no filtering | would gate visibility | **DATA: null on all 15 rows** — never exercised |
| `is_active` | same | `scopeActive` (no caller in this area), list filter | — | nothing | **DATA: true on all 15 rows** |
| `building_id` / `visible_building_ids` | same | `scopeVisibleInBuilding`, `visibility_type`, `isVisibleInBuilding`, `getVisibleBuildingIds`, and the `building_ids` list filter | product falls into the "restricted" bucket and shows in no building picker | **yes — decides which products the operator can even pick for a work** | live |
| `product_id` | same | `is_linked`/`is_custom` accessors, `scopeLinked/scopeCustom`, `syncFromMainProduct` (dead) | product is "custom" | nothing | live but almost always NULL |
| `type_id`, `category_id`, `unit_id` | same | copied to the line; `category`/`unit` labels; picker grouping | line gets NULL unit → blank unit everywhere downstream | category drives the picker's category filter | live |

**`syncFromMainProduct()` is dead.**
*CODE — `app/Models/CustomerProduct.php:282-295`* — it would overwrite name,
description, price, tax_rate, category, type and unit from the linked catalogue
product. `grep -rn "syncFromMainProduct" app/ resources/` returns **only that
definition**. No controller, no observer, no job, no command.

**`bulkAssign` is broken.**
*CODE — `app/Http/Controllers/Admin/CustomerProductController.php:478-486`:*
```php
$customerProduct = CustomerProduct::create([
    'product_id' => $productId,
    'customer_id' => $data['customer_id'],
    'building_id' => $data['building_id'] ?? null,
    'discount_type' => $data['discount_type'] ?? null,
    'discount_value' => $data['discount_value'] ?? null,
    'is_active' => true,
    'created_by' => auth()->id(),
]);
```
`discount_type`, `discount_value` and `created_by` are **not in `$fillable`** and are
silently dropped by Laravel's mass-assignment filter; the SQL design file's
`discount_type`/`discount_value` columns do not exist on the live table either. And the
call sets **no `name`, no `price`, no `tax_rate`, no `unit_id`, no `category_id`**, and
never calls `syncFromMainProduct()`. Every product created by this endpoint is a
nameless row with a NULL price that, if it ever reached a work, would produce a
`0.00` line.
*INFERRED:* the frontend `CustomerProductBulkAssignModal.jsx` posts to
`/admin/customer-products` per row (`:334-335`) rather than to `/bulk-assign`, which is
why this has not surfaced. *To close:* a request log showing whether `/bulk-assign` is
ever called.

**Auto-seeding of version prices on create.**
*CODE — `CustomerProductController.php:331-362`* — after `parent::store()`, it creates a
`CustomerProductPrice` row for every active and future version of that customer, seeded
with `$product->price ?? 0`. This is the only automatic link from layer 2 to layer 3.

## 2.3 `extra_work_products` — Model `ExtraWorkProduct` — THE LINE THAT BECOMES MONEY

*CODE — `app/Models/ExtraWorkProduct.php:13-27`* `$fillable = ['extra_work_id','customer_building_id','name','customer_product_id','price','tax_rate','quantity','hours_worked','is_fixed_price','unit','unit_id','category_id','description']`.

*CODE — `app/Models/ExtraWorkProduct.php:78-92`* — the line arithmetic, the only place
it is defined:
```php
public function getSubtotalAttribute(): float   { return round($this->price * $this->quantity, 2); }
public function getTaxAmountAttribute(): float  { return round($this->subtotal * ($this->tax_rate / 100), 2); }
public function getTotalWithTaxAttribute(): float{ return round($this->subtotal + $this->tax_amount, 2); }
public function getUnitNameAttribute(): ?string { return $this->productUnit?->label ?? null; }
```

### `extra_work_products.price`

- **NAME** `extra_work_products.price` (model cast `decimal:2`)
- **WRITTEN BY — four snapshot sites and one hand-edit:**
  1. *CODE — `ExtraWorksController.php:697-716`* (`store`, from `assignment_products`):
     ```php
     $customerProduct = \DB::table('customer_products')->where('id', $customerProductId)->first();
     ...
     'price' => $customerProduct->price ?? 0.00,
     'tax_rate' => $customerProduct->tax_rate ?? 0.00,
     'quantity' => $requestedQuantity,
     'is_fixed_price' => true,
     'unit_id' => $customerProduct->unit_id ?? null,
     'category_id' => $customerProduct->category_id ?? null,
     ```
  2. *CODE — `ExtraWorksController.php:1089-1105`* (`update`, append-only — existing
     `customer_product_id`s are skipped at `:1081`). Identical price/tax copy, but
     **omits `unit_id` and `category_id`**, so a line added by editing a work has no
     unit and no category while a line added at creation does.
  3. *CODE — `ExtraWorksController.php:6039-6060`* (`batchStore`):
     ```php
     $customerProduct = \App\Models\CustomerProduct::find($productId);
     ...
     'price' => $customerProduct->price,
     'tax_rate' => $customerProduct->tax_rate ?? 21,
     'quantity' => $product['quantity'] ?? 1,
     'unit' => $unitValue,
     ```
     — **`?? 21`, not `?? 0.00`**, and it writes the legacy `unit` *string* column
     instead of `unit_id`. A batch-created line therefore has `unit_id = NULL` and
     `unit_name = null`.
  4. *CODE — `app/Services/ExtraWorkService.php:64-81`* (`addProduct`):
     ```php
     'price' => $data['price'],
     'tax_rate' => $data['tax_rate'] ?? 0.00,
     'quantity' => $data['quantity'] ?? 1.00,
     'is_fixed_price' => $data['is_fixed_price'] ?? true,
     ```
     **The price is whatever the client sends.** The controller validates only
     `'price' => 'required|numeric|min:0|max:9999999.99'`
     (*CODE — `ExtraWorksController.php:1775`*). Nothing checks it against the customer
     product it claims to come from.
  5. *CODE — `app/Services/ExtraWorkService.php:98-104`* (`updateProduct`):
     `$product->update($data);` — a blind mass-update of the validated payload, no
     recompute, no audit, no history row.
- **READ BY** `subtotal` accessor → `ExtraWork::total_products_cost` → `ExtraWork::total_cost`;
  `transformModelData` (`ExtraWorksController.php:517-533`); `calculateFinancialSummary`
  (`:5726-5789`); `priceBreakdown` (`:4263-4276`); `ExtraWorkService::getProducts` summary;
  10 `ReportsController` revenue methods; and — one step removed — `invoice_items.amount`
  via `total_products_cost`.
- **IF NULL** treated as 0 by every consumer (`(float) null == 0`); the line renders as
  € 0,00 and, if the whole work sums to 0, the bulk-all invoice modal routes it to the
  "zero-amount group" branch that sets `status_id = 9` with **no invoice at all**
  (`ExtraWorkBulkAllInvoiceModal.jsx:267-273`).
- **GATES** it is the price. It also gates the zero-amount branch above, and the
  `exclude_zero_amount` filter in the revenue reports (`ReportsController.php:175`,
  `:618`, `:817`).
- **DEAD?** No. This is the only live money column in the area.

### `extra_work_products.tax_rate`

- **WRITTEN BY** the same five sites, with **three different NULL defaults** (0.00 in
  `store`/`update`/`addProduct`, 21 in `batchStore`, `|| 21` client-side in
  `EditProductModal.jsx:262`). Note `saveInlineEdit` does **not** send `tax_rate`, so a
  hand price-edit leaves the old rate in place.
- **READ BY** `tax_amount` accessor; `transformModelData` `total_tax`;
  `calculateFinancialSummary`; the browser's own summary in
  `ExtraWorkFinancialsTab.jsx:341-343` and `EditProductModal.jsx:222`.
- **NOT READ BY** the invoice. *CODE — `InvoiceController.php:145`*
  `'tax_rate' => 0.21, // Default 21% KDV`. **[PRODUCT=SERVICE]** the per-product rate
  is discarded at exactly this line.
- *DATA — `GET /admin/extra-works/448/products`*: `"tax_rate":"9.00"`, `subtotal 30.12`,
  `tax_amount 2.71`, `total_with_tax 32.83`. Agent A3 showed the matching invoice line
  413 carries `0.2100`. **Confirmed from the source side.**

### `extra_work_products.customer_product_id`

- **WRITTEN BY** all four snapshot sites; nullable in `addProduct`.
- **READ BY** the `customerProduct()` relation (rendered as a name in
  `ExtraWorkService::getProducts`), and the duplicate-skip check at
  `ExtraWorksController.php:1064-1080`.
- **NOT READ BY** any total, any report, any invoice. **The link exists but carries no
  money.**
- *DATA:* work 476 line 432 → `customer_product_id 105`, line price `45.18`;
  `GET /admin/customer-products/105` → name `"Opleverschoonmaak"`, price `37.020`.
  **The proof that the copy is by value and is never refreshed.**
- *DATA:* work 448 line 404 → `customer_product_id: null` with a real price of 30.12 —
  a line typed straight in through `addProduct`, with no catalogue provenance at all.

### `extra_work_products.hours_worked`

- **WRITTEN BY** `addProduct` / `updateProduct` only.
- **READ BY** `ExtraWorkService::getProducts` → `summary.total_hours` (*CODE — `:51`*
  `'total_hours' => $products->sum('hours_worked')`).
- **NOT READ BY** any money calculation. Labour money comes from
  `extra_work_employee_hours.total_cost` (A1 §2.1). This column is a second, unrelated
  hours number sitting on the money line.
- *DATA:* `null` on every line I sampled (404, 432, 393–400).
- **NEAR-DEAD** — it feeds one display field and nothing else.

### `extra_work_products.is_fixed_price`

- **WRITTEN BY** hard-coded `true` by `store` (`:710`) and `update` (`:1102`); client
  value (default `true`) by `addProduct`; **not set at all** by `batchStore`.
- **READ BY** `scopeFixedPrice`/`scopeHourlyRate` (**no caller anywhere in `app/`**);
  `calculateFinancialSummary` emits it as a display flag (`:5780`); the UI renders a
  "Fixed" chip and disables the quantity field (`EditProductModal.jsx:603,617`).
- **IF NULL** UI treats it as false.
- **GATES** one disabled input in one modal. **No calculation branches on it.**
- **NEAR-DEAD as logic.** And it contradicts its own source: *DATA* shows
  `is_fixed_priced = false` on **all 15** customer products, while the two main copy
  sites write `true` on the line unconditionally.

### `extra_work_products.unit` (string) vs `unit_id` (FK)

- Two conventions on one table. `store`/`addProduct` write `unit_id`; `batchStore`
  writes the `unit` string; `update` writes neither.
- *CODE — `ExtraWorkProduct.php:44-47`* `$hidden = ['unit', // Use unit_name instead (derived from productUnit->label)]`
  — the string column is hidden from every API response, so a batch-created line's unit
  is invisible even though it was stored.
- `unit_name` reads `productUnit?->label` — the **untranslated** `label` column, while
  `InvoiceController` reads `label_nl` and `calculateFinancialSummary` reads
  `product_units.abbreviation`. Three different columns of the same lookup row are used
  as "the unit" in three places.

## 2.4 `customer_product_versions` + `customer_product_prices` — the price book nobody bills from

*CODE — `app/Models/CustomerProductVersion.php:105-119`* `getActiveForCustomer()` —
"active" is purely date-driven: `start_date <= today AND (end_date IS NULL OR end_date >= today)`,
`orderByDesc('start_date')->first()`.

*CODE — `:123-150`* `createWithDateAdjustment()` — creating a version closes any
overlapping earlier version at `new start_date - 1 day`, inside a transaction.

*CODE — `:196-206`* the bulk adjusters, the only "price increase" tool in the system:
```php
public function applyPercentageAdjustment(float $percentage): int {
    $multiplier = 1 + ($percentage / 100);
    return $this->prices()->update(['price' => DB::raw("ROUND(price * {$multiplier}, 3)")]);
}
public function applyFixedAdjustment(float $amount): int {
    return $this->prices()->update(['price' => DB::raw("GREATEST(0, ROUND(price + {$amount}, 3))")]);
}
```
Note it rounds to **3** decimals into a **5**-decimal column, writes raw SQL, and
**records nothing** — no `product_price_history` row, no audit, no before/after.

**WRITTEN BY:** `CustomerProductVersionController::store` (seeds from a source version
or from `customer_products.price`), `updatePrice`, `bulkUpdatePrices`, `saveAllPrices`,
`syncMissingProducts`, and `CustomerProductController::store` (auto-seed).

**READ BY — exactly two consumers:**
1. `CustomerProductController::transformModelData` (*CODE — `:576-588`*) — **only when
   the caller passes `?price_version_id=`**, in which case it swaps `price` in the
   response and adds `customer_product_price_id`. This is used by the machine-planning
   screens.
2. The building-machine year plan. *CODE — `BuildingMachinesController.php:1408,1416`:*
   ```php
   ->leftJoin('customer_product_prices', 'machine_task_version_status.customer_product_price_id', '=', 'customer_product_prices.id')
   DB::raw('SUM(machine_tasks.times_per_year * machine_tasks.estimated_hours * COALESCE(customer_product_prices.price, 0)) as total_price'),
   ```
   A yearly **budget** number, VAT-free, that never becomes an invoice line.
   The link is `machine_plan_versions.customer_product_version_id`
   (*CODE — `2026_01_20_000001_add_customer_product_version_to_machine_plan_versions.php:19-23`*).

**NOT READ BY:** any extra-work path, `BillingService`, `InvoiceController`,
`ReportsController`, or any PDF. `grep -rn "CustomerProductPrice\|customer_product_prices" app/`
returns only the version controller and the machine controllers.

**DATA — the live divergence.** 25 of 26 customers have zero versions
(`GET /admin/customer-product-versions?customer_id=<each>` → `data: []`). Customer 2112
has three:

| Version | Range | is_active | prices_count | total_value |
|---|---|---|---|---|
| 1 `v1-01.01.2026-31.01.2026` | 2026-01-01 → 2026-01-31 | false | 4 | 178.495 |
| 5 `v2-01.02.2026-30.06.2026` | 2026-02-01 → 2026-06-30 | false | 4 | 180.599 |
| 6 `v3-01.07.2026-31.12.2026` | 2026-07-01 → null | **true** | 4 | 180.599 |

*DATA — `GET /admin/customer-product-versions/6/prices` vs `GET /admin/customer-products?customers=2112`:*

| customer_product | active version price | `customer_products.price` | what an extra work would use |
|---|---|---|---|
| 111 Uurtarief 150 | **55.42** | 49.000 | **49.00** |
| 113 Uurtarief 100 | **37.499** | 33.000 | **33.00** |
| 114 5 dagen voorman | **42.21** | 66.000 | **66.00** |
| 117 2 dagen per week | **45.47** | 32.500 | **32.50** |

Every single row disagrees, and in both directions. **The customer's own active price
version is ignored by the billing path.**

**Dead route:** `POST /admin/customer-product-versions/{id}/activate`
(*CODE — `routes/api.php:2102`*) points at `CustomerProductVersionController::activate`.
`grep -n "public function" ` on that controller lists `index, store, show, update,
destroy, active, getPrices, updatePrice, bulkUpdatePrices, saveAllPrices,
syncMissingProducts` — **no `activate`.** Activation is date-driven; the button behind
this route cannot work.

## 2.5 `product_price_history` — a DEAD table with two broken doors

- **NAME** `product_price_history`, Model `ProductPriceHistory` (`$timestamps = false`,
  boot hook auto-stamping `changed_at`).
- **WRITTEN BY** *nothing*. `grep -rn "ProductPriceHistory" app/ config/ database/`
  returns exactly one hit: `app/Models/ProductPriceHistory.php:9`, the class
  declaration itself. No controller, no observer (there is no Product or
  CustomerProduct observer registered — *CODE — `app/Providers/AppServiceProvider.php:23-29`*
  registers observers for Building, Customer, Contact, Employee, User, ExtraWork and
  ExtraWorkComment only), no job, no command, no migration seed.
- **READ BY** two routes, **both of which fail**:
  - *CODE — `routes/api.php:1809`* `Route::get('/{id}/price-history', 'priceHistory')`
    on `ProductController` — and `ProductController` (122 lines) defines only `index`,
    `getCustomerProductsWithNullBuilding` and `statistics`. **No `priceHistory` method.**
  - *CODE — `app/Http/Controllers/Admin/CustomerProductController.php:430`*
    `$history = $customerProduct->priceHistory()` — **`CustomerProduct` has no
    `priceHistory()` relation** (its relations are `customer, building, product,
    category, unit, versionPrices, machineTasks`). The inverse relation exists on the
    *history* model (`ProductPriceHistory::customerProduct()`), but not the forward one.
- **IF NULL/EMPTY** always empty.
- **GATES** nothing.
- **DEAD** — declared, schema'd in `database/sql/create_products_system.sql:255-283`,
  routed twice, and never written or successfully read.

**Consequence for the business question:** there is **no record anywhere of who changed
a price, when, from what, or why.** `applyPercentageAdjustment` can move an entire
customer's price book with one call and leaves no trace beyond
`customer_product_prices.updated_at`.

## 2.6 `product_units` and `product_categories` — delete guards that count the wrong table

*CODE — `app/Models/ProductCategory.php:66-69`* `public function products(): HasMany { return $this->hasMany(Product::class, 'product_category_id'); }`
*CODE — `app/Models/ProductUnit.php:66-69`* `public function products(): HasMany { return $this->hasMany(Product::class, 'unit_id'); }`

*CODE — `ProductUnitController::destroy`:*
```php
$unit = ProductUnit::withCount(['products', 'derivedUnits'])->find($id);
if ($unit->products_count > 0) {
    return $this->error('Cannot delete unit with products. Please reassign products first.', 422);
}
```
`ProductCategoryController::destroy` is the same shape (`products_count` + `children_count`).

**Neither guard counts `customer_products` or `extra_work_products`.** And `ProductUnit`
has **no `SoftDeletes`** (*CODE — `ProductUnit.php:10-12`*, `use HasFactory;` only), so
its delete is permanent. `ProductCategory` does soft-delete, which is almost as bad:
the `belongsTo` on the line will resolve to `null` and the category name disappears.

**DATA — this is not hypothetical.**
`GET /admin/product-units?per_page=50`:

| id | slug | label | products_count | in live use on money lines? |
|---|---|---|---|---|
| 1 | uur | Uur | **0** | yes — `extra_work_products` line 404 (`unit_id 1`), customer products 105/111/113/114 |
| 5 | per-beurt | Per beurt | **0** | yes — lines 393–400 (`unit_id 5`), 8 customer products |
| 2 | day | Dag | 4 | yes |
| 3 | m2 | m2 | 1 | yes |

Units 1 and 5 carry the unit of nearly every billed line in the system and are both
**deletable** by the guard. `GET /admin/product-categories?per_page=50` shows the same
for category 17 `event-schoonmaak` (`products_count 0`, used by customer products
94/95/96) and category 21 `opleverschoonmaak`.

**IF DELETED:** `ExtraWorkProduct::unit_name` returns `null`; the financials tab and
`calculateFinancialSummary` render an empty unit; `InvoiceController`'s
`$firstProduct->unit->label_nl` (already broken for other reasons — A3 §2.5) stays at
its `'stuks'` default. Money is unaffected; the description of what was sold is lost,
including on already-sent invoices, because the PDF re-renders from live relations.

## 2.7 The six total formulas, quoted

**#1 — `ExtraWork::total_products_cost`** *(CODE — `app/Models/ExtraWork.php:427-435`)*
```php
$products = $this->products; $total = 0;
foreach ($products as $product) { $total += $product->subtotal ?? 0; }
return (float) $total;
```
`subtotal` is already `round(price * quantity, 2)`. **Per-line rounding, VAT excluded,
labour excluded.** This is the number that becomes `invoice_items.amount`.

**#2 — `ExtraWork::total_cost`** *(CODE — `:440-445`)* `getTotalLaborCost() + total_products_cost`.
Labour included, VAT excluded. **Never invoiced** — A1 and A3 both established this;
I confirm it from the product side: no invoice writer reads `total_cost`.

**#3 — the LIST total** *(CODE — `ExtraWorksController.php:517-533`)*
```php
foreach ($model->products as $product) {
    $productSubtotal = round($product->price * $product->quantity, 2);
    $productTax      = round($productSubtotal * ($product->tax_rate / 100), 2);
    $subtotal  += $productSubtotal;
    $taxAmount += $productTax;
}
$total = round($subtotal + $taxAmount, 2);
$data['total_price']    = number_format($total, 2, '.', '');
$data['total_tax']      = number_format($taxAmount, 2, '.', '');
$data['total_subtotal'] = number_format($subtotal, 2, '.', '');
```
Rounds **each line's tax** before summing. Emitted as **strings**. These three fields
are what every bulk modal (approve / complete / archive-approve / archive-reject /
invoice / invoice-all) displays and what the bulk-invoice modal sums to show the
operator the invoice total.

**#4 — the DETAIL total** *(CODE — `ExtraWorksController.php:5751-5789`)*
```php
$lineTotal = $price * $quantity;
$lineTax   = $lineTotal * ($taxRate / 100);
$subtotal += $lineTotal;
$totalTax += $lineTax;
...
'subtotal'  => round($subtotal, 2),
'total_tax' => round($totalTax, 2),
'total'     => round($subtotal + $totalTax, 2),
```
Sums **unrounded**, rounds once at the end. This is `financial_summary`, which is what
`show()` returns and what the **approval modal** displays. On a many-line work it can
differ from #3 by cents.

**#5 — `priceBreakdown`** *(CODE — `ExtraWorksController.php:4312-4315`)*
```php
$taxRate = 0.21; // 21% VAT (can be made configurable)
$taxAmount = $subtotal * $taxRate;
$grandTotal = $subtotal + $taxAmount;
```
`$subtotal = productsTotal + laborTotal`. **The only formula that bills labour, and the
only one with a hard-coded rate.** `'currency' => 'EUR'` is hard-coded too. It ignores
every per-line `tax_rate` on the work.

**#6 — the revenue reports** *(CODE — `ReportsController.php:170-172`, and the same
lambda at `:613`, `:806`, `:1025`, `:1331`, `:1534`)*
```php
$totalPrice = $work->products->sum(function ($product) {
    return ($product->price ?? 0) * ($product->quantity ?? 1);
});
```
**No rounding at any step.** VAT and labour both excluded. The `_excl_vat` variants at
`:806` and `:1025` prefer `$product->subtotal` when it is `> 0` and fall back to
`price * quantity` — i.e. the same number, sometimes rounded and sometimes not,
depending on whether the accessor was materialised.

**Client-side #7** *(CODE — `ExtraWorkFinancialsTab.jsx:333-354`)* — the browser sums
unrounded and rounds once, matching #4; *(CODE — `EditProductModal.jsx:215-236`)* — the
add-cart does the same but defaults a missing rate to **21** rather than 0.

## 2.8 The hand-edit surfaces, quoted

### (a) The line price on a work — free text

*CODE — `frontend/src/pages/finalosius/extra-works/modules/ExtraWorkFinancialsTab.jsx:168-201`:*
```js
const startInlineEdit = (product) => {
  if (isCustomer) return;
  setEditingProduct({ id: product.id, name: String(product.name), price: String(product.price),
                      quantity: String(product.quantity), unit_id: product.unit_id || null,
                      description: String(product.description || '') });
};
...
const response = await apiClient.put(
  `/admin/extra-works/${extraWorkId}/products/${editingProduct.id}`,
  { name: ..., price: parseFloat(editingProduct.price) || 0,
    quantity: parseFloat(editingProduct.quantity) || 1, unit_id: ..., description: ... });
```
Double-click a row, type a number, save. It writes `extra_work_products.price` directly
via `ExtraWorkService::updateProduct`'s blind `$product->update($data)`. It does **not**
send `tax_rate` (so the old rate survives a price change) and does **not** send
`customer_product_id` (so the line keeps claiming a provenance it no longer has).

**It overrides nothing and rewrites the line.** Every total then follows, because no
total is stored.

**Gate:** `POST/PUT/DELETE /admin/extra-works/{id}/products*` all carry
`ucb.permission:extra_works,update` (delete on v1 also uses `update`, not `delete` —
*CODE — `routes/api.php:734-737`*), plus this in-method check, repeated three times:
*CODE — `ExtraWorksController.php:1754-1769`:*
```php
if ($user->role_id !== 1) { // Not admin
    $extraWork = ExtraWork::findOrFail($id);
    if ($extraWork->status_id !== 1) { // Status is not "new"
        return response()->json([... 'reason' => 'status_restriction',
            'current_status' => $extraWork->status_id, 'required_status' => 1], 403);
    }
}
```
So: a non-admin may only touch money while the work is New; **`role_id == 1` may
re-price a work at any status, including 9 (invoiced).** Note this check calls
`ExtraWork::findOrFail` directly and so, like the other endpoints A1 listed, bypasses
`applyUcbPermissions` entirely.

Meldings (`type = 2`) have **no product routes at all** — the `prefix('meldings')` block
(`routes/api.php:677…`) contains none. A melding can still acquire priced lines through
the shared `store`/`update` `assignment_products` path.

### (b) The invoice line — amount, rate and quantity

*CODE — `InvoiceController.php:647-684`:*
```php
if (!$invoice->isDraft()) { return ... 'Can only edit items in draft invoices', 403; }
$validator = Validator::make($request->all(), [
    'amount' => 'sometimes|numeric|min:0',
    'tax_rate' => 'sometimes|numeric|min:0|max:1',
    'quantity' => 'sometimes|numeric|min:0', ...]);
$item->update($request->only(['amount','tax_rate','description','unit_name','quantity']));
$this->recalculateInvoiceTotals($invoice);
```
Reachable: *CODE — `frontend/.../invoices/components/InvoiceItemsTable.jsx:96-102`* +
`EditItemModal.jsx:35,93` (`* 100` on load, `/ 100` on save — the operator types 21 and
0.21 is stored). This is the **only** way to correct the discarded 9% VAT, and it must
be done manually on every affected line, on a draft invoice, before sending.

It rewrites the invoice line and recalculates the invoice header. It does **not** write
back to `extra_work_products`, so from that moment the invoice and the work disagree
permanently, and nothing flags it.

### (c) The invoice total — a true override

*CODE — `InvoiceController.php:196-238`* — draft-only, then
`$invoice->update($request->only([... 'summary_price', 'summary_tax_rate', 'summary_quantity',
'summary_unit', 'summary_description', 'summary_subtitle', 'discount_type', 'discount_value', ...]))`
with **no call to `recalculateInvoiceTotals`**.

Reachable: *CODE — `frontend/.../invoices/components/InvoiceContainer.jsx:29,62,145-146,197-198`*
— an "Overzicht" form with a `summary_price` field and a discount pair, posted to
`PUT /admin/invoices/{id}`.

*CODE — `resources/views/pdf/invoice-vertical.blade.php:313-369`:*
```php
foreach($invoice->items as $item) {
    $lineTotal = floatval($item->amount ?? 0) * floatval($item->quantity ?? 1);
    $itemSubtotal += $lineTotal;
    $itemTaxTotal += $lineTotal * floatval($item->tax_rate ?? 0.21);
}
if ($itemSubtotal > 0) { $avgTaxRate = $itemTaxTotal / $itemSubtotal; }
$summaryPrice   = ($invoice->summary_price !== null) ? floatval($invoice->summary_price) : $itemSubtotal;
$summaryTaxRate = $invoice->summary_tax_rate ? floatval($invoice->summary_tax_rate) : $avgTaxRate;
...
$subtotalAfterDiscount = $summaryPrice - $discountAmount;
$summaryTax   = $subtotalAfterDiscount * $summaryTaxRate;
$summaryTotal = $subtotalAfterDiscount + $summaryTax;
$summaryLineTotal = $summaryPrice + ($summaryPrice * $summaryTaxRate);
```

**So, for the prompt's question — if a hand-edited total and the sum of lines disagree,
which one does the invoice use? All three answers ship on the same invoice:**

| Consumer | Uses |
|---|---|
| `invoices.subtotal` / `tax_amount` / `total_amount` (DB, and anything reading the API) | **the lines** — `summary_price` is never folded in |
| PDF page 1, the summary line **and** the totals block the customer reads | **`summary_price`**, minus discount, times a blended average rate |
| PDF page 2 (SPECIFICATIE) | **the lines**, discount not applied |

Note also `$summaryLineTotal` (the "Totaal" cell on the summary line itself) is computed
**without** the discount while the totals block three rows below it is computed **with**
it — the same page contradicts itself whenever a discount is set. A2 flagged this; I
confirm it and add that `summary_price` compounds it, because the page-1 discount is
taken off the *override*, not off the lines.

*DATA:* no live invoice has a non-null `summary_price` or a discount (A2: 3 invoices,
2 sent 1 draft, no `summary_*` override). So all of §2.8(c) is **CODE-level**, on a
path that is fully wired and reachable from the UI.

## 2.9 Where the other Product families meet money

**`extra_work_v2_products` (Model `ExtraWorkV2Product`).** Same line arithmetic
(`round(price*qty,2)`, `round(subtotal*rate/100,2)`). It has a **model-event snapshot**
rather than a controller one:
*CODE — `app/Models/ExtraWorkV2Product.php:176-189`:*
```php
static::creating(function ($model) {
    if ($model->customer_product_id && !$model->product_name) {
        $customerProduct = CustomerProduct::find($model->customer_product_id);
        if ($customerProduct) {
            $model->product_name = $model->product_name ?? $customerProduct->product?->name;
            $model->price        = $model->price ?? $customerProduct->price;
            $model->tax_rate     = $model->tax_rate ?? $customerProduct->tax_rate ?? 21;
        }
    }
});
```
Note `$customerProduct->product?->name` — it reaches through to the **catalogue**
product for the name. *DATA:* 14 of 15 live customer products have `product_id = NULL`,
so `->product` is null and `product_name` stays NULL, after which
`getDisplayNameAttribute()` falls back to `'Unknown Product'`.

`ExtraWorkV2Product` adds a `frequency` dimension (`once|weekly|monthly|per_schedule`)
with `applicable_periods`, and `appliesToWeek/appliesToMonth`. `BillingService` sums
these products as "income":
*CODE — `app/Services/BillingService.php:142-144`:*
```php
$totalIncome = $products->sum(function ($product) {
    return floatval($product->quantity) * floatval($product->price);
});
```
— unrounded, VAT-free — and then splits it into `invoiceable_items` with
`'tax_rate' => 21` hard-coded at **eight** creation sites (`:276, :321, :384, :433,
:531, :565, :636, :693, :780`). The split uses floor-and-remainder:
*CODE — `:610-612`:*
```php
$baseAmount   = floor($work->fixed_price / $monthCount * 100) / 100; // Floor to 2 decimals
$totalFromBase = $baseAmount * $monthCount;
$remainder     = round($work->fixed_price - $totalFromBase, 2);
```
with the remainder added to the **last** instalment. That is the only correct rounding
policy in the entire pricing area, and it lives on the path with zero live rows.

**`prj_project_products` (Model `PrjProjectProduct`).** *CODE — the create migration
`2026_02_04_120000:11-22`* — `product_name` (a plain string), `unit_type` (a plain
string), `quantity`, `price`, `tax_rate` default **21.00**. **There is no
`customer_product_id`, no `product_id`, no `unit_id` and no `category_id`.** The project
money path is completely disconnected from the product catalogue and the customer price
list; an operator types a name and a price. Same line arithmetic as the other two.
*DATA — `GET /admin/invoiceable-items?per_page=15`*: all 13 live rows are
`type: "project"`, `unit_id: null`, `tax_rate: "21.00"`, `notes: "auto_generated_from_task"`.

**A correction to a tier-1 note:** A2's "COULD NOT DETERMINE #4" and the schema-owner
handoff both describe `invoiceable_items.total_amount`. The column is called **`total`**
— *DATA*, a full row dump of item 562 shows `"subtotal":"400.00","tax_rate":"21.00","tax_amount":"84.00","total":"484.00"`
and no `total_amount` key at all. `BillingService.php:28`'s `'total_amount' => $work->fixed_price`
is therefore writing a **non-existent attribute** on some other model or being silently
dropped. `project_id` and `task_id` are confirmed present and NULL, as A2 reported.

---

# 3. THIS AREA'S CONNECTION MAP

## 3.1 The price pipeline, end to end

```
products (6 rows, catalogue)
   │  price, tax_rate, unit_id, category_id, type_id(1=Service,2=Product)
   │
   │  syncFromMainProduct()  ...................... NEVER CALLED  ✗
   │  CustomerProduct.product_id ................... set on 1 of 15 rows
   ▼
customer_products (15 rows) ── THE customer price list
   │  price(10,3) · tax_rate · quantity · unit_id · category_id
   │  building_id / visible_building_ids  →  which products the picker offers
   │
   ├──► customer_product_prices (version book, 3 versions, 1 customer)
   │       ▲ seeded by CustomerProductController::store + copyPricesFrom
   │       │ edited by updatePrice / bulkUpdatePrices / saveAllPrices
   │       │           / applyPercentageAdjustment / applyFixedAdjustment
   │       └──► machine_task_version_status.customer_product_price_id
   │               └──► SUM(times_per_year × estimated_hours × price)
   │                       = building-machine YEAR BUDGET.  Never an invoice.  ✗
   │
   │  ══ SNAPSHOT (copy by value, 4 sites) ══════════════════════════
   ▼
extra_work_products  ── name, price, tax_rate, quantity, unit_id, category_id
   │                    customer_product_id kept but never followed for money
   │  ▲ hand-editable: PUT /admin/extra-works/{id}/products/{pid}  (price, qty, name)
   │
   ├──► ExtraWork::total_products_cost  = Σ round(price×qty,2)
   │       └──► invoice_items.amount        ← tax_rate REPLACED by 0.21  ✗
   │       └──► invoice_items.quantity=1, unit_name='stuks'  (A3: broken pivot) ✗
   ├──► transformModelData total_price/total_tax/total_subtotal → every bulk modal
   ├──► financial_summary → detail page + APPROVAL MODAL (read-only)
   ├──► priceBreakdown → products + LABOUR at flat 21%
   └──► ReportsController × 10 → revenue, unrounded, VAT-free, labour-free

invoice_items ── amount, tax_rate(fraction), quantity
   │  ▲ hand-editable on DRAFT: PUT /admin/invoices/{id}/items/{itemId}
   ├──► recalculateInvoiceTotals → invoices.subtotal/tax_amount/total_amount
   └──► PDF page 2 (SPECIFICATIE)

invoices.summary_price / summary_tax_rate / discount_*
   │  ▲ hand-editable on DRAFT: PUT /admin/invoices/{id}  (Overzicht tab)
   └──► PDF page 1 ONLY.  Overrides the lines.  Never touches the stored totals.  ✗

product_price_history ── written by nothing, read by two broken routes.  DEAD.  ✗
```

## 3.2 What action changes what

| Action | Endpoint | Writes | Does NOT touch |
|---|---|---|---|
| Edit a catalogue product's price | `PUT /admin/products/{id}` | `products.price` | every customer price list, every existing line, every invoice. **Zero downstream effect.** |
| Edit a customer product's price | `PUT /admin/customer-products/{id}` | `customer_products.price` | existing `extra_work_products` lines; existing `customer_product_prices` version rows; anything already invoiced. Affects only lines created **after** the change. |
| Create a customer product | `POST /admin/customer-products` | `customer_products` row **+ one `customer_product_prices` row per active/future version** | — |
| Bulk-adjust a version ±% | `POST /admin/customer-product-versions/{id}/prices/bulk` | every `customer_product_prices.price` in that version, `ROUND(...,3)` | `customer_products.price`; every extra work; every invoice; any history. **Silent.** |
| Add a product to a work | `POST /admin/extra-works/{id}/products` | a new `extra_work_products` row at the price **the client sent** | nothing upstream |
| Add products at create/edit | `POST` / `PUT /admin/extra-works[/{id}]` with `assignment_products` | new rows at `customer_products.price`, append-only (no removal path in `update`) | nothing upstream |
| Inline-edit a line price | `PUT /admin/extra-works/{id}/products/{pid}` | `extra_work_products.price/name/quantity/unit_id/description` | `tax_rate` (left stale), `customer_product_id` (left claiming false provenance), any invoice already created |
| Approve a work | `PUT /admin/extra-works/{id}` from the approval modal | `approved_at`, `status_id=4`, `approval_notes`, optionally `hours_planed` | **no money at all** |
| Approve/reject an archive | `POST /admin/extra-works/{id}/archive/(approve\|reject)` | archive stamps + notes | **no money at all** |
| Bulk-invoice | `POST /admin/invoices` | `invoice_items.amount = total_products_cost`, `tax_rate = 0.21`, work → `status_id 9` | per-product VAT, labour, unit, quantity |
| Bulk-invoice a **zero-amount** group | `PATCH /admin/extra-works/{id}` `{status_id: 9}` | only the status | no invoice exists at all |
| Edit an invoice line | `PUT /admin/invoices/{id}/items/{itemId}` (draft) | `invoice_items.*` **+ recalculated invoice totals** | `extra_work_products` — the work and the invoice diverge silently |
| Edit the invoice "Overzicht" | `PUT /admin/invoices/{id}` (draft) | `invoices.summary_*`, `discount_*` | `invoices.subtotal/tax_amount/total_amount`, the lines, PDF page 2 |
| Delete a product unit | `DELETE /admin/product-units/{id}` | **hard-deletes the row** if no *catalogue* product uses it | guard ignores `customer_products` and `extra_work_products` → live and already-invoiced lines lose their unit |
| Delete a product category | `DELETE /admin/product-categories/{id}` | soft-deletes if no *catalogue* product uses it | same blind spot |

## 3.3 Gates — what a price actually blocks

| Gate | Where | Effect |
|---|---|---|
| `status_id != 1` and `role_id != 1` | the three product endpoints, in-method | **403 `status_restriction`** — non-admins cannot change money after the work leaves New. Admins can, at any status. |
| `ucb.permission:extra_works,update` | `routes/api.php:735-737` | who may add/edit/**delete** a priced line (delete uses `update` on v1, `delete` on v2 — an inconsistency) |
| `ucb.permission:products,*` | `routes/api.php:1524-1530, 1788-1796, 1803-1811, 1818-1827` | the whole catalogue + customer price list |
| `ucb.permission:customers,*` | `routes/api.php:2097-2107` | **the version price book is gated on `customers`, not `products`** — a user with full product rights and no customer rights cannot touch versions, and vice versa |
| `config('products.features.enabled')` | every method of `ProductController`(no), `CustomerProductController`, `ProductCategoryController`, `ProductUnitController` | a kill switch for the whole area, default `true`. `ProductController::index` does **not** check it. |
| `!$invoice->isDraft()` | `InvoiceController::update`, `updateItem` | money edits on an invoice stop at `sent` |
| total == 0 | `ExtraWorkBulkAllInvoiceModal.jsx:128,267-273` | a zero-total group is marked invoiced **with no invoice** |
| `exclude_zero_amount` | `ReportsController:175,618,817` | a zero-priced work vanishes from revenue reports |
| `products_count > 0` | unit/category destroy | blocks deletion — but counts the wrong table |

## 3.4 Dead / near-dead, collected

| Thing | Verdict | One-line reason |
|---|---|---|
| `product_price_history` (table + model) | **DEAD** | no writer in the entire codebase; both read routes are broken |
| `ProductController::priceHistory` route | **DEAD/500** | the method does not exist |
| `CustomerProductController::priceHistory` | **DEAD/500** | `$customerProduct->priceHistory()` is not a relation |
| `POST /customer-product-versions/{id}/activate` | **DEAD/500** | no `activate` method |
| `CustomerProduct::syncFromMainProduct()` | **DEAD** | never called |
| `CustomerProduct::isValidForDate()` | **DEAD** | never called |
| `ExtraWorkProduct::scopeFixedPrice/scopeHourlyRate` | **DEAD** | no caller in `app/` |
| `CustomerProductController::bulkAssign` | **BROKEN** | writes 3 non-fillable fields, no price, no name |
| `extra_work_products.hours_worked` | **NEAR-DEAD** | one display sum; no money uses it |
| `extra_work_products.is_fixed_price` | **NEAR-DEAD** | disables one input; no calculation branches on it; contradicts its source |
| `extra_work_products.unit` (string) | **NEAR-DEAD** | written only by `batchStore`, and `$hidden` from every response |
| `customer_products.quantity` | **NEAR-DEAD** | one display `total`; the copy sites use the request's quantity |
| `customer_products.start_date/end_date/is_active` | **UNEXERCISED** | null/true on all 15 live rows |
| `products.price` / `products.tax_rate` | **DEAD AS MONEY** | 14 of 15 customer products are unlinked, and the one sync path is dead |
| `config/products.php` `features.*` (except `enabled`), `defaults.*`, `pricing.*`, `bundles.*`, `quotations.*`, `recurring.*`, `search.*`, `cache.*` | **DEAD** | only `products.features.enabled` and `products.defaults.currency` (in a dead accessor) are read anywhere |
| `customer_product_versions` / `customer_product_prices` | **LIVE, BUT NOT FOR BILLING** | read only by the machine year-plan budget |

## 3.5 Where their "Product" meets our "Service", with money attached

**[PRODUCT=SERVICE]** flags, in the order the money moves:

1. `products.type_id` 1 = **Service**, 2 = Product. The default is 1. One flat catalogue
   holds both, and only an icon and a colour distinguish them
   (`Product.php:61-70`). Nothing prices, taxes or reports on the distinction.
2. `customer_products` is the real service price list: 15 rows, per customer, per
   building, with per-row VAT. Our Service-with-a-price is their CustomerProduct.
3. `extra_work_products` is the priced service line on a job. Its unit is genuinely a
   service unit (`Uur`, `Per beurt`, `Per maand`, `Per keer`, `Vaste prijs`) — 5 of the
   10 units are service units and only `Stuk`/`m2`/`Aantal` are goods-like.
4. **The line's unit and per-line VAT are both destroyed at the invoice boundary**
   (`InvoiceController.php:132-152`): every invoice line becomes `1.00 stuks @ 21%`,
   whatever service was actually sold. A3 proved the harm; §2.3 proves the source was
   correct.
5. **Labour is a separate species of money that never becomes a line.**
   `extra_work_employee_hours.total_cost` is shown on the work, is included in
   `total_cost` and in `priceBreakdown`'s "grand total", and is invoiced by nothing.
   A service business whose labour never reaches an invoice bills only its materials
   and its fixed-price service rows.
6. `prj_project_products` re-invents the service line as free text with no link to the
   catalogue or the customer price list at all.

---

# 4. COULD NOT DETERMINE

1. **The true column definitions of `extra_work_products`.** The table has no
   create-migration and no SQL file. Everything I state about its types comes from
   model casts and observed values. In particular I cannot confirm whether
   `price` is `decimal(10,2)` or something wider, whether `customer_product_id` has a
   foreign key (and with what ON DELETE), or whether `unit_id` / `category_id` are
   constrained. **To close:** `SHOW CREATE TABLE extra_work_products` and
   `SELECT * FROM information_schema.referential_constraints WHERE table_name='extra_work_products'`.

2. **Whether the live `products` / `customer_products` schema can be reproduced at all.**
   Both create-migrations are empty stubs and `database/sql/create_products_system.sql`
   describes a different design (`base_price`, `custom_price`, `discount_type`,
   `final_price`, `valid_from`, `approval_status`) than the live API returns. **To
   close:** `SHOW CREATE TABLE products; SHOW CREATE TABLE customer_products;` plus
   `SELECT migration, batch FROM migrations WHERE migration LIKE '2025_10_10%'`.
   This belongs with the schema-owner's existing anomaly list.

3. **Whether a 3-decimal customer price has ever reached a 2-decimal line.** The
   customer-product form validates `decimal:0,2` so the UI cannot create one, but
   `customer_product_prices` accepts 5 decimals and the version→line path does not
   exist, so today the answer is "no". **To close:**
   `SELECT id, price FROM customer_products WHERE price <> ROUND(price,2)`.

4. **Whether `POST /admin/customer-products/bulk-assign` is ever called.** The frontend
   bulk-assign modal posts row-by-row to the normal store endpoint instead. If anything
   does call `/bulk-assign` it is creating nameless, priceless customer products.
   **To close:** `SELECT COUNT(*) FROM customer_products WHERE name IS NULL OR price IS NULL`,
   or an access log.

5. **Whether `summary_price` or a discount has ever been used on a real invoice.** No
   live invoice sets either (A2 confirmed; I confirmed the UI path exists). Every claim
   in §2.8(c) about what the PDF prints is therefore CODE-only. **To close:** set
   `summary_price` on a scratch draft invoice and render its PDF — or
   `SELECT id, summary_price, discount_type, discount_value FROM invoices WHERE summary_price IS NOT NULL OR discount_type IS NOT NULL`.

6. **Whether deleting a product unit actually succeeds against the live DB.** The
   application guard permits it, but a foreign key on `extra_work_products.unit_id`
   (which I could not read — see #1) would reject it at the database. **To close:** the
   FK list for `extra_work_products` and `customer_products`.

7. **What the `type_id` values mean beyond 1/2, and whether a lookup table exists.**
   The values are hard-coded in four places (`Product.php:61`, `CustomerProduct.php:186`,
   `CustomerProductController.php:531`, `config/base/customer_products.php:120-125`) with
   no `product_types` table. If a third value were ever written, `type_label` would say
   "Service". **To close:** `SELECT DISTINCT type_id FROM products, customer_products`.

8. **Whether `ExtraWorkV2Product`'s `frequency` / `applicable_periods` ever change a
   price.** I read the model and `BillingService`'s income sum, which multiplies
   `quantity × price` with no frequency factor at all — so `appliesToWeek`/
   `appliesToMonth` appear to be scheduling filters used elsewhere. I did not read
   `ExtraWorksV2Controller`'s period-product endpoints (`routes/api.php:918-921`). That
   belongs to the V2 / billing agent. **To close:** read
   `ExtraWorksV2Controller::getPeriodProducts/addPeriodProduct` and every caller of
   `appliesToWeek`.

9. **The full `EntityController` write path for `products` / `customer_products`.**
   There is no `config/admin/products.php`; only `config/base/products.php` and
   `config/base/customer_products.php` exist, so the `?context=` parameter that the
   architecture agent flagged would resolve to a missing file for these entities. I read
   the field/validation blocks but not `EntityController`'s config-resolution and
   fallback logic. **To close:** the architecture agent's pass over
   `app/Http/Controllers/Base/EntityController.php:800-950`.

10. **Whether any real role holds `products,update` without `customers,update`.** The
    version price book is gated on `customers`, the price list on `products`. If those
    two rights are ever split, one operator can change the billing price and another can
    change the budget price, with no overlap and no history. **To close:** the RBAC
    agent's read of `PermissionService` and the live role/permission rows.

## Where I stopped

I read, in full: `Product`, `ProductCategory`, `ProductUnit`, `ProductPriceHistory`,
`CustomerProduct`, `CustomerProductPrice`, `CustomerProductVersion`, `ExtraWorkProduct`,
`ExtraWorkV2Product`, `PrjProjectProduct`; `ProductController`,
`CustomerProductController`, `CustomerProductVersionController`, and the `destroy`
methods of `ProductUnitController` / `ProductCategoryController`; the product-related
ranges of `ExtraWorksController` (`store` 685-760, `update` 1050-1140, `getProducts`/
`addProduct`/`updateProduct`/`deleteProduct` 1720-1940, `priceBreakdown` 4253-4374,
`calculateFinancialSummary` 5726-5789, `batchStore` 6025-6075, `transformModelData`
505-540); `ExtraWorkService` 1-130; `BillingService`'s pricing arithmetic;
`InvoiceController` 185-265 and 640-700; the summary block of
`resources/views/pdf/invoice-vertical.blade.php` (305-375); `config/products.php` and the
pricing parts of `config/base/customer_products.php`; `database/sql/create_products_system.sql`;
and the eight relevant migrations. On the frontend: `ExtraWorkFinancialsTab.jsx`,
`EditProductModal.jsx`, `ExtraWorkApprovalModal.jsx`, the six bulk modals,
`InvoiceItemsTable.jsx`, `EditItemModal.jsx`, `InvoiceContainer.jsx`.

I did **not** read: `ProductCategoryController` / `ProductUnitController` beyond their
delete guards, `MachineTasksController` and `BuildingMachinesController` beyond the two
version-price queries quoted, `ExtraWorksV2Controller`'s product and period-product
endpoints, the `ContinuousWork*` family, or `EntityController` itself. Those are other
agents' areas and are named in §4.
