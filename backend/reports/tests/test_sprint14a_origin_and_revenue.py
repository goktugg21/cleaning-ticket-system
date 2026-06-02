"""
Sprint 14A — ticket origin separation + Extra Work revenue states.

PART A — tickets-by-origin
  Each operational Ticket is classified into exactly one origin:
    CONVERTED  -> status == CONVERTED_TO_EXTRA_WORK
    EXTRA_WORK -> spawned from an ExtraWorkRequest (and not converted)
    PLANNED    -> spawned from a PlannedOccurrence (and not the above)
    NORMAL     -> everything else
  Also: ?origin= narrows the existing by-type/customer/building reports;
  an unknown value -> 400 with stable code `origin_invalid`.

PART B — Extra Work revenue states
  Each in-scope ExtraWorkRequest is classified into exactly one of four
  revenue states (earned / in_progress / quoted_pipeline / lost) and an
  amount is picked. Provider-management roles only; STAFF + CUSTOMER_USER
  are denied because the report exposes commercial amounts.

Both parts reuse the existing TenantFixtureMixin (see test_dimensions_json
for the role/scope contract).
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import Building, BuildingManagerAssignment
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from planned_work.models import (
    Frequency,
    PlannedOccurrence,
    PlannedOccurrenceStatus,
    RecurringJob,
)
from test_utils import TenantFixtureMixin
from tickets.models import Ticket, TicketStatus, TicketType


URL_ORIGIN = "/api/reports/tickets-by-origin/"
URL_ORIGIN_CSV = "/api/reports/tickets-by-origin/export.csv"
URL_TYPE = "/api/reports/tickets-by-type/"

URL_REVENUE = "/api/reports/extra-work-revenue/"
URL_REVENUE_CSV = "/api/reports/extra-work-revenue/export.csv"


def _origin_counts(buckets):
    return {b["origin"]: b["count"] for b in buckets}


# ===========================================================================
# PART A — tickets-by-origin
# ===========================================================================


class _OriginBase(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # self.ticket (company A) is a NORMAL ticket by default.

        # EXTRA_WORK: ticket spawned from an EW request.
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="EW A",
            description="d",
        )
        self.ew_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="EW spawned",
            description="d",
            type=TicketType.REQUEST,
            extra_work_request=self.ew,
        )

        # CONVERTED: a ticket in the terminal CONVERTED_TO_EXTRA_WORK status.
        self.converted_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Converted",
            description="d",
        )
        Ticket.objects.filter(pk=self.converted_ticket.pk).update(
            status=TicketStatus.CONVERTED_TO_EXTRA_WORK
        )

        # PLANNED: a ticket linked to a PlannedOccurrence.
        self.job = RecurringJob.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            title="Recurring A",
            frequency=Frequency.WEEKLY,
            start_date="2026-01-01",
            created_by=self.super_admin,
        )
        self.occurrence = PlannedOccurrence.objects.create(
            recurring_job=self.job,
            company=self.company,
            building=self.building,
            customer=self.customer,
            planned_date="2026-06-01",
            status=PlannedOccurrenceStatus.TICKET_CREATED,
        )
        self.planned_ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Planned spawned",
            description="d",
            planned_occurrence=self.occurrence,
        )


class TicketsByOriginScopeTests(_OriginBase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL_ORIGIN)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_ORIGIN)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_origins_separated_correctly(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_ORIGIN)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        counts = _origin_counts(response.data["buckets"])
        # Company A: self.ticket NORMAL + EW ticket + converted + planned.
        # Company B: self.other_ticket NORMAL.
        self.assertEqual(counts.get("NORMAL"), 2)
        self.assertEqual(counts.get("EXTRA_WORK"), 1)
        self.assertEqual(counts.get("CONVERTED"), 1)
        self.assertEqual(counts.get("PLANNED"), 1)
        self.assertEqual(response.data["total"], 5)

    def test_converted_ew_ticket_counts_as_converted_not_extra_work(self):
        # A ticket that is BOTH spawned-from-EW AND in CONVERTED status must
        # classify as CONVERTED (status wins over the EW link).
        Ticket.objects.filter(pk=self.ew_ticket.pk).update(
            status=TicketStatus.CONVERTED_TO_EXTRA_WORK
        )
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_ORIGIN)
        counts = _origin_counts(response.data["buckets"])
        self.assertNotIn("EXTRA_WORK", counts)
        self.assertEqual(counts.get("CONVERTED"), 2)

    def test_buckets_in_fixed_origin_order(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_ORIGIN)
        origins = [b["origin"] for b in response.data["buckets"]]
        # Fixed order: NORMAL, EXTRA_WORK, CONVERTED, PLANNED (present ones).
        self.assertEqual(origins, ["NORMAL", "EXTRA_WORK", "CONVERTED", "PLANNED"])

    def test_origin_label_present(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_ORIGIN)
        for bucket in response.data["buckets"]:
            self.assertIn("origin_label", bucket)
            self.assertTrue(bucket["origin_label"])

    def test_company_admin_only_sees_own_company(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_ORIGIN)
        counts = _origin_counts(response.data["buckets"])
        # Company A only: 1 NORMAL + EW + converted + planned.
        self.assertEqual(counts.get("NORMAL"), 1)
        self.assertEqual(counts.get("EXTRA_WORK"), 1)
        self.assertEqual(counts.get("CONVERTED"), 1)
        self.assertEqual(counts.get("PLANNED"), 1)
        self.assertEqual(response.data["total"], 4)

    def test_building_manager_only_sees_assigned_building(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL_ORIGIN)
        # Manager assigned to building A only.
        self.assertEqual(response.data["total"], 4)

    def test_cross_company_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_ORIGIN, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class OriginFilterOnByTypeTests(_OriginBase):
    def test_origin_filter_narrows_by_type(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"origin": "EXTRA_WORK"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only the EW-spawned ticket (REQUEST type).
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["buckets"][0]["ticket_type"], "REQUEST")

    def test_origin_filter_normal_excludes_special_origins(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"origin": "NORMAL"})
        # 2 NORMAL tickets (company A self.ticket + company B other_ticket).
        self.assertEqual(response.data["total"], 2)

    def test_origin_filter_planned(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"origin": "PLANNED"})
        self.assertEqual(response.data["total"], 1)

    def test_origin_filter_converted(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"origin": "CONVERTED"})
        self.assertEqual(response.data["total"], 1)

    def test_invalid_origin_returns_400_with_code(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE, {"origin": "BOGUS"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "origin_invalid")

    def test_origin_absent_is_additive_noop(self):
        # Without ?origin the by-type total is unchanged from baseline.
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_TYPE)
        # self.ticket + ew_ticket + converted + planned + other_ticket = 5.
        self.assertEqual(response.data["total"], 5)


class TicketsByOriginExportTests(_OriginBase):
    EXPECTED_HEADERS = [
        "origin",
        "origin_label",
        "count",
        "period_from",
        "period_to",
    ]

    def _csv_rows(self, response):
        import csv
        import io

        text = response.content.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text))
        return reader.fieldnames, list(reader)

    def test_csv_unauthenticated_returns_401(self):
        response = self.client.get(URL_ORIGIN_CSV)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_csv_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_ORIGIN_CSV)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_ORIGIN_CSV)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("tickets-by-origin", response["Content-Disposition"])
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_HEADERS)
        json_response = self.client.get(URL_ORIGIN)
        self.assertEqual(len(rows), len(json_response.data["buckets"]))


# ===========================================================================
# PART B — Extra Work revenue states
# ===========================================================================


class _RevenueBase(TenantFixtureMixin, APITestCase):
    def _ew(self, company, building, customer, *, subtotal, vat, total,
            final_subtotal=None, final_vat=None, final_total=None,
            ew_status=ExtraWorkStatus.REQUESTED):
        ew = ExtraWorkRequest.objects.create(
            company=company,
            building=building,
            customer=customer,
            created_by=self.super_admin,
            title="EW",
            description="d",
            subtotal_amount=Decimal(subtotal),
            vat_amount=Decimal(vat),
            total_amount=Decimal(total),
            final_subtotal_amount=(
                Decimal(final_subtotal) if final_subtotal is not None else None
            ),
            final_vat_amount=(
                Decimal(final_vat) if final_vat is not None else None
            ),
            final_total_amount=(
                Decimal(final_total) if final_total is not None else None
            ),
            status=ew_status,
        )
        return ew

    def _spawn(self, ew, ticket_status):
        ticket = Ticket.objects.create(
            company=ew.company,
            building=ew.building,
            customer=ew.customer,
            created_by=self.super_admin,
            title="EW spawned",
            description="d",
            type=TicketType.REQUEST,
            extra_work_request=ew,
        )
        Ticket.objects.filter(pk=ticket.pk).update(status=ticket_status)
        ticket.refresh_from_db()
        return ticket


class ExtraWorkRevenuePermissionTests(_RevenueBase):
    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_returns_403_commercial(self):
        staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_csv_staff_returns_403_commercial(self):
        staff = self.make_user("staff-b@example.com", UserRole.STAFF)
        self.client.force_authenticate(user=staff)
        response = self.client.get(URL_REVENUE_CSV)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ExtraWorkRevenueClassificationTests(_RevenueBase):
    def test_earned_uses_final_total_not_estimate(self):
        self.client.force_authenticate(user=self.super_admin)
        ew = self._ew(
            self.company, self.building, self.customer,
            subtotal="100.00", vat="21.00", total="121.00",
            final_subtotal="200.00", final_vat="42.00", final_total="242.00",
        )
        self._spawn(ew, TicketStatus.CLOSED)
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        earned = response.data["states"]["earned"]
        self.assertEqual(earned["count"], 1)
        # MUST use final (242.00), NOT the estimate (121.00).
        self.assertEqual(earned["total"], "242.00")
        self.assertEqual(earned["subtotal"], "200.00")
        self.assertEqual(earned["vat"], "42.00")
        self.assertNotEqual(earned["total"], "121.00")

    def test_earned_falls_back_to_estimate_when_final_null(self):
        # Legacy / fixed-price EW: final_total_amount is NULL, so EARNED
        # falls back to the estimate total_amount.
        self.client.force_authenticate(user=self.super_admin)
        ew = self._ew(
            self.company, self.building, self.customer,
            subtotal="100.00", vat="21.00", total="121.00",
        )
        self._spawn(ew, TicketStatus.CLOSED)
        response = self.client.get(URL_REVENUE)
        earned = response.data["states"]["earned"]
        self.assertEqual(earned["count"], 1)
        self.assertEqual(earned["total"], "121.00")
        self.assertEqual(earned["subtotal"], "100.00")

    def test_in_progress_spawned_not_closed(self):
        self.client.force_authenticate(user=self.super_admin)
        ew = self._ew(
            self.company, self.building, self.customer,
            subtotal="50.00", vat="10.50", total="60.50",
        )
        self._spawn(ew, TicketStatus.IN_PROGRESS)
        response = self.client.get(URL_REVENUE)
        ip = response.data["states"]["in_progress"]
        self.assertEqual(ip["count"], 1)
        self.assertEqual(ip["total"], "60.50")

    def test_quoted_pipeline_no_ticket_proposed(self):
        self.client.force_authenticate(user=self.super_admin)
        self._ew(
            self.company, self.building, self.customer,
            subtotal="30.00", vat="6.30", total="36.30",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )
        response = self.client.get(URL_REVENUE)
        pipeline = response.data["states"]["quoted_pipeline"]
        self.assertEqual(pipeline["count"], 1)
        self.assertEqual(pipeline["total"], "36.30")

    def test_lost_customer_rejected_no_ticket(self):
        self.client.force_authenticate(user=self.super_admin)
        self._ew(
            self.company, self.building, self.customer,
            subtotal="80.00", vat="16.80", total="96.80",
            ew_status=ExtraWorkStatus.CUSTOMER_REJECTED,
        )
        response = self.client.get(URL_REVENUE)
        lost = response.data["states"]["lost"]
        self.assertEqual(lost["count"], 1)
        self.assertEqual(lost["total"], "96.80")

    def test_lost_cancelled_no_ticket(self):
        self.client.force_authenticate(user=self.super_admin)
        self._ew(
            self.company, self.building, self.customer,
            subtotal="10.00", vat="2.10", total="12.10",
            ew_status=ExtraWorkStatus.CANCELLED,
        )
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.data["states"]["lost"]["count"], 1)
        self.assertEqual(response.data["states"]["lost"]["total"], "12.10")

    def test_lost_spawned_ticket_rejected(self):
        self.client.force_authenticate(user=self.super_admin)
        ew = self._ew(
            self.company, self.building, self.customer,
            subtotal="40.00", vat="8.40", total="48.40",
        )
        self._spawn(ew, TicketStatus.REJECTED)
        response = self.client.get(URL_REVENUE)
        lost = response.data["states"]["lost"]
        self.assertEqual(lost["count"], 1)
        self.assertEqual(lost["total"], "48.40")

    def test_totals_aggregate_all_states(self):
        self.client.force_authenticate(user=self.super_admin)
        earned = self._ew(
            self.company, self.building, self.customer,
            subtotal="100.00", vat="0.00", total="100.00",
            final_subtotal="100.00", final_vat="0.00", final_total="100.00",
        )
        self._spawn(earned, TicketStatus.CLOSED)
        self._ew(
            self.company, self.building, self.customer,
            subtotal="50.00", vat="0.00", total="50.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )
        response = self.client.get(URL_REVENUE)
        totals = response.data["totals"]
        self.assertEqual(totals["count"], 2)
        self.assertEqual(totals["total"], "150.00")


class ExtraWorkRevenueScopeTests(_RevenueBase):
    def setUp(self):
        super().setUp()
        # One EW per company so scoping can be asserted.
        self.ew_a = self._ew(
            self.company, self.building, self.customer,
            subtotal="100.00", vat="0.00", total="100.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )
        self.ew_b = self._ew(
            self.other_company, self.other_building, self.other_customer,
            subtotal="200.00", vat="0.00", total="200.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )

    def test_super_admin_sees_all(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.data["totals"]["count"], 2)
        self.assertEqual(response.data["totals"]["total"], "300.00")

    def test_company_admin_only_own_company(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.data["totals"]["count"], 1)
        self.assertEqual(response.data["totals"]["total"], "100.00")

    def test_company_admin_cannot_see_other_company_via_param(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL_REVENUE, {"company": self.other_company.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_building_manager_only_assigned_building(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get(URL_REVENUE)
        # Manager assigned to building A only.
        self.assertEqual(response.data["totals"]["count"], 1)
        self.assertEqual(response.data["totals"]["total"], "100.00")

    def test_soft_deleted_ew_excluded(self):
        from django.utils import timezone

        ExtraWorkRequest.objects.filter(pk=self.ew_a.pk).update(
            deleted_at=timezone.now()
        )
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_REVENUE)
        self.assertEqual(response.data["totals"]["count"], 1)
        self.assertEqual(response.data["totals"]["total"], "200.00")


class ExtraWorkRevenueExportTests(_RevenueBase):
    EXPECTED_HEADERS = [
        "state",
        "count",
        "subtotal",
        "vat",
        "total",
        "period_from",
        "period_to",
    ]

    def setUp(self):
        super().setUp()
        self.ew = self._ew(
            self.company, self.building, self.customer,
            subtotal="100.00", vat="0.00", total="100.00",
            ew_status=ExtraWorkStatus.PRICING_PROPOSED,
        )

    def _csv_rows(self, response):
        import csv
        import io

        text = response.content.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text))
        return reader.fieldnames, list(reader)

    def test_csv_response_shape(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_REVENUE_CSV)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("extra-work-revenue", response["Content-Disposition"])
        headers, rows = self._csv_rows(response)
        self.assertEqual(headers, self.EXPECTED_HEADERS)
        # One row per state (4 states).
        self.assertEqual(len(rows), 4)
        states = {r["state"] for r in rows}
        self.assertEqual(
            states, {"earned", "in_progress", "quoted_pipeline", "lost"}
        )
