"""
SoT Addendum A.1 — Customer Company Admin (CCA) is now a COMPANY-WIDE
membership status (`CustomerUserMembership.is_company_admin`), not a
per-building `access_role`.

A company-wide CCA:
  * is admin across ALL of the customer's buildings (present + future),
  * needs NO per-building `CustomerUserBuildingAccess` (CUBA) rows,
  * cannot be downgraded by any per-building row,
  * is toggled via POST/DELETE
    `/api/customers/<cid>/users/<uid>/company-admin/` (audited), and
  * supersedes the legacy per-building CCA rows, which the 0010
    forward-only migration collapses into the flag.

These tests pin the new behaviour end to end:
  1. Scoping with the flag + ZERO CUBA rows (tickets, extra work, buildings).
  2. `compute_role_defaults` flag-wins (no per-building downgrade).
  3. The effective-permissions endpoint reflects company-wide CCA.
  4. The company-admin toggle endpoint (auth matrix + audit + idempotency).
  5. The 0010 migration collapse semantics.
  6. Back-compat for plain Customer User / Customer Location Manager.
  7. Regression for the row-based CCA checks that had to learn the flag:
     ticket-create, Extra Work actor classification, the
     `CanManageCustomerSideUsers` admit, and the two
     `customer_access_role` projections.

No new permission keys. One migration (0010). No frontend changes here.
"""
from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.effective_actions import compute_role_defaults
from accounts.models import UserRole
from accounts.scoping import (
    building_ids_for,
    company_admin_customer_ids,
    scope_tickets_for,
)
from audit.models import AuditLog
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from customers.permissions import user_can
from extra_work.models import ExtraWorkRequest
from extra_work.scoping import scope_extra_work_for
from tickets.models import Ticket, TicketStatus, TicketType


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
CCA = CustomerUserBuildingAccess.AccessRole.CUSTOMER_COMPANY_ADMIN
CU = CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
CLM = CustomerUserBuildingAccess.AccessRole.CUSTOMER_LOCATION_MANAGER


def _mk(email: str, role: str, **extra) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _CompanyWideFixture(TestCase):
    """One provider company + a customer linked to three buildings
    (b1/b2/b3) + a SECOND customer (cross-tenant isolation guard). A
    company-wide CCA carries the membership flag with ZERO CUBA rows."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov CW", slug="prov-cw")
        cls.b1 = Building.objects.create(company=cls.company, name="CW-B1")
        cls.b2 = Building.objects.create(company=cls.company, name="CW-B2")
        cls.b3 = Building.objects.create(company=cls.company, name="CW-B3")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer CW", building=cls.b1
        )
        for b in (cls.b1, cls.b2, cls.b3):
            CustomerBuildingMembership.objects.create(
                customer=cls.customer, building=b
            )

        # A second customer + building — must stay invisible to the CCA.
        cls.ob1 = Building.objects.create(company=cls.company, name="CW-OB1")
        cls.other_customer = Customer.objects.create(
            company=cls.company, name="Other CW", building=cls.ob1
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.other_customer, building=cls.ob1
        )

        # Actors.
        cls.super_admin = _mk(
            "sa-cw@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.admin = _mk("ca-cw@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin, company=cls.company
        )
        cls.staff = _mk("staff-cw@example.com", UserRole.STAFF)

        # The company-wide CCA: membership flagged, ZERO CUBA rows.
        cls.cca_user = _mk("ccauser-cw@example.com", UserRole.CUSTOMER_USER)
        cls.cca_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.cca_user, is_company_admin=True
        )

        # A plain Customer User with a single CUSTOMER_USER row on b1.
        cls.plain_user = _mk("plain-cw@example.com", UserRole.CUSTOMER_USER)
        cls.plain_mem = CustomerUserMembership.objects.create(
            customer=cls.customer, user=cls.plain_user
        )
        cls.plain_access_b1 = CustomerUserBuildingAccess.objects.create(
            membership=cls.plain_mem, building=cls.b1, access_role=CU
        )

        # One ticket + one Extra Work per building of the customer
        # (created by the provider, so the CCA's visibility can only come
        # from the company-wide union, not `view_own`).
        cls.tickets = {}
        cls.ews = {}
        for b in (cls.b1, cls.b2, cls.b3):
            cls.tickets[b.id] = Ticket.objects.create(
                company=cls.company,
                building=b,
                customer=cls.customer,
                created_by=cls.super_admin,
                title=f"T {b.name}",
                description="d",
                type=TicketType.REPORT,
            )
            cls.ews[b.id] = ExtraWorkRequest.objects.create(
                company=cls.company,
                building=b,
                customer=cls.customer,
                created_by=cls.super_admin,
                title=f"EW {b.name}",
                description="d",
            )
        # And one ticket/EW on the OTHER customer — never visible to CCA.
        cls.other_ticket = Ticket.objects.create(
            company=cls.company,
            building=cls.ob1,
            customer=cls.other_customer,
            created_by=cls.super_admin,
            title="other T",
            description="d",
            type=TicketType.REPORT,
        )
        cls.other_ew = ExtraWorkRequest.objects.create(
            company=cls.company,
            building=cls.ob1,
            customer=cls.other_customer,
            created_by=cls.super_admin,
            title="other EW",
            description="d",
        )

    # --- helpers -----------------------------------------------------
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _ca_url(self, customer_id, user_id):
        return f"/api/customers/{customer_id}/users/{user_id}/company-admin/"

    def _effective_url(self, user_id, customer_id, building_id=None):
        url = (
            f"/api/users/{user_id}/effective-permissions/"
            f"?customer_id={customer_id}"
        )
        if building_id is not None:
            url += f"&building_id={building_id}"
        return url


# ---------------------------------------------------------------------------
# 1. Scoping with the flag + ZERO CUBA rows.
# ---------------------------------------------------------------------------
class CompanyWideScopeTests(_CompanyWideFixture):
    def test_helper_returns_admin_customer_id(self):
        self.assertEqual(
            set(company_admin_customer_ids(self.cca_user)),
            {self.customer.id},
        )
        self.assertEqual(company_admin_customer_ids(self.plain_user), set())

    def test_cca_has_zero_cuba_rows(self):
        # Sanity: the company-wide CCA's authority is the flag, not rows.
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(
                membership=self.cca_mem
            ).count(),
            0,
        )

    def test_building_ids_for_returns_all_customer_buildings(self):
        self.assertEqual(
            set(building_ids_for(self.cca_user)),
            {self.b1.id, self.b2.id, self.b3.id},
        )

    def test_scope_tickets_returns_all_customer_tickets(self):
        visible = set(
            scope_tickets_for(self.cca_user).values_list("id", flat=True)
        )
        self.assertEqual(
            visible, {t.id for t in self.tickets.values()}
        )
        self.assertNotIn(self.other_ticket.id, visible)

    def test_scope_extra_work_returns_all_customer_requests(self):
        visible = set(
            scope_extra_work_for(self.cca_user).values_list("id", flat=True)
        )
        self.assertEqual(visible, {e.id for e in self.ews.values()})
        self.assertNotIn(self.other_ew.id, visible)


# ---------------------------------------------------------------------------
# 2. compute_role_defaults — flag wins, no per-building downgrade.
# ---------------------------------------------------------------------------
class RoleDefaultsFlagWinsTests(_CompanyWideFixture):
    def test_role_defaults_cca_on_building_with_no_row(self):
        block = compute_role_defaults(self.cca_user, self.customer, self.b2)
        self.assertEqual(block["access_role"], CCA)
        # CCA grants the full customer.* key set.
        self.assertIn("customer.users.manage", block["default_permission_keys"])

    def test_role_defaults_cca_wins_over_lower_per_building_row(self):
        # Give the company-wide CCA a LOWER per-building row on b1; the
        # flag must still resolve CCA (no downgrade).
        CustomerUserBuildingAccess.objects.create(
            membership=self.cca_mem, building=self.b1, access_role=CU
        )
        block = compute_role_defaults(self.cca_user, self.customer, self.b1)
        self.assertEqual(block["access_role"], CCA)

    def test_role_defaults_building_none_is_cca(self):
        block = compute_role_defaults(self.cca_user, self.customer, None)
        self.assertEqual(block["access_role"], CCA)

    def test_user_can_grants_cca_keys_company_wide(self):
        # Any building, any CCA key — True, with no per-building row.
        self.assertTrue(
            user_can(
                self.cca_user,
                self.customer.id,
                self.b3.id,
                "customer.ticket.approve_location",
            )
        )
        self.assertTrue(
            user_can(
                self.cca_user, self.customer.id, None, "customer.users.manage"
            )
        )


# ---------------------------------------------------------------------------
# 3. Effective-permissions endpoint reflects company-wide CCA.
# ---------------------------------------------------------------------------
class EffectivePermissionsReflectsCompanyWideTests(_CompanyWideFixture):
    def test_endpoint_surfaces_company_wide_cca(self):
        response = self._api(self.super_admin).get(
            self._effective_url(
                self.cca_user.id, self.customer.id, self.b2.id
            )
        )
        self.assertEqual(
            response.status_code, status.HTTP_200_OK, response.data
        )
        self.assertTrue(response.data["scope"]["in_scope"])
        self.assertEqual(
            response.data["role_defaults"]["access_role"], CCA
        )
        # A company-wide CCA has no per-building overrides that apply.
        self.assertEqual(response.data["overrides"], [])

    def test_serializer_emits_is_company_admin(self):
        response = self._api(self.super_admin).get(
            f"/api/customers/{self.customer.id}/users/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data["results"]
        by_uid = {r["user_id"]: r for r in rows}
        self.assertTrue(by_uid[self.cca_user.id]["is_company_admin"])
        self.assertFalse(by_uid[self.plain_user.id]["is_company_admin"])


# ---------------------------------------------------------------------------
# 4. Company-admin toggle endpoint — auth matrix + audit + idempotency.
# ---------------------------------------------------------------------------
class CompanyAdminEndpointTests(_CompanyWideFixture):
    def _audit_count(self, membership):
        return AuditLog.objects.filter(
            target_model="customers.CustomerUserMembership",
            target_id=membership.id,
        ).count()

    def test_super_admin_grant_and_revoke_with_audit(self):
        before = self._audit_count(self.plain_mem)
        # Grant.
        r1 = self._api(self.super_admin).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r1.status_code, status.HTTP_200_OK, r1.data)
        self.assertTrue(r1.data["is_company_admin"])
        self.plain_mem.refresh_from_db()
        self.assertTrue(self.plain_mem.is_company_admin)
        self.assertEqual(self._audit_count(self.plain_mem), before + 1)
        # Revoke.
        r2 = self._api(self.super_admin).delete(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)
        self.assertFalse(r2.data["is_company_admin"])
        self.plain_mem.refresh_from_db()
        self.assertFalse(self.plain_mem.is_company_admin)
        self.assertEqual(self._audit_count(self.plain_mem), before + 2)

    def test_response_includes_actions_block(self):
        r = self._api(self.super_admin).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertIn("actions", r.data)
        self.assertIn("can_manage_customer_company_admins", r.data["actions"])

    def test_company_admin_allowed_when_policy_true(self):
        # Default policy is True.
        r = self._api(self.admin).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.plain_mem.refresh_from_db()
        self.assertTrue(self.plain_mem.is_company_admin)

    def test_company_admin_blocked_when_policy_false(self):
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=[
                "provider_admin_may_manage_customer_company_admins"
            ]
        )
        r = self._api(self.admin).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(r.data.get("code"), "cca_management_forbidden")
        self.plain_mem.refresh_from_db()
        self.assertFalse(self.plain_mem.is_company_admin)

    def test_company_admin_revoke_blocked_when_policy_false(self):
        # Grant first (as SA), then disable the policy and try to revoke
        # as the provider admin — blocked.
        self.plain_mem.is_company_admin = True
        self.plain_mem.save(update_fields=["is_company_admin"])
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=[
                "provider_admin_may_manage_customer_company_admins"
            ]
        )
        r = self._api(self.admin).delete(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.plain_mem.refresh_from_db()
        self.assertTrue(self.plain_mem.is_company_admin)

    def test_super_admin_can_toggle_regardless_of_policy(self):
        self.company.provider_admin_may_manage_customer_company_admins = False
        self.company.save(
            update_fields=[
                "provider_admin_may_manage_customer_company_admins"
            ]
        )
        r = self._api(self.super_admin).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

    def test_cca_actor_cannot_toggle_a_peer(self):
        # The company-wide CCA actor (a CUSTOMER_USER) must not be able
        # to grant/revoke another user's company-admin status.
        r = self._api(self.cca_user).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.plain_mem.refresh_from_db()
        self.assertFalse(self.plain_mem.is_company_admin)

    def test_staff_actor_refused(self):
        r = self._api(self.staff).post(
            self._ca_url(self.customer.id, self.plain_user.id)
        )
        self.assertIn(
            r.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_404_when_target_has_no_membership(self):
        stranger = _mk("stranger-cw@example.com", UserRole.CUSTOMER_USER)
        r = self._api(self.super_admin).post(
            self._ca_url(self.customer.id, stranger.id)
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_idempotent_grant_writes_no_extra_audit_row(self):
        api = self._api(self.super_admin)
        r1 = api.post(self._ca_url(self.customer.id, self.plain_user.id))
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        after_first = self._audit_count(self.plain_mem)
        # A second grant is a no-op success and must NOT write a row.
        r2 = api.post(self._ca_url(self.customer.id, self.plain_user.id))
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertTrue(r2.data["is_company_admin"])
        self.assertEqual(self._audit_count(self.plain_mem), after_first)


# ---------------------------------------------------------------------------
# 5. The 0010 migration collapse semantics.
# ---------------------------------------------------------------------------
class MigrationCollapseTests(TestCase):
    """Exercises the forward data step of customers/0010 directly against
    the current schema (the column already exists post-migrate)."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov MIG", slug="prov-mig")
        cls.b1 = Building.objects.create(company=cls.company, name="MIG-B1")
        cls.b2 = Building.objects.create(company=cls.company, name="MIG-B2")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Customer MIG", building=cls.b1
        )
        for b in (cls.b1, cls.b2):
            CustomerBuildingMembership.objects.create(
                customer=cls.customer, building=b
            )

    def _collapse(self):
        module = importlib.import_module(
            "customers.migrations.0010_add_is_company_admin"
        )
        module.collapse_cca_rows(django_apps, None)

    def _mem(self, email):
        user = _mk(email, UserRole.CUSTOMER_USER)
        return CustomerUserMembership.objects.create(
            customer=self.customer, user=user
        )

    def test_multi_building_cca_collapses_to_flag(self):
        mem = self._mem("mig-multi@example.com")
        CustomerUserBuildingAccess.objects.create(
            membership=mem, building=self.b1, access_role=CCA
        )
        CustomerUserBuildingAccess.objects.create(
            membership=mem, building=self.b2, access_role=CCA
        )
        self._collapse()
        mem.refresh_from_db()
        self.assertTrue(mem.is_company_admin)
        self.assertEqual(
            CustomerUserBuildingAccess.objects.filter(membership=mem).count(),
            0,
        )

    def test_mixed_rows_keep_lower_row_drop_cca_row(self):
        mem = self._mem("mig-mixed@example.com")
        CustomerUserBuildingAccess.objects.create(
            membership=mem, building=self.b1, access_role=CCA
        )
        keep = CustomerUserBuildingAccess.objects.create(
            membership=mem, building=self.b2, access_role=CU
        )
        self._collapse()
        mem.refresh_from_db()
        self.assertTrue(mem.is_company_admin)
        remaining = list(
            CustomerUserBuildingAccess.objects.filter(membership=mem)
        )
        self.assertEqual(remaining, [keep])
        self.assertEqual(remaining[0].access_role, CU)

    def test_non_cca_membership_untouched(self):
        mem = self._mem("mig-plain@example.com")
        row = CustomerUserBuildingAccess.objects.create(
            membership=mem, building=self.b1, access_role=CU
        )
        self._collapse()
        mem.refresh_from_db()
        self.assertFalse(mem.is_company_admin)
        self.assertTrue(
            CustomerUserBuildingAccess.objects.filter(pk=row.pk).exists()
        )


# ---------------------------------------------------------------------------
# 6. Back-compat — plain Customer User / Customer Location Manager.
# ---------------------------------------------------------------------------
class BackCompatTests(_CompanyWideFixture):
    def test_plain_user_not_company_wide(self):
        self.assertEqual(company_admin_customer_ids(self.plain_user), set())
        # No company-wide building expansion: only their single b1 row.
        self.assertEqual(set(building_ids_for(self.plain_user)), {self.b1.id})

    def test_plain_user_does_not_see_other_building_tickets(self):
        # The key back-compat guard: a plain user with only a b1 row must
        # NOT gain company-wide ticket visibility.
        visible = set(
            scope_tickets_for(self.plain_user).values_list("id", flat=True)
        )
        self.assertNotIn(self.tickets[self.b2.id].id, visible)
        self.assertNotIn(self.tickets[self.b3.id].id, visible)

    def test_plain_user_role_default_not_cca(self):
        block = compute_role_defaults(self.plain_user, self.customer, self.b1)
        self.assertEqual(block["access_role"], CU)
        self.assertFalse(
            user_can(
                self.plain_user,
                self.customer.id,
                None,
                "customer.users.manage",
            )
        )

    def test_location_manager_role_default_not_cca(self):
        clm_user = _mk("clm-cw@example.com", UserRole.CUSTOMER_USER)
        clm_mem = CustomerUserMembership.objects.create(
            customer=self.customer, user=clm_user
        )
        CustomerUserBuildingAccess.objects.create(
            membership=clm_mem, building=self.b1, access_role=CLM
        )
        block = compute_role_defaults(clm_user, self.customer, self.b1)
        self.assertEqual(block["access_role"], CLM)


# ---------------------------------------------------------------------------
# 7. Regression — row-based CCA checks that had to learn the flag.
# ---------------------------------------------------------------------------
class RowBasedCcaChecksHonourFlagTests(_CompanyWideFixture):
    def test_company_wide_cca_can_create_ticket_at_any_building(self):
        # tickets.serializers ticket-create validation: a flag-CCA with
        # ZERO rows may create at any building of the customer.
        payload = {
            "building": self.b3.id,
            "customer": self.customer.id,
            "title": "CCA-created",
            "description": "x",
            "type": TicketType.REPORT,
        }
        r = self._api(self.cca_user).post("/api/tickets/", payload, format="json")
        self.assertEqual(
            r.status_code, status.HTTP_201_CREATED, getattr(r, "data", r)
        )

    def test_company_wide_cca_can_manage_lower_users(self):
        # CanManageCustomerSideUsers admit: a flag-CCA (no rows) is still
        # admitted to the customer-user management surface.
        r = self._api(self.cca_user).get(
            f"/api/customers/{self.customer.id}/users/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

    def test_employees_directory_shows_flag_cca_as_cca(self):
        # customers.serializers_memberships.get_customer_access_role: a
        # flag-CCA (no rows) reports CUSTOMER_COMPANY_ADMIN.
        r = self._api(self.super_admin).get(
            f"/api/customers/{self.customer.id}/employees/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        rows = r.data["results"]
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(
            by_id[self.cca_user.id]["customer_access_role"], CCA
        )

    def test_extra_work_classifies_flag_cca_as_company_admin(self):
        # extra_work.serializers.derive_actor_kind: a flag-CCA classifies
        # as the company-admin actor regardless of any per-building row.
        from extra_work.serializers import derive_actor_kind

        kind = derive_actor_kind(self.cca_user, self.customer, self.b2)
        self.assertEqual(kind, "CUSTOMER_COMPANY_ADMIN")

    def test_company_wide_cca_in_scope_for_ticket_messages_attachments(self):
        # tickets.permissions.user_has_scope_for_ticket: a flag-CCA (zero
        # rows) is in scope for every ticket of the customer, so it can
        # post messages / attachments and drive transitions.
        from tickets.permissions import user_has_scope_for_ticket

        for b in (self.b1, self.b2, self.b3):
            self.assertTrue(
                user_has_scope_for_ticket(
                    self.cca_user, self.tickets[b.id]
                )
            )
        # Cross-customer isolation still holds.
        self.assertFalse(
            user_has_scope_for_ticket(self.cca_user, self.other_ticket)
        )

    def test_company_wide_cca_can_approve_or_reject_any_ticket(self):
        # tickets.state_machine SCOPE_CUSTOMER_LINKED: a flag-CCA may drive
        # the customer-decision transition on ANY building, no per-row req.
        from tickets.state_machine import can_transition

        waiting = Ticket.objects.create(
            company=self.company,
            building=self.b2,
            customer=self.customer,
            created_by=self.super_admin,
            title="await",
            description="d",
            type=TicketType.REPORT,
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self.assertTrue(
            can_transition(self.cca_user, waiting, TicketStatus.APPROVED)
        )
        self.assertTrue(
            can_transition(self.cca_user, waiting, TicketStatus.REJECTED)
        )

    def test_company_wide_cca_sees_service_catalog(self):
        # extra_work.catalog_scope: a flag-CCA sees the provider catalog of
        # the customer's company (else an empty Extra Work cart).
        from extra_work.catalog_scope import scope_company_ids_for_catalog

        scope = scope_company_ids_for_catalog(self.cca_user)
        self.assertIsNotNone(scope)
        self.assertIn(self.company.id, scope)

    def test_company_wide_cca_can_read_customer_pricing(self):
        # extra_work.views_pricing._customer_user_has_access: a flag-CCA is
        # admitted to the customer-side pricing read (privilege-inversion
        # guard — a strictly-lower Customer User with one row is admitted).
        from extra_work.views_pricing import _customer_user_has_access

        self.assertTrue(
            _customer_user_has_access(self.cca_user, self.customer)
        )
