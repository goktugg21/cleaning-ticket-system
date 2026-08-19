# A6 - People, Assignment, Permissions (Osius reference system)

Scope: Employee / User / Role / RolePermission / UserGranularPermission /
UserCustomerBuildingPermission / Module / UserModuleOverride; the coordinator-vs-worker
model; **which role may perform each extra-work transition and each invoice action**;
what a customer user can see of a work.

Read-only investigation. Backend `/tmp/osius-ref/backend`, frontend `/tmp/osius-ref/frontend`,
live GETs against dev-api via the wrapper. Personal data is redacted to ids/roles.

Evidence labels: **CODE** = file:line I read; **DATA** = endpoint I called + values returned;
**INFERRED** = reasoning, stated as such.

---

# 1. PLAIN-ENGLISH LOGIC

## 1.1 There is one real permission check in this system, and it only knows your role

Every protected route carries a middleware alias called `ucb.permission:<module>,<action>`.
The name says "user-customer-building". **It does not look at user-customer-building data
at all.** It does exactly three things: is there a logged-in user; map the action word to a
bit; ask "does this user's `role_id` have that bit for that module slug in the
`role_permissions` table". Pass or 403. It never narrows a query, never looks at which
customer or building the record belongs to, never looks at the user's personal overrides,
never looks at the granular permission tables.

So the effective rule for the whole application is:

> **What you may DO is decided by your role alone. What you SEE is decided, separately and
> only on some endpoints, by code inside the controller.**

There are no Laravel Policies and no Gates anywhere in the codebase. There is no state
machine object for extra works. Authorisation is: this one role-only middleware, plus an
`admin.only` middleware (`role_id === 1`) used on about a dozen routes, plus roughly eight
hand-written `if ($user->role_id != 1)` lines scattered through controllers.

## 1.2 Four permission systems exist. Three of them are decorative.

| System | Table | Written by | Enforced anywhere? |
|---|---|---|---|
| Role permissions (bitwise) | `role_permissions` | (no UI found; seeded/DB) | **YES** - the only real gate |
| User module overrides | `user_module_overrides` | `POST /admin/users/{id}/module-overrides` | **NO** - never read by any gate |
| Granular permissions (tabs/components/actions) | `user_granular_permissions`, `role_permission_templates` | admin CRUD screens | **NO** - served to the SPA as UI hints |
| UCB customer/building grants | `user_customer_building_permissions` | `POST /admin/users/{id}/ucb-permissions/bulk-assign` | **PARTLY** - four controllers use it for row filtering; the middleware ignores it |

This is the single most important fact in this report. An administrator can open a user,
see a permissions screen, tick boxes, save, get a success message - and change nothing about
what that user can do through the API. The live system already has such rows: user 147
(location_chef) has a module override restricting `extra_works` to view+list+create+update
(mask 15) while their role grants mask 63; user 153 (employee) has an override restricting
`extra_works` to view+list (mask 3) while their role grants **255 - everything**. The
override loses, silently, because nothing consults it.

## 1.3 The bit meanings disagree between two files

`RolePermission` (the table that is actually enforced) defines
`32=export, 64=import, 128=admin`. `PermissionService` and `UserModuleOverride` define
`32=restore, 64=export, 128=manage`. Every screen and every API response that renders a
role mask into words uses `PermissionService`, so a role holding *export* is displayed as
"restore", *import* is displayed as "export", and *admin* is displayed as "manage". The
permission label an operator reads is not the permission the middleware enforces.

## 1.4 Roles

Eight roles exist. Three of them (customer_employee, customer_manager, contact_person) have
no users at all in the live system.

| id | slug | level | role type | live users |
|---|---|---|---|---|
| 1 | admin | 100 | Admin | 6 |
| 2 | customer | 1 | Customer | 6 |
| 3 | customer_employee | 2 | Customer | 0 |
| 4 | employee | 2 | Employee | 4 |
| 5 | location_manager | 3 | Employee | 2 |
| 6 | location_chef | 2 | Employee | 1 |
| 7 | customer_manager | 3 | Customer | 0 |
| 8 | contact_person | 2 | Customer | 0 |

`level` is written and displayed but no code ever compares two levels. It does not stop a
lower role granting a higher one (see 1.7).

## 1.5 The live role-permission matrix

This is the real, enforced authorisation table, pulled from the running system.

| module slug | admin(1) | customer(2) | employee(4) | loc.manager(5) | loc.chef(6) |
|---|---|---|---|---|---|
| **extra_works** | 255 | **31** | **255** | 127 | 63 |
| **melding** | 255 | 15 | 55 | 127 | 55 |
| **invoices** | **31** | *(absent)* | *(absent)* | *(absent)* | *(absent)* |
| customers | 255 | 3 | 17 | 23 | 17 |
| buildings | 255 | 2 | 23 | 31 | 23 |
| contacts | 255 | 2 | 17 | 23 | 17 |
| employees | 255 | *(absent)* | *(absent)* | 31 | 19 |
| users | 255 | *(absent)* | *(absent)* | **23** | *(absent)* |
| products | 255 | 3 | *(absent)* | *(absent)* | *(absent)* |
| reports | *(absent)* | **255** | *(absent)* | *(absent)* | *(absent)* |
| work-plan | *(absent)* | 255 | *(absent)* | *(absent)* | *(absent)* |

Bits: 1=view 2=list 4=create 8=update 16=delete 32=export 64=import 128=admin.
An absent row means `roleHasPermission` returns false, i.e. hard 403.

Read the consequences straight off that table:

- **Only the admin role can touch invoices at all.** Nobody else has an `invoices` row, so
  every invoice route 403s for every other role. Invoicing is a single-role feature.
- **The employee role holds 255 on extra_works** - view, list, create, update, delete and
  every high bit. An "employee" is, on extra works, as powerful as an admin.
- **The customer role holds 31 on extra_works** - including update (8) and delete (16). A
  customer user can change any extra work's status, edit it, add and delete its products and
  its employee-hour rows.
- The admin role has **no** `reports` row and **no** `work-plan` row, while the customer role
  has 255 on both. If the reports routes were gated, an admin would be denied and a customer
  allowed. They are not gated at all (see 1.8), so everyone gets them.

## 1.6 Extra work transitions are not a state machine, and they are not role-aware

The extra-work lifecycle in the UI is: 1 New -> 2 In behandeling -> 3 Interne goedkeuring ->
4 Goedkeuring door de klant -> 8 Voltooid; plus 5/6 (V2 approval statuses), 7 Gefactureerd
(V2 invoiced) and 9 "invoiced" (v1 invoiced - the label in the live dropdown is literally
the untranslated English word).

Two backend surfaces move a work between statuses, and they behave differently:

1. **`PUT /admin/extra-works/{id}`** - the generic update. This is what the UI actually
   calls for Plan, Start, Approve and Revert; every one of those buttons just posts a new
   `status_id`. It goes through the shared query builder, so it *is* row-scoped (you must be
   assigned to the work or hold a UCB row for its customer-building). Gate:
   `extra_works,update`.
2. **`PUT /admin/extra-works/{id}/status`** and **`POST /admin/extra-works/{id}/archive/approve`
   / `.../archive/reject`** - these load the record with a bare `findOrFail` and are **not
   row-scoped at all**. Gate: `extra_works,update`.

Neither surface validates the transition. `updateStatus` validates only that the target id
exists in `t_ticket_status`. There is no from-state check, no "you may not leave status 9",
no role condition, no history row. `approveArchive` unconditionally writes `status_id = 8`
whatever the work was on before, including 9.

Because status 9 is the only real billed/unbilled flag for v1 works (tier-1 finding, which
my evidence supports), this means: **any user holding `extra_works,update` - which includes
the customer role and the employee role - can un-bill an invoiced work, or mark an unbilled
one as invoiced, by sending one integer.** The `/status` and `/archive/*` variants can do it
to a work belonging to a customer the actor has no relationship with at all.

## 1.7 A location manager can mint an admin

`POST /admin/users` is gated on `users,create`. The location_manager role holds `users=23`
(view+list+create+delete). The controller validates `role_id` as
`required|integer|exists:roles,id` and nothing else - there is no check that the creator may
grant the requested role, and no comparison of `roles.level`. A location manager can
therefore create a new user with `role_id = 1` and hold full admin. Note also that a role
change wipes the target's module overrides, and that deleting a user is a **hard** delete
(the User model does not use SoftDeletes) which silently cascades away all of their UCB grants.

There is no audit log written for any permission, role, or UCB change. `ActivityLogger` is
never called from `UsersController`, `UserGranularPermissionsController`, or
`UserPermissionController`.

## 1.8 Routes with no permission middleware at all

Everything under `/api/admin/...` sits inside `auth:sanctum` + `user.status` only - the
`admin` prefix group itself carries **no** middleware. Any route inside it that does not
carry its own `ucb.permission` is open to every authenticated user of every role. The ones
that matter:

- **`/api/admin/reports/*` - all 12 PDF and Excel report endpoints, no middleware.** These
  are the revenue reports; tier-1 established that ten `ReportsController` methods compute
  revenue from `extra_works.status_id = 9`. Any authenticated user of any role can pull the
  whole company's extra-work revenue by building, by department, and the employee-hours
  report, as PDF or Excel.
- `POST /api/admin/buildings/bulk/update`, `bulk/delete`, `bulk/status-update`, and
  `GET /admin/buildings/summary` - no middleware, while the single-record equivalents all
  require `buildings,update` / `buildings,delete`.
- `POST /api/admin/mail/auth/password-reset` - no middleware, in a group where every other
  mail route is gated.
- `/api/admin/projects/*` (17 routes) and `/api/admin/meta/*` - no middleware.
- The seven role dashboards (`/api/customer/dashboard`, `/api/admin/dashboard`, ...) - no
  middleware. This one is **not** a leak: each dashboard derives its scope from the
  *caller's own* `role_id`, so a customer calling `/api/admin/dashboard` still gets
  customer-scoped numbers. Worth stating plainly so nobody "fixes" it wrongly.

## 1.9 Same record, two different permission gates

`/admin/meldings/{id}` and `/admin/extra-works/{id}` are the same controller and the same
table. The `{id}` routes carry no type filter. So record 433 - a type=1 extra work - is
readable at `GET /admin/meldings/433` (verified live) under the `melding,view` bit, and at
`GET /admin/extra-works/433` under the `extra_works,view` bit. A customer holds
`melding=15` (no delete) but `extra_works=31` (delete), so the delete they are denied on one
URL is granted on the other for the identical record.

## 1.10 Coordinator vs worker

These are two genuinely separate tracks pointing at two different tables:

- **Coordinator = a `User`.** Stored in `extrawork_assignments.user_id`. Created by
  `POST /admin/extra-works/{id}/employees` (the endpoint is named "employees" but its payload
  key is `user_id`). The candidate pool is computed server-side as: users holding a UCB row on
  one of the work's customer-buildings, active, whose role name is not in
  `('customer','customer_employee','contact_person')`. Note `customer_manager` is **not** in
  that exclusion list, so a customer-type role can be offered as a coordinator.
- **Worker = an `Employee`.** Stored in `extrawork_worker_assignments.employee_id`. Created by
  `POST /admin/extra-works/{id}/workers` / `.../workers/bulk`. Deleting the assignment cascades
  a delete of that employee's `extra_work_employee_hours` rows for that work - which is where
  labour money lives.

**The word "coordinator" does not appear anywhere in the backend PHP.** It is purely a
frontend label. There is no `is_coordinator` column, no coordinator role, no behaviour keyed
on coordinator status anywhere in the API. Concretely: **coordinator status changes nothing
in the backend.** It is an entry in the `extrawork_assignments` table which (a) makes the
work visible to that user through the row-scoping clause, (b) adds them to the FCM
notification audience, and (c) nothing else. No transition, price, total, invoice period or
button is decided by it.

The convention that "coordinators are location chefs" lives only in the plan modal, which
pre-selects `available_users` whose `role.name === 'location_chef'`.

**On the lowercased-email claim in the brief: it is TRUE, but it is frontend-only and it is
not the User-Employee link.** The real link is the `users.employee_id` foreign key - every
one of the 19 live users is either `source_type=employee` with an `employee_id` or
`source_type=contact` with a `contact_id`. The lowercased-email match exists in exactly one
place: the Plan modal, which mirrors the chosen coordinators into the worker list by matching
`user.email.toLowerCase()` against `employee.email.toLowerCase()`. So a coordinator whose
User email differs in any way from their Employee email is simply not auto-added as a worker,
and gets no hours row - a silent money consequence of a string comparison in a React effect.
The same effect has a comment/code mismatch: the comment says "keep only manually added
workers" but the code clears the whole worker list when the last coordinator is deselected.

Separately, "worker" has a second, string-typed definition in the backend:
`Employee::isWorker()` and `Employee::scopeWorkers()` decide worker-hood by
`position LIKE 'worker%'`. An employee whose free-text `position` is spelled anything else is
not a worker to that scope.

## 1.11 What a customer user can see of a work

**There is no customer-facing controller and no customer-facing serializer.**
`app/Models/CustomerExtrawork.php` and
`app/Http/Controllers/Admin/CustomerExtraworksController.php` both exist as **zero-byte files**
and neither is routed. A customer user hits exactly the same `/api/admin/extra-works/...`
endpoints as an admin and receives exactly the same payload. `transformModelData` has no role
branch anywhere in it.

So the API answer to "which fields are hidden from a customer" is: **none.** A customer with
`extra_works,view` receives, for any work they can reach: `total_price`, `total_tax`,
`total_subtotal`, `total_cost`, `total_products_cost`, `total_labor_cost`, `total_hours`,
`financial_summary`, the full `products` array including each product's unit price, tax rate
and the linked `customer_product` record, `worker_assignments`, `user_assignments` with every
assignee's name and email, `available_users` with names, emails and roles of every internal
user scoped to that building, `approval_notes`, `completion_notes`,
`archive_approval_notes`, `archive_rejection_reason`, `draft_message`, and the full comment
thread with commenter emails.

The hiding is done entirely in the React client, by `isCustomer = role.name === 'customer'`,
which suppresses the Employee Hours tab, the Customer Building tab, product edit/delete, file
delete and the internal-notes block. Every one of those is a client-side render condition over
data the server already sent.

Files are not scoped either: `GET /api/files/view/{guid}` requires only a valid token (which
may be passed as a query parameter so it works in `<img src>`), and `DownloadController::view`
does no ownership or scope check whatsoever. Any authenticated user holding any file GUID gets
the file.

Row visibility is the one real customer restriction, and only on list endpoints:
`applyUcbPermissions` limits the list to works the user is assigned to, created (dead clause,
see 2.6), or holds a UCB row for. **`show()` bypasses it** - it is overridden in
`ExtraWorksController` to call `ExtraWork::with(...)->findOrFail($id)` directly - so a customer
who guesses or is given an id reads any other customer's work in full, including its money.

---

# 2. EVIDENCE

## 2.1 The middleware

**NAME** `App\Http\Middleware\UcbPermissionMiddleware::handle` (alias `ucb.permission`)
**CODE** `app/Http/Middleware/UcbPermissionMiddleware.php:52-56`
```php
$hasPermission = RolePermission::roleHasPermission(
    $user->role_id,
    $moduleSlug,
    $permissionBit
);
```
That is the entire decision. `$request` is not consulted for customer_id/building_id; the
class has no reference to `user_customer_building_permissions`, `user_module_overrides`, or
`user_granular_permissions`.

**CODE** `app/Models/RolePermission.php:219-228`
```php
public static function roleHasPermission(int $roleId, string $moduleSlug, int $permission): bool
{
    $rolePermission = self::getPermission($roleId, $moduleSlug);
    if (!$rolePermission) { return false; }
    return $rolePermission->hasPermission($permission);
}
```
No row for the module = deny.

**Answer to the standing RBAC question handed up by tier-1:** `ucb.permission` **only
allows or denies the route. It never narrows the query.** Any row scoping is the
controller's own doing.

**CODE** `bootstrap/app.php:29-35` - the four aliases: `user.status`, `wrap.api`,
`ucb.permission`, `admin.only`, `token.query.auth`. Nothing else.
**CODE** no `app/Policies` directory exists; `grep -rn "Gate::|authorize("` over
`app/Providers` and `app/Http/Controllers` returns only unrelated "privacy policy" URL strings.

**CODE** `app/Http/Middleware/AdminOnly.php:35` - `if ($user->role_id !== 1)` -> 403.
**CODE** `app/Http/Middleware/CheckUserStatus.php:79-148` - `status_id` 1 allowed, 2/3 denied,
4 allowed only on paths containing `auth/me`, `auth/logout`, `user/status`, anything else denied.

## 2.2 The bit-meaning collision

**CODE** `app/Models/RolePermission.php:26-33`
```php
const PERMISSION_EXPORT = 32;   const PERMISSION_IMPORT = 64;   const PERMISSION_ADMIN = 128;
```
**CODE** `app/Services/PermissionService.php:11-22`
```php
const BITS = [ ... 'restore' => 32, 'export'  => 64, 'manage'  => 128, 'assign' => 256, 'bulk' => 512 ];
```
**CODE** `app/Models/UserModuleOverride.php:58-69` - same second scheme.
**CODE** `app/Http/Controllers/Admin/UsersController.php:729,760` - the profile payload renders
both `role_permissions` and `module_overrides` through `PermissionService::maskToActions`.
**DATA** `GET /admin/users/1/profile` returns `extra_works` mask 255 rendered as
`['view','list','create','update','delete','restore','export','manage']` - "restore" and
"manage" are labels for bits the enforcing model calls export and admin.

## 2.3 UserModuleOverride - written, displayed, never enforced

**CODE** grep for `UserModuleOverride` across `app/`, `routes/`, `config/`, `database/seeders`
returns exactly one hit outside its own model file: `app/Models/User.php:157` (the `hasMany`
relation). No controller and no middleware reads the model.
**CODE** the table *is* read, but only by raw queries in three places:
`app/Services/PermissionService.php:57-66` (`getUserOverride`),
`app/Http/Controllers/Admin/UsersController.php:735-765` (display),
`app/Http/Controllers/Admin/UsersController.php:487-500` (wipe on role change).
**CODE** `PermissionService::effectiveMask` (`:27-36`) - the only place an override actually
beats a role mask - is called from exactly one place:
`app/Http/Controllers/Auth/AuthController.php:317-323`, inside `getEffectivePermissions`,
which feeds the login response for four hard-coded resources
(`['tickets','customers','buildings','users']` - note `extra_works` and `invoices` are not in
that list).
**DATA** `GET /admin/users/147/module-overrides` returns 8 live rows, including
`{module_slug: "extra_works", permission_mask: 15}` for a user whose role grants 63, and
`GET /admin/users/153/profile` shows `extra_works` role mask **255** against an override of **3**.
**Consequence (INFERRED, from those two CODE facts + that DATA):** user 153's restriction to
view+list is not enforced; `ucb.permission:extra_works,delete` will pass for them because
`role_permissions` says 255.

Also note the model's `$fillable` declares a `resource` column while every live query joins on
`umo.module_id`; the live rows returned by the API carry `module_id`. The model's fillable list
does not match the table.

## 2.4 Granular permissions - a UI hint API

**CODE** `grep -rln "user_granular_permissions" app/` returns only
`GranularPermissionController.php`, `Admin/RolePermissionTemplateController.php`,
`Admin/UserPermissionController.php`, `Models/UserGranularPermission.php` - i.e. the
permission-serving and permission-CRUD controllers. No business controller consults it.
**CODE** `app/Http/Controllers/GranularPermissionController.php:259-274` - `determineScope`
is a hard-coded `role_id => 'all'|'ucb'|'assigned'` map with no DB read.
**DATA** `GET /granular-permissions` as role 1 returns `scope: "all"` and a large
`modules.melding.components` / `modules.extra_work.components` tree with `show` flags,
`status_conditions` and `ownership_conditions` per component key
(`approve.completeDate`, `detail.coordinator`, ...). This is presentation metadata; nothing
server-side evaluates a `status_condition`.
**DATA** `GET /admin/user-granular-permissions/effective/147` returns
`melding.tabs.archived.show=false`, `melding.components["approve.info"].show=false` etc. for
the location chef - again advisory only.

`config/permissions.php` (87 lines of cache TTLs, `ucb.admin_bypass`, `null_semantics`,
action bits, invalidation strategy) is read by **nothing**: `grep -rn "config('permissions"`
over `app/` returns zero hits. **DEAD config file.**

## 2.5 Role and module data

**DATA** `GET /admin/roles` - the 8 roles in table 1.4 (id, name, display_name, level,
type_id, is_system).
**DATA** `GET /admin/users?per_page=100` - 19 users; role distribution admin 6, customer 6,
employee 4, location_manager 2, location_chef 1; every row has either `employee_id` +
`source_type=employee` or `contact_id` + `source_type=contact`.
**DATA** `GET /admin/users/{1,148,153,150,147}/profile` -> the `role_permissions` array,
which is the matrix in 1.5. Full module list for admin:
`building_customers, buildings, client_invoice_items, client_photos, client_rentals, contacts,
contracts, customer_buildings, customer_clients, customer_departments, customer_works_types,
customers, departments, employee_buildings, employee_contracts, employees, extra_works,
invoices(31), lookup_tables, mail, mail_groups(63), melding, notifications, products, roles,
statuses, users` - all 255 except invoices=31 and mail_groups=63.
**CODE** `app/Http/Controllers/Admin/UsersController.php:708-732` - the query that produces it
(`role_permissions rp JOIN modules m`).

**Module slugs actually used as route gates** (`grep -o "ucb.permission:[a-z_]*" routes/api.php | sort -u`):
`building_customers, buildings, contacts, contracts, customer_buildings, customer_departments,
customers, customer_works_types, employee_contracts, employees, extra_works, invoices,
lookup_tables, mail, melding, products, users`.
Every other module row that exists in `role_permissions` - `reports`, `work-plan`, `roles`,
`statuses`, `notifications`, `departments`, `mail_groups`, `client_invoice_items`,
`client_photos`, `client_rentals`, `customer_clients`, `employee_buildings` - **gates nothing.
Those masks are dead data.**

**No migration creates `role_permissions`, `modules`, `user_module_overrides`, or
`user_customer_building_permissions`.** `grep -rln "'<table>'" database/migrations/` finds only
*alter* migrations (`2025_10_19_222623_add_page_fields_to_role_permissions_table.php`,
`2025_10_19_162727_add_page_info_to_modules_table.php`) and nothing at all for the other two.
The permission schema cannot be reproduced from a clean `migrate`. (This extends the DBA-level
schema-anomaly list tier-1 handed up.)

## 2.6 `extra_works.created_by` is a display string, so the "creator" access clause is dead

**CODE** `database/migrations/2025_10_18_072000_add_action_by_fields_to_extra_works.php:21`
```php
$table->string('created_by', 100)->nullable()->after('created_at')->comment('Name of person who created');
```
**CODE** `app/Http/Controllers/Admin/ExtraWorksController.php:610-618`
```php
$roleName = $user->role->display_name ?? 'User';
$userInfo = "{$user->name} ({$roleName})";
$createdByName = $userInfo;
```
written at `:669` (`$updateFields['created_by'] = $createdByName;`); the numeric creator goes
to a different column at `:671` (`$updateFields['created_user_id'] = $userId;`).
**CODE** `app/Http/Controllers/Admin/ExtraWorksController.php:350`
```php
$q->orWhere('extra_works.created_by', $user->id);
```
and the identical clause in `getAccessibleExtraWorks` at `:3166`.
**DATA** `GET /admin/extra-works?per_page=5` - every row has
`created_by: "<name> (Admin)"` and `created_user_id: 128`.
**DATA** `GET /admin/extra-works/accessible?user_id=147` - rows carry
`created_by: "B Amsterdam"` and `creator_name: null`.

**Verdict: the "you can see what you created" branch of the access filter never matches**
(MySQL casts a name string to 0). This confirms the tier-1 claim and supplies the mechanism:
it is not a type mismatch in the comparison, it is that the column holds a rendered display
name and the numeric creator lives in `created_user_id`, which the clause does not use.
Same bug at `:3228`: `\App\Models\User::find($extraWork->created_by)` - looking up a user by
name - which is why the DATA above shows `creator_name: null`.

## 2.7 Row scoping: which extra-work endpoints apply it

**CODE** `app/Http/Controllers/Admin/ExtraWorksController.php:327-365` -
`applyUcbPermissions`: `role_id == 1` returns the query untouched (`:337`), then
`assignments.user_id = me` OR the dead `created_by` clause OR an EXISTS over
`extra_work_customer_building` joined to `user_customer_building_permissions`.
Note it does **not** filter on `scope_mask` - any UCB row, even `scope_mask = 0`, grants
visibility here (contrast `ExtraWorkService.php:951` and `RecipientDeterminer.php:168`, which
do require `scope_mask > 0` for notifications).
**CODE** `app/Http/Controllers/Base/EntityController.php:300-304` - `buildQuery` calls
`applyUcbPermissions` unconditionally, including when `applyFilters=false`.
**CODE** `EntityController::show/update/destroy` (`:964-1013`, `:1062-1075`) all route through
`buildQuery(...,false)`, so the base implementations are scoped.
**CODE** but `ExtraWorksController` overrides `show()` at `:1356` with
`ExtraWork::with([...])->findOrFail($id)` - **unscoped**.
**CODE** `grep -n "ExtraWork::findOrFail" ExtraWorksController.php` - 20 unscoped loads,
including `updateStatus:3631`, `approveArchive:2636`, `rejectArchive:2717`,
`convertToExtraWork:2806`, `convertToMelding:2899`, `removeCustomerBuilding:2990`,
`getWorkers:2347`, `addWorker:2396`, `bulkAddWorkers:2469`, `bulkDeleteWorkers:2556`,
`updateHours:5636`, `saveDraft:5807`, `clearDraft:5886`, `destroy:3874`,
`addProduct:1755`, `updateProduct:1825`, `deleteProduct:1896`.
`priceBreakdown` at `:4256` uses `ExtraWork::with([...])` + find - also unscoped.
**CODE** `app/Http/Controllers/Admin/ExtraWorkEmployeeHoursController.php` - grep for
`auth()`/`role_id`/`role->` returns only `created_by`/`updated_by` stamps. **No authorisation
logic of any kind**; the gate is entirely the `extra_works,*` role bit on the route.

**CODE** base `EntityController::applyUcbPermissions` (`:783-787`) is a no-op returning the
query unchanged, and only four controllers override it: `Admin/CustomersController:125`,
`Admin/ExtraWorksController:327`, `Admin/CustomerBuildingsController:322`,
`Admin/BuildingsController:102`. **Every other entity controller in the system has no row
scoping at all** - including invoices.

## 2.8 The transition endpoints in detail

**CODE** `ExtraWorksController::updateStatus` `:3621-3757`. Full authorisation content of the
method: none. Validation is
```php
'status_id' => 'required|exists:t_ticket_status,id',
```
then `ExtraWork::findOrFail($id)` at `:3631`, `$extraWork->status_id = $validated['status_id']`
at `:3635`, save. The only branching on the new status (`:3643`, `:3648`) chooses which
system comment text to add. No from-state check, no role check, no scope check, no history row.
The remaining 100 lines build a notification audience: UCB holders with `scope_mask > 0` on the
record's customer-buildings + active assignees + everyone sharing `user_department_id` +
everyone whose role slug is `admin`.

**CODE** `ExtraWorksController::approveArchive` `:2633-2694`:
```php
$extraWork = ExtraWork::findOrFail($id);
...
$extraWork->update([
    'status_id' => 8,
    'archive_approved_at' => now(),
    'archive_approved_by' => $userInfo,   // display string again
    ...
]);
```
Unconditional write of status 8, from any status, by any holder of `extra_works,update`,
on any record. `rejectArchive` `:2714-...` requires a `reason` and a caller-supplied
`status_id`, again with no from-state or role condition.

**CODE** the UI transitions do not use those endpoints at all -
`frontend/src/pages/finalosius/extra-works/detail.jsx:925` (Plan -> `PUT /admin/extra-works/{id}`
with `status_id: 2`), `:976` (Start -> `status_id: 2`), `:990` (Approve -> `status_id: 4`),
`:1047` (Revert -> arbitrary `status_id: previousStatus` plus null-ing the archive fields),
`:1123` (`POST .../archive/approve`), `:1153` (`POST .../archive/reject`).

**CODE** `frontend/.../components/WorkflowActionsBar.jsx:73-296` - the button table. Every
button is `disabled={isCustomer}` **except** the status-4 "Archive/Approve" and "Reject
Archive" pair at `:207` and `:225`, which are `disabled={archiving || rejectingArchive}` only.
Status 4 is "Goedkeuring door de klant", so leaving those enabled for a customer looks
deliberate - but the backend places no reciprocal restriction, so a provider-side user with
`extra_works,update` can take the customer's approval decision for them, and a customer can
click Archive on any status-4 work in their scope.

## 2.9 Invoice actions

**CODE** `routes/api.php:1104-1134` - every invoice route carries `ucb.permission:invoices,<action>`:
`index`(list) `store`(create) `pendingExtraWorks`(view) `show`(view) `update`(update)
`destroy`(delete) `sendInvoice`(update) `previewInvoice`(view) `downloadInvoice`(view)
`updateStatus`(update) `regeneratePdf`(update) `revertToDraft`(update) `bulkDownload`(view)
`createFromInvoiceableItems`(create) `getInvoiceableItemsForCustomer`(view)
`addItem`/`updateItem`/`deleteItem`/`removeExtraWork`(update).
`routes/api.php:1071-1078` - the `invoiceable-items` CRUD, same `invoices,*` gates, including
`PUT /admin/invoiceable-items/{id}/status` on `invoices,update`.
`routes/api.php:951-978` - `extra-work-v2-invoices`, same `invoices,*` gates.

**CODE** `app/Http/Controllers/Admin/InvoiceController.php` - `grep -n "auth()|role_id|user()"`
returns three hits, all `'created_by' => auth()->id()` stamps (`:125, :1191, :1297`).
**The controller contains no authorisation logic and no per-customer scope.** `index` treats
`customer_id` as an optional filter, not an enforced one (confirming tier-1).

**Because no role except admin has an `invoices` row (DATA, 2.5), every invoice action is
admin-only in practice, and admins are unscoped.** The "invoice permission" dimension of the
RBAC model has exactly two states: admin, and 403.

Invoice state guards do exist, and they are status-based rather than role-based:
`sendInvoice:341` (`status !== 'draft'` -> 403), `update:197` (`!isDraft()` -> 403),
`destroy:255` (`!isDraft()` -> 403), `addItem:562` (`!isDraft()`),
`regeneratePdf:483` (`status === 'draft'`), `revertToDraft:527` (`status !== 'sent'`),
`updateStatus:857` (`status !== 'sent'`; target restricted to `paid|cancelled`).
`destroy` also reverts the invoice's extra works to `status_id = 8` and nulls `invoice_id`
and `invoice_date` (`:265-270`).

**The RBAC split tier-1 asked about is real and I can name the roles.** `PUT /admin/extra-works/{id}/status`
requires `extra_works,update`; every invoice route requires `invoices,*`. The customer role,
the employee role, the location_manager role and the location_chef role all hold
`extra_works` update and none of them holds any `invoices` bit. So four of the five populated
roles can move a work off status 9 - staling a sent invoice - and none of them can see, fix
or even read the invoice they just staled.

## 2.10 Login flags and dead user fields

**CODE** `app/Http/Controllers/Auth/AuthController.php:96-116` - the platform-permission block
is commented out under `// TODO: ENABLE LATER`. `web_login_enabled` and `mobile_login_enabled`
are therefore **never enforced**.
**DATA** user 148 has `web_login_enabled: false` and is a live account.
**CODE** `is_login_user` - written at `ContactsController.php:119`,
`Admin/UsersController.php` store, and rendered in contact/employee list payloads
(`ContactsController.php:234,241,400,407` as `can_login`/`has_login_permission`), but never
checked in `AuthController::processLogin`. **Advisory only.**
**CODE** `rbac_version` - auto-incremented by `User::boot` (`app/Models/User.php:389-393`) when
`role_id`, `status_id` or `department_id` change, echoed at `UsersController.php:663`, read by
nothing (no cache key, no token invalidation, zero frontend references). **DEAD.**
**CODE** `users.parent_id` - fillable at `User.php:29`, has `parent()`/`children()` relations at
`:97,:105`, and no query anywhere uses either. **DEAD.**
**CODE** `User` uses `HasApiTokens, HasFactory, Notifiable` - **no SoftDeletes** - while
`app/Observers/UserObserver.php:37-66` hard-deletes the user's `user_customer_building_permissions`
and `user_module_overrides` on `deleting`. Deleting a user permanently destroys their access
grants with no audit row.
**CODE** `app/Http/Controllers/Auth/AuthController.php:680` calls
`\App\Services\UserPermissionService::getFormattedPermissions($user->id)`. **That class does
not exist** (`find app -iname "*UserPermissionService*"` returns nothing).
**DATA** `GET /me/permissions` -> `{"success":false,"error":{"code":"ERROR"},"message":"Internal server error"}`.
The user-facing "my permissions" endpoint is permanently broken.

## 2.11 Coordinator / worker evidence

**CODE** `app/Models/ExtraworkAssignment.php:10-19` - table `extrawork_assignments`, fillable
`extra_work_id, user_id, assigned_by, assigned_at, assignment_notes, is_active`, with the
in-code comment `// ✅ FIXED: employee_id → user_id`.
**CODE** `app/Models/ExtraWorkWorkerAssignment.php:11-16` - table
`extrawork_worker_assignments`, fillable `extra_work_id, employee_id`; `:32-37` the `deleting`
hook that cascades `ExtraWorkEmployeeHour` deletion for that (work, employee).
**CODE** `app/Models/Employee.php:74-77` - `users(): HasMany(User::class, 'employee_id')`.
That FK is the real User<->Employee link.
**CODE** `grep -rn "coordinator" app/ --include=*.php` -> **zero hits**.
**CODE** `grep -rln "coordinator" frontend/src` -> four locale bundles plus
`ExtraWorkUserAssignmentsTab.jsx`, `ExtraWorkPlanModal.jsx`, `ExtraWorkBulkPlanModal.jsx`.
**CODE** `frontend/.../modals/ExtraWorkPlanModal.jsx:107-109`
```js
// Auto-select location_chef users as coordinators
const locationChefs = availableUsers.filter(u => u.role?.name === 'location_chef');
```
**CODE** the email match, `ExtraWorkPlanModal.jsx:114-144` (quoted in full because the brief
asked for it):
```js
// Sync workers with selected coordinators (match by EMAIL, not ID)
useEffect(() => {
  if (selectedUsers.length > 0 && employees.length > 0) {
    const coordinatorEmails = selectedUsers.map(u => u.email?.toLowerCase()).filter(Boolean);
    const coordinatorWorkers = employees.filter(emp =>
      coordinatorEmails.includes(emp.email?.toLowerCase())
    );
    setSelectedWorkers(prev => {
      const extraWorkers = prev.filter(w =>
        !coordinatorEmails.includes(w.email?.toLowerCase())
      );
      const mergedWorkers = [...coordinatorWorkers];
      extraWorkers.forEach(worker => {
        if (!mergedWorkers.find(w => w.email?.toLowerCase() === worker.email?.toLowerCase())) {
          mergedWorkers.push(worker);
        }
      });
      return mergedWorkers;
    });
  } else if (selectedUsers.length === 0) {
    // If no coordinators selected, keep only manually added workers
    setSelectedWorkers([]);
  }
}, [selectedUsers, employees]);
```
The `employees` list it matches against comes from `GET /admin/employees/list-light`
(`:71`), gated on `employees,list` - which the **customer role does not have**, so for a
customer user that fetch 403s, `employees` stays empty, and the worker sync silently produces
nothing.
**CODE** `Employee.php:179-182, 231-234` - the other "worker" definition:
```php
public function scopeWorkers($query) { return $query->where('position', 'LIKE', 'worker%'); }
public function isWorker(): bool { return str_starts_with(strtolower($this->position ?? ''), 'worker'); }
```
**CODE** `ExtraWorksController::getAvailableUsersForExtraWork:3064-3115` - the coordinator
candidate pool:
```php
->whereIn('u.id', $userIds)            // users with a UCB row on this work's customer_buildings
->where('u.status_id', 1)
->whereNotIn('r.name', ['customer', 'customer_employee', 'contact_person'])
```
`customer_manager` is absent from that exclusion list.

## 2.12 Customer visibility evidence

**CODE** `app/Models/CustomerExtrawork.php` - **0 bytes**.
`app/Http/Controllers/Admin/CustomerExtraworksController.php` - **0 bytes**, and
`grep -n "CustomerExtraworks" routes/api.php` -> no route.
(Other zero-byte files found in the same sweep: `app/Listeners/ContextAwareTranslationListener.php`,
`app/Listeners/SmartTranslateTicketMessageListener.php`, `app/Http/Controllers/Base/EmployeesController.php`,
`app/Http/Controllers/Base/ContactsController.php`.)
**CODE** `ExtraWorksController::transformModelData:396-580` - no `auth()`, no `role`, no
conditional field removal by actor. The `unset()` calls at `:407-421` drop translation
variants and denormalised name columns only.
**DATA** `GET /admin/extra-works/433` returns, among 88 top-level keys:
`total_price: 91.11, total_tax: 15.81, total_subtotal: 75.30, total_cost: 75.3,
total_labor_cost: 0, total_products_cost: 75.3, total_hours: 2.5`, a `products` array with
`price: "75.30", tax_rate: "21.00"` and the nested `customer_product` record, plus
`financial_summary`, `available_users`, `user_assignments`, `worker_assignments`,
`draft_message`, `approval_notes`, `archive_rejection_reason`, `top_level_comments`.
**CODE** the client-side hiding: `detail.jsx:186-189` defines
`isCustomer = userRole === 'customer'`; `:1360, :1379, :1427, :1451` hide the Employee Hours,
User Assignments and Customer Building tabs; `ExtraWorkFilesTab.jsx:186` hides the file delete
control; `ExtraWorkFinancialsTab.jsx:171, 408, 436, 460, 486, 499, 692, 755` disable product
add/edit/delete and hide the internal notes block.
**CODE** file access: `routes/api.php:32-39` puts `files/view/{path}` behind `token.query.auth`
only; `app/Http/Middleware/TokenQueryAuth.php:35-60` accepts `?token=` from the query string;
`app/Http/Controllers/DownloadController.php:63-103` (`view` -> `viewByGuid`) validates the
GUID format and streams the file with **no ownership or scope check**.

## 2.13 Ungated routes (verified group headers)

| route(s) | line | group middleware |
|---|---|---|
| `Route::prefix('admin')->group(...)` (the whole admin tree) | `routes/api.php:288` | **none** |
| `GET /admin/reports/*` - 12 endpoints | `:1081-1100` | **none** |
| `POST /admin/buildings/bulk/update|delete|status-update`, `GET /admin/buildings/summary` | `:311-314` | **none** (siblings on `:302-310` are gated) |
| `POST /admin/mail/auth/password-reset` | `:1227` | **none** (siblings gated) |
| `/admin/projects/*` (13 routes, `Projects_ProjectController`) | `:525-541` | **none** |
| `/admin/meta/contact-email-statuses`, `/admin/meta/service-line-types` | `:294-295` | **none** |
| 7 role dashboards + `/work-plan/weekly` | `:240-285, :300-303` | **none** (self-scoping, see below) |

The dashboards are self-scoping: `Customer/DashboardController.php:186-200` and
`Admin/DashboardController.php:~155-170` both derive scope from the caller's own `role_id`
via the same hard-coded map, so hitting another role's dashboard URL does not widen access.

Groups that *do* carry `admin.only` at group level (so are correctly locked):
`users/{userId}/granular-permissions` `:1457`, `roles/{roleId}/permission-template` `:1469`,
`permission-metadata` `:1473`, `role-permission-templates` `:1481`, `user-granular-permissions`
`:1496`, `data-exports` `:1847`, `prj-projects` `:2112`.

---

# 3. CONNECTION MAP

## 3.1 Field-level read/write maps

**`role_permissions.permissions`** (int bitmask)
- WRITTEN BY: no HTTP endpoint found - no route writes this table. Seeded/DB-managed.
- READ BY: `RolePermission::roleHasPermission` <- `UcbPermissionMiddleware::handle` (every
  gated route); `PermissionService::getRoleMask` <- `effectiveMask` <- login payload;
  `AuthController::getEnhancedPermissions` (login menu); `UsersController` profile display.
- IF NULL/EMPTY: no row -> hard 403 on every route gated on that module.
- GATES: **everything**. This is the authorisation system.

**`user_module_overrides.permission_mask`**
- WRITTEN BY: `POST /admin/users/{userId}/module-overrides`, `.../module-overrides/bulk`
  (gated `users,update`); wiped by `UsersController::update:487-500` on role change and by
  `UserObserver::deleting`.
- READ BY: `PermissionService::getUserOverride` -> only `AuthController::getEffectivePermissions`
  (login payload, 4 hard-coded resources); `UsersController` profile/override display.
- IF NULL/EMPTY: role mask applies (which is also what happens when it is NOT empty).
- GATES: **nothing.** Not consulted by any authorisation decision. **Functionally dead as a
  control, live as a mirage** - the UI shows a restriction the API does not apply.

**`user_granular_permissions.{visibility,tabs,components,actions}`** (JSON)
- WRITTEN BY: `POST /admin/users/{userId}/granular-permissions`, `.../reset`,
  `POST|PUT /admin/user-granular-permissions/*`, `applyTemplate`, and
  `UserGranularPermission::createFromRoleTemplate` on first read.
- READ BY: `GET /granular-permissions`, `GET /admin/user-granular-permissions/effective/{id}`,
  `GET /admin/users/{id}/granular-permissions` - all three are permission-serving endpoints
  consumed by the SPA.
- IF NULL/EMPTY: falls back to `role_permission_templates`; if that is empty too the module is
  omitted from the response.
- GATES: client-side rendering only. No server-side effect.

**`user_customer_building_permissions.customer_building_id`**
- WRITTEN BY: `POST /admin/users` (auto, `scope_mask` 1), `createFromSource` (`scope_mask` 3),
  `POST /admin/users/{userId}/ucb-permissions/bulk-assign` (`scope_mask` from body, default
  255 or 1 depending on path), removed by `bulk-remove` and by `UserObserver::deleting`.
- READ BY: `ExtraWorksController::applyUcbPermissions:352-360`;
  `CustomersController:125`, `BuildingsController:102`, `CustomerBuildingsController:322`;
  `getAvailableUsersForExtraWork:3077`; `getAccessibleExtraWorks:3151`;
  the seven role dashboards; `ExtraWorkService::getNotificationRecipients:951`;
  `RecipientDeterminer:168`; the four `ExtraWork*` events; `AuthController::getUserUcbSummary`.
- IF NULL/EMPTY: a non-admin sees only works they are assigned to (the creator branch is dead).
- GATES: row visibility on four list endpoints, notification audience, coordinator candidate
  pool. **Never gates an action.**

**`user_customer_building_permissions.scope_mask`**
- WRITTEN BY: as above. Values seen in code: 1, 3, 255, or caller-supplied `0..1023`.
- READ BY: only as `scope_mask > 0` in six places - `LocationManager/DashboardController:178`,
  `CustomerManager/DashboardController:178`, `ExtraWorksController:3674`,
  `ExtraWorkService:951`, `RecipientDeterminer:168`, `updateStatus`'s audience block. Also
  surfaced in `AuthController` payloads.
- IF NULL/EMPTY: `0` still grants visibility through `applyUcbPermissions` (which does not
  check it) but suppresses notifications.
- GATES: notification audience and two role dashboards. **The individual bits are never
  decoded** - only `> 0` is ever tested. The 10-bit vocabulary is decorative.

**`extra_works.created_by`** (varchar 100)
- WRITTEN BY: `ExtraWorksController::store:669` and `batchStore:6010` as `"Name (Role)"`;
  `:808, :959, :994, :5963, :6026` write a numeric user id into *other* tables' `created_by`.
- READ BY: `applyUcbPermissions:350` and `getAccessibleExtraWorks:3166` as an integer
  comparison (never matches); `:3228` as a User primary key (always null); displayed in list
  payloads and in `formatWorkWithCalculations:4842`.
- IF NULL/EMPTY: no change - the clause is inert either way.
- **DEAD as an access-control input.** Live as a display string.

**`extra_works.status_id`**
- WRITTEN BY: `PUT /admin/extra-works/{id}` (any value, via the generic update);
  `PUT /admin/extra-works/{id}/status` (any value in `t_ticket_status`);
  `POST /{id}/archive/approve` (hard 8); `POST /{id}/archive/reject` (caller-supplied);
  `PUT /admin/extra-works/groups/{groupId}/status` (bulk);
  `InvoiceController::destroy:265` (reverts to 8 when a draft invoice is deleted);
  `PATCH /admin/extra-works/{id}` from the frontend bulk modal (tier-1's finding).
- READ BY: ten revenue methods in `ReportsController` (`=9` means invoiced), every dashboard,
  the UI button table, `applyAdditionalScopes`, `destroy`'s `!= 1` guard, `addProduct`/
  `updateProduct`/`deleteProduct`'s `!== 1` guard.
- GATES: yes - blocks product edits and deletion for non-admins when != 1; decides which
  workflow buttons render; **is the billed/unbilled flag**.

**`users.{web_login_enabled, mobile_login_enabled, is_login_user, rbac_version, parent_id}`**
- All written, all displayed, none read by any decision. See 2.10.

## 3.2 THE HEADLINE TABLE - extra-work transitions

Row scoping column: "scoped" = the caller must be assigned to the work or hold a UCB row on
its customer-building; "**unscoped**" = any record id, any customer.

| Transition / action | Route | Middleware | Row-scoped? | Roles that pass (live data) |
|---|---|---|---|---|
| Create work | `POST /admin/extra-works` | `extra_works,create` | n/a | admin, customer, employee, loc.mgr, loc.chef |
| Batch create | `POST /admin/extra-works/batch` | `extra_works,create` | n/a | same |
| List works | `GET /admin/extra-works` | `extra_works,list` | scoped | all five |
| **Read one work (all fields incl. money)** | `GET /admin/extra-works/{id}` | `extra_works,view` | **unscoped** | all five |
| Plan / Start / Approve / Revert (the real UI path) | `PUT /admin/extra-works/{id}` | `extra_works,update` | scoped | admin, customer, employee, loc.mgr, loc.chef |
| **Set any status incl. 9 (invoiced)** | `PUT /admin/extra-works/{id}/status` | `extra_works,update` | **unscoped** | all five |
| **Archive-approve (-> status 8)** | `POST /admin/extra-works/{id}/archive/approve` | `extra_works,update` | **unscoped** | all five |
| **Archive-reject (-> caller-chosen status)** | `POST /admin/extra-works/{id}/archive/reject` | `extra_works,update` | **unscoped** | all five |
| Bulk group status | `PUT /admin/extra-works/groups/{groupId}/status` | `extra_works,update` | see controller | all five |
| Delete work | `DELETE /admin/extra-works/{id}` | `extra_works,delete` | scoped (`parent::destroy`) | admin, customer, employee, loc.mgr, loc.chef - **but** non-admins are blocked unless `status_id == 1` (`:3878`) |
| Delete same record via melding alias | `DELETE /admin/meldings/{id}` | `melding,delete` | scoped | admin, employee, loc.mgr, loc.chef (**customer denied** - melding=15) |
| Add / edit / delete product (money) | `POST|PUT|DELETE /admin/extra-works/{id}/products[/{pid}]` | `extra_works,update` | **unscoped** | all five - **but** non-admins blocked unless `status_id == 1` (`:1754, :1824, :1895`) |
| Assign coordinator (User) | `POST /admin/extra-works/{id}/employees` | `extra_works,update` | **unscoped** | all five |
| Assign worker (Employee) | `POST /admin/extra-works/{id}/workers[/bulk]` | `extra_works,update` | **unscoped** | all five |
| **Create / edit / delete employee hours (labour money)** | `POST|PUT|DELETE /admin/extra-works/{id}/employee-hours[/...]` | `extra_works,create|update|delete` | **unscoped** | all five |
| Update hours_planed / hours_worked | `PATCH /admin/extra-works/{id}/hours` | `extra_works,update` | **unscoped** | all five |
| Move work to another customer/building | `PUT /admin/extra-works/{id}` with `customer_building_id` | `extra_works,update` | scoped on read, **unvalidated on write** | all five |
| Remove a customer-building link | `DELETE /admin/extra-works/{id}/customer-buildings/{cbId}` | `extra_works,update` | **unscoped** | all five |
| Convert melding <-> extra work | `POST /admin/extra-works/{id}/convert-to-{melding,extra-work}` | `extra_works,update` | **unscoped** | all five |
| Delete a published attachment | `DELETE /admin/extra-works/{id}/attachments/{aid}` | `extra_works,update` | **unscoped** | **admin only** (extra `role->slug === 'admin'` check at `:1675`) |
| Delete someone else's comment | `DELETE /admin/extra-works/{id}/comments/{cid}` | `extra_works,update` | **unscoped** | admin + location_manager only (`ExtraWorkService:427`); others limited to own |
| Price breakdown | `GET /admin/extra-works/{id}/price-breakdown` | `extra_works,view` | **unscoped** | all five |
| Read another user's accessible set | `GET /admin/extra-works/accessible?user_id=N` | `extra_works,list` | n/a - **caller identity not checked against `user_id`** | all five |
| Revenue reports (PDF + Excel) | `GET /admin/reports/*` | **NONE** | n/a | **every authenticated user** |

## 3.3 THE HEADLINE TABLE - invoice actions

| Action | Route | Middleware | Roles that pass | Extra guard |
|---|---|---|---|---|
| List invoices | `GET /admin/invoices` | `invoices,list` | **admin only** | none - `customer_id` is an optional filter, not a scope |
| Read invoice | `GET /admin/invoices/{id}` | `invoices,view` | admin only | none |
| Create invoice | `POST /admin/invoices` | `invoices,create` | admin only | none |
| Create from invoiceable items | `POST /admin/invoices/from-invoiceable-items` | `invoices,create` | admin only | none |
| Edit invoice (incl. summary_* and discount fields) | `PUT /admin/invoices/{id}` | `invoices,update` | admin only | `isDraft()` else 403 |
| Delete invoice | `DELETE /admin/invoices/{id}` | `invoices,delete` | admin only | `isDraft()`; reverts its works to status 8 |
| Add / edit / delete line | `POST|PUT|DELETE /admin/invoices/{id}/items[/{itemId}]` | `invoices,update` | admin only | `isDraft()` |
| Remove an extra work from an invoice | `DELETE /admin/invoices/{id}/items/by-extra-work/{ewId}` | `invoices,update` | admin only | see controller |
| **Send (assigns nothing - status only)** | `POST /admin/invoices/{id}/send` | `invoices,update` | admin only | `status === 'draft'` else 403; requires >=1 item |
| Preview / download / bulk download | `GET .../preview|download`, `POST .../bulk-download` | `invoices,view` | admin only | none |
| Regenerate PDF | `POST /admin/invoices/{id}/regenerate-pdf` | `invoices,update` | admin only | rejects `draft` |
| Revert to draft | `POST /admin/invoices/{id}/revert-to-draft` | `invoices,update` | admin only | `status === 'sent'` |
| Mark paid / cancelled | `PUT /admin/invoices/{id}/status` | `invoices,update` | admin only | `status === 'sent'`; target in `paid|cancelled` |
| Pending extra works | `GET /admin/invoices/pending-extra-works` | `invoices,view` | admin only | (500s - tier-1) |
| Invoiceable item CRUD + status | `/admin/invoiceable-items/*` | `invoices,view|create|update|delete` | admin only | none |
| V2 invoices (all 15 routes) | `/admin/extra-work-v2-invoices/*` | `invoices,view|create|update|delete` | admin only | none |

**One-line answer: every invoice action requires the admin role, because `role_permissions`
contains an `invoices` row for role 1 and for no other role. There is no non-admin invoice
persona in this system.**

## 3.4 What points at what

```
                       role_permissions.permissions  ─── the ONLY enforced gate
                                   │
                   UcbPermissionMiddleware (allow/deny, no query narrowing)
                                   │
      ┌────────────────────────────┴────────────────────────────┐
      │                                                          │
  gated route                                            UNGATED route
      │                                            (/admin/reports/*, buildings bulk,
      │                                             /admin/projects/*, /admin/meta/*)
      │                                                          │
  controller ──┬── calls buildQuery() ──> applyUcbPermissions ──> user_customer_building_permissions
               │        (index, PUT {id}, DELETE {id})              (visibility only, scope_mask ignored)
               │
               └── calls ExtraWork::findOrFail() ──> NO SCOPE
                   (show, /status, /archive/*, products, workers,
                    employee-hours, hours, convert, price-breakdown)

  user_module_overrides ──> PermissionService::effectiveMask ──> login payload only ──> SPA menu
  user_granular_permissions ──> GET /granular-permissions ──> SPA tab/button rendering only
  config/permissions.php ──> (nothing)
  config/{context}/{entity}.php 'permissions' ──> getEntityMetaConfig ──> SPA only
```

Action -> consequence chains that cross a money boundary:

- `PUT /admin/extra-works/{id}` or `/status` sets `status_id` -> `status_id = 9` is the v1
  billed flag -> ten `ReportsController` revenue methods count it -> **four non-invoice roles
  can change reported revenue.**
- `DELETE /admin/extra-works/{id}/workers/{aid}` -> `ExtraWorkWorkerAssignment::deleting`
  cascades `ExtraWorkEmployeeHour` rows -> labour cost for that work drops -> gate is
  `extra_works,update`, held by the customer role.
- `DELETE /admin/invoices/{id}` (admin, draft only) -> its extra works revert to `status_id = 8`
  and `invoice_id`/`invoice_date` are nulled -> the works re-enter the unbilled pool.
- `POST /admin/users` with `role_id = 1` -> a new admin -> full invoice access. Gate is
  `users,create`, held by location_manager.
- Deleting a user -> hard delete -> `UserObserver` wipes their UCB rows -> every extra work
  that was visible only through those rows becomes invisible to everyone but admins, with no
  audit trail.

---

# 4. COULD NOT DETERMINE

1. **The true column definitions of `role_permissions`, `modules`,
   `user_module_overrides` and `user_customer_building_permissions`.** No migration creates
   any of them. I inferred columns from the raw queries and from live API payloads.
   *To close:* a `SHOW CREATE TABLE` for those four tables from whoever has DB access.

2. **Whether `role_permissions` can be written at all through the application.** I found no
   route and no controller method that inserts or updates it - `RolesController` only exposes
   `index` and `getBySource`. If it is DB-managed, then the entire enforced permission model
   has no admin UI, which would explain why three parallel decorative systems were built.
   *To close:* grep a deploy/seed repo, or confirm with the operator how a role's module bits
   are changed in practice.

3. **Empirical proof of the cross-role claims.** My token is `role_id = 1`, so I could not
   actually execute a customer-role `PUT /admin/extra-works/{id}/status` or an
   employee-role delete. Every cross-role statement in section 3 is CODE (the route's
   middleware argument) + DATA (that role's live `role_permissions` mask) and is therefore
   labelled INFERRED for the *outcome*.
   *To close:* one non-admin token per role and a read-only 403/200 probe. Note the same
   probe would settle whether `/admin/reports/*` really is reachable by a customer.

4. **Roles 3 (customer_employee), 7 (customer_manager) and 8 (contact_person) have no users**,
   so `GET /admin/users/{id}/profile` could not give me their `role_permissions` rows. Their
   place in the matrix in 1.5 is blank, not zero.
   *To close:* a `SELECT` over `role_permissions` for role_ids 3, 7, 8, or one seeded user each.

5. **`t_ticket_status` slugs.** I have ids and localised labels from
   `GET /admin/extra-works/meta/form-data` (1 Nieuw, 2 In behandeling, 3 Interne goedkeuring,
   4 Goedkeuring door de klant, 5 Interne goedkeuring, 6 Klant goedkeuring, 7 Gefactureerd,
   8 Voltooid, 9 "invoiced") and the slugs `started|basladi|planned|planlandi|resolved|closed`
   from code, but no endpoint exposes the table's `slug` column and no migration seeds it.
   **Note a partial contradiction with tier-1**, which reported 9 = "Gefactureerd": in the live
   dropdown **7** is Gefactureerd (the V2 invoiced status) and **9**'s label is the raw English
   word "invoiced" (the v1 one). The *substance* of tier-1's finding - that 9 is the v1 billed
   flag - is confirmed by `ReportsController:129,285,438,563,739,962,1298` all treating
   `status_id = 9` as "Faturalanan".
   *To close:* `SELECT id, slug, label, label_nl FROM t_ticket_status`.

6. **`user_granular_permissions` / `role_permission_templates` row counts and content in
   production.** I read the serving code and one effective payload; I did not enumerate how
   many users have custom rows or how far they diverge from role templates.
   *To close:* `GET /admin/user-granular-permissions` (admin.only, exists at `routes/api.php:1498`).

7. **Whether the mobile app or the `portal_extra_works` SQL view applies any customer-facing
   redaction of its own.** That view is the one plausible place where a customer-safe field
   subset could exist, and it is outside my area. Handing to the MOBILE/EXTERNAL agent.

8. **The `?context=` config-swap risk** flagged by tier-1 for `EntityController:855-858, 910-913`
   intersects my area: `config/sub/extra-works.php` may carry a different `permissions` block.
   I confirmed the `permissions` key is **never enforced** in any context
   (`getEntityMetaConfig:1959` is its only reader), so a context flip cannot change
   authorisation - but it can change the writable field allow-list. That half remains open and
   belongs to the ARCHITECTURE/CONTEXT agent.

9. **Whether any real operator has actually exercised the location_manager -> create admin path.**
   The capability is proven (route gate + live role mask + absent validation); the history is not.
   *To close:* `SELECT id, role_id, created_at FROM users` cross-referenced with `user_activities`.

---

# 5. NOTES FOR THE CONTRADICTION SWEEP

Explicit agreements and disagreements with the tier-1 reports:

- **AGREE, with mechanism supplied:** `applyUcbPermissions`'s `created_by` clause never
  matches. Tier-1 called it a string-vs-int comparison; the precise cause is that
  `extra_works.created_by` is `VARCHAR(100)` holding `"Name (Role)"`
  (`2025_10_18_072000_add_action_by_fields_to_extra_works.php:21`,
  `ExtraWorksController:610-618,669`) while the numeric creator lives in `created_user_id`.
- **AGREE:** `show()`, `updateStatus()`, `approveArchive()`, `rejectArchive()`,
  `priceBreakdown()` and the conversion endpoints bypass the scope filter. I add 14 more
  unscoped endpoints (section 2.7) and the role names that reach them.
- **AGREE:** the `extra_works,update` vs `invoices,*` split is real. I can now name the roles:
  customer, employee, location_manager and location_chef all hold `extra_works` update and
  none holds any `invoices` bit.
- **AGREE:** `ucb.permission` does not narrow the query - it is a pure allow/deny.
- **PARTIALLY CONTRADICT:** status 9's label. Tier-1 reported 9 = "Gefactureerd"; the live
  form-data dropdown shows **7** = "Gefactureerd" and **9** = "invoiced". The billed-flag
  substance stands.
- **NEW, and it changes how every other report should be read:** `user_module_overrides` and
  `user_granular_permissions` are not enforced anywhere. Any tier-1 or tier-2 statement of the
  form "user X is restricted to Y" that rests on those tables is describing the UI, not the API.
