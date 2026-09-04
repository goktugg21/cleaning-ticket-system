"""W5-B — day-by-day Extra Work: the batch, and the title it composes.

    POST  /api/extra-work/batch/            one form, many works
    GET   /api/extra-work/groups/<id>/      the members and their spread
    PATCH /api/extra-work/groups/<id>/members/   title / time / condition

WHAT A GROUP IS FOR
-------------------
An operator agrees a series of visits in one conversation — every
Tuesday in November, or three slots on the handover day — and types the
job once. The group is the receipt for that click. It is a CREATION and
EDITING convenience and nothing else: see `models.ExtraWorkGroup` for
the full statement, and for why there is no group-status and no
group-delete endpoint here.

EVERY MEMBER GOES THROUGH THE ORDINARY CREATE PATH
--------------------------------------------------
`create_batch` calls `ExtraWorkRequestCreateSerializer` once per slot.
Not a stripped-down copy of it, not a bulk INSERT — the same serializer
the single create form posts to, with the same cart classification, the
same intent validation, the same routing decision and the same ticket
spawn. A member is therefore a real Extra Work in every respect on the
day it is born, which is the one rule this feature is not allowed to
bend.

The reference system takes the other road and pays for it. Its
`batchStore` writes its own field set inline, so batch-created records
carry `requested_at` = the SCHEDULED SLOT rather than a request time
("`requested_at` is 22 days BEFORE `created_at` -- it is the scheduled
slot, not a request time. Any report that reads `requested_at` as 'when
was this asked for' is wrong for every batch-created record", A1
§batchStore), never set `requested_by` at all, and write products with a
`unit` string where the single path writes `unit_id` — "two different
product-unit conventions on the same table". None of that can happen
here, because there is no second writer to drift from the first.

ALL OR NOTHING
--------------
One transaction around the group and every member. The reference has
"no transaction around batch creation. The group is created first; if
the loop then throws, the group survives with zero members", and the
live consequence is on the record: **15 of the 19 group rows in their
database have zero members** (A7 §1.2, §2.1). A group with no members
is not a state this code can produce.

THE TITLE SUFFIX IS A DISPLAY CONVENIENCE, NEVER A STORAGE MEDIUM
-----------------------------------------------------------------
Each member's title is composed once, at creation, as

    {standard title} [WK47-19.11.2025:18:00:op]

so a list of twelve siblings can be told apart at a glance. Every fact
in that suffix is ALSO a real column — `preferred_date`,
`scheduled_time`, `condition` — and the columns are the truth. Nothing
in this codebase parses a title. `compose_member_title` runs one way
only, and `regenerate` in the members endpoint re-derives the suffix
FROM the columns when a slot is edited; it never reads the old string to
find out what the slot was.

That is the whole point of the exercise. Over there the title IS the
storage: "the title column itself is the storage medium for four
separate pieces of scheduling data (week number, date, time,
condition), all of which also exist as real columns except the
condition" (A7 §1.3). The bill for that arrived in two instalments.
First, the suffix format changed and the parser was never taught the
old one, so 44 live records carry `[WK45-03.11.2025:18:00-op]` and 27
carry `[WK3-13.01.2026:00:00:op]`, and the bulk-edit regex matches only
the second. Second, the group editor reads the TRANSLATED title and
writes it back to the raw column, so "touching any row in that modal
permanently replaces the record's stored title with the editing user's
language variant" (A7 §1.4) — and that title becomes the invoice line
description (00-connection-map §369).
"""
from __future__ import annotations

from datetime import date as date_cls, time as time_cls

from django.db import transaction

from .models import ExtraWorkCondition, ExtraWorkGroup


#: The ceiling on one batch.
#:
#: A date range is typed by hand and a fat-fingered one is a real risk:
#: "every weekday next year" is 260 works, each of which spawns a ticket
#: and a notification fan-out. Sixty is chosen to clear the honest cases
#: with room to spare — a weekly visit for a year is 52, twice a week
#: for a quarter is 26, every day for two months is 60 — while making a
#: runaway range fail loudly at the door instead of quietly creating
#: hundreds of records somebody then has to cancel one by one.
#:
#: Enforced SERVER-SIDE. The picker also refuses to go past it, but a
#: client-side limit is a courtesy and this is the rule.
MAX_BATCH_SLOTS = 60

ERR_TOO_MANY_SLOTS = "extra_work_batch_too_many_slots"
ERR_DUPLICATE_SLOT = "extra_work_batch_duplicate_slot"
ERR_NO_SLOTS = "extra_work_batch_no_slots"

#: Dutch short codes, matching the reference system's vocabulary because
#: operators read these titles and nl is this product's primary
#: language. A LABEL, not a value: the value is the enum on the column.
_CONDITION_SUFFIX = {
    ExtraWorkCondition.AT_HANDOVER: "op",
    ExtraWorkCondition.BEFORE_HANDOVER: "voor",
    ExtraWorkCondition.AFTER_HANDOVER: "na",
}


def compose_member_title(
    standard_title: str,
    slot_date: date_cls | None,
    slot_time: time_cls | None,
    condition: str | None,
) -> str:
    """`{standard} [WK47-19.11.2025:18:00:op]` — one direction only.

    Absent parts are simply left out rather than defaulted, so a slot
    with no time reads `[WK47-19.11.2025]` instead of claiming midnight,
    and a slot nobody gave a condition to does not silently claim "at
    handover". That distinction is the reason `condition` is nullable —
    see `ExtraWorkCondition`.

    THERE IS NO INVERSE OF THIS FUNCTION, and there must never be. If
    you find yourself wanting to know a member's slot, read
    `preferred_date`, `scheduled_time` and `condition`; they are columns.
    """
    base = (standard_title or "").strip()
    if slot_date is None:
        return base
    week = slot_date.isocalendar()[1]
    parts = [f"WK{week}-{slot_date.strftime('%d.%m.%Y')}"]
    if slot_time is not None:
        parts.append(slot_time.strftime("%H:%M"))
    label = _CONDITION_SUFFIX.get(condition)
    if label:
        parts.append(label)
    suffix = ":".join(parts)
    return f"{base} [{suffix}]".strip()


class BatchRejected(Exception):
    """A refusal with a ready-to-return 400 body.

    Same shape as `planning.PlanRejected` so the bulk family answers in
    one dialect.
    """

    def __init__(self, body: dict):
        super().__init__(body.get("detail", ""))
        self.body = body


def validate_slots(slots: list[dict]) -> list[dict]:
    """Cap the batch and refuse a slot list that repeats itself.

    A duplicate (date, time) pair is almost always a picker mistake —
    the same day clicked twice — and creating two identical works is
    much harder to undo than refusing one click. The refusal names the
    slot, because unlike a tenant id there is nothing to leak: the
    caller sent it.
    """
    if not slots:
        raise BatchRejected(
            {
                "detail": "Pick at least one day for this work.",
                "code": ERR_NO_SLOTS,
            }
        )
    if len(slots) > MAX_BATCH_SLOTS:
        raise BatchRejected(
            {
                "detail": (
                    f"That would create {len(slots)} separate works. "
                    f"The most one batch may create is {MAX_BATCH_SLOTS}. "
                    "Narrow the date range, or create the rest as a "
                    "second batch."
                ),
                "code": ERR_TOO_MANY_SLOTS,
                "limit": MAX_BATCH_SLOTS,
                "requested": len(slots),
            }
        )
    seen: set[tuple] = set()
    for slot in slots:
        key = (slot["date"], slot.get("time"))
        if key in seen:
            when = slot["date"].isoformat()
            if slot.get("time") is not None:
                when = f"{when} {slot['time'].strftime('%H:%M')}"
            raise BatchRejected(
                {
                    "detail": (
                        f"{when} appears twice in the selection. Each "
                        "slot creates its own work, so the same slot "
                        "cannot be picked twice."
                    ),
                    "code": ERR_DUPLICATE_SLOT,
                }
            )
        seen.add(key)
    return slots


def create_batch(*, shared: dict, slots: list[dict], serializer_class, context):
    """Create one real Extra Work per slot, then the group, atomically.

    `shared` is the RAW, unvalidated payload every member shares —
    customer, building, description, labels, cart lines, intent,
    billing target — exactly as it arrived on the wire. It is handed to
    the create serializer untouched, so a member is validated by the
    same rules, in the same order, with the same error messages as a
    work created one at a time. Nothing here pre-digests it: a batch
    payload that a single create would reject is rejected here too, and
    for the same reason.

    `slots` is the validated `[{date, time, condition}, ...]` list.

    The group row is created AFTER the members and its tenant anchors
    are read off the members rather than off the request. That ordering
    is deliberate: the anchors then describe what was actually written,
    and a group whose company/customer/building disagree with its own
    members is not expressible. It also means a group with zero members
    cannot exist, which is the state 15 of the reference system's 19
    groups are in.

    Returns `(group, members)`.
    """
    slots = validate_slots(slots)
    standard_title = str(shared.get("title", "") or "")

    with transaction.atomic():
        members = []
        for slot in slots:
            payload = dict(shared)
            payload["title"] = compose_member_title(
                standard_title,
                slot["date"],
                slot.get("time"),
                slot.get("condition"),
            )
            payload["preferred_date"] = slot["date"].isoformat()
            # THE SAME SERIALIZER THE SINGLE FORM POSTS TO. See the
            # module docstring for why a second writer is not an option.
            serializer = serializer_class(data=payload, context=context)
            serializer.is_valid(raise_exception=True)
            members.append(serializer.save())

        first = members[0]
        group = ExtraWorkGroup.objects.create(
            company=first.company,
            customer=first.customer,
            building=first.building,
            standard_title=standard_title,
            created_by=context["request"].user,
        )
        for index, (member, slot) in enumerate(zip(members, slots), start=1):
            member.group = group
            member.group_sequence = index
            member.scheduled_time = slot.get("time")
            member.condition = slot.get("condition")
            member.save(
                update_fields=[
                    "group",
                    "group_sequence",
                    "scheduled_time",
                    "condition",
                    "updated_at",
                ]
            )
    return group, members


def group_status_counts(group) -> list[dict]:
    """`[{status, count}, ...]` over EVERY member, computed once.

    One query, from the members themselves. The reference system offers
    three member counts by three routes and they disagree: a frozen
    `group_total` that is never decremented, an Eloquent `item_count`
    that excludes soft-deleted rows, and a raw query-builder status
    distribution that does NOT — "so after a member is soft-deleted,
    `item_count` drops but the status distribution does not, and the two
    group summaries on the same screen disagree" (A7 §2.1). There is one
    count here and the badge and the expanded list are both rendered
    from it.
    """
    from django.db.models import Count

    rows = (
        group.members.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    return [{"status": row["status"], "count": row["count"]} for row in rows]
