"""Sprint 12 — PlannedOccurrence pricing + schedule-window contract.

Closes the backend gap that planned/recurring work had no per-occurrence
price snapshot and no per-occurrence time window (Ramazan: recurring work
is billed per occurrence; events can carry a specific time like "this date
after 09:00").

Covers:
  * Generation snapshots the job's price + window onto each new occurrence.
  * Editing the job later does NOT mutate existing occurrences (frozen
    snapshot); a newly generated future occurrence uses the new values.
  * The spawned ticket seeds its scheduled_start_at from the occurrence
    snapshot.
  * The read serializer exposes the snapshot + computed VAT-exclusive
    subtotal / vat / VAT-inclusive total (null when not separately billed).
  * The provider-only `override` PATCH action edits the snapshot; STAFF /
    CUSTOMER_USER are 403; an out-of-scope BM gets 404; a cancelled
    occurrence is frozen.
  * The override emits exactly one targeted AuditLog UPDATE row, while
    generation / status reconcile never emit an occurrence CRUD row.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from planned_work.generation import generate_occurrences
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    PricingMode,
    RecurringJob,
)
from tickets.models import Ticket

from ._base import PlannedWorkFixtureMixin


TODAY = datetime.date(2026, 6, 1)


class _Sprint12Base(PlannedWorkFixtureMixin, APITestCase):
    def make_fixed_job(
        self,
        *,
        fixed_price="50.00",
        vat_pct="21.00",
        preferred_start_time=datetime.time(9, 0),
        time_window_label="morning",
        building=None,
        customer=None,
        frequency=Frequency.WEEKLY,
        start_date=TODAY,
    ) -> RecurringJob:
        building = building or self.building
        customer = customer or self.customer
        return RecurringJob.objects.create(
            company=building.company,
            building=building,
            customer=customer,
            title="Fixed weekly clean",
            frequency=frequency,
            start_date=start_date,
            preferred_start_time=preferred_start_time,
            time_window_label=time_window_label,
            pricing_mode=PricingMode.FIXED,
            fixed_price=Decimal(fixed_price),
            vat_pct=Decimal(vat_pct),
            created_by=self.super_admin,
        )

    def make_occurrence(self, *, job, planned_date, **overrides) -> PlannedOccurrence:
        defaults = dict(
            recurring_job=job,
            company=job.company,
            building=job.building,
            customer=job.customer,
            planned_date=planned_date,
            status=PlannedOccurrenceStatus.PLANNED,
            pricing_mode=job.pricing_mode,
            fixed_price=job.fixed_price,
            vat_pct=job.vat_pct,
            preferred_start_time=job.preferred_start_time,
            time_window_label=job.time_window_label,
        )
        defaults.update(overrides)
        return PlannedOccurrence.objects.create(**defaults)

    def override_url(self, occ):
        return f"/api/planned-work/planned-occurrences/{occ.id}/override/"


class OccurrenceSnapshotGenerationTests(_Sprint12Base):
    def test_generation_snapshots_price_and_window(self):
        job = self.make_fixed_job()
        generate_occurrences(days_ahead=7, today=TODAY)

        occ = PlannedOccurrence.objects.get(
            recurring_job=job, planned_date=TODAY
        )
        self.assertEqual(occ.pricing_mode, PricingMode.FIXED)
        self.assertEqual(occ.fixed_price, Decimal("50.00"))
        self.assertEqual(occ.vat_pct, Decimal("21.00"))
        self.assertEqual(occ.preferred_start_time, datetime.time(9, 0))
        self.assertEqual(occ.time_window_label, "morning")

    def test_spawned_ticket_uses_occurrence_start_time(self):
        job = self.make_fixed_job(preferred_start_time=datetime.time(9, 0))
        generate_occurrences(days_ahead=7, today=TODAY)

        occ = PlannedOccurrence.objects.get(
            recurring_job=job, planned_date=TODAY
        )
        ticket = Ticket.objects.get(planned_occurrence=occ)
        self.assertEqual(
            timezone.localtime(ticket.scheduled_start_at).time(),
            datetime.time(9, 0),
        )

    def test_editing_job_price_does_not_mutate_existing_occurrence(self):
        job = self.make_fixed_job(fixed_price="50.00")
        generate_occurrences(days_ahead=7, today=TODAY)
        occ = PlannedOccurrence.objects.get(
            recurring_job=job, planned_date=TODAY
        )

        # Edit the template price AFTER the occurrence was materialized.
        job.fixed_price = Decimal("999.00")
        job.time_window_label = "evening"
        job.save(update_fields=["fixed_price", "time_window_label"])

        occ.refresh_from_db()
        self.assertEqual(occ.fixed_price, Decimal("50.00"))
        self.assertEqual(occ.time_window_label, "morning")

    def test_new_occurrence_after_job_edit_uses_new_price(self):
        job = self.make_fixed_job(fixed_price="50.00")
        generate_occurrences(days_ahead=7, today=TODAY)  # TODAY, +7

        job.fixed_price = Decimal("80.00")
        job.save(update_fields=["fixed_price"])

        generate_occurrences(days_ahead=21, today=TODAY)  # adds +14, +21

        old = PlannedOccurrence.objects.get(
            recurring_job=job, planned_date=TODAY
        )
        new = PlannedOccurrence.objects.get(
            recurring_job=job, planned_date=TODAY + datetime.timedelta(days=14)
        )
        self.assertEqual(old.fixed_price, Decimal("50.00"))
        self.assertEqual(new.fixed_price, Decimal("80.00"))


class OccurrenceSerializerTests(_Sprint12Base):
    def test_serializer_exposes_price_window_and_totals(self):
        job = self.make_fixed_job(fixed_price="100.00", vat_pct="21.00")
        occ = self.make_occurrence(job=job, planned_date=TODAY)

        self.authenticate(self.super_admin)
        resp = self.client.get(
            f"/api/planned-work/planned-occurrences/{occ.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data["pricing_mode"], PricingMode.FIXED)
        self.assertEqual(data["fixed_price"], "100.00")
        self.assertEqual(data["time_window_label"], "morning")
        self.assertEqual(data["preferred_start_time"], "09:00:00")
        self.assertEqual(data["subtotal_ex_vat"], "100.00")
        self.assertEqual(data["vat_amount"], "21.00")
        self.assertEqual(data["total_inc_vat"], "121.00")

    def test_contract_included_totals_null(self):
        job = RecurringJob.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="Contract clean",
            frequency=Frequency.WEEKLY,
            start_date=TODAY,
            pricing_mode=PricingMode.CONTRACT_INCLUDED,
            created_by=self.super_admin,
        )
        occ = self.make_occurrence(
            job=job,
            planned_date=TODAY,
            pricing_mode=PricingMode.CONTRACT_INCLUDED,
            fixed_price=None,
        )

        self.authenticate(self.super_admin)
        resp = self.client.get(
            f"/api/planned-work/planned-occurrences/{occ.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["subtotal_ex_vat"])
        self.assertIsNone(resp.data["vat_amount"])
        self.assertIsNone(resp.data["total_inc_vat"])


class OccurrenceOverrideTests(_Sprint12Base):
    def setUp(self):
        super().setUp()
        self.job = self.make_fixed_job()
        self.occ = self.make_occurrence(job=self.job, planned_date=TODAY)

    def test_provider_admin_can_override_price_and_window(self):
        self.authenticate(self.company_admin)
        resp = self.client.patch(
            self.override_url(self.occ),
            {
                "fixed_price": "75.50",
                "vat_pct": "9.00",
                "preferred_start_time": "14:30:00",
                "time_window_label": "afternoon",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.occ.refresh_from_db()
        self.assertEqual(self.occ.fixed_price, Decimal("75.50"))
        self.assertEqual(self.occ.vat_pct, Decimal("9.00"))
        self.assertEqual(self.occ.preferred_start_time, datetime.time(14, 30))
        self.assertEqual(self.occ.time_window_label, "afternoon")

    def test_override_fixed_without_price_rejected(self):
        contract_occ = self.make_occurrence(
            job=self.job,
            planned_date=TODAY + datetime.timedelta(days=1),
            pricing_mode=PricingMode.CONTRACT_INCLUDED,
            fixed_price=None,
        )
        self.authenticate(self.super_admin)
        resp = self.client.patch(
            self.override_url(contract_occ),
            {"pricing_mode": PricingMode.FIXED},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["fixed_price"][0].code, "fixed_price_required")

    def test_override_hourly_rejected(self):
        self.authenticate(self.super_admin)
        resp = self.client.patch(
            self.override_url(self.occ),
            {"pricing_mode": PricingMode.HOURLY},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["pricing_mode"][0].code, "pricing_mode_not_supported"
        )

    def test_staff_cannot_override(self):
        self.authenticate(self.staff)
        resp = self.client.patch(
            self.override_url(self.occ),
            {"fixed_price": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.occ.refresh_from_db()
        self.assertEqual(self.occ.fixed_price, Decimal("50.00"))

    def test_customer_user_cannot_override(self):
        self.authenticate(self.customer_user)
        resp = self.client.patch(
            self.override_url(self.occ),
            {"fixed_price": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_out_of_scope_bm_cannot_override(self):
        # other_manager is a BUILDING_MANAGER on other_building only.
        self.authenticate(self.other_manager)
        resp = self.client.patch(
            self.override_url(self.occ),
            {"fixed_price": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancelled_occurrence_cannot_be_overridden(self):
        self.occ.status = PlannedOccurrenceStatus.CANCELLED
        self.occ.save(update_fields=["status"])
        self.authenticate(self.super_admin)
        resp = self.client.patch(
            self.override_url(self.occ),
            {"fixed_price": "10.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "occurrence_override_forbidden_state")


class OccurrenceOverrideAuditTests(_Sprint12Base):
    def setUp(self):
        super().setUp()
        self.job = self.make_fixed_job()
        self.occ = self.make_occurrence(job=self.job, planned_date=TODAY)

    def _po_audit_updates(self):
        return AuditLog.objects.filter(
            target_model="planned_work.PlannedOccurrence",
            action=AuditAction.UPDATE,
        )

    def test_override_writes_one_audit_update_row(self):
        self.authenticate(self.company_admin)
        resp = self.client.patch(
            self.override_url(self.occ),
            {"fixed_price": "75.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        rows = self._po_audit_updates()
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertIn("fixed_price", row.changes)
        self.assertEqual(row.changes["fixed_price"]["after"], "75.50")

    def test_generation_does_not_write_occurrence_audit_update(self):
        # Generation CREATEs occurrences + reconciles ticket status; none of
        # that touches the tracked price/window fields, so the UPDATE-only
        # handler must emit no occurrence CRUD rows.
        generate_occurrences(days_ahead=7, today=TODAY)
        self.assertEqual(self._po_audit_updates().count(), 0)
