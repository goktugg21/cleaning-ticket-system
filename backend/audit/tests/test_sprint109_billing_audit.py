"""
#109 Part B (audit P2-1) — ExtraWorkRequest BILLING-field audit trail.

The parent ExtraWorkRequest is registered with a dedicated UPDATE-only
targeted-field handler (invoice_date / is_invoiced / invoiced_at) in
backend/audit/signals.py. These tests lock:

  * the billing-month PATCH writes one AuditLog UPDATE row with actor
    + before/after invoice_date;
  * a mark-invoiced run writes one row per changed EW;
  * a clear-invoiced run writes one row per changed EW;
  * a plain status transition writes NO ExtraWorkRequest audit row
    (H-11 separation: ExtraWorkStatusHistory owns workflow changes).
"""
from __future__ import annotations

from datetime import date

from audit.models import AuditAction, AuditLog
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from extra_work.state_machine import apply_transition
from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture, _dt
from tickets.models import TicketStatus


def _ew_audit_rows(ew_id):
    return AuditLog.objects.filter(
        target_model="extra_work.ExtraWorkRequest", target_id=ew_id
    )


class BillingPatchAuditTests(_InvoiceRunFixture):
    def test_billing_patch_writes_update_row_with_actor_and_diff(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 20),
        )
        AuditLog.objects.all().delete()
        api = self._api(self.admin)
        resp = api.patch(
            f"/api/extra-work/{ew.id}/billing/",
            {"invoice_date": "2026-06-15"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        rows = _ew_audit_rows(ew.id)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.action, AuditAction.UPDATE)
        self.assertEqual(row.actor, self.admin)
        self.assertEqual(
            row.changes["invoice_date"],
            {"before": None, "after": "2026-06-15"},
        )

    def test_clearing_invoice_date_diffs_back_to_none(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED,
            closed_at=_dt(2026, 5, 20),
            invoice_date=date(2026, 6, 15),
        )
        AuditLog.objects.all().delete()
        api = self._api(self.admin)
        resp = api.patch(
            f"/api/extra-work/{ew.id}/billing/",
            {"invoice_date": None},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row = _ew_audit_rows(ew.id).get()
        self.assertEqual(
            row.changes["invoice_date"],
            {"before": "2026-06-15", "after": None},
        )


class InvoiceRunAuditTests(_InvoiceRunFixture):
    def test_mark_run_writes_one_row_per_changed_ew(self):
        ew1 = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 10)
        )
        ew2 = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 20)
        )
        # A different-month EW the run must not touch (and must not
        # produce an audit row for).
        ew_other = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 6, 20)
        )
        AuditLog.objects.all().delete()
        api = self._api(self.admin)
        resp = api.post(
            "/api/extra-work/mark-invoiced/",
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["invoiced_count"], 2)

        for ew in (ew1, ew2):
            row = _ew_audit_rows(ew.id).get()
            self.assertEqual(row.action, AuditAction.UPDATE)
            self.assertEqual(row.actor, self.admin)
            self.assertEqual(
                row.changes["is_invoiced"], {"before": False, "after": True}
            )
            self.assertIsNone(row.changes["invoiced_at"]["before"])
            self.assertIsNotNone(row.changes["invoiced_at"]["after"])
        self.assertFalse(_ew_audit_rows(ew_other.id).exists())

    def test_clear_run_writes_rows(self):
        ew = self._make_ew_with_ticket(
            ticket_status=TicketStatus.CLOSED, closed_at=_dt(2026, 5, 10)
        )
        api = self._api(self.admin)
        api.post(
            "/api/extra-work/mark-invoiced/",
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        AuditLog.objects.all().delete()
        resp = api.post(
            "/api/extra-work/clear-invoiced/",
            {"company": self.company.id, "year": 2026, "month": 5},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        row = _ew_audit_rows(ew.id).get()
        self.assertEqual(
            row.changes["is_invoiced"], {"before": True, "after": False}
        )


class StatusSeparationTests(_InvoiceRunFixture):
    def test_plain_status_transition_writes_no_ew_audit_row(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Status-only EW",
            description="d",
            status=ExtraWorkStatus.REQUESTED,
        )
        AuditLog.objects.all().delete()
        apply_transition(
            ew,
            self.super_admin,
            ExtraWorkStatus.UNDER_REVIEW,
            note="status only",
        )
        self.assertFalse(_ew_audit_rows(ew.id).exists())
