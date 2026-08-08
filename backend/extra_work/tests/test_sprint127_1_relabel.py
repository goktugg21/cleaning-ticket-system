"""
Sprint 127.1 — the provider relabel endpoint PATCH /api/extra-work/<id>/labels/.

Closes the create-only gap: the create serializer was the sole writer of
department / work_type, so ticket-converted EWs (conversion.py's direct ORM
create) could never be labelled and a mislabel could never be corrected.

Covers:
  * a ticket-converted EW (built through the REAL conversion path) can be
    relabelled afterwards;
  * a foreign-customer label is rejected with the SAME coded error as at
    create (proving the shared validator is genuinely shared);
  * clear-to-null; empty body 400;
  * the permission matrix — provider roles (SA / CA / BM-with-scope) may;
    customer 403, STAFF 403, BM-without-scope 403, cross-tenant 404;
  * relabel-after-invoiced is ALLOWED;
  * a relabel writes an attributable AuditLog UPDATE row with before/after;
  * BUILDING_MANAGER can now READ the label picker (dropdown source).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
    Department,
    WorkType,
)
from extra_work.conversion import convert_ticket_to_extra_work
from extra_work.models import ExtraWorkRequest, ExtraWorkRequestIntent
from tickets.models import Ticket, TicketStatus

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


def _labels_url(ew_id):
    return f"/api/extra-work/{ew_id}/labels/"


class _RelabelFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-1271")
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-1271")
        cls.building_a1 = Building.objects.create(
            company=cls.company_a, name="A1-1271"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="A2-1271"
        )
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A 1271"
        )
        cls.customer_a2 = Customer.objects.create(
            company=cls.company_a, name="Customer A2 1271"
        )
        for c in (cls.customer_a, cls.customer_a2):
            CustomerBuildingMembership.objects.create(
                customer=c, building=cls.building_a1
            )

        cls.admin_a = _mk("admin-a-1271@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        cls.admin_b = _mk("admin-b-1271@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_b, company=cls.company_b
        )
        # BM assigned to building_a1 (has scope on EWs there + can see
        # customer_a); a second BM assigned only to building_a2 (no scope).
        cls.bm_a = _mk("bm-a-1271@example.com", UserRole.BUILDING_MANAGER)
        CompanyUserMembership.objects.create(user=cls.bm_a, company=cls.company_a)
        BuildingManagerAssignment.objects.create(
            user=cls.bm_a, building=cls.building_a1
        )
        cls.bm_other = _mk("bm-o-1271@example.com", UserRole.BUILDING_MANAGER)
        CompanyUserMembership.objects.create(
            user=cls.bm_other, company=cls.company_a
        )
        BuildingManagerAssignment.objects.create(
            user=cls.bm_other, building=cls.building_a2
        )
        cls.staff_a = _mk("staff-a-1271@example.com", UserRole.STAFF)
        CompanyUserMembership.objects.create(
            user=cls.staff_a, company=cls.company_a
        )

        cls.cust_a = _mk("cust-a-1271@example.com", UserRole.CUSTOMER_USER)
        m_a = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_a,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )

        cls.dept_a = Department.objects.create(
            customer=cls.customer_a, name="Event"
        )
        cls.wt_a = WorkType.objects.create(
            customer=cls.customer_a, name="Eindschoonmaak"
        )
        cls.dept_a2 = Department.objects.create(
            customer=cls.customer_a2, name="Foreign dept"
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _bare_ew(self, customer=None, building=None):
        """An unlabelled EW created directly (stands in for any pre-127 row)."""
        return ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=building or self.building_a1,
            customer=customer or self.customer_a,
            created_by=self.cust_a,
            title="Unlabelled EW",
            description="d",
        )


class ConversionThenRelabelTests(_RelabelFixture):
    def _convert_a_ticket(self):
        ticket = Ticket.objects.create(
            company=self.company_a,
            building=self.building_a1,
            customer=self.customer_a,
            created_by=self.cust_a,
            title="Melding",
            description="reported",
            status=TicketStatus.OPEN,
        )
        # The REAL conversion path (service fn, direct ORM create) — the one
        # that produces rows with no way to be labelled at create.
        ew, _spawned = convert_ticket_to_extra_work(
            ticket,
            actor=self.admin_a,
            request_intent=ExtraWorkRequestIntent.REQUEST_QUOTE,
            line_items_data=[
                {
                    "service": None,
                    "custom_description": "Ad-hoc task",
                    "quantity": Decimal("1.00"),
                    "requested_date": date(2026, 6, 15),
                    "customer_note": "",
                }
            ],
        )
        return ew

    def test_converted_ew_starts_on_the_default_labels_then_can_be_relabelled(
        self,
    ):
        """Sprint 154 §I.7 CHANGED this rule, deliberately.

        A converted Extra Work used to start UNLABELLED, and this test
        pinned that. It now starts on the customer's auto-provisioned
        "Algemeen" pair, because the owner's requirement is that every
        Extra Work carries both labels — and `extra_work.conversion`
        builds its row with `objects.create()`, so a serializer-level
        rule could never have reached it.

        What this test still guards is the part that matters and did NOT
        change: whatever a converted request starts on, the relabel
        endpoint can move it.
        """
        ew = self._convert_a_ticket()
        self.assertIsNotNone(ew.department_id)
        self.assertIsNotNone(ew.work_type_id)
        self.assertEqual(ew.department.name, "Algemeen")
        self.assertEqual(ew.work_type.name, "Algemeen")

        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id),
            {"department": self.dept_a.id, "work_type": self.wt_a.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept_a.id)
        self.assertEqual(ew.work_type_id, self.wt_a.id)


class RelabelBehaviourTests(_RelabelFixture):
    def test_set_both_labels(self):
        ew = self._bare_ew()
        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id),
            {"department": self.dept_a.id, "work_type": self.wt_a.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["department"], self.dept_a.id)
        self.assertEqual(resp.data["department_name"], "Event")
        self.assertEqual(resp.data["work_type"], self.wt_a.id)

    def test_partial_update_leaves_other_label_untouched(self):
        ew = self._bare_ew()
        ew.department = self.dept_a
        ew.work_type = self.wt_a
        ew.save(update_fields=["department", "work_type"])
        # Send only work_type=null; department must stay.
        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id), {"work_type": None}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept_a.id)
        self.assertIsNone(ew.work_type_id)

    def test_clear_to_null(self):
        ew = self._bare_ew()
        ew.department = self.dept_a
        ew.save(update_fields=["department"])
        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id), {"department": None}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        ew.refresh_from_db()
        self.assertIsNone(ew.department_id)

    def test_empty_body_rejected(self):
        ew = self._bare_ew()
        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id), {}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "no_labels_provided")

    def test_foreign_customer_label_rejected_same_code_as_create(self):
        ew = self._bare_ew()
        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id), {"department": self.dept_a2.id}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        # SAME code the create serializer emits — proves the shared validator.
        self.assertEqual(
            resp.data["department"][0].code, "department_customer_mismatch"
        )
        ew.refresh_from_db()
        self.assertIsNone(ew.department_id)

    def test_claim_flag_alone_does_not_lock_labels(self):
        # Sprint 127.2 regression for the §1 trap: `is_invoiced` is the DRAFT
        # claim flag (set at draft generation), NOT "issued". The lock keys
        # on a live ISSUED/SENT invoice line, so is_invoiced=True with no such
        # invoice must still relabel. (The invoice-driven lock is covered end
        # to end in test_sprint127_2_label_lock.py.)
        ew = self._bare_ew()
        ew.is_invoiced = True
        ew.save(update_fields=["is_invoiced"])
        resp = self._api(self.admin_a).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept_a.id)


class RelabelPermissionTests(_RelabelFixture):
    def test_super_admin_may(self):
        sa = _mk("sa-1271@example.com", UserRole.SUPER_ADMIN)
        ew = self._bare_ew()
        resp = self._api(sa).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 200)

    def test_building_manager_with_scope_may(self):
        ew = self._bare_ew()
        resp = self._api(self.bm_a).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 200)

    def test_building_manager_without_scope_cannot_relabel(self):
        # bm_other manages building_a2; this EW is on building_a1, so the
        # viewset's scope helper removes it and get_object() 404s BEFORE the
        # explicit osius building-scope check (which stays as defense in
        # depth, mirroring actual_hours). Either way the out-of-scope BM
        # cannot relabel it.
        ew = self._bare_ew(building=self.building_a1)
        resp = self._api(self.bm_other).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        ew.refresh_from_db()
        self.assertIsNone(ew.department_id)

    def test_customer_user_403(self):
        ew = self._bare_ew()
        resp = self._api(self.cust_a).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["code"], "relabel_forbidden")

    def test_staff_403(self):
        ew = self._bare_ew()
        resp = self._api(self.staff_a).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_404(self):
        # admin_b belongs to company_b; the EW is company_a's → the viewset
        # scope helper removes it, so get_object() 404s (no bespoke check).
        ew = self._bare_ew()
        resp = self._api(self.admin_b).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        self.assertEqual(resp.status_code, 404)


class RelabelAuditTests(_RelabelFixture):
    def test_relabel_writes_attributable_update_row(self):
        ew = self._bare_ew()
        self._api(self.admin_a).patch(
            _labels_url(ew.id), {"department": self.dept_a.id}, format="json"
        )
        logs = AuditLog.objects.filter(
            target_model="extra_work.ExtraWorkRequest",
            target_id=ew.id,
            action=AuditAction.UPDATE,
        )
        self.assertTrue(logs.exists())
        dept_logs = [log for log in logs if "department_id" in log.changes]
        self.assertEqual(len(dept_logs), 1)
        change = dept_logs[0].changes["department_id"]
        self.assertEqual(change["before"], None)
        self.assertEqual(change["after"], self.dept_a.id)
        self.assertEqual(dept_logs[0].actor_id, self.admin_a.id)


class BuildingManagerPickerReadTests(_RelabelFixture):
    def test_bm_with_scope_can_read_the_picker(self):
        Department.objects.create(customer=self.customer_a, name="Member")
        resp = self._api(self.bm_a).get(
            f"/api/customers/{self.customer_a.id}/departments/"
        )
        self.assertEqual(resp.status_code, 200)
        names = {row["name"] for row in resp.data["results"]}
        self.assertIn("Event", names)

    def test_bm_cannot_write_the_picker(self):
        resp = self._api(self.bm_a).post(
            f"/api/customers/{self.customer_a.id}/departments/",
            {"name": "BM should not create"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_staff_still_cannot_read_the_picker(self):
        resp = self._api(self.staff_a).get(
            f"/api/customers/{self.customer_a.id}/departments/"
        )
        self.assertEqual(resp.status_code, 403)
