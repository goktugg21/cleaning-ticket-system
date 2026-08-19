# Osius reference system - Agent A4: the hours chain

Scope: every table, model, endpoint and screen in this system that stores a NUMBER OF
HOURS or turns hours into money. Nothing in the reference system was modified; every
API call was a GET through the read-only wrapper.

Evidence labels used throughout:

- **CODE** - a path + line I read, with the line quoted.
- **DATA** - an endpoint I called through the read-only wrapper, and the values returned.
- **INFERRED** - a conclusion I drew, stated as such, with what would confirm it.

Vocabulary note: their **Product** is our **Service**. Every place where a Product and
an hour meet money is flagged `[PRODUCT=SERVICE]`.

---

# 1. Plain-English logic first

## 1.1 There are FOUR separate hour systems, and they do not talk to each other

This is the single most important fact in the area. A number of hours in this system can
live in any of four unconnected places:

| # | Where hours live | What it is | Money? |
|---|---|---|---|
| 1 | `extra_works.hours_planed` / `extra_works.hours_worked` | two loose decimal columns on the v1 Extra Work record | **no** |
| 2 | `extra_work_employee_hours` | the v1 labour ledger: one row per employee per day per overtime type | **yes** - `total_cost` |
| 3 | `worker_planned_hours` + `worker_approved_hours` | the "unified" v2 / project / continuous-work hours system with a submit -> approve -> revert lifecycle | **yes** - `total_cost` on the approved row |
| 4 | `contracts.total_hours_year` / `contract_lines.hours_year` | contracted hours per year, a pricing input on the contract | yes, but it is a **budget**, computed from nothing an employee ever did |

**No number ever crosses between them.** There is no join, no sync, no observer, no job,
no data migration that carries a value from one family to another. I checked every
reader and writer of each table (see section 2.7 and 4).

The practical consequence: the same employee, in the same calendar week, can appear in
two different "hours" screens with two different totals, and neither screen knows the
other exists. I proved this live - see section 2.7.

## 1.2 `hours_planed` is a decoration. `hours_worked` is a ghost.

`hours_planed` ("budget hours") is written from **six** different places in the SPA and
one dedicated endpoint. It is read back only to be **printed on a screen**. It caps
nothing, warns nothing, blocks nothing and touches no price. A work with
`hours_planed = 1.00` and 13.5 distributed hours produces no warning anywhere - that is
a real live record (id 474).

`hours_worked` is worse. It is writable by the same endpoints, but **all 39 live v1
Extra Works have `hours_worked = null`.** Its only real consumer is
`ExtraWork::getRemainingHours()`, and because it is always null that function
degenerates (section 1.4). Two live UI gates *do* reference it - a kanban drag rule and a
"distribute hours" modal - and one of the two is in a component nothing imports.

## 1.3 Labour money: the exact formula, and the two ways it silently becomes zero

Labour cost lives **only** on `extra_work_employee_hours.total_cost`, and it is written
by a model `saving` hook:

```
total_cost = round( hours x hourly_rate x overtime_multiplier , 2 )
```

- `hourly_rate` is **snapshotted onto the hour row at creation time** from the employee's
  current rate. It is never re-read, never re-computed, and the update endpoint cannot
  change it.
- `overtime_multiplier` is read **live from `overtime_types` at the moment the row is
  saved**, then discarded. Editing a multiplier later does **not** re-price existing rows,
  but every screen still shows the *new* multiplier next to the *old* cost.
- If the employee has no hourly rate, the snapshot is `0` (not null, no exception) and
  the labour cost of those hours is **EUR 0.00**, silently.

Live proof of all three: on Extra Work 474, three employees booked 13.5 hours. Two of
them (7.5 hours) had no rate, so they cost EUR 0.00. The third booked 6 hours at a
snapshotted 30.00 x 1.5 = EUR 270.00 - even though that employee's *only* stored rate
today is 33.00. See section 2.4.

Of 40 live employees, **35 have no hourly rate at all**. Any hour booked for them is free.

## 1.4 `getRemainingHours()` is structurally always zero, and `canDistributeHours()` is dead

The brief asked me to verify three beliefs separately. All three are **CONFIRMED**, and
one of them is worse than the brief thought:

1. **"`hours_planed` is written in several places and read only for display"** -
   CONFIRMED. Six writers, zero decision-readers.
2. **"`canDistributeHours()` exists and is NEVER CALLED"** - CONFIRMED. Exactly one
   occurrence in the entire backend and frontend: its own definition.
3. **"`getRemainingHours()` does NOT use `hours_planed`"** - CONFIRMED, and it is worse
   than "does not use". Its formula is
   `$this->hours ?? $this->hours_worked ?? $this->total_hours ?? 0`, where:
   - `$this->hours` does not exist on the model at all -> always null;
   - `$this->hours_worked` is null on every live record;
   - `$this->total_hours` is an accessor that returns **the distributed hours themselves**.

   So the expression collapses to `max(0, distributed - distributed)` = **0, always.**
   Live: every single record I queried returned `remaining_hours: 0`, including one with
   13.5 distributed hours.

   And because `canDistributeHours($h)` is `getRemainingHours() >= $h`, if anyone ever
   wired it up it would **refuse every single distribution**. It is dead code that would
   break the feature if revived.

There is a third dead guard: `ExtraWorkEmployeeHour::validateTotalHours()`, a full
throw-on-overrun check, never called. The model's own boot method carries the epitaph:
`// Hours validation removed per user request` / `// No limit check on distributed hours
vs extra work total hours`.

**Net: nothing anywhere caps how many hours can be booked against an Extra Work.**

## 1.5 The hours you can see are not the hours you are charged for

The Extra Work detail screen's hours grid is built from the **worker-assignment list**
(`extrawork_worker_assignments`), then hours are attached to it by matching
`employee_id`. Hour rows whose employee is no longer an assigned worker are **invisible
in the grid but still counted in every total**.

This is not theoretical. Live:

- Extra Work **474**: `distributed_hours: 13.5`, `total_labor_cost: 270`, and
  `assigned_workers: []` - **the grid is completely empty**.
- Extra Work **469**: `distributed_hours: 2.5`, `total_labor_cost: 82.5`, three assigned
  workers all showing `0 hours / 0 cost`.
- Extra Work **448**: 1 hour, `assigned_workers: []`.

The cause is three different worker-removal code paths, only one of which cascades the
hour deletion (section 3.4). Two of them orphan the hours and their money.

## 1.6 Extra-work hours reach the weekly sheet as a read-time projection, ungated

Question 5 of the brief, answered: **it is a projection computed at read time, it is a
raw SQL join, and it is NOT gated on the Extra Work's status.**

`GET /admin/prj-weekly-projects/extra-works?year&week` joins
`extra_work_employee_hours -> extra_works -> extra_work_customer_building -> buildings/
customers`, filtered on **`work_date` inside the ISO week** and `extra_works.deleted_at
IS NULL`. That is the entire filter. No status check, no approval check, no assignment
check.

Live proof: Extra Work **553** is `status_id = 1` (Nieuw - not planned, not completed,
not approved, not invoiced). Its 5 hours appear on the week-3-2026 planning sheet, in
the HR "hours by building" report, and in the weekly employee-hours report.

Note also there is **no weekly *contract* sheet fed by worked hours**. `contracts` /
`contract_lines` carry `hours_year` as a *sold* quantity used for pricing; nothing in the
codebase compares it to hours actually worked.

## 1.7 The v1 draft / saved / approved flow locks nothing

`extra_work_employee_hours.status` has three values, and the model's own comment gives
the Dutch meaning:

```
draft        = Gepland      (planned)
pre-approved = Goedgekeurd  (approved)
approved     = Gecorrigeerd (corrected)
```

Read that twice. **The string `approved` means CORRECTED, not approved.** The string that
means "approved" is `pre-approved`. Every reader in the codebase honours this inversion,
so it is internally consistent - but it is a trap for anyone reading the database.

Transitions are driven from the weekly planning page, one POST per state, with no guard
of any kind:

| Button | Endpoint | Writes |
|---|---|---|
| Goedkeuren | `POST /admin/prj-weekly-projects/extra-works/hours/{id}/approve` | `status = 'pre-approved'` |
| Intrekken | `.../reject` | `status = 'draft'` |
| Corrigeren | `.../correct` | `status = 'approved'` |

**Nothing locks at any step.** A "corrected" hour row can still be edited, re-priced and
hard-deleted by the same page, and by the Extra Work detail tab, and by the bulk-delete
endpoints. There is no immutability hook, no reason field, no history row.

Live status distribution across every week of 2025 and 2026 (70 hour rows):
**53 `draft`, 0 `pre-approved`, 17 `approved`(=corrected).** The middle state has never
been used - operators appear to go straight from Gepland to Gecorrigeerd, or never move
at all.

## 1.8 The v2 flow DOES lock - and "drift" is where its two numbers diverge

The word **"drift" does not appear anywhere in this codebase** (I grepped the whole tree;
the only hit is an unrelated `frontend/.i18nrules`). But the *concept* the brief is
pointing at exists and is deliberate, in the `worker_planned_hours` /
`worker_approved_hours` pair:

- `worker_planned_hours.planned_hours` is what was planned.
- On approval a **separate immutable snapshot row** is written to
  `worker_approved_hours.approved_hours`, and the approver **may override the number**.
- The planned row is then marked approved but its `planned_hours` is deliberately left
  alone. The code comment says it outright: `// Update planned record status (but NOT the
  hours!)`.
- On revert, the approved row is stamped `is_corrected = true` with
  `original_hours` = the pre-correction figure, and the planned row goes back to draft
  **still holding the original planned number**.

So "drift" = the gap between planned and approved for the same day. `getWeeklyData`
returns `total_planned_hours` and `total_approved_hours` side by side, which is the
screen where the drift is visible.

This family DOES lock: `WorkerPlannedHour::updating` throws if a submitted/approved row's
hours, employee, date or overtime type are touched; `deleting` throws on approved rows;
`WorkerApprovedHour::updating` throws on any field except the five correction fields.

**But there is a second, incompatible approval path that bypasses all of it** - see
section 1.9.

## 1.9 Two mutually incompatible approvals write the same table

`worker_planned_hours` has two independent approval mechanisms:

**Path A - the service (`WorkerHoursApprovalService`).** Creates a `WorkerApprovedHour`
snapshot row, computes `total_cost`, and links it back via
`worker_planned_hours.approved_hour_id`. This is the only path that produces money.

**Path B - `PrjCentralizedPlanningController`.** Uses `DB::table(...)->update()`, which
bypasses every model event and every lock. It sets `status = 'approved'` plus the
separate `approved_by` / `approved_at` **columns**, and **creates no
`WorkerApprovedHour` at all.**

A row approved through Path B:

- has `status = 'approved'`, so `isLocked()` is true and it can never be edited again;
- has `approved_hour_id = null`, so the revert workflow (which starts from an approved-hour
  id) can never unlock it;
- has **no cost row anywhere**, so its labour money simply does not exist;
- **disappears from the weekly planning screen**, which lists planned rows
  `WHERE status != 'approved'` and approved rows from `worker_approved_hours` - and the
  Path-B row is in neither set.

Path B also accepts `status = 'planned'`, a value that is not in the model's `STATUSES`
enum and not in the migration's column enum.

## 1.10 Where hours DO touch money, and where they conspicuously do not

| Hour number | Reaches money? | How |
|---|---|---|
| `extra_work_employee_hours.hours` | **yes** | x snapshotted rate x live multiplier -> `total_cost` |
| `extra_work_employee_hours.total_cost` | **shown** on `priceBreakdown` as part of the grand total, at a hard-coded 21% VAT | but **never reaches an invoice** - confirms tier-1 A2/A3 |
| `extra_works.hours_planed` | **no** | display only |
| `extra_works.hours_worked` | **no** | never multiplied by anything |
| `extra_work_products.hours_worked` `[PRODUCT=SERVICE]` | **no** | the line subtotal is `price x quantity`; `hours_worked` is not in it |
| `worker_planned_hours.planned_hours` | only via approval | `WorkerApprovedHour.total_cost` |
| `worker_planned_hours.actual_hours` | **no** | never read into any cost |
| `worker_approved_hours.total_cost` | computed and stored | no invoice, no report, no export reads it |
| `contract_lines.hours_year` | **yes** | but as a sold budget, disconnected from worked hours |

`[PRODUCT=SERVICE]` The most misleading of these is `extra_work_products.hours_worked`.
The only place that treats it as money is a frontend modal
(`ExtraWorkProductEditModal.jsx`) which computes `price x hours_worked` for hourly
products - and that component is **imported by nothing**. The backend's authoritative
line total is `price x quantity`, always. A "per Uur" service line priced by hours is
therefore priced by its `quantity` column, not by its `hours_worked` column.

---

# 2. Evidence

## 2.1 The models

### `ExtraWorkEmployeeHour` - `app/Models/ExtraWorkEmployeeHour.php`

**CODE** `:11` `protected $table = 'extra_work_employee_hours';`

**CODE** `:19-27` the three statuses and their real meanings:
```php
* draft = Gepland (planned)
* pre-approved = Goedgekeurd (approved)
* approved = Gecorrigeerd (corrected)
public const STATUS_DRAFT = 'draft';
public const STATUS_PRE_APPROVED = 'pre-approved';
public const STATUS_APPROVED = 'approved';
```

**CODE** `:29-41` fillable: `extra_work_id, employee_id, work_date, hours,
overtime_type_id, hourly_rate, total_cost, status, notes, created_by, updated_by`.

**CODE** `:55-70` the ONLY writer of labour money:
```php
static::saving(function ($model) {
    if ($model->isDirty(['hours', 'hourly_rate', 'overtime_type_id'])) {
        $multiplier = 1.00;
        if ($model->overtime_type_id) {
            $overtimeType = OvertimeType::find($model->overtime_type_id);
            if ($overtimeType) { $multiplier = $overtimeType->multiplier; }
        }
        $model->total_cost = round($model->hours * $model->hourly_rate * $multiplier, 2);
    }
});
```
Note: `hourly_rate` is in the dirty-check list but **no live endpoint ever makes it
dirty after creation** - see 2.3.

**CODE** `:72-73` the removed guard, verbatim:
```php
// Hours validation removed per user request
// No limit check on distributed hours vs extra work total hours
```

**CODE** `:122-146` `validateTotalHours()` - a complete overrun check that throws.
**DEAD** - `grep -rn "validateTotalHours" backend frontend` returns exactly one line,
its own definition.

**CODE** `:176-196` `scopeDraft/scopePreApproved/scopeApproved/scopeByStatus`.
**DEAD** - grep finds no caller outside the model file.

**CODE** `:200-247` `getTotalHoursForExtraWork`, `getTotalCostForExtraWork` -
**DEAD**, no callers. `getSummaryByEmployee` / `getSummaryByDate` are live (the summary
endpoint).

**No migration in `database/migrations/` creates this table.** `grep -rn
"extra_work_employee_hours" database/` returns **nothing**. See section 5.

### `OvertimeType` - `app/Models/OvertimeType.php`

**CODE** `:16-35` fillable includes `multiplier`, `type`, `is_paid`, `is_active`,
`sort_order`, and five label / five description columns.

**CODE** `:37-41` `'multiplier' => 'decimal:2'`.

**CODE** `:112-115` `calculateCost(float $baseAmount)` - **DEAD**, no callers.

**DATA** `GET /admin/overtime-types` returns 8 active types:

| id | code | label | label_nl | multiplier | type |
|---|---|---|---|---|---|
| 1 | GU | Normale uren | Normale uren | 1.00 | normal |
| 2 | GU 150 | Weekend uren 150% | Overwerk | 1.50 | overtime |
| 3 | GU 130 | Nacht uren 130 | **Weekend** | 1.30 | weekend |
| 4 | GU 250 | Feestedag 250% | Feestdag | **2.50** | holiday |
| 5 | ZU | ZU uren | Ziekteverlof | 1.00 | sick_leave |
| 6 | SU | Snipper uren 100% | Vakantie | 1.00 | vacation |
| 10 | ZU 150 | ZU 150% | null | 1.50 | vacation |
| 11 | SU 150 | SU 150% | null | 1.50 | vacation |

Three data problems visible in that table alone:
1. **The labels contradict themselves and each other.** id 3 is `label` "Nacht uren 130",
   `label_nl` "Weekend", `description_nl` "Weekenduren (175%)", `type` "weekend",
   `multiplier` 1.30. Four different stories in one row.
2. **`label` vs `label_nl` disagree on ids 2 and 3**, and different endpoints pick
   different ones: `ExtraWorkEmployeeHoursController::index` and
   `PrjCentralizedPlanningController` use `label`; `WorkerHoursApprovalService` uses
   `getLocalizedName()` which prefers `label_{locale}`. **The same overtime type is named
   differently on two screens.**
3. **`code` ("GU", "GU 150", ...) is in neither `$fillable` nor the controller's
   validation rules** (`OvertimeTypeController.php:115-134`, `:173-192`). It is real,
   populated data that **no API path can write**. INFERRED: set directly in SQL.

**CODE** `OvertimeTypeController.php:184` `'multiplier' => 'sometimes|required|numeric|
min:0|max:10'` under `ucb.permission:employees,update` - the multiplier is freely
editable, and because `total_cost` is stored, editing it **does not re-price history**
while every screen shows the new multiplier next to the old cost.

**CODE** `OvertimeTypeController.php:223-240` `destroy()` - the usage guard is
**commented out**:
```php
// Check if type has employee hours (when implemented)
// $usageCount = $type->employeeHours()->count();
// if ($usageCount > 0) { return $this->error(...); }
$type->delete();
```
A hard delete. `worker_planned_hours` / `worker_approved_hours` declare
`onDelete('set null')`; `extra_work_employee_hours` has no migration so its FK behaviour
is unknown (section 5).

### `EmployeeHourlyRate` - `app/Models/EmployeeHourlyRate.php`

**CODE** `:19-27` fillable: `employee_id, hourly_rate, currency, effective_from,
effective_to, notes, is_active, created_by, updated_by`.

**CODE** `:91-100` `scopeCurrent()` - correctly checks `effective_from <= today` AND
(`effective_to` null OR `>= today`).

**CODE** `:104-111` `scopeEffectiveOn($date)` - the historically-correct lookup.
**Used by exactly one endpoint** (`GET .../hourly-rates/for-date`) and by **no cost
calculation anywhere.**

**CODE** `Employee.php:194-200` - the resolver that actually prices labour:
```php
public function currentHourlyRate()
{
    return $this->hasOne(EmployeeHourlyRate::class)
        ->where('is_active', true)
        ->latest('effective_from');
}
```
**It does not use `scopeCurrent()`.** It ignores `effective_from` and `effective_to`
entirely. Two consequences: a **future-dated** active rate is used immediately, and an
**expired** active rate keeps being used forever.

**DATA** proof of the expired case. `GET /admin/employees/24/hourly-rates` returns exactly
one row: `hourly_rate "33.00"`, `effective_from 2025-11-02`, `effective_to 2025-12-11`,
`is_active true`, and the model's own accessor says `"is_current": false`. Yet
`GET /admin/employees?per_page=100` reports employee 24 with `hourly_rate: 33` - because
the `currentHourlyRate` relation returned the expired row.

**CODE** `Employee.php:239-243`:
```php
public function getCurrentHourlyRateValue(): ?float
{
    $rate = $this->currentHourlyRate()->first();
    return $rate ? (float) $rate->hourly_rate : null;
}
```
Returns **null** when there is no rate. Every caller coerces it: `?? 0`.

**CODE** `EmployeeHourlyRateController.php:99-102, 216-247` `store()` auto-deactivates
overlapping rates (`auto_deactivate_previous`, default true) by setting `is_active=false`
and `effective_to = new_from - 1 day`. **CODE** `:149-159` `destroy()` is a hard delete -
there is no soft delete on this model, so a rate history row can be erased while hour rows
that snapshotted it survive.

**DATA** Of 40 live employees, only **5** have any hourly rate: ids 9 (30), 15 (33),
24 (33, expired), 37 (33), 39 (17.5). **35 of 40 employees price at EUR 0.00.**

### `WorkerPlannedHour` - `app/Models/WorkerPlannedHour.php`

**CODE** migration `2026_02_11_120000_create_worker_planned_hours_table.php` gives the
true schema: `source_type` enum(extra_work, continuous_work, project, machine, other)
default 'extra_work'; `source_id`; `plan_group_id`; `task_id`; `employee_id`; `work_date`;
`day_of_week` enum; `year` int; `week_number` int; `planned_hours` decimal(5,2) default 0;
`overtime_type_id`; `hourly_rate` decimal(10,2) nullable; `status` enum(draft, submitted,
approved, rejected) default 'draft'; `submitted_at`; `submitted_by`; `approved_hour_id`;
`notes`; `created_by`; `updated_by`.

**CODE** `2026_02_24_141000_add_actual_hours_to_worker_planned_hours.php:16-18` adds
`actual_hours` decimal(5,2), `approved_by`, `approved_at`. **None of the three is in the
model's `$fillable`.** They are reachable only through raw `DB::table()` writes.

**CODE** unique index `unique_wph_entry` on
`(source_type, source_id, task_id, employee_id, work_date, overtime_type_id)`. Because
`task_id` and `overtime_type_id` are nullable and MySQL treats NULLs as distinct in a
unique index, **duplicate rows are possible whenever either is null** - which is the
normal case for extra-work hours.

**CODE** `:264-268` `getTotalCostAttribute()` = `planned_hours x (hourly_rate ?? 0) x
multiplier` - a computed attribute, **not stored**, and not in `$appends`. It is used
nowhere. **DEAD.**

**CODE** `:335-350` `submit()`, `:355-365` `reject()`, `:372-382` `revertToDraft()`.

**CODE** `:307-311` `isLocked()` = status in (submitted, approved).
**CODE** `:432-437` `updating` hook:
```php
if ($model->isLocked() && $model->isDirty(['planned_hours','employee_id','work_date','overtime_type_id'])) {
    throw new \Exception('Cannot modify locked (submitted/approved) planned hours. Use revert first.');
}
```
**CODE** `:441-445` `deleting` hook throws on approved rows.

**CODE** `:161-169` and `:172-180` - `extraWork()` resolves to **`ExtraWorkV2`**, not the
v1 `ExtraWork`. Same in `WorkerApprovedHour.php:143-146`. This is the structural proof
that `source_type = 'extra_work'` here means **v2**, never v1.

### `WorkerApprovedHour` - `app/Models/WorkerApprovedHour.php`

**CODE** migration `2026_02_11_120001` : `approved_hours` decimal(5,2) NOT NULL,
`hourly_rate` "Rate at approval time", `total_cost` "Calculated: hours * rate *
multiplier", `approved_at`/`approved_by` NOT NULL, plus the correction block
`is_corrected`, `corrected_at`, `corrected_by`, `correction_reason`,
`original_hours` "Hours before correction". FK `planned_hour_id ... onDelete('restrict')`.

**CODE** `:288-311` `createFromPlanned()` - the snapshot:
```php
$multiplier = $planned->overtimeType?->multiplier ?? 1;
$totalCost = (float) $planned->planned_hours * (float) ($planned->hourly_rate ?? 0) * $multiplier;
```
It copies `planned_hours` into `approved_hours`. **It never looks at `actual_hours`.**

**CODE** `:316-330` `updating` hook - immutable except
`is_corrected, corrected_at, corrected_by, correction_reason, original_hours`.
**CODE** `:332-333` `// Allow deletion via revert workflow / No deleting protection -
hard delete is allowed`. So the "immutable" row can be hard-deleted.

**CODE** `:247-259` `getCalculatedCostAttribute()` - recomputes from the live multiplier.
**DEAD**, no callers - which means the stored `total_cost` is never reconciled against
the current multiplier.

### `WorkerAssignedHour.php.deprecated` and `ExtraWorkV2AssignmentHour.php.deprecated`

Both carry the `.deprecated` suffix and are not autoloadable. Their tables were dropped:
`2026_02_11_160000_drop_worker_assigned_hours_table.php`,
`2026_02_11_142944_drop_extra_work_v2_assignments_tables.php`. Their data was copied into
`worker_planned_hours` by `2026_02_11_130000_migrate_worker_hours_data.php`.
**CODE** that migration's `up()` migrates three sources - `worker_assigned_hours`,
`prj_project_assignments`, `extra_work_v2_assignment_hours` - and
**`extra_work_employee_hours` is not one of them.** The v1 ledger was never folded in.

### `EmployeeContract` / `EmployeeContractType` - NOT hours models

**CODE** `EmployeeContract.php:17-31` fillable: `employee_id, contract_type_id,
contract_number, title, start_date, end_date, salary, file_guid, file_name, file_size,
mime_type, description, created_by, updated_by`. **There is no hours column.** It is an
HR document holder with a PDF attached.

**CODE** `:36-42` `$casts` contains `'is_active' => 'boolean'` and `:78-81`
`scopeActive()` filters on `is_active`, but `is_active` is **not in `$fillable`** and
there is **no migration creating `employee_contracts`** - so whether the column exists at
all is unverified. If it does not, `scopeActive()` raises an SQL error.

**CODE** `:249-256` `boot()` `deleting` hook checks `$contract->file_path`, a property
that is **not in `$fillable` and not in `$casts`** - the file column is `file_guid`. So
the storage cleanup never fires. Orphaned files on delete. (INFERRED from the field-name
mismatch; confirmed only by reading, not by executing.)

**DATA** `GET /admin/employee-contracts?per_page=5` -> `"total": 0`. **Zero live rows.**

### Contract hours - `Contract` / `ContractLine` / `ContractLinePlanning`

**CODE** `ContractLine.php:23` `hours_year`; `Contract.php:26` `total_hours_year`.
**CODE** `Contract.php:220-234` `calculateTotals()` sums `hours_year` across lines into
`total_hours_year`.
**DATA** `GET /admin/contracts?per_page=3` -> contract 56 `total_hours_year: "11960.95"`,
`total_amount_year: "91099.460"`, `project_hours: {"food": 11960.95}`.

**CODE** `ContractLinePlanning.php:35-55` is the weekly contract *execution* row -
`year`, `week_number`, `scheduled_day`, `status_id`, `actual_hours`, `completed_at`.
`markAsCompleted(int $userId, ?float $actualHours = null, ...)` (`:203-213`) is its only
hours writer.

**Nothing joins any of this to `extra_work_employee_hours` or `worker_*_hours`.** The
complete reader/writer list of the v1 hours table (section 2.7) contains no contract file.

## 2.2 `hours_planed` - the complete read/write map

**NAME** `extra_works.hours_planed`, `decimal(10,2)` nullable
(**CODE** `2025_10_27_020441_add_hours_planed_to_extra_works_table.php:15`)

**WRITTEN BY**

| Writer | Evidence |
|---|---|
| `PATCH /admin/extra-works/{id}/hours` -> `ExtraWorksController::updateHours` | **CODE** `:5640` `'hours_planed' => 'nullable|numeric|min:0|max:999999.99'`; `:5645-5647` |
| `PUT /admin/extra-works/{id}` (config allow-list; `fillable => true`) | **CODE** `config/base/extra-works.php:209-218` |
| SPA plan modal (status 1 -> 2) | **CODE** `extra-works/detail.jsx:920-922` |
| SPA approval modal (status -> 4), editable field | **CODE** `modals/ExtraWorkApprovalModal.jsx:64, 124-127, 200-201` |
| SPA bulk plan modal | **CODE** `modals/ExtraWorkBulkPlanModal.jsx:150, 207-209` |
| SPA group bulk edit modal | **CODE** `modals/GroupBulkEditModal.jsx:205, 496` |
| SPA hours tab "budget hours" pencil | **CODE** `modules/ExtraWorkEmployeeHoursTab.jsx:759-770` |

**READ BY** - display only, every one of them:

| Reader | What it does with it | Evidence |
|---|---|---|
| `updateHours` response payload | echoes it back | **CODE** `ExtraWorksController.php:5667` |
| Info tab | `{hours_planed}h` or `'N/A'` | **CODE** `modules/ExtraWorkInfoTabPanel.jsx:704` |
| Detail header (x2) | prints `{hours_planed}h` | **CODE** `components/ExtraWorkDetailHeader.jsx:630-634, 889-895` |
| Sticky financial widget | a row labelled "Uren" | **CODE** `components/FinancialStatusWidget.jsx:53, 157-166` |
| Hours tab summary card | `summary.plannedHours.toFixed(1)}h` | **CODE** `modules/ExtraWorkEmployeeHoursTab.jsx:443, 1145-1148` |
| Completion modal | prints it | **CODE** `modals/ExtraWorkCompletionModal.jsx:362` |
| 4 bulk modals (approve / complete / archive-approve / archive-reject) | a read-only "Budget Hours" cell | **CODE** `ExtraWorkBulkApproveModal.jsx:179`, `ExtraWorkBulkCompleteModal.jsx:199`, `ExtraWorkBulkArchiveApproveModal.jsx:179`, `ExtraWorkBulkArchiveRejectModal.jsx:209` |
| the two `portal_extra_works` SQL views | selected, never used in PHP | **CODE** `2025_11_10_192031:22,126`, `2025_12_09_031108:23,121` |
| v1 -> v2 one-shot migration | copied to `extra_works_v2.duration_hours` | **CODE** `2026_01_26_100000_migrate_extra_works_to_v2.php:72,137` |

**IF NULL/EMPTY** - the header and widget hide the row (`{extraWork.hours_planed && ...}`);
the info tab prints `'N/A'`; the summary card and bulk modals print `0.0h` /
`0.00h` (`parseFloat(...) || 0`).

**GATES** - **none.** It blocks no button, no transition, no price, no invoice period.
Not compared to distributed hours anywhere. Not used by `getRemainingHours()`.

**DEAD?** Not dead - it is written, stored and displayed. But it is **inert**: no
decision in the system depends on its value.

**DATA** live values across 39 records: `45.00, 2.00, 1.00, 1.50, 2.50, 0.00` and 26
nulls. Record 474 has `hours_planed: "1.00"` against `total_hours: 13.5` - a 13.5x
overrun with no warning anywhere in the UI.

## 2.3 `hours_worked` - the complete read/write map

Careful: **three different columns share this name** on three different tables. They are
unrelated.

### (a) `extra_works.hours_worked`, `decimal(8,2)` nullable
(**CODE** `2025_10_18_103000_add_hours_worked_completion_notes_to_extra_works.php:12`,
comment "Total hours worked")

**WRITTEN BY**
- `PATCH /admin/extra-works/{id}/hours` (**CODE** `ExtraWorksController.php:5641,5649-5651`)
- `PUT /admin/extra-works/{id}` via the config allow-list (`config/base/extra-works.php:199-208`)
- SPA hours-tab pencil (**CODE** `ExtraWorkEmployeeHoursTab.jsx:792-803`)
- SPA kanban validation modal (**CODE** `components/KanbanValidationModal.jsx:56,231-236`)
- explicitly **nulled** by the SPA's 3 -> 2 revert (**CODE** `extra-works/detail.jsx:1026`)

**READ BY**
- `ExtraWork::getRemainingHours()` - **CODE** `ExtraWork.php:525` (structurally inert, 1.4)
- `ExtraWorkEmployeeHour::validateTotalHours()` - **CODE** `:141` (dead)
- `comprehensiveReport` payload - **CODE** `ExtraWorksController.php:4792`
- `/employee-hours` + `/summary` `total_hours` field - **CODE** `ExtraWorkEmployeeHoursController.php:105, 671`
- SPA timeline - **CODE** `modules/ExtraWorkTimelineTab.jsx:97-98`
- SPA kanban gate 2 -> 3 - **CODE** `components/ExtraWorkKanbanView.jsx:499-501`
- SPA hours-tab summary card - **CODE** `ExtraWorkEmployeeHoursTab.jsx:444`
- melding QA flag `hours_worked > 24h` - **CODE** `reports/melding/MeldingReport.jsx:156-157`
- the two `portal_extra_works` SQL views
- v1 -> v2 migration -> `extra_works_v2.actual_hours`

**IF NULL/EMPTY** - `getRemainingHours()` falls through to `total_hours` and returns 0
(1.4). The kanban 2 -> 3 drag is **blocked** with "Hours worked required". The timeline
entry is suppressed. Every `total_hours` echo becomes 0.

**GATES** - exactly two, both client-side:
1. **CODE** `ExtraWorkKanbanView.jsx:498-501` - blocks the kanban drag from status 2 to 3
   unless `hours_worked > 0`. This is a **live** component (imported by
   `extra-works/index.jsx`). The equivalent server endpoint (`PUT /{id}` with
   `status_id: 3`) has no such check.
2. **CODE** `modals/EmployeeHoursDistributionModal.jsx:331-336, 380-385, 460-461` - the
   only "total distributed <= hours_worked" cap in the entire product:
   `if (totalHours > hoursWorked) setError('Total hours (...) exceeds hours worked (...)')`.
   **This component is imported by nothing.** `grep -rn "EmployeeHoursDistributionModal"
   src` returns only the file itself and one markdown changelog. **DEAD component, and it
   was carrying the only cap.**

**DATA** `hours_worked` is **null on all 39 live v1 Extra Works.** The kanban gate is
therefore permanently closed for any drag 2 -> 3, and every operator must be using the
modal path instead.

### (b) `extra_work_products.hours_worked`, `decimal(10,2)` nullable `[PRODUCT=SERVICE]`
(**CODE** `2025_10_12_000002_add_status_to_ticket_extrawork_products.php:21`, comment
"Actual hours worked")

**WRITTEN BY** `ExtraWorkService::addProduct` / `updateProduct` (**CODE**
`app/Services/ExtraWorkService.php:76`).
**READ BY** `ExtraWorkService::getProducts` summary only:
**CODE** `:51` `'total_hours' => $products->sum('hours_worked'),`
**NOT READ BY** the line total. **CODE** `ExtraWorkProduct.php:78-81`:
```php
public function getSubtotalAttribute(): float
{
    return round($this->price * $this->quantity, 2);
}
```
So an hourly service line is priced by `quantity`, not by `hours_worked`. The only code
that prices it by hours is **CODE** `documents/components/ExtraWorkProductEditModal.jsx:
85-86` `// Saatlik: price x hours_worked` - and that file is imported nowhere, and three
of its actions are stubs (`// TODO: API call ... (Backend API pending)`).
**Effectively DEAD as money.**

### (c) `machine_task_assignments.hours_worked` / `extra_work_v2_assignments.hours_worked`
Out of my scope; noted so nobody confuses them with (a). The v2 assignments table was
dropped in `2026_02_11_142944`.

## 2.4 Labour cost - formula, snapshot point, and the NULL case

**The formula.** **CODE** `ExtraWorkEmployeeHour.php:68`
`$model->total_cost = round($model->hours * $model->hourly_rate * $multiplier, 2);`

**Where the rate is snapshotted.** At **row creation**, from the employee's *current*
rate. Four creation paths, all of them reading the same resolver:

| Creator | Rate source | Evidence |
|---|---|---|
| `POST /admin/extra-works/{id}/employee-hours` (single) | `$employee->getCurrentHourlyRateValue() ?? 0` | **CODE** `ExtraWorkEmployeeHoursController.php:171` |
| the same endpoint, bulk `records[]` | identical | **CODE** `:290` |
| `POST /admin/prj-weekly-projects/extra-works/hours` | `$employee ? ($employee->hourly_rate ?? 0) : 0` (the accessor - same resolver) | **CODE** `PrjCentralizedPlanningController.php:3294-3295` |
| nothing else | - | grep, section 2.7 |

**It is never re-snapshotted.** **CODE** `ExtraWorkEmployeeHoursController.php:425`
`$employeeHour->fill($request->only(['work_date','hours','overtime_type_id','notes']));` -
`hourly_rate` is not in that list, and the update validator does not accept it either
(`:386-391`). **CODE** `PrjCentralizedPlanningController.php:3345-3353` - the weekly
page's edit writes only `hours` and `overtime_type_id`. So editing hours **re-prices at
the original snapshot rate**, forever.

**DATA proof of the snapshot.** Extra Work 474, hour row id 707:
`employee_id 24, work_date 2026-02-10, hours "6.00", overtime_type_id 2 (x1.5),
hourly_rate "30.00", total_cost "270.00"`. Employee 24's *only* stored rate today is
**33.00**. The 30.00 came from a rate row that no longer exists (rates are hard-deleted -
`EmployeeHourlyRateController.php:149-159`), and the snapshot outlived it.
6 x 30 x 1.5 = 270 - arithmetic confirmed.

**DATA proof of the multiplier applied live at save.** Extra Work 553, employee 9, all
three rows at rate 30.00 on 2026-01-12:

| hour id | overtime type | multiplier | hours | total_cost | check |
|---|---|---|---|---|---|
| 724 | 2 Weekend uren 150% | 1.50 | 3.00 | 135.00 | 3 x 30 x 1.5 = 135 |
| 723 | 3 Nacht uren 130 | 1.30 | 1.00 | 39.00 | 1 x 30 x 1.3 = 39 |
| 722 | 10 ZU 150% | 1.50 | 1.00 | 45.00 | 1 x 30 x 1.5 = 45 |

Sum 219.00 = the record's `total_labor_cost`. Formula fully confirmed against live data.

**What happens when the rate is NULL.** `getCurrentHourlyRateValue()` returns `null`
(**CODE** `Employee.php:239-243`); every caller writes `?? 0`; the saving hook computes
`hours x 0 x multiplier` = **0.00**. **Not null. No exception. No warning. No log.**

**DATA proof.** Extra Work 474, rows 704 / 717 / 718: employee 22,
`hourly_rate "0.00"`, `total_cost "0.00"` for 1.0 + 1.5 + 1.5 = 4 hours. Plus employee 23
with 2.5 hours at 0. Of the work's 13.5 hours, **7.5 hours cost EUR 0.00**, and the
`priceBreakdown` screen prints them as `"cost": 0` beside real hours without any flag.

**DATA the same for the v2 family**, where the rate is optional at write time:
`WorkerHoursApprovalService::bulkSave` takes `hourly_rate` **from the request payload
only** (**CODE** `:589,600`), and `updateSourceHours` - the endpoint the "Medewerker Uren"
page actually calls - **never sets `hourly_rate` at all** (**CODE**
`WorkerHoursApprovalService.php:1141-1152`). Rows created there approve at
`total_cost = hours x 0 x multiplier = 0`.

Only the v2 detail path snapshots properly: **CODE** `ExtraWorksV2Controller.php:2835-2836`
`$hourlyRate = $employee?->currentHourlyRate?->hourly_rate ?? 0;` - and there it is
**re-snapshotted on every save** (`updateOrCreate` writes `hourly_rate` every time), so a
rate change *does* re-price still-draft v2 hours. **The two families behave oppositely on
rate changes.**

## 2.5 `getRemainingHours()` / `canDistributeHours()` - full grep results

**CODE** `ExtraWork.php:523-536`:
```php
public function getRemainingHours(): float
{
    $totalHours = $this->hours ?? $this->hours_worked ?? $this->total_hours ?? 0;
    $distributedHours = $this->getTotalDistributedHours();
    return max(0, $totalHours - $distributedHours);
}

public function canDistributeHours(float $hours): bool
{
    return $this->getRemainingHours() >= $hours;
}
```

`$this->hours`: there is **no `hours` column, no `getHoursAttribute`, and no `hours()`
relation** on `ExtraWork` - I read `$fillable` (`:20-80`), `$casts` (`:85-118`) and
grepped the file. Eloquent returns null.

`$this->total_hours`: **CODE** `ExtraWork.php:506-509`
`public function getTotalHoursAttribute(): float { return $this->getTotalDistributedHours(); }`
and **CODE** `:489-492` `getTotalDistributedHours()` = `$this->employeeHours()->sum('hours')`.

So with `hours_worked` null (all live records) the expression is
`max(0, distributed - distributed)` = **0**.

**`canDistributeHours` - complete grep of backend AND frontend:**
```
backend/app/Models/ExtraWork.php:533:    public function canDistributeHours(float $hours): bool
```
One line. **NEVER CALLED. CONFIRMED DEAD.** And if revived it would return false for every
positive argument.

**`getRemainingHours` - complete grep:** 9 call sites, **all of them response-payload
echoes**, none a decision:
- `ExtraWorksController.php:5670` (updateHours response)
- `ExtraWorkEmployeeHoursController.php:107, 225, 368, 441, 481, 553, 635, 675`
  (index / store / bulkStore / update / destroy / destroyByEmployee /
  destroyByEmployeeAndOvertimeType / summary responses)

**DATA** every live call returned `remaining_hours: 0`, including work 474 with 13.5
distributed hours and work 448 with 1 distributed hour. The frontend does not even
display the field - `ExtraWorkEmployeeHoursTab.jsx` computes its own
`plannedHours`/`workedHours` from `extraWork` instead, and the only consumer of
`remaining_hours` in the SPA is the dead `EmployeeHoursDistributionModal`.

## 2.6 The two worker-hours families

The brief names `/worker-hours/*` and `/weekly-worker-hours/*`. **`/weekly-worker-hours/*`
does not exist.** `grep -rn "weekly-worker-hours"` over both repos returns nothing. The
nearest real things are:

- **Family V1**: `GET /admin/employees/weekly-hours` -> `ExtraWorkEmployeeHoursController::
  weeklyHours` (routes/api.php:802), reading `extra_work_employee_hours`.
- **Family V2**: the `/admin/worker-hours/*` group (routes/api.php:2377-2417) ->
  `WorkerHoursController` -> `WorkerHoursApprovalService`, reading
  `worker_planned_hours` / `worker_approved_hours`.
- plus `GET /admin/prj-weekly-projects/hours` -> `PrjCentralizedPlanningController::
  weeklyWorkerHours` (routes/api.php:2291), a third view over Family V2 restricted to
  `source_type = 'project'`.

### Family V1 - `/admin/employees/weekly-hours`

**GOVERNS** an employee-by-week-by-overtime-type timesheet built purely from v1
extra-work hours.
**WRITES** nothing - read only.
**READS** `extra_work_employee_hours` with optional `year` / `week` / `employee_id` /
`date` filters (**CODE** `ExtraWorkEmployeeHoursController.php:789-983`). No status
filter, no soft-delete filter, no tenant scope of its own.
**Middleware** `ucb.permission:employees,view`.

**DATA** `GET /admin/employees/weekly-hours?year=2026&week=3` returns three rows for
employee 9 (1h Nacht + 3h Weekend + 1h ZU on Monday, total 5) - the hours of Extra Work
553, which is `status_id = 1` (Nieuw).

Sibling: `GET /admin/extra-works/employee-hours/by-building` (+ `/pdf`) - same source,
grouped Year -> Week/Month -> Building -> Employee -> OvertimeType
(**CODE** `:1000-1262`). **DATA** confirmed the same 5 hours land under building 3031
"B3 Amsterdam", customer 2054.

**Bug worth flagging:** the week *filter* is
**CODE** `:1046` `$q->orWhereRaw('WEEKOFYEAR(work_date) = ?', [$week]);` - MySQL's
`WEEKOFYEAR` - while the week *grouping* three dozen lines later is
**CODE** `:1104` `$recordWeek = (int) $workDate->format('W');` - PHP's ISO-8601 week.
The two disagree for dates near a year boundary, so a row can be filtered in under one
week number and displayed under another.

Sibling report: `GET /admin/reports/employee-hours-extra-works` (+ `/excel`) -
**CODE** `ReportsController.php:1997-2100`. Hours only, no money. **These report routes
carry no `ucb.permission` middleware at all** (routes/api.php:1081-1099) - only the outer
`auth:sanctum` + `user.status`. Any authenticated user can pull the whole company's
employee-hours PDF. Handing that to the RBAC agent.

Also: `WeeklyEmployeeHours.jsx:301` calls `GET /admin/employees/weekly-hours/export`,
which **is not a registered route** - so the PDF button always fails and silently falls
back to the client-side Excel export (**CODE** `:320-324`).

### Family V2 - `/admin/worker-hours/*`

**GOVERNS** planned and approved worker hours for **ExtraWorkV2, continuous work,
projects and machines** - `source_type` + `source_id`. Never v1 Extra Works: both
`extraWork()` relations resolve `ExtraWorkV2` (**CODE** `WorkerPlannedHour.php:161-164`,
`WorkerApprovedHour.php:143-146`), and `getSourceName()` looks up `ExtraWorkV2::find()`
(**CODE** `WorkerHoursApprovalService.php:944-951`).

**WRITTEN BY**
| Writer | Sets rate? | Locks respected? | Evidence |
|---|---|---|---|
| `POST /admin/worker-hours/bulk-save` | from payload only | yes (skips + reports errors) | **CODE** `WorkerHoursApprovalService.php:534-621` |
| `POST /admin/worker-hours/update-source-hours` | **no - never sets `hourly_rate`** | no - relies on the model hook, which **throws** | **CODE** `:1102-1178` |
| `PUT /admin/extra-works-v2/{id}/workers/{employeeId}/hours` | yes, re-snapshots every save | yes (`continue` on locked) | **CODE** `ExtraWorksV2Controller.php:2816-2911` |
| `WorkerPlannedHourService::saveHour` (v2 internals) | yes, payload-or-employee | yes (throws) | **CODE** `WorkerPlannedHourService.php:27-77` |
| `PUT /admin/prj-centralized-planning/worker-hours/{id}` | n/a | **NO - raw `DB::table()->update()`** | **CODE** `PrjCentralizedPlanningController.php:1299-1345` |

**Middleware:** the entire `/admin/worker-hours/*` group carries **no `ucb.permission`**
(routes/api.php:2377-2417) - only `auth:sanctum` + `user.status` from the outer group and
`auth:sanctum` again from the controller constructor. The `prj-centralized-planning`
routes carry `admin.only` (`role_id === 1`, **CODE** `app/Http/Middleware/AdminOnly.php:
33-45`).

**Which endpoints the SPA actually calls** (complete grep of `frontend/src`):
used - `form-data`, `employee-overview`, `pending-summary`, `weekly`,
`approve-employee-all-sources`, `revert-employee-all-sources`, `approve-source`,
`revert-source`, `approve-week`, `revert-week`, `submit-week`, `update-source-hours`.
**Never called from the SPA** - `bulk-save`, `submit`, `approve`, `reject`, `revert`,
`pending-approval`, `summary`, `approved-report`, `approve-employee-week`. That is 9 of
21 endpoints with no client.

**DOES A NUMBER EVER FLOW BETWEEN THE TWO FAMILIES? No.** Traced four ways:

1. **Schema.** No column in either family references the other. `worker_planned_hours`
   has `source_type`/`source_id`; `source_type='extra_work'` dereferences `ExtraWorkV2`.
2. **Code.** The complete reader/writer set of `extra_work_employee_hours` (section 2.7)
   contains no file that also touches `worker_*_hours`, except
   `PrjCentralizedPlanningController` - and there the two are queried in **separate
   methods that never combine** (`weeklyWorkerHours` reads `worker_*`;
   `weeklyExtraWorks` reads `extra_work_employee_hours`; the frontend fetches both and
   renders them as two independent lists, **CODE**
   `prj-projects/weekly-projects/index.jsx:191-213`).
3. **Migration.** `2026_02_11_130000_migrate_worker_hours_data.php:23-37` migrates
   `worker_assigned_hours`, `prj_project_assignments` and
   `extra_work_v2_assignment_hours`. `extra_work_employee_hours` is not among them.
4. **DATA.** For employee 9, week 3 of 2026:
   - `GET /admin/employees/weekly-hours?year=2026&week=3` -> **5.0 hours** (from v1 Extra
     Work 553).
   - `GET /admin/worker-hours/employee-overview?year=2026&week=3` -> **2.0 hours**
     (1.5 Mon + 0.5 Fri, source `project` 61 "Extra Diensten").

   Same person, same week, two screens, two totals, **neither includes the other**.
   That is the finding.

## 2.7 Every reader and writer of `extra_work_employee_hours` (complete)

`grep -rn "ExtraWorkEmployeeHour|extra_work_employee_hours" backend/app`:

**Writers**
- `ExtraWorkEmployeeHoursController::store` `:199` (single) and `bulkStore` `:321`
- `ExtraWorkEmployeeHoursController::update` `:425`
- `ExtraWorkEmployeeHoursController::destroy` `:468`, `destroyByEmployee` `:532`,
  `destroyByEmployeeAndOvertimeType` `:610`
- `PrjCentralizedPlanningController::storeExtraWorkHours` `:3297`,
  `updateExtraWorkHours` `:3336`, `deleteExtraWorkHours` `:3382`
- `PrjCentralizedPlanningController::approveExtraWorkHours` `:3180` /
  `rejectExtraWorkHours` `:3215` / `correctExtraWorkHours` `:3250` and the three
  `...Simple` variants `:3413/:3446/:3479` - status only
- `ExtraWorkWorkerAssignment::boot()` `deleting` cascade `:32-36`

**Readers**
- `ExtraWorkEmployeeHoursController::index` `:32` / `summary` `:664-665` /
  `weeklyHours` `:820` / `hoursByBuilding` `:1025` / `hoursByBuildingPdf` `:1280`
- `ExtraWork::getTotalDistributedHours` `:489` and `getTotalLaborCost` `:497` - which feed
  `total_hours`, `total_labor_cost`, `total_cost` on every Extra Work JSON payload
- `ExtraWorksController::priceBreakdown` `:4279-4305`, `comprehensiveReport` `:4204`,
  weekly report `:4333`, `:4739`
- `ReportsController::employeeHoursExtraWorks` `:2015` and `...Excel` `:2124`
- `PrjCentralizedPlanningController::weeklyExtraWorks` `:2935`,
  `weeklyExtraWorkWorkers` `:3123`
- `Employee::workHours()` `:207` (relation, no live caller)
- `OvertimeType::employeeHours()` `:55` (relation, no live caller)

**Not in that list, and this is the point:** no invoice file, no contract file, no
`worker_*_hours` file, no scheduler, no job, no observer.

## 2.8 The Extra Work hours screen and its blind spot

**CODE** `ExtraWorkEmployeeHoursController::index` `:21-121`. It builds the response from
`ExtraWorkWorkerAssignment::where('extra_work_id', ...)` and then attaches
`$hoursByWorker->get($assignment->employee_id, collect())`. Hour rows for an employee who
is not in `extrawork_worker_assignments` are **never emitted**, yet the same response's
`extra_work.distributed_hours` and `total_labor_cost` are computed from the raw sums.

**DATA**
```
GET /admin/extra-works/474/employee-hours
{"assigned_workers":[], "extra_work":{"distributed_hours":13.5,"total_labor_cost":270,...}}

GET /admin/extra-works/469/employee-hours
assigned_workers: emp 33 -> 0h/0, emp 34 -> 0h/0, emp 36 -> 0h/0
extra_work: distributed_hours 2.5, total_labor_cost 82.5

GET /admin/extra-works/448/employee-hours
{"assigned_workers":[], "extra_work":{"distributed_hours":1,...}}
```

Three live records where the grid shows nothing (or all zeros) while the totals show
real hours and, on 474, EUR 270 of labour.

Two more things about this endpoint:
- **CODE** `:86-92` dereferences `$employee->id` / `->name` after `$employee =
  $assignment->employee` **without a null check** (unlike `:47` two lines earlier, which
  does check). A soft-deleted employee turns the whole screen into a 500.
- The SPA sends `start_date` / `end_date` params (**CODE**
  `ExtraWorkEmployeeHoursTab.jsx:234-237`) which the controller **completely ignores** -
  it always returns every hour of the work, and the week filtering happens client-side.

**The store guard that the other path skips.** `POST /admin/extra-works/{id}/
employee-hours` refuses an employee with no worker assignment
(**CODE** `:159-168` `NOT_ASSIGNED_WORKER`) and refuses a duplicate
`(extra_work, employee, work_date, overtime_type)` (**CODE** `:174-190` `DUPLICATE_ENTRY`).
`POST /admin/prj-weekly-projects/extra-works/hours` does **neither** (**CODE**
`PrjCentralizedPlanningController.php:3282-3325`) - no assignment check, no duplicate
check. **Every hour row created from the weekly page starts life as an orphan unless a
worker assignment happens to exist.**

**Also:** `GET /admin/employees/workers`, the picker that populates the assignment list,
is `Employee::workers()->active()` = **CODE** `Employee.php:178-182`
`where('position', 'LIKE', 'worker%')`. **DATA** it returns **3 employees** out of 40.
The live hour rows belong to employees whose positions are "Manager",
"Lokasyon Manager", "Locasyon manager", "Isci" - **none of whom the picker can offer.**

## 2.9 The v1 draft / saved / approved flow - who does what, what locks

| Step | Who | Endpoint | Writes | Locks |
|---|---|---|---|---|
| create | admin, weekly planning page or Extra Work hours tab | `POST .../employee-hours` or `POST /prj-weekly-projects/extra-works/hours` | row + `total_cost`, `status` defaults to `draft` | none |
| Goedkeuren | admin (`admin.only`, role_id 1) on the weekly page | `POST /prj-weekly-projects/extra-works/hours/{id}/approve` | `status = 'pre-approved'`, `updated_by` | **none** |
| Intrekken | same | `.../reject` | `status = 'draft'` | **none** |
| Corrigeren | same | `.../correct` | `status = 'approved'` (= Gecorrigeerd) | **none** |
| edit | anyone with `extra_works,update`, or any admin | `PUT .../employee-hours/{id}` or `PUT /prj-weekly-projects/extra-works/hours/{id}` | `hours`, `overtime_type_id`, re-prices at the old snapshot rate | **none - status is not checked** |
| delete | `extra_works,delete`, or any admin | 3 delete endpoints | hard delete | **none** |

**CODE** `PrjCentralizedPlanningController.php:3192-3194`:
```php
$hour->status = 'pre-approved';
$hour->updated_by = auth()->id();
$hour->save();
```
That is the entire approval. No transaction, no history row, no reason, no guard on the
current status, no check on the parent Extra Work's status.

**DATA** across every week of 2025 and 2026 (`GET /admin/prj-weekly-projects/extra-works`
for 106 year/week combinations, 48 extra-work/week cells, 70 hour rows):
**53 `draft`, 0 `pre-approved`, 17 `approved`.** The middle state is unused in production.

Note also: the same Extra Work appears in **three different weeks** (474 in 2025-W44,
2025-W48 and 2026-W07) because the sheet buckets by `work_date` on the hour row, which
nothing constrains to the work's own planning window.

## 2.10 The v2 draft / submitted / approved / rejected flow

| Step | Who | Endpoint | Writes | Locks |
|---|---|---|---|---|
| save draft | any authenticated user (no ucb gate) | `POST /admin/worker-hours/update-source-hours`, or `PUT /admin/extra-works-v2/{id}/workers/{emp}/hours` | `planned_hours`, `status = draft`; the v2 path also re-snapshots `hourly_rate` | locked rows are skipped (v2) or **throw** (update-source-hours) |
| submit | approval page | `POST /admin/worker-hours/submit-week` | `status = submitted`, `submitted_at`, `submitted_by` | **row becomes locked** - hours/employee/date/overtime edits now throw |
| approve | approval page / Medewerker page | `approve-week`, `approve-source`, `approve-employee-all-sources` | creates `WorkerApprovedHour` (immutable), `total_cost`, sets `approved_hour_id` | approved row immutable except correction fields; planned row cannot be deleted |
| reject | service only, **no SPA caller** | `POST /admin/worker-hours/reject` | `status = rejected`, appends "Rejected: {reason}" to `notes` | unlocks (rejected is editable) |
| revert / correct | approval page / Medewerker page | `revert-week`, `revert-source`, `revert-employee-all-sources` | approved row -> `is_corrected = true`, `corrected_at/by`, `correction_reason`, `original_hours`; planned row -> draft, `approved_hour_id = null`, `submitted_* = null` | reason is **required**, min 5 chars |

**The submit step is optional in practice.** `approveSource` accepts DRAFT rows directly:
**CODE** `WorkerHoursApprovalService.php:1197-1199`
```php
->whereIn('status', [WorkerPlannedHour::STATUS_DRAFT, WorkerPlannedHour::STATUS_SUBMITTED])
->where('planned_hours', '>', 0);
```
and the "Medewerker Uren" page never calls submit at all (its only calls are
`update-source-hours` then `approve-source`, **CODE**
`worker-hours/index.jsx:669, 752-763`). `ExtraWorksV2Controller::approveWorkerHours`
documents the same shortcut in its own header comment: *"users can approve directly
without a separate submit step."*

**Drift is created here.** **CODE** `ExtraWorksV2Controller.php:2986-2992, 3020`:
```php
$hoursToApprove = $planned->planned_hours;
if ($approvedHoursOverride && isset($approvedHoursOverride[$planned->day_of_week])) {
    $hoursToApprove = (float) $approvedHoursOverride[$planned->day_of_week];
}
...
'approved_hours' => $hoursToApprove, // Use override, not planned
...
// Update planned record status (but NOT the hours!)
```
and the revert doc comment states the intent: *"This preserves the original planned values -
when approved had 5 hours and planned had 3 hours, reverting will show 3 hours again."*

**Where drift is visible:** `WorkerHoursApprovalService::getWeeklyData` returns
`total_planned_hours` and `total_approved_hours` in the same summary
(**CODE** `:167-169`); `weeklyWorkerHours` returns three parallel buckets
`planned_workers` / `approved_workers` / `corrected_workers` with three totals
(**CODE** `PrjCentralizedPlanningController.php:2045-2107`).

**`actual_hours` is the one number in this family with nowhere to go.** It is written by
`PrjCentralizedPlanningController::updateWorkerHours` `:1319-1321` and
`approveWorkerHours` `:1372-1374`, and read only for display by `centralizedTasksWeekly`
(`:852, :906, :926`). `WorkerApprovedHour::createFromPlanned` copies **`planned_hours`**,
not `actual_hours`. **So a corrected actual figure never reaches the cost.**

## 2.11 The second, incompatible approval path (detail)

**CODE** `PrjCentralizedPlanningController.php:1338` and `:1398-1420`:
```php
DB::table('worker_planned_hours')->where('id', $id)->update($updateData);
...
$updated = DB::table('worker_planned_hours')
    ->whereIn('id', $ids)
    ->where('status', '!=', 'approved')
    ->update([
        'status' => 'approved',
        'approved_by' => auth()->id(),
        'approved_at' => now(),
        'updated_at' => now(),
    ]);
```

No `WorkerApprovedHour` is created. No `approved_hour_id` is set. No model event fires,
so `WorkerPlannedHour::updating`'s lock guard never runs.

**CODE** `:1315` the accepted status set is `'nullable|string|in:draft,planned,approved'` -
`planned` is not in `WorkerPlannedHour::STATUSES` and not in the column enum
(`draft, submitted, approved, rejected`). Writing it through the query builder bypasses
Eloquent; MySQL in non-strict mode would coerce it to `''`.

**Consequence chain** (INFERRED from the code; would be confirmed by a SQL query for
`worker_planned_hours WHERE status='approved' AND approved_hour_id IS NULL`, which I
cannot run):
`weeklyWorkerHours` lists planned rows `WHERE wph.status != 'approved'` (**CODE** `:2050`)
and approved rows from `worker_approved_hours` (**CODE** `:2068-2074`). A Path-B row is in
neither -> **the hours vanish from the screen**, permanently locked and unrevertable,
with no cost row.

The SPA does call this path: **CODE** `PrjWeekPlanPage.jsx:1721, 1766, 1796` hit
`/admin/prj-centralized-planning/worker-hours/{id}` and `.../approve`.

---

# 3. This area's connection map

## 3.1 The four hour worlds

```
WORLD 1 - v1 Extra Work loose columns
   extra_works.hours_planed  --(display only)--> 6 SPA screens
   extra_works.hours_worked  --(kanban 2->3 gate, client-side only)--> drag blocked
                             --(getRemainingHours)--> always 0
                             --(dead modal cap)--> nothing

WORLD 2 - v1 labour ledger                     [the only v1 money]
   employees.position LIKE 'worker%'
        v
   extrawork_worker_assignments  --(model delete only)--> cascades hour deletion
        v (employee_id match, display join)
   extra_work_employee_hours
        ^ hourly_rate  <-- SNAPSHOT at create from employee_hourly_rates
        ^ multiplier   <-- read LIVE from overtime_types at save, then discarded
        |
        +--> total_cost --> ExtraWork::getTotalLaborCost()
        |                     +--> total_labor_cost   (list + detail JSON)
        |                     +--> total_cost         (= labour + products)
        |                     +--> priceBreakdown.labor.total_cost --> grand_total @ 21%
        |                     +--X-- NEVER REACHES AN INVOICE  (confirms A2/A3)
        +--> hours --> total_hours / distributed_hours
        |          --> GET /admin/employees/weekly-hours          (HR timesheet)
        |          --> GET /admin/extra-works/employee-hours/by-building (+pdf)
        |          --> GET /admin/reports/employee-hours-extra-works (+excel)
        |          --> GET /admin/prj-weekly-projects/extra-works  (weekly sheet)
        +--> status (draft | pre-approved | approved==CORRECTED)
                   --> bucketing on the weekly sheet ONLY. Gates nothing.

WORLD 3 - unified planned/approved hours       [v2 / project / continuous / machine]
   worker_planned_hours (draft->submitted->approved/rejected)
        | hourly_rate: re-snapshotted every save on the v2 path,
        |              NEVER set by update-source-hours
        +--(approve, path A)--> worker_approved_hours.total_cost   -> read by nothing
        +--(approve, path B: DB::table)--> status='approved', NO snapshot row
                                          -> invisible + unrevertable + costless
        +-- actual_hours --> display only, never costed

WORLD 4 - contracted hours
   contract_lines.hours_year --> contracts.total_hours_year --> pricing, dashboards
   contract_line_planning.actual_hours --> execution tracking
   (no link to any worked hour anywhere)
```

## 3.2 What action changes what

| Action | Immediate write | Knock-on |
|---|---|---|
| `POST .../employee-hours` | new hour row; `total_cost` computed by the saving hook | every Extra Work payload's `total_hours`, `total_labor_cost`, `total_cost`; the weekly sheet; three HR reports; `priceBreakdown` |
| `PUT .../employee-hours/{id}` (hours or overtime type) | `hours` / `overtime_type_id`; `total_cost` recomputed **at the old rate**, **with the current multiplier** | all of the above |
| `PATCH /admin/extra-works/{id}/hours` | `hours_planed` and/or `hours_worked` | **nothing computes differently.** `remaining_hours` in the response is still 0 |
| `POST /admin/employees/{id}/hourly-rates` | new `employee_hourly_rates` row, old overlapping rates deactivated | **existing hour rows are NOT re-priced.** New rows use the new value - even if it is future-dated or already expired |
| `DELETE /admin/employees/{id}/hourly-rates/{id}` | hard delete | snapshots survive, their source is gone |
| `PUT /admin/overtime-types/{id}` (multiplier) | `overtime_types.multiplier` | **existing `total_cost` unchanged**; every screen shows the new multiplier beside the old cost |
| `DELETE /admin/overtime-types/{id}` | hard delete, guard commented out | `worker_*_hours.overtime_type_id` -> null; `extra_work_employee_hours` behaviour unknown (no migration) |
| `DELETE /admin/extra-works/{id}/workers/{assignmentId}` | assignment row, **model** delete | **cascades: all that employee's hour rows and their money are destroyed** |
| `POST /admin/extra-works/{id}/workers/bulk-delete` | `ExtraWorkWorkerAssignment::where(...)->delete()` (query-builder mass delete) | **no cascade** -> hours orphaned |
| `PUT /admin/extra-works/{id}` with `workers[]` | `\DB::table('extrawork_worker_assignments')->...->delete()` | **no cascade** -> hours orphaned |
| weekly-sheet approve / reject / correct | `extra_work_employee_hours.status` | only which of three buckets the row appears in |
| `POST /admin/worker-hours/approve-source` | `WorkerApprovedHour` + `total_cost`, planned -> approved | planned row locked; weekly totals move from planned to approved |
| `POST /admin/prj-centralized-planning/worker-hours/{id}/approve` | raw status/approved_by/approved_at | row locked, **no cost, no snapshot, disappears from the weekly view, cannot be reverted** |
| `POST .../worker-hours/revert-*` | approved -> `is_corrected`, planned -> draft | `original_hours` preserved; the planned number is the ORIGINAL plan, not the approved figure - this is the drift |

## 3.3 Gates that actually exist in the hours chain

| Gate | Where | Real? |
|---|---|---|
| employee must be an assigned worker | `ExtraWorkEmployeeHoursController::store` `:159-168` | **yes**, but only on that one endpoint |
| no duplicate (work, employee, date, overtime type) | same controller `:174-190`, `:302-317`, `:400-423` | **yes**, same caveat |
| `hours` between 0.01 and 999999 | `:141`, `:250` | yes |
| max 50 records per bulk call | `:240` | yes |
| kanban 2 -> 3 requires `hours_worked > 0` | `ExtraWorkKanbanView.jsx:499-501` | **client only** |
| distributed <= `hours_worked` | `EmployeeHoursDistributionModal.jsx:334, 383` | **dead component** |
| distributed <= work total | `ExtraWorkEmployeeHour::validateTotalHours()` | **never called** |
| `canDistributeHours()` | `ExtraWork.php:533` | **never called**, and would return false always |
| planned-hour lock on submitted/approved | `WorkerPlannedHour::updating/deleting` | **yes**, and bypassed by `DB::table()` |
| approved-hour immutability | `WorkerApprovedHour::updating` | **yes**, but hard delete is allowed |
| correction reason required | `WorkerHoursApprovalService::revert` `:445-447`; controller `min:5` | yes |
| `extra_work_employee_hours.status` | - | **gates nothing at all** |
| Extra Work `status_id` on hour visibility | - | **no gate anywhere** |

## 3.4 The orphan mechanism, precisely

```
ExtraWorkWorkerAssignment::boot() { static::deleting(fn => delete matching hour rows) }
        ^ fires only for  $model->delete()
        |
   [A] DELETE /admin/extra-works/{id}/workers/{assignmentId}
       ExtraWorksController.php:2599  $assignment->delete()      --> CASCADE FIRES
                                                                     hours + money destroyed
   [B] POST /admin/extra-works/{id}/workers/bulk-delete
       ExtraWorksController.php:2558  ...::where(...)->delete()  --> NO EVENT, orphan
   [C] PUT /admin/extra-works/{id} with workers[]
       ExtraWorksController.php:1028  \DB::table(...)->delete()  --> NO EVENT, orphan
```

Path A silently destroys labour money that is already on a screen. Paths B and C silently
hide labour money that is still in the totals. **DATA** confirms B/C happened: works 448,
469 and 474 all carry hours with no matching assignment.

---

# 4. Corrections to the brief and to tier-1 reports

**No contradiction with any tier-1 report.** Everything I found is consistent with
01-extra-work.md, 02-invoicing.md and 03-ew-invoice-seam.md. Three places where I can now
*extend* them:

1. **A1 §"Hours and money" said `hours_planed` is read by "`updateHours` response only".**
   That is true of the backend, but the SPA reads it in **eight** places. Still display
   only, so A1's conclusion stands; the surface is wider than stated.
2. **A1 noted `getRemainingHours()`'s `$this->hours` is "harmless but misleading".** It is
   not harmless: combined with `hours_worked` being null on 100% of live records, it makes
   the function return 0 unconditionally, which is why `canDistributeHours()` cannot be
   revived without breaking the feature.
3. **A3's "labour never reaches an invoice" is confirmed** from the hours side: the
   complete reader list of `extra_work_employee_hours` contains no invoicing file.

**Corrections to my own brief:**

- **"`/weekly-worker-hours/*`"** - no such route family exists anywhere in either repo.
  The two real families are `/admin/employees/weekly-hours` (v1) and
  `/admin/worker-hours/*` (v2).
- **"contract-hours models"** - `EmployeeContract` has **no hours column** and **zero live
  rows**; it is an HR document record. The real contract-hours concept is
  `contract_lines.hours_year` -> `contracts.total_hours_year`, which is a sold budget with
  no link to worked hours.
- **"drift"** - the word appears nowhere in the codebase. The concept exists only in the
  v2 family, as planned vs approved divergence.

---

# 5. Schema anomalies for the DBA / migration owner

Adding to the three anomalies A2 already raised:

4. **Four live tables have no `Schema::create` migration anywhere in
   `database/migrations/` (289 files):** `extra_work_employee_hours`,
   `employee_hourly_rates`, `overtime_types`, `employee_contracts`.
   `grep -rn "extra_work_employee_hours|employee_hourly_rates|employee_contracts"
   database/` returns **nothing**; `overtime_types` appears only as the *target* of eleven
   foreign keys in other migrations. **A clean `php artisan migrate` on an empty database
   cannot reproduce this schema** - it would fail on the first FK to `overtime_types`
   (`2026_01_27_000001_create_extra_work_v2_assignment_hours_table.php:33`). Column types,
   defaults, nullability and FK on-delete behaviour for all four tables are therefore
   **unverifiable from the repository**.
5. **`overtime_types.code`** ("GU", "GU 150", "GU 130", "GU 250", "ZU", "SU", "ZU 150",
   "SU 150") is live, populated data that is in neither `OvertimeType::$fillable` nor
   `OvertimeTypeController`'s validation rules. **No API path can write it.**
6. **`worker_planned_hours.actual_hours`, `.approved_by`, `.approved_at`** exist as
   columns (`2026_02_24_141000`) but are absent from `WorkerPlannedHour::$fillable`. They
   are writable only through raw `DB::table()` calls, and `actual_hours` is never costed.
7. **`worker_planned_hours`'s unique index** includes two nullable columns
   (`task_id`, `overtime_type_id`); MySQL treats NULLs as distinct, so the constraint does
   not prevent duplicates in the common case.
8. **`WorkerHoursApprovalService::updateSourceHours` `:1149`** passes `'week' => $week` to
   `WorkerPlannedHour::create()`. There is no `week` column (it is `week_number`) and
   `week` is not fillable, so the value is silently discarded; the model's `creating` hook
   happens to derive `week_number` from `work_date`, which masks the mistake.

---

# 6. COULD NOT DETERMINE

Each item below names the gap and exactly what would close it.

1. **The true column definitions of `extra_work_employee_hours`, `employee_hourly_rates`,
   `overtime_types` and `employee_contracts`** - defaults, nullability, string lengths and
   FK `ON DELETE` behaviour. No migration creates them. **To close:** `SHOW CREATE TABLE`
   on the four tables, or a `mysqldump --no-data`.

2. **The default value of `extra_work_employee_hours.status`.** Neither
   `ExtraWorkEmployeeHoursController::store` nor `bulkStore` sets it, yet every live row
   I saw had a non-null value, and `weeklyExtraWorks` defensively wraps it in
   `COALESCE(eweh.status, 'draft')` - implying NULLs were once possible. **To close:**
   `SHOW CREATE TABLE extra_work_employee_hours`, plus
   `SELECT COUNT(*) ... WHERE status IS NULL`.

3. **Whether any `worker_planned_hours` row is currently stranded by the raw-SQL approval
   path.** The mechanism is proven from code; the live count is not. **To close:**
   `SELECT id, source_type, source_id, employee_id, work_date, status FROM
   worker_planned_hours WHERE status = 'approved' AND approved_hour_id IS NULL;`
   and `... WHERE status NOT IN ('draft','submitted','approved','rejected');`

4. **Where hour row 707's `hourly_rate = 30.00` came from.** Employee 24's only surviving
   rate row is 33.00 (2025-11-02 to 2025-12-11). The most likely explanation is that a
   30.00 rate row existed and was hard-deleted (`EmployeeHourlyRateController::destroy`
   has no soft delete), but I cannot prove it. **To close:** an audit-log or binlog query,
   or `SELECT * FROM employee_hourly_rates WHERE employee_id = 24` including any
   soft-delete column if one exists.

5. **The full live contents of `worker_approved_hours`** - how many rows, how much
   `total_cost`, how many `is_corrected`. `GET /admin/worker-hours/approved-report` is
   blocked by the read-only wrapper (its path contains "approve"). **To close:** either a
   wrapper allow-list entry for that one GET, or
   `SELECT source_type, COUNT(*), SUM(total_cost), SUM(is_corrected) FROM
   worker_approved_hours GROUP BY source_type;`

6. **Whether `employee_contracts.is_active` exists.** `EmployeeContract::scopeActive()`
   filters on it, `$casts` declares it, `$fillable` omits it, and there is no migration.
   The table has zero rows so the scope has never been exercised against data. **To
   close:** `SHOW CREATE TABLE employee_contracts`.

7. **Whether `EmployeeContract`'s delete hook ever fires correctly.** It checks
   `$contract->file_path`; the model's file column is `file_guid`. **To close:** confirm
   the column list, then delete a test contract in a non-production copy and check
   storage.

8. **Who or what created the live `extra_work_employee_hours` rows.** `created_by` is
   populated but I did not correlate it against users, and both creation endpoints are
   plausible. **To close:**
   `SELECT created_by, COUNT(*) FROM extra_work_employee_hours GROUP BY created_by;`
   plus a look at whether any row lacks a matching `extrawork_worker_assignments` row -
   `SELECT h.id FROM extra_work_employee_hours h LEFT JOIN extrawork_worker_assignments a
   ON a.extra_work_id = h.extra_work_id AND a.employee_id = h.employee_id
   WHERE a.id IS NULL;` - which would size the orphan problem exactly.

9. **Whether any mobile client or external portal writes these tables.** The
   `portal_extra_works` SQL view selects both `hours_planed` and `hours_worked` and no PHP
   reads it (A1 raised this). I did not investigate the mobile app. **To close:** the
   MOBILE/EXTERNAL agent's pass, or DB grants/connection-log inspection.

10. **Whether `ucb.permission` narrows the hour queries or only allows/denies.** Every
    `/admin/extra-works/{id}/employee-hours` route carries `ucb.permission:extra_works,*`,
    but the controller calls `ExtraWork::findOrFail($extraWorkId)` directly with no scope
    filter of its own; the weekly-sheet hour endpoints carry only `admin.only`; the
    `/admin/worker-hours/*` group and the `/admin/reports/*` group carry **no permission
    middleware at all**. **To close:** the RBAC agent's read of
    `app/Http/Middleware/UcbPermissionMiddleware.php` and
    `app/Services/PermissionService.php`.

11. **Whether anything outside PHP re-prices hours.** The application declares no
    scheduler (A2's finding, which I did not re-test), so nothing periodic re-computes
    `total_cost` after a rate or multiplier change. **To close:** the infrastructure
    agent's read of the host crontab and systemd units.
