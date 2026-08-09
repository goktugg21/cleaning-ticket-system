"""
Sprint 157 §2 — assigning workers and managers to Extra Work.

A NEW write surface, so the properties are asserted rather than assumed:

  1. **All-or-nothing.** One unresolvable id rejects the whole batch with
     zero writes. A partial bulk assign is worse than none, because the
     operator then has to work out which half landed.
  2. **H-1, the Sprint 142.1 oracle class.** A foreign id and a fictional
     id produce EQUAL response bodies — compared for equality, not merely
     checked for both being errors, because two 400s with different
     wording still answer "does this id exist".
  3. **CUSTOMER_* can never be assigned and can never call this**, in
     either role.
  4. **Audit fires (H-10).** `objects.create()` / instance `.delete()`,
     never a queryset `.update()` — asserted by counting AuditLog rows.
  5. **The company boundary.** A person who is not reachable inside the
     request's provider company is rejected with the same body as any
     other invalid id.
"""
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditLog
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from companies.models import CompanyUserMembership
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from test_utils import TenantFixtureMixin


BULK_URL = "/api/extra-work/bulk-assign/"


def assignments_url(request_id):
    return f"/api/extra-work/{request_id}/assignments/"


class ExtraWorkAssignmentTestBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.staff = self.make_user("ew-staff@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        self.staff_b = self.make_user("ew-staff-b@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.staff_b, building=self.other_building
        )
        CompanyUserMembership.objects.get_or_create(
            user=self.company_admin, company=self.company
        )
        BuildingManagerAssignment.objects.get_or_create(
            user=self.manager, building=self.building
        )
        self.request_a = self._make_request(self.company, self.building)
        self.request_b = self._make_request(self.company, self.building)
        self.foreign_request = self._make_request(
            self.other_company, self.other_building, customer=self.other_customer
        )

    def _make_request(self, company, building, customer=None):
        return ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer or self.customer,
            created_by=self.super_admin,
            title="Deep clean the atrium",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )

    def _body(self, requests, users, role="WORKER", mode="assign"):
        return {
            "requests": [r.id for r in requests],
            "users": [u.id for u in users],
            "role": role,
            "mode": mode,
        }


class BulkAssignHappyPathTests(ExtraWorkAssignmentTestBase):
    def test_assigns_many_people_to_many_requests(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._body([self.request_a, self.request_b], [self.staff, self.manager]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["created"], 4)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 4)

    def test_reassigning_the_same_pair_is_a_no_op_not_an_error(self):
        self.authenticate(self.company_admin)
        body = self._body([self.request_a], [self.staff])
        self.client.post(BULK_URL, body, format="json")
        again = self.client.post(BULK_URL, body, format="json")
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertEqual(again.data["created"], 0)
        self.assertEqual(again.data["already_assigned"], 1)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 1)

    def test_one_person_can_be_both_worker_and_manager(self):
        """`role` is part of the unique key, deliberately."""
        self.authenticate(self.company_admin)
        self.client.post(
            BULK_URL, self._body([self.request_a], [self.manager], "WORKER"),
            format="json",
        )
        response = self.client.post(
            BULK_URL, self._body([self.request_a], [self.manager], "MANAGER"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            ExtraWorkAssignment.objects.filter(user=self.manager).count(), 2
        )

    def test_unassign_removes_only_that_role(self):
        self.authenticate(self.company_admin)
        for role in ("WORKER", "MANAGER"):
            self.client.post(
                BULK_URL, self._body([self.request_a], [self.manager], role),
                format="json",
            )
        response = self.client.post(
            BULK_URL,
            self._body([self.request_a], [self.manager], "WORKER", "unassign"),
            format="json",
        )
        self.assertEqual(response.data["removed"], 1)
        remaining = ExtraWorkAssignment.objects.filter(user=self.manager)
        self.assertEqual([a.role for a in remaining], ["MANAGER"])

    def test_unassigning_a_pair_that_is_not_assigned_is_counted(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._body([self.request_a], [self.staff], "WORKER", "unassign"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["not_assigned"], 1)

    def test_the_read_lists_who_is_assigned(self):
        self.authenticate(self.company_admin)
        self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff]), format="json"
        )
        response = self.client.get(assignments_url(self.request_a.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_email"], self.staff.email)
        self.assertEqual(rows[0]["role"], "WORKER")


class BulkAssignAtomicityTests(ExtraWorkAssignmentTestBase):
    def test_one_bad_request_id_rolls_back_everything(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            {
                "requests": [self.request_a.id, 999_999],
                "users": [self.staff.id],
                "role": "WORKER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            ExtraWorkAssignment.objects.count(),
            0,
            "the good request's assignment survived a bad id in the batch",
        )

    def test_one_bad_user_id_rolls_back_everything(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            {
                "requests": [self.request_a.id],
                "users": [self.staff.id, 999_999],
                "role": "WORKER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)


class BulkAssignOracleTests(ExtraWorkAssignmentTestBase):
    """H-1. The bodies must be EQUAL, not merely both errors."""

    def test_foreign_request_reads_like_a_fictional_one(self):
        self.authenticate(self.company_admin)
        foreign = self.client.post(
            BULK_URL,
            self._body([self.foreign_request], [self.staff]),
            format="json",
        )
        fictional = self.client.post(
            BULK_URL,
            {
                "requests": [999_999],
                "users": [self.staff.id],
                "role": "WORKER",
                "mode": "assign",
            },
            format="json",
        )
        self.assertEqual(foreign.status_code, fictional.status_code)
        self.assertEqual(
            str(foreign.data),
            str(fictional.data),
            "a foreign request id reads differently from a fictional one",
        )

    def test_foreign_user_reads_like_a_fictional_one(self):
        self.authenticate(self.company_admin)
        foreign = self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff_b]), format="json"
        )
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
        self.assertEqual(foreign.status_code, fictional.status_code)
        self.assertEqual(str(foreign.data), str(fictional.data))

    def test_a_cross_company_pair_reads_the_same_too(self):
        """Both ids are real and both are resolvable to THIS actor as a
        SUPER_ADMIN — only the PAIR is illegal. It must still be the same
        answer, or the endpoint becomes a way to map which company a
        person belongs to."""
        self.authenticate(self.super_admin)
        cross = self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff_b]), format="json"
        )
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
        self.assertEqual(cross.status_code, fictional.status_code)
        self.assertEqual(str(cross.data), str(fictional.data))
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)


class BulkAssignPermissionTests(ExtraWorkAssignmentTestBase):
    def test_customer_user_cannot_call_the_endpoint(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_a_customer_user_can_never_be_assigned(self):
        """Not even by a SUPER_ADMIN, and not in either role.

        The role filter in `assignable_users_for` admits provider-side
        roles only, so a customer user is unresolvable as a target and
        the batch is rejected exactly like a fictional id.
        """
        self.authenticate(self.super_admin)
        for role in ("WORKER", "MANAGER"):
            response = self.client.post(
                BULK_URL,
                self._body([self.request_a], [self.customer_user], role),
                format="json",
            )
            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST, role
            )
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_staff_cannot_call_the_endpoint(self):
        """Assignment is a provider-MANAGEMENT operation. A staff member
        being assignable does not make them an assigner."""
        self.authenticate(self.staff)
        response = self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_is_not_assignable(self):
        """A SUPER_ADMIN is not a provider employee — the same rule the
        timesheets module applies when it refuses them hours of their
        own."""
        self.authenticate(self.super_admin)
        response = self.client.post(
            BULK_URL, self._body([self.request_a], [self.super_admin]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_foreign_requests_assignments_are_not_readable(self):
        self.authenticate(self.company_admin)
        response = self.client.get(assignments_url(self.foreign_request.id))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BulkAssignAuditTests(ExtraWorkAssignmentTestBase):
    """H-10 — every assignment and removal leaves a trace."""

    def _logs(self):
        ct = ContentType.objects.get_for_model(ExtraWorkAssignment)
        return AuditLog.objects.filter(target_model=ct.model_class().__name__)

    def test_assigning_writes_an_audit_row(self):
        self.authenticate(self.company_admin)
        before = AuditLog.objects.count()
        self.client.post(
            BULK_URL,
            self._body([self.request_a, self.request_b], [self.staff]),
            format="json",
        )
        self.assertGreaterEqual(
            AuditLog.objects.count() - before,
            2,
            "a bulk assign of two pairs wrote fewer than two audit rows — "
            "a queryset .update()/bulk_create would fire no signals at all",
        )

    def test_unassigning_writes_an_audit_row(self):
        self.authenticate(self.company_admin)
        self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff]), format="json"
        )
        before = AuditLog.objects.count()
        self.client.post(
            BULK_URL,
            self._body([self.request_a], [self.staff], "WORKER", "unassign"),
            format="json",
        )
        self.assertGreater(AuditLog.objects.count(), before)


class AssignmentModelTests(ExtraWorkAssignmentTestBase):
    def test_the_same_person_and_role_cannot_be_stored_twice(self):
        from django.db import IntegrityError, transaction

        ExtraWorkAssignment.objects.create(
            extra_work_request=self.request_a, user=self.staff, role="WORKER"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExtraWorkAssignment.objects.create(
                    extra_work_request=self.request_a,
                    user=self.staff,
                    role="WORKER",
                )

    def test_deleting_the_request_removes_its_assignments(self):
        ExtraWorkAssignment.objects.create(
            extra_work_request=self.request_a, user=self.staff, role="WORKER"
        )
        self.request_a.delete()
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_the_assigned_user_is_protected(self):
        """PROTECT, deliberately: an assignment records who was put on a
        job, and deleting the account should not silently erase it."""
        from django.db.models import ProtectedError

        ExtraWorkAssignment.objects.create(
            extra_work_request=self.request_a, user=self.staff, role="WORKER"
        )
        with self.assertRaises(ProtectedError):
            self.staff.delete()
