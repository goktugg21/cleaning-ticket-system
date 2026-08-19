# Osius reference system — Agent A8: CONTEXT SWEEP (Tier 3)

Scope: everything AROUND the Extra Work / Invoicing spine. One short paragraph per
model. Purpose: decide for each one whether it touches Extra Work or Invoicing at all.
Depth was deliberately NOT pursued — anything that turned out to touch money is handed
up as a question, not investigated here.

Read-only. Repos `/tmp/osius-ref/backend` and `/tmp/osius-ref/frontend`. Live API GET only.
Nothing modified.

Labels: **CODE** = read in repo (path:line). **DATA** = live GET result. **INFERRED** = stated as such.

---

# 1. PLAIN-ENGLISH LOGIC FIRST

The reference system's "context" layer splits cleanly into three piles.

**Pile 1 — the customer/location skeleton that the money records actually hang off.**
Customer, Building, the `customer_buildings` pivot, CustomerDepartment and
CustomerWorksType are not decoration: Extra Work v1 points at a `customer_building_id`
(the pivot row, not the customer and not the building), Extra Work v2 points at
`customer_id` + `building_id` separately, and the two "slicer" tables
(CustomerDepartment = a department inside the customer's own organisation,
CustomerWorksType = the customer's own name for a kind of work) are copied straight onto
extra works, onto invoiceable items and onto the invoice header. These five are the
context models that genuinely matter for billing, because they decide *who is billed*
and *how the invoice is split*.

**Pile 2 — a contract/planning world that models money but never produces an invoice.**
Contracts carry a full billing configuration — `billing_period`, `billing_day`,
`billing_type` (advance/arrears), `payment_terms`, `first_invoice_date`,
`prorate_start` — plus yearly and monthly amounts, and they fan out into ContractProject
(per building, per discipline) and ContractLine (per service type, with `unit_price`,
`amount_year`, `amount_month`, and even a `billing_period_override`). All of it is
written by the contract screens and read back by the contract screens. Nothing in the
codebase turns a contract into an invoice: no job, no scheduler entry, no service reads
`billing_period` or `first_invoice_date` outside `ContractController`. The recurring
billing that *does* exist lives on Extra Work v2 (`BillingService` reads
`$work->billing_day`), not on contracts. So the contract world is a parallel,
disconnected money model — it looks like the invoicing engine and is not wired to one.

**Pile 3 — genuinely unrelated subsystems.** The Prj* project-management models, the
Machine* year-plan/task models, Grades (quality inspections), Setting and ServiceType are
their own worlds. Two footnotes: (a) `prj_project_products` carries `price`, `tax_rate`
and quantity — a second, independent money surface with its own product concept, which
never reaches an invoice; (b) `grades_inspections` has a nullable `extra_work_id` FK whose
migration comment says "Oluşturulan extra work (varsa)" ("the created extra work, if
any") — the model reads it, but nothing anywhere writes it. It is a wired-but-unused
escape hatch from a failed inspection to a billable job.

"Tickets" as a business object no longer exists. A migration in Nov 2025 dropped eleven
legacy ticket tables outright, keeping only the three lookup tables — status, priority,
category — which the extra works table still points at. So when this system says
"ticket status" on an Extra Work, it is reading a survivor of a deleted subsystem.

There are no complaints anywhere in the codebase.

---

# 2. EVIDENCE — one entry per model

## 2.1 Customer

(a) The customer organisation record: name, address, city, and a stack of lookup FKs
(status, type, industry, category, size). **CODE** `app/Models/Customer.php:16-33`.

(b) **YES.** `invoices.customer_id` (`app/Models/Invoice.php:68`
`return $this->belongsTo(Customer::class);`), `invoiceable_items.customer_id`
(`app/Models/InvoiceableItem.php:129`), and `extra_works_v2.customer_id`
(`app/Models/ExtraWorkV2.php:219`). Extra Work **v1** does NOT hold `customer_id` — it
reaches the customer only through `customer_building_id` (see 2.4). Handed up.

## 2.2 CustomerDepartment

(a) A department **inside the customer's organisation** (`customer_id` + name +
status). **CODE** `app/Models/CustomerDepartment.php:13-26`. Distinct from
`UserDepartment`, which is the provider's own internal department and is what
`extra_works.user_department_id` points at.

(b) **YES, three times.** `extra_works.customer_department_id`
(**CODE** `app/Models/ExtraWork.php:261`), `extra_works_v2.customer_department_id`
(**CODE** `ExtraWorkV2.php:229`), `invoiceable_items.customer_department_id`
(**CODE** migration `2026_01_29_140000_create_invoiceable_items_table.php:31` +
`:76` `->references('id')->on('customer_departments')->onDelete('set null')`), and
`invoices.customer_department_id` added later
(**CODE** `2026_02_23_100000_extend_invoices_for_invoiceable_items.php:22-23`,
comment on `:21`: "Add customer_department_id for department-level invoices";
model `Invoice.php:78`). This is an invoice-splitting dimension. Handed up.

## 2.3 CustomerWorksType

(a) The customer's own classification of a kind of work (`customer_id` + name +
status). **CODE** `app/Models/CustomerWorksType.php:13-26`.

(b) **YES.** `extra_works.customer_works_type_id` (**CODE** `ExtraWork.php:266`),
`extra_works_v2.customer_works_type_id` (**CODE** `ExtraWorkV2.php:234`), and
`invoiceable_items.customer_works_type_id` (**CODE** migration
`2026_01_29_140000...:32` and FK at `:77`). Note it is NOT on the `invoices` header —
only on the items. Handed up.

## 2.4 Building (and the `customer_buildings` pivot)

(a) A physical building: address, city, type, floor, status. **CODE**
`app/Models/Building.php:16-31`. A building is tied to a customer through the pivot
model `CustomerBuilding` (`customer_buildings`, columns `customer_id`, `building_id`,
`is_system_managed`, `created_by`, `created_at` only — **CODE**
`app/Models/CustomerBuilding.php:14-34`).

(b) **YES.** `invoices.building_id` (**CODE** migration
`2025_11_27_131834_create_invoices_table.php:24`, comment "Bina ID (opsiyonel - bazı
faturalar binaya kesilir)" = "optional, some invoices are issued to the building";
model `Invoice.php:73`), `invoiceable_items.building_id` (`InvoiceableItem.php:137`),
`extra_works_v2.building_id` (`ExtraWorkV2.php:224`). And critically Extra Work **v1**
does not use `building_id` at all — it uses `extra_works.customer_building_id`, the
pivot row (**CODE** `ExtraWork.php:42` in `$fillable`; migration
`2025_10_14_000001_refactor_extra_works_to_customer_building_id.php`). The v1/v2 split
in how a job is located is a real seam. Handed up.

## 2.5 Contract

(a) A customer contract header: number, validity window, totals
(`total_m2`, `total_hours_year`, `total_amount_year`, `total_amount_month`), a
`service_types` JSON array, and a full billing configuration. **CODE**
`app/Models/Contract.php:17-52`.

(b) **NO — not in code, despite appearances.** `contracts.first_invoice_date` exists
and is the only invoice-named column; it is written and validated only by
`ContractController` (**CODE** `ContractController.php:139,155,194,210`) and read
nowhere else in `app/` or `routes/`. Same for `billing_period` / `billing_day` /
`prorate_start`: a repo-wide grep outside `Contract.php` and `ContractController.php`
returns only `ExtraWorkV2`/`ExtraWorksV2Controller`/`BillingService` hits, and
`BillingService.php:341` reads `$work->billing_day` (the extra work), not a contract.
**DATA** `GET /admin/contracts?per_page=2` returned contract id 56, `CNT-2026-0003`,
`billing_period":"monthly"`, `billing_day":1`, `billing_type":"advance"`,
`payment_terms":30`, `first_invoice_date":null`, `prorate_start":true`,
`total_amount_month":"7591.622"` — real billing config, on a real live contract, that
no invoice code consumes. **INFERRED:** contract-based recurring invoicing is designed
but unimplemented; confirming step would be a grep of any queue/scheduler artefact —
`app/Jobs` contains only three translation jobs and `routes/console.php` contains only
Laravel's stock `inspire` command (**CODE**, both read in full), so there is no
scheduler to run it.

## 2.6 ContractLine

(a) One priced line of a contract: `service_type` (slug), `line_type_id`, `norm`,
`unit_price`, `m2`, `hours_year`, `frequency`, `amount_year`, `amount_month`, plus
share/origin bookkeeping and a `billing_period_override`. **CODE**
`app/Models/ContractLine.php:12-33`.

(b) **NO.** No `invoice`/`extra_work` column, no such relation
(repo grep of `app/Models` for `extra_work|extrawork|invoice` does not list
`ContractLine.php`). `billing_period_override` is written and read only by
`ContractLineController` (**CODE** `ContractLineController.php:79,102,148,196-197`).
Money that never reaches an invoice.

## 2.7 ContractProject

(a) A per-building, per-discipline block of a contract (`project_type` =
cleaning / glass / floor / green / food …), carrying its own yearly/monthly totals,
hours and m2, optionally linked to a `building_budget_id`. **CODE**
`app/Models/ContractProject.php:14-44`.

(b) **NO.** No invoice or extra-work column or relation. **DATA** the same contracts
call returned `projects":[{"id":63,"contract_id":56,"building_id":197,
"project_type":"food","total_amount_year":"91099.460",...}]` and a rolled-up
`project_totals":{"food":91099.46}` — totals that live and die inside the contract
screens.

## 2.8 The Prj* models (PrjProject, PrjTask, PrjTaskPlan, PrjTaskTemplate,
PrjPlanGroup*, PrjProjectAssignment, PrjProjectProduct, PrjTaskPlanAssignment,
PrjTaskTemplateItem)

(a) A separate, self-contained project-management module: a `prj_projects` header
(category, execution_mode, code, status, priority, dates, `customer_id`,
`building_id`, `estimated_hours`) with tasks, task plans, reusable task templates and
plan groups underneath. **CODE** `app/Models/PrjProject.php:15-40`.

(b) **NO** for the module as a whole — none of the Prj* files match
`extra_work|extrawork|invoice`. **One flag, not an investigation:**
`prj_project_products` carries `product_name`, `unit_type`, `quantity`, `price`,
`tax_rate` and appends `subtotal` / `tax_amount` / `total_with_tax`, and points at
`customer_department_id` + `customer_works_type_id` (**CODE**
`app/Models/PrjProjectProduct.php:10-45`). That is a second money surface using their
"Product" vocabulary and the same two invoice-splitting dimensions as
`invoiceable_items`, with no path to an invoice. Handed up as a question only.

## 2.9 The Machine* models (BuildingMachine, BuildingMachineArea, BuildingMachinePart,
MachineYearPlan, MachinePlanVersion, MachineTask, MachineTaskSchedule,
MachineTaskAssignment, MachineTaskStatus, MachineTaskVersionStatus)

(a) A machine/equipment year-planning module: machines belong to a building, are
broken into areas and parts, and get a versioned year plan of scheduled, assignable
tasks with day-type rules (weekday / weekend / any-1..any-4). **CODE**
`app/Models/MachineTask.php:12-35`.

(b) **NO.** No Machine* model matches `extra_work|extrawork|invoice`.

## 2.10 Grades (GradesTemplate*, GradesInspectionPlan, GradesInspection,
GradesInspectionSnapshotRoom, GradesInspectionFinding(+Photo),
GradesInspectionRoomCategory, GradesInspectionOutcomeEvent,
GradesInspectionReportExport)

(a) A quality-inspection module added May 2026 (migrations
`2026_05_19_100001` … `2026_05_22_110002`): templates of categories and items, an
inspection plan, an inspection that snapshots rooms, per-item findings with photos,
scoring with a `max_failure_percentage` per category, an overall status and a recheck
flow.

(b) **YES, but the link is inert.** `grades_inspections.extra_work_id` is a nullable
FK to `extra_works`: **CODE** migration
`2026_05_19_100006_create_grades_inspections_table.php:38`
`$table->unsignedBigInteger('extra_work_id')->nullable()->comment('Oluşturulan extra
work (varsa)');` with a real foreign key at `:65`. The model declares it fillable
(`GradesInspection.php:41`), casts it (`:67`), exposes
`belongsTo(ExtraWork::class,'extra_work_id')` (`:126`) and a `has_extra_work` accessor
(`:229-231`). **A grep of `app/Http/Controllers/Admin/Grades/` for `extra_work_id`
returns no assignment** — the only ExtraWork mentions in that directory are two
comments about copying its file-upload pattern (`GradesInspectionController.php:1501`,
`:1532`). `GradesInspectionOutcomeEvent.php` contains no ExtraWork reference at all.
So: a failed inspection cannot currently create or attach an Extra Work. Handed up.

## 2.11 Setting

(a) A generic key/value store: `key`, `value` (cast to array), `description`, with a
static `Setting::getValue($key, $default)` helper. **CODE**
`app/Models/Setting.php:9-30`.

(b) **NO.** Every live usage is mail templating: a repo-wide grep for `Setting::` /
`use App\Models\Setting` (excluding `UserNotificationSetting` and
`UserPrivacySetting`) hits only `MailController.php:7,904,1191,1908` and
`SettingsController.php:6,21`, all against the single key `mail_default_variables`.
There is no invoice numbering, tax rate, VAT or payment-terms setting in this table —
**INFERRED**, confirmable by listing the live `settings` rows, which I did not do.

## 2.12 ServiceType (and ServiceLineType)

(a) Lookup table `t_service_type`: slug + four-language labels + icon, colour, sort
order, `is_active`, `metadata`. **CODE** `app/Models/ServiceType.php:9-28`. Slugs grew
over time by migration — cleaning, general_cleaning, food
(`2025_12_16_100003`, `2025_12_16_230551`, `2026_01_11_165302`,
`2026_01_15_000003`). `ServiceLineType` (`t_service_line_type`) is a second lookup
scoped by `service_type` (**CODE** `ServiceLineType.php:10-25`).

(b) **NO.** Its consumers are contracts and building budgets:
`ContractLine.php:71` `belongsTo(ServiceType::class,'service_type','slug')` (joined by
slug, not id), `BuildingServiceBudget.php:86` (`service_type_id`),
`Contract::getLinesGroupedByServiceType()` (`Contract.php:249`), plus
`PrjTask`/`PrjTaskTemplate` scopes. No invoice or extra-work table carries a service
type. **This is a real asymmetry:** the contract world classifies work by ServiceType,
the extra-work/invoice world classifies it by CustomerWorksType. They do not meet.

## 2.13 Tickets

(a) **The ticket subsystem is deleted.** Migration
`2025_11_02_183945_remove_legacy_ticket_tables.php` drops eleven tables
(`task_assignments`, `ticket_tasks`, `ticket_user_starred`,
`ticket_typing_indicators`, …) after `SET FOREIGN_KEY_CHECKS=0`. Its own docblock
(**CODE** lines 12-19) states: "Removes legacy ticket system tables that have been
replaced by Extra Works system. IMPORTANT: This migration KEEPS the following tables as
they are actively used by Extra Works: t_ticket_status (referenced by
extra_works.status_id), t_ticket_priority (referenced by extra_works.priority_id),
t_ticket_category (referenced by extra_works.category_id). These tables will be renamed
in a future migration to reflect their actual usage." There is no `Ticket` model and no
`TicketTask` model left in `app/Models` — only `TicketStatus`, `TicketPriority`,
`TicketCategory`.

(b) **YES, as lookups only.** `ExtraWork.php:226` `belongsTo(TicketStatus::class,
'status_id')`, `:231` `belongsTo(TicketPriority::class,'priority_id')`, `:251`
`belongsTo(TicketCategory::class,'category_id')`; same three on
`ExtraWorkV2.php:239,244`. Also a **dangling reference**: `ExtraWork.php:271`
`return $this->hasMany(TicketTask::class, 'extra_work_id')` — the `TicketTask` class no
longer exists and `ticket_tasks` was dropped, so calling that relation would fatal.
Handed up.

## 2.14 Complaints

**Does not exist.** A grep for `complaint` across `app/Models` and
`app/Http/Controllers` returns nothing, and no migration filename contains it. Nothing
to report.

## 2.15 Incidental dead artefacts noticed while sweeping

- `app/Models/CustomerExtrawork.php` is a **0-byte file** (`wc -l` = 0). It is not a
  class; anything referencing `CustomerExtrawork` would fatal. **CODE**, measured.
- `app/Models/_old_unused/` exists as a directory, and five `.deprecated` model files
  sit in `app/Models` (`ContinuousWorkEntry`, `ExtraWorkV2Assignment`,
  `ExtraWorkV2AssignmentHour`, `WorkerAssignedHour`). Noted, not treated as live.

---

# 3. THIS AREA'S CONNECTION MAP

Only edges I actually read are drawn. `-->` means "column points at".

```
                      Customer
                      /   |   \
      customer_buildings  |    \--- CustomerDepartment ---\
        (pivot)           |     \-- CustomerWorksType ----- \
           |              |                                  \
           |              |                                   \
   extra_works            |                          invoiceable_items
   .customer_building_id  |                          .customer_id
   .customer_department_id \                         .building_id
   .customer_works_type_id  \                        .customer_department_id
   .status_id ---> t_ticket_status  (survivor of      .customer_works_type_id
   .priority_id -> t_ticket_priority  deleted ticket  .invoice_id ---> invoices
   .category_id -> t_ticket_category  subsystem)                          |
   .user_department_id -> user_departments (PROVIDER side, not customer)  |
           ^                                                              |
           | extra_work_id (nullable FK, NEVER WRITTEN)                   |
   grades_inspections                                                     |
                                                                          |
   extra_works_v2                                            invoices ----/
   .customer_id ---> Customer                                .customer_id
   .building_id ---> Building                                .building_id
   .customer_department_id                                   .customer_department_id
   .customer_works_type_id                                   (NO customer_works_type_id)
   .billing_day  --> read by BillingService

  ===== the disconnected money world (no edge to any invoice) =====

   Contract (billing_period, billing_day, billing_type, payment_terms,
             first_invoice_date, prorate_start, total_amount_year/month)
      |-- ContractProject (per building, per project_type, own totals)
      |-- ContractLine (unit_price, amount_year/month, billing_period_override)
             `--> ServiceType (joined by SLUG, not id)
      `-- BuildingServiceBudget --> ServiceType (by id)

   PrjProject --> PrjProjectProduct (price, tax_rate, quantity,
                  customer_department_id, customer_works_type_id)   [money, no invoice]

  ===== no edge to extra work or invoicing at all =====
   Machine* (BuildingMachine/Area/Part, MachineYearPlan, MachinePlanVersion,
             MachineTask/Schedule/Assignment/Status)
   Grades templates / plans / findings / photos / exports  (except the inert FK above)
   Setting  (mail_default_variables only)
```

Actions that change something across this map, as far as this sweep established:

- Creating/updating a **contract** writes billing configuration that changes **nothing**
  downstream — no invoice, no schedule, no total outside the contract screens.
- Setting an extra work's **customer_department_id / customer_works_type_id** is what
  later determines how an invoiceable item — and, for department, an invoice header —
  is sliced. That is the one context-layer choice with billing consequences.
- Deleting a **CustomerDepartment / CustomerWorksType** does not orphan an invoiceable
  item: the FKs are `onDelete('set null')` (**CODE**
  `2026_01_29_140000_create_invoiceable_items_table.php:76-77`), so the slice silently
  becomes blank. Both models also use `SoftDeletes`, so an ordinary UI delete would not
  fire the FK action at all.

---

# 4. COULD NOT DETERMINE

1. **Whether contract billing config is consumed outside PHP.** I grepped `app/` and
   `routes/` only. A database view, a stored procedure, an external ERP export or a
   cron outside this repo could read `contracts.billing_period` / `first_invoice_date`.
   To close: list MySQL views/events/triggers, and check the deployment's system crontab.
2. **What the live `settings` table actually contains.** I read every code reference
   (all `mail_default_variables`) but never listed the rows. If a settings admin
   endpoint returns all keys, one GET closes it.
3. **Whether any historic `grades_inspections` row has a non-null `extra_work_id`.**
   Code writes it nowhere, but data could have been seeded or set by hand. To close:
   GET the grades inspections list and look for a non-null `extra_work_id`.
4. **Whether `ExtraWork::tasks()` (`ExtraWork.php:271`, `hasMany(TicketTask::class)`) is
   ever called.** I confirmed the class and table are gone, but not that no controller
   eager-loads `tasks`. To close: grep controllers/resources for `'tasks'` in `with()`
   arrays on ExtraWork queries — I did not, to stay in budget.
5. **Building / Customer soft-delete behaviour against issued invoices.** Both use
   `SoftDeletes`; I did not check whether invoice queries join without
   `withTrashed()`, which would make a soft-deleted customer's invoices vanish from
   lists. To close: read the invoice list query's joins.
6. **The frontend side of every model above.** This sweep was backend-only by design;
   no `/tmp/osius-ref/frontend` file was read. Screen-level behaviour for these context
   models is unverified.
7. **ContractRevision / ContractRevisionLine, ContractLinePlanning,
   BuildingCostDistribution, BuildingServiceBudget, CustomerServiceAllocation,
   CustomerProduct / CustomerProductPrice / CustomerProductVersion,
   ContinuousWork\*** were outside my named list and were NOT swept. Several of them
   are money-shaped and `ContinuousWork*` demonstrably touches Extra Work v2
   (`ExtraWorkV2.php:605,613` `hasMany(ContinuousWorkPeriod::class,
   'extra_work_v2_id')`, `hasMany(ContinuousWorkWorker::class, ...)`). They need an
   owner.
