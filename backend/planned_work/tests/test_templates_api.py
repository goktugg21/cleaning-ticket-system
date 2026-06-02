"""Sprint 11B Batch 4 — RecurringJob template API: permissions, tenancy,
and write-validation.

Covers brief scenarios 1-7:
  1. SA create -> 201; company derived from building, created_by=SA.
  2. CA create in own company -> 201; CA create for other company -> 400.
  3. BM create for assigned building -> 201; BM other building -> 400.
  4. STAFF / CUSTOMER_USER are 403 on POST and GET (provider-only).
  5. Cross-provider list/detail isolation (H-1 / H-2).
  6. pricing_mode / fixed_price / end_date validation.
  7. default crew eligibility validation.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status

from accounts.models import UserRole
from planned_work.models import (
    Frequency,
    PricingMode,
    RecurringJob,
    RecurringJobDefaultManager,
    RecurringJobDefaultStaff,
)
from rest_framework.test import APITestCase

from ._base import PlannedWorkFixtureMixin


JOBS_URL = "/api/planned-work/recurring-jobs/"


class RecurringJobCreateScopeTests(PlannedWorkFixtureMixin, APITestCase):
    def test_super_admin_create_derives_company_and_created_by(self):
        self.authenticate(self.super_admin)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        job = RecurringJob.objects.latest("id")
        self.assertEqual(job.company_id, self.building.company_id)
        self.assertEqual(job.created_by_id, self.super_admin.id)

    def test_company_admin_create_in_own_company(self):
        self.authenticate(self.company_admin)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        job = RecurringJob.objects.latest("id")
        self.assertEqual(job.company_id, self.company.id)
        self.assertEqual(job.created_by_id, self.company_admin.id)

    def test_company_admin_create_for_other_company_building_forbidden(self):
        self.authenticate(self.company_admin)
        payload = self.recurring_job_payload(
            building=self.other_building.id, customer=self.other_customer.id
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["building"][0].code, "forbidden_scope")
        self.assertEqual(RecurringJob.objects.count(), 0)

    def test_building_manager_create_for_assigned_building(self):
        self.authenticate(self.manager)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        job = RecurringJob.objects.latest("id")
        self.assertEqual(job.building_id, self.building.id)

    def test_building_manager_create_for_other_building_forbidden(self):
        self.authenticate(self.manager)
        payload = self.recurring_job_payload(
            building=self.other_building.id, customer=self.other_customer.id
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["building"][0].code, "forbidden_scope")
        self.assertEqual(RecurringJob.objects.count(), 0)


class RecurringJobRoleGateTests(PlannedWorkFixtureMixin, APITestCase):
    def test_staff_post_forbidden(self):
        self.authenticate(self.staff)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_list_forbidden(self):
        self.authenticate(self.staff)
        resp = self.client.get(JOBS_URL)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_post_forbidden(self):
        self.authenticate(self.customer_user)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_list_forbidden(self):
        self.authenticate(self.customer_user)
        resp = self.client.get(JOBS_URL)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class RecurringJobTenancyIsolationTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A template owned by company A, created by SA.
        self.job_a = self.make_recurring_job(created_by=self.super_admin)

    def test_other_company_admin_list_excludes_company_a_job(self):
        self.authenticate(self.other_company_admin)
        resp = self.client.get(JOBS_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.job_a.id, self.response_ids(resp))

    def test_other_company_admin_detail_404(self):
        self.authenticate(self.other_company_admin)
        resp = self.client.get(f"{JOBS_URL}{self.job_a.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RecurringJobValidationTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_hourly_pricing_rejected(self):
        payload = self.recurring_job_payload(pricing_mode=PricingMode.HOURLY)
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["pricing_mode"][0].code, "pricing_mode_not_supported")

    def test_fixed_without_price_rejected(self):
        payload = self.recurring_job_payload(pricing_mode=PricingMode.FIXED)
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["fixed_price"][0].code, "fixed_price_required")

    def test_end_before_start_rejected(self):
        payload = self.recurring_job_payload(
            start_date=datetime.date(2026, 6, 10).isoformat(),
            end_date=datetime.date(2026, 6, 1).isoformat(),
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["end_date"][0].code, "end_before_start")


class RecurringJobCrewEligibilityTests(PlannedWorkFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_ineligible_default_staff_rejected(self):
        # A STAFF user with NO BuildingStaffVisibility on the building.
        ineligible_staff = self.make_user(
            "staff-none@example.com", UserRole.STAFF
        )
        payload = self.recurring_job_payload(
            default_staff_ids=[ineligible_staff.id]
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["default_staff_ids"][0].code, "staff_not_eligible")
        self.assertEqual(RecurringJobDefaultStaff.objects.count(), 0)

    def test_non_assigned_default_manager_rejected(self):
        # `self.other_manager` is a BUILDING_MANAGER but assigned to
        # other_building, NOT self.building.
        payload = self.recurring_job_payload(
            default_manager_ids=[self.other_manager.id]
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["default_manager_ids"][0].code, "manager_not_eligible")
        self.assertEqual(RecurringJobDefaultManager.objects.count(), 0)

    def test_eligible_crew_persisted(self):
        payload = self.recurring_job_payload(
            default_staff_ids=[self.staff.id],
            default_manager_ids=[self.manager.id],
        )
        resp = self.client.post(JOBS_URL, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        job = RecurringJob.objects.latest("id")
        self.assertEqual(
            list(job.default_staff.values_list("user_id", flat=True)),
            [self.staff.id],
        )
        self.assertEqual(
            list(job.default_managers.values_list("user_id", flat=True)),
            [self.manager.id],
        )


class RecurringJobCrossCompanyMovePatchTests(
    PlannedWorkFixtureMixin, APITestCase
):
    """Regression (verification finding, H-1/H-2): a PATCH that moves a
    job's building+customer to another provider company must re-anchor the
    denormalized `company`, keeping scope + spawned-ticket tenancy
    consistent. Pre-fix `company` drifted stale at the old company."""

    def setUp(self):
        super().setUp()
        self.job_a = self.make_recurring_job(created_by=self.super_admin)

    def test_patch_to_other_company_reanchors_company(self):
        self.authenticate(self.super_admin)
        resp = self.client.patch(
            f"{JOBS_URL}{self.job_a.id}/",
            {
                "building": self.other_building.id,
                "customer": self.other_customer.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

        self.job_a.refresh_from_db()
        self.assertEqual(self.job_a.building_id, self.other_building.id)
        # company tracks building.company — NOT left stale at company A.
        self.assertEqual(self.job_a.company_id, self.other_company.id)
        self.assertEqual(
            self.job_a.company_id, self.other_building.company_id
        )

    def test_scope_follows_the_move(self):
        self.authenticate(self.super_admin)
        self.client.patch(
            f"{JOBS_URL}{self.job_a.id}/",
            {
                "building": self.other_building.id,
                "customer": self.other_customer.id,
            },
            format="json",
        )
        # Now company B's admin sees it; company A's admin does not.
        self.authenticate(self.other_company_admin)
        self.assertEqual(
            self.client.get(f"{JOBS_URL}{self.job_a.id}/").status_code,
            status.HTTP_200_OK,
        )
        self.authenticate(self.company_admin)
        self.assertEqual(
            self.client.get(f"{JOBS_URL}{self.job_a.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )


class GenerateActionValidationTests(PlannedWorkFixtureMixin, APITestCase):
    """Regression (verification finding): the generate action coerces +
    bounds days_ahead so a non-numeric value is a clean 400 (not a 500)
    and a huge int cannot mass-materialize occurrences/tickets."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)
        # Anchor on the live date: the generate action has no injectable
        # `today`, so a single same-day occurrence is always inside the
        # horizon regardless of when the suite runs.
        today = timezone.localdate()
        self.job = self.make_recurring_job(
            start_date=today,
            end_date=today,
        )

    def test_non_integer_days_ahead_is_400(self):
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/generate/",
            {"days_ahead": "abc"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["code"], "invalid_days_ahead")

    def test_out_of_range_days_ahead_is_400(self):
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/generate/",
            {"days_ahead": 100000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.data)
        self.assertEqual(resp.data["code"], "invalid_days_ahead")

    def test_valid_days_ahead_generates(self):
        resp = self.client.post(
            f"{JOBS_URL}{self.job.id}/generate/",
            {"days_ahead": 7},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["occurrences_created"], 1)
