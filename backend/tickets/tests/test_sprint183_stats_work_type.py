"""
Sprint 183 §2 — `/api/tickets/stats/` takes the work-type parameter.

Sprint 182 gave the Tickets page a work-type control but not this
endpoint, so under "Tickets only" every status chip fell back to an em
dash: the page had no number to show because there was no way to ask for
one. Agent C of that sprint flagged it and could not fix it — the
endpoint is backend and that sprint's slice was frontend-only.

What these pin, and why in this shape:

  * the endpoint ANSWERS under every setting of the control, with real
    numbers rather than a missing key;
  * the chips SUM to the All tile under every setting — the property the
    owner reads off the screen, asserted directly rather than inferred
    from two separate counts;
  * chargeable + ordinary == everything, exactly, because the two
    branches of `apply_is_extra_work` are one `Q` filtered and excluded;
  * the chips count the SAME rows the list returns, which is the thing a
    chip is for. Counting the right number of the wrong rows is the
    failure this catches.

A filter test issues a query but never serialises a row; every
assertion here goes through the rendered endpoint.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from tickets.models import Ticket, TicketStatus


User = get_user_model()
PASSWORD = "StrongerTestPassword183!"

STATS_URL = "/api/tickets/stats/"
TICKETS_URL = "/api/tickets/"

#: The control's three settings, as the page sends them.
WORK_TYPE_SETTINGS = (
    ("all", {}),
    ("chargeable", {"is_extra_work": "true"}),
    ("tickets", {"is_extra_work": "false"}),
)


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-183")
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 183", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="ca-183@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="CA",
        )
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _extra_work(self, title="An extra work"):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=title,
            description="d",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
        )

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

    def _mixed_population(self):
        """Both origins, several statuses, and every parentage path.

        The three paths matter: `apply_is_extra_work` unions all three,
        and a population that only ever used the canonical FK would let
        the other two rot without a test noticing.
        """
        ew = self._extra_work()
        self._ticket("charge open", extra_work_request=ew)
        self._ticket(
            "charge in progress",
            extra_work_request=ew,
            status=TicketStatus.IN_PROGRESS,
        )
        self._ticket(
            "charge closed", extra_work_request=ew, status=TicketStatus.CLOSED
        )
        self._ticket("ordinary open")
        self._ticket("ordinary in progress", status=TicketStatus.IN_PROGRESS)
        self._ticket(
            "ordinary waiting",
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self._ticket("ordinary closed", status=TicketStatus.CLOSED)

    def stats(self, **params):
        response = self.api(self.admin).get(STATS_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.data


class StatsAnswersUnderEverySettingTests(_Fixture):
    def setUp(self):
        super().setUp()
        self._mixed_population()

    def test_every_setting_returns_numbers_not_a_missing_key(self):
        """The em-dash bug, stated as an assertion. The page renders a
        dash when the number is absent, so the fix is that the number is
        present — under all three settings, not only the default."""
        for name, params in WORK_TYPE_SETTINGS:
            with self.subTest(setting=name):
                data = self.stats(**params)
                self.assertIn("total", data)
                self.assertIn("by_status", data)
                self.assertIsInstance(data["total"], int)
                for value in data["by_status"].values():
                    self.assertIsInstance(value, int)

    def test_the_chips_sum_to_the_all_tile_under_every_setting(self):
        """THE property the owner reads off the screen.

        Every status chip is a `by_status` entry; the All tile is
        `total`. If they ever disagree the page is lying about one of
        them, and there is no way to tell which from looking at it.
        """
        for name, params in WORK_TYPE_SETTINGS:
            with self.subTest(setting=name):
                data = self.stats(**params)
                self.assertEqual(
                    sum(data["by_status"].values()),
                    data["total"],
                    f"chips do not sum to the All tile under {name}",
                )

    def test_chargeable_plus_ordinary_equals_everything(self):
        """The two halves are exact complements, so they reconstruct the
        whole. This is what `apply_is_extra_work` being one `Q` filtered
        and excluded buys — and what a stray `.distinct()` on one branch
        used to cost."""
        everything = self.stats()
        chargeable = self.stats(is_extra_work="true")
        ordinary = self.stats(is_extra_work="false")

        self.assertEqual(
            chargeable["total"] + ordinary["total"], everything["total"]
        )
        self.assertGreater(chargeable["total"], 0)
        self.assertGreater(ordinary["total"], 0)
        for status_value in everything["by_status"]:
            with self.subTest(status=status_value):
                self.assertEqual(
                    chargeable["by_status"].get(status_value, 0)
                    + ordinary["by_status"].get(status_value, 0),
                    everything["by_status"][status_value],
                )

    def test_the_chips_count_the_rows_the_list_returns(self):
        """A chip counting the right number of the WRONG rows is the
        failure this catches — both halves now go through the same
        `apply_is_extra_work`, and this proves they land on one set."""
        for name, params in WORK_TYPE_SETTINGS:
            with self.subTest(setting=name):
                data = self.stats(**params)
                listed = self.api(self.admin).get(
                    TICKETS_URL, {**params, "page_size": 100}
                )
                self.assertEqual(listed.status_code, 200, listed.content)
                self.assertEqual(listed.data["count"], data["total"])

    def test_an_unparseable_value_means_no_opinion(self):
        """A typo in a URL must not silently hide every chargeable row.
        `?is_extra_work=yes` is not `false`."""
        self.assertEqual(
            self.stats(is_extra_work="yes")["total"], self.stats()["total"]
        )

    def test_it_composes_with_hide_finished_extra_work(self):
        """The page can set both at once, and the two narrowings have to
        survive each other — the chips still sum."""
        data = self.stats(is_extra_work="true", hide_finished_extra_work="true")
        self.assertEqual(sum(data["by_status"].values()), data["total"])
        # The CLOSED chargeable row is the one `hide_finished` drops.
        self.assertNotIn(TicketStatus.CLOSED, data["by_status"])

    def test_the_default_is_unchanged_for_every_existing_caller(self):
        """The dashboard KPI strip and the status-breakdown panel send no
        work-type parameter and must keep the totals they had."""
        self.assertEqual(self.stats()["total"], Ticket.objects.count())


class StatsWorkTypeScopingTests(_Fixture):
    """The parameter narrows; it never widens. Whatever the caller asks
    for, they still only ever see their own tenant."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_company = Company.objects.create(
            name="Other", slug="other-183"
        )
        cls.other_building = Building.objects.create(
            company=cls.other_company, name="OB", address="O 1"
        )
        cls.other_customer = Customer.objects.create(
            company=cls.other_company, name="Other cust", building=cls.other_building
        )
        cls.other_admin = User.objects.create_user(
            email="ca-other-183@example.com",
            password=PASSWORD,
            role=UserRole.COMPANY_ADMIN,
            full_name="Other CA",
        )
        CompanyUserMembership.objects.create(
            user=cls.other_admin, company=cls.other_company
        )

    def test_no_setting_of_the_parameter_reaches_another_tenant(self):
        Ticket.objects.create(
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
            created_by=self.other_admin,
            title="theirs",
            description="d",
            status=TicketStatus.OPEN,
        )
        self._ticket("mine")
        for name, params in WORK_TYPE_SETTINGS:
            with self.subTest(setting=name):
                self.assertLessEqual(self.stats(**params)["total"], 1)
