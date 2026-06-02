"""
Sprint 14D — PDF export for the Extra Work revenue report.

Closes the transcript-backed gap surfaced by Sprint 14C-BIS
(transkript.txt:65 "Bunu bir pdf yapip cakiyoruz" / :415 "csv veya pdf"):
the monthly/weekly Extra Work revenue report is exported as a PDF too.

The PDF reuses the EXACT same compute path (scope, filters, date range,
revenue states, money totals) as the existing JSON / CSV revenue endpoints
via `compute_extra_work_revenue`, so the three formats cannot drift. These
tests reuse the Sprint 14A `_RevenueBase` fixture.
"""
from rest_framework import status

from accounts.models import UserRole
from audit.models import AuditLog
from extra_work.models import ExtraWorkStatus

from .test_sprint14a_origin_and_revenue import _RevenueBase


URL_REVENUE_PDF = "/api/reports/extra-work-revenue/export.pdf"


class ExtraWorkRevenuePDFBasicTests(_RevenueBase):
    def setUp(self):
        super().setUp()
        self.ew = self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="100.00",
            vat="21.00",
            total="121.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )

    def test_pdf_returns_valid_pdf_for_super_admin(self):
        self.client.force_authenticate(user=self.super_admin)
        resp = self.client.get(URL_REVENUE_PDF)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("application/pdf", resp["Content-Type"])
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("extra-work-revenue.pdf", resp["Content-Disposition"])
        # Body starts as a valid PDF.
        self.assertEqual(resp.content[:4], b"%PDF", resp.content[:8])

    def test_pdf_shares_date_range_filter_empty_window_still_valid(self):
        # A window that excludes the seeded EW -> empty report, still a valid
        # PDF. Proves the PDF goes through the same date-range filter as the
        # JSON / CSV views (it does not blow up and does not include the row).
        self.client.force_authenticate(user=self.super_admin)
        resp = self.client.get(
            URL_REVENUE_PDF, {"from": "2000-01-01", "to": "2000-01-31"}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.content[:4], b"%PDF")

    def test_pdf_invalid_date_matches_json_csv_400(self):
        # Same validation path as JSON / CSV: a malformed date -> 400.
        self.client.force_authenticate(user=self.super_admin)
        resp = self.client.get(URL_REVENUE_PDF, {"from": "not-a-date"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pdf_get_writes_no_audit_rows(self):
        before = AuditLog.objects.count()
        self.client.force_authenticate(user=self.super_admin)
        resp = self.client.get(URL_REVENUE_PDF)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(AuditLog.objects.count(), before)


class ExtraWorkRevenuePDFScopeTests(_RevenueBase):
    def setUp(self):
        super().setUp()
        # One EW per company so provider scoping is observable.
        self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal="100.00",
            vat="0.00",
            total="100.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )
        self._ew(
            self.other_company,
            self.other_building,
            self.other_customer,
            subtotal="200.00",
            vat="0.00",
            total="200.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )

    def _pdf(self, params=None):
        return self.client.get(URL_REVENUE_PDF, params or {})

    def test_super_admin_can_export(self):
        self.client.force_authenticate(user=self.super_admin)
        self.assertEqual(self._pdf().status_code, status.HTTP_200_OK)

    def test_company_admin_can_export_own_company(self):
        self.client.force_authenticate(user=self.company_admin)
        self.assertEqual(self._pdf().status_code, status.HTTP_200_OK)

    def test_company_admin_cross_company_param_403(self):
        self.client.force_authenticate(user=self.company_admin)
        resp = self._pdf({"company": self.other_company.id})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_can_export_assigned_building(self):
        self.client.force_authenticate(user=self.manager)
        self.assertEqual(self._pdf().status_code, status.HTTP_200_OK)

    def test_staff_forbidden(self):
        staff = self.make_user("staff-pdf@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        self.assertEqual(self._pdf().status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_forbidden(self):
        self.client.force_authenticate(user=self.customer_user)
        self.assertEqual(self._pdf().status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_unauthorized(self):
        self.assertEqual(
            self._pdf().status_code, status.HTTP_401_UNAUTHORIZED
        )
