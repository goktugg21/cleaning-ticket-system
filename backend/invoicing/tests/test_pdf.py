"""Phase 3 — invoice PDF renderer + fetch endpoint."""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from rest_framework.test import APIClient

from customers.models import Customer

from invoicing.invoice_pdf import render_invoice_pdf
from invoicing.models import Invoice
from invoicing.services import generate_draft_invoices
from invoicing.state_machine import issue_invoice, reverse_invoice, send_invoice

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _page_count(data: bytes) -> int:
    return len(PdfReader(BytesIO(data)).pages)


class RenderInvoicePdfTests(InvoicingFixture):
    def _draft(self, n_lines=2):
        for _ in range(n_lines):
            self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        return generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.CUSTOMER,
        )[0]

    def test_returns_pdf_magic_bytes(self):
        data = render_invoice_pdf(self._draft())
        self.assertTrue(data)
        self.assertTrue(data.startswith(b"%PDF"))

    def test_is_two_page_document(self):
        data = render_invoice_pdf(self._draft(n_lines=2))
        self.assertEqual(_page_count(data), 2)

    def test_draft_shows_concept_and_no_real_number(self):
        draft = self._draft()
        self.assertIsNone(draft.number)
        text = _pdf_text(render_invoice_pdf(draft))
        self.assertIn("CONCEPT", text)

    def test_issued_shows_real_number_and_no_draft_marker(self):
        issued = issue_invoice(self.admin, self._draft())
        self.assertIsNotNone(issued.number)
        text = _pdf_text(render_invoice_pdf(issued))
        self.assertIn(issued.number, text)
        self.assertNotIn("CONCEPT", text)

    def test_sent_shows_real_number(self):
        sent = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        text = _pdf_text(render_invoice_pdf(sent))
        self.assertIn(sent.number, text)
        self.assertNotIn("CONCEPT", text)

    def test_reversal_shows_creditnota_and_negative_total(self):
        # One line -> draft 121.00; reversal -121.00.
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        draft = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        sent = send_invoice(self.admin, issue_invoice(self.admin, draft))
        reversal = reverse_invoice(self.admin, sent)
        self.assertLess(reversal.total_amount, 0)
        text = _pdf_text(render_invoice_pdf(reversal))
        self.assertIn("Creditnota", text)
        self.assertIn("-121,00", text)  # Dutch negative money formatting


class InvoicePdfEndpointTests(InvoicingFixture):
    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _issued_invoice(self):
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        draft = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]
        return issue_invoice(self.admin, draft)

    def test_provider_operator_in_scope_gets_pdf(self):
        inv = self._issued_invoice()
        resp = self._api(self.admin).get(f"/api/invoices/{inv.id}/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertIn("inline", resp["Content-Disposition"])

    def test_customer_user_forbidden(self):
        inv = self._issued_invoice()
        resp = self._api(self.customer_user).get(f"/api/invoices/{inv.id}/pdf/")
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_operator_404(self):
        inv = self._issued_invoice()  # company A
        # admin_b is a provider operator, but company A's invoice is out of
        # their scope -> 404.
        resp = self._api(self.admin_b).get(f"/api/invoices/{inv.id}/pdf/")
        self.assertEqual(resp.status_code, 404)
