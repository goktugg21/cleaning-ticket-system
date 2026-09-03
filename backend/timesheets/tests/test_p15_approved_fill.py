"""P-15 §0.2 — only an APPROVED agreed-hours pattern fills the sheet.

The owner's ruling on P-14's S2 finding: the approval road
(Draft → Submitted → Agreed) used to gate NOTHING in the fill —
`_agreements_for_week` read `auto_fill` and the validity window alone,
so a DRAFT pattern wrote hours into reports and closing exactly like an
agreed one (pinned live by C2: pattern 17, never approved, wrote entry
57). Now the fill reads `status=APPROVED` beside the flag; this module
is the pin.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from timesheets.models import ContractHours, ContractHoursStatus, TimeEntry

from .fixtures import TimesheetsFixture


FILL_URL = "/api/timesheets/entries/fill-week/"
ISO_YEAR, ISO_WEEK = 2026, 21


class ApprovedOnlyFillTests(TimesheetsFixture):
    def _pattern(self, *, status, monday="8.00", employee=None):
        return ContractHours.objects.create(
            company=self.company_a,
            employee=employee or self.staff_a,
            building=self.building_a,
            hour_type=self.normal_a,
            valid_from=date(2026, 1, 1),
            monday=Decimal(monday),
            auto_fill=True,
            status=status,
            created_by=self.ca_a,
        )

    def _fill(self, user):
        return self.api(user).post(
            FILL_URL,
            {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK},
            format="json",
        )

    def _entries(self):
        return TimeEntry.objects.filter(
            employee=self.staff_a, iso_year=ISO_YEAR, iso_week=ISO_WEEK
        )

    def test_a_draft_pattern_seeds_nothing(self):
        self._pattern(status=ContractHoursStatus.DRAFT)
        response = self._fill(self.staff_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(self._entries().count(), 0)

    def test_a_submitted_pattern_seeds_nothing_either(self):
        self._pattern(status=ContractHoursStatus.SAVED)
        response = self._fill(self.staff_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(self._entries().count(), 0)

    def test_an_approved_pattern_fills(self):
        self._pattern(status=ContractHoursStatus.APPROVED)
        response = self._fill(self.staff_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 1)
        entries = self._entries()
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.get().hours, Decimal("8.00"))

    def test_approval_after_the_fact_fills_on_the_next_run(self):
        """The road is not decoration: approving the pattern is what
        turns the flag on in practice."""
        pattern = self._pattern(status=ContractHoursStatus.DRAFT)
        self._fill(self.staff_a)
        self.assertEqual(self._entries().count(), 0)
        pattern.status = ContractHoursStatus.APPROVED
        pattern.save(update_fields=["status"])
        response = self._fill(self.staff_a)
        self.assertEqual(response.data["created"], 1)
        self.assertEqual(self._entries().count(), 1)
