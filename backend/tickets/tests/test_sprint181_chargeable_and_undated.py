"""Sprint 181 §5/§8 — the two new backend surfaces, each rendered.

  §5  `?is_extra_work=` — every chargeable-work ticket as a GROUP.
      `?extra_work_request=<id>` has always answered "which tickets came
      from THAT extra work"; nothing answered "which came from an extra
      work at all", so the sub-page listing them had no query to make.
  §8  `undated_entries` on the work-plan payload. `counts.undated` was
      already there and the page could only say how much work it was
      declining to show.

Both get a test that RENDERS the endpoint carrying them: a filter test
issues a query but never serialises a row, and a payload key that is
counted but not returned is exactly the shape §8 exists to fix.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import Ticket, TicketStaffAssignment, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword181!"

TICKETS_URL = "/api/tickets/"
WORK_PLAN_URL = "/api/tickets/work-plan/"


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-181")
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 181", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="ca-181@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="CA",
        )
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.staff = User.objects.create_user(
            email="staff-181@example.com",
            password=PASSWORD,
            role=UserRole.STAFF,
            full_name="Staff",
        )
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _ticket(self, title, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=title,
            description="d",
            status=extra.pop("status", TicketStatus.OPEN),
            **extra,
        )

    def _extra_work(self):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="An extra work",
            description="d",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
        )


class IsExtraWorkFilterTests(_Fixture):
    def test_true_returns_only_chargeable_work(self):
        ew = self._extra_work()
        chargeable = self._ticket("From an extra work", extra_work_request=ew)
        ordinary = self._ticket("An ordinary melding")

        resp = self.api(self.admin).get(TICKETS_URL, {"is_extra_work": "true"})
        self.assertEqual(resp.status_code, 200, resp.content)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertIn(chargeable.id, ids)
        self.assertNotIn(ordinary.id, ids)

    def test_false_returns_only_ordinary_tickets(self):
        ew = self._extra_work()
        chargeable = self._ticket("From an extra work", extra_work_request=ew)
        ordinary = self._ticket("An ordinary melding")

        resp = self.api(self.admin).get(TICKETS_URL, {"is_extra_work": "false"})
        self.assertEqual(resp.status_code, 200, resp.content)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertIn(ordinary.id, ids)
        self.assertNotIn(chargeable.id, ids)

    def test_absent_param_changes_nothing(self):
        """Every existing caller keeps its behaviour."""
        ew = self._extra_work()
        chargeable = self._ticket("From an extra work", extra_work_request=ew)
        ordinary = self._ticket("An ordinary melding")

        resp = self.api(self.admin).get(TICKETS_URL)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertIn(chargeable.id, ids)
        self.assertIn(ordinary.id, ids)

    def test_rows_still_serialise_their_origin(self):
        """The sub-page renders the pill from `extra_work_origin`, so the
        filtered rows must still carry it — a filter test that only
        counted ids would miss a serializer break."""
        ew = self._extra_work()
        self._ticket("From an extra work", extra_work_request=ew)

        resp = self.api(self.admin).get(TICKETS_URL, {"is_extra_work": "true"})
        row = resp.data["results"][0]
        self.assertIsNotNone(row["extra_work_origin"])
        self.assertEqual(
            row["extra_work_origin"]["extra_work_request_id"], ew.id
        )

    def test_no_duplicate_rows(self):
        """Two of the three parentage paths join through a to-many
        relation; without `distinct()` a ticket would appear twice."""
        ew = self._extra_work()
        self._ticket("From an extra work", extra_work_request=ew)

        resp = self.api(self.admin).get(TICKETS_URL, {"is_extra_work": "true"})
        ids = [row["id"] for row in resp.data["results"]]
        self.assertEqual(len(ids), len(set(ids)))


class UndatedEntriesTests(_Fixture):
    def test_undated_slot_is_returned_as_a_row(self):
        """§8 — the payload carries the ROWS, not just `counts.undated`."""
        ticket = self._ticket("Nobody has scheduled this")
        TicketStaffAssignment.objects.create(ticket=ticket, user=self.staff)

        resp = self.api(self.staff).get(WORK_PLAN_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("undated_entries", resp.data)
        titles = {e["title"] for e in resp.data["undated_entries"]}
        self.assertIn("Nobody has scheduled this", titles)

    def test_the_row_count_agrees_with_the_count_that_was_already_there(self):
        """The lane and the number must not be able to disagree — that is
        the whole subject of this sprint."""
        for i in range(3):
            ticket = self._ticket(f"Undated {i}")
            TicketStaffAssignment.objects.create(
                ticket=ticket, user=self.staff
            )

        resp = self.api(self.staff).get(WORK_PLAN_URL)
        self.assertEqual(
            len(resp.data["undated_entries"]),
            resp.data["counts"]["undated"],
        )

    def test_limit_and_truncation_flag_are_published(self):
        """Same contract as the two sibling lists: a list that silently
        stops is the same defect as a count describing one page."""
        resp = self.api(self.staff).get(WORK_PLAN_URL)
        self.assertIn("undated_entries", resp.data["limits"])
        self.assertIn("undated_entries", resp.data["truncated"])
        self.assertFalse(resp.data["truncated"]["undated_entries"])

    def test_a_scheduled_slot_is_not_in_the_lane(self):
        """`scheduled_start_at` lives on the ASSIGNMENT (the slot), not
        on the ticket — `_slot_undated_q` filters
        `TicketStaffAssignment`. Getting that wrong the first time is
        why this test is here."""
        from django.utils import timezone

        ticket = self._ticket("This one has a date")
        TicketStaffAssignment.objects.create(
            ticket=ticket,
            user=self.staff,
            scheduled_start_at=timezone.now(),
        )

        resp = self.api(self.staff).get(WORK_PLAN_URL)
        titles = {e["title"] for e in resp.data["undated_entries"]}
        self.assertNotIn("This one has a date", titles)
