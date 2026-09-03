"""P-16 Part C — the preview-vs-generate month question, closed.

P-14 C1 filed the trap: the preview beside the Generate button answers
the THROUGH question (everything unbilled up to and including the
picked month — Sprint 120's ≤-period rule) while the button answered
the exact-month question; six lines predicted, one produced. The close:
the generate endpoint accepts `through`, the Facturen screen always
passes it, and the button bills exactly the list its preview showed.
The default stays exact-month, so no other caller changes behaviour;
double-billing stays impossible either way — the CLAIM (`is_invoiced`
plus the live line link) is what prevents it, not the month window.
"""
from datetime import datetime, timezone as dt_timezone

from ._helpers import InvoicingFixture

GENERATE_URL = "/api/invoices/generate/"


def _dt(year, month, day):
    return datetime(year, month, day, 12, 0, tzinfo=dt_timezone.utc)


class GenerateThroughTests(InvoicingFixture):
    def _api(self, user):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def setUp(self):
        super().setUp()
        # One earned EW in May, one in June — two billing months open.
        self.ew_may = self.make_ew(closed_at=_dt(2026, 5, 31))
        self.ew_june = self.make_ew(closed_at=_dt(2026, 6, 15))

    def test_default_stays_exact_month(self):
        resp = self._api(self.admin).post(
            GENERATE_URL,
            {"customer": self.customer.id, "year": 2026, "month": 6},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        lines = [line for inv in resp.data for line in inv["lines"]]
        self.assertEqual(len(lines), 1)
        self.ew_may.refresh_from_db()
        self.ew_june.refresh_from_db()
        self.assertFalse(self.ew_may.is_invoiced)
        self.assertTrue(self.ew_june.is_invoiced)

    def test_through_bills_what_the_preview_shows(self):
        resp = self._api(self.admin).post(
            GENERATE_URL,
            {
                "customer": self.customer.id,
                "year": 2026,
                "month": 6,
                "through": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        lines = [line for inv in resp.data for line in inv["lines"]]
        self.assertEqual(len(lines), 2)
        self.ew_may.refresh_from_db()
        self.ew_june.refresh_from_db()
        self.assertTrue(self.ew_may.is_invoiced)
        self.assertTrue(self.ew_june.is_invoiced)

    def test_through_cannot_double_bill(self):
        """The claim, not the window, is the guard: a second through
        run finds an empty pool and creates nothing."""
        api = self._api(self.admin)
        first = api.post(
            GENERATE_URL,
            {
                "customer": self.customer.id,
                "year": 2026,
                "month": 6,
                "through": True,
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        second = api.post(
            GENERATE_URL,
            {
                "customer": self.customer.id,
                "year": 2026,
                "month": 6,
                "through": True,
            },
            format="json",
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data, [])
