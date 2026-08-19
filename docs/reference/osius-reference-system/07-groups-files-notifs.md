# Osius reference system — Agent A7: Groups, Attachments, Comments, Notifications, Schedule

Scope: `extra_work_groups` + the group columns on `extra_works`, the `condition` field,
`extra_works_attachments` (`is_draft` / `is_pre_file` / `is_comment`), `extra_work_comments`
+ `extra_work_comment_reads` + `ExtraWorkCommentObserver`, `messages` / `internal_messages`,
and the whole notification stack (`push_notifications`, `push_notification_devices`,
`user_fcm_tokens`, `user_notification_settings`, `mail_templates`, `mail_logs`) —
plus the question of whether anything is time-driven.

Nothing in the reference system was modified. Every API call was a GET through the
read-only wrapper.

Evidence labels:

- **CODE** — a path and line I read, with the line quoted.
- **DATA** — an endpoint I called, with the values that came back.
- **INFERRED** — a conclusion I drew, stated as such, with what would confirm it.

---

# 1. Plain-English logic first

## 1.1 The headline answers, up front

1. **`condition` (op / voor / na) is never stored anywhere.** There is no column, no
   config field, no payload key that survives the request. It is read once, converted to a
   Dutch word, and **baked into the title string**. Every later reader — including the group
   bulk-edit screen — recovers it by running a regular expression over the title.

2. **`is_draft` does not hide anything from a customer.** In this SPA a draft photo is
   rendered to every viewer, including a customer, in a section literally headed
   "Draft Images". The only three things `is_draft` actually does are: stage photos in the
   completion modal, gate who may delete an attachment, and get flipped to published when
   somebody moves the record to status 4.

3. **The group workflow reaches "done" by a different road than the single-record
   workflow.** The single-record path goes 3 → 4 → 8 and publishes drafts at 4. The group
   bar's "Goedkeuren" button jumps 3 → 8 directly, so those records land in the invoicing
   pool with `approved_at = NULL` and any draft photos still hidden. Proved on live data:
   all eight members of group 17 are at status 8 with `approved_at` null.

4. **Nothing in this system is time-driven, and nothing escalates to a manager.**
   The application declares no scheduler at all. There is a fully translated
   `deadline_reminder` notification template in four languages that **nothing sends**.
   The only "scheduled" endpoint in the whole mail subsystem returns a hard-coded fake
   response with the warning `Queue system not implemented yet. This is a MOCK response.`

5. **The push-notification system is, in practice, down to one notification type.** Live
   data shows that since 2025-11-20 the only `push_notifications` row ever written for the
   admin user is `status_changed`. Comment, attachment, created and assignment
   notifications all stopped within a three-day window in November 2025, and the code
   explains why: the audience rule was swapped for one that does not include admins and
   almost certainly matches nobody at all.

## 1.2 What an ExtraWorkGroup actually is

A group is a **receipt for one batch-create click**, and nothing more.

When an operator uses the "multiple days" mode on the Extra Work create form, the browser
expands the chosen week/day/time grid into a flat list of `scheduled_entries` and posts it
to `POST /admin/extra-works/batch`. If there is more than one entry the server first creates
one `extra_work_groups` row, then creates N `extra_works` rows, each stamped with
`extra_work_group_id`, a `group_sequence` (1..N) and a `group_total` (N, frozen forever).

The group row itself carries almost nothing: a `building_id` (which is a **customer-building**
id, not a building id — the column name lies but the FK and the model relation are both
correct), a `year`, a `week_number`, an `is_auto_generated` flag that is always `true` and
that nothing ever reads, a `created_by`, and a `name` that the only writer always sets to
`null`.

Because `name` is always null, the group's display name is computed on the fly from the
**first member's title with the schedule suffix stripped off**. That accessor is used by one
endpoint and not the other, which is why the same group is called two different things in
two different screens (see 1.4).

**The member row with `group_sequence = 1` is the group header.** That single fact changes
what the list endpoint returns: a status filter that matches *any* member causes the header
row to be returned, even if the header itself has a different status. This is why the list
counts and the statistics counts do not agree (a fact tier-1 A1 already recorded).

There is **no transaction** around batch creation. The group is created first; if the loop
then throws, the group survives with zero members. Live data shows this has happened
repeatedly: **15 of the 19 group rows in the database have zero members.**

## 1.3 The `condition` field — op / voor / na

The create form lets the operator say, per time-slot, whether the work happens **at**
(`op`), **before** (`voor`) or **after** (`na`) a moment — in practice, before or after the
handover ("oplevering"). The browser sends `condition: 'at' | 'before' | 'after'`.

The server maps that to `op` / `voor` / `na` and concatenates it onto the title:

```
Adam verme a binasina [WK3-13.01.2026:00:00:op]
```

That is the entire lifecycle of the value. There is no `condition` column on `extra_works`,
none on `extra_work_groups`, none in the entity config, none in the portal SQL view. No
query filters on it, no report groups by it, no calculation changes because of it, no
notification mentions it. **It is a substring of a free-text title.**

The group bulk-edit screen then has to parse it back out of the title with a regex in order
to show the operator a dropdown — and when the operator saves, it re-generates the whole
suffix and writes the composed string back into `title`. So the *title column itself* is the
storage medium for four separate pieces of scheduling data (week number, date, time,
condition), all of which also exist as real columns except the condition.

**The suffix format changed at some point and the parser was never taught the old one.**
44 live records carry the old dash form `[WK45-03.11.2025:18:00-op]`; 27 carry the current
colon form `[WK3-13.01.2026:00:00:op]`. The bulk-edit regex only matches the colon form.
Every one of the 44 dash-form records is ungrouped, so the broken parse is currently
unreachable — but the ungrouped dash-form records are exactly the ones that carry the money
(records 433-476, the invoiced generation).

## 1.4 One group, two names, two titles

`GET /admin/extra-works` returns `group.name` — the **raw column**, which is always `null`,
so the grid falls back to `Groep #19 (Week 3)`.

`GET /admin/extra-works/groups/19` returns `group.name` = the **`display_name` accessor**,
which is derived from the first member's **translated** title. That accessor is
language-sensitive. Live, the same group is called all of these:

| language | group name |
|---|---|
| nl | `Geen toegang tot gebouwen (WK3)` |
| en | `No entry to buildings (WK3)` |
| tr | `Binalara giriş yasaktır (WK3)` |
| bg | `Няма достъп до сградите (WK3)` |

And the member titles come back translated too. `GET /admin/extra-works/553` (which
deliberately bypasses the translation accessor) returns the raw title
`Adam verme a binasina [WK3-12.01.2026:00:00:op]`, while `GET /admin/extra-works/groups/19`
returns `No entry to buildings [WK3-12.01.2026:00:00:op]` for the same record.

This matters because the **group bulk-edit modal reads the translated title and writes it
back into the raw column**. Touching any row in that modal permanently replaces the record's
stored title with the editing user's language variant.

## 1.5 Attachments: one table, four different meanings

`extra_works_attachments` is a join row: `extra_work_id` + `file_id` + three booleans and a
`comment_id`. The three booleans are not independent — they encode four mutually exclusive
kinds of file:

| kind | is_pre_file | is_comment | is_draft | who writes it |
|---|---|---|---|---|
| **Pre-file** — attached at creation time, "here is what needs doing" | true | false | false | `store` / `batchStore`, from the create form |
| **Post-file** — attached during the work, "here is what we did" | false | false | false | the Files tab's upload button |
| **Comment file** — attached to a chat message | false | **true** | false | `addComment`, `addCommentAttachment`, `addSystemComment` |
| **Draft file** — staged in the completion modal, awaiting approval | false | false | **true** | the completion modal only |

`is_pre_file` is a pure label. **Nothing branches on it.** It changes no permission, blocks
no button, decides no price, appears in no report and in no notification. Both the Files tab
and the approval modal use it only to sort files into two visual sections. The five query
scopes the model defines for it (`preFiles`, `workFiles`, `commentFiles`, `notDraft`,
`drafts`, `includingDrafts`) have **zero callers**.

`is_draft` is the only one of the three that gates anything, and it gates exactly two
things: (a) a non-admin may delete a draft attachment but not a published one, and (b) when
a record moves to status 4, every draft on it is flipped to published in one raw SQL update.
That flip is **one-way** — nothing un-publishes.

## 1.6 What the customer actually sees

Everything.

The Files tab receives `isCustomer` and uses it in exactly one place: to hide the delete
button. The "Draft Images" section is rendered above the pre-files and post-files sections,
to every viewer, with a `DRAFT` chip on each card. A customer opening an extra work at
status 3 sees the completion photos that the operator has not yet had approved.

Separately, the Files tab is fed `extraWork.attachments` from `GET /admin/extra-works/{id}`,
which returns **all** rows including `is_comment = true`. So every photo posted in the chat
also appears in the Files tab under "Post-files". On record 468, all five attachments are
comment attachments and all five will render twice in the UI.

The external customer portal (`portal.osius.nl` — proved by a live `uploaded_from: "portal"`
file whose URL points at that host) reads the `portal_extra_works` SQL view. **That view
selects no attachment columns and no group columns at all**, so whatever the portal shows,
it does not come from this table through that view.

## 1.7 Comments: an audit trail that nobody designed as one

`extra_work_comments` holds two completely different things in one list:

- **user comments** (`type = 'user'`) — actual chat, optionally threaded one level deep
  (`parent_comment_id`), optionally with files.
- **system comments** (`type` in `created`, `status_change`, `approved`, `system`) — written
  by the model's `updated` hook on every status change, and by `approveArchive` /
  `rejectArchive` / the conversion endpoints.

Because there is no state machine and no separate history table, **the comment list IS the
status history**. On record 468 the comment list is 27 entries long and 24 of them are
status changes, of which fourteen are `Voltooid → invoiced` / `invoiced → Voltooid` pairs —
the visible fingerprint of the invoice being created and removed seven times.

Three cosmetic-but-diagnostic details, all confirmed on live data:

- The message reads `Status Status gewijzigd:` — the word "Status" is duplicated in the
  source string.
- Status 9's label is the untranslated lowercase word `invoiced`, so the Dutch sentence
  reads `Status Status gewijzigd: Voltooid → invoiced`.
- The service that attaches a colour and icon to a status-change comment uses a regex that
  cannot match a multi-line comment. Every status change that carried extra detail lines
  (planning info, approval info, archive info) comes back with `color: null, icon: null`.

Deletion is soft but hand-rolled: the model imports Laravel's `SoftDeletes` trait and then
**never uses it**; instead there is an `is_deleted` boolean plus a manually written
`deleted_at`. Deleting a comment **hard-deletes** its attachment rows (the join rows, not
the files) with no recovery.

`mentioned_users` is validated on the way in, cast to an array, and stored. **Nothing reads
it.** No notification, no query, no UI. It is dead.

## 1.8 Unread tracking is a snapshot taken at write time

`extra_work_comment_reads` is not a "who has seen this" table. It is a **fan-out table
written once, when the comment is created**, with one row per user who was considered
"related" at that instant. The author's row is pre-marked as read; everyone else's `read_at`
is null.

Consequences that follow directly from that design:

- A user who gains access to a record **after** a comment was written will never have a row
  for it, so it can never be unread for them and `mark-read` on it silently updates zero
  rows.
- A user who loses access keeps their unread rows forever.
- The "related users" computation pushes `extra_works.created_by` into a list of user ids —
  but `created_by` is a `VARCHAR(100)` display name (`"B Amsterdam"`, `"<name> (Admin)"`).
  **The creator is therefore never in the fan-out.** (Tier-1 A1 found the same bug in the
  model; it exists a second time, independently, in `ExtraWorkService`.)
- The two copies of the function do not even agree on how to find admins: the model and the
  service look for role **`name` = 'admin'**; `updateStatus` and the dead service helper look
  for role **`slug` = 'admin'**.

## 1.9 Messages and InternalMessages: two inboxes, one row between them

There are two near-identical private-message systems, built four days apart:

- `messages` (created 2025-11-04) — user-to-user, optional `extra_work_id`, optional
  "also send as email", optional "also send a push".
- `internal_messages` (created 2025-11-08) — the same thing again, plus a `priority` level
  `urgent`, plus drafts, plus a middleware that blocks customers, plus a WhatsApp-style
  conversations view that can group by extra work.

Neither is wired into the Extra Work detail page. Live, user 1's `messages` inbox contains
**one** row, from 2025-11-05, whose subject is literally `"Extra Work #251"` and whose
`extra_work_id` is **null** — the link column was not used even in the one case where the
message was about an extra work. The `internal_messages` inbox is empty.

Meanwhile the front end still ships a `messageService.js` pointed at `/tickets/{id}/messages`
— a route family that **does not exist anywhere in this backend** — and the Melding detail
page uploads files by POSTing to a **hard-coded production URL**
`https://api.osius.nl/api/extra-works/{id}/messages`, carrying the current (dev) bearer
token to a different environment.

## 1.10 Notifications: three parallel systems that do not know about each other

| # | System | Storage | Delivery |
|---|---|---|---|
| 1 | `App\Services\Firebase\NotificationService` | writes a `push_notifications` row + one `push_notification_devices` row per device | Firebase Cloud Messaging, plus a Socket.IO `notification.user` broadcast |
| 2 | `App\Services\NotificationService` (a *different* class with the same short name) | **writes nothing** | `Redis::publish("private-user.{id}", ...)` straight to the socket server |
| 3 | Laravel broadcast events (`ExtraWorkCommentPosted`, `ExtraWorkStatusChanged`, `ExtraWorkUpdated`, `ExtraWorkAttachmentAdded`) | none | `broadcast(...)->toOthers()` on `PrivateChannel` |

System 2 and system 3 are the same objects: each of those four events calls system 2 **from
its own constructor**, as a side effect of being instantiated, before it is ever broadcast.

Only system 1 leaves a trace. The bell icon, the unread count, and the notification history
all read `push_notifications`. Anything that goes only through system 2 or 3 is invisible the
moment the user is offline. **Attachment notifications are exactly that**: adding a file
publishes to Redis and broadcasts, and writes no `push_notifications` row at all.

## 1.11 The sharp question, answered: is anything time-driven? does anything escalate?

**No, and no.**

- `routes/console.php` is eight lines and contains only Laravel's stock `inspire` command.
- `bootstrap/app.php` contains no `->withSchedule(...)`.
- There is no `app/Console/Kernel.php`.
- `app/Console/Commands/` contains three commands — `ProcessIncomingMail`,
  `RecalculateGradesScores`, `VerifyInspectionScore` — none of them scheduled, none of them
  notification-producing.
- `app/Jobs/` contains three jobs — `AutoTranslateJob`, `AutoTranslateCommentJob`,
  `AutoTranslateExtraWorkJob`. All three are translation. None is a reminder.
- `app/Observers/` contains seven observers. All seven fire on model events only.

The intent was clearly there once. `config/notifications.php` carries a fully translated
`deadline_reminder` template in nl/en/tr/bg ("De deadline voor deze taak nadert" / "The
deadline for this task is approaching"). **Zero code paths reference it.** The same is true
of `approval_requested`, `assigned_to_work`, `extra_work_approved` and `extra_work_rejected`
— five of the twelve configured templates are unreachable.

The only endpoint in the system with "schedule" in its name,
`POST /admin/mail/bulk/schedule`, validates a `send_at` date and then returns a fabricated
job id with `'mock_mode' => true` and the warning that the queue system is not implemented.

**Nothing escalates.** There is no manager-notification path of any kind. The closest thing
is `updateStatus`'s fan-out, which notifies *everyone* — all UCB holders, all assignees,
everyone in the same user department, and all admins — for every status change equally. It
is a broadcast, not an escalation: nobody is notified *because* somebody else failed to act.

The practical consequence, combined with tier-1 A1's finding that no date on an extra work
is ever compared to the clock: **an extra work that is never touched again is never
mentioned again.** No reminder, no ageing, no chase, no manager alert. It simply sits there.

## 1.12 The shortest list of things that are broken or dead in my area

- `extra_work_groups.is_auto_generated` — written `true` always, read by nothing. **DEAD.**
- `extra_work_groups.name` — writer always passes `null`. Effectively **DEAD**.
- `extra_work_groups.building_id` — written, and the `building()` relation exists, but the
  relation is never called and no query filters on it. **DEAD as a read.**
- `condition` — never persisted; lives only inside the title string.
- `extra_work_comments.mentioned_users` — written and validated, read by nothing. **DEAD.**
- All 6 query scopes on `ExtraWorkAttachment` and all 4 on `ExtraWorkComment` — **0 callers.**
- `ExtraWorkService::getNotificationRecipients()` and `sendNotificationToUsers()` (130 lines,
  a complete second recipient rule) — **0 callers.**
- `NotificationService::sendMeldingNotification / sendExtraWorkNotification /
  sendCommentNotification / sendStatusChangeNotification` — **0 callers.**
- `ExtraWorkActivityLogger::logCommentAdded / logCommentRemoved / logAttachmentAdded /
  logAttachmentRemoved` — **0 callers.** Comments and files never reach the activity log.
- `MailService::sendToTicketCustomers()` and `MailController::sendTicketNotification()` — both
  reference `App\Models\Ticket`, which does not exist, and `sendTicketNotification` has **no
  route**. **DEAD.**
- `GET /admin/extra-works/{id}/attachments?file_type=…` — **500**, the column was dropped in
  October 2025 and the filter was not.
- `ExtraWorkFilesTab.fetchAttachments()` unwraps the response as if it were a bare array;
  the API returns an object. When the tab fetches for itself it always shows zero files.
- `ExtraWorkService::deleteCommentAttachment()` writes `'file_name' => $fileName` where
  `$fileName` is never defined.
- `ExtraWorkAttachment::uploadedBy()` points at a `created_by` column that does not exist on
  the table; the broadcast payload's `uploaded_by` is always null and the notification always
  says the uploader was "System".
- Two separate migrations add the same six translation columns to `extra_work_comments`, two
  days apart, neither guarded — a clean `migrate` cannot run.
- `GET /admin/extra-works/{id}/comments` ignores `page` and `per_page` entirely while the UI
  sends them and pages on the result. Clicking "Load more" duplicates the whole list.

---

# 2. Evidence — read/write maps

## 2.1 `extra_work_groups`

### The table

*CODE — `database/migrations/2025_12_23_100800_create_extra_work_groups_table.php:16-27`:*

```php
Schema::create('extra_work_groups', function (Blueprint $table) {
    $table->id();
    $table->unsignedBigInteger('building_id')->nullable();
    $table->string('name')->nullable();
    $table->unsignedSmallInteger('year')->nullable();
    $table->unsignedTinyInteger('week_number')->nullable();
    $table->boolean('is_auto_generated')->default(true);
    $table->unsignedBigInteger('created_by')->nullable();
    $table->timestamps();

    $table->foreign('building_id')->references('id')->on('customer_buildings')->nullOnDelete();
    $table->foreign('created_by')->references('id')->on('users')->nullOnDelete();
    $table->index(['building_id', 'year', 'week_number']);
});
```

Note the FK: `building_id` references **`customer_buildings`**, and the model agrees —
*CODE `app/Models/ExtraWorkGroup.php:41`:* `return $this->belongsTo(CustomerBuilding::class, 'building_id');`
The column name is misleading but the value written by `batchStore` is correct. See §4 for
the correction to tier-1 A1 on this point.

There is **no `SoftDeletes`** on this model. `bulkDeleteGroup` hard-deletes the row.

### Field map

**`extra_work_groups.id`**
- WRITTEN BY: auto.
- READ BY: `extra_works.extra_work_group_id`; `GET /admin/extra-works/groups/{id}`;
  `PUT /admin/extra-works/groups/{id}/status`; `DELETE /admin/extra-works/groups/{id}`;
  `ExtraWorkV2.legacyGroup()` (`app/Models/ExtraWorkV2.php:332`, `legacy_extra_work_group_id`).
- GATES: whether the detail page renders a group card and a group action bar.

**`extra_work_groups.building_id`**
- WRITTEN BY: `ExtraWorksController::batchStore` only.
  *CODE `:5957-5964`:* `'building_id' => $customerBuildings[0] ?? null,`
  — i.e. the **first** selected customer-building; the rest are dropped.
- READ BY: **nothing.** `ExtraWorkGroup::building()` is defined and never called
  (`grep -rn "ExtraWorkGroup" app/` returns four hits, all of them `create`/`with`/`findOrFail`).
  No group payload emits it.
- IF NULL: nothing changes.
- **DEAD as a read.**

**`extra_work_groups.name`**
- WRITTEN BY: `batchStore` only, always `null`.
  *CODE `:5959`:* `'name' => null, // Will use display_name accessor`
- READ BY: two places, and they disagree.
  - `ExtraWorksController::transformModelData:542` — `'name' => $model->group->name,` — the
    **raw column**, so always null on the list endpoint.
    *DATA — `GET /admin/extra-works?per_page=100`, record 553:*
    `"group": {"id": 19, "name": null, "year": 2026, "week_number": 3, "item_count": 12, ...}`
  - `ExtraWorksController::getGroupMembers:6158` — `'name' => $group->display_name,` — the
    **accessor**, which is never null.
- IF NULL: `getDisplayNameAttribute` falls through to the first member's title minus the
  `[WK…]` suffix, plus ` (WK{n})`; if there are no members it returns `Groep #{id}`.
  *CODE `app/Models/ExtraWorkGroup.php:63-76`:*
  ```php
  $firstWork = $this->extraWorks()->first();
  if ($firstWork) {
      $title = preg_replace('/\s*\[WK\d+-.*\]$/', '', $firstWork->title);
      return $title . ' (WK' . $this->week_number . ')';
  }
  return 'Groep #' . $this->id;
  ```
  `$firstWork->title` goes through the translation accessor.
- GATES: the group card's label in the detail header
  (`ExtraWorkDetailHeader.jsx:334-340`, which prefers `name`, then `Wk{n} - {year}`), and
  the group chip in the list grid (`ExtraWorkDataGrid.jsx:679-680`,
  `` group.name || `Groep #${group.id} (Week ${group.week_number})` ``).
- **Effectively DEAD as a column; the accessor carries all the meaning.**

**`extra_work_groups.year` / `week_number`**
- WRITTEN BY: `batchStore` from the **first** entry only.
  *CODE `:5960-5961`:* `'year' => $firstEntry['year'] ?? now()->year,`
  `'week_number' => $firstEntry['weekNumber'] ?? now()->weekOfYear,`
- READ BY: `getGroupMembers` payload; `transformModelData`'s `group` block; the display-name
  accessor; `GroupBulkEditModal`'s `generateTitleSuffix` (it uses `groupData.group.week_number`
  as the week for **every** row's regenerated suffix).
- **This is a real defect in the group bulk-edit path.** Group 19 spans weeks 3, 4 and 5
  (DATA: member titles `[WK3-…]`, `[WK4-…]`, `[WK5-…]`) but the group's `week_number` is 3.
  Saving a row in the bulk-edit modal rewrites its suffix with `WK3` regardless of the row's
  actual date.
  *CODE — `GroupBulkEditModal.jsx:87-105`:* `const wk = weekNumber || getWeek(dateObj, {weekStartsOn: 1});`
  — the group's week wins over the row's own date.
- GATES: the regenerated title suffix; the group's fallback display name.

**`extra_work_groups.is_auto_generated`**
- WRITTEN BY: `batchStore`, hard-coded `true` (`:5962`).
- READ BY: **nothing.** `grep -rn "is_auto_generated" app/` returns only
  `ExtraWorkGroup.php:17` (`$fillable`), `:22` (`$casts`) and the unrelated `PrjPlanGroup`.
- **DEAD.**

**`extra_work_groups.created_by`** (a real integer FK, unlike `extra_works.created_by`)
- WRITTEN BY: `batchStore` (`:5963`, `$user?->id`).
- READ BY: `createdUser()` relation is defined and **never called**; not in any payload.
- **DEAD as a read.**

### The group columns on `extra_works`

**`extra_work_group_id`, `group_sequence`, `group_total`**
- WRITTEN BY: `batchStore` only (`:6015-6017`). None of the three is in the entity config's
  `fields` allow-list, so `PUT /admin/extra-works/{id}` cannot change them.
- READ BY:
  - `buildQuery`'s group-aware status filter (`:110-136`) — `group_sequence = 1` is the
    header test.
  - `transformModelData` (`:540-580`) — emits `group`, `group_sequence`, `group_total`, and
    for headers a `status_distribution`.
  - `getGroupMembers`, `bulkUpdateGroupStatus`, `bulkDeleteGroup`.
  - `ExtraWork::groupSiblings()` (`app/Models/ExtraWork.php:368-375`) — defined, **no callers**.
  - The SPA: `ExtraWorkDataGrid` expand/collapse, the detail header's group card, the group
    action bar, both group modals.
- IF NULL: `transformModelData` sets `data['group'] = null` and the record renders as a
  normal standalone row.
- GATES: **`group_sequence == 1` changes which rows a status filter returns** — this is the
  group-header inflation that makes list totals and statistics totals disagree.
- `group_total` is frozen at creation. If a member is deleted it is not decremented.
  *DATA:* group 19's members all carry `group_total: 12` and `item_count` is also 12; group
  18's members carry `group_total: 3` with `item_count` 3. No divergence yet on live data,
  but nothing maintains it.

### Three different member counts, computed three different ways

| value | how | excludes soft-deleted? |
|---|---|---|
| `group_total` | frozen integer written at batch time | n/a — never updated |
| `group.item_count` | `$model->group->extraWorks()->count()` (Eloquent) — `:545`, `:6161` | **yes** |
| `group.status_distribution` counts | `\DB::table('extra_works')->join(...)->groupBy(...)` — `:550-563`, `:6131-6145` | **no** — a raw query-builder select bypasses the `SoftDeletes` global scope |

So after a member is soft-deleted, `item_count` drops but the status distribution does not,
and the two group summaries on the same screen disagree.
*CODE — `ExtraWorksController.php:6131-6133`:*
```php
$statusDistribution = \DB::table('extra_works')
    ->join('t_ticket_status as ts', 'extra_works.status_id', '=', 'ts.id')
    ->where('extra_works.extra_work_group_id', $groupId)
```
No `whereNull('deleted_at')`.

### Live group inventory

*DATA — `GET /admin/extra-works/groups/{n}` for n = 1..21:*

| group | members | name | year/week | status distribution |
|---|---|---|---|---|
| 1-15 | **0** | `Groep #n` | 2025 / 52 | empty |
| 16 | 4 | `deneme-1 (WK52)` | 2025 / 52 | 1 → 4 |
| 17 | 8 | `deneme K-1 (WK52)` | 2025 / 52 | 8 → 8 |
| 18 | 3 | `Deneme (WK52)` | 2025 / 52 | 4 → 1, 1 → 2 |
| 19 | 12 | `No entry to buildings (WK3)` | 2026 / 3 | 1 → 10, 2 → 2 |
| 20, 21 | 404 | — | — | — |

**Fifteen orphaned group rows out of nineteen.** Groups 1 and 2 were created 10 seconds
apart (`2025-12-23T10:46:42` and `10:46:52`). `batchStore` creates the group before the
member loop and is not wrapped in a transaction:

*CODE — `ExtraWorksController.php:5952-5966`:* the `ExtraWorkGroup::create([...])` call sits
outside any `DB::transaction()`; the `foreach ($scheduledEntries as $entry)` loop that
follows can throw into the method's own `catch`, which returns a 500 and leaves the group.

**INFERRED:** groups 1-15 are the residue of failed or abandoned batch-create attempts.
*To confirm:* `SELECT g.id, g.created_at, COUNT(ew.id) FROM extra_work_groups g LEFT JOIN
extra_works ew ON ew.extra_work_group_id = g.id GROUP BY g.id;` including soft-deleted rows —
if the soft-deleted count is also zero, nothing was ever created for them.

### The three group write endpoints

**`POST /admin/extra-works/batch`** — `ucb.permission:extra_works,create` (`routes/api.php:704`).
No validation rules of any kind on `scheduled_entries` beyond "not empty". The per-entry
`date`, `time`, `weekNumber`, `year`, `condition` keys are read with `??` defaults and
`Carbon::parse` — a malformed `date` throws and 500s the whole batch, after the group row
has already been written.

One more defect in that loop: files are read from the **request**, not the entry, inside the
per-entry loop:
*CODE — `:6065-6076`:*
```php
$files = $request->input('files', []);
if (!empty($files)) {
    foreach ($files as $file) {
        $fileId = is_array($file) ? ($file['id'] ?? null) : $file;
        if ($fileId) {
            \App\Models\ExtraWorkAttachment::create([
                'extra_work_id' => $extraWork->id,
                'file_id' => $fileId,
                'is_pre_file' => $file['is_pre_file'] ?? 1,
            ]);
```
so **every uploaded file is attached to every record in the batch** — a 12-entry batch with
3 photos creates 36 attachment rows pointing at 3 files. And if `$file` is a bare integer,
`$file['is_pre_file']` on an int is a PHP warning evaluating to null. The SPA always sends
the array form (`add.jsx:920, 943` — `{id, is_pre_file: 1}`), so only the fan-out happens in
practice.

**`PUT /admin/extra-works/groups/{groupId}/status`** — `ucb.permission:extra_works,update`.
*CODE — `:6247-6254`:*
```php
$query = ExtraWork::where('extra_work_group_id', $groupId);
if ($sourceStatusId) {
    $query->where('status_id', $sourceStatusId);
}
$updatedCount = $query->update(['status_id' => $newStatusId]);
```
`$newStatusId` is **not validated** against `t_ticket_status`. A mass `update()` bypasses
Eloquent events entirely: no `*_by` stamp, no `*_at` stamp, no system comment, no broadcast,
no FCM, no activity row, no draft publication.

Its **only caller** is `GroupEditModal.jsx:112`, which sends `{status_id}` and **never**
`source_status_id` — so the whole group is moved to one status regardless of where each
member was.

**`DELETE /admin/extra-works/groups/{groupId}`** — `ucb.permission:extra_works,delete`.
*CODE — `:6344-6349`:*
```php
$group = \App\Models\ExtraWorkGroup::findOrFail($groupId);
$deletedCount = ExtraWork::where('extra_work_group_id', $groupId)->delete();
$group->delete();
```
Members are **soft**-deleted; the group row is **hard**-deleted. Because the FK is
`nullOnDelete`, MySQL then nulls `extra_work_group_id` on the (soft-deleted) members, so
restoring them would produce orphans with a `group_sequence` and `group_total` but no group.
There is **no status check** — a group containing status-8 or status-9 records can be
deleted this way, unlike `bulkDelete` which refuses anything that is not status 1
(`:6294-6301`).

Neither `getGroupMembers` nor `bulkUpdateGroupStatus` nor `bulkDeleteGroup` applies the
UCB scope filter — each starts from `ExtraWorkGroup::findOrFail($groupId)` / a bare
`ExtraWork::where(...)`, exactly like the other unscoped endpoints tier-1 A1 listed.

## 2.2 `condition` — the complete footprint

### Backend

`grep -rn "'condition'" app/ config/ database/ routes/` returns 16 hits. Fifteen are
unrelated (`PermissionMetadataController`'s `'condition'` metadata type, and the
`config/*/extra-works.php` `bulk_actions` blocks whose `'condition' => "status_id IN (1,2,3)"`
strings are display rules for buttons, not this field).

**The one hit that is this field:**

*CODE — `app/Http/Controllers/Admin/ExtraWorksController.php:5988-5998`:*
```php
// Get condition label in Dutch
$conditionLabel = match($entry['condition'] ?? 'at') {
    'before' => 'voor',
    'after'  => 'na',
    default  => 'op',
};

// Build title with schedule suffix
$baseTitle = $entry['title'] ?? $request->input('title', 'Extra Work');
$scheduleSuffix = " [WK{$entry['weekNumber']}-{$scheduleDate->format('d.m.Y')}:{$entry['time']}:{$conditionLabel}]";
$fullTitle = $baseTitle . $scheduleSuffix;
```

`$conditionLabel` is used once, in the string on the next line, and then goes out of scope.
`$entry['condition']` is never assigned to a model attribute.

- **WRITTEN BY:** nothing persists it. There is no `condition` column on `extra_works`, on
  `extra_work_groups`, or in the `portal_extra_works` view (I read the full column list of
  the view — see §2.7).
- **READ BY (server):** nothing. No filter, no report, no grouping, no price rule, no
  notification.
- **IF EMPTY:** the `match` default gives `op`. The operator cannot tell "explicitly at" from
  "not specified".
- **GATES:** nothing.
- **DEAD as data; alive only as five characters of the title.**

### Frontend

`grep -rn "condition" src/` (excluding the unrelated permission-condition UI and vendor docs)
gives exactly three areas:

**(a) Producer — the v1 create form.**
*CODE — `src/pages/finalosius/extra-works/add.jsx:993-1000`:*
```js
allScheduledEntries.push({
  date: day.date,
  time: timeSlot.time || '00:00',
  condition: timeSlot.condition || 'at',
  weekNumber: week.week_number,
  ...
```
The values are `'at' | 'before' | 'after'`, chosen in `EditDayModal.jsx` (`conditionOptions`,
`:91`) and stored per time-slot in `ScheduleDaysModal.jsx`'s
`{ date: [{ time, condition }] }` shape (`:51`).

**(b) Preview — the same file renders the Dutch label locally, duplicating the server's map.**
*CODE — `add.jsx:1800-1801`:*
```js
const conditionLabel = timeSlot.condition === 'at' ? 'op' :
                       timeSlot.condition === 'before' ? 'voor' : 'na';
```

**(c) The only consumer — `GroupBulkEditModal`, which re-derives it from the title.**
*CODE — `GroupBulkEditModal.jsx:61-65, 87-118`:*
```js
const CONDITION_LABELS = { op: 'op', na: 'na', voor: 'voor' };
...
const cond = CONDITION_LABELS[condition] || 'op';
return `[WK${wk}-${dateStr}:${timeStr}:${cond}]`;
...
const extractBaseTitle = (title) =>
  title.replace(/\s*\[WK\d+-[\d.]+:\d{2}:\d{2}:\w+\]\s*$/, '').trim();
const extractCondition = (title) => {
  const match = title.match(/\[WK\d+-[\d.]+:\d{2}:\d{2}:(\w+)\]/);
  return match ? match[1] : 'op';
};
```
Note the vocabulary flip: the modal's dropdown values are the **Dutch** `op` / `na` / `voor`
(`:1161-1173`), while the create form's are the **English** `at` / `before` / `after`. The
two never meet because the modal parses from the title, not from the API.

**The regex only matches the current suffix format.** DATA, from a scan of all 76 live
titles:

| separator before the condition | condition | count |
|---|---|---|
| `-` (old) | `op` | 35 |
| `-` (old) | `na` | 8 |
| `-` (old) | `voor` | 1 |
| `:` (current) | `op` | 26 |
| `:` (current) | `na` | 1 |

All 44 old-format records have `extra_work_group_id = null`; all 27 current-format records
belong to groups 16-19. So the parse failure is currently unreachable from the UI — but if
one of those 44 records were ever put in a group, `extractBaseTitle` would fail to strip and
`getFullTitle` would append a second suffix on save. Example old-format title, DATA:
record 468 — `The Wiechert eindschoonmaak  [WK48-24.11.2025:12:00-voor]`.

**INFERRED:** the dash format was produced by an earlier client-side per-record loop (the
records are ungrouped and dated Nov 2025, before the group migration of 2025-12-23), and the
colon format by the current `batchStore`. *To confirm:* the git history of
`ExtraWorksController::batchStore` and of `add.jsx`, which I do not have.

## 2.3 `extra_works_attachments`

### The table's history

There is no `CREATE TABLE extra_works_attachments` migration; the table predates the
migration set, like `extra_works` itself. Four migrations reshape it:

| migration | change |
|---|---|
| `2025_10_18_035142_update_extra_works_attachments_use_file_id.php:20-56` | **drops** `file_name`, `file_path`, `thumbnail_path`, `thumbnail_guid`, `file_type`, `mime_type`, `file_size`, `display_name`, `uploaded_by`; **adds** `file_id` (FK `files`, cascade) |
| `2025_10_18_050703_…` | rebuilds the separate `extra_work_comment_attachments` table on `file_id` |
| `2025_10_18_120214_add_comment_fields_to_extra_works_attachments.php:18-25` | adds `is_comment` boolean default false, `comment_id` nullable FK → `extra_work_comments` **ON DELETE CASCADE**, index |
| `2025_11_04_154403_drop_extra_work_comment_attachments_table.php` | drops the separate comment-attachment table — comment files now live here with `is_comment = true` |
| `2025_11_04_211044_add_draft_columns_to_extra_works_and_attachments.php:14-18` | adds `is_draft` boolean default false + index |

`is_pre_file` has **no migration in this repo** — it predates the set. Its default is
therefore unknown from the repo; the model casts it to boolean and every writer supplies it
explicitly.

**Consequence of the October drop that is still live in the code:**

- `ExtraWorkAttachment::uploadedBy()` — *CODE `app/Models/ExtraWorkAttachment.php:46-49`:*
  `return $this->belongsTo(User::class, 'created_by');` — there is no `created_by` column
  (grep of all 289 migrations for `created_by` on this table returns nothing, and the live
  JSON has no such key). The relation resolves to null.
  *DATA — `GET /admin/extra-works/468/attachments`, attachment 456:* the object's keys are
  exactly `id, extra_work_id, file_id, is_pre_file, is_comment, is_draft, comment_id,
  created_at, updated_at, file` — no `created_by`, no `uploaded_by`.
  Downstream: `ExtraWorkAttachmentAdded.php:88` — `$userName = $this->attachmentData['uploaded_by']['name'] ?? 'System';`
  → **every attachment notification says "System" uploaded the file.**
- `ExtraWorkService::getAttachments` still offers a `file_type` filter on the dropped column.
  *CODE `app/Services/ExtraWorkService.php:142-144`:*
  ```php
  if ($fileType) {
      $query->where('file_type', $fileType);
  }
  ```
  *DATA — `GET /admin/extra-works/468/attachments?file_type=image`:*
  `{"success":false,"error":{"code":"QUERY_ERROR","details":"SQLSTATE[42S22]: Column not found: 1054 Unknown column 'file_type' in 'where clause' …"}}`
  **500.** The parameter is documented in the controller's own log line (`:1560`).
- `ExtraWorkCommentPosted.php:66-74` builds its broadcast attachment payload from
  `$attachment->file_name`, `->file_size`, `->file_type`, `->mime_type` — all four dropped.
  Every websocket comment payload carries four nulls.

### `is_pre_file` — full map

**WRITTEN BY**

| writer | value | when |
|---|---|---|
| `ExtraWorksController::store` — `:746, :756` | `$fileData['is_pre_file'] ?? 1` | create form, `files: [{id, is_pre_file: 1}]` (`add.jsx:920, 943`) |
| `ExtraWorksController::store` legacy branch — `:633` | `1` | request keys `file1`..`file4` |
| `ExtraWorksController::store` — `:864` | `false` | files re-linked to the auto-created comment |
| `ExtraWorksController::batchStore` — `:6072` | `$file['is_pre_file'] ?? 1` | batch create |
| `ExtraWorkService::addAttachments` — `:191` | `$attachmentData['is_pre_file'] ?? false` | `POST /{id}/attachments` |
| `ExtraWorkService::addAttachment` (deprecated) — `:228` | `$data['is_pre_file'] ?? true` | **note the opposite default** |
| `ExtraWorkService::addComment` — `:326` | `false` | comment files |
| `ExtraWorkService::addCommentAttachment` — `:490` | `false` | `POST /{id}/comments/{cid}/attachments` |
| `ExtraWork::addSystemComment` — `app/Models/ExtraWork.php:795` | `false` | system-comment images |
| SPA Files tab — `ExtraWorkFilesTab.jsx:321` | `0` | manual upload on the detail page |
| SPA approval modal — `ExtraWorkApprovalModal.jsx:174` | `0` | approval photos |
| SPA completion modal — `ExtraWorkCompletionModal.jsx:196` | `0` | completion photos |

**READ BY**

| reader | what it does |
|---|---|
| `GET /{id}/attachments?is_pre_file=` — `ExtraWorksController:1567`, `ExtraWorkService:146-148` | an optional list filter, never used by the SPA |
| `ExtraWorkFilesTab.jsx:400-402` | splits the grid into "Pre-files" / "Post-files" sections |
| `ExtraWorkApprovalModal.jsx:133` | `att.is_pre_file === 0 \|\| === false` → "completion images" preview |
| `ExtraWorkAttachmentAdded.php:44` | echoed into the broadcast payload |
| scopes `preFiles()` / `workFiles()` — `ExtraWorkAttachment.php:85-93` | **0 callers** |

**IF NULL/EMPTY:** the model casts it to boolean, so null reads as false → the file lands in
"Post-files".

**GATES:** nothing. No button, no transition, no price, no permission, no report, no
notification, no invoice. Purely a visual grouping.

**Not dead, but inert** — it is written by eleven code paths and read only to decide which
of two headings a thumbnail appears under.

### `is_draft` — full map

**WRITTEN BY (set to true)**

Exactly one path in the whole system:
*CODE — `src/pages/finalosius/extra-works/modals/ExtraWorkCompletionModal.jsx:193-198`:*
```js
uploadedFileIds.push({
  id: uploadResult.data.file_id,
  is_pre_file: 0,
  is_draft: 1 // Draft file
});
...
await apiClient.post(`/admin/extra-works/${extraWork.id}/attachments`, { files: uploadedFileIds });
```
accepted by
*CODE — `ExtraWorksController::addAttachment:1617-1622`:*
```php
$validated = $request->validate([
    'files' => 'required|array|min:1',
    'files.*.id' => 'required|exists:files,id',
    'files.*.is_pre_file' => 'nullable|boolean',
    'files.*.is_draft' => 'nullable|boolean',
]);
```
and stored by `ExtraWorkService::addAttachments:192` — `'is_draft' => $attachmentData['is_draft'] ?? false,`.

Note that this is a **client-declared** flag with no server-side rule: any caller with
`extra_works,update` may create a published file, or a draft file, at any status.

**WRITTEN BY (set to false — i.e. published)**

One path, and it is a raw SQL update that runs as a side effect of a status change:
*CODE — `ExtraWorksController::update:1285-1296`:*
```php
// If approved (status_id=4 OR approved_at set), publish all draft attachments
if (($request->has('status_id') && $request->input('status_id') == 4) ||
    ($request->has('approved_at') && $request->input('approved_at'))) {
    \DB::table('extra_works_attachments')
        ->where('extra_work_id', $id)
        ->where('is_draft', true)
        ->update([
            'is_draft' => false,
            'updated_at' => now()
        ]);
```
A second, identical block exists at `:1316-1330` but is unreachable whenever `$autoFields`
is non-empty, because the first block's branch `return`s at `:1303`.

There is **no un-publish path.** `is_draft` is a one-way latch. The "Terugdraaien" (revert)
button that walks a record from 4 back to 3 does not restore the drafts.

**READ BY**

| reader | effect |
|---|---|
| `ExtraWorksController::deleteAttachment:1673-1683` | **the only permission gate.** `if (!$attachment->is_draft) { … only role slug 'admin' may delete … }` |
| `ExtraWorkService::getAttachments:150-152` + `ExtraWorksController:1568` | optional `?is_draft=` list filter |
| `ExtraWorkCompletionModal.jsx:75-90` | fetches the record's attachments and keeps only `is_draft` ones, to show the operator what is already staged |
| `ExtraWorkFilesTab.jsx:121-123` | the chip label: `file.is_draft ? 'DRAFT' : (file.is_pre_file ? 'PRE-FILE' : 'POST-FILE')` |
| `ExtraWorkFilesTab.jsx:400` | `draftFiles` → its own "Draft Images" section, rendered to everyone |
| scopes `notDraft()` / `drafts()` / `includingDrafts()` | **0 callers** |

**IF NULL/EMPTY:** boolean cast → false → published.

**GATES:** (a) deletion permission, (b) the completion modal's staging list, (c) which
heading the thumbnail appears under. **It gates no visibility.**

**What the customer sees, precisely.** `isCustomer` is computed in
*CODE — `detail.jsx:186-189`:*
```js
const userRole = sessionUser?.role?.name || sessionUser?.role || sessionUser?.role_type;
return userRole === 'customer';
```
and passed down to the Files tab (`:1405`). Inside the tab it is used in exactly one place —
*CODE `ExtraWorkFilesTab.jsx:186`:* `{!isCustomer && (` — wrapping the delete icon. The
draft section (`:443-470`) has no `isCustomer` guard. A customer therefore sees every draft
photo, with a `DRAFT` chip on it.

**Live state:** every attachment on every record I could reach has `is_draft: false`.
*DATA — `GET /admin/extra-works/{468,549,475}/attachments?is_draft=1` → `total_count: 0` for
all three.* So there is currently no draft in the system to be leaked; the exposure is
structural, not realised. **INFERRED** that no record is currently mid-completion.

### `is_comment` and `comment_id`

**WRITTEN BY:** `ExtraWorkService::addComment:326-329`, `addCommentAttachment:488-493`,
`ExtraWork::addSystemComment:793-799`, and `ExtraWorksController::store:860-868` (which
attaches the create-form files to the auto-generated `created` comment and then sets that
comment's `has_attachments`). All four write `is_comment => true` **and** `is_pre_file => false`.

**READ BY:** `ExtraWorkComment::attachments()` (`app/Models/ExtraWorkComment.php:81-85`,
`hasMany(ExtraWorkAttachment, 'comment_id')->where('is_comment', true)`);
`deleteComment` / `deleteCommentAttachment`; the `has_attachments` recount
(`ExtraWorkService:521-527`); the broadcast payload. **Not read by the Files tab** — which is
why comment photos also show up there.

**GATES:** nothing beyond which relation returns the row.

**Cascade:** `comment_id` is `ON DELETE CASCADE` on `extra_work_comments.id`. But comment
deletion is a **soft** flag (`is_deleted`), so the cascade never fires; instead
`ExtraWorkService::deleteComment:442-446` hard-deletes the attachment rows by hand:
```php
ExtraWorkAttachment::where('extra_work_id', $extraWorkId)
    ->where('comment_id', $commentId)
    ->where('is_comment', true)
    ->delete();
```
The `files` rows survive; only the join rows go. A "soft-deleted" comment therefore loses its
photos irreversibly.

### The attachment model's own event

*CODE — `app/Models/ExtraWorkAttachment.php:59-79`:*
```php
protected static function booted()
{
    static::created(function ($attachment) {
        try {
            broadcast(new \App\Events\ExtraWorkAttachmentAdded($attachment))->toOthers();
```
This fires on **every** attachment row — pre-file, post-file, draft, comment file, and system
comment file alike. There is no filter. Creating an extra work with three photos broadcasts
three attachment events plus the created event; a batch of 12 with 3 photos broadcasts 36.

It writes **no `push_notifications` row** (the event's `sendNotifications()` calls
`App\Services\NotificationService::sendToUsers`, the Redis-only class). So an attachment is
invisible in the notification bell and in the history.

### Attachment endpoints and their permissions

| method + path | controller | permission | notes |
|---|---|---|---|
| GET `/{id}/attachments` | `getAttachments` | `extra_works,view` | `?file_type=` 500s; `?is_pre_file=`/`?is_draft=` work |
| POST `/{id}/attachments` | `addAttachment` | `extra_works,update` | the only validated attachment write |
| DELETE `/{id}/attachments/{aid}` | `deleteAttachment` | `extra_works,update` + an in-controller admin check for non-drafts | |
| POST `/{id}/comments/{cid}/attachments` | `addCommentAttachment` | `extra_works,update` | accepts `file_id` **or** `guid` |
| DELETE `/{id}/comments/{cid}/attachments/{aid}` | `deleteCommentAttachment` | `extra_works,update` | the only file operation that writes an activity row — and it references an undefined `$fileName` |

*CODE — `routes/api.php:728-731, 753-758`.*

**Every one of these carries `ucb.permission:extra_works,*`** — including when the record is a
Melding, because the `/admin/meldings` prefix has only ten routes (`routes/api.php:675-690`)
and none of them is an attachment or comment route. A user holding `melding,update` but not
`extra_works,update` cannot attach a file to a Melding at all; a user holding
`extra_works,update` but not `melding,*` can. **Cross-module permission crossing — handoff to
the RBAC agent.**

*CODE — `ExtraWorkService::deleteCommentAttachment:529-541`:*
```php
DB::table('extra_work_activities')->insert([
    ...
    'metadata' => json_encode([
        'comment_id' => $commentId,
        'file_name' => $fileName,      // $fileName is never assigned in this method
    ]),
```
Under PHP 8 this is a warning and stores `null`.

### The Files tab's own fetch is broken

*CODE — `ExtraWorkFilesTab.jsx:257-260`:*
```js
const response = await apiClient.get(`/admin/extra-works/${extraWorkId}/attachments`);
if (response.success && response.data) {
    const rawAttachments = Array.isArray(response.data) ? response.data : [];
```
*DATA — the endpoint returns* `{"success":true,"message":"…","data":{"attachments":[…],"total_count":5}}`.
`response.data` is an object, so `rawAttachments` is always `[]`.

The tab is normally saved by the parent, which passes `attachments={extraWork.attachments}`
from `GET /admin/extra-works/{id}` (`detail.jsx:1403`) and takes the `attachmentsProp` branch
(`:221-247`). But `useImperativeHandle` exposes `refresh: fetchAttachments` (`:255`), so **the
programmatic refresh after an upload empties the grid** until the page is reloaded.
The completion modal, by contrast, reads it correctly:
*CODE — `ExtraWorkCompletionModal.jsx:73`:* `const rawAttachments = response.data.attachments || [];`

## 2.4 Comments, comment reads, and the observer

### `extra_work_comments`

No create migration (predates the set). Two migrations add the **same six translation
columns**, two days apart, **neither guarded**:

*CODE — `2025_11_02_100458_add_translation_columns_to_extra_work_comments_table.php:14-24`* adds
`comment_nl, comment_en, comment_tr, comment_bg, original_language, translate_meta`.
*CODE — `2025_11_04_150909_add_translation_columns_to_extra_work_comments_table.php:14-25`* adds
`original_language, comment_tr, comment_en, comment_nl, comment_bg, translate_meta`.

Same six columns, same table, different `after()` ordering, no `Schema::hasColumn` check on
either. A clean `php artisan migrate` cannot complete. **Schema anomaly — handoff to the
DBA/migration owner, alongside the `summary_subtitle` pair tier-1 A2 reported.**

The model's own accessor contradicts the migrations:
*CODE — `app/Models/ExtraWorkComment.php:114-118`:*
```php
/**
 * Comment Accessor
 * Returns comment value as-is (no translation columns in database)
 */
public function getCommentAttribute($value) { return $value; }
```
*DATA — `GET /admin/extra-works/468/comments`* — every comment object carries
`comment_bg, comment_en, comment_nl, comment_tr, translate_meta, original_language`.
The columns exist; the comment in the code is stale. (They are not in `$hidden`, unlike
`ExtraWork`'s, so they ship to every client.)

### Field map

**`type`** (`'user' | 'system' | 'status_change' | 'approved' | 'rejected' | 'created'`)
- WRITTEN BY: `ExtraWorkService::addComment` → always `'user'` (`:302`);
  `ExtraWork::addSystemComment($message, $type)` → `'created'` from the `created` hook
  (`ExtraWork.php:546`), `'status_change'` from the `updated` hook (`:659`) and from
  `updateStatus`'s two dead Turkish branches (`:3645, :3650`), `'approved'` from
  `approveArchive`, `'rejected'` from `rejectArchive`.
- READ BY: `ExtraWorkComment::booted()` — **notification is sent only for `type === 'user'`**
  (`:248-251`); `shouldTranslate()` (`:236-239`) — system types are never translated;
  `ExtraWorkService::getComments:274` — only `status_change` gets colour/icon.
- GATES: whether a comment produces a push notification at all; whether it is translated;
  whether it is coloured.

**`comment`** (text)
- WRITTEN BY: `addComment` (validated `required|string|min:1|max:10000`, `:1973`),
  `updateComment` (same rule), `addSystemComment` (composed server-side).
- READ BY: the comments tab; `extractStatusInfo`'s regex; the FCM body's
  `substr($comment->comment, 0, 100)`; the Redis payload's `mb_substr(…, 0, 50)`.

**`user_id`** (FK users, required)
- WRITTEN BY: `addComment` → `auth()->id()`; `addSystemComment` → `auth()->id() ?? 1`
  (**user 1 is the implicit system user**).
- READ BY: `user()` relation; `updateComment`'s ownership check (`where('user_id', auth()->id())`);
  the FCM `excludeUserId`.
- *DATA:* record 468's comments show `user_id: 1` for archive-era system comments and
  `user_id: 128` for the recent ones — i.e. the "system" author varies by whether anyone was
  authenticated.

**`created_by`**
- WRITTEN BY: `addSystemComment` only — `'created_by' => $userId` (`app/Models/ExtraWork.php:783`).
  `addComment` never sets it, so **user comments have `created_by = null`.**
- READ BY: `createdBy()` relation; `createUnreadRecords`'s author test
  (`$user->id === $comment->created_by`) — which is therefore never true for a user comment
  written via `addComment` on the model path; `ExtraWorkCommentPosted`'s
  `$this->userId = $comment->created_by ?? $comment->user_id;`.
- Note `ExtraWorkService::addComment` compensates with its own author test
  (`$user->id === auth()->id()`, `:337`), so the SPA path does mark the author read. The model
  path does not.

**`parent_comment_id`**
- WRITTEN BY: `addComment` (validated `exists:extra_work_comments,id`).
- READ BY: `topLevelComments()` (`whereNull`), `replies()`, `is_reply` accessor.
- **One level only** — `replies()` does not recurse, and the UI adds a reply to
  `comment.replies` of the parent it was replying to, so replying to a reply is silently
  flattened. No validation prevents a client from nesting.

**`has_attachments`**
- WRITTEN BY: `addComment` (`!empty($data['attachments'])`), `addCommentAttachment` (`true`),
  `deleteCommentAttachment` (recount), `store`'s comment-relink block, `addSystemComment`.
- READ BY: the broadcast payload and the UI badge. `updateAttachmentsFlag()` is defined
  (`ExtraWorkComment.php:158-162`) and **never called**.

**`mentioned_users`** (json, cast to array)
- WRITTEN BY: `addComment` — validated `nullable|array` with `mentioned_users.* => exists:users,id`
  (`ExtraWorksController:1975-1976`), stored at `ExtraWorkService:303`.
- READ BY: **nothing.** `grep -rn "mentioned_users" app/ database/` returns only the fillable,
  the cast, the validation and the write. The frontend does not send it (`ExtraWorkCommentsTab.jsx`'s
  payload is `{comment, parent_comment_id, files}`) and does not render it.
- **DEAD.**

**`is_edited` / `edited_at`**
- WRITTEN BY: `updateComment` (`ExtraWorkService:394-399`). `markAsEdited()` is defined and
  never called.
- READ BY: the UI badge only.

**`is_deleted` / `deleted_at`**
- WRITTEN BY: `deleteComment` (`ExtraWorkService:434-437`). `softDelete()` is defined and
  never called.
- READ BY: every comment query (`where('is_deleted', false)`), `ExtraWork::comments()`,
  `topLevelComments()`, `replies()`, the unread counters.
- **The model imports `Illuminate\Database\Eloquent\SoftDeletes` at line 11 and never adds it
  to the class** (`class ExtraWorkComment extends Model`, `:14`). The trait is dead weight and
  the `deleted_at` column is managed by hand.

**`original_language`, `comment_nl/en/tr/bg`, `translate_meta`**
- WRITTEN BY: `ExtraWorkCommentObserver::handleTranslation` (`original_language` via
  `saveQuietly()`) and `AutoTranslateJob` (the variants).
- READ BY: `getCommentInLanguage()` (`ExtraWorkComment.php:218-228`) — **0 callers**. The
  columns are shipped raw to the client, which does not use them either.
- **Effectively DEAD downstream of the job that fills them.**

### `ExtraWorkCommentObserver` — read in full

Registered at *CODE `app/Providers/AppServiceProvider.php:29`*:
`\App\Models\ExtraWorkComment::observe(\App\Observers\ExtraWorkCommentObserver::class);`

It has exactly two hooks, `created` and `updated`, and both do the same one thing: call
`handleTranslation`. There is **no `deleted`, no `saving`, no `deleting`** hook.

*CODE — `app/Observers/ExtraWorkCommentObserver.php:32-84`, the whole body:*

1. `if (!$comment->shouldTranslate()) return;` — system, status_change, approved, rejected and
   created comments are skipped. Only `type = 'user'` is translated.
2. `if (!$comment->isDirty('comment') && !$comment->wasRecentlyCreated) return;`
3. `if (empty($comment->comment)) return;`
4. Language resolution, in order: the authenticated user's `language`; else the comment
   author's `language`; else **`'tr'`**. (Note the fallback is Turkish while the platform's
   stated primary language, everywhere else in the codebase, is Dutch.)
5. On create only: `$comment->original_language = $userLanguage; $comment->saveQuietly();`
   — `saveQuietly` deliberately avoids re-entering the observer.
6. `AutoTranslateJob::dispatch($comment, ['comment'], $userLanguage);`

**What the observer does NOT do:** it writes no activity row, sends no notification, touches
no unread record, does not maintain `has_attachments`, and does nothing on delete.

`AutoTranslateJob` is queued. `config/queue.php:16` — `'default' => env('QUEUE_CONNECTION', 'database')`.
Whether a worker is running is outside the repo. **INFERRED** that one is, because live
records have populated `title_nl`/`title_en`/`title_tr`/`title_bg` (DATA §1.4). *To confirm:*
the supervisor/systemd unit list on the host.

### `extra_work_comment_reads`

**WRITTEN BY — creation (the fan-out)**

Two near-identical implementations, one per comment-creation path:

*CODE — `app/Models/ExtraWork.php:812-831` (`createUnreadRecords`, used by `addSystemComment`):*
```php
$users = $this->getRelatedUsers();
foreach ($users as $user) {
    $readAt = ($user->id === $comment->created_by) ? now() : null;
    $records[] = ['comment_id' => $comment->id, 'user_id' => $user->id,
                  'read_at' => $readAt, 'created_at' => now(), 'updated_at' => now()];
}
ExtraWorkCommentRead::insert($records);
```

*CODE — `app/Services/ExtraWorkService.php:333-348` (used by `addComment`):* the same shape,
but with `$readAt = ($user->id === auth()->id()) ? now() : null;` and a raw
`DB::table('extra_work_comment_reads')->insert($records);`.

**The "related users" rule (twice, identically buggy)**

*CODE — `app/Models/ExtraWork.php:836-861` and `app/Services/ExtraWorkService.php:371-386`:*
```php
$userIds = collect();
if ($this->created_by) {            // ← VARCHAR(100) display name
    $userIds->push($this->created_by);
}
$assignedUsers = $this->employeeAssignments()->pluck('user_id');
$userIds = $userIds->merge($assignedUsers);
$adminUsers = User::whereHas('role', function ($query) {
    $query->where('name', 'admin');          // ← role NAME
})->pluck('id');
$userIds = $userIds->merge($adminUsers);
return User::whereIn('id', $userIds->unique())->get();
```

- `created_by` is a name string (*DATA*: `"<name> (Admin)"` on record 567, `"B Amsterdam"`
  on record 476 per tier-1 A1). MySQL coerces it to `0` in the `IN` list. **The record's
  creator is never in the fan-out.**
- The admin lookup uses `role.name = 'admin'`, which is correct for this database
  (*DATA — `GET /admin/roles`*: role 1 has `name: "admin"`). Compare `updateStatus`, which
  uses `role.slug` (§2.6).
- There is no UCB check here at all — this fan-out is creator + assignees + all admins.

**WRITTEN BY — marking read**

- `POST /{id}/comments/{cid}/mark-read` → `ExtraWorkComment::markAsRead($userId)`
  *CODE `app/Models/ExtraWorkComment.php:167-172`:*
  ```php
  $this->reads()->where('user_id', $userId)->update(['read_at' => now()]);
  ```
  An `update`, not an `updateOrCreate`. If no row exists (because the user was not "related"
  when the comment was written) this updates zero rows and returns 200 anyway.
- `POST /{id}/comments/mark-all-read` → a bulk `DB::table(...)->update(...)` over that user's
  null-`read_at` rows for the record's non-deleted comments (`ExtraWorksController:3838-3849`).
  Returns the affected count.

**READ BY**

- `GET /{id}/unread-count` (`ExtraWorksController:3798-3806`) and the identical
  `unread_comments_count` appended attribute (`app/Models/ExtraWork.php:886-901`) — a
  `whereHas('reads', user = me AND read_at IS NULL)` count. Returns 0 when unauthenticated.
- `ExtraWorkComment::getReadByUsersAttribute()` (last 5 readers) and
  `getUnreadCountAttribute()` — **neither is in `$appends`; 0 callers. DEAD.**

*DATA:* `GET /admin/extra-works/468/unread-count` → `{"count": 10}` (record has 27 comments);
`GET /admin/extra-works/567/unread-count` → `{"count": 0}` (record has 6 comments, five of
which user 1 wrote).

**GATES:** the unread badge on the comments tab and in the list grid. Nothing else.
No notification, no permission, no report depends on it.

### The comment endpoint / UI contract mismatch

*CODE — `ExtraWorkService::getComments:257-287`:* the method takes `int $extraWorkId` and
nothing else. It returns every top-level comment, eager-loading `replies` and both levels of
`attachments`, ordered `created_at desc`, with `total_count = $comments->count()`.

*CODE — `ExtraWorkCommentsTab.jsx:115-140`:*
```js
const response = await apiClient.get(`/admin/extra-works/${extraWorkId}/comments`, {
  params: { page, per_page: commentsPerPage }      // commentsPerPage = 10  (:63)
});
...
const totalComments = response.data.total || response.data.meta?.total || commentList.length;
const hasMore = (page * commentsPerPage) < totalComments;
...
if (append) setComments(prev => [...prev, ...commentList]);
```

*DATA — `GET /admin/extra-works/468/comments?page=2&per_page=5`* → `total_count: 27,
returned: 27`. The parameters are ignored.

So on a 27-comment record: `total` is undefined, `meta` is undefined, `commentList.length` is
27, `hasMore = 10 < 27 = true`, the "Load more" button renders, clicking it re-fetches all 27
and **appends** them — 54 rows, 27 duplicated — and `hasMore` is still true (`20 < 27`).
A second click gives 81.

This is also an unbounded server list: there is no cap on how many comments the endpoint
returns, and no cap on `attachments` either.

## 2.5 `messages` and `internal_messages`

### `messages`

*CODE — `2025_11_04_222101_create_messages_table.php:16-28`:* `from_user_id`, `to_user_id`,
`subject`, `message`, `is_read`, `read_at`, `replied_to_message_id`,
`priority enum('low','normal','high')`, `deleted_by_sender`, `deleted_by_receiver`.
*CODE — `2025_11_05_135358_add_extra_work_id_to_messages_table.php:16-20`:* adds
`extra_work_id` nullable, FK → `extra_works` **ON DELETE CASCADE**, indexed.
*CODE — `2025_11_05_135359_create_message_attachments_table.php`:* `message_id` + `file_id`,
both cascade.

Routes: `routes/api.php:113-126`, prefix `messages`, **no `ucb.permission` middleware** —
only the outer `auth:sanctum` + `user.status` group.

**`messages.extra_work_id`**
- WRITTEN BY: `MessageService::sendMessage`'s `$extraWorkId` argument (`:57`), which comes
  from `MessagesController::store`.
- READ BY: `Message::extraWork()`, `Message::scopeForExtraWork()` (**0 callers**), and the
  `with(['fromUser','toUser','attachments'])` eager-load — note `extraWork` is not in it.
- *DATA — `GET /messages/inbox`:* the single row user 1 has is
  `{"id":7,"from_user_id":147,"to_user_id":1,"extra_work_id":null,"subject":"Extra Work #251",
  "message":"D d d dv", … "created_at":"2025-11-05T07:49:42Z"}` — **the subject names an
  extra work and the link column is null.**
- **Effectively DEAD on live data.**

`MessageService::sendMessage` takes two opt-in booleans:
- `$sendNotification` → `sendMessageNotification` → `NotificationService::sendToUser(...,
  notificationType: 'inbox_message', ...)` (`MessageService.php:184-192`).
  *DATA:* exactly one `inbox_message` row exists in the 475-row notification history, dated
  2025-11-05 — the same day as the single message.
- `$sendAsEmail` → `sendMessageEmail` → `MailService::sendDirectMail(...)` with a hand-built
  HTML body in Turkish, `replyTo` set to the sender's address
  (`MessageService.php:216-262`). **This is the only email in my scope that can ever be sent,
  and only if the caller explicitly opts in.**

### `internal_messages`

*CODE — `2025_11_08_091429_create_internal_messages_table.php:16-30`:* the same shape plus
`priority enum('low','normal','high','urgent')` and `is_draft`.
*CODE — `2025_11_08_093611_…:16-18`:* adds `extra_work_id` nullable, FK **ON DELETE SET NULL**
(note: the two tables chose different FK behaviours for the same relationship).

Routes: `routes/api.php:2546-2568`, prefix `internal-messages`, with
`App\Http\Middleware\InternalMessagingMiddleware` — the only thing in my scope with a
purpose-built access middleware ("Employees Only — Customer Access BLOCKED").

Extra surface over `messages`: `/conversations` (`group_by=contact|extra_work`), `/drafts`,
`/drafts/{id}/send`, `DELETE /drafts/{id}` (permanent).

**`internal_messages.is_draft`**
- WRITTEN BY: `saveDraft` (true), `InternalMessage::sendDraft()` (`:233-236`, sets false).
- READ BY: `scopeInbox` (`is_draft = false`), `scopeSent` (false), `scopeDrafts` (true),
  `scopeUnread` (false), `isDraft()`, `markAsRead`/`markAsUnread` guards
  (`where('is_draft', false)`), `getUnreadCount`.
- **GATES:** a draft is invisible in every list except the author's own drafts, cannot be
  marked read, and does not count toward unread. `sendDraft` refuses if `to_user_id` is null.
  This is the one `is_draft` in the system that actually gates visibility — the attachment
  one does not.

Notification: `notificationType: 'internal_message'`, with the extra-work id folded into the
body as a `[Extra Work #N]` prefix (`InternalMessageService.php:186-208`). *DATA:* zero
`internal_message` rows in the notification history; user 1's internal inbox is empty.

### Two dead front-end message paths

*CODE — `src/services/entities/messageService.js:5-31`:* every endpoint is
`/tickets/{ticketId}/messages…`, plus reaction and typing-indicator endpoints.
`grep -n "prefix('tickets')" routes/api.php` → **no match.** The entire service 404s.

*CODE — `src/pages/finalosius/meldings/detail.jsx:408-422`:*
```js
const messageResponse = await fetch(`https://api.osius.nl/api/extra-works/${id}/messages?language=${currentLanguage}`, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}`, ... },
  body: JSON.stringify({ type: 'text', content: `Uploaded ${files.length} file…`, attachments: {...} })
});
```
A hard-coded **production** host inside a dev build, reached with `fetch` rather than the
configured api client, carrying the current session token. There is no
`/extra-works/{id}/messages` route in this backend either. **Handoff to whoever owns the
Melding UI and to security.**

## 2.6 The notification stack

### The tables

| table | migration | key columns |
|---|---|---|
| `user_fcm_tokens` | `2025_10_23_120435` | `user_id`, `device_id`, `fcm_token`, `device_type` (ios/android/web), `device_name`, `app_version`, `is_active`, `last_used_at` |
| `user_notification_settings` | `2025_10_23_120440` | `push_enabled`, `sound_enabled`, `vibration_enabled`, five per-type booleans, `quiet_hours_enabled/_start/_end`, `email_notifications`, `email_frequency` |
| `push_notifications` | `2025_10_23_120626` (+ `2025_10_24_083933` adds `read_at`, `action_url`, `action_type`) | `user_id`, `notification_type`, `title`, `body`, `related_type`, `related_id`, `data` (json), `status`, `sent_at`, `read_at`, `failed_reason`, `fcm_message_id`, `fcm_response` |
| `push_notification_devices` | same | `notification_id`, `fcm_token_id`, `status`, `sent_at`, `delivered_at`, `failed_reason` |
| `mail_templates` | pre-existing (+ `2025_10_07_073323`) | `name`, `type` (customer/employee/user/auth/ticket/contact), `language` (tr/en/nl/bg), `subject`, `html_content`, `variables`, `is_active` |
| `mail_logs` | pre-existing (+ AI columns `2025_10_07_160000`, `resent_from_batch_id` `2025_10_08_205500`) | outgoing and incoming mail, with AI summary/topic/importance/sentiment on inbound |

### `NotificationService::sendToUser` — the single funnel

*CODE — `app/Services/Firebase/NotificationService.php:36-231`.* In order:

1. `User::find($userId)` — throws if missing.
2. `$settings = $user->notificationSettings` — **created on demand** with all-true defaults
   if absent (`UserNotificationSetting::createForUser`).
3. `if (!$settings->push_enabled) return ['reason' => 'push_disabled']` — **no row is written.**
4. `if (!$settings->isNotificationTypeEnabled($notificationType)) return ['reason' => 'notification_type_disabled']` — **no row.**
5. `if ($settings->isInQuietHours()) return ['reason' => 'quiet_hours']` — **no row, and no
   retry later. A notification suppressed by quiet hours is lost, not deferred.**
6. `PushNotification::create([... 'status' => 'pending'])` — **the row is written here**, before
   any device is tried.
7. If `$user->activeFcmTokens` is empty → `markAsFailed('No active FCM tokens')`, commit, return.
8. Otherwise, per token: create a `push_notification_devices` row, call
   `FcmService::sendWithOptions`, mark the device sent/failed, `markAsUsed()` the token; if
   FCM says the token is invalid, **`$invalidToken->deactivate()`**.
9. `markAsSent()` if any device succeeded, else `markAsFailed('All devices failed')`.
10. Finally, broadcast `NotificationUserEvent` on the user's private channel.

**The per-type preference map is out of sync with the types actually sent.**

*CODE — `app/Models/UserNotificationSetting.php:88-99`:*
```php
$typeMap = [
    'melding_created'    => 'melding_notifications',
    'melding_updated'    => 'melding_notifications',
    'extra_work_created' => 'extra_work_notifications',
    'extra_work_updated' => 'extra_work_notifications',
    'comment_added'      => 'comment_notifications',
    'status_changed'     => 'status_change_notifications',
    'user_assigned'      => 'assignment_notifications',
];
$field = $typeMap[$type] ?? null;
return $field ? $this->$field : true;    // ← unmapped types are ALWAYS allowed
```

The types the live code actually sends are `melding_created`, `melding_updated`,
`extra_work_created`, `extra_work_updated`, **`comment_created`** (`ExtraWorkComment.php:309`),
`status_changed`, **`melding_assigned` / `extra_work_assigned`** (`ExtraWorksController:2222`),
`inbox_message`, `internal_message`.

So:
- **`comment_notifications` is inert** — the live comment type is `comment_created`, not the
  mapped `comment_added`. Turning comment notifications off does nothing.
- **`assignment_notifications` is inert** — the live types are `melding_assigned` /
  `extra_work_assigned`, not the mapped `user_assigned`.
- `inbox_message` and `internal_message` have no preference at all.
- Only `melding_*`, `extra_work_created/updated` and `status_changed` respect their toggle.

*DATA — `GET /user/notification-settings`:* user 1's settings are all-true defaults with
`quiet_hours_enabled: false`, `quiet_hours_start: "22:00:00"`, `quiet_hours_end: "08:00:00"`,
`email_notifications: true`, `email_frequency: "instant"`.

**`email_notifications` and `email_frequency` are dead in this subsystem.** `grep -rn
"email_frequency" app/` returns only the fillable and the defaults. `NotificationService`
never sends mail. There is no digest job (there is no scheduler at all), so `'instant'` is
the only value that could ever mean anything and even it is unused.

### Every notification type: trigger, recipient rule, storage

| type | trigger (CODE) | recipient rule | writes `push_notifications`? |
|---|---|---|---|
| `extra_work_created` / `melding_created` | `ExtraWork::created` → `dispatch(fn => sendFcmNotification($ew,'created'))->afterResponse()` — `ExtraWork.php:544-553` | `RecipientDeterminer::getRecipientsForExtraWork`, excluding `auth()->id()` | yes |
| `extra_work_updated` / `melding_updated` | `ExtraWork::updated` **only when `status_id` is NOT among the dirty keys** — `ExtraWork.php:678-700` | same | yes |
| `comment_created` | `ExtraWorkComment::created` **only when `type === 'user'`** — `ExtraWorkComment.php:246-259` | same, excluding `$comment->user_id` | yes |
| `status_changed` | `PUT /admin/extra-works/{id}/status` only — `ExtraWorksController:3658-3725` | **hand-rolled**: UCB holders with `scope_mask > 0` on the record's customer-buildings ∪ active assignees ∪ every `users.department_id = extra_works.user_department_id` with `status_id = 1` ∪ every user whose role **slug** is `admin`. **Nobody is excluded — the actor notifies himself.** | yes |
| `extra_work_assigned` / `melding_assigned` | `POST /admin/extra-works/{id}/employees` — `ExtraWorksController:2216-2233` | the newly assigned user, and only him | yes |
| `inbox_message` | `MessageService::sendMessage` when `$sendNotification` is true | the recipient | yes |
| `internal_message` | `InternalMessageService` send / sendDraft when `$sendNotification` is true | the recipient | yes |
| *(attachment added)* | `ExtraWorkAttachment::created` — `ExtraWorkAttachment.php:61` | UCB holders (**no `scope_mask` filter**) ∪ all users with role **name** `admin`, minus `auth()->id()` — `ExtraWorkAttachmentAdded.php:151-186` | **NO** — Redis only |
| *(status changed, event path)* | `ExtraWork::updated` when `status_id` is dirty — `ExtraWork.php:658` | same UCB ∪ admins rule | **NO** — Redis only |
| *(record updated, event path)* | `ExtraWork::updated` any other field — `ExtraWork.php:682` | same | **NO** — Redis only |
| *(comment posted, event path)* | `ExtraWorkService::addComment` and `ExtraWork::triggerNotification` | same | **NO** — Redis only |

**Four different UCB predicates for "who cares about this record" coexist:**

1. `RecipientDeterminer::getRoleUsers` — role slug in {`location-chef`, `location-manager`,
   `customer`} **and** `users.status_id = 1` **and** a UCB row with `scope_mask > 0`.
2. `ExtraWorksController::updateStatus` — any UCB row with `scope_mask > 0`, plus assignees,
   plus department, plus role **slug** `admin`.
3. `ExtraWorkService::getNotificationRecipients` — identical to (2). **0 callers.**
4. `ExtraWorkCommentPosted` / `ExtraWorkAttachmentAdded` / `ExtraWorkStatusChanged` /
   `ExtraWorkUpdated::getRelatedUserIds` — any UCB row **with no `scope_mask` filter at all**,
   plus role **name** `admin`.

### `RecipientDeterminer`, in full (this closes tier-1 A1's open question 7)

*CODE — `app/Services/Notification/RecipientDeterminer.php:24-27`:*
```php
const ROLE_LOCATION_CHEF    = 'location-chef';
const ROLE_LOCATION_MANAGER = 'location-manager';
const ROLE_CUSTOMER         = 'customer';
```

*CODE — `:105-145` (`determineRequiredRoles`):*
- `type == 2` (Melding) → always `[location-chef, customer]`, regardless of status.
- `type == 1`, status 1 or 2 → `[location-chef, customer]`.
- `type == 1`, status 3, 4 or 8 → `[location-chef, location-manager, customer]`.
- anything else (statuses 5, 6, 7, **9**) → logs "Unknown status" and falls back to
  `[location-chef, customer]`.

*CODE — `:157-171` (`getRoleUsers`):*
```php
$users = User::query()
    ->whereHas('role', function ($query) use ($roleSlug) {
        $query->where('slug', $roleSlug);
    })
    ->where('status_id', 1)
    ->whereHas('customerBuildingPermissions', function ($query) use ($customerBuildingIds) {
        $query->whereIn('customer_building_id', $customerBuildingIds)
              ->where('scope_mask', '>', 0);
    })
    ->select('id', 'name', 'email')->get();
```

*CODE — `:47-58`:* if the record has **no** customer-buildings it logs a warning and returns
`[]` — so an extra work created without a building notifies nobody at all.

**Two things are wrong with this, one certain and one near-certain:**

1. **Admins are not in the audience.** The role list is location-chef / location-manager /
   customer. Every earlier implementation included admins. This alone explains why the admin
   user stopped receiving created/updated/comment notifications.
2. **The role identifiers are hyphenated where the rest of the system uses underscores.**
   *DATA — `GET /admin/roles?per_page=100`* returns eight roles whose `name` values are
   `admin, customer, customer_employee, employee, location_manager, customer_manager,
   location_chef, contact_person`; the payload has **no `slug` field at all**, and
   `Role::$fillable` (`app/Models/Role.php:16-34`) does not list one.
   Every other role check in the codebase uses the underscored form:
   *CODE `app/Http/Controllers/WorkPlan/WeeklyController.php:47`:* `$user->role && $user->role->name === 'location_chef'`;
   *CODE `app/Http/Controllers/DashboardController.php:49, 54`:* `case 'location_manager':` / `case 'location_chef':`;
   *CODE `app/Services/ExtraWorkService.php:427`:* `in_array($user->role->slug, ['admin', 'location_manager'])`.
   `RecipientDeterminer` is the **only** place in the tree that uses hyphens.
   **INFERRED:** `getRoleUsers` matches nobody, so every model-event notification resolves to
   an empty recipient list. *To confirm:* `SHOW COLUMNS FROM roles LIKE 'slug';` and, if it
   exists, `SELECT id, name, slug FROM roles;`.

### The live proof

*DATA — `GET /notifications?per_page=200` over all three pages, 475 rows, all `user_id = 1`
(the endpoint is scoped to the authenticated user — `NotificationsController.php:38`):*

| notification_type | count | first | last |
|---|---|---|---|
| `comment_added` | 217 | 2025-10-27 | **2025-11-18** |
| `status_changed` | 155 | 2025-10-27 | **2026-02-17** |
| `attachment_added` | 36 | 2025-10-27 | **2025-11-19** |
| `extra_work_created` | 33 | 2025-10-27 | **2025-11-19** |
| `user_assigned` | 25 | 2025-10-27 | **2025-11-20** |
| `melding_created` | 8 | 2025-10-28 | 2025-11-13 |
| `inbox_message` | 1 | 2025-11-05 | 2025-11-05 |

Status: 222 `sent`, 253 `failed`, and **every failure reads `No active FCM tokens`.**

*DATA — `GET /firebase/tokens`:* user 1 has exactly one token — `device_type: "ios"`,
`device_name: "iPhone 13 Pro Max"`, **`is_active: false`**, `last_used_at: "2025-11-20T20:09:35Z"`,
`created_at: "2025-11-07"`. `active_count: 0`.

Two independent conclusions follow, and they are different:

- **Delivery** stopped on 2025-11-20, when FCM rejected the token and step 8 of
  `sendToUser` deactivated it. Since then every notification for user 1 is written with
  `status = failed`. Nothing re-activates a token except a fresh `POST /firebase/token` from
  the device.
- **Generation** of everything except `status_changed` stopped in the same window, and that
  is a *code* change, not a token problem — because a `push_notifications` row is created
  before any device is touched (step 6), so a token-less user still accumulates rows. The
  types that vanished are exactly the ones that were re-pointed at `RecipientDeterminer`;
  `status_changed` is the one that kept its hand-rolled admin-inclusive fan-out.
  Corroborating DATA: record 567 was created 2026-08-06 and moved 1 → 2 → 3 → 4 → 8 on
  2026-08-16/17 (its comment log proves it), and produced **zero** notification rows — the
  most recent row of any kind is 2026-02-17.

`attachment_added` is a third case: the current code writes no `push_notifications` row for
an attachment at all, so those 36 historical rows must have come from
`ExtraWorkService::sendNotificationToUsers` — the 130-line helper that now has zero callers.
**INFERRED**, and consistent with the `comment_added` / `user_assigned` type names, which are
exactly the names that helper's callers would have used and which the current code no longer
emits. *To confirm:* the git history of `ExtraWorkService`.

### Mail: nothing in this area ever sends one

`grep -rn "Mail::\|MailService\|mail(" app/Models/ExtraWork*.php app/Services/ExtraWorkService.php app/Http/Controllers/Admin/ExtraWorksController.php app/Observers/ app/Events/` → **no matches.**

No extra work, melding, group, comment, attachment or status change produces an email. The
mail subsystem serves customers, employees, users, password reset and bulk marketing only.

Two mail paths that *look* like they belong here and do not work:

- `MailService::sendToTicketCustomers(int $ticketId, …)` (`app/Services/MailService.php:66-165`)
  begins `\App\Models\Ticket::with([...])->findOrFail($ticketId)`. **`app/Models/Ticket.php`
  does not exist** (`ls app/Models/ | grep "^Ticket"` returns only `TicketCategory`,
  `TicketPriority`, `TicketStatus`). Its only caller is `MailController::sendToTicketCustomers`,
  which has no route.
- `MailController::sendTicketNotification` (`:1816-1935`) validates `exists:tickets,id`,
  loads `App\Models\Ticket`, and looks up `MailTemplate::where('name','ticket_notification')`.
  `grep -n "sendTicketNotification" routes/api.php` → **no match.** Unroutable.

Both build attachment lists from `$att->file_name` / `->file_path` / `->file_size` /
`->file_type` — the columns dropped in October 2025.

### The scheduler audit — the evidence for "nothing is time-driven"

```
$ cat routes/console.php
<?php
use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');
```
Eight lines. That is the entire file.

*CODE — `bootstrap/app.php:22-27`:*
```php
return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
    )
```
No `->withSchedule(...)`. There is no `app/Console/Kernel.php`.

`ls app/Console/Commands/` → `ProcessIncomingMail.php`, `RecalculateGradesScores.php`,
`VerifyInspectionScore.php`. None is registered on a schedule; none produces a reminder.

`ls app/Jobs/` → `AutoTranslateJob.php`, `AutoTranslateCommentJob.php`,
`AutoTranslateExtraWorkJob.php`. All three are translation.

`ls app/Observers/` → seven observers, all model-event driven.

**The unreachable time-based intent:**

*CODE — `config/notifications.php:231-247`:*
```php
// REMINDER NOTIFICATIONS
'deadline_reminder' => [
    'nl' => ['title' => 'Deadline Herinnering', 'body' => 'De deadline voor deze taak nadert'],
    'en' => ['title' => 'Deadline Reminder',    'body' => 'The deadline for this task is approaching'],
    'tr' => [...], 'bg' => [...],
],
```

Of the twelve configured templates, **five have zero code references outside the config file**:
`extra_work_approved`, `extra_work_rejected`, `assigned_to_work`, `approval_requested`,
`deadline_reminder` (verified by grepping each key across `app/`).

*CODE — `app/Http/Controllers/Admin/MailController.php:824-843` (`scheduleBulkSend`, routed at
`routes/api.php:1253`):*
```php
// 🚧 TODO: Queue sistemi eklenecek (Laravel Horizon)
// Şimdilik sadece simülasyon
$jobId = 'bulk_mail_job_' . uniqid();
...
return $this->success([
    'job_id' => $jobId, 'scheduled_for' => $scheduledFor,
    'status' => 'scheduled', 'mock_mode' => true,
    'warning' => '🚧 Queue system not implemented yet. This is a MOCK response.',
```

**Does anything escalate to a manager? No.** The only rule anywhere that mentions a manager
role is `RecipientDeterminer::determineRequiredRoles`, which adds `location-manager` to the
audience once a record reaches status 3, 4 or 8 — that is a widening of the audience on
*progress*, not an escalation on *failure*, it is not time-based, and (per the slug problem
above) it very likely resolves to nobody.

## 2.7 The `portal_extra_works` view — what it does and does not carry

I read the full `CREATE VIEW` in
`database/migrations/2025_12_09_031108_fix_portal_extra_works_view_category_name.php:19-105`.

It selects roughly 60 columns from `extra_works` plus five joined labels
(`ts.label_en AS status_name`, `tp.label_en AS priority_name`, `tc.label AS category_name`,
`cd.name`, `cwt.name`).

**Relevant to my scope, it does NOT select:**
- any attachment column (there are none on `extra_works`, and no join to
  `extra_works_attachments`);
- `extra_work_group_id`, `group_sequence`, `group_total` — **the grouping is entirely
  invisible to the portal**;
- any comment or comment-read data.

It **does** select `ew.deleted_at` but has **no `WHERE ew.deleted_at IS NULL`**, so the view
exposes soft-deleted extra works unless the consumer filters them itself.

It does select `draft_message`, `drafted_at`, `drafted_by`, `upload_is_required` and
`notes_is_required` — the fields tier-1 A1 showed are dead on the PHP side.

That the portal exists at all is confirmed by DATA rather than code:
*DATA — `GET /admin/extra-works/475/attachments`*, file 591:
`"uploaded_from": "portal"`, `"url": "https://portal.osius.nl/api/files/962b1f70-…"`,
`"uploaded_by": 148`. Compare record 468's files: `"uploaded_from": "admin"`,
`"description": "Mobile upload: …"`, `"uploaded_by": null`, served from `dev-api.osius.nl`.
So at least three writers put rows in this table: the admin SPA, a mobile client, and the
customer portal — and the portal stores its files on its own host.

---

# 3. This area's connection map

## 3.1 Group creation and everything that hangs off it

```
SPA create form (entryMode = 'multiple')
  ScheduleDaysModal  ──► { date: [{time, condition}] }
  EditDayModal       ──► condition ∈ {at, before, after}
        │
        ▼
POST /admin/extra-works/batch        (ucb.permission: extra_works,create)
        │
        ├─► [if >1 entry]  extra_work_groups row
        │        building_id = customerBuildings[0]     ── read by nothing
        │        year, week_number = FIRST entry's      ── read by the bulk-edit suffix generator
        │        name = null                            ── read as null by the LIST
        │        is_auto_generated = true               ── read by nothing
        │        created_by = user id                   ── read by nothing
        │        ⚠ created BEFORE the loop, no transaction → 15 orphan rows live
        │
        └─► per entry, N × extra_works
                 title = base + " [WK{n}-{d.m.Y}:{HH:mm}:{op|voor|na}]"
                      └── condition dies here; the string is its only storage
                 customer_start_date = the slot's date
                 deadline_at         = the slot's date 20:59:00
                 requested_at        = the slot's datetime  (NOT "now")
                 extra_work_group_id / group_sequence / group_total
                 ⚠ request-level files are attached to EVERY entry
                      └──► ExtraWorkAttachment::created ──► broadcast + Redis (× N × files)
                 └──► ExtraWork::created
                        ├──► addSystemComment('Created: …', 'created')
                        │       ├──► extra_work_comment_reads fan-out (creator excluded — bug)
                        │       └──► broadcast ExtraWorkCommentPosted ──► Redis
                        └──► FCM 'extra_work_created' via RecipientDeterminer (→ empty, see §2.6)
```

## 3.2 The three group action surfaces, and how differently they behave

```
DETAIL PAGE ── group card (ExtraWorkDetailHeader) ── shows display_name + member count
      │
      ├── group action bar (WorkflowActionsBar :313-395)
      │     buttons are built from group.status_distribution and map
      │       status 1 → "Plannen"    → ExtraWorkBulkPlanModal
      │       status 2 → "Voltooien"  → ExtraWorkBulkCompleteModal
      │       status 3 → "Goedkeuren" → ExtraWorkBulkArchiveApproveModal
      │     each modal LOOPS over the members and hits the NORMAL per-record endpoints:
      │       PUT  /admin/extra-works/{id}            (plan: status 2; complete: status 3)
      │       POST /admin/extra-works/{id}/archive/approve   ("Goedkeuren" → status 8!)
      │     ⇒ full stamping, full events, full system comments
      │     ⇒ BUT status 4 is SKIPPED, so approved_at stays null and DRAFTS ARE NEVER PUBLISHED
      │
      ├── GroupEditModal  ── a status dropdown
      │     PUT /admin/extra-works/groups/{id}/status  { status_id }
      │     ⇒ mass update(), NO source_status_id, NO validation of the target status
      │     ⇒ zero events, zero stamps, zero comments, zero notifications
      │     and a delete button → DELETE /admin/extra-works/groups/{id}
      │           ⇒ soft-deletes every member (any status), hard-deletes the group row
      │
      └── GroupBulkEditModal ── an inline grid (date / time / condition / status / title /
            plan dates / budget hours / workers)
              reads member.title  ← the TRANSLATED title from getGroupMembers
              extractCondition(title)     ← regex; only matches the ':cond]' format
              extractBaseTitle(title)     ← same regex
              on save, per changed row:
                PUT /admin/extra-works/{id} { status_id, title: base + REGENERATED suffix,
                                              planed_at, planed_start_at, planed_end_at, workers }
                PATCH /admin/extra-works/{id}/hours { hours_planed }
              ⚠ status_id is ALWAYS in the payload  ──► triggers the auto-stamp engine:
                    a row at status 3 gets completed_at re-stamped to now()
                    a row at status 4 gets approved_at re-stamped AND its drafts published
              ⚠ the raw title is overwritten with the translated one
              ⚠ the suffix's week number comes from group.week_number, not the row's date
```

## 3.3 The attachment lifecycle

```
CREATE FORM ─ files[] {id, is_pre_file:1} ──► extra_works_attachments (pre-file)
                                     └──► ALSO re-linked to the auto 'created' comment
                                          with is_comment=true, is_pre_file=false  (:860-868)

FILES TAB  ─ upload ──► POST /{id}/attachments {id, is_pre_file:0}      (post-file)

COMPLETION MODAL ─ upload ──► POST /{id}/attachments {id, is_pre_file:0, is_draft:1}
                              then PUT /{id} {completed_at, status_id:3, completion_notes}
                                              ▲
                                              └── drafts stay hidden here

APPROVAL (single record) ─ PUT /{id} {status_id:4}
        └──► ExtraWorksController:1285-1296
               UPDATE extra_works_attachments SET is_draft = 0 WHERE extra_work_id = ? AND is_draft = 1
               ⇒ THE ONLY PUBLISH PATH.  One-way; revert does not undo it.

GROUP "Goedkeuren" ─ POST /{id}/archive/approve → status 8, status 4 never visited
        ⇒ drafts remain is_draft = 1 FOREVER
        ⇒ the record is now in the invoicing pool (status 8) with hidden completion photos

COMMENT ─ POST /{id}/comments {files:[{id}]} ──► is_comment=1, comment_id=N, is_pre_file=0

EVERY ExtraWorkAttachment::created
        └──► broadcast ExtraWorkAttachmentAdded
               ├──► Redis "private-user.{id}" to UCB holders (no scope_mask filter) + admins
               └──► NO push_notifications row, NO activity row, NO mail

DELETE ─ DELETE /{id}/attachments/{aid}
        └── if is_draft = 0 → only role slug 'admin' may proceed (403 otherwise)
```

## 3.4 Comment → notification → unread, in one picture

```
POST /admin/extra-works/{id}/comments        (ucb.permission: extra_works,update)
   │  validation: comment required|max:10000; parent_comment_id exists; mentioned_users exists
   ▼
ExtraWorkService::addComment
   ├─ ExtraWorkComment::create(type='user', mentioned_users=…)   ← mentioned_users then DEAD
   │     │
   │     ├──► ExtraWorkComment::booted::created (type==='user' only)
   │     │       └──► dispatch(afterResponse) → RecipientDeterminer
   │     │              → NotificationService::sendToUser('comment_created', …)
   │     │                 ├─ push_enabled? type enabled? (comment_created is UNMAPPED → always yes)
   │     │                 ├─ quiet hours?  → suppressed, NOT deferred
   │     │                 ├─ push_notifications row  (status pending → sent|failed)
   │     │                 ├─ per active token: push_notification_devices row + FCM
   │     │                 └─ broadcast NotificationUserEvent
   │     │
   │     └──► ExtraWorkCommentObserver::created
   │             └── shouldTranslate()? → AutoTranslateJob (queue: database)
   │
   ├─ per file: ExtraWorkAttachment(is_comment=1, comment_id=…)  ──► attachment broadcast
   │
   ├─ extra_work_comment_reads fan-out: creator(string→never) + assignees + role.name='admin'
   │
   └─ broadcast ExtraWorkCommentPosted
           ├── its CONSTRUCTOR calls App\Services\NotificationService::sendToUsers  (Redis only)
           │      audience: UCB holders (no scope_mask) + role.name='admin', minus the author
           └── broadcastOn(): extra-work.{id}, user.{author}, department users, active
               assignees, role.name='admin', and  user.{extra_works.created_by}
                                                       └── a NAME string → channel "user.B Amsterdam"
```

## 3.5 Where my area touches money and invoicing

- **The invoicing pool is `status_id = 8`.** The group "Goedkeuren" button is one of only two
  ways to reach 8 (the other being the single-record archive approve), and it reaches it from
  status 3 without passing through 4. So group-processed work enters invoicing with
  `approved_at = NULL`, `approved_by = NULL`, `is_approved = false` and unpublished drafts.
  *DATA — group 17, all eight members:* `status_id 8`, `approved_at null`, `approved_by null`,
  `is_approved false`, `completed_at 2025-12-23T15:54:28..31`,
  `archive_approved_at 2025-12-23T15:55:28..31` — one second apart per record, the signature of
  a client-side loop, not a mass update.
- **The invoice line description is the title** (tier-1 A1/A3: `InvoiceController.php:145`,
  `'description' => $work->title`). The title is also the storage medium for the schedule
  suffix and the condition. **So `[WK45-03.11.2025:18:00-op]` is printed on the customer's
  invoice line.** And because `GroupBulkEditModal` rewrites the title from the *translated*
  variant, a bulk edit can change the text that will appear on an invoice into another
  language.
- `PUT /admin/extra-works/groups/{id}/status` accepts an unvalidated `status_id` and mass-updates
  a whole group. Setting it to 9 marks a whole group "invoiced" with no invoice; setting it to
  8 on a group that contains status-9 members pulls them off a sent invoice. It requires only
  `extra_works,update`. This is the group-shaped version of the risk the RBAC handoff already
  flagged for `PUT /{id}/status`.
- `DELETE /admin/extra-works/groups/{id}` has **no status guard** and will soft-delete
  status-8 and status-9 members. `invoice_items.extra_work_id` is `ON DELETE RESTRICT`, but a
  soft delete never hits that constraint, so the invoice line survives pointing at a hidden row.

## 3.6 Notification reachability, summarised

```
                       writes a row the bell can show?
extra_work_created          yes ── but audience = RecipientDeterminer → empty since ~2025-11-19
extra_work_updated          yes ── same
melding_created/updated     yes ── same
comment_created             yes ── same, AND its user preference is unmapped (inert)
status_changed              yes ── audience includes admins; the ONLY type still arriving
extra_work_assigned         yes ── audience = the assignee alone; preference unmapped (inert)
melding_assigned            yes ── same
inbox_message               yes ── opt-in per call; no preference
internal_message            yes ── opt-in per call; no preference
attachment added            NO  ── Redis + broadcast only
status changed (event path) NO  ── Redis + broadcast only
record updated (event path) NO  ── Redis + broadcast only
comment posted (event path) NO  ── Redis + broadcast only
deadline_reminder           NEVER SENT ── template exists in 4 languages, no caller
approval_requested          NEVER SENT
assigned_to_work            NEVER SENT
extra_work_approved         NEVER SENT
extra_work_rejected         NEVER SENT
any email about an extra work / melding / comment / attachment  ── DOES NOT EXIST
```

---

# 4. Where my evidence CONTRADICTS a tier-1 report

**(1) The group bar button does NOT use the mass-update endpoint.**

Tier-1 A1 (`01-extra-work.md`, §2.4 and the §3.2 transition table) says:

> the group "Goedkeuren" button (source 3 → target 4, `WorkflowActionsBar.jsx:302`) sets
> `status_id = 4` on N records with **no `approved_at`, no `approved_by`, no system comment,
> no broadcast, no FCM, no activity row, and no draft-attachment publication**

and lists the transition as `N records, s → t | group bar button | PUT /groups/{groupId}/status`.

**That is wrong on the endpoint, wrong on the target status, and wrong on the events — but
right by accident on the outcome for drafts.** The line cited, `WorkflowActionsBar.jsx:302`,
is `const found = groupData.group.status_distribution.find((s) => s.status_id === statusId);`
— a helper, not a call.

What actually happens:
*CODE — `WorkflowActionsBar.jsx:307-311`:*
```js
const groupActionConfig = {
  1: { targetStatus: 2, icon: 'mdi:calendar-clock', label: 'Plannen',    color: 'primary' },
  2: { targetStatus: 3, icon: 'mdi:check-circle',   label: 'Voltooien',  color: 'success' },
  3: { targetStatus: 4, icon: 'mdi:check-decagram', label: 'Goedkeuren', color: 'secondary' },
};
```
*CODE — `:369`:* `onClick={() => onGroupBulkAction(status.status_id, config.targetStatus, status.count)}`
*CODE — `detail.jsx:444-468` (`handleGroupBulkAction`):*
```js
if (sourceStatusId === 1 && targetStatusId === 2)       setBulkPlanModalOpen(true);
else if (sourceStatusId === 2 && targetStatusId === 3)  setBulkCompleteModalOpen(true);
else if ((sourceStatusId === 3 && targetStatusId === 4) || (sourceStatusId === 4 && targetStatusId === 8))
                                                        setBulkArchiveApproveModalOpen(true);
```
and the modals loop over the members using ordinary per-record endpoints:
*CODE — `ExtraWorkBulkPlanModal.jsx:215`:* `await apiClient.put(`/admin/extra-works/${work.id}`, updatePayload);`
*CODE — `ExtraWorkBulkCompleteModal.jsx:95`:* `await apiClient.put(`/admin/extra-works/${work.id}`, updatePayload);`
*CODE — `ExtraWorkBulkArchiveApproveModal.jsx:77`:* `await apiClient.post(`/admin/extra-works/${work.id}/archive/approve`, payload);`

So the group bar **does** stamp, **does** fire model events, **does** write system comments and
**does** write archive columns. It does not publish drafts, but for a different reason than A1
gave: the "Goedkeuren" button whose config says `targetStatus: 4` actually routes to the
archive-approve modal and lands the records on **status 8**, skipping 4 entirely.

The mass-update endpoint `PUT /admin/extra-works/groups/{groupId}/status` has exactly **one**
caller in the whole front end — *CODE `GroupEditModal.jsx:112`* — and A1's description of its
event-free behaviour is correct for that caller.

**(2) `extra_work_groups.building_id` is not a type error.**

Tier-1 A1 §2.4 writes:

> **The group's `building_id` is populated with a `customer_buildings.id`,** not a
> `buildings.id`.

presented among the defects. The value is correct for the schema: the migration declares
`->foreign('building_id')->references('id')->on('customer_buildings')`
(`2025_12_23_100800:24`) and the model declares
`belongsTo(CustomerBuilding::class, 'building_id')` (`ExtraWorkGroup.php:41`). The column is
badly *named*, but writing a customer-building id into it is what both the FK and the relation
require. The real problem with the column is that **nothing reads it**.

**(3) A partial correction on `getRelatedUsers`.**

A1 reports the `created_by`-as-user-id bug in `app/Models/ExtraWork.php:841-861`. It exists a
second time, verbatim, in `app/Services/ExtraWorkService.php:371-386`, and that is the copy
that runs for user comments posted from the SPA. A1's conclusion ("only assignees and users
with role name `admin` receive unread rows") holds for both.

---

# 5. COULD NOT DETERMINE

1. **Whether the `roles` table has a `slug` column, and what its values are.**
   This decides whether `RecipientDeterminer` (hyphenated slugs), `updateStatus`
   (`slug = 'admin'`), `deleteAttachment` (`$user->role->slug === 'admin'`) and
   `deleteComment` (`slug in ['admin','location_manager']`) work at all. There is no
   `create roles` migration in the repo, `Role::$fillable` does not list `slug`, and the
   `/admin/roles` payload omits it. Every other role check in the codebase uses the
   underscored `name`, and `/admin/roles` confirms those `name` values.
   *To close:* `SHOW COLUMNS FROM roles;` and `SELECT id, name, slug FROM roles;`.
   Until then my claim that `RecipientDeterminer` matches nobody is **INFERRED**, not proved
   — although the DATA (no model-event notification since 2025-11-19) is consistent with it,
   and the admin-exclusion half of the claim is certain from the code alone.

2. **Whether `attachment_added` / `comment_added` / `user_assigned` really came from
   `ExtraWorkService::sendNotificationToUsers`.** I proved those helper methods have zero
   callers today, and I proved the historical rows exist with exactly those type names while
   the current code emits different names. The link between them is **INFERRED**.
   *To close:* `git log -p app/Services/ExtraWorkService.php app/Models/ExtraWorkComment.php`
   around 2025-11-18..20.

3. **Whether the 15 empty groups are failed batches or deleted-member remnants.**
   `bulkDeleteGroup` deletes the group row too, so it cannot be the cause; a failed
   `batchStore` can. But I could not query for soft-deleted members.
   *To close:* `SELECT g.id, g.created_at, COUNT(ew.id) AS live, SUM(ew.deleted_at IS NOT NULL)
   AS deleted FROM extra_work_groups g LEFT JOIN extra_works ew ON ew.extra_work_group_id = g.id
   GROUP BY g.id;`

4. **Whether any `is_draft = true` attachment has ever existed.** Live: zero on every record I
   could reach, and I could not scan the whole table. The exposure I describe in §1.6 is
   therefore structural rather than observed.
   *To close:* `SELECT is_draft, is_pre_file, is_comment, COUNT(*) FROM extra_works_attachments
   GROUP BY 1,2,3;`

5. **Whether the old dash-format title suffix came from an earlier `batchStore` or from a
   client-side loop.** 44 live records carry it and all 44 are ungrouped, which points at a
   pre-group client loop, but that is **INFERRED**.
   *To close:* the git history of `batchStore` and of `add.jsx`.

6. **Whether a queue worker is running.** `AutoTranslateJob` / `AutoTranslateCommentJob` are
   queued on the `database` connection, and the FCM dispatches use `->afterResponse()` (which
   needs no worker). Populated `title_nl`/`title_en`/`title_tr`/`title_bg` on live records
   imply a worker exists, but that is inference.
   *To close:* `SELECT COUNT(*) FROM jobs; SELECT COUNT(*) FROM failed_jobs;` and the host's
   supervisor/systemd unit list. **This also belongs to the infrastructure handoff** — the
   same read that would settle whether an external cron drives anything.

7. **Whether an external cron drives anything the application does not declare.** I proved the
   *application* declares no scheduler. I cannot see `deploy.sh`, `crm-laravel.service`,
   `crm-socket.service` or the host crontab, so a cron calling an HTTP endpoint on a timer
   would be invisible to me. Given that none of the reminder templates has a caller anywhere,
   even a cron would have nothing extra-work-related to invoke. **Same handoff as tier-1's
   infrastructure item.**

8. **Who consumes `portal_extra_works`.** I confirmed the view's exact column list and
   confirmed a customer portal exists at `portal.osius.nl` (from a live file record's
   `uploaded_from` and URL). I could not confirm that the portal reads this view rather than
   the API. What I *can* state definitively is that the view carries **no attachment and no
   group columns**, so neither drafts nor grouping can reach a consumer through it.
   *To close:* the portal's own source, or a DB grant/connection audit.

9. **What `messages.priority` and `internal_messages.priority` do.** Both are stored and both
   have a `byPriority` scope used as a list filter. `internal_messages` additionally uses
   `priority === 'urgent'` to prefix the notification title with "ACİL". Beyond that I found
   no consumer, but I read only `InternalMessageService`, not `InternalMessagesController`'s
   `conversations` view in full.

10. **The `websocket-server/` side of the Redis/broadcast path.** Everything I say about
    system 2 and system 3 stops at `Redis::publish` and at `broadcastOn()`. Whether the socket
    server actually authorises `private-user.{id}` channels, and what it does with a channel
    named `user.B Amsterdam`, is outside this repository.

11. **Whether `POST /admin/extra-works/{id}/comments` and the attachment endpoints really
    accept what I say they accept.** Every claim about a write path in this report is
    CODE-level, read from the controller, the service and the SPA. I issued no writes — the
    ground rules forbid it. The DATA in this report is all GET.

## Stopping point

I read in full: `ExtraWorkGroup`, `ExtraWorkAttachment`, `ExtraWorkComment`,
`ExtraWorkCommentRead`, `Message`, `InternalMessage`, `PushNotification`,
`PushNotificationDevice`, `UserFcmToken`, `UserNotificationSetting`, `MailTemplate`,
`MailLog` (fillable/casts/docblock), `ExtraWorkCommentObserver`, `RecipientDeterminer`,
`NotificationFormatter`, `App\Services\Firebase\NotificationService`,
`App\Services\NotificationService`, `FcmService` (constructor + availability),
`ExtraWorkAttachmentAdded`, `ExtraWorkCommentPosted`, `ExtraWorkStatusChanged`,
`ExtraWorkUpdated`, `bootstrap/app.php`, `routes/console.php`, `config/notifications.php`,
`AppServiceProvider`, the group/attachment/comment/message migrations, the full
`portal_extra_works` view definition, and the route blocks for extra-works, meldings,
messages, internal-messages, firebase and mail.

In `ExtraWorksController` (6434 lines) I read in full: `batchStore`, `getGroupMembers`,
`bulkUpdateGroupStatus`, `bulkDeleteGroup`, `getAttachments`, `addAttachment`,
`deleteAttachment`, `getComments`, `addComment`, `updateComment`, `deleteComment`,
`addCommentAttachment`, `deleteCommentAttachment`, `markCommentAsRead`,
`getUnreadCommentsCount`, `markAllCommentsAsRead`, `updateStatus`, `addEmployee`,
`show`, the draft-publication blocks in `update` (`:1275-1335`), and the group-aware filter
and group block in `buildQuery` / `transformModelData`.

In `ExtraWorkService` (1130 lines) I read in full: every attachment method, every comment
method, `getRelatedUsers`, `extractStatusInfo`, `generateActivityDescription`,
`getNotificationRecipients`, `sendNotificationToUsers`.

In the front end I read: `GroupBulkEditModal`, `GroupEditModal`, `ExtraWorkFilesTab`,
`ExtraWorkCommentsTab` (fetch + post), `ExtraWorkCompletionModal`, the three bulk workflow
modals, `WorkflowActionsBar`'s group section, `ExtraWorkDetailHeader`'s group card,
`detail.jsx`'s group and tab wiring, and `add.jsx`'s batch payload.

I did **not** read in full: `MailController` (2600+ lines — I read `scheduleBulkSend`,
`sendTicketNotification` and the `MailLog::create` call sites, not the bulk-send machinery),
`InternalMessagesController`, `MessagesController`, `NotificationSettingsController`,
`IncomingMailProcessor`, `TemplateManager`, `FcmService` beyond its constructor and
`sendToDevice`, and the V2 equivalents (`ExtraWorkV2Attachment`, `ExtraWorkV2Comment`,
`ExtraWorkV2CommentRead`), which I touched only where they clarified a v1 column's origin.
The mail *bulk* subsystem and the V2 comment/attachment family are the two obvious next
starting points if anyone needs them.
