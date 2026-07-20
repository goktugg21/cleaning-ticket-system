"""Phase 5 — the CUSTOMER read surface (the security core).

Locks the three hard invariants of `scope_customer_invoices_for` + the
`my/` endpoints:
  1. SENT-only — a customer never sees a DRAFT or an ISSUED invoice;
  2. own-customer-only — membership-level; no other customer of the same
     provider they aren't a member of, no cross-tenant;
  3. redaction — the customer read drops the provider-internal fields.
Plus: soft-deleted never visible; a SENT reversal (their credit note) IS
visible; the PDF is scope-gated; a non-customer gets an empty list / 404 (not
a 500); the provider endpoints stay 403 for a customer and unaffected for an
operator.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserMembership,
)
from invoicing.models import Invoice, InvoiceLine

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

LIST_URL = "/api/invoices/my/"


def _mk(email, role):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role, full_name=email.split("@")[0]
    )


class _CustomerReadFixture(TestCase):
    """Company A with two customers (A1, A2); a CUSTOMER_USER who is a MEMBER
    of A1 ONLY. Company B (separate tenant) with customer B1. Invoices in
    every relevant state so the scope can be pinned exactly."""

    @classmethod
    def setUpTestData(cls):
        # --- Company A ---
        cls.company = Company.objects.create(name="Prov A", slug="prov-a-inv5")
        cls.building = Building.objects.create(company=cls.company, name="A-B1")
        cls.customer_a1 = Customer.objects.create(
            company=cls.company, name="Cust A1", building=cls.building
        )
        cls.customer_a2 = Customer.objects.create(
            company=cls.company, name="Cust A2", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_a1, building=cls.building
        )
        cls.admin = _mk("admin-inv5@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.admin, company=cls.company)
        # The customer user is a MEMBER of A1 only (no building access needed).
        cls.cu = _mk("cu-inv5@example.com", UserRole.CUSTOMER_USER)
        CustomerUserMembership.objects.create(
            user=cls.cu, customer=cls.customer_a1
        )

        # --- Company B (separate tenant) ---
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-inv5")
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B-B1"
        )
        cls.customer_b1 = Customer.objects.create(
            company=cls.company_b, name="Cust B1", building=cls.building_b
        )

        # --- Invoices ---
        cls.inv_a1_sent = cls._inv(cls.customer_a1, Invoice.Status.SENT, "2026-0001")
        cls.inv_a1_draft = cls._inv(cls.customer_a1, Invoice.Status.DRAFT)
        cls.inv_a1_issued = cls._inv(cls.customer_a1, Invoice.Status.ISSUED, "2026-0002")
        cls.inv_a1_sent_deleted = cls._inv(
            cls.customer_a1, Invoice.Status.SENT, "2026-0003", deleted=True
        )
        cls.inv_a1_reversal_sent = cls._inv(
            cls.customer_a1, Invoice.Status.SENT, "2026-0004", is_reversal=True
        )
        # Same provider, different customer the cu is NOT a member of.
        cls.inv_a2_sent = cls._inv(cls.customer_a2, Invoice.Status.SENT, "2026-0005")
        # Cross-tenant.
        cls.inv_b1_sent = cls._inv(
            cls.customer_b1, Invoice.Status.SENT, "2026-0001", company=cls.company_b
        )

        # A line on the visible invoice (extra_work=NULL — the redaction test
        # only checks the KEY is absent from the serialized output).
        InvoiceLine.objects.create(
            invoice=cls.inv_a1_sent,
            ordering=0,
            description="Uitgevoerd werk",
            extra_work=None,
            quantity=Decimal("1.00"),
            unit_price=Decimal("100.00"),
            vat_pct=Decimal("21.00"),
            line_subtotal=Decimal("100.00"),
            line_vat=Decimal("21.00"),
            line_total=Decimal("121.00"),
            period_year=2026,
            period_month=5,
        )

    @classmethod
    def _inv(cls, customer, status, number=None, *, deleted=False, is_reversal=False, company=None):
        now = timezone.now()
        return Invoice.objects.create(
            company=company or cls.company,
            customer=customer,
            status=status,
            number=number,
            year=2026 if number else None,
            issued_at=now if status in (Invoice.Status.ISSUED, Invoice.Status.SENT) else None,
            sent_at=now if status == Invoice.Status.SENT else None,
            deleted_at=now if deleted else None,
            is_reversal=is_reversal,
            period_year=2026,
            period_month=5,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            created_by=cls.admin,
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class CustomerInvoiceListScopeTests(_CustomerReadFixture):
    def test_list_shows_only_own_sent(self):
        resp = self._api(self.cu).get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        ids = {row["id"] for row in resp.data}
        # ONLY the SENT invoice + the SENT reversal of A1.
        self.assertEqual(
            ids, {self.inv_a1_sent.id, self.inv_a1_reversal_sent.id}
        )
        # Explicitly none of the excluded rows.
        for excluded in (
            self.inv_a1_draft,
            self.inv_a1_issued,
            self.inv_a1_sent_deleted,
            self.inv_a2_sent,
            self.inv_b1_sent,
        ):
            self.assertNotIn(excluded.id, ids)

    def test_sent_reversal_is_visible(self):
        resp = self._api(self.cu).get(LIST_URL)
        ids = {row["id"] for row in resp.data}
        self.assertIn(self.inv_a1_reversal_sent.id, ids)

    def test_non_customer_gets_empty_list_not_500(self):
        resp = self._api(self.admin).get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])


class CustomerInvoiceDetailScopeTests(_CustomerReadFixture):
    def _detail(self, inv):
        return f"/api/invoices/my/{inv.id}/"

    def _pdf(self, inv):
        return f"/api/invoices/my/{inv.id}/pdf/"

    def test_own_sent_detail_ok(self):
        resp = self._api(self.cu).get(self._detail(self.inv_a1_sent))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["number"], "2026-0001")

    def test_own_sent_pdf_ok(self):
        resp = self._api(self.cu).get(self._pdf(self.inv_a1_sent))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_draft_detail_and_pdf_404(self):
        api = self._api(self.cu)
        self.assertEqual(api.get(self._detail(self.inv_a1_draft)).status_code, 404)
        self.assertEqual(api.get(self._pdf(self.inv_a1_draft)).status_code, 404)

    def test_issued_detail_and_pdf_404(self):
        api = self._api(self.cu)
        self.assertEqual(api.get(self._detail(self.inv_a1_issued)).status_code, 404)
        self.assertEqual(api.get(self._pdf(self.inv_a1_issued)).status_code, 404)

    def test_other_customer_same_provider_404(self):
        api = self._api(self.cu)
        self.assertEqual(api.get(self._detail(self.inv_a2_sent)).status_code, 404)
        self.assertEqual(api.get(self._pdf(self.inv_a2_sent)).status_code, 404)

    def test_cross_tenant_404(self):
        api = self._api(self.cu)
        self.assertEqual(api.get(self._detail(self.inv_b1_sent)).status_code, 404)
        self.assertEqual(api.get(self._pdf(self.inv_b1_sent)).status_code, 404)

    def test_soft_deleted_404(self):
        api = self._api(self.cu)
        self.assertEqual(
            api.get(self._detail(self.inv_a1_sent_deleted)).status_code, 404
        )

    def test_non_customer_detail_404(self):
        # A provider operator hitting the customer detail gets 404 (empty
        # scope), never a leak.
        resp = self._api(self.admin).get(self._detail(self.inv_a1_sent))
        self.assertEqual(resp.status_code, 404)


class CustomerInvoiceRedactionTests(_CustomerReadFixture):
    # Provider-internal fields the customer read MUST NOT expose.
    DROPPED_INVOICE_KEYS = {
        "company",
        "customer",
        "year",
        "reverses",
        "created_at",
        "updated_at",
    }
    DROPPED_LINE_KEYS = {"extra_work", "id", "ordering", "created_at", "updated_at"}

    def test_redaction_drops_provider_fields(self):
        resp = self._api(self.cu).get(f"/api/invoices/my/{self.inv_a1_sent.id}/")
        self.assertEqual(resp.status_code, 200)
        keys = set(resp.data.keys())
        # Dropped invoice-level keys are ABSENT.
        self.assertEqual(keys & self.DROPPED_INVOICE_KEYS, set())
        # Customer-facing keys are PRESENT.
        for present in (
            "number",
            "status",
            "customer_name",
            "building_name",
            "subtotal_amount",
            "vat_amount",
            "total_amount",
            "summary_text",
            "is_reversal",
            "issued_at",
            "sent_at",
            "lines",
        ):
            self.assertIn(present, keys)
        # Line redaction: extra_work + internal plumbing ABSENT.
        line = resp.data["lines"][0]
        line_keys = set(line.keys())
        self.assertEqual(line_keys & self.DROPPED_LINE_KEYS, set())
        self.assertNotIn("extra_work", line_keys)  # the key redaction, explicit
        for present in ("description", "quantity", "line_total"):
            self.assertIn(present, line_keys)


class ProviderSurfaceUnaffectedTests(_CustomerReadFixture):
    def test_customer_403_on_provider_list(self):
        resp = self._api(self.cu).get("/api/invoices/")
        self.assertEqual(resp.status_code, 403)

    def test_customer_403_on_issue(self):
        resp = self._api(self.cu).post(
            f"/api/invoices/{self.inv_a1_draft.id}/issue/"
        )
        self.assertEqual(resp.status_code, 403)

    def test_customer_403_on_generate(self):
        resp = self._api(self.cu).post(
            "/api/invoices/generate/",
            {"customer": self.customer_a1.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_operator_unaffected_on_provider_list(self):
        resp = self._api(self.admin).get("/api/invoices/")
        self.assertEqual(resp.status_code, 200)
