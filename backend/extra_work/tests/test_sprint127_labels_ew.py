"""
Sprint 127 — the ExtraWorkRequest side of the label feature:

  * the ONE rule — a Department / Work Type assigned to an Extra Work MUST
    belong to that Extra Work's own customer — enforced by the create
    serializer (the sole EW write path) and asserted here for BOTH a
    same-company-different-customer foreign label (the pure customer rule,
    not confounded by company) and the happy path;
  * the read serializers (list + detail) expose the label id AND name to
    every viewer, customers included, and null for an untagged row;
  * the two new list filters (department / work_type, by id) compose with
    the existing customer + building filters — all four at once.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
    Department,
    WorkType,
)
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkPricingUnitType,
    ExtraWorkRequest,
    Service,
    ServiceCategory,
)

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"
URL = "/api/extra-work/"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role,
        full_name=email.split("@")[0], **extra,
    )


class _EwLabelFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-127e")
        cls.building_a1 = Building.objects.create(
            company=cls.company_a, name="A1-127e"
        )
        cls.building_a2 = Building.objects.create(
            company=cls.company_a, name="A2-127e"
        )
        # Two customers UNDER THE SAME COMPANY, so the foreign-label test
        # exercises the pure customer rule (not a company mismatch).
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A 127e"
        )
        cls.customer_a2 = Customer.objects.create(
            company=cls.company_a, name="Customer A2 127e"
        )
        for c in (cls.customer_a, cls.customer_a2):
            CustomerBuildingMembership.objects.create(
                customer=c, building=cls.building_a1
            )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a, building=cls.building_a2
        )

        cls.admin_a = _mk("admin-a-127e@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(
            user=cls.admin_a, company=cls.company_a
        )
        cls.cust_a = _mk("cust-a-127e@example.com", UserRole.CUSTOMER_USER)
        m_a = CustomerUserMembership.objects.create(
            customer=cls.customer_a, user=cls.cust_a
        )
        for b in (cls.building_a1, cls.building_a2):
            CustomerUserBuildingAccess.objects.create(
                membership=m_a,
                building=b,
                access_role=(
                    CustomerUserBuildingAccess.AccessRole.CUSTOMER_USER
                ),
            )

        cls.cat = ServiceCategory.objects.create(company=cls.company_a, name="Cleaning 127e")
        # Unpriced (no CustomerServicePrice) so carts route PROPOSAL and do
        # not spawn instant tickets — keeps these tests about the labels.
        cls.service = Service.objects.create(
            category=cls.cat,
            company=cls.company_a,
            name="Deep clean 127e",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("50.00"),
        )

        cls.dept_a = Department.objects.create(
            customer=cls.customer_a, name="Event"
        )
        cls.dept_a2 = Department.objects.create(
            customer=cls.customer_a2, name="Foreign dept"
        )
        cls.wt_a = WorkType.objects.create(
            customer=cls.customer_a, name="Eindschoonmaak"
        )
        cls.wt_a2 = WorkType.objects.create(
            customer=cls.customer_a2, name="Foreign wt"
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _payload(self, **extra):
        payload = {
            "customer": self.customer_a.id,
            "building": self.building_a1.id,
            "title": "Cart 127e",
            "description": "d",
            "category": ExtraWorkCategory.DEEP_CLEANING,
            "line_items": [
                {
                    "service": self.service.id,
                    "quantity": "1.00",
                    "requested_date": "2026-06-15",
                }
            ],
        }
        payload.update(extra)
        return payload


class SameCustomerValidatorTests(_EwLabelFixture):
    def test_own_customer_department_and_work_type_accepted(self):
        resp = self._api(self.cust_a).post(
            URL,
            self._payload(department=self.dept_a.id, work_type=self.wt_a.id),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(pk=resp.data["id"])
        self.assertEqual(ew.department_id, self.dept_a.id)
        self.assertEqual(ew.work_type_id, self.wt_a.id)

    def test_foreign_customer_department_rejected(self):
        # dept_a2 belongs to customer_a2, but the EW is for customer_a.
        resp = self._api(self.cust_a).post(
            URL, self._payload(department=self.dept_a2.id), format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["department"][0].code, "department_customer_mismatch"
        )
        self.assertFalse(
            ExtraWorkRequest.objects.filter(title="Cart 127e").exists()
        )

    def test_foreign_customer_work_type_rejected(self):
        resp = self._api(self.cust_a).post(
            URL, self._payload(work_type=self.wt_a2.id), format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["work_type"][0].code, "work_type_customer_mismatch"
        )

    def test_omitted_labels_fall_back_to_the_customer_default(self):
        """Sprint 154 §I.7 CHANGED this rule, deliberately.

        Omitting the labels used to leave them NULL, and this test pinned
        that as backward compatibility. They now resolve to the
        customer's auto-provisioned "Algemeen" pair.

        The BACKWARD-COMPATIBLE half is unchanged and still asserted: a
        client that omits both fields still gets a 201. What changed is
        what it gets back — a labelled request instead of an unlabelled
        one. That is the point: the owner's rule is that every Extra Work
        carries both labels, and filling the gap here is what makes it
        true on every write path rather than only on the form's.
        """
        resp = self._api(self.cust_a).post(URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        ew = ExtraWorkRequest.objects.get(pk=resp.data["id"])
        self.assertIsNotNone(ew.department_id)
        self.assertIsNotNone(ew.work_type_id)
        self.assertEqual(ew.department.name, "Algemeen")
        self.assertEqual(ew.work_type.name, "Algemeen")


class ReadSerializerLabelTests(_EwLabelFixture):
    def _ew(self, **extra):
        return ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=self.building_a1,
            customer=self.customer_a,
            created_by=self.cust_a,
            title="EW read 127e",
            description="d",
            **extra,
        )

    def test_detail_exposes_id_and_name(self):
        ew = self._ew(department=self.dept_a, work_type=self.wt_a)
        resp = self._api(self.admin_a).get(f"{URL}{ew.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["department"], self.dept_a.id)
        self.assertEqual(resp.data["department_name"], "Event")
        self.assertEqual(resp.data["work_type"], self.wt_a.id)
        self.assertEqual(resp.data["work_type_name"], "Eindschoonmaak")

    def test_untagged_row_reports_null(self):
        ew = self._ew()
        resp = self._api(self.admin_a).get(f"{URL}{ew.id}/")
        self.assertIsNone(resp.data["department"])
        self.assertIsNone(resp.data["department_name"])
        self.assertIsNone(resp.data["work_type_name"])

    def test_customer_sees_the_label(self):
        ew = self._ew(department=self.dept_a)
        resp = self._api(self.cust_a).get(f"{URL}{ew.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["department_name"], "Event")

    def test_list_serializer_carries_name(self):
        self._ew(department=self.dept_a)
        resp = self._api(self.admin_a).get(URL, {"customer": self.customer_a.id})
        self.assertEqual(resp.status_code, 200)
        row = next(
            r for r in resp.data["results"] if r["department"] == self.dept_a.id
        )
        self.assertEqual(row["department_name"], "Event")


class LabelFilterCompositionTests(_EwLabelFixture):
    def _ew(self, building, **extra):
        return ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=building,
            customer=self.customer_a,
            created_by=self.cust_a,
            title="EW filter 127e",
            description="d",
            **extra,
        )

    def setUp(self):
        # b1: dept_a + wt_a ; b1: dept_a only ; b2: wt_a only ; b1: untagged
        self.ew_both = self._ew(
            self.building_a1, department=self.dept_a, work_type=self.wt_a
        )
        self.ew_dept = self._ew(self.building_a1, department=self.dept_a)
        self.ew_wt = self._ew(self.building_a2, work_type=self.wt_a)
        self.ew_bare = self._ew(self.building_a1)

    def _ids(self, resp):
        return {r["id"] for r in resp.data["results"]}

    def test_filter_by_department(self):
        resp = self._api(self.admin_a).get(
            URL, {"department": self.dept_a.id}
        )
        self.assertEqual(self._ids(resp), {self.ew_both.id, self.ew_dept.id})

    def test_filter_by_work_type(self):
        resp = self._api(self.admin_a).get(URL, {"work_type": self.wt_a.id})
        self.assertEqual(self._ids(resp), {self.ew_both.id, self.ew_wt.id})

    def test_all_four_filters_compose(self):
        resp = self._api(self.admin_a).get(
            URL,
            {
                "customer": self.customer_a.id,
                "building": self.building_a1.id,
                "department": self.dept_a.id,
                "work_type": self.wt_a.id,
            },
        )
        # Only ew_both is on building_a1 AND carries both labels.
        self.assertEqual(self._ids(resp), {self.ew_both.id})
