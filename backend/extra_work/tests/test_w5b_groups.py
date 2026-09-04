"""
W5-B — day-by-day (multi-date) Extra Work.

    POST  /api/extra-work/batch/
    GET   /api/extra-work/groups/<id>/
    PATCH /api/extra-work/groups/<id>/members/

WHAT THESE TESTS ARE GUARDING, beyond "the feature works":

  * **Every member is a REAL Extra Work.** Created by the same
    serializer the single form posts to, with its own status, its own
    lifecycle and its own money. A group owns nothing. The reference
    system's batch path writes its own field set inline and drifted:
    over there `requested_at` holds the SCHEDULED SLOT rather than a
    request time, so it reads 22 days BEFORE `created_at` and "any
    report that reads `requested_at` as 'when was this asked for' is
    wrong for every batch-created record" (A1 §batchStore).

  * **All or nothing.** One transaction around every member and the
    group. Theirs has none, and the live consequence is that 15 of
    their 19 group rows have zero members (A7 §1.2).

  * **The title is composed, NEVER parsed.** Every fact in the suffix
    is also a real column and the columns are authoritative. Over there
    the title IS the storage, which produced two incompatible suffix
    formats whose parser understands only one, and a bulk editor that
    overwrites the stored title with the editing user's language
    variant — a title that becomes the invoice line description
    (A7 §1.3, §1.4).

  * **`condition` distinguishes "at handover" from "nobody said".**
    Theirs cannot: `match($entry['condition'] ?? 'at')` collapses the
    two, and A7 §2.2 records the consequence in one line.

  * **Tenant scoping, and no group-shaped hole in it.** None of the
    reference system's three group endpoints applies its scope filter.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from unittest import mock

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work.groups import MAX_BATCH_SLOTS, compose_member_title
from extra_work.models import (
    ExtraWorkCondition,
    ExtraWorkGroup,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from test_utils import TenantFixtureMixin


BATCH_URL = "/api/extra-work/batch/"


def group_url(pk):
    return f"/api/extra-work/groups/{pk}/"


def members_url(pk):
    return f"/api/extra-work/groups/{pk}/members/"


class GroupTestBase(TenantFixtureMixin, APITestCase):
    def shared(self, **overrides):
        payload = {
            "customer": self.customer.id,
            "building": self.building.id,
            "title": "Trappenhuis",
            "description": "Wekelijkse ronde",
            "urgency": "NORMAL",
            "billed_to": "CUSTOMER",
            # P-16 repin — P-15's intent rule: a PROVIDER creating a
            # non-agreed cart gets no silent default (intent_required);
            # AUTO_START_AFTER_PRICING is the provider-legal choice.
            # The group mechanics under test are unchanged.
            "request_intent": "AUTO_START_AFTER_PRICING",
            "line_items": [
                {
                    # W-EW1 §2 — no per-line date. The batch writer sets
                    # `preferred_date` per SLOT and hands the same shared
                    # payload to the same create serializer, so every
                    # member's lines are stamped with THAT member's date.
                    "service": None,
                    "custom_description": "Trappenhuis",
                    "quantity": "1.00",
                }
            ],
        }
        payload.update(overrides)
        return payload

    def batch(self, slots, actor=None, **overrides):
        self.authenticate(actor or self.company_admin)
        body = self.shared(**overrides)
        body["slots"] = slots
        return self.client.post(BATCH_URL, body, format="json")


class BatchCreateTests(GroupTestBase):
    def test_ONE_FORM_MANY_WORKS(self):
        response = self.batch(
            [
                {"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"},
                {"date": "2026-11-26", "time": "18:00", "condition": "BEFORE_HANDOVER"},
                {"date": "2026-12-03", "time": "09:30", "condition": "AFTER_HANDOVER"},
            ]
        )

        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )
        self.assertEqual(response.data["created"], 3)
        group = ExtraWorkGroup.objects.get(pk=response.data["group"]["id"])
        self.assertEqual(group.members.count(), 3)

    def test_EVERY_MEMBER_IS_A_REAL_EXTRA_WORK(self):
        """Not a lightweight schedule row. Own id, own status, own
        lifecycle — and created by the SAME serializer the single form
        posts to, which is what stops a second write path from drifting
        away from the first."""
        response = self.batch(
            [{"date": "2026-11-19"}, {"date": "2026-11-26"}]
        )

        members = ExtraWorkRequest.objects.filter(
            id__in=response.data["members"]
        ).order_by("group_sequence")
        self.assertEqual(members.count(), 2)
        for member in members:
            self.assertEqual(member.status, ExtraWorkStatus.REQUESTED)
            self.assertEqual(member.customer_id, self.customer.id)
            self.assertEqual(member.building_id, self.building.id)
            self.assertEqual(member.description, "Wekelijkse ronde")
            # The cart went through classification like any other create.
            self.assertTrue(member.line_items.exists())

    def test_the_slot_is_stored_in_COLUMNS_not_only_in_the_title(self):
        response = self.batch(
            [{"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"}]
        )

        member = ExtraWorkRequest.objects.get(pk=response.data["members"][0])
        self.assertEqual(member.preferred_date, date(2026, 11, 19))
        self.assertEqual(member.scheduled_time, time(18, 0))
        self.assertEqual(member.condition, ExtraWorkCondition.AT_HANDOVER)
        self.assertEqual(member.group_sequence, 1)

    def test_the_composed_title_matches_the_agreed_format(self):
        response = self.batch(
            [{"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"}]
        )

        member = ExtraWorkRequest.objects.get(pk=response.data["members"][0])
        self.assertEqual(
            member.title, "Trappenhuis [WK47-19.11.2026:18:00:op]"
        )

    def test_a_slot_with_no_time_does_not_claim_midnight(self):
        """And a slot with no condition does not claim "at handover".
        Both absences are real answers and the title says so by leaving
        the part out."""
        response = self.batch([{"date": "2026-11-19"}])

        member = ExtraWorkRequest.objects.get(pk=response.data["members"][0])
        self.assertIsNone(member.scheduled_time)
        self.assertIsNone(member.condition)
        self.assertEqual(member.title, "Trappenhuis [WK47-19.11.2026]")

    def test_NOBODY_SAID_IS_NOT_THE_SAME_AS_AT_HANDOVER(self):
        """The reference system cannot express this. Its
        `match($entry['condition'] ?? 'at')` turns an unanswered slot
        into `op`, and A7 §2.2 records the consequence: "The operator
        cannot tell 'explicitly at' from 'not specified'."
        """
        response = self.batch(
            [
                {"date": "2026-11-19", "condition": "AT_HANDOVER"},
                {"date": "2026-11-20"},
            ]
        )

        first, second = (
            ExtraWorkRequest.objects.filter(id__in=response.data["members"])
            .order_by("group_sequence")
        )
        self.assertEqual(first.condition, ExtraWorkCondition.AT_HANDOVER)
        self.assertIsNone(second.condition)

    def test_the_group_carries_the_standard_title_unsuffixed(self):
        response = self.batch([{"date": "2026-11-19", "time": "18:00"}])

        group = ExtraWorkGroup.objects.get(pk=response.data["group"]["id"])
        self.assertEqual(group.standard_title, "Trappenhuis")

    def test_the_groups_tenant_anchors_come_from_the_members(self):
        """So a group whose company/customer/building disagree with its
        own members is not expressible."""
        response = self.batch([{"date": "2026-11-19"}])

        group = ExtraWorkGroup.objects.get(pk=response.data["group"]["id"])
        member = ExtraWorkRequest.objects.get(pk=response.data["members"][0])
        self.assertEqual(group.company_id, member.company_id)
        self.assertEqual(group.customer_id, member.customer_id)
        self.assertEqual(group.building_id, member.building_id)


class BatchGuardTests(GroupTestBase):
    def test_THE_CAP_IS_ENFORCED_SERVER_SIDE(self):
        """A fat-fingered range is a real risk: "every weekday next
        year" is 260 works, each spawning a ticket and a notification
        fan-out."""
        slots = [
            {"date": date.fromordinal(date(2027, 1, 1).toordinal() + i).isoformat()}
            for i in range(MAX_BATCH_SLOTS + 1)
        ]

        response = self.batch(slots)

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_batch_too_many_slots"
        )
        self.assertEqual(response.data["limit"], MAX_BATCH_SLOTS)
        # And nothing was created.
        self.assertEqual(ExtraWorkGroup.objects.count(), 0)
        self.assertEqual(ExtraWorkRequest.objects.count(), 0)

    def test_exactly_the_cap_is_allowed(self):
        slots = [
            {"date": date.fromordinal(date(2027, 1, 1).toordinal() + i).isoformat()}
            for i in range(MAX_BATCH_SLOTS)
        ]

        response = self.batch(slots)

        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )
        self.assertEqual(response.data["created"], MAX_BATCH_SLOTS)

    def test_the_same_slot_twice_is_refused(self):
        response = self.batch(
            [
                {"date": "2027-02-01", "time": "09:00"},
                {"date": "2027-02-01", "time": "09:00"},
            ]
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_batch_duplicate_slot"
        )
        self.assertEqual(ExtraWorkRequest.objects.count(), 0)

    def test_the_same_DAY_at_two_TIMES_is_fine(self):
        """Three slots on the handover day is the normal case, not a
        mistake."""
        response = self.batch(
            [
                {"date": "2027-02-01", "time": "09:00"},
                {"date": "2027-02-01", "time": "13:00"},
            ]
        )

        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data
        )

    def test_AN_EMPTY_SLOT_LIST_IS_REFUSED(self):
        response = self.batch([])

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )

    def test_A_FAILURE_MIDWAY_ROLLS_BACK_THE_MEMBERS_ALREADY_CREATED(self):
        """The reference system's signature defect, refused.

        Over there the group is created first and the member loop is not
        wrapped in a transaction, so a throw leaves the group behind with
        nothing in it — and 15 of their 19 live group rows are in exactly
        that state (A7 §1.2, §2.1).

        Patched to fail AFTER all three members are written, so this
        proves rollback of work already committed to the session rather
        than a refusal at the door.
        """
        with mock.patch(
            "extra_work.groups.ExtraWorkGroup.objects.create",
            side_effect=RuntimeError("boom after the members were written"),
        ):
            with self.assertRaises(RuntimeError):
                self.batch(
                    [
                        {"date": "2027-03-01"},
                        {"date": "2027-03-02"},
                        {"date": "2027-03-03"},
                    ]
                )

        # Every member created before the failure is gone, and so is any
        # group row.
        self.assertEqual(ExtraWorkRequest.objects.count(), 0)
        self.assertEqual(ExtraWorkGroup.objects.count(), 0)

    def test_a_bad_shared_payload_creates_nothing(self):
        """The slots are fine; the cart is empty. A single create would
        refuse it, so the batch refuses it too — with no group left
        behind."""
        response = self.batch(
            [{"date": "2027-03-01"}, {"date": "2027-03-02"}], line_items=[]
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(ExtraWorkGroup.objects.count(), 0)
        self.assertEqual(ExtraWorkRequest.objects.count(), 0)

    def test_JSON_ONLY_AT_THE_DOOR(self):
        """DRF reads a boolean ABSENT from form input as False, so a
        form-encoded write could silently clear a completion flag across
        a whole series. Pinned on both group writes."""
        self.authenticate(self.company_admin)
        response = self.client.post(
            BATCH_URL, {"customer": self.customer.id}, format="multipart"
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )


class TitleCompositionTests(APITestCase):
    """`compose_member_title` runs ONE WAY. There is no inverse and there
    must never be — see the module docstring for what parsing costs."""

    def test_the_full_suffix(self):
        self.assertEqual(
            compose_member_title(
                "Trappenhuis",
                date(2026, 11, 19),
                time(18, 0),
                ExtraWorkCondition.AT_HANDOVER,
            ),
            "Trappenhuis [WK47-19.11.2026:18:00:op]",
        )

    def test_each_condition_gets_its_own_dutch_code(self):
        for condition, code in (
            (ExtraWorkCondition.AT_HANDOVER, "op"),
            (ExtraWorkCondition.BEFORE_HANDOVER, "voor"),
            (ExtraWorkCondition.AFTER_HANDOVER, "na"),
        ):
            self.assertTrue(
                compose_member_title(
                    "T", date(2026, 11, 19), time(18, 0), condition
                ).endswith(f":{code}]"),
                condition,
            )

    def test_absent_parts_are_left_out_rather_than_defaulted(self):
        self.assertEqual(
            compose_member_title("T", date(2026, 11, 19), None, None),
            "T [WK47-19.11.2026]",
        )
        self.assertEqual(
            compose_member_title(
                "T", date(2026, 11, 19), time(9, 30), None
            ),
            "T [WK47-19.11.2026:09:30]",
        )

    def test_no_date_means_no_suffix_at_all(self):
        self.assertEqual(compose_member_title("T", None, None, None), "T")


class GroupReadTests(GroupTestBase):
    def setUp(self):
        super().setUp()
        response = self.batch(
            [
                {"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"},
                {"date": "2026-11-26", "time": "18:00"},
            ]
        )
        self.group_id = response.data["group"]["id"]
        self.member_ids = response.data["members"]

    def test_the_members_come_back_in_sequence(self):
        self.authenticate(self.company_admin)
        response = self.client.get(group_url(self.group_id))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            [row["group_sequence"] for row in response.data["members"]], [1, 2]
        )

    def test_the_counts_describe_the_whole_series(self):
        self.authenticate(self.company_admin)
        response = self.client.get(group_url(self.group_id))

        block = response.data["group"]
        self.assertEqual(block["member_count"], 2)
        self.assertEqual(
            block["status_counts"], [{"status": "REQUESTED", "count": 2}]
        )

    def test_the_LIST_row_carries_the_same_whole_series_counts(self):
        """Whole-group truth, not page truth, so a badge reading "2"
        never depends on how the list happened to paginate. The
        reference system instead marks `group_sequence == 1` as a header
        row and branches its status filter on it — "the group-header
        inflation that makes list totals and statistics totals
        disagree" (A7 §2.1)."""
        self.authenticate(self.company_admin)
        response = self.client.get("/api/extra-work/?page_size=100")

        rows = {row["id"]: row for row in response.data["results"]}
        for member_id in self.member_ids:
            block = rows[member_id]["group"]
            self.assertIsNotNone(block)
            self.assertEqual(block["id"], self.group_id)
            self.assertEqual(block["member_count"], 2)

    def test_A_WORK_WITH_NO_GROUP_RENDERS_group_NULL(self):
        """The normal case must not regress. A standalone work is not a
        series of one."""
        solo = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Ordinary work",
            description="x",
            status=ExtraWorkStatus.REQUESTED,
        )

        self.authenticate(self.company_admin)
        response = self.client.get("/api/extra-work/?page_size=100")

        rows = {row["id"]: row for row in response.data["results"]}
        self.assertIsNone(rows[solo.id]["group"])

    def test_H1_a_foreign_group_is_a_404(self):
        """None of the reference system's three group endpoints applies
        its scope filter at all (A7 §2.1)."""
        self.authenticate(self.other_company_admin)
        response = self.client.get(group_url(self.group_id))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_group_that_does_not_exist_answers_the_same_way(self):
        self.authenticate(self.other_company_admin)
        foreign = self.client.get(group_url(self.group_id))
        fiction = self.client.get(group_url(98765432))

        self.assertEqual(foreign.status_code, fiction.status_code)


class GroupMemberEditTests(GroupTestBase):
    def setUp(self):
        super().setUp()
        response = self.batch(
            [
                {"date": "2026-11-19", "time": "18:00", "condition": "AT_HANDOVER"},
                {"date": "2026-11-26", "time": "18:00", "condition": "AT_HANDOVER"},
            ]
        )
        self.group_id = response.data["group"]["id"]
        self.first, self.second = response.data["members"]

    def patch_members(self, members, actor=None):
        self.authenticate(actor or self.company_admin)
        return self.client.patch(
            members_url(self.group_id), {"members": members}, format="json"
        )

    def test_condition_and_time_are_edited_by_KEY_PRESENCE(self):
        response = self.patch_members(
            [{"extra_work": self.first, "condition": "AFTER_HANDOVER"}]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        first = ExtraWorkRequest.objects.get(pk=self.first)
        second = ExtraWorkRequest.objects.get(pk=self.second)
        self.assertEqual(first.condition, ExtraWorkCondition.AFTER_HANDOVER)
        # Untouched: not mentioned, not written.
        self.assertEqual(first.scheduled_time, time(18, 0))
        self.assertEqual(second.condition, ExtraWorkCondition.AT_HANDOVER)

    def test_condition_can_be_CLEARED_back_to_nobody_said(self):
        response = self.patch_members(
            [{"extra_work": self.first, "condition": None}]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(ExtraWorkRequest.objects.get(pk=self.first).condition)

    def test_A_TITLE_IS_REGENERATED_FROM_COLUMNS_NEVER_PARSED(self):
        """The operator moves the slot to 07:00 and asks for the title
        to catch up. The new suffix is derived from `preferred_date`,
        `scheduled_time` and `condition` — the old title is never read.

        This is the exact operation the reference system gets wrong in
        two ways at once: its regex only understands the newer of two
        suffix formats it has produced, and the week number it writes
        comes from the GROUP rather than the row, so "group 19 spans
        weeks 3, 4 and 5 but the group's week_number is 3. Saving a row
        in the bulk-edit modal rewrites its suffix with WK3 regardless
        of the row's actual date" (A7 §2.1).
        """
        # A deliberately misleading hand-edited title, to prove nothing
        # reads it.
        member = ExtraWorkRequest.objects.get(pk=self.second)
        member.title = "Something else entirely [WK1-01.01.2000:00:00:na]"
        member.save(update_fields=["title"])

        response = self.patch_members(
            [
                {
                    "extra_work": self.second,
                    "scheduled_time": "07:00",
                    "regenerate_title": True,
                }
            ]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        member.refresh_from_db()
        # WK48 from the ROW's own date, 07:00 from the column just set.
        self.assertEqual(
            member.title, "Trappenhuis [WK48-26.11.2026:07:00:op]"
        )

    def test_a_hand_written_title_is_kept_when_regenerate_is_not_asked(self):
        response = self.patch_members(
            [{"extra_work": self.first, "title": "Bespoke name"}]
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            ExtraWorkRequest.objects.get(pk=self.first).title, "Bespoke name"
        )

    def test_ALL_OR_NOTHING(self):
        """One unresolvable member rejects the batch with zero writes."""
        response = self.patch_members(
            [
                {"extra_work": self.first, "condition": "AFTER_HANDOVER"},
                {"extra_work": 98765432, "condition": "AFTER_HANDOVER"},
            ]
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(
            ExtraWorkRequest.objects.get(pk=self.first).condition,
            ExtraWorkCondition.AT_HANDOVER,
        )

    def test_a_work_from_ANOTHER_group_cannot_be_edited_through_this_one(self):
        other = self.batch([{"date": "2027-05-05"}])
        stranger = other.data["members"][0]

        response = self.patch_members(
            [{"extra_work": stranger, "condition": "AFTER_HANDOVER"}]
        )

        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )

    def test_a_customer_is_refused_at_the_door(self):
        response = self.patch_members(
            [{"extra_work": self.first, "condition": "AFTER_HANDOVER"}],
            actor=self.customer_user,
        )

        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertEqual(
            response.data["code"], "extra_work_group_provider_only"
        )

    def test_JSON_ONLY_ON_THE_MEMBER_EDIT_TOO(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            members_url(self.group_id),
            {"members": [{"extra_work": self.first}]},
            format="multipart",
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )


class MembersAreIndependentTests(GroupTestBase):
    """The rule the whole feature rests on: a group is a convenience,
    never an owner. Deleting or cancelling one member must not disturb
    the others, and no total anywhere comes from a group."""

    def setUp(self):
        super().setUp()
        response = self.batch(
            [
                {"date": "2026-11-19"},
                {"date": "2026-11-26"},
                {"date": "2026-12-03"},
            ]
        )
        self.group_id = response.data["group"]["id"]
        self.member_ids = response.data["members"]

    def test_DELETING_ONE_MEMBER_LEAVES_THE_OTHERS_ALONE(self):
        ExtraWorkRequest.objects.get(pk=self.member_ids[1]).delete()

        survivors = ExtraWorkRequest.objects.filter(
            id__in=self.member_ids
        ).order_by("group_sequence")
        self.assertEqual(survivors.count(), 2)
        for survivor in survivors:
            self.assertEqual(survivor.group_id, self.group_id)
        # And the count follows, because it is derived and not frozen.
        # The reference freezes `group_total` at creation and never
        # decrements it (A7 §2.1).
        group = ExtraWorkGroup.objects.get(pk=self.group_id)
        self.assertEqual(group.members.count(), 2)

    def test_ONE_MEMBER_MOVING_STATUS_DOES_NOT_MOVE_THE_REST(self):
        member = ExtraWorkRequest.objects.get(pk=self.member_ids[0])
        member.status = ExtraWorkStatus.CANCELLED
        member.save(update_fields=["status"])

        others = ExtraWorkRequest.objects.filter(
            id__in=self.member_ids[1:]
        )
        for other in others:
            self.assertEqual(other.status, ExtraWorkStatus.REQUESTED)

    def test_LOSING_THE_GROUP_DOES_NOT_TAKE_THE_WORK_WITH_IT(self):
        """`SET_NULL`, never CASCADE. The reference system's group
        delete soft-deletes every member with no status check at all, so
        a group containing invoiced work can be removed in one click
        (A7 §2.1). Ours cannot express that."""
        ExtraWorkGroup.objects.get(pk=self.group_id).delete()

        survivors = ExtraWorkRequest.objects.filter(id__in=self.member_ids)
        self.assertEqual(survivors.count(), 3)
        for survivor in survivors:
            self.assertIsNone(survivor.group_id)

    def test_a_member_prices_and_invoices_entirely_on_its_own(self):
        """No total anywhere is computed from a group. Money still flows
        per work."""
        first = ExtraWorkRequest.objects.get(pk=self.member_ids[0])
        first.subtotal_amount = Decimal("100.00")
        first.save(update_fields=["subtotal_amount"])

        second = ExtraWorkRequest.objects.get(pk=self.member_ids[1])
        self.assertEqual(second.subtotal_amount, Decimal("0.00"))
