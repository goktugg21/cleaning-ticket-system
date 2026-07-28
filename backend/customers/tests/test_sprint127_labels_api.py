"""
Sprint 127 — per-customer Extra Work label lists (Department + WorkType):
customer-scoped CRUD API, case/whitespace-insensitive per-customer
uniqueness (DB-level, not only the friendly serializer pre-check),
provider-write / customer-read permission split, cross-tenant isolation,
the PROTECT-on-delete-while-in-use → coded 400 → is_active soft-retire
path, and audit-on-rename (a relabel must be attributable).

Department is exercised in full; WorkType shares one abstract base and one
view mixin, so it gets a parity smoke class rather than a full re-run.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
    Department,
    WorkType,
)
from extra_work.models import ExtraWorkRequest

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


def _dept_url(cid):
    return f"/api/customers/{cid}/departments/"


def _dept_detail_url(cid, lid):
    return f"/api/customers/{cid}/departments/{lid}/"


def _wt_url(cid):
    return f"/api/customers/{cid}/work-types/"


def _wt_detail_url(cid, lid):
    return f"/api/customers/{cid}/work-types/{lid}/"


class _LabelFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-127")
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-127")
        cls.building_a1 = Building.objects.create(
            company=cls.company_a, name="A1-127"
        )
        cls.sa = _mk("sa-127@example.com", UserRole.SUPER_ADMIN)
        cls.ca_a = _mk("ca-a-127@example.com", UserRole.COMPANY_ADMIN)
        cls.ca_b = _mk("ca-b-127@example.com", UserRole.COMPANY_ADMIN)
        cls.staff_a = _mk("staff-a-127@example.com", UserRole.STAFF)
        CompanyUserMembership.objects.create(user=cls.ca_a, company=cls.company_a)
        CompanyUserMembership.objects.create(user=cls.ca_b, company=cls.company_b)

        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A 127"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B 127"
        )

        # Customer user WITH active access to customer_a (read the picker).
        cls.cust_a = _mk("cust-a-127@example.com", UserRole.CUSTOMER_USER)
        m_a = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_a
        )
        CustomerUserBuildingAccess.objects.create(
            membership=m_a,
            building=cls.building_a1,
            access_role=CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER,
        )
        # Customer user with access to customer_b only (probes customer_a).
        cls.cust_b = _mk("cust-b-127@example.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            customer=cls.customer_b, user=cls.cust_b, is_company_admin=True
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class LabelCrudTests(_LabelFixture):
    def test_ca_creates_department_for_own_customer(self):
        resp = self._api(self.ca_a).post(
            _dept_url(self.customer_a.id), {"name": "Event"}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["name"], "Event")
        self.assertTrue(resp.data["is_active"])
        # customer is stamped from the URL, never echoed as a writable field.
        self.assertNotIn("customer", resp.data)
        dept = Department.objects.get(pk=resp.data["id"])
        self.assertEqual(dept.customer_id, self.customer_a.id)

    def test_sa_creates_for_any_customer(self):
        resp = self._api(self.sa).post(
            _dept_url(self.customer_b.id), {"name": "Algemeen"}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            Department.objects.get(pk=resp.data["id"]).customer_id,
            self.customer_b.id,
        )

    def test_name_is_trimmed_on_write(self):
        resp = self._api(self.ca_a).post(
            _dept_url(self.customer_a.id), {"name": "  Member  "}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["name"], "Member")

    def test_blank_name_rejected(self):
        resp = self._api(self.ca_a).post(
            _dept_url(self.customer_a.id), {"name": "   "}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["name"][0].code, "label_name_required")

    def test_list_scoped_to_url_customer_only(self):
        Department.objects.create(customer=self.customer_a, name="Event")
        Department.objects.create(customer=self.customer_b, name="Foreign")
        resp = self._api(self.ca_a).get(_dept_url(self.customer_a.id))
        self.assertEqual(resp.status_code, 200)
        names = {row["name"] for row in resp.data["results"]}
        self.assertEqual(names, {"Event"})

    def test_is_active_filter(self):
        Department.objects.create(customer=self.customer_a, name="Active")
        Department.objects.create(
            customer=self.customer_a, name="Archived", is_active=False
        )
        resp = self._api(self.ca_a).get(
            _dept_url(self.customer_a.id), {"is_active": "true"}
        )
        names = {row["name"] for row in resp.data["results"]}
        self.assertEqual(names, {"Active"})

    def test_rename_department(self):
        dept = Department.objects.create(customer=self.customer_a, name="Evenement")
        resp = self._api(self.ca_a).patch(
            _dept_detail_url(self.customer_a.id, dept.id),
            {"name": "Event"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["name"], "Event")

    def test_archive_and_reactivate(self):
        dept = Department.objects.create(customer=self.customer_a, name="Event")
        url = _dept_detail_url(self.customer_a.id, dept.id)
        resp = self._api(self.ca_a).patch(url, {"is_active": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_active"])
        resp = self._api(self.ca_a).patch(url, {"is_active": True}, format="json")
        self.assertTrue(resp.data["is_active"])

    def test_delete_unused_department_succeeds(self):
        dept = Department.objects.create(customer=self.customer_a, name="Unused")
        resp = self._api(self.ca_a).delete(
            _dept_detail_url(self.customer_a.id, dept.id)
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Department.objects.filter(pk=dept.pk).exists())


class LabelUniquenessTests(_LabelFixture):
    def test_case_and_whitespace_variant_rejected(self):
        self._api(self.ca_a).post(
            _dept_url(self.customer_a.id), {"name": "Event"}, format="json"
        )
        for variant in ("event", "EVENT", " Event", "Event ", "  event  "):
            resp = self._api(self.ca_a).post(
                _dept_url(self.customer_a.id), {"name": variant}, format="json"
            )
            self.assertEqual(
                resp.status_code, 400, f"variant {variant!r} should collide"
            )
            self.assertEqual(
                resp.data["name"][0].code, "department_name_conflict"
            )

    def test_same_name_allowed_in_different_customers(self):
        r_a = self._api(self.ca_a).post(
            _dept_url(self.customer_a.id), {"name": "Event"}, format="json"
        )
        r_b = self._api(self.sa).post(
            _dept_url(self.customer_b.id), {"name": "event"}, format="json"
        )
        self.assertEqual(r_a.status_code, 201)
        self.assertEqual(r_b.status_code, 201)

    def test_department_and_work_type_may_share_a_name(self):
        # Two separate tables: "Event" is a valid Department AND a valid
        # WorkType for the same customer, no cross-list collision.
        r_d = self._api(self.ca_a).post(
            _dept_url(self.customer_a.id), {"name": "Event"}, format="json"
        )
        r_w = self._api(self.ca_a).post(
            _wt_url(self.customer_a.id), {"name": "Event"}, format="json"
        )
        self.assertEqual(r_d.status_code, 201)
        self.assertEqual(r_w.status_code, 201)

    def test_db_constraint_is_the_real_backstop(self):
        Department.objects.create(customer=self.customer_a, name="Event")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Department.objects.create(
                    customer=self.customer_a, name="  event  "
                )
        self.assertEqual(
            Department.objects.filter(customer=self.customer_a).count(), 1
        )

    def test_rename_into_a_collision_rejected(self):
        Department.objects.create(customer=self.customer_a, name="Event")
        other = Department.objects.create(customer=self.customer_a, name="Member")
        resp = self._api(self.ca_a).patch(
            _dept_detail_url(self.customer_a.id, other.id),
            {"name": "event"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["name"][0].code, "department_name_conflict")

    def test_rename_to_own_name_is_not_a_self_collision(self):
        dept = Department.objects.create(customer=self.customer_a, name="Event")
        resp = self._api(self.ca_a).patch(
            _dept_detail_url(self.customer_a.id, dept.id),
            {"name": "Event", "is_active": False}, format="json",
        )
        self.assertEqual(resp.status_code, 200)


class LabelPermissionTests(_LabelFixture):
    def test_customer_user_with_access_may_read(self):
        Department.objects.create(customer=self.customer_a, name="Event")
        resp = self._api(self.cust_a).get(_dept_url(self.customer_a.id))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_customer_user_may_not_write(self):
        dept = Department.objects.create(customer=self.customer_a, name="Event")
        cid = self.customer_a.id
        self.assertEqual(
            self._api(self.cust_a).post(
                _dept_url(cid), {"name": "New"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self._api(self.cust_a).patch(
                _dept_detail_url(cid, dept.id), {"name": "X"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self._api(self.cust_a).delete(
                _dept_detail_url(cid, dept.id)
            ).status_code,
            403,
        )
        dept.refresh_from_db()
        self.assertEqual(dept.name, "Event")

    def test_staff_forbidden_read_and_write(self):
        resp = self._api(self.staff_a).get(_dept_url(self.customer_a.id))
        self.assertEqual(resp.status_code, 403)
        resp = self._api(self.staff_a).post(
            _dept_url(self.customer_a.id), {"name": "X"}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_customer_user_without_access_may_not_read(self):
        # cust_b belongs to customer_b; probing customer_a's picker → 403.
        Department.objects.create(customer=self.customer_a, name="Event")
        resp = self._api(self.cust_b).get(_dept_url(self.customer_a.id))
        self.assertEqual(resp.status_code, 403)


class LabelCrossTenantTests(_LabelFixture):
    def setUp(self):
        self.dept_a = Department.objects.create(
            customer=self.customer_a, name="Event"
        )

    def test_foreign_ca_cannot_read_list(self):
        # ca_b acting on customer_a (a foreign company's customer) → 403.
        resp = self._api(self.ca_b).get(_dept_url(self.customer_a.id))
        self.assertEqual(resp.status_code, 403)

    def test_foreign_ca_cannot_read_detail(self):
        resp = self._api(self.ca_b).get(
            _dept_detail_url(self.customer_a.id, self.dept_a.id)
        )
        self.assertEqual(resp.status_code, 403)

    def test_foreign_ca_cannot_rename(self):
        resp = self._api(self.ca_b).patch(
            _dept_detail_url(self.customer_a.id, self.dept_a.id),
            {"name": "hijacked"}, format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.dept_a.refresh_from_db()
        self.assertEqual(self.dept_a.name, "Event")

    def test_foreign_ca_cannot_delete(self):
        resp = self._api(self.ca_b).delete(
            _dept_detail_url(self.customer_a.id, self.dept_a.id)
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Department.objects.filter(pk=self.dept_a.pk).exists())

    def test_label_id_from_another_customer_is_404(self):
        # A department that exists, but under customer_b, is invisible under
        # customer_a's URL scope (queryset filters to the URL customer).
        dept_b = Department.objects.create(
            customer=self.customer_b, name="Foreign"
        )
        resp = self._api(self.sa).get(
            _dept_detail_url(self.customer_a.id, dept_b.id)
        )
        self.assertEqual(resp.status_code, 404)


class LabelDeleteProtectTests(_LabelFixture):
    def _ew_tagged_with(self, *, department=None, work_type=None):
        return ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=self.building_a1,
            customer=self.customer_a,
            created_by=self.cust_a,
            title="Tagged EW",
            description="d",
            department=department,
            work_type=work_type,
        )

    def test_delete_in_use_department_rejected_with_coded_400(self):
        dept = Department.objects.create(customer=self.customer_a, name="Event")
        self._ew_tagged_with(department=dept)
        resp = self._api(self.ca_a).delete(
            _dept_detail_url(self.customer_a.id, dept.id)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "department_protected")
        self.assertTrue(Department.objects.filter(pk=dept.pk).exists())

    def test_soft_retire_is_the_offered_path(self):
        dept = Department.objects.create(customer=self.customer_a, name="Event")
        self._ew_tagged_with(department=dept)
        # The delete is refused, but archiving never touches the FK.
        resp = self._api(self.ca_a).patch(
            _dept_detail_url(self.customer_a.id, dept.id),
            {"is_active": False}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_active"])

    def test_delete_in_use_work_type_rejected_with_coded_400(self):
        wt = WorkType.objects.create(customer=self.customer_a, name="Eindschoonmaak")
        self._ew_tagged_with(work_type=wt)
        resp = self._api(self.ca_a).delete(
            _wt_detail_url(self.customer_a.id, wt.id)
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "work_type_protected")


class LabelAuditTests(_LabelFixture):
    def test_rename_writes_attributable_audit_log(self):
        dept = Department.objects.create(customer=self.customer_a, name="Evenement")
        self._api(self.ca_a).patch(
            _dept_detail_url(self.customer_a.id, dept.id),
            {"name": "Event"}, format="json",
        )
        logs = AuditLog.objects.filter(
            target_model="customers.Department",
            target_id=dept.id,
            action=AuditAction.UPDATE,
        )
        self.assertTrue(logs.exists())
        name_logs = [log for log in logs if "name" in log.changes]
        self.assertEqual(len(name_logs), 1)
        self.assertEqual(name_logs[0].actor_id, self.ca_a.id)


class WorkTypeParityTests(_LabelFixture):
    """WorkType shares the base + view mixin with Department; a focused
    parity pass proves its own endpoints are wired, not a copy of the
    Department suite."""

    def test_crud_happy_path(self):
        resp = self._api(self.ca_a).post(
            _wt_url(self.customer_a.id),
            {"name": "Opleverschoonmaak"}, format="json",
        )
        self.assertEqual(resp.status_code, 201)
        wt_id = resp.data["id"]
        self.assertEqual(
            WorkType.objects.get(pk=wt_id).customer_id, self.customer_a.id
        )
        resp = self._api(self.ca_a).get(_wt_url(self.customer_a.id))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_work_type_list_scoped_to_customer(self):
        WorkType.objects.create(customer=self.customer_a, name="Mine")
        WorkType.objects.create(customer=self.customer_b, name="Theirs")
        resp = self._api(self.ca_a).get(_wt_url(self.customer_a.id))
        names = {row["name"] for row in resp.data["results"]}
        self.assertEqual(names, {"Mine"})
