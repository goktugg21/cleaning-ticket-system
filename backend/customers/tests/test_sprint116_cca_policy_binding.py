"""
Sprint 116 — CustomerCompanyPolicy binds a company-wide Customer Company Admin.

Owner decision (2026-07-26, SoT Addendum A.1): the company-level
`CustomerCompanyPolicy` toggles MUST bind a company-wide Customer Company
Admin (CCA). Turning a policy family off for the customer denies that
family's keys even for a CCA.

Per Addendum A.1 the CCA otherwise stays the un-downgradable top customer-side
role: the per-building `is_active` and `permission_overrides` layers still do
NOT apply to a company-wide CCA, and no per-building row can downgrade one. The
company-level policy is the ONLY layer that narrows a CCA.

A company-wide CCA carries `CustomerUserMembership.is_company_admin=True` with
ZERO `CustomerUserBuildingAccess` rows.

Sprint 116 Session A2 additionally closes two ticket-path short-circuits
that bypassed `user_can` entirely (and so bypassed the policy too):
`tickets.serializers.TicketCreateSerializer.validate` and
`tickets.state_machine._user_passes_scope`'s SCOPE_CUSTOMER_LINKED branch.
`CCATicketCreatePolicyTests` and `CCATicketApprovalPolicyTests` below drive
those REAL paths (the API endpoint / `apply_transition`), not `user_can`
directly, so a regression in the outer gate would actually be caught.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserRole
from accounts.scoping import scope_tickets_for
from buildings.models import Building
from companies.models import Company
from customers.models import (
    CustomerCompanyPolicy,
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from customers.permissions import user_can
from tickets.models import Ticket, TicketStatus, TicketType
from tickets.state_machine import TransitionError, apply_transition

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
CU = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER

# The four policy fields and the permission key(s) each one governs
# (mirrors customers.permissions._POLICY_FAMILY_FIELD, from the other side).
TOGGLES: dict[str, list[str]] = {
    "customer_users_can_create_tickets": ["customer.ticket.create"],
    "customer_users_can_approve_ticket_completion": [
        "customer.ticket.approve_own",
        "customer.ticket.approve_location",
    ],
    "customer_users_can_create_extra_work": ["customer.extra_work.create"],
    "customer_users_can_approve_extra_work_pricing": [
        "customer.extra_work.approve_own",
        "customer.extra_work.approve_location",
    ],
}


class CCAPolicyBindingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov 116", slug="prov-116")
        cls.b1 = Building.objects.create(company=cls.company, name="B116-1")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 116", building=cls.b1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.b1
        )
        cls.cca_user = User.objects.create_user(
            email="cca116@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="CCA 116",
        )
        # Company-wide CCA: membership flag set, ZERO per-building rows.
        cls.cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca_user, is_company_admin=True
        )

    def setUp(self):
        # The auto-create signal made a policy row at safe defaults (all
        # True). Fetch it fresh each test (per-test savepoint rollback keeps
        # tests isolated).
        self.policy = CustomerCompanyPolicy.objects.get(customer=self.customer)

    def _can(self, key, building_id=None):
        return user_can(self.cca_user, self.customer.id, building_id, key)

    def _set(self, field, value):
        setattr(self.policy, field, value)
        self.policy.save(update_fields=[field, "updated_at"])

    def test_each_policy_toggle_binds_the_cca(self):
        """For every policy field: True -> CCA allowed for its key(s);
        False -> CCA denied for its key(s)."""
        for field, keys in TOGGLES.items():
            for key in keys:
                self._set(field, True)
                with self.subTest(field=field, key=key, toggle=True):
                    self.assertTrue(
                        self._can(key),
                        f"{key} must be allowed for a CCA when {field}=True",
                    )
                self._set(field, False)
                with self.subTest(field=field, key=key, toggle=False):
                    self.assertFalse(
                        self._can(key),
                        f"{key} must be denied for a CCA when {field}=False",
                    )
                # Reset so a shared-field key (approve_own/approve_location)
                # starts the next iteration from True.
                self._set(field, True)

    def test_key_outside_policy_map_unaffected_by_any_toggle(self):
        """A CCA-granted key that is NOT in the policy map stays True even
        with every policy toggle turned OFF."""
        for field in TOGGLES:
            self._set(field, False)
        for key in (
            "customer.ticket.view_company",
            "customer.users.manage",
            "customer.users.manage_permissions",
        ):
            with self.subTest(key=key):
                self.assertTrue(
                    self._can(key),
                    f"{key} is outside the policy map; a CCA must still pass",
                )

    def test_cca_with_no_access_rows_resolves_when_policy_permits(self):
        """The A.1 guarantee: a company-wide CCA with ZERO per-building rows
        still resolves (True) for its keys when the policy permits."""
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(
                membership=self.cca_mem
            ).count(),
            0,
        )
        for key in (
            "customer.ticket.create",
            "customer.extra_work.approve_location",
            "customer.ticket.view_company",
        ):
            with self.subTest(key=key):
                self.assertTrue(self._can(key))

    def test_per_building_row_cannot_downgrade_a_cca(self):
        """An inactive per-building row AND a restrictive permission_overrides
        row must NOT downgrade a CCA — the short-circuit ignores per-building
        rows entirely. (Policy permits here, so only the per-building layers
        could have denied — they must not.)"""
        CustomerUserBuildingAccess.objects.create(
            membership=self.cca_mem,
            building=self.b1,
            access_role=CU,
            is_active=False,
            permission_overrides={
                "customer.ticket.create": False,
                "customer.extra_work.approve_own": False,
            },
        )
        for key in (
            "customer.ticket.create",
            "customer.extra_work.approve_own",
            "customer.ticket.approve_location",
        ):
            with self.subTest(key=key, building=self.b1.id):
                self.assertTrue(
                    self._can(key, building_id=self.b1.id),
                    f"{key}: a per-building row must not downgrade a CCA",
                )
            with self.subTest(key=key, building=None):
                self.assertTrue(
                    self._can(key),
                    f"{key}: a per-building row must not downgrade a CCA",
                )


class CCATicketCreatePolicyTests(TestCase):
    """Session A2 — the ticket CREATE path (`TicketCreateSerializer.validate`)
    used to short-circuit `if membership.is_company_admin: return attrs`,
    bypassing `user_can` and therefore the policy. It now defers to
    `user_can` itself. Driven through the real `/api/tickets/` endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov 116b", slug="prov-116b")
        cls.b1 = Building.objects.create(company=cls.company, name="B116b-1")
        cls.b2 = Building.objects.create(company=cls.company, name="B116b-2")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 116b", building=cls.b1
        )
        for b in (cls.b1, cls.b2):
            CustomerBuildingMembership.objects.create(customer=cls.customer, building=b)
        cls.cca_user = User.objects.create_user(
            email="cca116b@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="CCA 116b",
        )
        cls.cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca_user, is_company_admin=True
        )

    def setUp(self):
        self.policy = CustomerCompanyPolicy.objects.get(customer=self.customer)

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _payload(self, building):
        return {
            "building": building.id,
            "customer": self.customer.id,
            "title": "CCA ticket",
            "description": "d",
            "type": TicketType.REPORT,
        }

    def test_create_allowed_at_building_with_no_access_row_when_policy_true(self):
        """A.1 regression: the CCA has ZERO access rows anywhere, and the
        policy default is True — creation at b2 (no row) must succeed."""
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(membership=self.cca_mem).count(),
            0,
        )
        r = self._api(self.cca_user).post(
            "/api/tickets/", self._payload(self.b2), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_create_denied_when_policy_toggle_off(self):
        self.policy.customer_users_can_create_tickets = False
        self.policy.save(update_fields=["customer_users_can_create_tickets"])
        r = self._api(self.cca_user).post(
            "/api/tickets/", self._payload(self.b1), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)

    def test_create_allowed_again_when_policy_toggle_back_on(self):
        self.policy.customer_users_can_create_tickets = False
        self.policy.save(update_fields=["customer_users_can_create_tickets"])
        self.policy.customer_users_can_create_tickets = True
        self.policy.save(update_fields=["customer_users_can_create_tickets"])
        r = self._api(self.cca_user).post(
            "/api/tickets/", self._payload(self.b1), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)

    def test_per_building_row_does_not_downgrade_ticket_create(self):
        """An inactive row with a revoking override at b1 must NOT stop the
        CCA from creating at b1 (policy True — only the policy can deny)."""
        CustomerUserBuildingAccess.objects.create(
            membership=self.cca_mem,
            building=self.b1,
            access_role=CU,
            is_active=False,
            permission_overrides={"customer.ticket.create": False},
        )
        r = self._api(self.cca_user).post(
            "/api/tickets/", self._payload(self.b1), format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)


class CCATicketApprovalPolicyTests(TestCase):
    """Session A2 — the ticket-approval scope
    (`state_machine._user_passes_scope`, SCOPE_CUSTOMER_LINKED) used to
    short-circuit on `company_admin_customer_ids(user)`, bypassing
    `user_can` and therefore the policy. It now falls through to the same
    `user_can`-based approve_own/approve_location gates as everyone else.
    Driven through the real `apply_transition` (mirrors
    tickets.tests.test_sprint109_customer_approval_gate)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov 116c", slug="prov-116c")
        cls.building = Building.objects.create(company=cls.company, name="B116c-1")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 116c", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.cca_user = User.objects.create_user(
            email="cca116c@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="CCA 116c",
        )
        cls.cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca_user, is_company_admin=True
        )
        # A DIFFERENT customer user created the ticket, so the CCA must
        # resolve it via approve_location, NOT approve_own — the more
        # meaningful A.1 case (CCA drives ANY ticket of the customer).
        cls.other_user = User.objects.create_user(
            email="other116c@example.com",
            password=PASSWORD,
            role=UserRole.CUSTOMER_USER,
            full_name="Other 116c",
        )
        other_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.other_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=other_mem, building=cls.building
        )

    def setUp(self):
        self.policy = CustomerCompanyPolicy.objects.get(customer=self.customer)
        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.other_user,
            title="T 116c",
            description="d",
            type=TicketType.REPORT,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )

    def test_cca_can_approve_any_ticket_at_building_with_no_access_row(self):
        """A.1 regression: the CCA has ZERO access rows, didn't create the
        ticket, and the policy default is True — approval must succeed."""
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(membership=self.cca_mem).count(),
            0,
        )
        ticket = apply_transition(self.ticket, self.cca_user, TicketStatus.APPROVED)
        # Sprint 180 §1 — a customer approval auto-closes. This test is
        # about the CCA being ALLOWED to approve with no access row;
        # reaching a terminal state via APPROVED proves it, and the
        # denial sibling below still raises.
        self.assertEqual(ticket.status, TicketStatus.CLOSED)

    def test_approval_denied_when_policy_toggle_off(self):
        self.policy.customer_users_can_approve_ticket_completion = False
        self.policy.save(
            update_fields=["customer_users_can_approve_ticket_completion"]
        )
        with self.assertRaises(TransitionError):
            apply_transition(self.ticket, self.cca_user, TicketStatus.APPROVED)

    def test_per_building_row_does_not_downgrade_ticket_approval(self):
        """An inactive row with a revoking override at the ticket's building
        must NOT stop the CCA from approving (policy True)."""
        CustomerUserBuildingAccess.objects.create(
            membership=self.cca_mem,
            building=self.building,
            access_role=CU,
            is_active=False,
            permission_overrides={"customer.ticket.approve_location": False},
        )
        ticket = apply_transition(self.ticket, self.cca_user, TicketStatus.APPROVED)
        # Sprint 180 §1 — auto-closed. The revoking row still did not
        # stop the approval, which is what this test locks.
        self.assertEqual(ticket.status, TicketStatus.CLOSED)

    def test_visibility_unaffected_by_policy_when_action_denied(self):
        """Denial is ACTION-only: with the policy toggle off (so approval is
        refused), the CCA must still SEE the ticket via scope_tickets_for —
        no per-building row is needed for visibility either (Addendum A.1)."""
        self.policy.customer_users_can_approve_ticket_completion = False
        self.policy.save(
            update_fields=["customer_users_can_approve_ticket_completion"]
        )
        with self.assertRaises(TransitionError):
            apply_transition(self.ticket, self.cca_user, TicketStatus.APPROVED)
        self.assertTrue(
            scope_tickets_for(self.cca_user).filter(pk=self.ticket.pk).exists()
        )
