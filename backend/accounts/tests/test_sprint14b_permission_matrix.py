"""
Sprint 14B — Permission Matrix Backend Contract.

Pins the read-only GET /api/permissions/matrix/ endpoint:

  * tri-state rows (inherited / override / effective / source) for both
    target types,
  * override-allow / override-deny / inherited / policy-denied source
    strings,
  * the deliberate deviation note: `effective` mirrors the LIVE resolver
    (override-wins-over-policy), while `policy_denied` flags only the
    canonical "policy removed an otherwise-granted key" case,
  * BM matrix surfaces ONLY BM_MATRIX_KEYS (no customer.* / no
    osius.staff.manage),
  * grantable / read_only lists disjoint + covering, policy_denied subset,
  * scope (SA any, CA own-company, BM own-building; out-of-scope -> 404;
    STAFF / CUSTOMER_USER -> 403; anon -> 401),
  * GET writes nothing (AuditLog count + permission_overrides unchanged).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from accounts.permission_matrix import (
    BM_MATRIX_KEYS,
    CUSTOMER_MATRIX_KEYS,
)
from audit.models import AuditLog
from buildings.models import BuildingManagerAssignment
from customers.models import (
    CustomerCompanyPolicy,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from test_utils import TenantFixtureMixin


CUSTOMER_USER = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
CUSTOMER_LOCATION_MANAGER = (
    CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER
)

MATRIX_URL = "/api/permissions/matrix/"

OVERRIDE_KEY = "osius.building_manager.override_customer_decision"
PREP_KEY = "osius.building_manager.prepare_extra_work_proposal"
VIEW_BUILDING_KEY = "osius.ticket.view_building"


def _customer_url(access_id: int) -> str:
    return (
        f"{MATRIX_URL}?target_type=customer_building_access"
        f"&target_id={access_id}"
    )


def _bm_url(assignment_id: int) -> str:
    return (
        f"{MATRIX_URL}?target_type=building_manager_assignment"
        f"&target_id={assignment_id}"
    )


class _MatrixFixture(TenantFixtureMixin, APITestCase):
    def _access(self) -> CustomerUserBuildingAccess:
        return CustomerUserBuildingAccess.objects.get(
            membership__user=self.customer_user,
            membership__customer=self.customer,
            building=self.building,
        )

    def _bm_assignment(self) -> BuildingManagerAssignment:
        return BuildingManagerAssignment.objects.get(
            user=self.manager, building=self.building
        )

    def _rows_by_key(self, response) -> dict:
        return {r["key"]: r for r in response.data["permissions"]}


# ---------------------------------------------------------------------------
# (1) tri-state shape + disjoint/covering grantable/read_only
# ---------------------------------------------------------------------------
class CustomerMatrixShapeTests(_MatrixFixture):
    def test_customer_matrix_returns_tristate_rows(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        rows = response.data["permissions"]
        self.assertEqual(
            {r["key"] for r in rows}, set(CUSTOMER_MATRIX_KEYS)
        )
        for r in rows:
            for field in (
                "key",
                "label",
                "category",
                "description",
                "inherited",
                "override",
                "effective",
                "source",
                "grantable",
                "read_only",
                "policy_denied",
                "policy_denied_reason",
                "read_only_reason",
            ):
                self.assertIn(field, r, f"row {r['key']} missing {field}")
            self.assertIsInstance(r["inherited"], bool)
            self.assertIsInstance(r["effective"], bool)
            self.assertIn(r["override"], (True, False, None))

        grantable = set(response.data["grantable_keys"])
        read_only = set(response.data["read_only_keys"])
        all_keys = {r["key"] for r in rows}
        self.assertEqual(grantable | read_only, all_keys)
        self.assertEqual(grantable & read_only, set())

        policy_denied = set(response.data["policy_denied_keys"])
        self.assertTrue(policy_denied.issubset(all_keys))

    def test_no_osius_keys_in_customer_matrix(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for r in response.data["permissions"]:
            self.assertTrue(r["key"].startswith("customer."))


# ---------------------------------------------------------------------------
# (2) override deny
# ---------------------------------------------------------------------------
class OverrideDenyTests(_MatrixFixture):
    def test_override_deny_on_inherited_true_key(self):
        access = self._access()
        access.permission_overrides = {"customer.ticket.create": False}
        access.save(update_fields=["permission_overrides"])

        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(access.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._rows_by_key(response)["customer.ticket.create"]
        self.assertIs(row["inherited"], True)
        self.assertIs(row["override"], False)
        self.assertIs(row["effective"], False)
        self.assertEqual(row["source"], "override_deny")
        self.assertIs(row["policy_denied"], False)


# ---------------------------------------------------------------------------
# (3) override allow
# ---------------------------------------------------------------------------
class OverrideAllowTests(_MatrixFixture):
    def test_override_allow_on_inherited_false_key(self):
        # customer.ticket.view_location is NOT a CUSTOMER_USER default.
        access = self._access()
        access.permission_overrides = {"customer.ticket.view_location": True}
        access.save(update_fields=["permission_overrides"])

        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(access.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._rows_by_key(response)["customer.ticket.view_location"]
        self.assertIs(row["inherited"], False)
        self.assertIs(row["override"], True)
        self.assertIs(row["effective"], True)
        self.assertEqual(row["source"], "override_allow")


# ---------------------------------------------------------------------------
# (4) no override -> inherited
# ---------------------------------------------------------------------------
class InheritedTests(_MatrixFixture):
    def test_no_override_effective_equals_inherited(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # customer.ticket.view_own is a CUSTOMER_USER default (no policy
        # field touches it) -> inherited True, override None, source
        # inherited.
        row = self._rows_by_key(response)["customer.ticket.view_own"]
        self.assertIsNone(row["override"])
        self.assertIs(row["effective"], row["inherited"])
        self.assertEqual(row["source"], "inherited")
        # A non-default key with no override -> inherited False, source
        # inherited.
        row2 = self._rows_by_key(response)["customer.ticket.view_company"]
        self.assertIsNone(row2["override"])
        self.assertIs(row2["inherited"], False)
        self.assertIs(row2["effective"], False)
        self.assertEqual(row2["source"], "inherited")


# ---------------------------------------------------------------------------
# (5) policy-denied
# ---------------------------------------------------------------------------
class PolicyDeniedTests(_MatrixFixture):
    def setUp(self):
        super().setUp()
        policy, _ = CustomerCompanyPolicy.objects.get_or_create(
            customer=self.customer
        )
        policy.customer_users_can_create_tickets = False
        policy.save(update_fields=["customer_users_can_create_tickets"])

    def test_policy_denied_key_shape(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._rows_by_key(response)["customer.ticket.create"]
        self.assertIs(row["inherited"], True)
        self.assertIsNone(row["override"])
        self.assertIs(row["effective"], False)
        self.assertIs(row["policy_denied"], True)
        self.assertEqual(row["source"], "policy_denied")
        self.assertEqual(
            row["policy_denied_reason"]["code"],
            "customer_company_policy_denied",
        )
        self.assertEqual(
            row["policy_denied_reason"]["policy_key"],
            "customer_users_can_create_tickets",
        )
        self.assertEqual(row["policy_denied_reason"]["scope"], "customer")
        self.assertIn(
            "customer.ticket.create", response.data["policy_denied_keys"]
        )
        self.assertIs(row["grantable"], False)
        self.assertIs(row["read_only"], True)
        self.assertEqual(row["read_only_reason"], "policy_denied")

    def test_override_true_beats_policy_in_effective(self):
        # Deviation note: override-wins-over-policy. An explicit override
        # True must make effective True even when the policy restricts the
        # family. policy_denied is False here (the override is present).
        access = self._access()
        access.permission_overrides = {"customer.ticket.create": True}
        access.save(update_fields=["permission_overrides"])

        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(access.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._rows_by_key(response)["customer.ticket.create"]
        self.assertIs(row["override"], True)
        self.assertIs(row["effective"], True)
        self.assertIs(row["policy_denied"], False)
        self.assertEqual(row["source"], "override_allow")
        # The family is still locked for editing by the policy restriction.
        self.assertIs(row["grantable"], False)
        self.assertEqual(row["read_only_reason"], "policy_denied")


# ---------------------------------------------------------------------------
# (6) BM matrix
# ---------------------------------------------------------------------------
class BmMatrixTests(_MatrixFixture):
    def setUp(self):
        super().setUp()
        assignment = self._bm_assignment()
        assignment.permission_overrides = {OVERRIDE_KEY: False}
        assignment.save(update_fields=["permission_overrides"])

    def test_bm_matrix_only_bm_keys(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_bm_url(self._bm_assignment().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        keys = {r["key"] for r in response.data["permissions"]}
        self.assertEqual(keys, set(BM_MATRIX_KEYS))
        # No customer.* keys, no company-management key.
        for k in keys:
            self.assertFalse(k.startswith("customer."))
        self.assertNotIn("osius.staff.manage", keys)
        self.assertNotIn("osius.building.manage", keys)
        self.assertNotIn("osius.customer_company.manage", keys)

    def test_revocable_override_deny_row(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_bm_url(self._bm_assignment().id))
        row = self._rows_by_key(response)[OVERRIDE_KEY]
        self.assertIs(row["override"], False)
        self.assertIs(row["effective"], False)
        self.assertEqual(row["source"], "override_deny")
        self.assertIs(row["policy_denied"], False)

    def test_building_scoped_key_system_managed(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_bm_url(self._bm_assignment().id))
        row = self._rows_by_key(response)[VIEW_BUILDING_KEY]
        self.assertIs(row["read_only"], True)
        self.assertEqual(row["read_only_reason"], "system_managed")
        self.assertIs(row["grantable"], False)

    def test_revocable_no_override_grantable_for_ca(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_bm_url(self._bm_assignment().id))
        row = self._rows_by_key(response)[PREP_KEY]
        self.assertIsNone(row["override"])
        self.assertEqual(row["source"], "inherited")
        self.assertIs(row["grantable"], True)

    def test_self_edit_forbidden_for_bm_actor_on_own_assignment(self):
        # A BM viewing their OWN assignment: revocable keys must be
        # read-only and never grantable. Per the spec ordering the
        # self-edit guard is checked before the actor-role gate, so the
        # reason is self_edit_forbidden.
        self.authenticate(self.manager)
        response = self.client.get(_bm_url(self._bm_assignment().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        row = self._rows_by_key(response)[PREP_KEY]
        self.assertIs(row["grantable"], False)
        self.assertEqual(row["read_only_reason"], "self_edit_forbidden")


# ---------------------------------------------------------------------------
# (7) list/flag consistency
# ---------------------------------------------------------------------------
class ListConsistencyTests(_MatrixFixture):
    def test_lists_match_row_flags(self):
        access = self._access()
        access.permission_overrides = {"customer.ticket.view_location": True}
        access.save(update_fields=["permission_overrides"])
        policy, _ = CustomerCompanyPolicy.objects.get_or_create(
            customer=self.customer
        )
        policy.customer_users_can_create_tickets = False
        policy.save(update_fields=["customer_users_can_create_tickets"])

        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(access.id))
        rows = response.data["permissions"]

        grantable_from_rows = {r["key"] for r in rows if r["grantable"]}
        read_only_from_rows = {r["key"] for r in rows if r["read_only"]}
        policy_from_rows = {r["key"] for r in rows if r["policy_denied"]}

        self.assertEqual(
            grantable_from_rows, set(response.data["grantable_keys"])
        )
        self.assertEqual(
            read_only_from_rows, set(response.data["read_only_keys"])
        )
        self.assertEqual(
            policy_from_rows, set(response.data["policy_denied_keys"])
        )
        self.assertEqual(grantable_from_rows & read_only_from_rows, set())


# ---------------------------------------------------------------------------
# (8) scope + auth
# ---------------------------------------------------------------------------
class ScopeAndAuthTests(_MatrixFixture):
    def _other_access(self) -> CustomerUserBuildingAccess:
        return CustomerUserBuildingAccess.objects.get(
            membership__user=self.other_customer_user,
            membership__customer=self.other_customer,
            building=self.other_building,
        )

    def test_super_admin_reads_any(self):
        self.authenticate(self.super_admin)
        for url in (
            _customer_url(self._access().id),
            _customer_url(self._other_access().id),
        ):
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, status.HTTP_200_OK, response.data
            )

    def test_company_admin_reads_own_company_target(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_company_admin_out_of_scope_target_404(self):
        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(self._other_access().id))
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND, response.data
        )

    def test_building_manager_reads_assigned_building_target(self):
        self.authenticate(self.manager)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_building_manager_out_of_scope_target_404(self):
        self.authenticate(self.manager)
        response = self.client.get(_customer_url(self._other_access().id))
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND, response.data
        )

    def test_building_manager_is_read_only_on_customer_target(self):
        self.authenticate(self.manager)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        rows = response.data["permissions"]
        self.assertEqual(response.data["grantable_keys"], [])
        for r in rows:
            self.assertIs(r["grantable"], False)
            # On non-policy-restricted keys the BM read-only reason is
            # actor_not_allowed (policy-restricted keys read policy_denied).
            if not r["policy_denied"]:
                self.assertEqual(r["read_only_reason"], "actor_not_allowed")

    def test_staff_forbidden(self):
        User = get_user_model()
        staff = User.objects.create_user(
            email="staff-14b@example.com",
            password=self.password,
            role=UserRole.STAFF,
            full_name="Staff 14B",
        )
        self.authenticate(staff)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )

    def test_customer_user_forbidden(self):
        self.authenticate(self.customer_user)
        response = self.client.get(_customer_url(self._access().id))
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN, response.data
        )

    def test_anonymous_unauthorized(self):
        response = self.client.get(_customer_url(self._access().id))
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_missing_target_type_400(self):
        self.authenticate(self.company_admin)
        response = self.client.get(
            f"{MATRIX_URL}?target_id={self._access().id}"
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "target_type_required")

    def test_invalid_target_type_400(self):
        self.authenticate(self.company_admin)
        response = self.client.get(
            f"{MATRIX_URL}?target_type=bogus&target_id={self._access().id}"
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "target_type_invalid")

    def test_invalid_target_id_400(self):
        self.authenticate(self.company_admin)
        response = self.client.get(
            f"{MATRIX_URL}?target_type=customer_building_access"
            f"&target_id=notanint"
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.data
        )
        self.assertEqual(response.data.get("code"), "target_id_invalid")

    def test_unknown_target_id_404(self):
        self.authenticate(self.company_admin)
        response = self.client.get(
            f"{MATRIX_URL}?target_type=customer_building_access"
            f"&target_id=99999999"
        )
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND, response.data
        )


# ---------------------------------------------------------------------------
# (9) GET writes nothing
# ---------------------------------------------------------------------------
class NoWriteTests(_MatrixFixture):
    def test_get_does_not_write_audit_or_mutate_overrides(self):
        access = self._access()
        access.permission_overrides = {"customer.ticket.create": False}
        access.save(update_fields=["permission_overrides"])

        before_audit = AuditLog.objects.count()
        before_overrides = dict(self._access().permission_overrides)

        self.authenticate(self.company_admin)
        response = self.client.get(_customer_url(access.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        # A second GET as well, to be sure nothing accumulates.
        self.client.get(_bm_url(self._bm_assignment().id))

        self.assertEqual(AuditLog.objects.count(), before_audit)
        self.assertEqual(
            self._access().permission_overrides, before_overrides
        )
