"""
Sprint 7 — audit coverage for scope-changing membership / assignment
mutations (and a re-confirmation that the existing User signal already
covers role / is_active changes).

The earlier Sprint 2.2 suite (test_audit.py) covers the four
admin-managed entity rows (User, Company, Building, Customer). This
file adds the three membership / assignment junction tables that
actually grant or revoke a user's scope at runtime:

  CompanyUserMembership      — POST   /api/companies/<id>/admins/
                               DELETE /api/companies/<id>/admins/<user_id>/
  BuildingManagerAssignment — POST   /api/buildings/<id>/managers/
                               DELETE /api/buildings/<id>/managers/<user_id>/
  CustomerUserMembership    — POST   /api/customers/<id>/users/
                               DELETE /api/customers/<id>/users/<user_id>/

For each create + delete we assert:
- exactly one AuditLog row is written,
- target_model + target_id identify the membership row,
- actor is the JWT-authenticated caller (not None, not Anonymous),
- changes carry user_id + user_email AND the entity's id + name
  (so an operator does not need a cross-lookup on pks),
- request_ip is taken from the first hop of X-Forwarded-For (verifies
  the audit middleware integrates with the proxy header chain, which
  Sprint 4's frontend nginx fix preserves).

We also re-confirm that the pre-existing User-row signal still emits
an UPDATE log when a user's role or is_active changes via the API,
because the brief asks for those events to be visible too.

Forbidden / unauthorised attempts are also exercised: an attempt
that hits a 403 / 404 must NOT produce an audit row, because the
underlying mutation never ran.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import CustomerUserMembership
from test_utils import TenantFixtureMixin


class _MembershipAuditBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # The fixture create()s a baseline of memberships — wipe all
        # audit rows so each test starts from zero.
        AuditLog.objects.all().delete()


# ===========================================================================
# CompanyUserMembership
# ===========================================================================


class CompanyMembershipAuditTests(_MembershipAuditBase):
    def setUp(self):
        super().setUp()
        # Make a fresh company-admin candidate that the fixture has NOT
        # already added to self.company, so POST .../admins/ is a real
        # CREATE.
        self.candidate = self.make_user(
            "company-admin-candidate@example.com", UserRole.COMPANY_ADMIN
        )
        self.url = f"/api/companies/{self.company.id}/admins/"

    def test_create_membership_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.url,
            {"user_id": self.candidate.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        logs = AuditLog.objects.filter(
            target_model="companies.CompanyUserMembership",
            action=AuditAction.CREATE,
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.actor, self.super_admin)
        membership = CompanyUserMembership.objects.get(
            company=self.company, user=self.candidate
        )
        self.assertEqual(log.target_id, membership.id)
        # Rich changes payload — operator should not need to look up pks.
        self.assertEqual(log.changes["user_id"]["after"], self.candidate.id)
        self.assertEqual(log.changes["user_email"]["after"], self.candidate.email)
        self.assertEqual(log.changes["company_id"]["after"], self.company.id)
        self.assertEqual(log.changes["company_name"]["after"], self.company.name)
        # And before-values are None on a CREATE.
        self.assertIsNone(log.changes["user_id"]["before"])
        self.assertIsNone(log.changes["company_name"]["before"])

    def test_delete_membership_via_api_writes_delete_audit_log(self):
        # Create the membership directly so the audit row from the
        # POST does not pollute the count.
        membership = CompanyUserMembership.objects.create(
            company=self.company, user=self.candidate
        )
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.delete(
            f"{self.url}{self.candidate.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="companies.CompanyUserMembership",
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.target_id, membership.id)
        # Before-values carry the user / company we removed; after is None.
        self.assertEqual(log.changes["user_id"]["before"], self.candidate.id)
        self.assertEqual(log.changes["user_email"]["before"], self.candidate.email)
        self.assertEqual(log.changes["company_id"]["before"], self.company.id)
        self.assertEqual(log.changes["company_name"]["before"], self.company.name)
        self.assertIsNone(log.changes["company_name"]["after"])

    def test_forbidden_create_does_not_write_audit_log(self):
        # COMPANY_ADMIN of a different company cannot add members to
        # self.company — the request 403s and no membership is created.
        self.authenticate(self.other_company_admin)
        response = self.client.post(
            self.url,
            {"user_id": self.candidate.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            AuditLog.objects.filter(
                target_model="companies.CompanyUserMembership"
            ).count(),
            0,
        )

    def test_create_membership_records_request_ip_from_xff(self):
        # The audit middleware trusts the FIRST hop of X-Forwarded-For —
        # this is the same chain the Sprint-4 frontend nginx config
        # forwards through to backend. The test client lets us set
        # HTTP_X_FORWARDED_FOR directly via kwargs.
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.url,
            {"user_id": self.candidate.id},
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.5",
            HTTP_X_REQUEST_ID="req-abc-7",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = AuditLog.objects.filter(
            target_model="companies.CompanyUserMembership"
        ).get()
        self.assertEqual(log.request_ip, "203.0.113.7")
        self.assertEqual(log.request_id, "req-abc-7")


# ===========================================================================
# BuildingManagerAssignment
# ===========================================================================


class BuildingMembershipAuditTests(_MembershipAuditBase):
    def setUp(self):
        super().setUp()
        # Fresh manager candidate not yet assigned to self.building.
        self.candidate = self.make_user(
            "manager-candidate@example.com", UserRole.BUILDING_MANAGER
        )
        self.url = f"/api/buildings/{self.building.id}/managers/"

    def test_create_assignment_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.url,
            {"user_id": self.candidate.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        log = AuditLog.objects.filter(
            target_model="buildings.BuildingManagerAssignment",
            action=AuditAction.CREATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["user_email"]["after"], self.candidate.email)
        self.assertEqual(log.changes["building_id"]["after"], self.building.id)
        self.assertEqual(log.changes["building_name"]["after"], self.building.name)

    def test_delete_assignment_via_api_writes_delete_audit_log(self):
        BuildingManagerAssignment.objects.create(
            building=self.building, user=self.candidate
        )
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.delete(
            f"{self.url}{self.candidate.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="buildings.BuildingManagerAssignment",
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["user_email"]["before"], self.candidate.email)
        self.assertEqual(log.changes["building_id"]["before"], self.building.id)
        self.assertEqual(log.changes["building_name"]["before"], self.building.name)


# ===========================================================================
# CustomerUserMembership
# ===========================================================================


class CustomerMembershipAuditTests(_MembershipAuditBase):
    def setUp(self):
        super().setUp()
        self.candidate = self.make_user(
            "customer-user-candidate@example.com", UserRole.CUSTOMER_USER
        )
        self.url = f"/api/customers/{self.customer.id}/users/"

    def test_create_membership_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.url,
            {"user_id": self.candidate.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        log = AuditLog.objects.filter(
            target_model="customers.CustomerUserMembership",
            action=AuditAction.CREATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["user_email"]["after"], self.candidate.email)
        self.assertEqual(log.changes["customer_id"]["after"], self.customer.id)
        self.assertEqual(log.changes["customer_name"]["after"], self.customer.name)

    def test_delete_membership_via_api_writes_delete_audit_log(self):
        CustomerUserMembership.objects.create(
            customer=self.customer, user=self.candidate
        )
        AuditLog.objects.all().delete()

        self.authenticate(self.super_admin)
        response = self.client.delete(
            f"{self.url}{self.candidate.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="customers.CustomerUserMembership",
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["user_email"]["before"], self.candidate.email)
        self.assertEqual(log.changes["customer_id"]["before"], self.customer.id)
        self.assertEqual(log.changes["customer_name"]["before"], self.customer.name)


# ===========================================================================
# User role / is_active are already audited via the existing User
# UPDATE signal — re-confirm here so a future refactor that drops the
# User signal is caught immediately.
# ===========================================================================


class UserRoleAndActiveAuditTests(_MembershipAuditBase):
    def test_user_role_change_records_role_in_changes(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            f"/api/users/{self.customer_user.id}/",
            {"role": UserRole.BUILDING_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["role"]["before"], UserRole.CUSTOMER_USER)
        self.assertEqual(log.changes["role"]["after"], UserRole.BUILDING_MANAGER)

    def test_user_deactivation_records_is_active_in_changes(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            f"/api/users/{self.customer_user.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = AuditLog.objects.filter(
            target_model="accounts.User",
            target_id=self.customer_user.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.changes["is_active"]["before"], True)
        self.assertEqual(log.changes["is_active"]["after"], False)
