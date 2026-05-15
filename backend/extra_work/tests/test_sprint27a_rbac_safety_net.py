"""
Sprint 27A — RBAC / permission / hierarchy safety net (extra_work app).

T-5  test_staff_cannot_approve_or_override_extra_work_pricing

Asserts hard invariant H-5 from docs/architecture/sprint-27-rbac-matrix.md:
STAFF must never drive an Extra Work request from
PRICING_PROPOSED into CUSTOMER_APPROVED or CUSTOMER_REJECTED.
That decision belongs to the customer (or, via the explicit
workflow-override path with mandatory reason, to a provider
operator — NOT staff).

Today's enforcement points:
  * `_is_provider_operator` excludes STAFF
    [extra_work/state_machine.py:64-71].
  * `_user_can_drive_transition` only walks the customer-approve
    branch when `user.role == CUSTOMER_USER`
    [extra_work/state_machine.py:152].

The test exercises both the direct state-machine call and the
HTTP `/transition/` endpoint with `is_override=True`, locking
that STAFF cannot route through either.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import StaffProfile, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.models import (
    ExtraWorkPricingLineItem,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from extra_work.state_machine import (
    TransitionError,
    apply_transition,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class StaffCannotApproveOrOverrideExtraWorkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

        # Provider operators (admin + manager) so we can drive the
        # row into PRICING_PROPOSED for the test.
        cls.admin = _mk("admin@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.manager = _mk("mgr@example.com", UserRole.BUILDING_MANAGER)
        BuildingManagerAssignment.objects.create(
            user=cls.manager, building=cls.building
        )

        # The actor under test.
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        # Give staff broad visibility so a scope leak (not the
        # decision block) would surface as a false-pass. Staff is
        # in scope but must still be blocked at the decision.
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

        cls.cust_user = _mk("cust@example.com", UserRole.CUSTOMER_USER)
        membership = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cust_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=cls.building
        )

        cls.ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.building,
            customer=cls.customer,
            created_by=cls.cust_user,
            title="Pricing decision target",
            description="x",
            status=ExtraWorkStatus.UNDER_REVIEW,
        )
        ExtraWorkPricingLineItem.objects.create(
            extra_work=cls.ew,
            description="Crew",
            unit_type="FIXED",
            quantity=Decimal("1"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
        )
        # Drive into PRICING_PROPOSED as the admin so the candidate
        # transitions for the test are CUSTOMER_APPROVED / REJECTED.
        cls.ew = apply_transition(
            cls.ew, cls.admin, ExtraWorkStatus.PRICING_PROPOSED
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_staff_cannot_approve_or_override_extra_work_pricing(self):
        """T-5: STAFF cannot drive PRICING_PROPOSED -> CUSTOMER_APPROVED
        or CUSTOMER_REJECTED via state machine OR HTTP, plain or
        with `is_override=True`."""

        # --- direct state-machine path (plain)
        for target in (
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ):
            with self.assertRaises(TransitionError) as ctx:
                apply_transition(self.ew, self.staff, target)
            self.assertEqual(
                ctx.exception.code,
                "forbidden_transition",
                f"STAFF must hit forbidden_transition on "
                f"PRICING_PROPOSED -> {target}, got {ctx.exception.code!r}",
            )
            self.ew.refresh_from_db()
            self.assertEqual(
                self.ew.status, ExtraWorkStatus.PRICING_PROPOSED
            )

        # --- direct state-machine path (with override args)
        # STAFF must not be able to use the workflow-override channel
        # either. The provider-operator branch in
        # _user_can_drive_transition starts with `_is_provider_operator`,
        # which excludes STAFF, so this rejects with
        # forbidden_transition before the override_reason check runs.
        for target in (
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ):
            with self.assertRaises(TransitionError) as ctx:
                apply_transition(
                    self.ew,
                    self.staff,
                    target,
                    is_override=True,
                    override_reason="staff trying to override",
                )
            self.assertEqual(
                ctx.exception.code,
                "forbidden_transition",
                f"STAFF override attempt on PRICING_PROPOSED -> {target} "
                f"must be forbidden_transition, got {ctx.exception.code!r}",
            )

        # --- HTTP path (plain)
        client = self._api(self.staff)
        for target in (
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ):
            response = client.post(
                f"/api/extra-work/{self.ew.id}/transition/",
                {"to_status": target},
                format="json",
            )
            # STAFF returns empty queryset from scope_extra_work_for
            # in the MVP, so the most likely shape is 404. If a future
            # refactor widens STAFF visibility, the state-machine
            # forbidden_transition (400) is the second layer.
            self.assertIn(
                response.status_code,
                (
                    status.HTTP_403_FORBIDDEN,
                    status.HTTP_404_NOT_FOUND,
                    status.HTTP_400_BAD_REQUEST,
                ),
                f"STAFF POST /transition/ {target} must not succeed; "
                f"got {response.status_code}: {response.content!r}",
            )
            self.ew.refresh_from_db()
            self.assertEqual(
                self.ew.status, ExtraWorkStatus.PRICING_PROPOSED
            )

        # --- HTTP path (with workflow override args)
        for target in (
            ExtraWorkStatus.CUSTOMER_APPROVED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ):
            response = client.post(
                f"/api/extra-work/{self.ew.id}/transition/",
                {
                    "to_status": target,
                    "is_override": True,
                    "override_reason": "staff trying to override",
                },
                format="json",
            )
            self.assertIn(
                response.status_code,
                (
                    status.HTTP_403_FORBIDDEN,
                    status.HTTP_404_NOT_FOUND,
                    status.HTTP_400_BAD_REQUEST,
                ),
                f"STAFF override attempt {target} must not succeed; "
                f"got {response.status_code}: {response.content!r}",
            )
            self.ew.refresh_from_db()
            self.assertEqual(
                self.ew.status, ExtraWorkStatus.PRICING_PROPOSED
            )
