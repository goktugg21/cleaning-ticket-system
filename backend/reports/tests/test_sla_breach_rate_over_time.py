from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import Ticket


URL = "/api/reports/sla-breach-rate-over-time/"


def _force(ticket, **fields):
    Ticket.objects.filter(pk=ticket.pk).update(**fields)
    ticket.refresh_from_db()
    return ticket


class SLABreachRateOverTimeTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Build a small, deterministic spread on today's date in the project
        # timezone. We use timezone.localdate() boundaries so the buckets
        # align with the local-day annotation that the view uses.
        today = timezone.localdate()
        midday = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        ) + timedelta(hours=12)

        # Company A: 4 non-historical tickets created today, 1 of which has
        # the permanent breach marker. Plus 1 historical ticket (excluded).
        self.t_total_a = []
        for i in range(4):
            t = Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=self.customer,
                created_by=self.customer_user,
                title=f"A-{i}", description=f"A-{i}",
            )
            _force(t, created_at=midday)
            self.t_total_a.append(t)
        # Mark one of them as ever-breached.
        _force(self.t_total_a[0], sla_first_breached_at=midday + timedelta(hours=2))

        # Add a HISTORICAL ticket — must not contribute to total or breached.
        self.t_historical = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.customer_user,
            title="Historical", description="Historical",
        )
        _force(
            self.t_historical,
            created_at=midday,
            sla_status="HISTORICAL",
            sla_first_breached_at=midday,
        )

        # self.ticket created during setUp() also lives in company A and
        # may have created_at slightly before midday; it's also non-historical
        # so it counts in the total. Force its created_at to match midday so
        # we have a clean known shape: 5 non-historical, 1 breached.
        _force(self.ticket, created_at=midday)

        self.from_str = today.isoformat()
        self.to_str = today.isoformat()

    def _params(self, **extras):
        params = {"from": self.from_str, "to": self.to_str}
        params.update(extras)
        return params

    def test_unauthenticated_returns_401(self):
        response = self.client.get(URL, self._params())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customer_user_returns_403(self):
        self.client.force_authenticate(user=self.customer_user)
        response = self.client.get(URL, self._params())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_breach_rate_excludes_historical(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, self._params())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Single bucket (today). 5 non-historical (4 As + self.ticket),
        # 1 breached (the first A). Historical ticket excluded.
        self.assertEqual(len(response.data["buckets"]), 1)
        bucket = response.data["buckets"][0]
        self.assertEqual(bucket["total"], 5)
        self.assertEqual(bucket["breached"], 1)
        self.assertEqual(bucket["breach_rate"], 0.2)

    def test_zero_total_returns_zero_rate_not_division_error(self):
        # Range entirely in the future, no tickets.
        future = (timezone.localdate() + timedelta(days=365)).isoformat()
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(URL, {"from": future, "to": future})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["buckets"]), 1)
        bucket = response.data["buckets"][0]
        self.assertEqual(bucket["total"], 0)
        self.assertEqual(bucket["breached"], 0)
        self.assertEqual(bucket["breach_rate"], 0.0)

    def test_granularity_day_for_short_range(self):
        self.client.force_authenticate(user=self.super_admin)
        today = timezone.localdate()
        response = self.client.get(
            URL, {"from": today.isoformat(), "to": today.isoformat()}
        )
        self.assertEqual(response.data["granularity"], "day")

    def test_granularity_week_for_medium_range(self):
        self.client.force_authenticate(user=self.super_admin)
        today = timezone.localdate()
        response = self.client.get(
            URL,
            {
                "from": (today - timedelta(days=60)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.data["granularity"], "week")

    def test_granularity_month_for_long_range(self):
        self.client.force_authenticate(user=self.super_admin)
        today = timezone.localdate()
        response = self.client.get(
            URL,
            {
                "from": (today - timedelta(days=400)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.data["granularity"], "month")

    def test_empty_buckets_filled_with_zeros(self):
        # 7-day range with tickets only on today; the other 6 days produce
        # total=0, breached=0, breach_rate=0.0 buckets.
        today = timezone.localdate()
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL,
            {
                "from": (today - timedelta(days=6)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        buckets = response.data["buckets"]
        self.assertEqual(len(buckets), 7)
        # Earlier days are empty.
        for b in buckets[:-1]:
            self.assertEqual(b["total"], 0)
            self.assertEqual(b["breached"], 0)
            self.assertEqual(b["breach_rate"], 0.0)
        # Last bucket is today, with the 5/1 mix.
        self.assertEqual(buckets[-1]["total"], 5)
        self.assertEqual(buckets[-1]["breached"], 1)

    def test_cross_tenant_returns_403(self):
        self.client.force_authenticate(user=self.company_admin)
        response = self.client.get(
            URL, {**self._params(), "company": self.other_company.id}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
