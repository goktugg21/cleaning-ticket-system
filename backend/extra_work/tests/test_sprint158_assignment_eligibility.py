"""
Sprint 158 §1 — WHO may be assigned, and as WHAT.

Sprint 157 used one set `{STAFF, BUILDING_MANAGER, COMPANY_ADMIN}` for
both roles, so a field worker could be made the MANAGER of a request.
Eligibility now comes from the request's BUILDING and differs per role:

  WORKER  — holds `BuildingStaffVisibility` on that building.
  MANAGER — holds `BuildingManagerAssignment` on that building, OR is a
            COMPANY_ADMIN of that building's company.

The four things these tests exist to guarantee:

  1. The role split is real — a worker cannot be made a manager and vice
     versa.
  2. **An ineligible-but-real id is indistinguishable from a fictional
     one.** Compared for EQUALITY, because two 400s with different
     wording would still answer "does this person exist / work here".
  3. **The picker and the validator agree BY CONSTRUCTION.** A test walks
     the candidate endpoint's ENTIRE output through the assign endpoint
     and asserts every one is accepted. That is the Sprint 152.1 §1a
     lesson: two separately-computed lists drift, and the operator gets
     options that always fail.
  4. The tenant check that Sprint 157 shipped still works and was NOT
     weakened — a person with no relationship to the building is
     rejected however senior the caller.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import CompanyUserMembership
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from test_utils import TenantFixtureMixin


BULK_URL = "/api/extra-work/bulk-assign/"


def candidates_url(request_id, role):
    return f"/api/extra-work/{request_id}/assignments/candidates/?role={role}"


class EligibilityTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # A worker and a manager ON the request's building.
        self.worker = self.make_user("elig-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker, building=self.building
        )
        self.site_manager = self.make_user(
            "elig-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.site_manager, building=self.building
        )

        # Same COMPANY, different BUILDING — the case the old
        # company-wide rule wrongly admitted.
        self.other_site = Building.objects.create(
            company=self.company, name="Other site", address="Elsewhere 1"
        )
        self.elsewhere_worker = self.make_user(
            "elig-elsewhere@example.com", UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.elsewhere_worker, building=self.other_site
        )

        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )

        self.request_a = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Deep clean",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )

    def _assign(self, users, role, mode="assign", requests=None):
        return self.client.post(
            BULK_URL,
            {
                "requests": [r.id for r in (requests or [self.request_a])],
                "users": [u.id for u in users],
                "role": role,
                "mode": mode,
            },
            format="json",
        )


class RoleSplitTests(EligibilityTestBase):
    def test_a_worker_can_be_assigned_as_a_worker(self):
        self.authenticate(self.company_admin)
        response = self._assign([self.worker], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["created"], 1)

    def test_a_worker_cannot_be_assigned_as_a_manager(self):
        """THE Sprint 158 defect. A field worker is not a manager."""
        self.authenticate(self.company_admin)
        response = self._assign([self.worker], "MANAGER")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_a_building_manager_can_be_assigned_as_a_manager(self):
        self.authenticate(self.company_admin)
        response = self._assign([self.site_manager], "MANAGER")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_a_building_manager_is_not_a_worker_candidate(self):
        """Being answerable for the job is not the same claim as doing
        it, and nothing about the manager role implies the first."""
        self.authenticate(self.company_admin)
        response = self._assign([self.site_manager], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_company_admin_is_a_manager_candidate(self):
        """The decision this sprint made explicitly.

        A COMPANY_ADMIN is authoritative over every building of their
        company by construction, so excluding them would mean a
        provider's own administrator could not be named responsible for a
        job in their own company while a building manager one level down
        could.
        """
        self.authenticate(self.super_admin)
        response = self._assign([self.company_admin], "MANAGER")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_a_company_admin_is_not_a_worker_candidate(self):
        self.authenticate(self.super_admin)
        response = self._assign([self.company_admin], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class BuildingNotCompanyTests(EligibilityTestBase):
    """Eligibility comes from the BUILDING, which is the whole change."""

    def test_a_worker_at_another_building_of_the_same_company_is_refused(self):
        self.authenticate(self.company_admin)
        response = self._assign([self.elsewhere_worker], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_the_same_person_becomes_eligible_once_given_the_building(self):
        """Proves the rule is about the link, not about the person."""
        self.authenticate(self.company_admin)
        self.assertEqual(
            self._assign([self.elsewhere_worker], "WORKER").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        BuildingStaffVisibility.objects.create(
            user=self.elsewhere_worker, building=self.building
        )
        self.assertEqual(
            self._assign([self.elsewhere_worker], "WORKER").status_code,
            status.HTTP_200_OK,
        )

    def test_assigning_across_two_buildings_needs_eligibility_at_both(self):
        second_request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.other_site,
            customer=self.customer,
            created_by=self.super_admin,
            title="Other site clean",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )
        self.authenticate(self.company_admin)
        # `worker` is eligible at `building` but not at `other_site`.
        response = self._assign(
            [self.worker], "WORKER", requests=[self.request_a, second_request]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            ExtraWorkAssignment.objects.count(),
            0,
            "the eligible half of the batch was written",
        )


class EligibilityOracleTests(EligibilityTestBase):
    """H-1 — ineligible must read exactly like non-existent."""

    def test_ineligible_person_is_indistinguishable_from_a_fictional_id(self):
        self.authenticate(self.company_admin)
        ineligible = self._assign([self.elsewhere_worker], "WORKER")
        fictional = self.client.post(
            BULK_URL,
            {
                "requests": [self.request_a.id],
                "users": [999_999],
                "role": "WORKER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(ineligible.status_code, fictional.status_code)
        self.assertEqual(
            str(ineligible.data),
            str(fictional.data),
            "an ineligible person reads differently from a fictional id, "
            "which lets a caller enumerate who works where",
        )

    def test_wrong_role_is_indistinguishable_from_a_fictional_id(self):
        """A worker asked for as a MANAGER is a real, visible person.

        If that answer differed from a fictional id, the endpoint would
        report which of two roles somebody holds.
        """
        self.authenticate(self.company_admin)
        wrong_role = self._assign([self.worker], "MANAGER")
        fictional = self.client.post(
            BULK_URL,
            {
                "requests": [self.request_a.id],
                "users": [999_999],
                "role": "MANAGER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(str(wrong_role.data), str(fictional.data))


class CandidateEndpointTests(EligibilityTestBase):
    def test_worker_candidates_are_the_buildings_staff(self):
        self.authenticate(self.company_admin)
        response = self.client.get(candidates_url(self.request_a.id, "WORKER"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {row["email"] for row in response.data}
        self.assertIn(self.worker.email, emails)
        self.assertNotIn(self.site_manager.email, emails)
        self.assertNotIn(self.elsewhere_worker.email, emails)

    def test_manager_candidates_are_the_buildings_managers_and_admins(self):
        self.authenticate(self.company_admin)
        response = self.client.get(candidates_url(self.request_a.id, "MANAGER"))
        emails = {row["email"] for row in response.data}
        self.assertIn(self.site_manager.email, emails)
        self.assertIn(self.company_admin.email, emails)
        self.assertNotIn(self.worker.email, emails)

    def test_every_offered_candidate_is_accepted_by_the_assign_endpoint(self):
        """The §1 requirement, walked end to end.

        "Who is offerable" must equal "who is acceptable". This takes the
        picker's ENTIRE output for each role and puts it through the
        write endpoint; a single rejection means the two lists have
        drifted, which is the failure mode Sprint 152.1 §1a documented.
        """
        self.authenticate(self.super_admin)
        for role in ("WORKER", "MANAGER"):
            offered = self.client.get(
                candidates_url(self.request_a.id, role)
            ).data
            self.assertGreater(len(offered), 0, f"no {role} candidates to test")
            response = self.client.post(
                BULK_URL,
                {
                    "requests": [self.request_a.id],
                    "users": [row["id"] for row in offered],
                    "role": role,
                    "mode": "assign",
                },
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                f"the picker offered a {role} the endpoint refused: "
                f"{response.data}",
            )
            self.assertEqual(response.data["created"], len(offered))

    def test_customer_user_cannot_read_the_candidates(self):
        self.authenticate(self.customer_user)
        response = self.client.get(candidates_url(self.request_a.id, "WORKER"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_foreign_requests_candidates_are_a_404(self):
        foreign = ExtraWorkRequest.objects.create(
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
            created_by=self.super_admin,
            title="Foreign",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )
        self.authenticate(self.company_admin)
        response = self.client.get(candidates_url(foreign.id, "WORKER"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TenantCheckStillHoldsTests(EligibilityTestBase):
    """Sprint 158 §1 says explicitly: the tenant check works, do not
    weaken it. This pins that the change did not."""

    def test_a_person_from_another_company_is_still_refused(self):
        other_worker = self.make_user("other-co@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=other_worker, building=self.other_building
        )
        self.authenticate(self.super_admin)
        response = self._assign([other_worker], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_a_person_visible_in_TWO_companies_is_eligible_in_both(self):
        """NOT a bug — the case the owner reported from crmtest.

        A user may legitimately hold `BuildingStaffVisibility` on
        buildings of two provider companies (the demo seed does exactly
        this). They are genuinely reachable in both, so both accept them.
        What misled the operator was the e-mail domain, not the scoping.
        """
        dual = self.make_user("dual@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=dual, building=self.building)
        BuildingStaffVisibility.objects.create(
            user=dual, building=self.other_building
        )
        self.authenticate(self.super_admin)
        response = self._assign([dual], "WORKER")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
