"""Shared planned-work test fixtures (Sprint 11B Batch 4).

`PlannedWorkFixtureMixin` extends the project `TenantFixtureMixin` with a
STAFF user + `BuildingStaffVisibility` on `self.building` (the base
fixture deliberately creates neither STAFF users nor visibility rows),
plus convenience constructors for a valid RecurringJob create payload
and a directly-constructed RecurringJob row.
"""
from __future__ import annotations

import datetime
from typing import Optional

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from planned_work.models import (
    Frequency,
    PricingMode,
    RecurringJob,
    RecurringJobWindow,
)
from test_utils import TenantFixtureMixin


class PlannedWorkFixtureMixin(TenantFixtureMixin):
    def setUp(self):
        super().setUp()
        # The base fixture creates no STAFF users / BuildingStaffVisibility
        # rows — add an eligible staff member on Building A here.
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )

    def recurring_job_payload(self, **overrides) -> dict:
        payload = {
            "building": self.building.id,
            "customer": self.customer.id,
            "title": "Weekly clean",
            "description": "",
            "frequency": Frequency.WEEKLY,
            "start_date": datetime.date(2026, 6, 1).isoformat(),
            "pricing_mode": PricingMode.CONTRACT_INCLUDED,
        }
        payload.update(overrides)
        return payload

    def make_recurring_job(
        self,
        *,
        frequency: str = Frequency.WEEKLY,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        preferred_start_time: Optional[datetime.time] = None,
        created_by=None,
        building=None,
        customer=None,
        is_active: bool = True,
        archived_at=None,
    ) -> RecurringJob:
        building = building or self.building
        customer = customer or self.customer
        return RecurringJob.objects.create(
            company=building.company,
            building=building,
            customer=customer,
            title="Weekly clean",
            frequency=frequency,
            start_date=start_date or datetime.date(2026, 6, 1),
            end_date=end_date,
            preferred_start_time=preferred_start_time,
            is_active=is_active,
            archived_at=archived_at,
            created_by=created_by or self.super_admin,
        )

    def default_window(self, job) -> RecurringJobWindow:
        """Return the job's first active window, creating one from its
        legacy schedule fields if it has none. Used by tests that build a
        PlannedOccurrence directly (the occurrence's source_window is a
        non-null PROTECTed FK), mirroring what the generator's
        lazy-default-window / data migration would produce."""
        window = job.windows.order_by("ordering", "id").first()
        if window is None:
            window = RecurringJobWindow.objects.create(
                recurring_job=job,
                label=job.time_window_label or "",
                start_time=job.preferred_start_time,
                ordering=0,
            )
        return window
