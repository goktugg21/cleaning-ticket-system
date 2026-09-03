"""P-15 §0.1 — H-12: committing an invoice is a company-level act.

The invariant (rbac-matrix §3, H-12): **issue, send, un-issue and
reverse are CA / SA only; a BUILDING_MANAGER keeps the building-level
half (drafts, preview, draft edits, lists, PDF).** Sending allocates
the gapless number and emails the customer — a company act, not a
building act.

Enforced at:
  * invoicing/views.py — `_forbid_non_admin`, used by `_transition`
    (the shared body of the four commit actions).
  * invoicing/state_machine.py — `is_invoice_admin` re-checks in
    issue/send/unissue/reverse (Addendum B's double gate — keep both).
  * invoicing/permissions.py — the one helper + the stable code
    `invoice_admin_only` both layers read.

The refusal a BM gets is the P-8-style sentence that names the next
actor: "Sending is done by the company admin. Your draft is ready for
them." — with the stable code, so the screen renders its own words.
"""
from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from buildings.models import BuildingManagerAssignment
from companies.models import CompanyUserMembership
from django.contrib.auth import get_user_model

from accounts.models import UserRole
from invoicing.models import Invoice, InvoiceLine
from invoicing.permissions import ERR_INVOICE_ADMIN_ONLY
from invoicing.state_machine import (
    issue_invoice,
    reverse_invoice,
    send_invoice,
    unissue_invoice,
)

from ._helpers import PASSWORD, InvoicingFixture

User = get_user_model()


class H12InvoiceAdminGateTests(InvoicingFixture):
    """A building manager's draft is fine; the commit belongs to the
    company admin."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bm = User.objects.create_user(
            email="bm-h12@example.com",
            password=PASSWORD,
            role=UserRole.BUILDING_MANAGER,
            full_name="BM H12",
        )
        CompanyUserMembership.objects.create(user=cls.bm, company=cls.company)
        BuildingManagerAssignment.objects.create(
            user=cls.bm, building=cls.building
        )

    def _client(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user)
        return client

    def _draft(self) -> Invoice:
        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            building=None,
            status=Invoice.Status.DRAFT,
            created_by=self.admin,
        )
        InvoiceLine.objects.create(
            invoice=invoice, ordering=0, description="Line", extra_work=None
        )
        return invoice

    # --- the four commits refuse a BM, with the sentence and the code --

    def test_bm_is_refused_on_every_commit_door(self):
        client = self._client(self.bm)
        draft = self._draft()
        issued = self._draft()
        issue_invoice(self.admin, issued)
        sent = self._draft()
        issue_invoice(self.admin, sent)
        send_invoice(self.admin, sent)

        for url in (
            f"/api/invoices/{draft.id}/issue/",
            f"/api/invoices/{issued.id}/send/",
            f"/api/invoices/{issued.id}/unissue/",
            f"/api/invoices/{sent.id}/reverse/",
        ):
            response = client.post(url)
            self.assertEqual(response.status_code, 403, url)
            self.assertEqual(
                response.data.get("code"), ERR_INVOICE_ADMIN_ONLY, url
            )
            self.assertIn("company admin", response.data.get("detail", ""), url)
        # Nothing moved.
        draft.refresh_from_db()
        issued.refresh_from_db()
        sent.refresh_from_db()
        self.assertEqual(draft.status, Invoice.Status.DRAFT)
        self.assertEqual(issued.status, Invoice.Status.ISSUED)
        self.assertEqual(sent.status, Invoice.Status.SENT)
        self.assertFalse(sent.reversed_by.exists())

    def test_bm_keeps_the_building_level_half(self):
        client = self._client(self.bm)
        draft = self._draft()
        # The lists and the record itself.
        self.assertEqual(client.get("/api/invoices/").status_code, 200)
        self.assertEqual(
            client.get(f"/api/invoices/{draft.id}/").status_code, 200
        )
        # Preview — recomputed numbers, no commitment.
        self.assertEqual(
            client.get(
                f"/api/invoices/preview/?customer={self.customer.id}"
            ).status_code,
            200,
        )
        # Draft edits and delete-draft stay theirs.
        self.assertEqual(
            client.patch(
                f"/api/invoices/{draft.id}/",
                {"summary_text": "By the BM"},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            client.delete(f"/api/invoices/{draft.id}/").status_code, 204
        )

    def test_ca_still_commits(self):
        client = self._client(self.admin)
        draft = self._draft()
        self.assertEqual(
            client.post(f"/api/invoices/{draft.id}/issue/").status_code, 200
        )
        self.assertEqual(
            client.post(f"/api/invoices/{draft.id}/send/").status_code, 200
        )
        draft.refresh_from_db()
        self.assertEqual(draft.status, Invoice.Status.SENT)
        self.assertIsNotNone(draft.number)

    def test_state_machine_rechecks_independently(self):
        """The double gate's second half: even a caller that skips the
        view layer is refused."""
        draft = self._draft()
        with self.assertRaises(PermissionDenied):
            issue_invoice(self.bm, draft)
        issue_invoice(self.admin, draft)
        with self.assertRaises(PermissionDenied):
            send_invoice(self.bm, draft)
        with self.assertRaises(PermissionDenied):
            unissue_invoice(self.bm, draft)
        send_invoice(self.admin, draft)
        with self.assertRaises(PermissionDenied):
            reverse_invoice(self.bm, draft)
