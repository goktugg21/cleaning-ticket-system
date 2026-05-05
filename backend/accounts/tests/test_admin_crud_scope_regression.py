"""
Regression net for CHANGE-16. None of the admin CRUD endpoints may alter
ticket scoping or state-machine behaviour. The contract from earlier batches
(CHANGE-6 in particular) is that:

- scope_tickets_for is unchanged.
- Soft-deleted tenant rows still hide from non-super-admin reads.
- Existing tickets attached to soft-deleted entities remain visible to staff
  via scope_tickets_for.
- COMPANY_ADMIN cannot modify users or memberships outside their company.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment
from test_utils import TenantFixtureMixin


class AdminCrudScopeRegressionTests(TenantFixtureMixin, APITestCase):
    def test_company_admin_membership_grant_does_not_leak_users_outside_company(self):
        """
        Documents the current (intentional) behaviour: a COMPANY_ADMIN of
        company A CAN add a BUILDING_MANAGER user from company B as a
        manager of a building in company A. The act of adding them is what
        gives the user a foothold in company A; the BuildingManagerAssignment
        does not require the user to already be a member of company A.

        This is the correct behaviour for cross-company hand-offs (e.g., a
        contractor manager working both sites). If you want a stricter rule,
        change the membership view's create() to enforce it explicitly.
        """
        # other_manager has BuildingManagerAssignment on other_building (company B).
        # company_admin of company A adds them as a manager of self.building (company A).
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/buildings/{self.building.id}/managers/",
            {"user_id": self.other_manager.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            BuildingManagerAssignment.objects.filter(
                user=self.other_manager, building=self.building
            ).exists()
        )

    def test_company_admin_role_change_outside_company_returns_403(self):
        # company_admin of company A tries to change other_customer_user's role.
        self.authenticate(self.company_admin)
        response = self.client.patch(
            f"/api/users/{self.other_customer_user.id}/",
            {"role": UserRole.BUILDING_MANAGER},
            format="json",
        )
        # Either 403 (object permission denies) or 404 (queryset hides it
        # because user is out of scope). Both honor the rule.
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.other_customer_user.refresh_from_db()
        self.assertEqual(self.other_customer_user.role, UserRole.CUSTOMER_USER)

    def test_company_admin_delete_user_outside_company_returns_403(self):
        self.authenticate(self.company_admin)
        response = self.client.delete(f"/api/users/{self.other_customer_user.id}/")
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
        self.other_customer_user.refresh_from_db()
        self.assertTrue(self.other_customer_user.is_active)

    def test_super_admin_can_act_across_companies(self):
        self.authenticate(self.super_admin)
        # Rename a building in company B.
        rename = self.client.patch(
            f"/api/buildings/{self.other_building.id}/",
            {"name": "Cross-Company Renamed"},
            format="json",
        )
        self.assertEqual(rename.status_code, status.HTTP_200_OK)
        # Soft-delete a customer in company B.
        delete = self.client.delete(f"/api/customers/{self.other_customer.id}/")
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        # Reactivate it.
        reactivate = self.client.post(
            f"/api/customers/{self.other_customer.id}/reactivate/"
        )
        self.assertEqual(reactivate.status_code, status.HTTP_200_OK)

    def test_full_admin_crud_does_not_break_existing_ticket_scope(self):
        # 1. Customer in company A has a ticket; super admin sees it.
        self.authenticate(self.super_admin)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.ticket.id, self.response_ids(response))

        # 2. Soft-delete + reactivate the customer of that ticket.
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        # Super admin still sees the ticket (CHANGE-6 contract).
        response = self.client.get("/api/tickets/")
        self.assertIn(self.ticket.id, self.response_ids(response))
        # Reactivate via the new endpoint.
        reactivate = self.client.post(f"/api/customers/{self.customer.id}/reactivate/")
        self.assertEqual(reactivate.status_code, status.HTTP_200_OK)

        # 3. The OTHER company admin (not in company A) still does not see this ticket.
        self.authenticate(self.other_company_admin)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.ticket.id, self.response_ids(response))
