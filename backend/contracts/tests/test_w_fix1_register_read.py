"""W-FIX1 D2 + D5 (audit F26, F9) — the register GET is a read, and a
building manager reads their buildings.

D2. `GET /api/contracts/extra-works/<customer>/` used to get-or-create
    the register and, for a manager, sync it — a write with no
    uniqueness guard under it. It now writes nothing: before the first
    sync it answers the same shape with `contract: null`; the explicit
    `POST .../sync/` makes and refreshes the register, and syncing twice
    concurrently is serialised on the contract row.
D5. A BUILDING_MANAGER receives the buildings they manage — lines,
    building list and summary alike — the same narrowing every other
    contract read applies to them.
"""
from __future__ import annotations

from decimal import Decimal

from buildings.models import BuildingManagerAssignment
from customers.models import CustomerBuildingMembership
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus

from contracts.models import Contract, ContractKind, ContractLine

from .test_w16_extra_work_register import RegisterFixture, register_url, sync_url


class TheRegisterGetIsARead(RegisterFixture):
    def test_before_the_first_sync_the_get_creates_nothing(self):
        before = Contract.objects.filter(kind=ContractKind.EXTRA_WORK).count()

        response = self.api(self.ca_a).get(register_url(self.customer_a.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["contract"])
        self.assertEqual(response.data["summary"]["job_count"], 0)
        self.assertEqual(response.data["summary"]["pending_sync"], 2)
        names = [b["name"] for b in response.data["buildings"]]
        self.assertIn(self.building_a.name, names)
        self.assertEqual(
            Contract.objects.filter(kind=ContractKind.EXTRA_WORK).count(), before
        )

    def test_a_manager_reading_twice_does_not_sync(self):
        self.api(self.ca_a).get(register_url(self.customer_a.id))
        self.api(self.ca_a).get(register_url(self.customer_a.id))
        self.assertEqual(ContractLine.objects.filter(extra_work__isnull=False).count(), 0)

    def test_the_sync_makes_the_register_and_the_get_then_reads_it(self):
        synced = self.api(self.ca_a).post(sync_url(self.customer_a.id))
        self.assertEqual(synced.status_code, 200, synced.data)
        self.assertEqual(synced.data["changed"]["added"], 2)

        response = self.api(self.ca_a).get(register_url(self.customer_a.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["contract"]["kind"], "EXTRA_WORK")
        self.assertEqual(response.data["summary"]["job_count"], 2)

    def test_syncing_twice_makes_no_duplicate_lines(self):
        self.api(self.ca_a).post(sync_url(self.customer_a.id))
        self.api(self.ca_a).post(sync_url(self.customer_a.id))
        per_ew = (
            ContractLine.objects.filter(extra_work__isnull=False)
            .values_list("extra_work_id", flat=True)
        )
        self.assertEqual(len(per_ew), len(set(per_ew)))


class TheRegisterIsScopedToAManagersBuildings(RegisterFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        CustomerBuildingMembership.objects.get_or_create(
            customer=cls.customer_a, building=cls.building_a2
        )
        cls.ew_elsewhere = ExtraWorkRequest.objects.create(
            company=cls.company_a,
            building=cls.building_a2,
            customer=cls.customer_a,
            created_by=cls.ca_a,
            title="Elsewhere",
            description="at A2, which bm_a does not manage",
            status=ExtraWorkStatus.COMPLETED,
            subtotal_amount=Decimal("300.00"),
            vat_amount=Decimal("63.00"),
            total_amount=Decimal("300.00"),
        )

    def setUp(self):
        super().setUp()
        self.api(self.ca_a).post(sync_url(self.customer_a.id))

    def test_the_admin_reads_every_building(self):
        response = self.api(self.ca_a).get(register_url(self.customer_a.id))
        names = {b["name"] for b in response.data["buildings"]}
        self.assertEqual(names, {self.building_a.name, self.building_a2.name})
        self.assertEqual(response.data["summary"]["job_count"], 3)

    def test_a_manager_reads_only_the_buildings_they_manage(self):
        self.assertTrue(
            BuildingManagerAssignment.objects.filter(
                user=self.bm_a, building=self.building_a
            ).exists()
        )
        response = self.api(self.bm_a).get(register_url(self.customer_a.id))
        self.assertEqual(response.status_code, 200, response.data)
        names = {b["name"] for b in response.data["buildings"]}
        self.assertEqual(names, {self.building_a.name})
        titles = {
            line["name"]
            for building in response.data["buildings"]
            for line in building["lines"]
        }
        self.assertNotIn("Elsewhere", titles)
        self.assertEqual(response.data["summary"]["job_count"], 2)
        self.assertEqual(response.data["summary"]["building_count"], 1)

    def test_the_other_manager_reads_the_other_building(self):
        response = self.api(self.bm_a2).get(register_url(self.customer_a.id))
        self.assertEqual(response.status_code, 200, response.data)
        names = {b["name"] for b in response.data["buildings"]}
        self.assertEqual(names, {self.building_a2.name})
        self.assertEqual(response.data["summary"]["job_count"], 1)
