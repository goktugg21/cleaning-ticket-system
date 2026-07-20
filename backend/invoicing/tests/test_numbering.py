"""Phase 2b — gapless per-(company, year) numbering."""
from __future__ import annotations

import threading

from django.db import connection, transaction
from django.test import TransactionTestCase

from companies.models import Company

from invoicing.numbering import allocate_invoice_number

from ._helpers import InvoicingFixture


class NumberingTests(InvoicingFixture):
    def _alloc(self, company, year):
        with transaction.atomic():
            return allocate_invoice_number(company.id, year)

    def test_sequential_per_company_year(self):
        got = [self._alloc(self.company, 2026) for _ in range(3)]
        self.assertEqual(
            [n for n, _ in got], ["2026-0001", "2026-0002", "2026-0003"]
        )
        self.assertEqual([s for _, s in got], [1, 2, 3])

    def test_independent_per_company(self):
        a1, _ = self._alloc(self.company, 2026)
        b1, _ = self._alloc(self.company_b, 2026)
        # Two different companies each start their own 2026 sequence at 0001.
        self.assertEqual(a1, "2026-0001")
        self.assertEqual(b1, "2026-0001")

    def test_new_year_restarts_at_one(self):
        self._alloc(self.company, 2026)
        self._alloc(self.company, 2026)
        n_2027, seq = self._alloc(self.company, 2027)
        self.assertEqual(n_2027, "2027-0001")
        self.assertEqual(seq, 1)

    def test_no_gaps_across_many(self):
        nums = [self._alloc(self.company, 2026)[0] for _ in range(5)]
        self.assertEqual(nums, [f"2026-{i:04d}" for i in range(1, 6)])


class NumberingConcurrencyTests(TransactionTestCase):
    """Real Postgres row-lock proof: two threads allocate concurrently and
    must serialize on the InvoiceNumberSequence row — distinct, consecutive,
    gapless. Uses TransactionTestCase so each thread's commit is visible
    across connections."""

    def setUp(self):
        self.company = Company.objects.create(name="ConcCo", slug="conc-co-2b")

    def test_concurrent_allocations_serialize_gaplessly(self):
        results = []
        errors = []
        start = threading.Barrier(2)

        def worker():
            try:
                start.wait()
                with transaction.atomic():
                    results.append(allocate_invoice_number(self.company.id, 2026))
            except Exception as exc:  # noqa: BLE001 - surfaced via `errors`
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [], f"worker errors: {errors}")
        seqs = sorted(s for _, s in results)
        self.assertEqual(seqs, [1, 2])  # distinct + consecutive, no dup/gap
        self.assertEqual(
            sorted(n for n, _ in results), ["2026-0001", "2026-0002"]
        )
