# Osius reference system — Agent A1: Extra Work v1, the record and its lifecycle

Scope: `extra_works` (v1). ExtraWorkV2 appears only in section 8, clearly labelled.
Nothing in this document was modified in the reference system. All API calls were GET.

Evidence labels used throughout:

- **CODE** — a path + line I read, with the line quoted.
- **DATA** — an endpoint I called through the read-only wrapper, and the values that came back.
- **INFERRED** — a conclusion I drew, stated as such, with what would confirm it.

---

# 1. Plain-English logic first

## 1.1 What an Extra Work actually is

`extra_works` is one flat MySQL table that holds **two different business objects at once**.
A `type` column decides which one you are looking at: `type = 1` is an **Extra Work**
(a billable extra job), `type = 2` is a **Melding** (a report/notification from a customer).
There is no second table, no subclass, no separate model. The URL prefix
(`/admin/extra-works` vs `/admin/meldings`) and the permission module name are the only
things that differ at the API boundary — both prefixes are served by the same controller
method bodies.

Every record carries, in the same row:

- its own text (title/description) in four languages (nl/en/tr/bg) plus the "original" one,
- a status number,
- three parallel time-stamp families — planning, execution, approval,
- a fourth family for the archive workflow,
- an unused "draft message" family,
- two invoice columns that are almost always empty,
- two "completion requirement" booleans that nothing enforces,
- optional grouping columns that tie a batch of works created for one week together.

Money does **not** live on this record. Money lives in `extra_work_products` (materials/
services, their price and tax rate) and in `extra_work_employee_hours` (labour hours and
their cost). The record only exposes computed totals.

## 1.2 The status ladder — and the surprise

There is **no state machine**. Nowhere in the backend is there a transition table, an enum,
a guard, or a "you cannot go from X to Y" check. `status_id` is a plain foreign key into
`t_ticket_status`, and the only validation that ever runs on it is
`exists:t_ticket_status,id`. Any status can be set from any other status, forwards or
backwards, by any user who holds `extra_works,update`.

The authoritative status list, read live from the reference database, is:

| id | slug | Dutch label | live v1 rows |
|----|------|-------------|--------------|
| 1 | `new` | Nieuw | 19 |
| 2 | `in_progress` | In behandeling | 6 |
| 3 | `resolved` | Interne goedkeuring | 1 |
| 4 | `closed` | Goedkeuring door de klant | 6 |
| 5 | `internal_approval` | Interne goedkeuring | **0** |
| 6 | `customer_approval` | Klant goedkeuring | **0** |
| 7 | `invoiced_v2` | Gefactureerd | **0** |
| 8 | `archived` | **Voltooid** | 9 |
| 9 | `invoiced` | invoiced | 37 |

**The brief was wrong in three places, and this matters:**

1. **Status 5 is NOT "archive-rejected".** Its slug is `internal_approval` and its Dutch
   label is "Interne goedkeuring" — the same label as status 3. It belongs to the
   **ExtraWorkV2** schedule workflow, not to v1. No v1 code path ever writes it.
2. **Status 7, not 9, is the one labelled "Gefactureerd"** — but its slug is `invoiced_v2`
   and it is also a V2 status. The status that v1 actually means by "invoiced" is **9**,
   whose label is the untranslated lowercase string `invoiced`.
3. **Statuses 5, 6 and 7 are all V2 statuses and all have zero v1 rows.** They are not
   "unused leftovers of v1"; they are the newer system's vocabulary sharing v1's lookup table.

The v1 frontend nevertheless contains a full `case 5:` branch that renders
"Archive Rejected" with a "retry archive" button. That branch is **unreachable** — no
backend code sets status 5 — and if it were ever reached the status chip would read
"Interne goedkeuring", not "Archief afgewezen".

## 1.3 The real v1 ladder, as the code and the UI actually drive it

```
1 Nieuw
  │ (Plan button; Melding: Start button)
  ▼
2 In behandeling                     ← server stamps planed_by, planed_at
  │ (Complete button — Extra Work)
  ▼
3 Interne goedkeuring                ← server stamps completed_by, completed_at
  │ (Approve button)
  ▼
4 Goedkeuring door de klant          ← server stamps approved_by, approved_at,
  │                                     AND publishes every draft attachment
  │ (Archive/approve — a POST, not a PUT)
  ▼
8 Voltooid                           ← server stamps archive_approved_*, back-fills
  │                                     archive_requested_*, clears archive_rejected_*
  │ (invoice created elsewhere)
  ▼
9 invoiced
```

Two things about this picture are counter-intuitive and are the source of most of the
confusion in the reference system:

- **"Voltooid" (Completed) is status 8, at the END, after the archive step** — not
  status 3 or 4. The invoicing subsystem treats 8 as "ready to invoice"
  (`ExtraWork::where('status_id', 8)`), and un-invoicing puts a record **back to 8**.
- **The code comments inside the controller disagree with the labels.** The controller
  calls status 3 "completed" and status 4 "approved"; the labels call 3 "Interne
  goedkeuring" and 4 "Goedkeuring door de klant". The *stamps* follow the code comments:
  status 3 sets `completed_at`, status 4 sets `approved_at`.

A **Melding** (`type = 2`) skips the middle: the UI drives it `1 → 2 → 4` directly
(one "approve" button at status 2 that jumps to 4). Because it lands on status 4, the
server stamps `approved_at`/`approved_by` — but `completed_at` is never set for a Melding
that went through the short path.

## 1.4 What the server stamps that the client never sent

This is the single most important behaviour in the area. Almost all stamping happens in
**`PUT /admin/extra-works/{id}` (the generic update)**, driven by *what status number the
client happens to include in the body*. The dedicated `PUT /{id}/status` endpoint stamps
**nothing at all** — it only writes `status_id`.

| Client sends in the PUT body | Server additionally writes, unasked |
|---|---|
| `status_id: 2` (or any `planed_start_at`/`planed_end_at`) | `planed_by = "Name (Role)"`, and `planed_at = now()` if `planed_at` was not in the body |
| `status_id: 3` (or a truthy `completed_at`) | `completed_by = "Name (Role)"`, and `completed_at = now()` if `completed_at` was not in the body |
| `status_id: 4` (or a truthy `approved_at`) | `approved_by = "Name (Role)"`, `approved_at = now()` if absent, **and every draft attachment on the record is flipped to published** |
| a truthy `started_at` | `started_by = "Name (Role)"` |
| a truthy `archive_requested_at` / `archive_approved_at` / `archive_rejected_at` | the matching `*_by` string |

The "Name (Role)" format is `"{$user->name} ({$roleName})"` — a **free-text string**, not a
user id. That is a schema decision, not an accident: `created_by`, `requested_by`,
`approved_by`, `planed_by`, `started_by`, `completed_by`, `archive_*_by` and `drafted_by`
are all `VARCHAR(100)` columns holding a display name. See §5 for the two places where the
codebase forgets this and compares one of them to an integer user id.

## 1.5 Revert: a client-side illusion

There is **no revert endpoint**. "Revert" is a button in the SPA that issues an ordinary
`PUT /admin/extra-works/{id}` containing the previous status number plus a handful of
explicit `null`s. The backend has no idea a revert happened: no audit distinction, no
guard, no restriction on who may do it or from which status.

Worse, revert collides with the auto-stamping table above. Reverting **4 → 3** sends
`status_id: 3` with the approval fields nulled; the server sees `status_id == 3`, does not
see `completed_at` in the body, and therefore **re-stamps `completed_at = now()` and
`completed_by = current user`**. The original completion timestamp is destroyed by the act
of undoing the *approval*. The same shape applies to the archive-rejected revert path
(status 5 → 4), which is dead anyway.

## 1.6 Completion requirements: the named open question, answered

**`upload_is_required` and `notes_is_required` are enforced ONLY in the frontend, and in
practice they cannot even be turned on.** Three independent facts:

1. **No backend validation mentions them.** The completion action is
   `PUT /admin/extra-works/{id}` with `{completed_at, status_id: 3, completion_notes}`.
   That endpoint's validation rule set is built from the entity config, and the
   extra-works config contains **zero `validation` keys** — so the rule array is empty and
   `Validator::make($request->all(), [])` always passes. A request containing only
   `{"status_id": 3}` is accepted.
2. **No backend code reads them for a decision.** Across the whole PHP tree the two names
   appear in exactly four places: the model `$fillable`, the model `$casts`, one report
   payload that echoes them back, and two SQL view definitions. Never in an `if`.
3. **They cannot be written by any live endpoint.** The planning modal *sends* them, but
   the config-driven update only persists fields listed in the entity config's `fields`
   block, and neither name is in that list. So the values are silently discarded.
   Confirmed by data: **0 of 78 live records has either flag set to true.**

The only enforcement is two `if` statements in the SPA's completion modal and one in the
kanban drag handler. A direct API call, a mobile client, or a kanban drag that misses the
check completes the work with no notes and no photo.

## 1.7 Melding vs Extra Work, and conversion

Same table, same model, same controller, same status ladder. The `type` flag changes:

- which route prefix and which UCB permission module apply (`melding,*` vs `extra_works,*`),
- the push-notification type string, related-type label and deep link (`/meldings/{id}`
  vs `/extra-works/{id}`),
- which dashboard date the record is bucketed by (Melding uses `deadline_at`; Extra Work
  uses `planed_at`, falling back to `deadline_at`),
- which secondary buttons the SPA renders and whether the middle "complete" step is shown,
- the availability of the Melding-only report endpoint.

**Conversion writes exactly one column.** `POST /{id}/convert-to-extra-work` and
`POST /{id}/convert-to-melding` set `type` and nothing else, then add a system comment and
one `extra_work_activities` row. Status, planning stamps, products, hours, attachments,
buildings and group membership are all left exactly as they were. **It is fully reversible**
— both directions exist, each refuses if the record is already the target type, and
reversing simply writes the opposite activity row. There is also a bulk
`POST /bulk/convert-to-melding`, but that one uses a mass `update()` and therefore skips
the comment, the activity row and every model event.

## 1.8 Does anything compare a date on this record to `now()`?

**Yes — but never inside the Extra Work area itself.** `ExtraWorksController`,
`ExtraWorkService` and the `ExtraWork` model contain **zero** occurrences of `isPast()`,
`diffInDays`, `whereDate`, `Carbon::now` or `today()` used against a record date. Every
"is this late / is this today" judgement lives in the dashboards and the weekly work plan,
and every one of them uses **`deadline_at`** (with `planed_at` as the Extra Work
preference). `customer_start_date`, `planed_start_at`, `planed_end_at`, `requested_at`,
`completed_at`, `approved_at` and the whole archive family are **never** compared to the
clock anywhere. Details in §6.

## 1.9 The shortest list of things that are broken or dead

- `GET /admin/extra-works` **without** `?type` returns Extra Works *and* Meldings mixed
  (39 rows = 32 + 7). Only `/admin/meldings` self-scopes.
- `?customer_building_id=` on the list is a **500** — the column was dropped in Oct 2025 but
  is still declared as a filter.
- `GET /admin/invoices/pending-extra-works` — the "what can I invoice" endpoint — is
  **500 / DB error**, for the same reason plus two relations that do not exist on the model.
- `extra_works.invoice_id` / `invoice_date` are written by only one of the two invoicing
  paths; on the live data every status-9 record has both `NULL`.
- `file_1..file_4` columns: nothing reads or writes them. Dead.
- `upload_is_required` / `notes_is_required`: see §1.6. Dead in practice.
- The `portal_extra_works` SQL view is created and twice re-created by migrations and read
  by nothing in the PHP tree.
- `GET /{id}` (show) does **not** apply the UCB scope filter that the list applies.

---

# 2. Evidence — read/write maps

## 2.0 The table itself

There is **no `CREATE TABLE extra_works` migration in this repository.** 289 migrations
exist; the earliest that touches `extra_works` is `2025_10_14_000001_...` and it already
assumes the table, its `customer_id`/`building_id` columns and the FK names
`extra_works_ibfk_1`..`_8`. The table predates the migration set.
*CODE — `database/migrations/2025_10_14_000001_refactor_extra_works_to_customer_building_id.php:56`:*
`DB::statement('ALTER TABLE extra_works DROP FOREIGN KEY extra_works_ibfk_1'); // customer_id`

Consequence: **for the base columns the migrations are not the truth either.** Where I
could not find a migration I say so explicitly below.

### Columns with a real migration (nullability/defaults are authoritative)

| column | definition | migration |
|---|---|---|
| `customer_building_id` | `unsignedBigInteger` nullable — **added then DROPPED again** | added `2025_10_14_000001:24`, dropped `2025_10_18_040912:35` |
| `file_1..file_4` | `string(255)` nullable | `2025_10_14_000001:31-34` |
| `planed_start_at`, `planed_end_at` | `timestamp` nullable | `2025_10_18_000000:15-16` |
| `category_id` | `unsignedBigInteger` nullable, FK `t_ticket_category` ON DELETE SET NULL | `2025_10_18_040912:16` |
| `user_department_id` | `unsignedBigInteger` nullable, FK `t_user_department` SET NULL | `2025_10_18_040912:17` |
| `type` | `tinyInteger` **default 1**, indexed, comment `1=extrawork, 2=melding` | `2025_10_18_040912:18` |
| `planed_by`,`started_by`,`completed_by`,`created_by` | `string(100)` nullable, "Name of person who…" | `2025_10_18_072000:19-22` |
| `approved_by` | changed **from FK integer to `string(100)` nullable** | `2025_10_18_085500:22` |
| `requested_by` | changed **from FK integer to `string(100)` nullable** | `2025_10_18_103100:18` |
| `hours_worked` | `decimal(8,2)` nullable | `2025_10_18_103000:13` |
| `completion_notes` | renamed from `completion_note` | `2025_10_18_103000:16` |
| `customer_start_date` | `date` nullable | `2025_10_26_215815:16` |
| `hours_planed` | `decimal(10,2)` nullable | `2025_10_27_020441:16` |
| `draft_message` / `drafted_at` / `drafted_by` | `text` nullable / `timestamp` nullable / `string` nullable | `2025_11_04_211044:31-33` |
| `created_user_id` | `unsignedBigInteger` nullable, FK `users` SET NULL, indexed | `2025_11_05_054155:15-21` |
| translation columns (`*_nl/_en/_tr/_bg`, `original_language`, `translate_meta`) | added | `2025_11_02_100426` |
| `extra_work_group_id` / `group_sequence` / `group_total` | `unsignedBigInteger` nullable FK `extra_work_groups` nullOnDelete / two `unsignedSmallInteger` nullable | `2025_12_23_100846:15-20` |
| 7 indexes incl. `idx_type_status_planed`, `idx_type_status_requested` | — | `2025_12_30_082617:23-33` |

### Columns with NO migration in this repo

`id`, `title`, `description`, `status_id`, `priority_id`, `completion_notes` (original
`completion_note`), `approval_notes`, `upload_is_required`, `notes_is_required`,
`planed_at`, `started_at`, `completed_at`, `requested_at`, `approved_at`, `deadline_at`,
`customer_department_id`, `customer_works_type_id`, `is_customer_work`, `user_id`,
`created_at/updated_at/deleted_at`, the whole `archive_*` family, `invoice_id`,
`invoice_date`.
**COULD NOT DETERMINE their true nullability/defaults from this repo** — see §4.

Note: `2025_10_11_195020_create_ticket_extrawork_products_table.php:46-47` *does* define
`upload_is_required`/`notes_is_required` with `->default(false)`, but on a **different
table** (`ticket_extrawork_products`). It is not the `extra_works` definition.

## 2.1 The model — `app/Models/ExtraWork.php` (965 lines)

**Traits:** `SoftDeletes`, `HasTranslatableFields` (line 16). `$table = 'extra_works'`.

**`$fillable` (lines 20-91)** — 60 entries. Note that `$fillable` is *almost irrelevant*
for the HTTP surface: the controllers write through `EntityController`, which computes its
own allow-list from the entity config, not from `$fillable` (§2.3).

**`$casts` (93-118)**

```php
'upload_is_required' => 'boolean',  'notes_is_required' => 'boolean',
'is_customer_work'   => 'boolean',
'hours_planed' => 'decimal:2',      'hours_worked' => 'decimal:2',
'planed_at','planed_start_at','planed_end_at','started_at','completed_at',
'requested_at','approved_at','deadline_at' => 'datetime',
'customer_start_date' => 'date',    'invoice_date' => 'date',
'archive_requested_at','archive_approved_at','archive_rejected_at','drafted_at' => 'datetime',
'translate_meta' => 'array',
```

*Consequence (CODE + DATA):* `is_customer_work` is cast to a real boolean, so the JSON
carries `false`/`true`. Three SPA gates compare it with `=== 1`:
`frontend/src/pages/finalosius/extra-works/components/WorkflowActionsBar.jsx:56` —
`const isCustomerWork = isMelding && extraWork.is_customer_work === 1;` — which can
therefore **never** be true, and `detail.jsx:1369` `extraWork.is_customer_work !== 1` which
is therefore **always** true. DATA: `GET /admin/extra-works?statuses=9&per_page=1` →
`"is_customer_work": false`. The "customer work" gating in the detail page and the action
bar is inert. (`ExtraWorkDataGrid.jsx:563` writes `=== 1 || === true` and does work.)

**`$with` (120-130)** — eager loads `status, priority, category, userDepartment,
customerDepartment, customerWorksType, customerBuildings, createdUser, user` on **every**
query of this model, everywhere in the app.

**`$appends` (132-146)** — `is_approved, is_pending, products_count, attachments_count,
comments_count, employees_count, unread_comments_count, created_user_name, user_name,
total_cost, total_products_cost, total_hours, total_labor_cost`. Each of the first six and
the last four executes its own `COUNT`/`SUM` query per row (lines 391-412, 489-518) — an
N+1 by construction on list endpoints.

**`$hidden` (152-158)** — all 16 translation columns plus `translate_meta`.

**Mutator (167-182)** — `setDescriptionAttribute`: `strip_tags` + `html_entity_decode` +
`trim`; empty ⇒ `null`. **Every description stored is plain text**; HTML sent by the SPA
editor is destroyed on write. There is no matching mutator on `title`.

**Accessors (192-219)** — `title`, `description`, `completion_notes`, `approval_notes` all
return `getTranslatedField(...)`, i.e. the language variant, **not** the raw column.
`ExtraWorksController::transformModelData` (lines 391-395) deliberately overrides this by
reading `$model->getAttributes()['title']` etc. so the API returns the raw column. So the
accessor is bypassed on the admin API and only applies to other consumers.

**Relations (224-353)**

| method | target | key / filter |
|---|---|---|
| `status()` | `TicketStatus` (`t_ticket_status`) | `status_id` |
| `priority()` | `TicketPriority` | `priority_id` |
| `customerBuildings()` | `CustomerBuilding` **belongsToMany** via `extra_work_customer_building` | withPivot `created_by`, using `ExtraWorkCustomerBuilding` |
| `category()` | `TicketCategory` | `category_id` |
| `userDepartment()` | `UserDepartment` | `user_department_id` |
| `customerDepartment()` | `CustomerDepartment` | `customer_department_id` |
| `customerWorksType()` | `CustomerWorksType` | `customer_works_type_id` |
| `tasks()` | `TicketTask` | `extra_work_id`, `where task_source = 'extra_work'` |
| `attachments()` | `ExtraWorkAttachment` | `extra_work_id` |
| `products()` | `ExtraWorkProduct` | `extra_work_id` |
| `employeeAssignments()` / `assignments()` | `ExtraworkAssignment` | `extra_work_id` |
| `activeEmployeeAssignments()` | same | `+ is_active = true` |
| `comments()` | `ExtraWorkComment` | `is_deleted = false`, desc |
| `employeeHours()` | `ExtraWorkEmployeeHour` | `extra_work_id` |
| `workerAssignments()` | `ExtraWorkWorkerAssignment` | `extra_work_id` |
| `topLevelComments()` | `ExtraWorkComment` | `parent_comment_id IS NULL`, not deleted |
| `createdUser()` | `User` | `created_user_id` |
| `user()` | `User` | `user_id` |
| `invoiceItem()` | `InvoiceItem` hasOne | conventional `extra_work_id` |
| `invoice()` | `Invoice` **hasOneThrough** `InvoiceItem` | this is the real invoice link, not `invoice_id` |
| `group()` | `ExtraWorkGroup` | `extra_work_group_id` |

**Computed attributes**

- `is_approved` = `!empty($this->approved_at)`; `is_pending` = the negation (381-389).
  *Gate:* nothing in the backend branches on them; they are display-only.
  **Consequence:** a record moved to status 4 by the group bulk endpoint (§2.4) has
  `approved_at = NULL` and therefore reports `is_approved: false` while showing the
  "Goedkeuring door de klant" chip.
- `total_products_cost` (427-435) = `SUM(products.subtotal)` — **KDV/VAT excluded**.
- `total_cost` (440-445) = `getTotalLaborCost() + total_products_cost`, VAT excluded.
- `total_hours` (506-509) = `SUM(extra_work_employee_hours.hours)`.
- `total_labor_cost` (515-518) = `SUM(extra_work_employee_hours.total_cost)`.
- `getRemainingHours()` (523-528): `$this->hours ?? $this->hours_worked ?? $this->total_hours ?? 0` minus distributed. **`$this->hours` does not exist on this model** — it resolves to `null` and the `??` chain falls through to `hours_worked`. Harmless but misleading.
- `unread_comments_count` (889-901) — per-request, per-user; 0 when unauthenticated.

**Scopes (450-484)** — `pending` (`approved_at IS NULL`), `approved` (`NOT NULL`),
`forCustomer`, `forBuilding`, `forCustomerBuilding` (all via `whereHas('customerBuildings')`),
`byStatus`.

**`booted()` (541-701)** — two listeners, both of which fire only on **model** events, i.e.
**never** on the mass `update()` calls in §2.4.

`static::created` (544-554):
1. `addSystemComment("Created: {title} — {description}", 'created')`
2. `dispatch(fn => sendFcmNotification($extraWork, 'created'))->afterResponse()`

`static::updated` (557-700):
- If `status_id` is dirty **and** `$extraWork->skipStatusComment` is not set:
  builds `"Status Status gewijzigd: {old} → {new}"` (the doubled word is in the source,
  line 572) plus status-specific detail lines. The `switch ($newStatusId)` arms are
  **1** (created_at/created_by), **2** (planed_by/planed_at/planed_start_at/planed_end_at),
  **3** (`// No additional info needed`), **4** (approved_by/approved_at + approval notes),
  **8** (archive_approved_by/at + archive notes). *There is no arm for 5, 6, 7 or 9.*
- Line 613 reaches into the HTTP layer from the model: `request()->input('approval_notes')`.
- If `archive_rejected_at` is dirty and truthy, the whole message is replaced with
  `"Archief afgewezen"` + reason.
- Writes the system comment, then `broadcast(new ExtraWorkStatusChanged(...))->toOthers()`.
- Separately: if **any** other field is dirty, `broadcast(new ExtraWorkUpdated(...))` and a
  second FCM dispatch. Note the condition at line 680 is `!isset($changes['status_id'])`,
  so a status change alone does **not** send the "updated" FCM — only the status one.

`addSystemComment()` (776-810) — creates an `ExtraWorkComment` with
`user_id = auth()->id() ?? 1` (**user 1 is the implicit system user**), optionally attaches
files as `ExtraWorkAttachment` rows with `is_comment = true`, then creates unread records
and broadcasts.

`getRelatedUsers()` (841-861) — **BUG, CODE:**

```php
if ($this->created_by) {
    $userIds->push($this->created_by);   // created_by is a VARCHAR(100) NAME
}
```

`created_by` holds `"B Amsterdam"` (DATA, record 476). Pushing it into a collection that is
then used as `User::whereIn('id', ...)` means the creator is **never** included in the
unread-comment fan-out. Only assignees and users with role name `admin` receive unread rows.

`sendFcmNotification()` (709-767) — recipients from `RecipientDeterminer`; notification type
is `melding_{event}` when `type == 2`, else `extra_work_{event}`; `relatedType` likewise
`'Melding'`/`'ExtraWork'`.

**Translation support (910-964)** — `$translatable_fields = ['title','description',
'completion_notes','approval_notes']`, plus per-language getters with fallback to the base
column.

### The observer — `app/Observers/ExtraWorkObserver.php`

Registered at `app/Providers/AppServiceProvider.php:28`:
`\App\Models\ExtraWork::observe(\App\Observers\ExtraWorkObserver::class);`

`created()` → `ExtraWorkActivityLogger::logCreated` + queue translation.
`updated()` → translation, then a loop over `$importantFields`:

```php
'title','description','status','status_id','assigned_to','estimated_hours','actual_hours',
'priority','priority_id','planned_at','started_at','completed_at','approved_by',
'rejected_by','is_archived',
```

**Seven of those fifteen names are not columns on `extra_works`:** `status`, `assigned_to`,
`estimated_hours`, `actual_hours`, `priority`, `rejected_by`, `is_archived` — and
`planned_at` is misspelled (the column is `planed_at`, one `n`). `isDirty()` on a
non-existent attribute is always false, so:

- `logUserAssigned` / `logUserUnassigned` — **DEAD**
- `logArchived` / `logUnarchived` — **DEAD**
- `logRejected` — **DEAD**
- `logDateChange` for the *planning* date — **DEAD** (only `started_at`/`completed_at` fire)

`deleted()` → `logDeleted`. There is **no `deleting`/`restored`/`forceDeleted`** handler.

### Jobs and scheduler

`app/Jobs/` contains only `AutoTranslateJob`, `AutoTranslateCommentJob`,
`AutoTranslateExtraWorkJob`. **`routes/console.php` contains only Laravel's stock
`inspire` command and `bootstrap/app.php` registers no `withSchedule(...)`.** There is
**no scheduled task of any kind** touching Extra Works — nothing ages a record, nothing
escalates a deadline, nothing auto-archives, nothing auto-invoices. This is itself a
finding: every state change in this area is human-triggered. (CODE — `routes/console.php`
full file is 8 lines; `grep -n "schedule\|withSchedule" bootstrap/app.php` → no match.)

## 2.2 Routes and middleware

All routes below sit inside the admin group and each carries `ucb.permission:<module>,<action>`.
The controller constructor additionally applies `auth:sanctum` and a closure that injects
`type = 2` when the request path contains `/meldings` and no `type` was supplied
(`ExtraWorksController.php:45-50`).

### `/api/admin/extra-works` — `ucb.permission:extra_works,*`

| method + path | controller method | permission | writes |
|---|---|---|---|
| GET `/accessible` | `getAccessibleExtraWorks` | list | — |
| GET `/` | `index` (EntityController) | list | — |
| POST `/` | `store` | create | the record + products + assignments + attachments + buildings + workers |
| POST `/batch` | `batchStore` | create | N records + optional `extra_work_groups` row |
| POST `/bulk/delete` | `bulkDelete` | delete | soft-delete, status 1 only |
| POST `/bulk/convert-to-melding` | `bulkConvertToMelding` | update | `type` (mass update) |
| GET `/groups/{groupId}` | `getGroupMembers` | view | — |
| PUT `/groups/{groupId}/status` | `bulkUpdateGroupStatus` | update | `status_id` (mass update) |
| DELETE `/groups/{groupId}` | `bulkDeleteGroup` | delete | soft-delete all + group |
| GET `/meta/config` | `meta` | **`admin.only` +** list | — |
| GET `/meta/form-data` | `formData` | view | — |
| GET `/dashboard` | `dashboard` | view | — |
| GET `/statistics` | `statistics` | view | — |
| GET `/weekly-report` | `weeklyReport` | view | — |
| GET `/comprehensive-report` | `comprehensiveReport` | view | — |
| GET `/{id}` | `show` | view | — |
| PUT `/{id}` | `update` | update | **the main stamping path** |
| DELETE `/{id}` | `destroy` | delete | `deleted_at` |
| GET `/{id}/activities` | `getActivities` | view | — |
| GET/DELETE `/{id}/tasks…` | `getTasks`,`deleteTask` | view/delete | — |
| GET/POST/DELETE `/{id}/attachments…` | `getAttachments`,`addAttachment`,`deleteAttachment` | view/update/update | `extra_works_attachments` |
| GET/POST/PUT/DELETE `/{id}/products…` | `getProducts`,`addProduct`,`updateProduct`,`deleteProduct` | view/update | `extra_work_products` |
| GET/POST/PUT/DELETE `/{id}/employees…` | `getEmployees`,`addEmployee`,`updateEmployee`,`deleteEmployee` | view/update | `extrawork_assignments` |
| GET/POST/DELETE `/{id}/workers…` (+ `/bulk`) | `getWorkers`,`addWorker`,`bulkAddWorkers`,`bulkDeleteWorkers`,`deleteWorker` | view/update | `extrawork_worker_assignments` |
| GET/POST/PUT/DELETE `/{id}/comments…` | 6 methods | view/update | `extra_work_comments` |
| **PUT `/{id}/status`** | `updateStatus` | update | **`status_id` only** |
| PATCH `/{id}/hours` | `updateHours` | update | `hours_planed`, `hours_worked` |
| POST `/{id}/comments/{cid}/mark-read`, `/comments/mark-all-read` | read tracking | update | `extra_work_comment_reads` |
| GET `/{id}/unread-count` | `getUnreadCommentsCount` | view | — |
| PUT/DELETE `/{id}/draft` | `saveDraft`,`clearDraft` | update | `draft_message`,`drafted_at`,`drafted_by` |
| POST `/{id}/archive/approve` | `approveArchive` | update | status 8 + 8 archive columns |
| POST `/{id}/archive/reject` | `rejectArchive` | update | status from body + 6 archive columns |
| POST `/{id}/convert-to-extra-work` / `/convert-to-melding` | conversions | update | `type` |
| DELETE `/{id}/customer-buildings/{cbId}` | `removeCustomerBuilding` | update | junction row |
| GET `/{id}/price-breakdown` | `priceBreakdown` | view | — |

*CODE — `routes/api.php:695-786`.*

### `/api/admin/meldings` — `ucb.permission:melding,*`

Same controller, ten routes only: `index`, `store`, `meta`, `meta/config`,
`meta/form-data`, `dashboard`, `statistics`, `report` → `meldingReport`, `show`, `update`,
`destroy`. The list/create/meta/dashboard/statistics/report routes carry
`->defaults('type', 2)`; **`show`, `update` and `destroy` do not**.
*CODE — `routes/api.php:675-690`.*

### `/api/admin/extra-works/{extraWorkId}/employee-hours` — `ExtraWorkEmployeeHoursController`

`index`(view), `store`(create, bulk-capable), `update`(update), `destroy`(delete),
`destroy/employee/{id}`(delete), `destroy/employee/{id}/overtime-type/{id}`(delete),
`summary`(view). Plus `/employees/workers`, `/employees/weekly-hours`, `/overtime-types`,
and two `by-building` report routes. *CODE — `routes/api.php:788-811`.*

## 2.3 Validation — the load-bearing absence

`EntityController::getValidationRules()` builds rules **exclusively** from
`config['fields'][*]['validation'][$action]`:

*CODE — `app/Http/Controllers/Base/EntityController.php:583-586*:

```php
foreach ($config['fields'] ?? [] as $fieldName => $fieldConfig) {
    if (isset($fieldConfig['validation'][$action])) {
```

`grep -n validation config/base/extra-works.php` → **one hit, and it is a comment**
(`config/base/extra-works.php:840  // TCB (ticket_customer_building) validation`).
`config/admin/extra-works.php` → **zero hits**, and it does not override the `fields` key
at all.

**Therefore `POST /admin/extra-works` and `PUT /admin/extra-works/{id}` run with an EMPTY
rule array.** No required title, no `exists:` check on `status_id`, `priority_id`,
`category_id`, `customer_department_id`, no type check on the date fields, nothing. The
only guards on these two endpoints are the UCB permission middleware, the database's own
FK constraints, and MySQL's column types.

(The `sub` context config `config/sub/extra-works.php` *does* carry ~21 `validation` blocks.
It is only loaded when `$this->context === 'sub'`; `ExtraWorksController::$context = 'admin'`
— `ExtraWorksController.php:29`. **INFERRED:** validation was written for the sub context
and never ported to admin. Confirming would need a request through a `sub`-context route.)

The endpoints that *do* validate are the hand-written ones, and only those:

| endpoint | rules (verbatim) |
|---|---|
| `PUT /{id}/status` | `status_id: required\|exists:t_ticket_status,id`, `note: nullable\|string\|max:1000`, `images: nullable\|array`, `images.*: integer\|exists:files,id` (`:3624-3629`) |
| `PATCH /{id}/hours` | `hours_planed: nullable\|numeric\|min:0\|max:999999.99`, `hours_worked:` same (`:5639-5642`) |
| `PUT /{id}/draft` | `draft_message: required\|string\|max:5000` (`:5812`) |
| `POST /{id}/archive/approve` | `approval_notes: nullable\|string\|max:1000`, `note:` same, `images: nullable\|array`, `images.*: integer\|exists:files,id` (`:2638-2643`) |
| `POST /{id}/archive/reject` | `rejection_reason: nullable\|string\|max:1000`, `reason:` same, **`status_id: required\|integer\|exists:t_ticket_status,id`**, `images…` (`:2719-2724`) + a manual 400 if both reason fields are empty (`:2731-2735`) |
| `POST /{id}/attachments` | `files: required\|array\|min:1`, `files.*.id: required\|exists:files,id`, `files.*.is_pre_file: nullable\|boolean`, `files.*.is_draft: nullable\|boolean` (`:1617-1622`) |
| `POST /bulk/delete`, `POST /bulk/convert-to-melding` | `ids: required\|array\|min:1`, `ids.*: integer\|exists:extra_works,id` (`:6288-6291`, `:6373-6376`) |

### The write allow-list

`EntityController::getFillableFields()` (`:619-639`) returns the config field names whose
`fillable` is not `false`; `store`/`update` then do `$request->only($fillableFields)`.
The 39 field keys in `config/base/extra-works.php` are:

```
title, description, status_id, priority_id, type, is_customer_work, category_id,
user_department_id, customer_department_id, customer_works_type_id, customer_buildings*,
file_1..file_4, planed_at, planed_start_at, planed_end_at, deadline_at,
customer_start_date, started_at, completed_at, requested_at, created_at, hours_worked,
hours_planed, approved_at, requested_by, created_user_id, user_id, invoice_id,
invoice_date, planed_by, started_by, completed_by, approved_by, archive_approved_by,
archive_rejected_by, archive_rejection_reason
```
(*`customer_buildings` is `'fillable' => false` — handled by hand in the controller.*)

**Everything else on the model is unreachable through `store`/`update`**, notably:
`completion_notes`, `approval_notes`, `upload_is_required`, `notes_is_required`,
`archive_requested_at/by`, `archive_approved_at`, `archive_rejected_at`,
`archive_approval_notes`, `draft_message`, `drafted_at`, `drafted_by`,
`extra_work_group_id`, `group_sequence`, `group_total`, and all translation columns.
That is exactly why `update()` carries a hand-written block commented
`// Handle notes fields (parent might miss these)` (`:1242-1253`) which re-injects
`completion_notes`, `approval_notes`, `archive_approval_notes`,
`archive_rejection_reason` and writes them with a raw
`ExtraWork::where('id',$id)->update($autoFields)`.

`upload_is_required`/`notes_is_required` got **no such rescue block**, which is why the
planning modal's toggles are dropped (§3.6).

Defaults injected on create (`applyDefaultValues`, `:678-691`) from the config:
`status_id = 1`, `priority_id = 2`, `type = 1`, `is_customer_work = 0`.
There are **no** `forced_value` entries for extra-works, so `applyForcedValues` is a no-op
here.

## 2.4 `ExtraWorksController` — every public method

`class ExtraWorksController extends EntityController`, `$modelClass = ExtraWork::class`,
`$entityName = 'extra-works'`, `$context = 'admin'` (`:26-29`).
`index()`, `meta()` and `statistics()`'s scaffolding come from `EntityController`;
`statistics()` is overridden.

### `buildQuery(Request, bool $applyFilters)` — `:69-311` (protected, but it is the list)

1. `parent::buildQuery` → applies `applyUcbPermissions`, then (if `$applyFilters`)
   `applySearch` and `applyRequestFilters`, then `applyAdditionalScopes`.
2. Eager-loads a narrower relation set + `withCount(products, attachments,
   topLevelComments as comments_count, employeeAssignments as employees_count)`.
3. **`?statuses=` (comma list, OR)** with *group awareness*: a group header
   (`group_sequence = 1`) is returned if **any** sibling in the group matches.
   *CODE `:110-129`.* If `9` is in the list, `invoiceItem` and `invoice` are eager-loaded.
4. **`else` branch, `:146`:** `$query->where('status_id', '!=', 9);`
   Without an explicit `?statuses=`, invoiced records are hidden exactly like soft-deletes.
5. `?completed_start_date` + `?completed_end_date` + `?date_filter_type` ∈
   {`created` → `created_at`, `archived` → `archive_approved_at`}. Any other value ⇒ **no
   filter applied at all**, silently.
6. `?date_start` + `?date_end` + `?date_field`, with five compound aliases implemented as
   `COALESCE`: `customer_start_or_requested`, `planed_or_requested`,
   `approved_or_requested`, `approved_at_or_planed`, and `invoice_date` (which resolves via
   `whereHas('invoice')` to `invoices.invoice_date`, **not** to `extra_works.invoice_date`).
   Plain fields are white-listed to
   `created_at, archive_approved_at, planed_start_at, deadline_at, approved_at, requested_at, customer_start_date`.
   With no `date_field` the fallback ORs `created_at`, `planed_start_at`, `deadline_at`.
7. `?me=true` → `whereHas('employeeAssignments', user = me AND is_active)`.
8. Sorting: `sort_by` ∈ `date|priority|status|created_at|deadline_at|planed_start_at|approved_at|archive_approved_at|invoice_date`
   (`date` maps to `planed_start_at`), `sort_order` ∈ asc|desc, defaults `created_at desc`.
   `invoice_date` sorts through a correlated sub-select on `invoices`.
9. Logs the full SQL at info level on every list call (`:309`).

**Note what is missing: no `type` filter.** DATA: `GET /admin/extra-works?per_page=1` →
`total: 39`; `?type=1` → `32`; `?type=2` → `7`; `GET /admin/meldings?per_page=1` → `7`.
**The default Extra Works list contains all seven Meldingen.**

### `applyUcbPermissions(Builder)` — `:317-359`

- No user ⇒ `whereRaw('1 = 0')`.
- **`$user->role_id == 1` ⇒ returns the query untouched (full admin bypass).**
- Otherwise OR of: an active `extrawork_assignments` row for the user; **`extra_works.created_by = $user->id`**; an `extra_work_customer_building` row whose `customer_building_id` is in `user_customer_building_permissions` for the user.

**BUG (CODE + DATA):** `created_by` is `VARCHAR(100)` holding `"Name (Role)"` (or, on
customer-originated records, a customer name). DATA record 476: `"created_by": "B Amsterdam"`.
`orWhere('extra_works.created_by', $user->id)` compares that string to an integer; in MySQL
non-strict comparison this is `'B Amsterdam' = 148` → false. **The "creator can see their
own record" rule never fires.** The identical mistake is repeated in
`getAccessibleExtraWorks` (`:3166`).

### `applyAdditionalScopes` — `:365-388`
`?customer_id=` and `?building_id=` via `whereHas('customerBuildings', …)`. Works.

### `transformModelData($model, ?string $language)` — `:393-586`

Overrides the parent, and:
- forces `title/description/completion_notes/approval_notes` to the **raw** column
  (bypassing the translation accessors) and unsets all 16 language variants;
- unsets `customer_name`, `building_name`, `customer_id`, `building_id`;
- flattens `category`, `user_department`, `customer_department`, `customer_works_type`,
  `priority`, `status` into `*_name` scalars (with `getTranslatedLabel($language)` where
  available);
- emits `customer_buildings_arr` (ids) and a slimmed `customer_buildings` array;
- runs a **per-row query** for `user_assignments` (join on `extrawork_assignments`);
- recomputes `total_price` / `total_tax` / `total_subtotal` **from `extra_work_products`,
  including VAT**, as `number_format(...,2)` **strings**. Note this is a *third* money
  formula, different from `total_cost` (VAT-excluded, includes labour) and from
  `financial_summary` (§ below);
- runs `getAvailableUsersForExtraWork($model)` **per row**;
- for a group header (`group_sequence === 1`) runs a per-row `GROUP BY` to produce
  `group.status_distribution`.

*Consequence:* a 25-row list page issues on the order of 25 × (assignments + available
users + 6 appended counts) extra queries.

### `store(Request)` — `:588-921`  → `POST /admin/extra-works`

Reads `assignment_products`, `assigned_employees`, `workers`, `customer_buildings` (or a
single `customer_building_id`), `planed_by`/`started_by`/`completed_by`, and `files`
(new array form `[{id, is_pre_file}]`, or legacy `file1`..`file4` **request keys** — note
`"file{$i}"`, i.e. `file1`, which is *not* the `file_1` column).

Then `parent::store($request)` creates the row (empty validation; config defaults
status 1 / priority 2 / type 1 / is_customer_work 0), which fires `ExtraWork::created` →
system comment + FCM.

**Server-stamped on create, regardless of the payload (`:661-680`):**

```php
$roleName = $user->role->display_name ?? 'User';
$userInfo = "{$user->name} ({$roleName})";
$createdByName = $userInfo;  $requestedByName = $userInfo;
…
$updateFields['created_user_id'] = $userId;   // always
```

so `created_by`, `requested_by` (both strings) and `created_user_id` (the real FK) are
overwritten from the session. `customer_department_id` / `customer_works_type_id` are
re-applied explicitly.

Then, in order: products copied out of `customer_products` into `extra_work_products`
(`price`, `tax_rate`, `unit_id`, `category_id`, `is_fixed_price = true`, and
`customer_building_id => $extraWork->customer_building_id` — **a column that no longer
exists on the model, so this always inserts NULL**); user assignments; attachments (then
re-linked to the auto-created `type='created'` comment and that comment's
`has_attachments` set); customer-building junction rows; worker assignments.

**BUG (CODE, `:838`):** the `initial_comment` branch inserts
`'user_id' => $createdBy` — **`$createdBy` is never defined in this method.** Under PHP 8
it evaluates to `null` with a warning; `extra_work_comments.user_id` is a FK, so a request
containing `initial_comment` or `comment_files` will fail. The SPA's create form does not
send either key (`add.jsx:1054-1080`), which is why this has not surfaced.

Returns 200 with `transformModelData($extraWork)`.

### `update(Request, $id)` — `:923-1348` → `PUT /admin/extra-works/{id}` — **the stamping engine**

Order of operations:

1. `customer_building_id` (singular) ⇒ **replace mode**: deletes all junction rows and
   inserts one. `customer_buildings` (array) ⇒ **add-only mode**: inserts the diff, never
   removes. Two different semantics on one endpoint.
2. `workers` (`null` = untouched, `[]` = clear all) ⇒ full sync of
   `extrawork_worker_assignments`.
3. `assignment_products` ⇒ **append-only**; existing `customer_product_id`s are skipped.
   There is no removal path here.
4. `user_assignments` **or** `assigned_employees` ⇒ full sync of `extrawork_assignments`
   (removals are soft: `is_active = false`).
5. `$statusChanged` is computed at `:1176-1179` and **never read again** — dead local.
6. **The auto-fill block (`:1181-1275`)** — the table in §1.4, verbatim conditions:
   - `:1191-1193` `($request->has('planed_start_at') && …) || ($request->has('planed_end_at') && …) || ($request->has('status_id') && $request->input('status_id') == 2)` ⇒ `planed_by`, and `planed_at = now()` if absent.
   - `:1203` `$request->has('started_at') && $request->input('started_at')` ⇒ `started_by`.
   - `:1208-1216` `completed_at` truthy **or** `status_id == 3` ⇒ `completed_by`, `completed_at = now()` if absent.
   - `:1220-1229` `approved_at` truthy **or** `status_id == 4` ⇒ `approved_by`, `approved_at = now()` if absent.
   - `:1234-1241` truthy `archive_requested_at`/`archive_approved_at`/`archive_rejected_at` ⇒ the matching `*_by`.
   - `:1242-1253` pass-through for `completion_notes`, `approval_notes`, `archive_approval_notes`, `archive_rejection_reason`.
7. `$request->merge($autoFields)` then `parent::update(...)` (config allow-list, empty rules)
   — this is the write that fires the `ExtraWork::updated` model event.
8. **After** the parent succeeds, `ExtraWork::where('id',$id)->update($autoFields)` (`:1278`)
   — a second, event-free write that lands the fields the config allow-list dropped.
9. **`status_id == 4` or truthy `approved_at` ⇒ every `extra_works_attachments` row with
   `is_draft = true` is flipped to `is_draft = false` (`:1285-1296`)** — approval publishes
   the draft photos. This block exists twice (again at `:1318-1330`) but the first `return`
   makes the second unreachable whenever `$autoFields` is non-empty.

### `show(Request, $id)` — `:1353-1443` → `GET /{id}`

Loads the record with `findOrFail` **directly on the model** — it does **not** go through
`buildQuery`, therefore **`applyUcbPermissions` is not applied**. Any caller holding
`extra_works,view` can read any record by id, regardless of assignment, creator or UCB
scope. The same pattern (bare `ExtraWork::findOrFail`) is used by `updateStatus`,
`updateHours`, `saveDraft`, `clearDraft`, `approveArchive`, `rejectArchive`,
`convertToExtraWork`, `convertToMelding` and `priceBreakdown`. Only `update()` and
`destroy()` route through `buildQuery` and are scoped.

Response adds `user_assignments`, `worker_assignments`, `available_users` and
`financial_summary` (a **fourth** money shape — see `calculateFinancialSummary`, `:5726-5789`:
per-line `line_total`, `line_tax`, `line_total_with_tax` from `extra_work_products.tax_rate`,
joined to `product_units` for `unit_name`).

### `updateStatus(Request, $id)` — `:3621-3752` → `PUT /{id}/status`

Validates only `status_id: required|exists:t_ticket_status,id` (+ optional note/images).
**Writes `status_id` and nothing else.** No date stamp, no `*_by`, no transition guard,
no side effects on attachments. If the new status's slug is `started`/`basladi` or
`planned`/`planlandi` it sets `skipStatusComment` and writes a hand-made Turkish comment
("İşe başlandı" / "Planlandı") — but **no such slug exists** in the live status table
(`new, in_progress, resolved, closed, internal_approval, customer_approval, invoiced_v2,
archived, invoiced`), so both branches are **DEAD** and every call falls into the generic
`else` (`:3654`).

Then it sends FCM to: every user holding a UCB permission (`scope_mask > 0`) on any of the
record's customer-buildings, every active assignee, every user in
`users.department_id = extra_works.user_department_id` with `status_id = 1`, and every user
whose role slug is `admin`. Deep link `/meldings/{id}?tab=info` for type 2, else
`/extra-works/{id}?tab=info`.

*Consequence:* moving a record with `PUT /{id}/status` instead of `PUT /{id}` produces a
record in status 3 with **no `completed_at`**, or status 4 with **no `approved_at`** and
**with its draft attachments still hidden**. The SPA never uses this endpoint for the
workflow buttons — it uses `PUT /{id}` for all of them.

### `approveArchive(Request, $id)` — `:2633-2694` → `POST /{id}/archive/approve`

Accepts `note` or `approval_notes`, plus `images[]`. Writes, in one `update()`:

```php
'status_id'              => 8,
'archive_approved_at'    => now(),
'archive_approved_by'    => "{$user->name} ({$role->display_name})",
'archive_approval_notes' => $note,
'archive_requested_at'   => $extraWork->archive_requested_at ?? now(),   // back-filled
'archive_requested_by'   => $extraWork->archive_requested_by ?? $userInfo,
'archive_rejected_at'    => null,
'archive_rejected_by'    => null,
'archive_rejection_reason' => null,
```

Then `skipStatusComment = true` and a hand-written comment
`"Arşiv onaylandı - İş tamamlandı"` (+ note), with the uploaded images attached.

**There is no "request archive" endpoint anywhere.** `archive_requested_at`/`_by` are only
ever set by this back-fill. DATA record 476 confirms it: `archive_requested_at` ==
`archive_approved_at` == `2025-11-24T16:13:12`, to the second.

### `rejectArchive(Request, $id)` — `:2714-2794` → `POST /{id}/archive/reject`

`status_id` is **required in the body** — the server does not choose it. The SPA sends `3`
(`detail.jsx:1155`). Writes `archive_rejected_at = now()`, `archive_rejected_by = userInfo`,
clears the three `archive_approved_*` columns, and **appends** to
`archive_rejection_reason`:

```php
$rejectionId = $extraWork->archive_rejected_at ?
    (substr_count($extraWork->archive_rejection_reason ?? '', "\n") + 2) : 1;
$newEntry = "[{$timestamp}] #{$rejectionId} {$reason}";
```

so the column accumulates a newline-separated log and is **never replaced**. The method
docblock states plainly: *"'Rejected' status is NO LONGER USED! Rejection tracked via
archive_rejected_by/at/reason … Client shows rejected items based on archive_rejected_*
fields, NOT status"* (`:2718-2723`). The SPA's success toast nevertheless says
"Archive request rejected (Status 5 - Archive Rejected)" (`detail.jsx:1163`) — stale copy.

### `convertToExtraWork($id)` / `convertToMelding($id)` — `:2803-2984`

Guard: refuse with 400 if already the target type or not the source type. Write:
`update(['type' => 1])` / `update(['type' => 2])`. Add a system comment
(Turkish: *"Melding'den Extra Work'e dönüştürüldü"*). Insert an `extra_work_activities`
row with `action = 'type_converted'`, `old_value`, `new_value`, JSON metadata and the
client IP. **Nothing else is touched or cleared.**

### `destroy(Request, $id)` — `:3870-3897` → `DELETE /{id}`

```php
if ($extraWork->status_id != 1 && $user->role_id != 1) {
    return $this->fail('FORBIDDEN', …, 403);
}
return parent::destroy($request, $id);
```

Non-admins may delete only status 1; **`role_id == 1` may soft-delete anything, including a
status-9 invoiced record.** `parent::destroy` is scoped by `buildQuery`, so UCB applies here.

### `bulkDelete` / `bulkDeleteGroup` / `bulkUpdateGroupStatus` / `bulkConvertToMelding` — `:6231-6432`

- `bulkDelete`: validates ids, then **refuses the whole batch** with 400 if any record is
  not status 1 (`:6294-6301`), then soft-deletes.
- `bulkDeleteGroup`: **no status check at all** — soft-deletes every member of the group
  and the group row. A group containing invoiced works can be deleted this way.
- `bulkUpdateGroupStatus`: `ExtraWork::where('extra_work_group_id',$groupId)->update(['status_id' => $newStatusId])`, optionally narrowed by `source_status_id`. **`$newStatusId` is not validated against `t_ticket_status` at all.**
- `bulkConvertToMelding`: mass `update(['type' => 2])`.

**All four use query-builder mass updates, which bypass Eloquent events.** So the group
"Goedkeuren" button (source 3 → target 4, `WorkflowActionsBar.jsx:302`) sets `status_id = 4`
on N records with **no `approved_at`, no `approved_by`, no system comment, no broadcast, no
FCM, no activity row, and no draft-attachment publication**. Those records will report
`is_approved: false` while displaying the approved status.

### `batchStore(Request)` — `:5932-6100` → `POST /batch`

Takes `scheduled_entries[]`. If more than one entry, creates an `ExtraWorkGroup`:

```php
'building_id' => $customerBuildings[0] ?? null,   // this is a CUSTOMER-BUILDING id
'year' => $firstEntry['year'] ?? now()->year,
'week_number' => $firstEntry['weekNumber'] ?? now()->weekOfYear,
'is_auto_generated' => true,
```

**The group's `building_id` is populated with a `customer_buildings.id`,** not a
`buildings.id`. Then per entry:

```php
'status_id' => 1, 'type' => 1,
'customer_start_date' => $scheduleDateTime->toDateString(),
'deadline_at'         => $scheduleDate 20:59:00,
'requested_at'        => $scheduleDateTime,        // the SCHEDULED slot, not "now"
'created_by'          => "{$user->name} ({$role})",
'created_user_id'     => $user->id,
'extra_work_group_id' => $groupId,
'group_sequence' => $sequence++, 'group_total' => $groupTotal,
```

and the title gets a suffix `" [WK{week}-{d.m.Y}:{time}:{op|voor|na}]"`.
**`requested_by` is never set by this path** (unlike `store`).
DATA record 476: title `"…[WK44-02.11.2025:19:00-na]"`, `requested_at 2025-11-02T18:00:00Z`
(= 19:00 CET), `created_at 2025-11-24T16:08:03Z`. **`requested_at` is 22 days BEFORE
`created_at`** — it is the scheduled slot, not a request time. Any report that reads
`requested_at` as "when was this asked for" is wrong for every batch-created record.

Products are copied with a `'unit' => $unitValue` string column (whereas `store` writes
`unit_id`) — two different product-unit conventions on the same table.

### `saveDraft` / `clearDraft` — `:5804-5928`

`saveDraft` writes `draft_message`, `drafted_at = now()`, and
`drafted_by = "{$user->name} ({ucfirst(str_replace('-',' ',$user->role->name))})"` — note
this builds the role label from `role->name`, whereas every other stamp uses
`role->display_name`. Two different "Name (Role)" formats coexist in the same table.
`clearDraft` nulls all three.

### `updateHours` — `:5633-5719` → `PATCH /{id}/hours`

The only validated numeric write. Returns `distributed_hours` and `remaining_hours`
computed live from `extra_work_employee_hours`.

### `priceBreakdown` — `:4253-4374` → `GET /{id}/price-breakdown`

A **fifth** money shape: products (qty × price, no tax per line), labour grouped by
employee then by overtime type (`hours`, `cost`, `multiplier`), and a totals block using a
**hard-coded `$taxRate = 0.21`** with the comment `// 21% VAT (can be made configurable)`
(`:4312`). Currency hard-coded `'EUR'`.

### Reporting endpoints

`statistics` (`:3905-4007`), `dashboard` (`:3358`), `weeklyReport` (`:4024`),
`comprehensiveReport` (`:4406`), `meldingReport` (`:5069`). `comprehensiveReport` is the
only place in the entire backend that emits `upload_is_required` / `notes_is_required`
(`:4819-4820`) — as pass-through display values.

`statistics` white-lists five slugs (`new, in_progress, resolved, closed, archived`) and
hard-codes the sixth bucket:

```php
'value' => $counts[9] ?? 0,  // Status 9 = Invoiced
'label' => 'Invoiced',  // Hardcoded since status 9 doesn't exist in t_ticket_status
```

**That comment is factually wrong** — status 9 does exist (DATA, §3.1). And statuses
**5, 6 and 7 are absent from every statistic bucket**, so if a v1 record ever landed on one
it would vanish from all dashboards.

DATA cross-check: `GET /admin/extra-works/statistics` returned `new 18, in_progress 5,
resolved 1, closed 6, archived 9, invoiced 37` (sum 76), while `?statuses=n` returned
`19, 6, 1, 6, 9, 37` (sum 78). The two-row difference is the group-header inflation in
`buildQuery` step 3 — **the list counts and the statistic counts do not agree by design.**

## 2.5 Field-by-field read/write map

Format: NAME · WRITTEN BY · READ BY · IF NULL · GATES · DEAD?

### Identity / classification

**`id`** — auto. Read by everything.

**`type`** (tinyint, default 1) — WRITTEN BY: `store`/`batchStore` (default 1 / literal 1),
`convertToExtraWork` (1), `convertToMelding` (2), `bulkConvertToMelding` (2, mass).
READ BY: `?type=` filter, `statistics`, `dashboard`, `comprehensiveReport`,
`meldingReport`, all six dashboard controllers, `WeeklyController`, the FCM type/deep-link
choice (`ExtraWork.php:734-746`), the SPA's `isMelding`. IF NULL: `WeeklyController:456`
and `Admin/DashboardController:236` explicitly `orWhereNull('type')` and treat it as Extra
Work. GATES: route permission module, notification routing, dashboard bucket, which
buttons render. **Live.**

**`status_id`** — WRITTEN BY: `store` (default 1), `batchStore` (1), `update` (free),
`updateStatus` (free), `approveArchive` (8), `rejectArchive` (from body),
`bulkUpdateGroupStatus` (free, mass), `InvoiceController::store`/`addItem` (9),
`InvoiceController::destroy`/`removeExtraWork`/`deleteItem` (8). READ BY: everything.
GATES: everything the UI shows; the invoice pipeline's `where('status_id', 8)`;
`destroy`'s non-admin guard (`!= 1`); `bulkDelete`'s guard (`!== 1`); `buildQuery`'s
implicit `!= 9`. **Live and completely unguarded.**

**`priority_id`** — WRITTEN BY: `store` (default 2), `batchStore` (from body, default 1),
`update`. READ BY: filters, sorting (`sort_by=priority`), display. **Live.**

**`category_id`** (Meldingen: Verzoek/Extra/Compliment/Melden/Storing/Ongegrond/Klacht) —
WRITTEN BY: `store`/`update` via the config allow-list. READ BY: `category_name` in
transform, `meldingReport` grouping, `?category_id=` filter. IF NULL: `category_name: null`.
**Live (Melding-centric).**

**`user_department_id`** — WRITTEN BY: `store`/`update`; the SPA hard-codes `1` for
Meldingen (`add.jsx:1070`). READ BY: `user_department_name`; **and the FCM fan-out in
`updateStatus`** (`:3684-3688`) which notifies every active user in that department.
GATES: notification recipients. **Live.**

**`customer_department_id`, `customer_works_type_id`** — WRITTEN BY: `store` (explicitly
re-applied), `batchStore`, `update`. READ BY: `*_name` in transform, filters,
`comprehensiveReport` grouping. **Live.**

**`is_customer_work`** (boolean, default 0) — WRITTEN BY: `store` only (`:642`). READ BY:
**nothing in the backend**; four SPA gates, three of which are broken by the boolean cast
(see §2.1). **Effectively dead server-side; degraded client-side.**

### Text

**`title`** — WRITTEN BY: `store`, `batchStore` (with the `[WK…]` suffix), `update`.
READ BY: everything, plus `InvoiceItem.description` at invoice time
(`InvoiceController.php:145` `'description' => $work->title`). **GATES money-facing text:
the invoice line description IS the extra work title.** **Live.**

**`description`** — WRITTEN BY: same, through the HTML-stripping mutator. **Live.**

**`completion_notes`** — WRITTEN BY: **only** `update()`'s rescue block (`:1247-1249`);
**not** reachable through the config allow-list. READ BY: the SPA completion/detail panels,
`comprehensiveReport`. Cleared to `null` by the client-side 3→2 revert. GATES: the SPA's
`notesRequired` check (client-side only). **Live but fragile.**

**`approval_notes`** — WRITTEN BY: `update()`'s rescue block; also read straight off the
request inside the model event (`ExtraWork.php:613`). READ BY: detail panel,
`comprehensiveReport`. **Live.**

**`original_language`** — WRITTEN BY: `ExtraWorkObserver::handleTranslation` via
`saveQuietly()` on create. READ BY: `HasTranslatableFields`. **Live.**

**`title_*`, `description_*`, `completion_notes_*`, `approval_notes_*` (16 cols),
`translate_meta`** — WRITTEN BY: `AutoTranslateJob`. READ BY: the model accessors — which
`transformModelData` then deliberately overrides. `$hidden` strips them from JSON.
**Live for non-admin consumers; invisible on the admin API.**

### The "who did it" strings — all `VARCHAR(100)`

**`created_by`** — WRITTEN BY: `store` (`"Name (Role)"`), `batchStore` (same).
READ BY: display; `getRelatedUsers()` (broken, §2.1); `applyUcbPermissions` (broken, §2.4);
`getAccessibleExtraWorks` (broken); `ExtraWorkObserver::handleTranslation:159`
(`User::find($extraWork->created_by)` — **also broken**, always null, so the language
fallback silently degrades to `'tr'`). DATA: `"B Amsterdam"`.
**Live as display; every attempt to use it as a user id fails.**

**`created_user_id`** (FK `users`) — WRITTEN BY: `store` (**always**, from the session),
`batchStore`. READ BY: `createdUser` relation → `created_user_name`. **This is the real
creator field.** **Live.**

**`requested_by`** — WRITTEN BY: `store` (from the session), and it is in the config
allow-list so a client may also set it. **Not written by `batchStore`.** READ BY: display,
`?requested_by=` filter, `comprehensiveReport`. DATA record 476: `"B Amsterdam"`. **Live.**

**`planed_by` / `started_by` / `completed_by` / `approved_by`** — WRITTEN BY: `update()`'s
auto-fill (session `"Name (Role)"`); also client-settable through the allow-list; `store`
passes them through if supplied. READ BY: display, the model's status-change comment
builder, `comprehensiveReport`. GATES: none. **Live.**

**`archive_approved_by` / `archive_rejected_by`** — WRITTEN BY: `approveArchive` /
`rejectArchive` (session), `update()`'s auto-fill, and **both are in the config allow-list**
so a client can PUT any string into them. **Live.**

**`archive_requested_by`** — WRITTEN BY: `update()`'s auto-fill only if the client sends a
truthy `archive_requested_at` (which is *not* in the allow-list, so the date itself is not
persisted by that path), plus `approveArchive`'s `?? $userInfo` back-fill.
DATA record 476: `"148"` — a bare user id, a format **no current code path produces**.
**INFERRED:** legacy data or an out-of-band write. See §4.

**`drafted_by`** — WRITTEN BY: `saveDraft` only, with the `role->name` format.
READ BY: `Employee/DashboardController` and the SPA draft panel. **Live, minor.**

### Dates — see §6 for the full treatment

**`created_at` / `updated_at` / `deleted_at`** — standard; `created_at` is in the config
allow-list, so a client can back-date a record on create or update.

### Hours and money

**`hours_planed`** (decimal 10,2) — WRITTEN BY: `PATCH /{id}/hours`, `update` (allow-list),
the plan modal. READ BY: `updateHours` response only. **Not used in any total, any invoice
or any report.** Near-dead: it is written and displayed, never calculated with.

**`hours_worked`** (decimal 8,2) — WRITTEN BY: `PATCH /{id}/hours`, `update`; cleared by
the client-side 3→2 revert. READ BY: `getRemainingHours()`, `comprehensiveReport`.
**Never used for money** — labour cost comes from `extra_work_employee_hours.total_cost`.
DATA record 476: `hours_worked: null` on an invoiced record with `total_hours: 0`.

**`invoice_id` / `invoice_date`** — WRITTEN BY: **only** `InvoiceController::addItem`
(`:617-621`) and nulled by `destroy`/`removeExtraWork`/`deleteItem`. The bulk path
`InvoiceController::store` (`:152`) writes **only** `status_id = 9` and leaves both NULL.
READ BY: **nothing.** Every read of "the invoice" goes through the `invoice()`
hasOneThrough on `invoice_items`, including the `?date_field=invoice_date` filter
(`:231-234`) and the `sort_by=invoice_date` sub-select (`:302-306`), both of which query
`invoices.invoice_date`. DATA: record 476, `status_id 9`, `"invoice_id": null,
"invoice_date": null`. **DEAD — written by one path, read by none.**

**`file_1`, `file_2`, `file_3`, `file_4`** (varchar 255) — WRITTEN BY: **nothing.**
`store`'s legacy branch reads request keys `file1`..`file4` (no underscore) and turns them
into `extra_works_attachments` rows; it never touches the columns. READ BY: nothing —
`grep -rn "file_1" app/` returns only `app/Models/ExtraWork.php`. They appear in
`config/base/extra-works.php:123` and `config/user/extra-works.php:95` as form fields only.
**DEAD.**

**`upload_is_required` / `notes_is_required`** — see §5. **DEAD in practice.**

**`user_id`** (FK `users`) — WRITTEN BY: **no code path I could find.** It is in the config
allow-list, so a client *could* set it, but neither `add.jsx` nor any controller sends it.
READ BY: the `user()` relation, the `user_name` appended attribute, and `$with`
(so it is eager-loaded on every single query of this model). DATA record 476:
`user_id: 148`, identical to `created_user_id`. **INFERRED: a legacy column, back-filled
from `created_user_id`.** See §4.

### Archive family

**`archive_requested_at`** — WRITTEN BY: `approveArchive`'s `?? now()` back-fill only.
Not in the config allow-list, so the `update` path cannot persist it even though it
triggers the `*_by` stamp. READ BY: `comprehensiveReport` (`:4807`, plus a
`worksWithArchiveRequest` filter at `:4905`), the SPA timeline. **Live but degenerate** —
it can only ever equal `archive_approved_at`.

**`archive_approved_at`** — WRITTEN BY: `approveArchive` (`now()`), nulled by
`rejectArchive`. READ BY: `?date_filter_type=archived`, `?date_field=archived_at`,
`sort_by=archive_approved_at` (the "Completed" grid's default sort,
`ExtraWorkCompletedGroupedView.jsx:292`), `comprehensiveReport`, the SPA timeline,
the `idx_archive_approved_at` index. **Live and load-bearing for reporting.**

**`archive_approval_notes`** — WRITTEN BY: `approveArchive`, `update`'s rescue block;
nulled by `rejectArchive`. READ BY: the model's status-8 comment arm, the SPA. **Live.**

**`archive_rejected_at` / `archive_rejected_by` / `archive_rejection_reason`** —
WRITTEN BY: `rejectArchive` (append semantics on the reason), nulled by `approveArchive`
and by the SPA's dead 5→4 revert. READ BY: the model's "Archief afgewezen" branch
(`ExtraWork.php:639-652`), five SPA components that render a "rejected" badge purely from
these three fields regardless of status. **Live — and they are the real rejection record;
status is not.**

### Draft family

**`draft_message` / `drafted_at` / `drafted_by`** — WRITTEN BY: `saveDraft`, cleared by
`clearDraft`. READ BY: `Employee/DashboardController`, the SPA. Not in the config
allow-list, so `update` cannot touch them. **Live, self-contained.**

### Group family

**`extra_work_group_id` / `group_sequence` / `group_total`** — WRITTEN BY: `batchStore`
only. Not in the config allow-list. READ BY: `buildQuery`'s group-aware status filter,
`transformModelData`'s `group.status_distribution`, `getGroupMembers`,
`bulkUpdateGroupStatus`, `bulkDeleteGroup`, `groupSiblings()`, the SPA group bar.
GATES: **`group_sequence == 1` makes a record a group header, which changes which rows a
status filter returns.** **Live.**

---

# 3. This area's connection map

## 3.1 Status — authoritative source and live counts

*DATA — `GET /admin/extra-works/meta/config` → `data.form_data.statuses_data`:*

```
1 new                 Nieuw                        #b5bf41  mdi:plus
2 in_progress         In behandeling               #f59e0b  mdi:watch
3 resolved            Interne goedkeuring          #16a34a  mdi:check
4 closed              Goedkeuring door de klant    #64748b  mdi:close
5 internal_approval   Interne goedkeuring          #8b5cf6  mdi:check-decagram
6 customer_approval   Klant goedkeuring            #06b6d4  mdi:account-check
7 invoiced_v2         Gefactureerd                 #059669  mdi:receipt
8 archived            Voltooid                     #044b29  mdi:check
9 invoiced            invoiced                     #044b29  mdi:check
```

*DATA — `GET /admin/extra-works?statuses={n}&per_page=1`, `data.pagination.total`:*
`1→19, 2→6, 3→1, 4→6, 5→0, 6→0, 7→0, 8→9, 9→37`.
(These are group-inflated; the true per-status counts from `/statistics` are
`1→18, 2→5, 3→1, 4→6, 8→9, 9→37`.)

*CODE — `app/Http/Controllers/Admin/ExtraWorksV2Controller.php:78-81*:
```php
$q->whereIn('status_id', [5, 6]); // Internal + Customer Approval
…
$q->where('status_id', 7);
```
— 5/6/7 belong to V2's schedule workflow.

## 3.2 Transition table — every path that changes `status_id`

| from → to | trigger | endpoint + payload | server ALSO stamps | now possible | now impossible |
|---|---|---|---|---|---|
| any → 2 | "Plan werk" (Extra Work) | `PUT /{id}` `{planed_start_at, planed_end_at, upload_is_required*, notes_is_required*, status_id:2, started_at:<now>, workers[], hours_planed?}` (`detail.jsx:906-925`) | `planed_by`, `planed_at=now()`, `started_by` (because `started_at` is truthy) | Complete button; revert to 1 | delete for non-admins (`destroy` guard); bulk delete |
| any → 2 | "Start werk" (Melding) | `PUT /{id}` `{status_id:2}` (`detail.jsx:974-978`) | `planed_by`, `planed_at=now()` — **yes, even for a Melding that was never planned** | Approve button | as above |
| any → 3 | "Voltooien" | `PUT /{id}` `{completed_at:<now>, status_id:3, completion_notes?}` (`ExtraWorkCompletionModal.jsx:216-220`); draft photos posted first to `POST /{id}/attachments` with `is_draft:1` | `completed_by` | Approve button; revert to 2 | — |
| any → 4 | "Goedkeuren" | `PUT /{id}` `{status_id:4, approval_notes?}` (`detail.jsx:988-993`) | `approved_by`, `approved_at=now()`, **all `is_draft` attachments → published** | Archive approve / Archive reject; revert to 3 | — |
| any → 8 | "Archief goedkeuren" | `POST /{id}/archive/approve` `{note}` | `archive_approved_at=now()`, `archive_approved_by`, `archive_approval_notes`, back-fills `archive_requested_at/_by`, nulls all three `archive_rejected_*` | appears in `InvoiceController::pendingExtraWorks`; can be added to an invoice | the SPA renders no workflow buttons at status 8 |
| 8 → 9 | invoice created | `POST /admin/invoices` (`InvoiceController:152`) or `POST /admin/invoices/{id}/items` (`:617`) | bulk path: **nothing else**. item path: `invoice_id`, `invoice_date=now()` | — | hidden from the default list (`status_id != 9`); still deletable by an admin |
| 9 → 8 | invoice/item deleted | `DELETE /admin/invoices/{id}` (`:265-271`), `DELETE /{invoiceId}/extra-works/{id}` (`:723-727`), `DELETE /{id}/items/{itemId}` (`:784-789`) | `invoice_id=null`, `invoice_date=null` | re-invoiceable | — |
| 4/8 → 3 (or any) | "Archief afwijzen" | `POST /{id}/archive/reject` `{rejection_reason, status_id, images[]}` | `archive_rejected_at=now()`, `archive_rejected_by`, **appends** to `archive_rejection_reason`, nulls the three `archive_approved_*` | the SPA shows a red "rejected" badge from the fields, not the status | — |
| n → n-1 | "Terugdraaien" | `PUT /{id}` `{status_id: previous, <fields>: null}` (`detail.jsx:1004-1050`) | **re-stamps** per the auto-fill table — see §4 below | — | — |
| N records, s → t | group bar button | `PUT /groups/{groupId}/status` `{source_status_id, target_status_id}` | **NOTHING** — mass update, no events, no stamps, no comments | — | — |
| any | direct | `PUT /{id}/status` `{status_id}` | **NOTHING** | — | — |

`*` — `upload_is_required` / `notes_is_required` are in that plan payload but are silently
dropped (§2.3).

## 3.3 Revert — what is undone, what is cleared, what blocks it

*CODE — `frontend/src/pages/finalosius/extra-works/detail.jsx:1004-1050*:

| current status | target | nulled by the client |
|---|---|---|
| 2 | 1 | `started_at`, `started_by` |
| 3 | 2 | `completed_at`, `completed_by`, `completion_notes`, `hours_worked` |
| 4 | 3 | `approved_at`, `approved_by`, `approval_notes` |
| 5 | 4 | `archive_rejected_at`, `archive_rejected_by`, `archive_rejection_reason` — **unreachable, nothing sets status 5** |
| anything else | 1 | nothing (`previousStatus` stays at its initialiser `1`) |

**What blocks it: nothing.** No backend guard, no permission beyond
`extra_works,update`, no status precondition. The button is hidden for `isCustomer` and
rendered only at statuses 2, 3, 4, 5 — a UI decision, not a rule.

**What is NOT undone** — and this is the important part:

- **4 → 3 re-stamps `completed_at = now()` and `completed_by = <the reverting user>`,**
  because the payload contains `status_id: 3` and no `completed_at` key, which is exactly
  the auto-fill trigger at `ExtraWorksController.php:1208-1216`. The original completion
  time is lost.
- **2 → 1 re-stamps `planed_by` and `planed_at = now()`** is *not* triggered (target status
  is 1, and no `planed_*` key is sent) — but **1 → 2 always re-stamps `planed_at`**, so a
  revert-and-redo cycle overwrites the original planning time.
- Draft attachments published by the 4-approval are **never un-published**.
  `is_draft` is a one-way flip.
- `archive_rejection_reason` accumulates forever; nothing ever truncates it except the
  dead 5 → 4 branch.
- Nothing reverts the invoice link; that is the invoice controller's job.

## 3.4 The invoicing junction

```
extra_works (status 8)
    └── InvoiceController::pendingExtraWorks   ← BROKEN (see below)
    └── POST /admin/invoices            → invoice_items row + status 9 (invoice_id NOT set)
    └── POST /admin/invoices/{id}/items → invoice_items row + status 9 + invoice_id + invoice_date
invoice_items.extra_work_id → the ONLY real link (ExtraWork::invoice() hasOneThrough)
    amount    = $work->total_products_cost   // products only — LABOUR IS NOT INVOICED
    tax_rate  = 0.21                          // hard-coded
    description = $work->title
    quantity, unit_name from the FIRST product only
```

*CODE — `app/Http/Controllers/Admin/InvoiceController.php:143-152*:
```php
'amount' => $work->total_products_cost ?? 0, // Only products, not labor
'tax_rate' => 0.21, // Default 21% KDV
…
$work->update(['status_id' => 9]);
```

**Money-meets-vocabulary flag:** their **Product** (`extra_work_products`, sourced from
`customer_products`) is our **Service**. The invoice amount is the sum of those product
lines *excluding* VAT, and it **excludes all labour** even though the record computes
`total_labor_cost` and `priceBreakdown` presents labour as part of the grand total. Two
different answers to "what is this work worth" ship from the same record.

**`pendingExtraWorks` is broken.** *CODE — `InvoiceController.php:307-320*:
```php
$query = ExtraWork::where('status_id', 8)->whereDoesntHave('invoiceItem');
if ($request->has('customer_id')) { $query->where('customer_id', $request->customer_id); }
…
$extraWorks = $query->with(['customer', 'building', 'status'])…
```
`customer_id` was dropped from `extra_works` in October 2025, and `ExtraWork` has no
`customer()` or `building()` relation.
*DATA:* `GET /admin/invoices/pending-extra-works` → `{"success":false,…,"message":"Internal
server error"}`; with `?customer_id=2054` → `{"success":false,"error":{"code":"DB_ERROR"},…}`.
**The canonical "what can I invoice" endpoint returns 500.** How the operator actually
selects works for an invoice is a question for the invoicing agent (§4).

## 3.5 Notification / event fan-out

```
ExtraWork::created  ──► addSystemComment('created')  ──► ExtraWorkCommentRead rows
                    │                                └─► broadcast ExtraWorkCommentPosted
                    └► FCM  "extra_work_created" | "melding_created"  (RecipientDeterminer)

ExtraWork::updated (status_id dirty, unless skipStatusComment)
                    ──► addSystemComment('status_change')
                    └──► broadcast ExtraWorkStatusChanged

ExtraWork::updated (any other field dirty)
                    ──► broadcast ExtraWorkUpdated
                    └──► FCM  "extra_work_updated" | "melding_updated"

updateStatus (endpoint)  ──► its own FCM fan-out: UCB holders + assignees
                              + same-department active users + role-slug 'admin'

ExtraWorkObserver::created/updated  ──► extra_work_activities  +  AutoTranslateJob
```

**Every one of these is skipped by the four mass-update endpoints** (§2.4) and by
`saveQuietly()`.

## 3.6 The completion-requirement graph

```
ExtraWorkPlanModal            detail.jsx:913-914          PUT /admin/extra-works/{id}
  uploadRequired checkbox ──► upload_is_required ────────►  ✗ dropped: not in
  notesRequired  checkbox ──► notes_is_required  ────────►    config['fields'] allow-list
                                                              and no rescue block

extra_works.upload_is_required / notes_is_required   (default false, 0/78 rows true)
        │
        ├──► ExtraWorkCompletionModal.jsx:59-60,169-177   ← the ONLY enforcement
        ├──► ExtraWorkKanbanView.jsx:502-505              ← the only other enforcement
        ├──► ExtraWorkPlanModal.jsx:105-106               ← re-displays the stored value
        ├──► ExtraWorksController:4819-4820               ← echoed in comprehensiveReport
        └──► portal_extra_works VIEW                      ← read by nothing in app/
```

## 3.7 What points at `extra_works` from outside

| table / object | column | on delete |
|---|---|---|
| `extra_work_customer_building` | `extra_work_id` | cascade (`2025_10_18_040937:23`) |
| `extra_work_activities` | `extra_work_id` | (`2025_10_15_000001:30`) |
| `extrawork_worker_assignments` | `extra_work_id` | (`2025_10_27_155648:23`) |
| `invoice_items` | `extra_work_id` | **restrict** (`2025_11_27_131838:33`) |
| `messages`, `internal_messages` | `extra_work_id` | (`2025_11_05_135358`, `2025_11_08_093611`) |
| `extra_works_v2_schedules` | `legacy_extra_work_id` | tracking only |
| `portal_extra_works` (SQL VIEW) | reads ~40 columns | **no PHP reader** |
| `extra_work_products`, `extra_work_comments`, `extra_works_attachments`, `extrawork_assignments`, `extra_work_employee_hours`, `ticket_tasks` | `extra_work_id` | — |

Note `invoice_items` is `ON DELETE RESTRICT`, but `ExtraWork` uses `SoftDeletes`, so
`destroy` never hits that constraint — an invoiced record can be soft-deleted by an admin
and the invoice line survives, pointing at a `deleted_at`-flagged row.

---

# 4. Dates — the complete map, and the `now()` question

| column | cast | written by | read by | if null | gates |
|---|---|---|---|---|---|
| `requested_at` | datetime | `store` (client, `add.jsx` sends `new Date()`), `batchStore` (**the scheduled slot, not now**), `update` | `?date_field=requested_at`; the `COALESCE` fallback in all three compound aliases; `sort` not allowed; `comprehensiveReport`; `idx_requested_at`, `idx_type_status_requested` | the COALESCE aliases fall through to their primary field only, so the row drops out of the filtered range entirely | decides list membership for the status 1/2/3/4 date filters |
| `customer_start_date` | **date** | `store`/`update` (allow-list), `batchStore` (`$scheduleDateTime->toDateString()`) | `?date_field=customer_start_date`, `customer_start_or_requested` COALESCE, `Admin/DashboardController`, `WeeklyController`, `idx_customer_start_date` | falls back to `requested_at` in the COALESCE alias | the status-1 default date filter |
| `deadline_at` | datetime | `store`/`update` (allow-list), `batchStore` (`scheduleDate 20:59:00`) | **the only date compared to the clock** — see below; `?date_field=deadline_at`; `sort_by=deadline_at`; the no-`date_field` fallback OR | the overdue queries add `whereNotNull('deadline_at')`, so it is simply excluded | **"overdue" and "priority today" on six dashboards** |
| `planed_at` | datetime | `update` auto-fill (`now()` when `status_id==2` and the key is absent); allow-list | six dashboard controllers (`whereDate('planed_at', $today)`); model status-2 comment arm | `Admin/DashboardController:242` and `CustomerManager:251` fall back to `deadline_at` | the "priority today" bucket for Extra Works |
| `planed_start_at` | datetime | `update` (allow-list), plan modal | `?date_field=planed_start_at`; `planed_or_requested` COALESCE; `sort_by=date`/`planed_start_at`; `idx_planed_start_at`, `idx_type_status_planed`; `comprehensiveReport` | COALESCE → `requested_at` | the **default sort key** for `sort_by=date` |
| `planed_end_at` | datetime | `update` (allow-list), plan modal | display, `comprehensiveReport`'s `planed_duration_hours` | duration null | — |
| `started_at` | datetime | `update` (allow-list); plan modal sends `new Date()` | `WeeklyController`, `comprehensiveReport`, observer date log | — | — |
| `completed_at` | datetime | `update` auto-fill (`now()` when `status_id==3`); allow-list; nulled by the client-side 3→2 revert | `comprehensiveReport`, `InvoiceController::pendingExtraWorks`'s `orderBy` (in the broken endpoint), observer date log | — | — |
| `approved_at` | datetime | `update` auto-fill (`now()` when `status_id==4`); allow-list; nulled by the 4→3 revert | **`is_approved` / `is_pending` accessors and the `approved`/`pending` scopes**; `?date_field=approved_at`; `approved_or_requested` and `approved_at_or_planed` COALESCE; `sort_by=approved_at`; `idx_approved_at` | `is_approved:false`, `is_pending:true` | the only "approved yes/no" signal that is independent of `status_id` |
| `archive_requested_at` | datetime | `approveArchive` back-fill only | `comprehensiveReport` (+ a `worksWithArchiveRequest` count), SPA timeline | that count is 0 | — |
| `archive_approved_at` | datetime | `approveArchive` (`now()`); nulled by `rejectArchive` | `?date_filter_type=archived`; `?date_field=archived_at`; **`sort_by=archive_approved_at`, the Completed grid's default sort**; `comprehensiveReport`; `idx_archive_approved_at` | the row sorts last / drops out of an archived-date range | the "Voltooid" report period |
| `archive_rejected_at` | datetime | `rejectArchive` (`now()`); nulled by `approveArchive` and the dead 5→4 revert | the model's "Archief afgewezen" comment branch; **five SPA components render a rejected badge from it, ignoring status** | no badge | the visual "this was rejected" state |
| `drafted_at` | datetime | `saveDraft` (`now()`), nulled by `clearDraft` | Employee dashboard, SPA | — | — |
| `invoice_date` | **date** | `InvoiceController::addItem` only; nulled on removal | **nothing** | — | **DEAD** |
| `created_at` | datetime | Eloquent; **also in the config allow-list, so a client can set it** | `?date_filter_type=created`; `?date_field=created_at`; **default sort**; the model's status-1 comment arm; `comprehensiveReport` | — | default list order |
| `updated_at` | datetime | Eloquent (skipped by `saveQuietly`) | display | — | — |
| `deleted_at` | datetime | `SoftDeletes` | the global scope | — | hides the row everywhere |

## Does anything compare a date on this record to `now()`?

`grep -n "isPast\|diffInDays\|whereDate\|Carbon::now\|today()"` over
`app/Http/Controllers/Admin/ExtraWorksController.php`, `app/Models/ExtraWork.php` and
`app/Services/ExtraWorkService.php` → **no matches.** The Extra Work area itself never
looks at the clock.

Outside it, exactly one column is compared to the clock — **`deadline_at`** (with
`planed_at` as an Extra Work preference for "today"):

*CODE — `app/Http/Controllers/WorkPlan/WeeklyController.php:380-386* (and the identical
Extra Work block at `:455-461`):
```php
$today = Carbon::now()->format('Y-m-d');
$meldingsQuery = ExtraWork::where('type', 2)
    ->where('status_id', '<', 8)          // Not archived
    ->where('deadline_at', '<', $today)   // Deadline passed
    ->whereNotNull('deadline_at');
```

*CODE — `app/Http/Controllers/Admin/DashboardController.php:228-244*:
```php
$today = Carbon::today();
$meldingQuery = ExtraWork::where('type', 2)->whereDate('deadline_at', $today);
…
$extraWorkQuery = ExtraWork::where(fn($q) => $q->where('type',1)->orWhereNull('type'))
    ->where(function($q) use ($today) {
        $q->whereDate('planed_at', $today)
          ->orWhere(fn($sq) => $sq->whereNull('planed_at')->whereDate('deadline_at', $today));
    });
```

Same pattern in `CustomerManager/DashboardController.php:245-285` (which uses
`->where('deadline_at', '<', $now)` for its overdue bucket),
`CustomerEmployee/DashboardController.php:170-231`, `Customer/DashboardController.php:328`,
`LocationManager`, `LocationChef`, `ContactPerson` and `Employee` dashboards.

Note the overdue rule `status_id < 8`: because 5, 6 and 7 sort below 8, a record in any of
them would count as "not archived". Since no v1 record uses them, this is currently inert.

**Nothing ever compares `customer_start_date`, `planed_start_at`, `planed_end_at`,
`requested_at`, `started_at`, `completed_at`, `approved_at` or any `archive_*` date to the
current time.** There is no ageing, no SLA, no escalation, no auto-close, no reminder.
Combined with the absent scheduler (§2.1), **an Extra Work never changes by itself.**

---

# 5. Completion requirements — the proof, in full

**Claim: `upload_is_required` and `notes_is_required` are frontend-only, and in this
deployment they are unreachable even from the frontend.**

### (a) The whole backend footprint of the two names

```
database/migrations/2025_10_11_195020_create_ticket_extrawork_products_table.php:46-47
    → a DIFFERENT table (ticket_extrawork_products)
database/migrations/2025_11_10_192031_fix_portal_extra_works_view_status_names.php:49,50,153,154
database/migrations/2025_12_09_031108_fix_portal_extra_works_view_category_name.php:50,51,148,149
    → columns selected into the portal_extra_works VIEW; no PHP reads that view
app/Http/Controllers/Admin/ExtraWorksController.php:4819-4820
    'upload_is_required' => $work->upload_is_required,
    'notes_is_required'  => $work->notes_is_required,
    → comprehensiveReport payload, display only
app/Models/ExtraWork.php:26-27   ($fillable)
app/Models/ExtraWork.php:94-95   ($casts)
```

**Not once inside an `if`, a `Validator` rule, a `where`, or a `throw`.**

### (b) The completion endpoint's full validation block

The completion action is `PUT /admin/extra-works/{id}`
(*CODE — `frontend/src/pages/finalosius/extra-works/modals/ExtraWorkCompletionModal.jsx:215-220*):

```js
// Step 3: Mark as completed - status 3 = Pending Approval
const response = await apiClient.put(`/admin/extra-works/${extraWork.id}`, {
  completed_at: new Date().toISOString(),
  status_id: 3, // Pending Approval
  completion_notes: completionNotes.trim() || undefined,
});
```

`ExtraWorksController::update()` performs **no `$request->validate()` of its own** — grep
the method body (`:923-1348`): there is no `validate` call. It delegates to
`EntityController::update()`, whose entire validation is
(*CODE — `app/Http/Controllers/Base/EntityController.php:1016-1023*):

```php
// Validate request
$rules = $this->getValidationRules('update', $id, $request->all());
$validator = Validator::make($request->all(), $rules);

if ($validator->fails()) {
    $errors = $validator->errors();
    $message = $this->buildValidationMessage($errors);
    return $this->validationError($errors, $message);
}
```

and `getValidationRules` (*`:579-612`*) reads only
`$fieldConfig['validation'][$action]` / `['validation']['default']`. Neither
`config/base/extra-works.php` nor `config/admin/extra-works.php` contains a single
`validation` key for any field.

**`$rules` is `[]`. The validator always passes.**

### (c) What a request must contain to complete a work

**Nothing.** `PUT /api/admin/extra-works/{id}` with body `{"status_id": 3}` and a bearer
token holding `extra_works,update` will:

- set `status_id = 3`,
- stamp `completed_by = "Name (Role)"`,
- stamp `completed_at = now()` (because `completed_at` was not in the body),
- fire the status-change comment, broadcast and FCM,

with **no completion notes, no photo, no hours** — regardless of what
`upload_is_required` / `notes_is_required` say.

### (d) And they cannot be turned on anyway

The plan modal sends them (*CODE — `detail.jsx:906-916*):

```js
const updatePayload = {
  planed_start_at: planData.planedStartAt,
  planed_end_at: planData.planedEndAt,
  upload_is_required: planData.uploadRequired,
  notes_is_required: planData.notesRequired,
  status_id: 2, …
```

but `EntityController::update` does `$data = $request->only($fillableFields)`
(*`:1043`*), and neither name is among the 39 config field keys (§2.3). The `autoFields`
rescue block covers four note columns and none of these. So the toggle is a no-op.

**DATA confirming:** across statuses 1, 2, 3, 4, 8 and 9 — 78 records in total — **zero**
have `upload_is_required` or `notes_is_required` true.

### (e) Where the enforcement actually lives

*CODE — `ExtraWorkCompletionModal.jsx:167-177*:
```js
if (notesRequired && !completionNotes.trim()) { enqueueSnackbar(…); return; }
if (uploadRequired && attachedFiles.length === 0) { enqueueSnackbar(…); return; }
```
*CODE — `ExtraWorkKanbanView.jsx:502-505*:
```js
if (extraWork.notes_is_required && !extraWork.completion_notes) { … }
if (extraWork.upload_is_required && (!extraWork.attachments_count || extraWork.attachments_count === 0)) { … }
```

Two client-side `if`s. That is the entire enforcement surface of the feature.

---

# 6. ExtraWorkV2 — where the LOGIC differs (v2 section, context only)

V2 is a **separate table** (`extra_works_v2`), a separate model, a separate controller
(`ExtraWorksV2Controller`, routes under `/api/admin/extra-works-v2`) — but it shares the
`extra_works,*` UCB permission module and the same `t_ticket_status` lookup table.

The logic differences that matter:

1. **One definition, many occurrences.** v1 = one row per occurrence (a "week 44" batch is
   N rows tied by `extra_work_group_id`). V2 = one `extra_works_v2` row carrying a
   *recurrence rule* (`times_per_year`, `preferred_day_type`, `preferred_day_of_week`,
   `preferred_time`, `duration_hours`, `start_date`/`end_date`) plus N
   `extra_work_v2_schedules` rows. **The status that moves is the schedule's, not the
   parent's** — the parent aggregates (`new_schedules_count`, `planned_schedules_count`,
   `completed_schedules_count`, `approval_schedules_count`, `invoiced_schedules_count`).
   *DATA — `GET /admin/extra-works-v2?per_page=1`:* record 117 has `schedules_count: 10`,
   `new_schedules_count: 10`, `status_id: 1`.
2. **It uses statuses 5, 6 and 7 — the ones v1 never touches.**
   *CODE — `ExtraWorksV2Controller.php:78-81`* filters `whereIn('status_id',[5,6])` for
   "Internal + Customer Approval" and `where('status_id', 7)` for invoiced;
   `:3857` and `:5249` write `status_id => 7`. Its ladder is
   `1 new → 2 planned → 3 completed → 5 internal approval → 6 customer approval → 7 invoiced`.
   `:4219` even validates a *rejection target*: `'target_status_id' => 'nullable|integer|in:2,3,5'`
   — **V2 has the transition constraint that v1 lacks.**
3. **Money is on the record.** V2 carries `price_type`, `fixed_price`, `billing_type`,
   `billing_day`, `invoice_date`, `billing_start_date`, `billing_end_date`,
   `installment_count`, `installment_interval`, `first_installment_date`,
   `estimated_cost`, `actual_cost` — plus a computed `billing_month_count` accessor that
   counts calendar months between the two billing dates. v1 has none of this; v1's money
   is entirely derived from child rows at read time.
   *DATA — record 117:* `price_type: "fixed"`, `fixed_price: "1500.00"`,
   `billing_type: "on_completion"`.
4. **Continuous work is a first-class mode** (`is_continuous`, `continuous_type` ∈
   `open_ended|fixed_term`, `recording_frequency` ∈ `daily|weekly|biweekly|monthly`,
   `contract_duration_months`, `total_budget_hours`, `total_recorded_hours`,
   `last_recorded_date`). v1 has no concept of an open-ended job.
5. **Customer and building are direct FKs** (`customer_id`, `building_id`, nullable, with a
   `customer_buildings` many-to-many *in addition*). v1 has only the junction table —
   its direct columns were dropped, which is the root cause of the two broken endpoints in §3.4.
6. **`created_by` / `updated_by` / `assigned_to` are real integer FKs to `users`**
   (*migration `2026_01_26_000001:65-70`*), not the `VARCHAR(100)` display strings v1 uses.
   Every v1 bug that stems from comparing a name to an id (§2.1, §2.4) is structurally
   impossible in V2.
7. **A `deleting` model hook with real cleanup**: V2 deletes the matching
   `WorkerPlannedHour` and `WorkerApprovedHour` rows (source type `continuous_work` or
   `extra_work`) on delete (*`ExtraWorkV2.php:168-190`*). v1 has no such hook — deleting a
   v1 record orphans nothing but cleans nothing either.
8. **No `type` flag, no Melding.** Meldingen have no V2 equivalent; they stay on v1.
9. **Labour hours moved out** to the `worker_planned_hours` / `worker_approved_hours`
   system with a submit → approve → revert cycle; v1's labour lives in
   `extra_work_employee_hours` with no approval state.
10. **A one-shot data migration exists** (`2026_01_26_100000_migrate_extra_works_to_v2.php`):
    each v1 group becomes one V2 record with one schedule per member; each ungrouped v1
    record becomes one V2 record with one schedule. It sets
    `times_per_year = <group member count>`. v1 rows are **not** deleted or flagged —
    `extra_work_v2_schedules.legacy_extra_work_id` is the only back-pointer, and both
    systems remain live and independently writable.

---

# COULD NOT DETERMINE

1. **The true DDL of ~24 base columns.** There is no `CREATE TABLE extra_works` migration
   anywhere in this repository, and `database/sql/` contains only
   `cascade_delete_users_fk.sql` and `create_products_system.sql`. For `title`,
   `description`, `status_id`, `priority_id`, `approval_notes`, `upload_is_required`,
   `notes_is_required`, `planed_at`, `started_at`, `completed_at`, `requested_at`,
   `approved_at`, `deadline_at`, `customer_department_id`, `customer_works_type_id`,
   `is_customer_work`, `user_id`, `invoice_id`, `invoice_date` and the whole `archive_*`
   family I can state the cast and the observed values but **not the true nullability,
   default or column type**. *To close:* `SHOW CREATE TABLE extra_works;` on the reference
   database, or the original dump that predates the migration set.

2. **Who wrote `archive_requested_by = "148"`.** DATA record 476 carries a bare numeric
   user id there, while every live code path writes `"Name (Role)"` or back-fills from the
   same. `grep -rn "archive_requested_by" app/` returns only `ExtraWorksController` (two
   sites) and the model. **INFERRED:** legacy data from before the string-format
   convention, or a raw SQL/mobile write outside this repo. *To close:* `SELECT DISTINCT
   archive_requested_by FROM extra_works;` to see whether the numeric form is confined to a
   date range, plus a search of the mobile/websocket codebases.

3. **Who writes `extra_works.user_id`.** Nothing in `app/` sets it and the SPA create form
   does not send it, yet record 476 has `user_id = 148 = created_user_id`. **INFERRED:** a
   legacy column back-filled from `created_user_id`. *To close:* `SELECT COUNT(*) FROM
   extra_works WHERE user_id IS NOT NULL AND user_id <> created_user_id;` — if that is 0,
   it is a back-fill and the column is dead.

4. **How an operator actually picks works for an invoice.** The documented endpoint
   `GET /admin/invoices/pending-extra-works` returns 500 (DATA, §3.4), yet 37 records sit
   at status 9. So *some* path reaches `POST /admin/invoices` with `extra_work_ids`.
   *To close:* this is Agent-invoicing territory — read the SPA's invoice-creation page and
   `InvoiceController::createFromInvoiceableItems` / `getInvoiceableItemsForCustomer`
   (`:1054`, `:1343`) and the `invoiceable_items` table. **Handoff.**

5. **Whether the `sub` context is ever routed to for extra-works.**
   `config/sub/extra-works.php` carries ~21 real `validation` blocks that the admin context
   never loads. `EntityController::index/store/update` set `$this->context` from a
   `?context=` request parameter (`:855-858`, `:910-913`) — which means **a client may be
   able to switch the controller into the `sub` config at will, changing both the validation
   rules and the field allow-list mid-flight**. I did not test this (it would require a
   write). *To close:* a GET with `?context=sub` on the list endpoint and a diff of the
   returned `meta/config`, then a read of `config/sub/extra-works.php`'s `fields` block.

6. **Whether `PUT /{id}` really accepts a body with no validation.** I proved the rule array
   is empty by reading the config and the rule builder, and I proved the request shape the
   SPA sends. I did **not** issue a PUT — writes are out of bounds. The claim is CODE-level,
   not DATA-level. *To close:* one POST/PUT against a scratch record on a non-production
   copy.

7. **`RecipientDeterminer::getRecipientsForExtraWork` logic.** I read every call site but
   not `app/Services/Notification/RecipientDeterminer.php` itself, so the exact FCM audience
   for created/updated (as opposed to the hand-rolled audience in `updateStatus`, which I
   did read) is unverified.

8. **The `portal_extra_works` view's consumer.** The view is created and twice re-created by
   migrations and selects ~40 columns including both requirement flags, but
   `grep -rn "portal_extra_works" app/` returns nothing. *To close:* search the mobile app
   and the `websocket-server/` directory, or ask whether an external customer portal reads
   the database directly.

9. **`t_ticket_status` full DDL.** I have every row's `id`, `slug`, `label` (nl), `color` and
   `icon` from `meta/config`, and the English labels from `/statistics`. I did not see the
   `sort_order` values (which is why 8 is listed before 7), nor the `label_tr`/`label_bg`
   contents. *To close:* `SELECT * FROM t_ticket_status ORDER BY sort_order;`

10. **Whether statuses 5/6/7 have ever held a v1 row.** Live counts are 0, but soft-deleted
    rows are excluded by the global scope. *To close:*
    `SELECT status_id, COUNT(*) FROM extra_works GROUP BY status_id;` including
    `deleted_at IS NOT NULL`.

## Stopping point

I read the ExtraWork model in full (all 965 lines), the entire route table for
`/extra-works`, `/meldings` and `/extra-works/{id}/employee-hours`, every relevant
migration, `EntityController`'s config/validation/CRUD machinery, all four entity config
files, the observer, the provider registration, `routes/console.php`, and in
`ExtraWorksController` (6434 lines) the following methods in full: `buildQuery`,
`applyUcbPermissions`, `applyAdditionalScopes`, `transformModelData`, `store`, `update`,
`show`, `updateStatus`, `approveArchive`, `rejectArchive`, `convertToExtraWork`,
`convertToMelding`, `destroy`, `statistics`, `priceBreakdown`, `updateHours`,
`calculateFinancialSummary`, `saveDraft`, `clearDraft`, `batchStore`,
`bulkUpdateGroupStatus`, `bulkDelete`, `bulkDeleteGroup`, `bulkConvertToMelding`,
`addAttachment`, `deleteAttachment`, and the head of `getAccessibleExtraWorks`.

I did **not** read in full: `dashboard` (`:3358-3562`), `weeklyReport` (`:4024-4253`),
`comprehensiveReport` (`:4406-5069`, I read only its field-emission block and its docblock),
`meldingReport` (`:5069-5633`), the comment/product/employee/worker CRUD methods
(`:1720-2633`, which delegate to `ExtraWorkService`), and `ExtraWorkService.php` beyond its
method index. Those are reporting and child-collection surfaces; none of them writes
`extra_works` columns, which is why they were the ones I traded away. If a later agent needs
the report shapes, that is where to start.
