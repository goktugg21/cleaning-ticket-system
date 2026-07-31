"""
Sprint 127.2 — labels lock once the Extra Work sits on an ISSUED invoice.

Owner's rule: department / work_type become immutable once the work is on an
issued invoice, so the Department Report and issued invoices stay
reconcilable. Correcting a mislabel means credit the invoice, relabel,
re-invoice. A DRAFT does NOT lock (the correction window stays open); a
reversal releases the lock.

Every invoice here is built through the REAL invoicing services / state
machine (generate_draft_invoices -> issue_invoice -> send_invoice ->
reverse_invoice), never by hand-setting `status`, so the test exercises what
production does. The one deliberate hand-mutation is `deleted_at` on a real
sent invoice (no service soft-deletes a sent invoice, yet the lock predicate
must still honour deleted_at) — the status stays real.

The `is_invoiced`-alone case (the §1 trap) is the renamed regression test in
test_sprint127_1_relabel.py::test_claim_flag_alone_does_not_lock_labels.
"""
from __future__ import annotations

from django.utils import timezone

from customers.models import Department, WorkType
from invoicing.models import Invoice
from invoicing.services import (
    delete_draft_invoice,
    generate_draft_invoices,
)
from invoicing.state_machine import (
    issue_invoice,
    reverse_invoice,
    send_invoice,
)
from invoicing.tests._helpers import InvoicingFixture, dt
from rest_framework.test import APIClient

YEAR, MONTH = 2026, 5


class LabelLockTests(InvoicingFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dept = Department.objects.create(customer=cls.customer, name="Event")
        cls.dept2 = Department.objects.create(
            customer=cls.customer, name="Member"
        )
        cls.wt = WorkType.objects.create(
            customer=cls.customer, name="Eindschoonmaak"
        )

    # -- helpers ---------------------------------------------------------
    def _relabel(self, ew, **body):
        client = APIClient()
        client.force_authenticate(user=self.admin)  # COMPANY_ADMIN (provider)
        return client.patch(
            f"/api/extra-work/{ew.id}/labels/", body, format="json"
        )

    def _earned_ew(self):
        # An earned EW (CLOSED spawned ticket, May 2026) in the unbilled pool.
        return self.make_ew(closed_at=dt(YEAR, MONTH, 31))

    def _draft(self):
        return generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )[0]

    # -- draft leaves the correction window open -------------------------
    def test_draft_invoice_leaves_labels_open(self):
        ew = self._earned_ew()
        self._draft()  # claims the EW into a DRAFT
        resp = self._relabel(ew, department=self.dept.id)
        self.assertEqual(resp.status_code, 200, resp.data)
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept.id)

    def test_deleted_draft_leaves_labels_open(self):
        ew = self._earned_ew()
        draft = self._draft()
        delete_draft_invoice(self.admin, draft)  # real service: releases claim
        resp = self._relabel(ew, department=self.dept.id)
        self.assertEqual(resp.status_code, 200)

    # -- issued / sent lock ---------------------------------------------
    def test_issued_invoice_locks(self):
        ew = self._earned_ew()
        issue_invoice(self.admin, self._draft())
        resp = self._relabel(ew, department=self.dept.id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "labels_locked_by_invoice")
        # Sprint 129 §2b — an ISSUED-but-unsent invoice has no number, and the
        # 400 detail must NOT leak the old "CONCEPT" developer string.
        self.assertNotIn("concept", resp.data["detail"].lower())
        ew.refresh_from_db()
        self.assertIsNone(ew.department_id)

    def test_sent_invoice_locks(self):
        ew = self._earned_ew()
        send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        resp = self._relabel(ew, department=self.dept.id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "labels_locked_by_invoice")
        # The message names the document to credit (SENT → has a number).
        self.assertIn("invoice", resp.data["detail"].lower())

    def test_clear_to_null_is_blocked_when_locked(self):
        ew = self._earned_ew()
        ew.department = self.dept
        ew.save(update_fields=["department"])
        send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        # The lock is on the FIELDS, not on setting a value — clearing is
        # blocked too.
        resp = self._relabel(ew, department=None)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "labels_locked_by_invoice")
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept.id)

    def test_soft_deleted_issued_invoice_does_not_lock(self):
        ew = self._earned_ew()
        inv = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        # Sanity: it locks while live.
        self.assertEqual(self._relabel(ew, department=self.dept.id).status_code, 400)
        # Soft-delete it (status stays real SENT; only deleted_at changes).
        inv.deleted_at = timezone.now()
        inv.save(update_fields=["deleted_at"])
        resp = self._relabel(ew, department=self.dept.id)
        self.assertEqual(resp.status_code, 200)
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept.id)

    # -- the owner's correction flow ------------------------------------
    def test_reversal_unlocks_and_new_label_sticks(self):
        # Single-reversal unlock path. A SECOND reversal of the same original
        # has been impossible since Sprint 134's guard in
        # invoicing/state_machine.py (see invoicing/tests/test_reversal.py::
        # DoubleReversalGuardTests) — do not re-add a double-reversal case here.
        ew = self._earned_ew()
        ew.department = self.dept
        ew.save(update_fields=["department"])
        original = send_invoice(
            self.admin, issue_invoice(self.admin, self._draft())
        )
        # Locked while the issued invoice is live.
        self.assertEqual(self._relabel(ew, department=self.dept2.id).status_code, 400)
        # Credit it → the lock releases.
        reverse_invoice(self.admin, original)
        resp = self._relabel(ew, department=self.dept2.id)
        self.assertEqual(resp.status_code, 200, resp.data)
        ew.refresh_from_db()
        self.assertEqual(ew.department_id, self.dept2.id)

    def test_reinvoice_after_reversal_locks_again(self):
        ew = self._earned_ew()
        original = send_invoice(
            self.admin, issue_invoice(self.admin, self._draft())
        )
        reverse_invoice(self.admin, original)  # releases the EW to the pool
        # Re-invoice: a fresh DRAFT does not lock (still correctable)...
        redraft = self._draft()
        self.assertEqual(self._relabel(ew, department=self.dept.id).status_code, 200)
        # ...but issuing the re-invoice locks it again.
        issue_invoice(self.admin, redraft)
        resp = self._relabel(ew, department=self.dept2.id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "labels_locked_by_invoice")

    # -- Sprint 128 §0: the detail serializer exposes the lock ----------
    def _detail(self, ew):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client.get(f"/api/extra-work/{ew.id}/")

    def test_detail_reports_unlocked_for_a_drafted_ew(self):
        ew = self._earned_ew()
        self._draft()
        resp = self._detail(ew)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["labels_locked"])
        self.assertIsNone(resp.data["labels_locked_invoice"])

    def test_detail_reports_locked_and_names_invoice_for_sent_ew(self):
        ew = self._earned_ew()
        inv = send_invoice(self.admin, issue_invoice(self.admin, self._draft()))
        resp = self._detail(ew)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["labels_locked"])
        self.assertEqual(resp.data["labels_locked_invoice"], inv.number)

    def test_detail_locked_but_null_invoice_for_issued_unsent_ew(self):
        # Sprint 129 §2b — an ISSUED-but-unsent invoice locks the labels but
        # has no number yet (assigned at SEND), so the wire carries null, NOT
        # the old "CONCEPT (issued, unsent)" string. The frontend picks the
        # wording for the null case.
        ew = self._earned_ew()
        issue_invoice(self.admin, self._draft())  # ISSUED, not sent
        resp = self._detail(ew)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["labels_locked"])
        self.assertIsNone(resp.data["labels_locked_invoice"])
