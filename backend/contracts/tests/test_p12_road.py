"""
P-12 C1 — the contracts road: `?status=ENDING`, the Active tab's
`?ending=exclude` partition, and the stats' guidance facts
(`ending_soon`, `draft_without_lines`, `monthly_by_status`,
`start_here`). The road's rule: every contract lands in exactly one of
draft / active / ending / ended (cancelled off the road), and the
numbers the tabs print are the numbers the tabs' queries return.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.utils import timezone

from contracts.models import ContractLifecycle
from contracts.views_contracts import ENDING_SOON_DAYS

from .fixtures import CONTRACTS_URL, STATS_URL, ContractsFixture, make_contract


class ContractsRoadTests(ContractsFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        today = timezone.localdate()
        # An ACTIVE contract ending INSIDE the horizon -> the Ending tab.
        cls.ending_contract = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-0090",
            buildings=[cls.building_a],
            lines=[("Aflopend werk", "600.00", "12.00")],
            end_date=today + datetime.timedelta(days=ENDING_SOON_DAYS - 5),
        )
        # An ACTIVE contract ending OUTSIDE the horizon -> stays Active.
        cls.far_end_contract = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-0091",
            buildings=[cls.building_a],
            lines=[("Doorlopend werk", "300.00", "6.00")],
            end_date=today + datetime.timedelta(days=ENDING_SOON_DAYS + 30),
        )
        # A DRAFT with no lines -> the Start-here fact.
        cls.empty_draft = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-0092",
            buildings=[cls.building_a],
            lines=[],
            lifecycle=ContractLifecycle.DRAFT,
        )
        # An EXPIRED one -> the Ended tab.
        cls.expired_contract = make_contract(
            company=cls.company_a,
            customer=cls.customer_a,
            contract_type=cls.type_a,
            contract_no="CNT-2026-0093",
            buildings=[cls.building_a],
            lines=[("Oud werk", "100.00", "2.00")],
            end_date=today - datetime.timedelta(days=10),
        )

    def _ids(self, response):
        return {row["id"] for row in response.data["results"]}

    def test_status_ending_returns_only_the_horizon(self):
        response = self.api(self.ca_a).get(CONTRACTS_URL, {"status": "ENDING"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), {self.ending_contract.id})

    def test_active_with_ending_exclude_partitions(self):
        """The Active tab (ACTIVE + ending=exclude) and the Ending tab
        together are exactly the plain ACTIVE read — no row in both,
        none dropped."""
        client = self.api(self.ca_a)
        active_tab = client.get(
            CONTRACTS_URL, {"status": "ACTIVE", "ending": "exclude"}
        )
        ending_tab = client.get(CONTRACTS_URL, {"status": "ENDING"})
        plain_active = client.get(CONTRACTS_URL, {"status": "ACTIVE"})
        self.assertEqual(active_tab.status_code, 200)
        tab_ids = self._ids(active_tab)
        ending_ids = self._ids(ending_tab)
        self.assertEqual(tab_ids & ending_ids, set())
        self.assertEqual(tab_ids | ending_ids, self._ids(plain_active))
        self.assertNotIn(self.ending_contract.id, tab_ids)
        self.assertIn(self.far_end_contract.id, tab_ids)

    def test_stats_guidance_facts(self):
        response = self.api(self.ca_a).get(STATS_URL)
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["ending_soon"], 1)
        self.assertEqual(data["draft"], 1)
        self.assertEqual(data["draft_without_lines"], 1)
        self.assertEqual(data["expired"], 1)
        self.assertEqual(data["ending_soon_days"], ENDING_SOON_DAYS)
        # The buckets partition the money: the ending contract's
        # monthly amount sits in ending_soon, not in active.
        # `.data` carries the raw Decimal (the JSON renderer is what
        # turns it into the string the frontend types declare).
        self.assertEqual(
            Decimal(data["monthly_by_status"]["ending_soon"]), Decimal("600.00")
        )
        self.assertEqual(
            Decimal(data["monthly_by_status"]["active"])
            + Decimal(data["monthly_by_status"]["ending_soon"])
            + Decimal(data["monthly_by_status"]["draft"])
            + Decimal(data["monthly_by_status"]["expired"])
            + Decimal(data["monthly_by_status"]["cancelled"]),
            Decimal(data["monthly_total"]),
        )
        # Start here: the empty draft wins the slot; the ending soonest
        # is named beside it for the fallback.
        self.assertEqual(
            data["start_here"]["draft_no_lines"]["id"], self.empty_draft.id
        )
        self.assertEqual(
            data["start_here"]["ending_soonest"]["id"], self.ending_contract.id
        )

    def test_line_recurring_field_is_served(self):
        """P-12 C3 — the nested line serializer says which recurring
        work runs the line (empty list when none does)."""
        response = self.api(self.ca_a).get(
            f"/api/contracts/{self.contract_a.id}/"
        )
        self.assertEqual(response.status_code, 200)
        lines = response.data["projects"]
        self.assertTrue(lines)
        self.assertIn("recurring", lines[0])
        self.assertEqual(lines[0]["recurring"], [])
