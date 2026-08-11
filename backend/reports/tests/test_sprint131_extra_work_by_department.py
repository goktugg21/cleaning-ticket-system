"""
Sprint 131 — Extra Work revenue grouped Building -> Department -> Work
Type.

`compute_extra_work_by_department` shares `_resolve_extra_work_revenue_rows`
(scope/customer/date-window resolution + the in-scope ExtraWorkRequest
queryset + ticket map) and the per-row `_classify_extra_work` /
`_amounts_for_state` functions with the flat `compute_extra_work_revenue`
AND Sprint 124's `compute_extra_work_revenue_by_building` — one level
deeper (department, then work type). The tests below exist to PROVE the
sharing actually holds, the way `test_sprint124_revenue_by_building.py`
does for the by-building report — with the added twist that Sprint 131
must not silently drop untagged (department=None / work_type=None) rows,
which is every pre-Sprint-127 row in the system.

Reuses the TenantFixtureMixin + `_ew` / `_spawn` fixture-builder
conventions from test_sprint124_revenue_by_building.py.
"""
import datetime
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building
from customers.models import CustomerBuildingMembership, Department, WorkType
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType

URL_REVENUE = "/api/reports/extra-work-revenue/"
URL_DEPT = "/api/reports/extra-work-by-department/"
URL_DEPT_CSV = "/api/reports/extra-work-by-department/export.csv"
URL_DEPT_PDF = "/api/reports/extra-work-by-department/export.pdf"


class _DeptReportBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.building_2 = Building.objects.create(
            company=self.company, name="Building A-2", address="Second Street 1"
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.building_2
        )
        # Sprint 154 §I.7 auto-provisions an "Algemeen" Department on every
        # customer, so creating a second one violates
        # `uniq_customers_department_name_per_customer_ci` and takes the whole
        # class down in setUp. Reuse the provisioned row — this test is about
        # the department REPORT, not about who created the label.
        #
        # Sprint 154 fixed seven tests in
        # `customers.tests.test_sprint127_labels_api` the same way; this module
        # was missed because `reports` was not in that sprint's gate list, and
        # it has been failing silently ever since.
        self.dept_general, _ = Department.objects.get_or_create(
            customer=self.customer, name="Algemeen"
        )
        self.dept_event = Department.objects.create(
            customer=self.customer, name="Event"
        )
        self.wt_clean = WorkType.objects.create(
            customer=self.customer, name="Eindschoonmaak"
        )
        self.wt_repair = WorkType.objects.create(
            customer=self.customer, name="Reparatie"
        )

    def _ew(
        self,
        company,
        building,
        customer,
        *,
        subtotal,
        vat,
        total,
        final_subtotal=None,
        final_vat=None,
        final_total=None,
        ew_status=ExtraWorkStatus.REQUESTED,
        department=None,
        work_type=None,
        title="EW",
    ):
        return ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=self.super_admin,
            title=title,
            description="d",
            department=department,
            work_type=work_type,
            subtotal_amount=Decimal(subtotal),
            vat_amount=Decimal(vat),
            total_amount=Decimal(total),
            final_subtotal_amount=(
                Decimal(final_subtotal) if final_subtotal is not None else None
            ),
            final_vat_amount=(
                Decimal(final_vat) if final_vat is not None else None
            ),
            final_total_amount=(
                Decimal(final_total) if final_total is not None else None
            ),
            status=ew_status,
        )

    def _spawn(self, ew, ticket_status, closed_at=None):
        ticket = Ticket.objects.create(
            company=ew.company,
            building=ew.building,
            customer=ew.customer,
            created_by=self.super_admin,
            title="EW spawned",
            description="d",
            type=TicketType.REQUEST,
            extra_work_request=ew,
        )
        updates = {"status": ticket_status}
        if closed_at is not None:
            updates["closed_at"] = closed_at
        Ticket.objects.filter(pk=ticket.pk).update(**updates)
        ticket.refresh_from_db()
        return ticket

    def _earned(
        self,
        building,
        customer,
        total,
        *,
        department=None,
        work_type=None,
        title="EW",
        closed_at=None,
        company=None,
    ):
        ew = self._ew(
            company or self.company,
            building,
            customer,
            subtotal=total,
            vat="0.00",
            total=total,
            final_subtotal=total,
            final_vat="0.00",
            final_total=total,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            department=department,
            work_type=work_type,
            title=title,
        )
        self._spawn(ew, TicketStatus.CLOSED, closed_at=closed_at)
        return ew

    def _leaf_buckets(self, response_data):
        """Flatten the buildings->departments->work_types tree into one
        dict per leaf bucket, for assertions that don't care about nesting."""
        out = []
        for building in response_data["buildings"]:
            for dept in building["departments"]:
                for wt in dept["work_types"]:
                    out.append(
                        {
                            "building_id": building["building_id"],
                            "department_id": dept["department_id"],
                            "work_type_id": wt["work_type_id"],
                            "count": wt["count"],
                            "total": wt["total"],
                            "rows": wt["rows"],
                        }
                    )
        return out


class ExtraWorkByDepartmentPermissionTests(_DeptReportBase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL_DEPT)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_DEPT)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_returns_403_commercial(self):
        staff = self.make_user("staff-131@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        response = self.client.get(URL_DEPT)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ExtraWorkByDepartmentSumInvariantTests(_DeptReportBase):
    """The core invariant: leaf (building x department x work_type) buckets
    sum to the flat total, for the SAME filters — WITH untagged rows in
    the mix, since every pre-Sprint-127 row has department=work_type=None
    and must not be silently dropped from the sum."""

    def setUp(self):
        super().setUp()
        # Tagged, earned.
        self._earned(
            self.building,
            self.customer,
            "100.00",
            department=self.dept_general,
            work_type=self.wt_clean,
        )
        # Tagged, different department/work_type, second building.
        self._earned(
            self.building_2,
            self.customer,
            "40.00",
            department=self.dept_event,
            work_type=self.wt_repair,
        )
        # UNTAGGED, earned — the case every legacy row hits today.
        self._earned(self.building, self.customer, "25.00")
        # in_progress: spawned ticket exists, not terminal. Untagged.
        ew_ip = self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="50.00",
            vat="0.00",
            total="50.00",
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self._spawn(ew_ip, TicketStatus.IN_PROGRESS)
        # quoted_pipeline: no spawned ticket, still requested. Tagged.
        self._ew(
            self.company,
            self.building_2,
            self.customer,
            subtotal="30.00",
            vat="0.00",
            total="30.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
            department=self.dept_general,
        )
        # lost: no spawned ticket, customer rejected. Untagged.
        self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="20.00",
            vat="0.00",
            total="20.00",
            ew_status=ExtraWorkStatus.CUSTOMER_REJECTED,
        )
        # A second customer's EW on the SAME building — must not bleed in.
        from customers.models import Customer

        self.customer_two = Customer.objects.create(
            company=self.company, name="Customer A-2", building=self.building
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer_two, building=self.building
        )
        self._earned(self.building, self.customer_two, "999.00")

    def test_leaf_buckets_sum_to_flat_total(self):
        self.client.force_authenticate(user=self.super_admin)
        params = {
            "customer": self.customer.id,
            "from": "2020-01-01",
            "to": "2035-01-01",
        }

        flat = self.client.get(URL_REVENUE, params)
        by_dept = self.client.get(URL_DEPT, params)

        self.assertEqual(flat.status_code, status.HTTP_200_OK)
        self.assertEqual(by_dept.status_code, status.HTTP_200_OK)

        flat_total = Decimal(flat.data["totals"]["total"])
        leaves = self._leaf_buckets(by_dept.data)
        bucket_sum = sum((Decimal(leaf["total"]) for leaf in leaves), Decimal("0.00"))

        self.assertEqual(bucket_sum, flat_total)
        self.assertEqual(Decimal(by_dept.data["totals"]["total"]), flat_total)
        # 100 + 25 + 50 + 20 (building) + 40 + 30 (building_2); customer_two's
        # 999.00 is excluded. The 20.00 LOST row IS counted (mirrors the
        # by-building invariant test), same as the flat report.
        self.assertEqual(flat_total, Decimal("265.00"))

    def test_untagged_bucket_is_not_dropped(self):
        self.client.force_authenticate(user=self.super_admin)
        params = {"customer": self.customer.id}
        response = self.client.get(URL_DEPT, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        leaves = self._leaf_buckets(response.data)
        untagged = [
            leaf
            for leaf in leaves
            if leaf["department_id"] is None and leaf["work_type_id"] is None
        ]
        self.assertTrue(untagged, "the untagged bucket must still appear")
        untagged_total = sum(
            (Decimal(leaf["total"]) for leaf in untagged), Decimal("0.00")
        )
        # 25.00 (earned) + 50.00 (in_progress) + 20.00 (lost), all untagged.
        self.assertEqual(untagged_total, Decimal("95.00"))

    def test_buckets_sum_to_flat_total_billing_period_mode(self):
        month = "2026-03"
        Ticket.objects.filter(
            extra_work_request__customer=self.customer
        ).update(
            closed_at=datetime.datetime(2026, 3, 15, tzinfo=datetime.timezone.utc)
        )

        self.client.force_authenticate(user=self.super_admin)
        params = {"customer": self.customer.id, "billing_period": month}

        flat = self.client.get(URL_REVENUE, params)
        by_dept = self.client.get(URL_DEPT, params)

        self.assertEqual(flat.status_code, status.HTTP_200_OK)
        self.assertEqual(by_dept.status_code, status.HTTP_200_OK)

        flat_total = Decimal(flat.data["totals"]["total"])
        leaves = self._leaf_buckets(by_dept.data)
        bucket_sum = sum((Decimal(leaf["total"]) for leaf in leaves), Decimal("0.00"))
        self.assertEqual(bucket_sum, flat_total)


class ExtraWorkByDepartmentDetailRowTests(_DeptReportBase):
    def test_completed_at_and_week_no_populated_only_for_earned(self):
        self._earned(
            self.building,
            self.customer,
            "100.00",
            department=self.dept_general,
            work_type=self.wt_clean,
            title="Earned job",
            closed_at=datetime.datetime(2026, 6, 30, 10, 0, tzinfo=datetime.timezone.utc),
        )
        ew_ip = self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="50.00",
            vat="0.00",
            total="50.00",
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            department=self.dept_general,
            work_type=self.wt_clean,
            title="In progress job",
        )
        self._spawn(ew_ip, TicketStatus.IN_PROGRESS)

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        leaves = self._leaf_buckets(response.data)
        clean_leaf = next(
            leaf for leaf in leaves if leaf["work_type_id"] == self.wt_clean.id
        )
        rows_by_title = {r["title"]: r for r in clean_leaf["rows"]}

        earned_row = rows_by_title["Earned job"]
        self.assertEqual(earned_row["state"], "earned")
        self.assertEqual(earned_row["completed_at"], "2026-06-30")
        # ISO week of 2026-06-30 is 27 (verified against the reference
        # report's own WK27 for both 30-06 and 01-07).
        self.assertEqual(earned_row["week_no"], 27)

        in_progress_row = rows_by_title["In progress job"]
        self.assertEqual(in_progress_row["state"], "in_progress")
        self.assertIsNone(in_progress_row["completed_at"])
        self.assertIsNone(in_progress_row["week_no"])

    def test_excl_vat_column_is_subtotal_not_total(self):
        self._earned(
            self.building,
            self.customer,
            "121.00",  # total incl. VAT
            department=self.dept_general,
            work_type=self.wt_clean,
            title="Priced job",
        )
        ew = ExtraWorkRequest.objects.get(title="Priced job")
        ew.final_subtotal_amount = Decimal("100.00")
        ew.final_vat_amount = Decimal("21.00")
        ew.final_total_amount = Decimal("121.00")
        ew.save(update_fields=[
            "final_subtotal_amount", "final_vat_amount", "final_total_amount",
        ])

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT, {"customer": self.customer.id})
        leaves = self._leaf_buckets(response.data)
        clean_leaf = next(
            leaf for leaf in leaves if leaf["work_type_id"] == self.wt_clean.id
        )
        row = clean_leaf["rows"][0]
        self.assertEqual(row["subtotal"], "100.00")
        self.assertEqual(row["total"], "121.00")


class ExtraWorkByDepartmentOrderingTests(_DeptReportBase):
    def test_alphabetical_ordering_untagged_last(self):
        # Departments created out of alpha order on purpose.
        dept_z = Department.objects.create(customer=self.customer, name="Zzz Dept")
        self._earned(self.building, self.customer, "10.00", department=dept_z)
        self._earned(
            self.building, self.customer, "10.00", department=self.dept_general
        )
        self._earned(self.building, self.customer, "10.00")  # untagged

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        building = response.data["buildings"][0]
        dept_names = [d["department_name"] for d in building["departments"]]
        self.assertEqual(dept_names, ["Algemeen", "Zzz Dept", None])

    def test_buildings_ordered_alphabetically(self):
        self._earned(self.building_2, self.customer, "10.00")
        self._earned(self.building, self.customer, "10.00")

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT, {"customer": self.customer.id})
        names = [b["building_name"] for b in response.data["buildings"]]
        self.assertEqual(names, sorted(names))


class ExtraWorkByDepartmentFilterTests(_DeptReportBase):
    def test_department_filter_narrows_results(self):
        self._earned(
            self.building, self.customer, "10.00", department=self.dept_general
        )
        self._earned(
            self.building, self.customer, "20.00", department=self.dept_event
        )

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL_DEPT,
            {"customer": self.customer.id, "department": self.dept_general.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        leaves = self._leaf_buckets(response.data)
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["department_id"], self.dept_general.id)
        self.assertEqual(response.data["scope"]["department_id"], self.dept_general.id)
        self.assertEqual(
            response.data["scope"]["department_name"], self.dept_general.name
        )

    def test_work_type_filter_narrows_results(self):
        self._earned(self.building, self.customer, "10.00", work_type=self.wt_clean)
        self._earned(self.building, self.customer, "20.00", work_type=self.wt_repair)

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL_DEPT,
            {"customer": self.customer.id, "work_type": self.wt_repair.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        leaves = self._leaf_buckets(response.data)
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["work_type_id"], self.wt_repair.id)


class ExtraWorkByDepartmentCrossTenantTests(_DeptReportBase):
    def test_out_of_scope_customer_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_DEPT, {"customer": self.other_customer.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_building_param_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_DEPT, {"building": self.other_building.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_company_admin_never_sees_other_company_building(self):
        self._earned(self.building, self.customer, "100.00")
        self._earned(
            self.other_building,
            self.other_customer,
            "500.00",
            company=self.other_company,
        )
        self.client.force_authenticate(user=self.company_admin)

        response = self.client.get(URL_DEPT)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seen_ids = {b["building_id"] for b in response.data["buildings"]}
        self.assertIn(self.building.id, seen_ids)
        self.assertNotIn(self.other_building.id, seen_ids)

    def test_manager_scoped_to_own_building_only(self):
        self._earned(self.building, self.customer, "100.00")
        self._earned(self.building_2, self.customer, "40.00")
        self.client.force_authenticate(user=self.manager)

        response = self.client.get(URL_DEPT)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seen_ids = {b["building_id"] for b in response.data["buildings"]}
        self.assertEqual(seen_ids, {self.building.id})
        self.assertEqual(response.data["totals"]["total"], "100.00")

    def test_department_filter_from_other_tenant_does_not_leak_name(self):
        # A department belonging to a customer this company_admin cannot
        # see at all. The row filter already returns nothing for it (no
        # EW in this actor's scope can reference a foreign customer's
        # department — the write-side invariant ties a label to its own
        # customer); this test is about the SCOPE ECHO, which used to do
        # an unscoped lookup and leak the label's real name regardless.
        secret_dept = Department.objects.create(
            customer=self.other_customer, name="Other Co Secret Department"
        )
        self._earned(self.building, self.customer, "10.00")
        self.client.force_authenticate(user=self.company_admin)

        response = self.client.get(URL_DEPT, {"department": secret_dept.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["buildings"], [])
        # The id is just an echo of the caller's own input — harmless.
        self.assertEqual(response.data["scope"]["department_id"], secret_dept.id)
        # The NAME must not leak.
        self.assertIsNone(response.data["scope"]["department_name"])

    def test_work_type_filter_from_other_tenant_does_not_leak_name(self):
        secret_wt = WorkType.objects.create(
            customer=self.other_customer, name="Other Co Secret Work Type"
        )
        self._earned(self.building, self.customer, "10.00")
        self.client.force_authenticate(user=self.company_admin)

        response = self.client.get(URL_DEPT, {"work_type": secret_wt.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["buildings"], [])
        self.assertEqual(response.data["scope"]["work_type_id"], secret_wt.id)
        self.assertIsNone(response.data["scope"]["work_type_name"])

    def test_super_admin_still_sees_cross_company_label_names(self):
        # Guards against overtightening: SUPER_ADMIN has genuine global
        # scope, so the same cross-company department/work_type MUST
        # resolve its real name for them, unlike the company_admin tests
        # above.
        dept = Department.objects.create(
            customer=self.other_customer, name="Cross-Company Department"
        )
        wt = WorkType.objects.create(
            customer=self.other_customer, name="Cross-Company Work Type"
        )
        self.client.force_authenticate(user=self.super_admin)

        dept_response = self.client.get(URL_DEPT, {"department": dept.id})
        self.assertEqual(
            dept_response.data["scope"]["department_name"], "Cross-Company Department"
        )
        wt_response = self.client.get(URL_DEPT, {"work_type": wt.id})
        self.assertEqual(
            wt_response.data["scope"]["work_type_name"], "Cross-Company Work Type"
        )


class ExtraWorkByDepartmentExportTests(_DeptReportBase):
    EXPECTED_CSV_HEADERS = [
        "building_id",
        "building_name",
        "company_id",
        "company_name",
        "department_id",
        "department_name",
        "work_type_id",
        "work_type_name",
        "count",
        "subtotal",
        "vat",
        "total",
        "period_from",
        "period_to",
    ]

    def setUp(self):
        super().setUp()
        self._earned(
            self.building,
            self.customer,
            "100.00",
            department=self.dept_general,
            work_type=self.wt_clean,
            title="Clean job",
        )
        self._earned(self.building_2, self.customer, "40.00")

    def _csv_rows(self, response):
        import csv
        import io

        text = response.content.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text))
        return reader.fieldnames, list(reader)

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT_CSV, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("extra-work-by-department", response["Content-Disposition"])
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_CSV_HEADERS)
        self.assertEqual(len(rows), 2)
        totals = {r["building_id"]: r["total"] for r in rows}
        self.assertEqual(totals[str(self.building.id)], "100.00")
        self.assertEqual(totals[str(self.building_2.id)], "40.00")

    def test_csv_staff_returns_403(self):
        staff = self.make_user("staff-131-csv@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        response = self.client.get(URL_DEPT_CSV)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_pdf_export(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT_PDF, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_export_empty_result(self):
        # No EW at all in this window — the "Geen resultaten" branch.
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(
            URL_DEPT_PDF,
            {"customer": self.customer.id, "from": "2000-01-01", "to": "2000-01-31"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content.startswith(b"%PDF"))


class ExtraWorkByDepartmentZeroTests(_DeptReportBase):
    def test_building_with_no_revenue_is_omitted(self):
        self._earned(self.building, self.customer, "100.00")
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.get(URL_DEPT, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        seen_ids = {b["building_id"] for b in response.data["buildings"]}
        self.assertEqual(seen_ids, {self.building.id})
        self.assertNotIn(self.building_2.id, seen_ids)
        self.assertEqual(len(response.data["buildings"]), 1)

    def test_department_with_no_revenue_is_omitted(self):
        # dept_event exists as a label but is never used on any EW.
        self._earned(
            self.building, self.customer, "100.00", department=self.dept_general
        )
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.get(URL_DEPT, {"customer": self.customer.id})
        building = response.data["buildings"][0]
        dept_ids = {d["department_id"] for d in building["departments"]}
        self.assertEqual(dept_ids, {self.dept_general.id})


class ExtraWorkByDepartmentPDFPaginationTests(_DeptReportBase):
    """A work type with enough rows to outrun one page must repeat its
    column header + a "(vervolg)" context line on the continuation page —
    otherwise a reader who opens straight to that page sees bare numbered
    rows with no idea which department/work type or columns they are
    looking at. ~40 rows fit on one A4 detail page at 6mm/row; 50 forces
    at least one break without making the test slow."""

    def setUp(self):
        super().setUp()
        for i in range(50):
            self._earned(
                self.building,
                self.customer,
                "10.00",
                department=self.dept_general,
                work_type=self.wt_clean,
                title=f"Row {i}",
            )

    def test_header_and_context_repeat_on_page_break(self):
        from io import BytesIO

        from pypdf import PdfReader

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT_PDF, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        reader = PdfReader(BytesIO(response.content))
        # 1 summary page + at least 2 detail pages (50 rows > ~40/page).
        self.assertGreaterEqual(len(reader.pages), 3)

        detail_text = "\n".join(p.extract_text() for p in reader.pages[1:])
        self.assertIn("(vervolg)", detail_text)
        # The column header must appear more than once — once per detail
        # page, not just at the top of the first one.
        header_line = "# Titel Week Afgerond op Excl. BTW"
        self.assertGreater(detail_text.count(header_line), 1)

        # Every row must appear exactly once across the whole PDF — the
        # page-break fix must not drop or duplicate rows. `\b` word
        # boundaries + greedy `\d+` mean "Row 1" and "Row 10" cannot be
        # confused for one another.
        import re

        found = [int(n) for n in re.findall(r"\bRow (\d+)\b", detail_text)]
        self.assertEqual(sorted(found), list(range(50)))
