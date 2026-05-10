from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket
from tickets.serializers import (
    TicketDetailSerializer,
    TicketListSerializer,
    _sla_display_state,
    _sla_remaining_business_seconds,
)


URL = "/api/tickets/"


def _force(ticket, **fields):
    Ticket.objects.filter(pk=ticket.pk).update(**fields)
    ticket.refresh_from_db()
    return ticket


class SlaSerializerFieldTests(TenantFixtureMixin, TestCase):
    def test_remaining_seconds_positive_when_due_in_future(self):
        # self.ticket was just created — sla_due_at is ~24 business hours out.
        self.ticket.refresh_from_db()
        result = _sla_remaining_business_seconds(self.ticket)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_remaining_seconds_negative_when_overdue(self):
        # Freeze "now" to a fixed weekday business time so the overdue interval
        # always contains real business seconds. Using a relative
        # timezone.now() - timedelta(days=2) caused weekend flakiness: a Sun→Fri
        # span has zero business seconds, so assertLess(0, 0) failed in CI.
        fixed_now = timezone.make_aware(
            datetime(2026, 1, 7, 12, 0, 0),  # Wednesday, 12:00 project-local
            timezone.get_default_timezone(),
        )
        _force(self.ticket, sla_due_at=fixed_now - timedelta(hours=1))
        with patch("tickets.serializers.timezone.now", return_value=fixed_now):
            result = _sla_remaining_business_seconds(self.ticket)
        self.assertIsNotNone(result)
        self.assertLess(result, 0)

    def test_remaining_seconds_none_when_paused(self):
        _force(self.ticket, sla_paused_at=timezone.now())
        self.assertIsNone(_sla_remaining_business_seconds(self.ticket))

    def test_remaining_seconds_none_for_historical(self):
        _force(self.ticket, sla_status="HISTORICAL", sla_due_at=None)
        self.assertIsNone(_sla_remaining_business_seconds(self.ticket))

    def test_remaining_seconds_none_for_completed(self):
        _force(self.ticket, sla_status="COMPLETED")
        self.assertIsNone(_sla_remaining_business_seconds(self.ticket))

    def test_is_paused_field_reflects_paused_at(self):
        self.ticket.refresh_from_db()
        data = TicketListSerializer(self.ticket).data
        self.assertEqual(data["sla_is_paused"], False)
        _force(self.ticket, sla_paused_at=timezone.now())
        data = TicketListSerializer(self.ticket).data
        self.assertEqual(data["sla_is_paused"], True)

    def test_display_state_priority_paused_beats_breached(self):
        _force(
            self.ticket,
            sla_status="BREACHED",
            sla_paused_at=timezone.now(),
        )
        self.assertEqual(_sla_display_state(self.ticket), "PAUSED")

    def test_display_state_each_state(self):
        _force(self.ticket, sla_status="ON_TRACK", sla_paused_at=None)
        self.assertEqual(_sla_display_state(self.ticket), "ON_TRACK")
        _force(self.ticket, sla_status="AT_RISK")
        self.assertEqual(_sla_display_state(self.ticket), "AT_RISK")
        _force(self.ticket, sla_status="BREACHED")
        self.assertEqual(_sla_display_state(self.ticket), "BREACHED")
        _force(self.ticket, sla_status="COMPLETED")
        self.assertEqual(_sla_display_state(self.ticket), "COMPLETED")
        _force(self.ticket, sla_status="HISTORICAL")
        self.assertEqual(_sla_display_state(self.ticket), "HISTORICAL")

    def test_detail_exposes_raw_fields(self):
        self.ticket.refresh_from_db()
        data = TicketDetailSerializer(self.ticket).data
        for field in (
            "sla_status",
            "sla_due_at",
            "sla_started_at",
            "sla_completed_at",
            "sla_paused_at",
            "sla_first_breached_at",
            "sla_paused_seconds",
            "sla_display_state",
            "sla_remaining_business_seconds",
            "sla_is_paused",
        ):
            self.assertIn(field, data, f"detail serializer missing {field}")


class SlaFilterEndpointTests(TenantFixtureMixin, APITestCase):
    """End-to-end ?sla= filter behavior on the ticket list endpoint."""

    def setUp(self):
        super().setUp()
        # self.ticket is in the same company; create three more in company A
        # with different SLA states. The fixtures' self.other_ticket lives in
        # company B and is filtered out for the company_admin.
        self.t_breached = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Breached",
            description="Breached",
        )
        _force(self.t_breached, sla_status="BREACHED")

        self.t_at_risk = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="At risk",
            description="At risk",
        )
        _force(self.t_at_risk, sla_status="AT_RISK")

        self.t_paused_breached = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Paused-while-breached",
            description="Paused-while-breached",
        )
        _force(
            self.t_paused_breached,
            sla_status="BREACHED",
            sla_paused_at=timezone.now(),
        )

        # self.ticket stays ON_TRACK (default). Tickets in scope for the
        # company_admin: 4 (the original + 3 new).

        self.client.force_authenticate(user=self.company_admin)

    def _ids(self, response):
        return {row["id"] for row in response.data["results"]}

    def test_no_sla_param_returns_all(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 4)

    def test_sla_paused_returns_paused_only(self):
        response = self.client.get(URL, {"sla": "paused"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self._ids(response), {self.t_paused_breached.id})

    def test_sla_breached_excludes_paused(self):
        # t_breached should appear; t_paused_breached should NOT (paused
        # overrides underlying state per the priority rule).
        response = self.client.get(URL, {"sla": "breached"})
        self.assertEqual(self._ids(response), {self.t_breached.id})

    def test_sla_at_risk_excludes_paused(self):
        response = self.client.get(URL, {"sla": "at_risk"})
        self.assertEqual(self._ids(response), {self.t_at_risk.id})

    def test_sla_all_returns_all(self):
        response = self.client.get(URL, {"sla": "all"})
        self.assertEqual(response.data["count"], 4)

    def test_sla_invalid_value_treated_as_all(self):
        response = self.client.get(URL, {"sla": "not-a-real-state"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 4)
