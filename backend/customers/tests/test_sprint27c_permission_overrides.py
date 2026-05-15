"""
Sprint 27C — write support for permission_overrides + is_active on
CustomerUserBuildingAccess (closes RBAC gap G-B2).

Endpoint under test:
  PATCH /api/customers/<customer_id>/users/<user_id>/access/<building_id>/

Guarantees this file locks (test-first; some fail before Sprint 27C
implementation lands):

  1. permission_overrides write support
     - Only allow-listed keys (those in
       customers.permissions.CUSTOMER_PERMISSION_KEYS) accepted.
     - Values must be booleans.
     - Full-replacement semantics: the PATCH body's
       permission_overrides dict overwrites the previous one.
     - Provider-side osius.* keys MUST NOT be writable as a
       customer-side override (no scope-bleed via the override map).

  2. is_active write support
     - Provider operators (SUPER_ADMIN, COMPANY_ADMIN of the
       customer's company) can flip the per-row is_active flag.

  3. Self-edit guard (new in Sprint 27C)
     - Actor cannot edit access_role, permission_overrides, or
       is_active on their own access row, regardless of role.
     - Returns 403.

  4. Sprint 27A guard preserved:
     - Only SUPER_ADMIN may grant CUSTOMER_COMPANY_ADMIN.

  5. Customer-side users (User.role=CUSTOMER_USER) still cannot
     reach the endpoint at all (class-level gate from Sprint 23C);
     not even those holding CUSTOMER_COMPANY_ADMIN access_role.

  6. Audit
     - permission_overrides UPDATE writes an AuditLog row with
       the before/after diff.
     - is_active UPDATE writes an AuditLog row with the
       before/after diff.
     (Both fields are already in _CUBA_TRACKED_FIELDS, so the
     Sprint 23A audit signal handler should produce these rows
     automatically once the endpoint actually writes them.)
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
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


# ---------------------------------------------------------------------------
# permission_overrides write path
# ---------------------------------------------------------------------------
class PermissionOverridesWriteTests(TenantFixtureMixin, APITestCase):
    def _get_access(self):
        return CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )

    def test_company_admin_can_update_customer_user_permission_overrides_with_allowed_keys(
        self,
    ):
        """G-B2 happy path: provider COMPANY_ADMIN writes a valid
        customer.* overrides map. Endpoint returns 200 and the
        access row's permission_overrides reflects the input.
        """
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {
                "permission_overrides": {
                    "customer.ticket.create": False,
                    "customer.extra_work.view_location": True,
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        access = self._get_access()
        self.assertEqual(
            access.permission_overrides,
            {
                "customer.ticket.create": False,
                "customer.extra_work.view_location": True,
            },
        )

    def test_full_replacement_semantics_on_permission_overrides(self):
        """A second PATCH overwrites the previous override dict
        entirely — there is no merge. Locks the documented
        full-replacement semantics for predictability."""
        access = self._get_access()
        access.permission_overrides = {"customer.ticket.create": False}
        access.save(update_fields=["permission_overrides"])

        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {
                "permission_overrides": {
                    "customer.extra_work.view_company": True,
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        access.refresh_from_db()
        self.assertEqual(
            access.permission_overrides,
            {"customer.extra_work.view_company": True},
            "PATCH must replace the override dict, not merge.",
        )

    def test_empty_dict_clears_permission_overrides(self):
        access = self._get_access()
        access.permission_overrides = {"customer.ticket.create": False}
        access.save(update_fields=["permission_overrides"])

        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"permission_overrides": {}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        access.refresh_from_db()
        self.assertEqual(access.permission_overrides, {})

    def test_company_admin_cannot_write_unknown_permission_override_key(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {
                "permission_overrides": {
                    "customer.something.fake": True,
                }
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        # And the access row's permission_overrides is unchanged.
        self.assertEqual(self._get_access().permission_overrides, {})

    def test_company_admin_cannot_write_provider_permission_key_as_customer_override(
        self,
    ):
        """Provider-side osius.* keys must not bleed into the
        customer override map. Defense against scope escalation."""
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {
                "permission_overrides": {
                    "osius.ticket.assign_staff": True,
                }
            },
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(self._get_access().permission_overrides, {})

    def test_company_admin_cannot_write_non_boolean_permission_override_value(
        self,
    ):
        """Each override value must be a boolean. Reject ints,
        strings, None, lists, nested dicts."""
        bad_values = (1, 0, "true", "false", None, [], {"x": 1})
        self.authenticate(self.company_admin)
        for bad in bad_values:
            response = self.client.patch(
                _access_url(
                    self.customer.id,
                    self.customer_user.id,
                    self.building.id,
                ),
                {
                    "permission_overrides": {
                        "customer.ticket.create": bad,
                    }
                },
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"value={bad!r}: expected 400, got {response.status_code}",
            )
        self.assertEqual(self._get_access().permission_overrides, {})

    def test_permission_overrides_must_be_a_dict(self):
        """A non-dict payload for permission_overrides is 400."""
        self.authenticate(self.company_admin)
        for bad in ([], "not a dict", 1, True):
            response = self.client.patch(
                _access_url(
                    self.customer.id,
                    self.customer_user.id,
                    self.building.id,
                ),
                {"permission_overrides": bad},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"payload={bad!r}: expected 400, got {response.status_code}",
            )


# ---------------------------------------------------------------------------
# is_active write path
# ---------------------------------------------------------------------------
class IsActiveWriteTests(TenantFixtureMixin, APITestCase):
    def _get_access(self):
        return CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )

    def test_company_admin_can_deactivate_customer_building_access(self):
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(self._get_access().is_active)

    def test_company_admin_can_reactivate_customer_building_access(self):
        access = self._get_access()
        access.is_active = False
        access.save(update_fields=["is_active"])

        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(self._get_access().is_active)


# ---------------------------------------------------------------------------
# Self-edit guard (Sprint 27C — new)
# ---------------------------------------------------------------------------
class SelfEditGuardTests(TenantFixtureMixin, APITestCase):
    """
    Even SUPER_ADMIN or COMPANY_ADMIN cannot edit their own
    CustomerUserBuildingAccess row via this endpoint. The guard
    blocks every writable field (access_role, permission_overrides,
    is_active). 403.

    For these tests we synthesise a SUPER_ADMIN who happens to
    also have a CustomerUserBuildingAccess row — an unusual but
    possible production shape (e.g. an operator who is technically
    listed as a customer-side user on one of their own customers).
    """

    def setUp(self):
        super().setUp()
        User = get_user_model()
        # Give the super_admin themselves a customer access row on
        # (self.customer, self.building). The user.role stays
        # SUPER_ADMIN so they pass the endpoint's class permission;
        # the new self-edit guard must still reject the PATCH.
        membership = CustomerUserMembership.objects.create(
            customer=self.customer, user=self.super_admin
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership,
            building=self.building,
            access_role=CUSTOMER_USER,
        )

        # Same shape for company_admin.
        membership_co = CustomerUserMembership.objects.create(
            customer=self.customer, user=self.company_admin
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership_co,
            building=self.building,
            access_role=CUSTOMER_USER,
        )

    def test_self_cannot_edit_own_permission_overrides(self):
        for actor in (self.super_admin, self.company_admin):
            self.authenticate(actor)
            response = self.client.patch(
                _access_url(self.customer.id, actor.id, self.building.id),
                {"permission_overrides": {"customer.ticket.create": False}},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"actor={actor.email}: expected 403, got "
                f"{response.status_code}: {response.content!r}",
            )

    def test_self_cannot_deactivate_own_customer_access(self):
        for actor in (self.super_admin, self.company_admin):
            self.authenticate(actor)
            response = self.client.patch(
                _access_url(self.customer.id, actor.id, self.building.id),
                {"is_active": False},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"actor={actor.email}: expected 403, got "
                f"{response.status_code}: {response.content!r}",
            )

    def test_self_cannot_change_own_access_role(self):
        for actor in (self.super_admin, self.company_admin):
            self.authenticate(actor)
            response = self.client.patch(
                _access_url(self.customer.id, actor.id, self.building.id),
                {"access_role": CUSTOMER_LOCATION_MANAGER},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"actor={actor.email}: expected 403, got "
                f"{response.status_code}: {response.content!r}",
            )


# ---------------------------------------------------------------------------
# Sprint 27A guard preserved (regression net)
# ---------------------------------------------------------------------------
class SprintTwentyASevenGuardStillHoldsTests(TenantFixtureMixin, APITestCase):
    def test_only_super_admin_can_still_grant_customer_company_admin(self):
        # company_admin attempts → 400 (Sprint 27A guard)
        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"access_role": CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        # super_admin attempts → 200
        self.authenticate(self.super_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"access_role": CUSTOMER_COMPANY_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


# ---------------------------------------------------------------------------
# Customer-side users still cannot reach the endpoint
# ---------------------------------------------------------------------------
class CustomerSideCannotReachEndpointTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Promote self.customer_user to CUSTOMER_COMPANY_ADMIN access
        # role on (self.customer, self.building) so the actor below
        # has the strongest customer-side authority and the test still
        # expects a 403 — locking that the class-level gate looks at
        # User.role, not access_role.
        access = CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )
        access.access_role = CUSTOMER_COMPANY_ADMIN
        access.save(update_fields=["access_role"])

        # A peer to attempt to edit.
        User = get_user_model()
        self.peer = User.objects.create_user(
            email="peer-customer@example.com",
            password=self.password,
            role=UserRole.CUSTOMER_USER,
            full_name="Peer Customer",
        )
        peer_membership = CustomerUserMembership.objects.create(
            customer=self.customer, user=self.peer
        )
        CustomerUserBuildingAccess.objects.create(
            membership=peer_membership,
            building=self.building,
            access_role=CUSTOMER_USER,
        )

    def test_customer_company_admin_still_cannot_edit_peer_permission_overrides(
        self,
    ):
        self.authenticate(self.customer_user)
        response = self.client.patch(
            _access_url(self.customer.id, self.peer.id, self.building.id),
            {"permission_overrides": {"customer.ticket.create": False}},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            f"got {response.status_code}: {response.content!r}",
        )


# ---------------------------------------------------------------------------
# Audit coverage (existing CUBA signal should pick up the new writes)
# ---------------------------------------------------------------------------
class AuditCoverageTests(TenantFixtureMixin, APITestCase):
    def _get_access(self):
        return CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )

    def _audit_updates(self, access):
        return AuditLog.objects.filter(
            target_model="customers.CustomerUserBuildingAccess",
            target_id=access.id,
            action=AuditAction.UPDATE,
        )

    def test_permission_override_update_is_audit_logged(self):
        access = self._get_access()
        before = self._audit_updates(access).count()

        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"permission_overrides": {"customer.ticket.create": False}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        after = self._audit_updates(access)
        self.assertEqual(
            after.count() - before,
            1,
            "permission_overrides UPDATE must produce exactly one AuditLog row.",
        )
        row = after.latest("created_at")
        self.assertIn("permission_overrides", row.changes)
        diff = row.changes["permission_overrides"]
        self.assertEqual(diff.get("before"), {})
        self.assertEqual(
            diff.get("after"), {"customer.ticket.create": False}
        )

    def test_is_active_update_is_audit_logged(self):
        access = self._get_access()
        before = self._audit_updates(access).count()

        self.authenticate(self.company_admin)
        response = self.client.patch(
            _access_url(
                self.customer.id, self.customer_user.id, self.building.id
            ),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        after = self._audit_updates(access)
        self.assertEqual(
            after.count() - before,
            1,
            "is_active UPDATE must produce exactly one AuditLog row.",
        )
        row = after.latest("created_at")
        self.assertIn("is_active", row.changes)
        diff = row.changes["is_active"]
        self.assertEqual(diff.get("before"), True)
        self.assertEqual(diff.get("after"), False)
