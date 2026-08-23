"""W23 — the RecurringJob → ContractLine link, and its tenant law.

The FK is nullable and optional; the serializer is the sole write path
and enforces (P0 class, RBAC H-1/H-2 family):

  * the line's contract must belong to the JOB's customer
    (`contract_line_customer_mismatch`);
  * a line pinned to a building must match the job's building
    (`contract_line_building_mismatch`).

Both rejections and the happy path are exercised through the real
endpoint, as SUPER_ADMIN, so what is tested is the wire behaviour and
not a serializer called by hand.
"""
from __future__ import annotations

from datetime import date

from rest_framework.test import APIClient

from buildings.models import Building
from contracts.models import (
    Contract,
    ContractLine,
    ContractRevision,
)
from planned_work.models import RecurringJob

from ._base import PlannedWorkFixtureMixin
from django.test import TestCase

JOBS_URL = "/api/planned-work/recurring-jobs/"


class ContractLineLinkTests(PlannedWorkFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.super_admin)

        # A contract for THIS customer, one revision, two lines: one
        # unpinned, one pinned to a second building of the same company.
        self.second_building = Building.objects.create(
            company=self.company, name="Building A2", address="A street 2"
        )
        self.contract = Contract.objects.create(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-2026-9001",
            start_date=date(2026, 1, 1),
        )
        revision = ContractRevision.objects.create(
            contract=self.contract,
            label="Initial",
            effective_from=date(2026, 1, 1),
        )
        self.line_unpinned = ContractLine.objects.create(
            revision=revision, name="Dagelijkse schoonmaak"
        )
        self.line_other_building = ContractLine.objects.create(
            revision=revision,
            name="Glasbewassing A2",
            building=self.second_building,
        )

        # A contract for the OTHER tenant's customer.
        other_contract = Contract.objects.create(
            company=self.other_company,
            customer=self.other_customer,
            contract_no="CNT-2026-9002",
            start_date=date(2026, 1, 1),
        )
        other_revision = ContractRevision.objects.create(
            contract=other_contract,
            label="Initial",
            effective_from=date(2026, 1, 1),
        )
        self.foreign_line = ContractLine.objects.create(
            revision=other_revision, name="Foreign line"
        )

    def test_happy_path_links_and_reads_back(self):
        payload = self.recurring_job_payload(
            contract_line=self.line_unpinned.id
        )
        response = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        # Create echoes the WRITE serializer (no id / read-only names) —
        # the read shape is the detail GET's, so that is what is read.
        self.assertEqual(
            response.data["contract_line"], self.line_unpinned.id
        )
        job = RecurringJob.objects.get(contract_line=self.line_unpinned)
        detail = self.client.get(f"{JOBS_URL}{job.id}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["contract_line"], self.line_unpinned.id)
        self.assertEqual(
            detail.data["contract_line_name"], "Dagelijkse schoonmaak"
        )

    def test_line_pinned_to_matching_building_is_accepted(self):
        payload = self.recurring_job_payload(
            building=self.second_building.id,
            contract_line=self.line_other_building.id,
        )
        response = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_cross_customer_line_is_rejected(self):
        payload = self.recurring_job_payload(
            contract_line=self.foreign_line.id
        )
        response = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["contract_line"][0].code,
            "contract_line_customer_mismatch",
        )
        self.assertEqual(RecurringJob.objects.count(), 0)

    def test_wrong_building_line_is_rejected(self):
        # The job sits on self.building; the line is pinned to the
        # second building of the SAME company — same tenant, wrong
        # building.
        payload = self.recurring_job_payload(
            contract_line=self.line_other_building.id
        )
        response = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["contract_line"][0].code,
            "contract_line_building_mismatch",
        )

    def test_patch_customer_swap_cannot_strand_a_foreign_line(self):
        # Link the line legitimately, then try to move the job to the
        # other tenant's customer/building while KEEPING the line: the
        # effective-line validation must refuse — this is the hole the
        # attrs-only label pattern leaves open, closed here on purpose.
        create = self.client.post(
            JOBS_URL,
            self.recurring_job_payload(contract_line=self.line_unpinned.id),
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.data)
        # Create echoes the write serializer, which carries no id.
        job_id = RecurringJob.objects.get(
            contract_line=self.line_unpinned
        ).id
        response = self.client.patch(
            f"{JOBS_URL}{job_id}/",
            {
                "building": self.other_building.id,
                "customer": self.other_customer.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["contract_line"][0].code,
            "contract_line_customer_mismatch",
        )


class ContractPlanningEndpointTests(PlannedWorkFixtureMixin, TestCase):
    """W23 §2 — the year×week grid endpoint, driven from the linked
    occurrence machinery. Lives here (not contracts/tests) because the
    subject is the LINK: what the grid shows is planned_work data."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.super_admin)
        self.contract = Contract.objects.create(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-2026-9003",
            start_date=date(2026, 1, 1),
        )
        revision = ContractRevision.objects.create(
            contract=self.contract,
            label="Initial",
            effective_from=date(2026, 1, 1),
        )
        self.line = ContractLine.objects.create(
            revision=revision, name="Weekly clean", frequency_per_year=52
        )
        self.job = self.make_recurring_job()
        self.job.contract_line = self.line
        self.job.save(update_fields=["contract_line"])
        window = self.default_window(self.job)
        from planned_work.models import (
            PlannedOccurrence,
            PlannedOccurrenceStatus,
        )

        for planned, status_value in (
            (date(2026, 6, 1), PlannedOccurrenceStatus.COMPLETED),
            (date(2026, 6, 2), PlannedOccurrenceStatus.PLANNED),
            (date(2026, 6, 8), PlannedOccurrenceStatus.SKIPPED),
        ):
            PlannedOccurrence.objects.create(
                recurring_job=self.job,
                source_window=window,
                company=self.company,
                building=self.building,
                customer=self.customer,
                planned_date=planned,
                status=status_value,
            )

    def planning(self, contract_id, year=2026):
        return self.client.get(
            f"/api/contracts/{contract_id}/planning/?year={year}"
        )

    def test_grid_buckets_by_iso_week_with_dominant_status(self):
        response = self.planning(self.contract.id)
        self.assertEqual(response.status_code, 200, response.data)
        lines = response.data["lines"]
        self.assertEqual(len(lines), 1)
        row = lines[0]
        self.assertEqual(row["name"], "Weekly clean")
        self.assertEqual(row["frequency_per_year"], 52)
        # 3 occurrences, but SKIPPED is not a performance.
        self.assertEqual(row["planned_count"], 2)
        self.assertEqual(row["job_ids"], [self.job.id])
        weeks = {w["week"]: w for w in row["weeks"]}
        # 2026-06-01/02 are ISO week 23; -06-08 is week 24.
        self.assertEqual(weeks[23]["count"], 2)
        # COMPLETED vs PLANNED tie -> dominance order says COMPLETED.
        self.assertEqual(weeks[23]["status"], "COMPLETED")
        self.assertEqual(weeks[23]["job_id"], self.job.id)
        self.assertEqual(weeks[24]["status"], "SKIPPED")

    def test_out_of_scope_contract_is_a_404(self):
        client = APIClient()
        client.force_authenticate(user=self.other_company_admin)
        response = client.get(
            f"/api/contracts/{self.contract.id}/planning/?year=2026"
        )
        self.assertEqual(response.status_code, 404)

    def test_register_contract_answers_400_not_an_empty_grid(self):
        from contracts.models import ContractKind

        register = Contract.objects.create(
            company=self.company,
            customer=self.customer,
            contract_no="CNT-2026-9004",
            start_date=date(2026, 1, 1),
            kind=ContractKind.EXTRA_WORK,
        )
        response = self.planning(register.id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "register_has_no_planning")
