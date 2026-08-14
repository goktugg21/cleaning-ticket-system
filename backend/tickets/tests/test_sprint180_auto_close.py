"""
Sprint 180 §1 + §2 — customer approval closes the ticket, and the
ticket list stops carrying finished Extra Work.

§1. `WAITING_CUSTOMER_APPROVAL -> APPROVED` now auto-drives
    `APPROVED -> CLOSED` as a SYSTEM transition (`tickets/auto_close.py`).
    That is not cosmetic: `extra_work.billing.is_earned` demands CLOSED
    *specifically*, while the Extra Work auto-sync treats APPROVED and
    CLOSED alike — so before this sprint an Extra Work could read
    "Completed", be genuinely finished, and never become invoiceable.
    The tests below pin the trigger (the customer-decision leg and only
    it), the audit shape (a system-authored history row), the edge
    cases each named in the sprint brief, and the money consequence.

§2. `TicketFilter.hide_finished_extra_work` drops EW-spawned tickets
    whose OWN status is finished, and `/api/tickets/stats/` accepts the
    same flag so the count chips above the list agree with the rows in
    it.

The list-rendering tests deliberately go through the real endpoint and
read the serialised rows, not just the row count: a filter test issues a
query but never serialises a row, so it cannot catch a broken `fields`
entry (Sprint 173).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.billing import build_ticket_map, is_earned
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    ExtraWorkStatus,
    Service,
    ServiceCategory,
)
from tickets.auto_close import (
    AUTO_CLOSE_NOTE,
    STALLED_CUSTOMER_APPROVAL_DAYS,
    should_auto_close,
)
from tickets.models import Ticket, TicketStatus, TicketStatusHistory
from tickets.state_machine import (
    SYSTEM_AUTO_TRANSITIONS,
    TransitionError,
    apply_transition,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
STATUS_URL = "/api/tickets/{ticket_id}/status/"
LIST_URL = "/api/tickets/"
STATS_URL = "/api/tickets/stats/"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _AutoCloseFixtureMixin:
    """
    One provider company, one building, one customer, the four actors
    that matter for the approval leg, and a service catalog so Extra
    Work requests can be built.

    Tickets are created per-test rather than in the fixture: most tests
    need a ticket at a specific point in the walk, and sharing one
    across the auto-close tests would couple them.
    """

    @classmethod
    def _setup_fixture(cls, suffix: str):
        cls.company = Company.objects.create(
            name=f"Provider {suffix}", slug=f"prov-{suffix}"
        )
        cls.building = Building.objects.create(
            company=cls.company, name=f"Building {suffix}"
        )
        cls.customer = Customer.objects.create(
            company=cls.company,
            name=f"Customer {suffix}",
            building=cls.building,
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        cls.super_admin = _mk(
            f"super-{suffix}@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk(f"admin-{suffix}@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.manager = _mk(
            f"mgr-{suffix}@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        cls.cust_user = _mk(
            f"cust-{suffix}@example.com", UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        cls.service_cat = ServiceCategory.objects.create(
            company=cls.company, name=f"Cat {suffix}"
        )
        cls.service = Service.objects.create(
            category=cls.service_cat,
            company=cls.company,
            name=f"Service {suffix}",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

    # -- builders ---------------------------------------------------

    def _make_ticket(self, *, title="Ticket", status_value=None, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title=title,
            description="seed",
            status=status_value or TicketStatus.OPEN,
            **extra,
        )

    def _make_extra_work(self, *, title="EW", ew_status=None):
        """An EW anchored on the CANONICAL `extra_work_request` FK —
        the path `extra_work.billing.build_ticket_map` reads."""
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.cust_user,
            title=title,
            description="seed",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ew_status or ExtraWorkStatus.CUSTOMER_APPROVED,
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew,
            service=self.service,
            quantity=Decimal("1.00"),
            unit_type=ExtraWorkPricingUnitType.FIXED,
            requested_date=date(2026, 6, 1),
        )
        return ew

    def _walk_to_customer_approval(self, ticket, actor=None):
        """OPEN -> IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL through the
        real state machine, so `sent_for_approval_at` is stamped the way
        production stamps it."""
        actor = actor or self.admin
        ticket = apply_transition(
            ticket, actor, TicketStatus.IN_PROGRESS, note="walk"
        )
        return apply_transition(
            ticket,
            actor,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="walk",
        )

    def _api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


# ---------------------------------------------------------------------------
# §1 — the trigger
# ---------------------------------------------------------------------------
class CustomerApprovalAutoCloseTests(_AutoCloseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-close")

    def test_customer_approval_closes_the_ticket(self):
        ticket = self._walk_to_customer_approval(self._make_ticket())

        closed = apply_transition(
            ticket, self.cust_user, TicketStatus.APPROVED, note="looks good"
        )

        self.assertEqual(str(closed.status), str(TicketStatus.CLOSED))
        closed.refresh_from_db()
        self.assertEqual(str(closed.status), str(TicketStatus.CLOSED))
        # The APPROVED stamps survive — the ticket passed THROUGH
        # approved, it did not skip it.
        self.assertIsNotNone(closed.approved_at)
        self.assertIsNotNone(closed.resolved_at)
        # `closed_at` is what `extra_work.billing.billing_month` reads.
        self.assertIsNotNone(closed.closed_at)

    def test_apply_transition_returns_the_ticket_in_its_true_final_state(self):
        # The return value is what the serializer renders into the HTTP
        # response; if it still said APPROVED the client would show a
        # status the database disagrees with.
        ticket = self._walk_to_customer_approval(self._make_ticket())
        returned = apply_transition(
            ticket, self.cust_user, TicketStatus.APPROVED
        )
        self.assertEqual(
            str(returned.status),
            str(Ticket.objects.get(pk=ticket.pk).status),
        )

    def test_the_close_is_recorded_as_a_system_transition(self):
        ticket = self._walk_to_customer_approval(self._make_ticket())
        apply_transition(ticket, self.cust_user, TicketStatus.APPROVED)

        rows = list(
            TicketStatusHistory.objects.filter(ticket=ticket).order_by(
                "created_at", "id"
            )
        )
        approved_row = rows[-2]
        closed_row = rows[-1]

        self.assertEqual(
            str(approved_row.new_status), str(TicketStatus.APPROVED)
        )
        self.assertEqual(approved_row.changed_by_id, self.cust_user.id)

        self.assertEqual(str(closed_row.old_status), str(TicketStatus.APPROVED))
        self.assertEqual(str(closed_row.new_status), str(TicketStatus.CLOSED))
        # No person closed it. `changed_by IS NULL` is the system marker.
        self.assertIsNone(closed_row.changed_by_id)
        self.assertEqual(closed_row.note, AUTO_CLOSE_NOTE)
        # H-11: the auto-close is not a workflow override — nobody
        # overrode anybody's decision, the decision was honoured.
        self.assertFalse(closed_row.is_override)
        self.assertEqual(closed_row.override_reason, "")

    def test_provider_approval_on_behalf_also_closes_and_keeps_its_override_row(self):
        # The on-behalf route already existed (reason required, override
        # coerced). It is still a recorded CUSTOMER decision — typically
        # the customer approving by phone — so it closes too. That is
        # the case that actually happens in the field, and leaving it
        # out would leave the money hole open for the common path.
        ticket = self._walk_to_customer_approval(self._make_ticket())

        closed = apply_transition(
            ticket,
            self.admin,
            TicketStatus.APPROVED,
            override_reason="Customer approved by phone",
        )

        self.assertEqual(str(closed.status), str(TicketStatus.CLOSED))
        approved_row = TicketStatusHistory.objects.filter(
            ticket=ticket, new_status=TicketStatus.APPROVED
        ).latest("created_at")
        self.assertTrue(approved_row.is_override)
        self.assertEqual(
            approved_row.override_reason, "Customer approved by phone"
        )
        self.assertEqual(approved_row.changed_by_id, self.admin.id)

    def test_rejection_does_not_close(self):
        # Rejected work loops back through IN_PROGRESS for rework. It is
        # live work; closing it would destroy the loop.
        ticket = self._walk_to_customer_approval(self._make_ticket())
        rejected = apply_transition(
            ticket,
            self.cust_user,
            TicketStatus.REJECTED,
            note="not done properly",
        )
        self.assertEqual(str(rejected.status), str(TicketStatus.REJECTED))
        self.assertIsNone(rejected.closed_at)

    def test_admin_approval_with_no_customer_involved_does_not_close(self):
        # A SUPER_ADMIN correcting a stuck ticket straight into APPROVED
        # is an administrative act, not a customer approval. The ticket
        # parks on APPROVED and an admin closes it by hand, exactly as
        # before this sprint.
        ticket = self._make_ticket()
        approved = apply_transition(
            ticket,
            self.super_admin,
            TicketStatus.APPROVED,
            note="admin correction",
        )
        self.assertEqual(str(approved.status), str(TicketStatus.APPROVED))
        self.assertIsNone(approved.closed_at)

        # ...and the manual close still works.
        closed = apply_transition(
            approved, self.super_admin, TicketStatus.CLOSED
        )
        self.assertEqual(str(closed.status), str(TicketStatus.CLOSED))

    def test_reopened_ticket_closes_again_on_the_next_approval(self):
        ticket = self._walk_to_customer_approval(self._make_ticket())
        ticket = apply_transition(
            ticket, self.cust_user, TicketStatus.APPROVED
        )
        first_closed_at = ticket.closed_at
        self.assertIsNotNone(first_closed_at)

        ticket = apply_transition(
            ticket, self.super_admin, TicketStatus.REOPENED_BY_ADMIN
        )
        ticket = apply_transition(
            ticket, self.admin, TicketStatus.IN_PROGRESS
        )
        ticket = apply_transition(
            ticket, self.admin, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )
        ticket = apply_transition(
            ticket, self.cust_user, TicketStatus.APPROVED
        )

        self.assertEqual(str(ticket.status), str(TicketStatus.CLOSED))
        # TIMESTAMP_ON_ENTER overwrites on a loop, which is what billing
        # wants: the SECOND completion is the one that bills.
        self.assertGreater(ticket.closed_at, first_closed_at)

    def test_should_auto_close_predicate(self):
        ticket = self._make_ticket(status_value=TicketStatus.APPROVED)
        self.assertTrue(
            should_auto_close(ticket, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        )
        self.assertFalse(should_auto_close(ticket, TicketStatus.IN_PROGRESS))
        self.assertFalse(should_auto_close(ticket, TicketStatus.OPEN))

        rejected = self._make_ticket(status_value=TicketStatus.REJECTED)
        self.assertFalse(
            should_auto_close(
                rejected, TicketStatus.WAITING_CUSTOMER_APPROVAL
            )
        )


# ---------------------------------------------------------------------------
# §1 — the system actor is not a super-role
# ---------------------------------------------------------------------------
class SystemActorTests(_AutoCloseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-sys")

    def test_system_auto_transitions_holds_only_the_close_pair(self):
        self.assertEqual(
            SYSTEM_AUTO_TRANSITIONS,
            {(TicketStatus.APPROVED, TicketStatus.CLOSED)},
        )

    def test_system_actor_may_drive_the_close_pair(self):
        ticket = self._make_ticket(status_value=TicketStatus.APPROVED)
        closed = apply_transition(ticket, None, TicketStatus.CLOSED)
        self.assertEqual(str(closed.status), str(TicketStatus.CLOSED))
        self.assertIsNone(
            TicketStatusHistory.objects.filter(ticket=ticket)
            .latest("created_at")
            .changed_by_id
        )

    def test_system_actor_cannot_drive_anything_else(self):
        # A `None` actor must not become a back door. Every pair outside
        # SYSTEM_AUTO_TRANSITIONS is refused, including ones a human
        # SUPER_ADMIN could drive.
        for source, target in (
            (TicketStatus.OPEN, TicketStatus.IN_PROGRESS),
            (TicketStatus.WAITING_CUSTOMER_APPROVAL, TicketStatus.APPROVED),
            (TicketStatus.CLOSED, TicketStatus.REOPENED_BY_ADMIN),
        ):
            with self.subTest(source=source, target=target):
                ticket = self._make_ticket(status_value=source)
                with self.assertRaises(TransitionError) as ctx:
                    apply_transition(ticket, None, target)
                self.assertEqual(ctx.exception.code, "forbidden_transition")


# ---------------------------------------------------------------------------
# §1 — the money consequence
# ---------------------------------------------------------------------------
class ExtraWorkBecomesInvoiceableTests(_AutoCloseFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-money")

    def test_customer_approval_makes_the_extra_work_earned(self):
        ew = self._make_extra_work()
        ticket = self._make_ticket(title="EW ticket", extra_work_request=ew)
        ticket = self._walk_to_customer_approval(ticket)

        apply_transition(ticket, self.cust_user, TicketStatus.APPROVED)

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.COMPLETED)

        # The predicate the invoice run actually uses.
        ticket_map = build_ticket_map([ew.id])
        self.assertTrue(is_earned(ticket_map.get(ew.id)))
        # ...and a billable month resolves, because closed_at is set.
        self.assertIsNotNone(ticket_map[ew.id].closed_at)

    def test_extra_work_with_two_tickets_completes_only_when_both_close(self):
        ew = self._make_extra_work(title="EW two")
        first = self._walk_to_customer_approval(
            self._make_ticket(title="EW ticket 1", extra_work_request=ew)
        )
        second = self._walk_to_customer_approval(
            self._make_ticket(title="EW ticket 2", extra_work_request=ew)
        )

        # First ticket into IN_PROGRESS already lifted the EW to
        # IN_PROGRESS via the Sprint 29 Batch 29.8 hook.
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

        apply_transition(first, self.cust_user, TicketStatus.APPROVED)
        ew.refresh_from_db()
        self.assertEqual(
            ew.status,
            ExtraWorkStatus.IN_PROGRESS,
            "one sibling still open — the parent must not complete",
        )

        apply_transition(second, self.cust_user, TicketStatus.APPROVED)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.COMPLETED)

        # Both spawned tickets closed, so `build_ticket_map`'s
        # representative row is CLOSED whichever one it picks.
        for spawned in Ticket.objects.filter(extra_work_request=ew):
            self.assertEqual(str(spawned.status), str(TicketStatus.CLOSED))


# ---------------------------------------------------------------------------
# §1 — one notification, about the decision
# ---------------------------------------------------------------------------
class AutoCloseNotificationTests(_AutoCloseFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-mail")

    def test_approval_sends_one_email_describing_the_approval(self):
        ticket = self._walk_to_customer_approval(self._make_ticket())
        mail.outbox = []

        response = self._api(self.cust_user).post(
            STATUS_URL.format(ticket_id=ticket.id),
            {"to_status": TicketStatus.APPROVED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        # The customer just acted; the close is bookkeeping. Exactly one
        # status-change mail goes out per recipient, and it is about the
        # approval, not about the close.
        self.assertTrue(
            all("Gesloten" not in message.subject for message in mail.outbox),
            [message.subject for message in mail.outbox],
        )

        # The response body carries the ticket's TRUE final status.
        self.assertEqual(response.data["status"], str(TicketStatus.CLOSED))

    def test_on_behalf_approval_keeps_its_dedicated_subject(self):
        # Regression guard for the view change: reading `updated.status`
        # after the auto-close would resolve `is_admin_override` to
        # False and silently downgrade this mail to a generic status
        # change.
        ticket = self._walk_to_customer_approval(self._make_ticket())
        mail.outbox = []

        response = self._api(self.admin).post(
            STATUS_URL.format(ticket_id=ticket.id),
            {
                "to_status": TicketStatus.APPROVED,
                "override_reason": "Customer approved by phone",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(
            any(
                "namens de klant" in message.subject
                for message in mail.outbox
            ),
            [message.subject for message in mail.outbox],
        )


# ---------------------------------------------------------------------------
# §1 — work the customer never answers
# ---------------------------------------------------------------------------
class StalledApprovalFilterTests(_AutoCloseFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-stall")

    def _age_approval(self, ticket, days):
        ticket.sent_for_approval_at = timezone.now() - timedelta(days=days)
        ticket.save(update_fields=["sent_for_approval_at"])
        return ticket

    def test_filter_returns_only_old_enough_awaiting_tickets(self):
        stale = self._age_approval(
            self._walk_to_customer_approval(self._make_ticket(title="Stale")),
            days=STALLED_CUSTOMER_APPROVAL_DAYS + 7,
        )
        fresh = self._walk_to_customer_approval(self._make_ticket(title="Fresh"))
        # A ticket that is old but no longer awaiting anything must not
        # appear — it is not stuck, it is done.
        done = self._age_approval(
            self._walk_to_customer_approval(self._make_ticket(title="Done")),
            days=STALLED_CUSTOMER_APPROVAL_DAYS + 7,
        )
        apply_transition(done, self.cust_user, TicketStatus.APPROVED)

        response = self._api(self.admin).get(
            LIST_URL,
            {
                "awaiting_customer_approval_days": (
                    STALLED_CUSTOMER_APPROVAL_DAYS
                )
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(stale.id, ids)
        self.assertNotIn(fresh.id, ids)
        self.assertNotIn(done.id, ids)

    def test_rows_with_no_sent_for_approval_at_are_not_aged(self):
        # A hand-set fixture that never went through the transition has
        # no age to measure; ageing it off `created_at` would put a
        # ticket the customer was never asked about into the "customer
        # is sitting on this" queue.
        never_sent = self._make_ticket(
            title="Never sent",
            status_value=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self.assertIsNone(never_sent.sent_for_approval_at)

        response = self._api(self.admin).get(
            LIST_URL, {"awaiting_customer_approval_days": 0}
        )
        ids = {row["id"] for row in response.data["results"]}
        self.assertNotIn(never_sent.id, ids)

    def test_filter_absent_leaves_the_list_untouched(self):
        awaiting = self._walk_to_customer_approval(self._make_ticket())
        response = self._api(self.admin).get(LIST_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(awaiting.id, ids)


# ---------------------------------------------------------------------------
# §2 — finished Extra Work leaves the ticket list
# ---------------------------------------------------------------------------
class HideFinishedExtraWorkTests(_AutoCloseFixtureMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-hide")

    def setUp(self):
        super().setUp()
        self.ew = self._make_extra_work(title="EW hide")

        # Finished EW-spawned work — the rows the owner asked to stop
        # seeing.
        self.ew_closed = self._walk_to_customer_approval(
            self._make_ticket(title="EW closed", extra_work_request=self.ew)
        )
        apply_transition(
            self.ew_closed, self.cust_user, TicketStatus.APPROVED
        )
        self.ew_closed.refresh_from_db()

        # Live EW-spawned work — must survive.
        self.ew_open = self._make_ticket(
            title="EW open", extra_work_request=self.ew
        )
        self.ew_rejected = self._walk_to_customer_approval(
            self._make_ticket(title="EW rejected", extra_work_request=self.ew)
        )
        self.ew_rejected = apply_transition(
            self.ew_rejected,
            self.cust_user,
            TicketStatus.REJECTED,
            note="redo it",
        )

        # A finished NORMAL ticket — not Extra Work, so not in scope of
        # the instruction and must survive.
        self.normal_closed = self._walk_to_customer_approval(
            self._make_ticket(title="Normal closed")
        )
        apply_transition(
            self.normal_closed, self.cust_user, TicketStatus.APPROVED
        )

    def _list_ids(self, **params):
        response = self._api(self.admin).get(LIST_URL, {"page_size": 100, **params})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data, {row["id"] for row in response.data["results"]}

    def test_hidden_by_default_is_opt_in_at_the_api(self):
        # No param == today's behaviour, so every existing caller is
        # untouched. The DEFAULT lives in the Tickets page, which shows
        # a clearable chip alongside it.
        _, ids = self._list_ids()
        self.assertIn(self.ew_closed.id, ids)

    def test_hiding_drops_finished_extra_work_only(self):
        _, ids = self._list_ids(hide_finished_extra_work="true")

        self.assertNotIn(self.ew_closed.id, ids)
        # Live extra work stays.
        self.assertIn(self.ew_open.id, ids)
        # Rejected extra work is live work awaiting rework, not finished.
        self.assertIn(self.ew_rejected.id, ids)
        # Finished NORMAL tickets are not extra work.
        self.assertIn(self.normal_closed.id, ids)

    def test_an_administratively_approved_extra_work_ticket_is_also_finished(self):
        approved_only = self._make_ticket(
            title="EW approved only", extra_work_request=self.ew
        )
        approved_only = apply_transition(
            approved_only, self.super_admin, TicketStatus.APPROVED
        )
        self.assertEqual(
            str(approved_only.status), str(TicketStatus.APPROVED)
        )

        _, ids = self._list_ids(hide_finished_extra_work="true")
        self.assertNotIn(approved_only.id, ids)

    def test_hiding_is_not_keyed_on_the_parent_status(self):
        # The whole reason §2 is keyed on the TICKET's status: a
        # provider can drive an Extra Work to COMPLETED by hand while a
        # spawned ticket is still open, and that ticket must not vanish.
        self.ew.status = ExtraWorkStatus.COMPLETED
        self.ew.save(update_fields=["status"])

        _, ids = self._list_ids(hide_finished_extra_work="true")
        self.assertIn(self.ew_open.id, ids)

    def test_rows_still_serialise_their_extra_work_origin(self):
        # A filter test issues a query but never renders a row. This one
        # renders: it reads the `extra_work_origin` payload the ticket
        # list, agenda and meldingen list draw their pill from.
        _, _ = self._list_ids(hide_finished_extra_work="true")
        response = self._api(self.admin).get(
            LIST_URL, {"page_size": 100, "hide_finished_extra_work": "true"}
        )
        row = next(
            r for r in response.data["results"] if r["id"] == self.ew_open.id
        )
        origin = row["extra_work_origin"]
        self.assertIsNotNone(origin)
        self.assertEqual(origin["extra_work_request_id"], self.ew.id)
        for key in (
            "extra_work_request_title",
            "extra_work_request_status",
            "extra_work_request_item_id",
            "service_name",
            "origin",
        ):
            self.assertIn(key, origin)

        normal_row = next(
            r
            for r in response.data["results"]
            if r["id"] == self.normal_closed.id
        )
        self.assertIsNone(normal_row["extra_work_origin"])

    def test_stats_counts_agree_with_the_rows(self):
        response = self._api(self.admin).get(
            STATS_URL, {"hide_finished_extra_work": "true"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        hidden_stats = response.data

        payload, ids = self._list_ids(hide_finished_extra_work="true")
        self.assertEqual(hidden_stats["total"], payload["count"])
        self.assertEqual(
            hidden_stats["by_status"].get(str(TicketStatus.CLOSED), 0),
            sum(
                1
                for row in payload["results"]
                if row["status"] == str(TicketStatus.CLOSED)
            ),
        )

    def test_stats_without_the_flag_is_unchanged(self):
        plain = self._api(self.admin).get(STATS_URL).data
        payload, _ = self._list_ids()
        self.assertEqual(plain["total"], payload["count"])

    def test_extra_work_detail_panel_still_lists_every_spawned_ticket(self):
        # The Extra Work detail page's own spawned-tickets panel asks
        # for `?extra_work_request=<id>` and nothing else. Showing every
        # ticket the request spawned is the entire point of that panel,
        # so the §2 hide must not reach it. It does not, because the
        # filter is opt-in — this test is the guard on that.
        response = self._api(self.admin).get(
            LIST_URL, {"extra_work_request": self.ew.id, "page_size": 100}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.ew_closed.id, ids)
        self.assertIn(self.ew_open.id, ids)
        self.assertIn(self.ew_rejected.id, ids)


# ---------------------------------------------------------------------------
# §1 — the system row survives serialisation
# ---------------------------------------------------------------------------
class SystemRowRendersTests(_AutoCloseFixtureMixin, APITestCase):
    """
    `TicketStatusHistory.changed_by` became nullable this sprint, and a
    nullable FK is exactly the kind of change that passes every unit
    test and then 500s the page that renders it. These go through the
    real detail endpoint for the actors who read timelines.
    """

    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture(suffix="180-render")

    def setUp(self):
        super().setUp()
        self.ticket = self._walk_to_customer_approval(self._make_ticket())
        apply_transition(self.ticket, self.cust_user, TicketStatus.APPROVED)

    def _detail(self, user):
        response = self._api(user).get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def test_detail_renders_the_system_row_for_every_reader(self):
        for actor, label in (
            (self.super_admin, "super admin"),
            (self.admin, "company admin"),
            (self.manager, "building manager"),
            (self.cust_user, "customer user"),
        ):
            with self.subTest(actor=label):
                rows = self._detail(actor)["status_history"]
                closed_rows = [
                    row
                    for row in rows
                    if row["new_status"] == str(TicketStatus.CLOSED)
                ]
                self.assertEqual(len(closed_rows), 1, rows)
                row = closed_rows[0]
                self.assertIsNone(row["changed_by"])
                # `changed_by_email` is a CharField with
                # `source="changed_by.email"`. On a NULL FK, DRF's
                # attribute traversal raises AttributeError, and a
                # read-only (therefore not-required) field turns that
                # into SkipField — so the key is OMITTED, not null.
                #
                # Both shapes read as "no author" to every consumer we
                # have (the frontend tests the value for truthiness),
                # so this is not a bug today. It IS an inconsistency
                # worth closing: `allow_null=True` on that field would
                # make it emit null like the audit timeline does. That
                # is a one-line change in `tickets/serializers.py`,
                # which this sprint does not own. Asserted with `.get`
                # so the test states the contract rather than the
                # accident.
                self.assertIsNone(row.get("changed_by_email"))
                # The note is what the timeline shows under "System", so
                # it must survive the customer-side redaction pass: a
                # row with no author is not a provider-authored row.
                self.assertEqual(row["note"], AUTO_CLOSE_NOTE)
                self.assertFalse(row["is_override"])

    def test_audit_timeline_renders_the_system_row(self):
        # The provider-audit unified timeline is a SEPARATE reader of
        # the same rows (`audit/views_ticket_timeline.py`), and it is
        # the one a SUPER_ADMIN actually sees.
        response = self._api(self.super_admin).get(
            f"/api/audit/tickets/{self.ticket.id}/timeline/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        rows = response.data["timeline"]
        closed_rows = [
            row
            for row in rows
            if row.get("source") == "status_history"
            and row.get("new_status") == str(TicketStatus.CLOSED)
        ]
        self.assertEqual(len(closed_rows), 1, rows)
        self.assertIsNone(closed_rows[0]["changed_by_email"])
        self.assertEqual(closed_rows[0]["note"], AUTO_CLOSE_NOTE)
