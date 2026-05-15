"""
Sprint 27A — RBAC / permission / hierarchy safety net (customers app).

This file pins three of the seven Sprint 27A regression tests:

  T-1  test_company_admin_cannot_grant_customer_company_admin_access_role
  T-2  test_super_admin_can_grant_customer_company_admin_access_role
  T-3  test_customer_company_admin_cannot_promote_peer_to_company_admin

Plus the permission-override / workflow-override conceptual split:

  T-6  test_permission_override_is_distinct_from_workflow_override

The other three Sprint 27A tests live in:

  T-4  tickets/tests/test_sprint27a_rbac_safety_net.py
  T-5  extra_work/tests/test_sprint27a_rbac_safety_net.py
  T-7  audit/tests/test_sprint27a_rbac_safety_net.py

T-1 is the only Sprint 27A test that requires a backend code
change (the minimal `validate_access_role` guard added to
`CustomerUserBuildingAccessUpdateSerializer`). T-2, T-3, T-6
should already pass on master @ 95748b3.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from customers.models import (
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from test_utils import TenantFixtureMixin


CUSTOMER_USER = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
CUSTOMER_LOCATION_MANAGER = (
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
)
CUSTOMER_COMPANY_ADMIN = (
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
)


def _access_url(customer_id: int, user_id: int, building_id: int) -> str:
    return (
        f"/api/customers/{customer_id}/users/{user_id}/access/{building_id}/"
    )


class CustomerCompanyAdminGrantGuardTests(TenantFixtureMixin, APITestCase):
    """
    T-1, T-2: only SUPER_ADMIN may set access_role=CUSTOMER_COMPANY_ADMIN.

    The PATCH /access/<bid>/ endpoint is class-gated by
    `IsSuperAdminOrCompanyAdminForCompany`, so a provider
    COMPANY_ADMIN reaches the serializer. Without the Sprint 27A
    guard, a COMPANY_ADMIN can silently promote any user under
    their company's customers to CUSTOMER_COMPANY_ADMIN — Section
    H-7 of the RBAC matrix forbids this.
    """

    def test_company_admin_cannot_grant_customer_company_admin_access_role(self):
        """T-1: provider COMPANY_ADMIN PATCH → CUSTOMER_COMPANY_ADMIN must fail.

        Without the Sprint 27A serializer guard this returns 200 and
        promotes the user. With the guard it returns 400 and the
        access row's role stays CUSTOMER_USER.
        """
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"access_role": CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            f"Provider COMPANY_ADMIN must not be able to grant "
            f"CUSTOMER_COMPANY_ADMIN. Got {response.status_code}: "
            f"{response.content!r}",
        )
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        self.assertEqual(
            access.access_role,
            CUSTOMER_USER,
            "Access role was unexpectedly mutated by a non-SUPER_ADMIN.",
        )

    def test_super_admin_can_grant_customer_company_admin_access_role(self):
        """T-2: SUPER_ADMIN PATCH → CUSTOMER_COMPANY_ADMIN must succeed.

        Locks the positive half of the H-7 invariant: someone has to
        be able to grant the role; that someone is SUPER_ADMIN only.
        """
        self.authenticate(self.super_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"access_role": CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            f"SUPER_ADMIN must be able to grant CUSTOMER_COMPANY_ADMIN. "
            f"Got {response.status_code}: {response.content!r}",
        )
        self.assertEqual(
            response.data["access_role"], CUSTOMER_COMPANY_ADMIN
        )

    def test_company_admin_can_still_promote_to_customer_location_manager(self):
        """Regression net: the Sprint 27A guard is narrow.

        A provider COMPANY_ADMIN must still be able to grant
        CUSTOMER_LOCATION_MANAGER (the Sprint 23C contract). The
        Sprint 27A guard only rejects CUSTOMER_COMPANY_ADMIN as the
        target value; everything else passes through unchanged.
        """
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"access_role": CUSTOMER_LOCATION_MANAGER},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["access_role"], CUSTOMER_LOCATION_MANAGER
        )


class CustomerCompanyAdminCannotPromotePeerTests(
    TenantFixtureMixin, APITestCase
):
    """
    T-3: a user with `User.role=CUSTOMER_USER` (regardless of their
    CustomerUserBuildingAccess.access_role) must NOT be able to
    reach the access-role-PATCH endpoint at all.

    The endpoint is class-gated by `IsSuperAdminOrCompanyAdminForCompany`
    which checks the *global* `User.role`, not the customer-side
    `access_role`. So a customer-side user holding
    `access_role=CUSTOMER_COMPANY_ADMIN` is still
    `User.role=CUSTOMER_USER` at the global layer and must be
    rejected at the class permission with 403 before the serializer
    ever runs. Section H-6.
    """

    def setUp(self):
        super().setUp()
        User = get_user_model()
        # A customer-side user already promoted to COMPANY_ADMIN
        # access_role on (customer, building). Their global
        # User.role stays CUSTOMER_USER — the customer-side
        # hierarchy lives on the access row, not on User.
        self.cust_company_admin = User.objects.create_user(
            email="cust-company-admin@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
            full_name="Cust Company Admin",
        )
        membership = CustomerUserMembership.objects.create(
            customer=self.customer, user=self.cust_company_admin
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=self.building,
            access_role=CUSTOMER_COMPANY_ADMIN,
        )

        # A peer to promote.
        self.peer = User.objects.create_user(
            email="peer@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
            full_name="Peer",
        )
        peer_membership = CustomerUserMembership.objects.create(
            customer=self.customer, user=self.peer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=peer_membership,
            building=self.building,
            access_role=CUSTOMER_USER,
        )

    def test_customer_company_admin_cannot_promote_peer_to_company_admin(self):
        """T-3: customer-side COMPANY_ADMIN (access_role) tries to
        promote a peer — 403 from the class permission before the
        serializer guard even runs. Locks invariant H-6.
        """
        self.authenticate(self.cust_company_admin)
        response = self.client.patch(
            _access_url(self.customer.id, self.peer.id, self.building.id),
            {"access_role": CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            f"A customer-side user (even at COMPANY_ADMIN access_role) "
            f"must not reach the access-role-PATCH endpoint. Got "
            f"{response.status_code}: {response.content!r}",
        )
        # And the peer's access_role stays untouched.
        peer_access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.peer,
            membership__customer=self.customer,
            building=self.building,
        )
        self.assertEqual(peer_access.access_role, CUSTOMER_USER)


class PermissionVsWorkflowOverrideDistinctionTests(
    TenantFixtureMixin, APITestCase
):
    """
    T-6: permission override and workflow override are separate concepts.

    Sprint 27A locks the conceptual split in the data model (the
    brief's invariant H-11):

      * Permission override changes live on
        `CustomerUserBuildingAccess.permission_overrides` (JSON dict)
        and `CustomerUserBuildingAccess.is_active` (bool). They are
        persistent toggles that alter what a user is allowed to do
        over time.

      * Workflow override changes live on the Extra Work side as
        `ExtraWorkStatusHistory.is_override` (bool) +
        `ExtraWorkRequest.override_by/_reason/_at`. They are
        per-decision audit shapes recording a one-shot provider
        action that bypassed the normal customer decision.

    This test asserts:
      (a) Toggling a permission_overrides key does NOT touch any
          workflow-override field on any ExtraWorkRequest, AND
      (b) Stamping an ExtraWorkRequest override does NOT touch
          permission_overrides on any access row.

    The fields are unrelated in the schema, but a future refactor
    that, say, tried to consolidate "all override state" into one
    blob would silently break the audit story. This test catches
    that.
    """

    def test_permission_override_is_distinct_from_workflow_override(self):
        # --- setup: one access row, one extra-work row.
        from decimal import Decimal

        from extra_work.models import (
            ExtraWorkRequest,
            ExtraWorkStatus,
        )

        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        # Baseline: both override surfaces are empty / pristine.
        self.assertEqual(access.permission_overrides, {})
        self.assertTrue(access.is_active)

        extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Permission/workflow distinction probe",
            description="x",
            status=ExtraWorkStatus.PRICING_PROPOSED,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )
        self.assertIsNone(extra_work.override_by_id)
        self.assertEqual(extra_work.override_reason, "")
        self.assertIsNone(extra_work.override_at)

        # --- mutation 1: flip a permission-override key.
        # This is a persistent permission toggle. It must touch ONLY
        # `permission_overrides` (and indirectly `is_active`), never
        # any workflow-override column on any extra-work row.
        access.permission_overrides = {
            "customer.extra_work.create": False,
        }
        access.save(update_fields=["permission_overrides"])

        extra_work.refresh_from_db()
        self.assertIsNone(
            extra_work.override_by_id,
            "Permission override should not have stamped a workflow override.",
        )
        self.assertEqual(extra_work.override_reason, "")
        self.assertIsNone(extra_work.override_at)

        # --- mutation 2: stamp a workflow override on the extra-work.
        # The state-machine path is the canonical writer; here we
        # simulate the persisted shape directly so the test stays
        # focused on the schema separation.
        from django.utils import timezone

        extra_work.override_by = self.company_admin
        extra_work.override_reason = "Customer agreed by phone."
        extra_work.override_at = timezone.now()
        extra_work.save(
            update_fields=["override_by", "override_reason", "override_at"]
        )

        access.refresh_from_db()
        self.assertEqual(
            access.permission_overrides,
            {"customer.extra_work.create": False},
            "Workflow override stamped on extra-work must not touch "
            "permission_overrides on any access row.",
        )
        self.assertTrue(access.is_active)
