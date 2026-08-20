"""Sprint W4-Q §2 — per-company warning thresholds.

Two questions, and the second is the one that would hurt:

  1. Does a company's own number replace the platform default, per
     field, with 0 kept distinct from "not configured"?
  2. Can a company's number reach ANOTHER company's warnings?

(2) is the tenant-scoping surface of this sprint and is tested directly
rather than assumed: two tenants, one of them tuned to a hair trigger,
and the assertion is about what the other one does NOT get.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from buildings.models import Building, BuildingManagerAssignment
from companies.models import CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
)
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from notifications.models import (
    Notification,
    NotificationEventType,
    NotificationLog,
    NotificationType,
)
from sla import thresholds as sla_thresholds
from sla import warnings as sla_warnings
from sla.models import SlaWarningThreshold
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus


def _local(y, m, d, hh=12, mm=0):
    return timezone.make_aware(
        datetime.datetime(y, m, d, hh, mm), timezone.get_current_timezone()
    )


NOW = _local(2026, 8, 19, 12, 0)


def _mail_recipients(event_type):
    return set(
        NotificationLog.objects.filter(event_type=event_type).values_list(
            "recipient_email", flat=True
        )
    )


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

class ThresholdResolverTests(TenantFixtureMixin, TestCase):
    def test_a_company_with_no_row_gets_the_settings_value(self):
        """The migration story for every existing deployment: nothing is
        configured, so nothing changes."""
        resolved = sla_thresholds.resolve(self.company.id)
        self.assertEqual(resolved.manager_review_business_seconds, 8 * 3600)
        self.assertEqual(resolved.approval_cutoff_days, 5)
        self.assertEqual(resolved.cooldown_hours, 24)

    def test_an_unknown_company_id_gets_the_defaults_not_somebody_elses(self):
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=1
        )
        resolved = sla_thresholds.resolve(None)
        self.assertEqual(resolved.manager_review_business_seconds, 8 * 3600)

    def test_an_override_replaces_only_its_own_field(self):
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=2
        )
        resolved = sla_thresholds.resolve(self.company.id)
        self.assertEqual(resolved.manager_review_business_seconds, 2 * 3600)
        # Untouched fields still fall back, INDEPENDENTLY.
        self.assertEqual(
            resolved.manager_review_escalate_business_seconds, 24 * 3600
        )
        self.assertEqual(resolved.approval_cutoff_days, 5)

    def test_zero_is_a_configured_value_and_not_an_absent_one(self):
        """`manager_review_business_hours = 0` means "warn me the moment
        it lands in review". Reading it as "unset" would silently restore
        the 8-hour default and the operator would never know."""
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=0
        )
        resolved = sla_thresholds.resolve(self.company.id)
        self.assertEqual(resolved.manager_review_business_seconds, 0)
        stored = sla_thresholds.stored_values(self.company.id)
        self.assertEqual(stored["manager_review_business_hours"], 0)

    def test_business_hours_are_stored_as_hours_and_used_as_seconds(self):
        SlaWarningThreshold.objects.create(
            company=self.company, not_started_business_hours=3
        )
        self.assertEqual(
            sla_thresholds.resolve(
                self.company.id
            ).not_started_business_seconds,
            3 * 3600,
        )

    @override_settings(SLA_WARN_MANAGER_REVIEW_BUSINESS_SECONDS=6 * 3600)
    def test_the_settings_default_is_reported_in_the_stored_unit(self):
        self.assertEqual(
            sla_thresholds.default_for("manager_review_business_hours"), 6
        )

    def test_the_cached_resolver_answers_per_company(self):
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=1
        )
        resolver = sla_thresholds.ThresholdResolver()
        self.assertEqual(
            resolver.for_company(self.company.id).manager_review_business_seconds,
            1 * 3600,
        )
        self.assertEqual(
            resolver.for_company(
                self.other_company.id
            ).manager_review_business_seconds,
            8 * 3600,
        )


# ---------------------------------------------------------------------------
# Tenant isolation, through the real sweep
# ---------------------------------------------------------------------------

class ThresholdTenantIsolationTests(TenantFixtureMixin, TestCase):
    """Two provider companies, the same stalled work in each, and one of
    them tuned to fire early. The assertion is always about the OTHER
    one."""

    def setUp(self):
        super().setUp()
        patcher = patch("notifications.services.send_mail")
        patcher.start()
        self.addCleanup(patcher.stop)

    #: WALL-CLOCK offsets, and the distinction matters. The engine
    #: measures BUSINESS seconds (Mon-Fri 09:00-17:00), so a ticket
    #: stamped ten wall-clock hours before NOW — 02:00 on the same
    #: Wednesday — has waited only THREE business hours, not ten. Two
    #: of the tests below were written against the calendar and failed
    #: for exactly that reason. The two constants are named after what
    #: they are worth in the unit the sweep actually compares.
    #:
    #: NOW is Wed 19-08-2026 12:00 Amsterdam.
    #:   -2h  -> Wed 10:00                       =  2 business hours
    #:   -2d  -> Mon 12:00: Mon 12-17 (5) +
    #:           Tue 09-17 (8) + Wed 09-12 (3)   = 16 business hours
    #: 2 is under the 8-hour platform default; 16 is over it and still
    #: under the 24-hour escalation, so the responsible manager is the
    #: only recipient in either case.
    TWO_BUSINESS_HOURS = datetime.timedelta(hours=2)
    SIXTEEN_BUSINESS_HOURS = datetime.timedelta(days=2)

    def _stage_manager_review(self, ticket, ago=None):
        Ticket.objects.filter(pk=ticket.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=NOW - (ago or self.TWO_BUSINESS_HOURS),
        )

    def test_company_a_tuning_down_does_not_fire_company_b(self):
        # 2 business hours waited; the platform default is 8, so nobody
        # fires until A drops its own threshold to 1.
        self._stage_manager_review(self.ticket)
        self._stage_manager_review(self.other_ticket)
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=1
        )
        sla_warnings.sweep(now=NOW)
        got = _mail_recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertIn(self.manager.email, got)
        self.assertNotIn(self.other_manager.email, got)

    def test_company_b_tuning_up_does_not_silence_company_a(self):
        # Waited 16 business hours: past the platform default of 8, so
        # both would fire. B raises its own bar to 40 and goes quiet; A
        # must not be silenced along with it.
        self._stage_manager_review(self.ticket, self.SIXTEEN_BUSINESS_HOURS)
        self._stage_manager_review(
            self.other_ticket, self.SIXTEEN_BUSINESS_HOURS
        )
        SlaWarningThreshold.objects.create(
            company=self.other_company, manager_review_business_hours=40
        )
        sla_warnings.sweep(now=NOW)
        got = _mail_recipients(NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE)
        self.assertIn(self.manager.email, got)
        self.assertNotIn(self.other_manager.email, got)

    def test_a_companys_cooldown_does_not_govern_another_companys(self):
        """The cooldown is per company too, because it is one of the
        seven knobs. A zero-cooldown tenant re-firing every tick must not
        drag a 24-hour tenant along with it."""
        self._stage_manager_review(self.ticket, self.SIXTEEN_BUSINESS_HOURS)
        self._stage_manager_review(
            self.other_ticket, self.SIXTEEN_BUSINESS_HOURS
        )
        SlaWarningThreshold.objects.create(
            company=self.company, cooldown_hours=0
        )
        sla_warnings.sweep(now=NOW)
        first_a = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
            recipient_email=self.manager.email,
        ).count()
        first_b = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
            recipient_email=self.other_manager.email,
        ).count()
        self.assertEqual(first_a, 1)
        self.assertEqual(first_b, 1)

        # `created_at` is auto_now_add — the REAL clock — while `now` is a
        # fixed simulated instant, and the two are days apart in a test.
        # Advancing the simulated clock five minutes therefore proves
        # nothing about a zero-hour window: every row's REAL timestamp is
        # still ahead of the simulated cutoff and everything looks
        # suppressed. Age both channels' rows onto the simulated clock
        # instead, exactly as `test_warnings.py` does, and the two
        # tenants separate cleanly: A's window is zero wide so a row AT
        # `NOW` no longer suppresses, B's is 24 hours wide so the same
        # row still does.
        aged = NOW
        NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE
        ).update(created_at=aged)
        Notification.objects.filter(
            event_type=NotificationType.SLA_MANAGER_REVIEW_OVERDUE
        ).update(created_at=aged)

        sla_warnings.sweep(now=NOW + datetime.timedelta(minutes=5))
        second_a = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
            recipient_email=self.manager.email,
        ).count()
        second_b = NotificationLog.objects.filter(
            event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
            recipient_email=self.other_manager.email,
        ).count()
        # A opted out of the throttle and speaks again; B is untouched.
        self.assertGreater(second_a, first_a)
        self.assertEqual(second_b, first_b)

    def test_the_not_started_clock_is_per_company_too(self):
        # 2 business hours late: over company A's 1-hour override and
        # under the 4-hour platform default B is still on.
        for pk in (self.ticket.pk, self.other_ticket.pk):
            Ticket.objects.filter(pk=pk).update(
                status=TicketStatus.OPEN,
                scheduled_start_at=NOW - self.TWO_BUSINESS_HOURS,
            )
        SlaWarningThreshold.objects.create(
            company=self.company, not_started_business_hours=1
        )
        sla_warnings.sweep(now=NOW)
        got = _mail_recipients(NotificationEventType.SLA_WORK_NOT_STARTED)
        self.assertIn(self.manager.email, got)
        self.assertNotIn(self.other_manager.email, got)

    def test_the_extra_work_clock_reads_the_extra_works_own_company(self):
        """The EW sweep keys on `ExtraWorkRequest.company_id`, not on
        anything inherited from a ticket it may never spawn."""
        # Company B gets a second building/customer so an EW can exist
        # there; A is left on the platform default.
        other_ew = ExtraWorkRequest.objects.create(
            company=self.other_company,
            building=self.other_building,
            customer=self.other_customer,
            created_by=self.other_company_admin,
            title="B extra work",
            description="d",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
            provider_planned_date=NOW.date(),
        )
        ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.company_admin,
            title="A extra work",
            description="d",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            subtotal_amount=Decimal("10.00"),
            vat_amount=Decimal("2.10"),
            total_amount=Decimal("12.10"),
            provider_planned_date=NOW.date(),
        )
        # Planned at 09:00 today, now is 12:00 -> 3 business hours late.
        # The default is 4, so neither fires; B drops to 1 and only B
        # should speak.
        SlaWarningThreshold.objects.create(
            company=self.other_company, not_started_business_hours=1
        )
        sla_warnings.sweep(now=NOW)
        keyed = set(
            NotificationLog.objects.filter(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED
            ).values_list("extra_work_id", flat=True)
        )
        self.assertEqual(keyed, {other_ew.pk})


# ---------------------------------------------------------------------------
# The sweep still behaves when a row exists but says nothing
# ---------------------------------------------------------------------------

class EmptyOverrideRowTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("notifications.services.send_mail")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_all_null_row_behaves_exactly_like_no_row(self):
        """A company that opened the screen and saved nothing must not
        end up in a different regime from one that never opened it."""
        SlaWarningThreshold.objects.create(company=self.company)
        Ticket.objects.filter(pk=self.ticket.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=NOW - datetime.timedelta(hours=2),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertEqual(result["manager_review"], 0)
        Ticket.objects.filter(pk=self.ticket.pk).update(
            manager_review_at=NOW - datetime.timedelta(days=2)
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertGreaterEqual(result["manager_review"], 1)

    def test_a_third_building_in_the_same_company_shares_its_numbers(self):
        """Thresholds are per COMPANY, not per building — a second
        building under the same company must not need its own row."""
        second = Building.objects.create(
            company=self.company, name="Building A2", address="Side Street 2"
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager, building=second
        )
        customer2 = Customer.objects.create(
            company=self.company,
            building=second,
            name="Customer A2",
            contact_email="a2@example.com",
        )
        CustomerBuildingMembership.objects.create(
            customer=customer2, building=second
        )
        ticket2 = Ticket.objects.create(
            company=self.company,
            building=second,
            customer=customer2,
            created_by=self.company_admin,
            title="Ticket A2",
            description="d",
        )
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=1
        )
        Ticket.objects.filter(pk=ticket2.pk).update(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            manager_review_at=NOW - datetime.timedelta(hours=2),
        )
        result = sla_warnings.sweep(now=NOW)
        self.assertGreaterEqual(result["manager_review"], 1)


class MembershipSanityTests(TenantFixtureMixin, TestCase):
    def test_the_fixture_keeps_the_two_company_admins_apart(self):
        """Guards the isolation tests above: if both admins were members
        of both companies, every assertion in this module would pass for
        the wrong reason."""
        self.assertEqual(
            set(
                CompanyUserMembership.objects.filter(
                    user=self.company_admin
                ).values_list("company_id", flat=True)
            ),
            {self.company.id},
        )
