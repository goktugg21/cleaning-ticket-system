"""Phase 2a Part A — unbilled_extra_work (Option-1 semantics)."""
from __future__ import annotations

from datetime import date

from tickets.models import TicketStatus

from invoicing.selectors import unbilled_extra_work

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5


class UnbilledExtraWorkTests(InvoicingFixture):
    def _ids(self, **kw):
        rows = unbilled_extra_work(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH, **kw
        )
        return [e.id for e in rows]

    def test_plain_earned_in_month_appears(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        self.assertIn(ew.id, self._ids())

    def test_is_invoiced_row_excluded(self):
        # Legacy-settled / already-invoiced rows must never resurface.
        ew = self.make_ew(closed_at=dt(2026, 5, 31), is_invoiced=True)
        self.assertNotIn(ew.id, self._ids())

    def test_row_claimed_by_live_invoice_line_excluded(self):
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        self.claim_with_invoice(ew, deleted=False)
        self.assertNotIn(ew.id, self._ids())

    def test_row_claimed_only_by_soft_deleted_invoice_reappears(self):
        # Release path: is_invoiced cleared + invoice soft-deleted -> the EW
        # is unbilled again (no LIVE claim).
        ew = self.make_ew(closed_at=dt(2026, 5, 31))
        self.claim_with_invoice(ew, deleted=True)
        self.assertIn(ew.id, self._ids())

    def test_out_of_scope_returns_nothing(self):
        # Company-A admin asking for Company B's (company, customer): scope
        # excludes it -> empty.
        self.make_ew(
            closed_at=dt(2026, 5, 31),
            company=self.company_b,
            building=self.building_b,
            customer=self.customer_b,
            created_by=self.admin_b,
        )
        res = unbilled_extra_work(
            self.admin, self.company_b.id, self.customer_b.id, YEAR, MONTH
        )
        self.assertEqual(res, [])

    def test_not_earned_excluded(self):
        # Ticket OPEN => not earned even though invoice_date resolves to May.
        ew = self.make_ew(
            ticket_status=TicketStatus.OPEN,
            closed_at=None,
            invoice_date=date(2026, 5, 10),
        )
        self.assertNotIn(ew.id, self._ids())

    def test_wrong_month_excluded(self):
        ew = self.make_ew(closed_at=dt(2026, 6, 15))  # June, not May
        self.assertNotIn(ew.id, self._ids())

    def test_building_filter_narrows(self):
        in_b1 = self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        in_b2 = self.make_ew(closed_at=dt(2026, 5, 31), building=self.building2)
        ids_b1 = self._ids(building_id=self.building.id)
        self.assertIn(in_b1.id, ids_b1)
        self.assertNotIn(in_b2.id, ids_b1)
