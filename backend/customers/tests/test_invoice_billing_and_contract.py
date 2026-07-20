"""Invoicing Phase 4a Part D — customer billing-schedule + contract-PDF write.

  * An OSIUS admin (SA / CA-in-company) can PATCH invoice_day_rule +
    invoice_granularity_default on a customer, and upload / remove the
    informational contract PDF.
  * The Customer read serializer returns `contract_pdf_url` (null when unset,
    set after upload).
  * A customer user cannot write the billing schedule (403) nor the contract
    PDF (403).
  * Tenant isolation: a company-A admin cannot write a company-B customer's
    schedule (404) nor its contract PDF (403); a non-PDF upload is rejected.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import UserRole
from buildings.models import Building
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

# A minimal but structurally-valid PDF header (the magic-byte check only reads
# the first bytes); enough for the upload validator + storage round-trip.
_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _mk(email: str, role: str) -> "User":
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role, full_name=email.split("@")[0]
    )


def _pdf(name="contract.pdf", content=_PDF_BYTES, content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        # --- Company A ---
        cls.company = Company.objects.create(name="Prov A", slug="prov-a-inv4a")
        cls.building = Building.objects.create(company=cls.company, name="A-B1")
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust A", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.sa = _mk("sa-inv4a@example.com", UserRole.SUPER_ADMIN)
        cls.ca = _mk("ca-inv4a@example.com", UserRole.COMPANY_ADMIN)
        CompanyUserMembership.objects.create(user=cls.ca, company=cls.company)
        cls.cust_user = _mk("cu-inv4a@example.com", UserRole.CUSTOMER_USER)

        # --- Company B (separate tenant) ---
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-inv4a")
        cls.building_b = Building.objects.create(
            company=cls.company_b, name="B-B1"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Cust B", building=cls.building_b
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer_b, building=cls.building_b
        )

    def setUp(self):
        self.client = APIClient()

    def _detail(self, customer):
        return reverse("customer-detail", args=[customer.id])

    def _contract(self, customer):
        return reverse("customer-contract-pdf", args=[customer.id])


class BillingScheduleWriteTests(_Fixture):
    def test_super_admin_can_set_billing_schedule(self):
        self.client.force_authenticate(self.sa)
        resp = self.client.patch(
            self._detail(self.customer),
            {
                "invoice_day_rule": Customer.InvoiceDayRule.LAST_OF_MONTH,
                "invoice_granularity_default": (
                    Customer.InvoiceGranularity.PER_BUILDING
                ),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.invoice_day_rule,
            Customer.InvoiceDayRule.LAST_OF_MONTH,
        )
        self.assertEqual(
            self.customer.invoice_granularity_default,
            Customer.InvoiceGranularity.PER_BUILDING,
        )

    def test_company_admin_in_company_can_set_billing_schedule(self):
        self.client.force_authenticate(self.ca)
        resp = self.client.patch(
            self._detail(self.customer),
            {"invoice_day_rule": Customer.InvoiceDayRule.FIRST_OF_MONTH},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.invoice_day_rule,
            Customer.InvoiceDayRule.FIRST_OF_MONTH,
        )

    def test_customer_user_cannot_set_billing_schedule(self):
        self.client.force_authenticate(self.cust_user)
        resp = self.client.patch(
            self._detail(self.customer),
            {"invoice_day_rule": Customer.InvoiceDayRule.FIRST_OF_MONTH},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.invoice_day_rule, "")  # unchanged

    def test_cross_tenant_admin_cannot_set_billing_schedule(self):
        # CA of company A patching a company-B customer -> 404 (out of scope).
        self.client.force_authenticate(self.ca)
        resp = self.client.patch(
            self._detail(self.customer_b),
            {"invoice_day_rule": Customer.InvoiceDayRule.FIRST_OF_MONTH},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)


class ContractPdfReadSerializerTests(_Fixture):
    def test_contract_pdf_url_null_when_unset(self):
        self.client.force_authenticate(self.sa)
        resp = self.client.get(self._detail(self.customer))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("contract_pdf_url", resp.data)
        self.assertIsNone(resp.data["contract_pdf_url"])

    def test_contract_pdf_url_set_after_upload(self):
        self.client.force_authenticate(self.sa)
        up = self.client.post(
            self._contract(self.customer), {"file": _pdf()}, format="multipart"
        )
        self.assertEqual(up.status_code, 200)
        self.assertIsNotNone(up.data["contract_pdf_url"])
        # And the read serializer now surfaces it.
        resp = self.client.get(self._detail(self.customer))
        self.assertIsNotNone(resp.data["contract_pdf_url"])


class ContractPdfWriteTests(_Fixture):
    def test_super_admin_can_upload_and_remove(self):
        self.client.force_authenticate(self.sa)
        up = self.client.post(
            self._contract(self.customer), {"file": _pdf()}, format="multipart"
        )
        self.assertEqual(up.status_code, 200)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.contract_pdf)

        # Serve it back (provider view).
        got = self.client.get(self._contract(self.customer))
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got["Content-Type"], "application/pdf")

        # Remove.
        rm = self.client.delete(self._contract(self.customer))
        self.assertEqual(rm.status_code, 204)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.contract_pdf)

    def test_company_admin_in_company_can_upload(self):
        self.client.force_authenticate(self.ca)
        up = self.client.post(
            self._contract(self.customer), {"file": _pdf()}, format="multipart"
        )
        self.assertEqual(up.status_code, 200)

    def test_replace_on_reupload_keeps_one_active_pdf(self):
        self.client.force_authenticate(self.sa)
        self.client.post(
            self._contract(self.customer),
            {"file": _pdf(name="v1.pdf")},
            format="multipart",
        )
        self.customer.refresh_from_db()
        first_name = self.customer.contract_pdf.name
        self.client.post(
            self._contract(self.customer),
            {"file": _pdf(name="v2.pdf")},
            format="multipart",
        )
        self.customer.refresh_from_db()
        # A fresh uuid path per upload (replace-on-reupload).
        self.assertNotEqual(self.customer.contract_pdf.name, first_name)

    def test_customer_user_cannot_upload(self):
        self.client.force_authenticate(self.cust_user)
        resp = self.client.post(
            self._contract(self.customer), {"file": _pdf()}, format="multipart"
        )
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_admin_cannot_upload(self):
        self.client.force_authenticate(self.ca)  # company A admin
        resp = self.client.post(
            self._contract(self.customer_b), {"file": _pdf()}, format="multipart"
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_pdf_rejected(self):
        self.client.force_authenticate(self.sa)
        resp = self.client.post(
            self._contract(self.customer),
            {"file": _pdf(name="fake.pdf", content=b"\x89PNG\r\n")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)

    def test_wrong_extension_rejected(self):
        self.client.force_authenticate(self.sa)
        resp = self.client.post(
            self._contract(self.customer),
            {"file": _pdf(name="contract.txt", content_type="application/pdf")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
