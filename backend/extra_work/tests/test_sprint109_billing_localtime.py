"""
#109 Part C (audit P3-1) — billing_month buckets on the
Europe/Amsterdam LOCAL date of ticket.closed_at, not the UTC date.

A ticket closed at 00:30 local time on the 1st of a month is stored in
UTC as 22:30/23:30 on the LAST day of the previous month
(Europe/Amsterdam is UTC+1/+2). The old `.date()` on the raw UTC value
billed such work a month early.
"""
from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase

from extra_work.billing import billing_month


class _FakeTicket:
    def __init__(self, closed_at):
        self.closed_at = closed_at


class _FakeEW:
    def __init__(self, invoice_date=None):
        self.invoice_date = invoice_date


class BillingMonthLocaltimeTests(TestCase):
    def test_just_after_local_midnight_on_the_first_bills_new_month(self):
        # 2026-06-01 00:30 Europe/Amsterdam (CEST, UTC+2) ==
        # 2026-05-31 22:30 UTC. Build the UTC datetime explicitly.
        closed_utc = datetime(2026, 5, 31, 22, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(
            billing_month(_FakeEW(), _FakeTicket(closed_utc)), (2026, 6)
        )

    def test_winter_boundary_also_buckets_local(self):
        # 2026-01-01 00:30 Europe/Amsterdam (CET, UTC+1) ==
        # 2025-12-31 23:30 UTC.
        closed_utc = datetime(2025, 12, 31, 23, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(
            billing_month(_FakeEW(), _FakeTicket(closed_utc)), (2026, 1)
        )

    def test_midday_close_unchanged(self):
        closed_utc = datetime(2026, 5, 15, 12, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(
            billing_month(_FakeEW(), _FakeTicket(closed_utc)), (2026, 5)
        )

    def test_invoice_date_override_still_wins(self):
        closed_utc = datetime(2026, 5, 31, 22, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(
            billing_month(
                _FakeEW(invoice_date=date(2026, 4, 25)),
                _FakeTicket(closed_utc),
            ),
            (2026, 4),
        )
