"""
Sprint 27E — CustomerCompanyPolicy read/write API (closes the
backend half of G-F5 so the new CustomerFormPage policy panel
has somewhere to read and PATCH).

Endpoint under test:
  GET   /api/customers/<customer_id>/policy/
  PATCH /api/customers/<customer_id>/policy/

Backend contract (pinned here):

  1. Permission gate: `IsSuperAdminOrCompanyAdminForCompany`.
     - SUPER_ADMIN may read / update any customer's policy.
     - COMPANY_ADMIN may read / update only customers inside
       their own provider company; cross-provider attempts hit
       a 403 from the object-level check.
     - BUILDING_MANAGER / STAFF / CUSTOMER_USER cannot reach
       the endpoint at all (class-level 403).

  2. Response shape: every CustomerCompanyPolicy boolean field
     plus `customer_id`. The auto-create signal (Sprint 27C)
     guarantees the row exists for every Customer.

  3. PATCH validates boolean-only values (rejects ints/strings/
     None/lists) to match the Sprint 27C `permission_overrides`
     contract and to avoid Python's `bool is int` coercion
     letting `0/1` through.

  4. PATCH writes are audit-logged. The Sprint 27C signal trio
     already covers `CustomerCompanyPolicy` UPDATE; this test
     locks that the new endpoint surfaces those audit rows.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from customers.models import CustomerCompanyPolicy
from test_utils import TenantFixtureMixin


def _policy_url(customer_id: int) -> str:
    return f"/api/customers/{customer_id}/policy/"


class CustomerCompanyPolicyReadTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_can_read_customer_company_policy(self):
        self.authenticate(self.super_admin)
        response = self.client.get(_policy_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # Every documented field is present.
        for field in (
            "customer_id",
            "show_assigned_staff_name",
            "show_assigned_staff_email",
            "show_assigned_staff_phone",
            "customer_users_can_create_tickets",
            "customer_users_can_approve_ticket_completion",
            "customer_users_can_create_extra_work",
            "customer_users_can_approve_extra_work_pricing",
        ):
            self.assertIn(field, response.data)
        self.assertEqual(response.data["customer_id"], self.customer.id)
        # Defaults all True.
        for boolean_field in (
            "show_assigned_staff_name",
            "show_assigned_staff_email",
            "show_assigned_staff_phone",
            "customer_users_can_create_tickets",
            "customer_users_can_approve_ticket_completion",
            "customer_users_can_create_extra_work",
            "customer_users_can_approve_extra_work_pricing",
        ):
            self.assertTrue(response.data[boolean_field], boolean_field)

    def test_company_admin_can_read_own_customer_company_policy(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_policy_url(self.customer.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_company_admin_cannot_read_cross_provider_customer_company_policy(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_policy_url(self.other_customer.id))
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )

    def test_customer_user_cannot_read_customer_company_policy(self):
        self.authenticate(self.customer_user)
        response = self.client.get(_policy_url(self.customer.id))
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )

    def test_anonymous_cannot_read_customer_company_policy(self):
        response = self.client.get(_policy_url(self.customer.id))
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )


class CustomerCompanyPolicyWriteTests(TenantFixtureMixin, APITestCase):
    def _policy(self):
        return CustomerCompanyPolicy.objects.get(customer=self.customer)

    def test_super_admin_can_update_customer_company_policy(self):
        self.authenticate(self.super_admin)
        response = self.client.patch(
            _policy_url(self.customer.id),
            {
                "customer_users_can_create_extra_work": False,
                "customer_users_can_approve_extra_work_pricing": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        policy = self._policy()
        self.assertFalse(policy.customer_users_can_create_extra_work)
        self.assertFalse(policy.customer_users_can_approve_extra_work_pricing)
        # Untouched fields stay True.
        self.assertTrue(policy.customer_users_can_create_tickets)
        self.assertTrue(policy.show_assigned_staff_name)

    def test_company_admin_can_update_own_customer_company_policy(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _policy_url(self.customer.id),
            {"customer_users_can_create_tickets": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(self._policy().customer_users_can_create_tickets)

    def test_company_admin_cannot_update_cross_provider_customer_company_policy(self):
        # other_customer belongs to other_company → company_admin should be denied.
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _policy_url(self.other_customer.id),
            {"customer_users_can_create_tickets": False},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        other_policy = CustomerCompanyPolicy.objects.get(
            customer=self.other_customer
        )
        self.assertTrue(other_policy.customer_users_can_create_tickets)

    def test_customer_user_cannot_update_customer_company_policy(self):
        self.authenticate(self.customer_user)
        response = self.client.patch(
            _policy_url(self.customer.id),
            {"customer_users_can_create_tickets": False},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )
        self.assertTrue(self._policy().customer_users_can_create_tickets)

    def test_non_boolean_value_is_rejected(self):
        self.authenticate(self.super_admin)
        for bad in (1, 0, "true", "false", None, [], {"x": 1}):
            response = self.client.patch(
                _policy_url(self.customer.id),
                {"customer_users_can_create_tickets": bad},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"value={bad!r}: expected 400, got {response.status_code}",
            )
        # Nothing wrote through.
        self.assertTrue(self._policy().customer_users_can_create_tickets)

    def test_unknown_field_in_payload_is_ignored(self):
        """Defense in depth: PATCH with a field outside the policy
        whitelist must not silently mutate state. DRF
        ModelSerializer ignores unknown keys by default; this lock
        prevents an accidental future Meta.fields broadening from
        leaking a non-policy field through this endpoint."""
        self.authenticate(self.super_admin)
        response = self.client.patch(
            _policy_url(self.customer.id),
            {
                "customer_users_can_create_tickets": False,
                "totally_made_up_field": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertNotIn("totally_made_up_field", response.data)
        # The legitimate field still wrote through.
        self.assertFalse(self._policy().customer_users_can_create_tickets)

    def test_customer_id_is_read_only_in_response(self):
        """The PATCH body's customer_id (if a caller sends one) must
        not rebind the policy to a different customer. Defends
        against scope-bleed via the endpoint."""
        self.authenticate(self.super_admin)
        response = self.client.patch(
            _policy_url(self.customer.id),
            {
                "customer_id": self.other_customer.id,
                "customer_users_can_create_tickets": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # The policy still belongs to self.customer.
        policy = self._policy()
        self.assertEqual(policy.customer_id, self.customer.id)
        # And the other customer's policy is untouched.
        other_policy = CustomerCompanyPolicy.objects.get(
            customer=self.other_customer
        )
        self.assertTrue(other_policy.customer_users_can_create_tickets)


class CustomerCompanyPolicyAuditTests(TenantFixtureMixin, APITestCase):
    def test_customer_company_policy_update_is_audit_logged(self):
        policy = CustomerCompanyPolicy.objects.get(customer=self.customer)
        before = AuditLog.objects.filter(
            target_model="customers.CustomerCompanyPolicy",
            target_id=policy.id,
            action=AuditAction.UPDATE,
        ).count()

        self.authenticate(self.company_admin)
        response = self.client.patch(
            _policy_url(self.customer.id),
            {"customer_users_can_create_extra_work": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        rows = AuditLog.objects.filter(
            target_model="customers.CustomerCompanyPolicy",
            target_id=policy.id,
            action=AuditAction.UPDATE,
        )
        self.assertEqual(
            rows.count() - before,
            1,
            "Policy UPDATE via the API must write exactly one AuditLog row.",
        )
        row = rows.latest("created_at")
        self.assertIn("customer_users_can_create_extra_work", row.changes)
        self.assertEqual(
            row.changes["customer_users_can_create_extra_work"],
            {"before": True, "after": False},
        )
        # Actor captured from the JWT-authenticated request.
        self.assertEqual(row.actor_id, self.company_admin.id)
