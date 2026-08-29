"""
FE-3 (Addendum D §D.11 G3) — `days_until_due` on the meerwerk detail:
the chip's number, by the same rule as `is_overdue`.
"""
from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework import status as http
from rest_framework.test import APITestCase

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin


class DaysUntilDueTests(TenantFixtureMixin, APITestCase):
    def _request(self, **kwargs) -> ExtraWorkRequest:
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Deep clean",
            description="",
            **kwargs,
        )

    def _read(self, row: ExtraWorkRequest):
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(f"/api/extra-work/{row.id}/")
        self.assertEqual(response.status_code, http.HTTP_200_OK, response.data)
        return response.data

    def test_no_deadline_no_number(self):
        data = self._read(self._request(status=ExtraWorkStatus.REQUESTED))
        self.assertIsNone(data["days_until_due"])
        self.assertFalse(data["is_overdue"])

    def test_days_left_and_days_over(self):
        today = timezone.localdate()
        ahead = self._request(
            status=ExtraWorkStatus.UNDER_REVIEW,
            deadline=today + datetime.timedelta(days=5),
        )
        self.assertEqual(self._read(ahead)["days_until_due"], 5)
        late = self._request(
            status=ExtraWorkStatus.IN_PROGRESS,
            deadline=today - datetime.timedelta(days=2),
        )
        data = self._read(late)
        self.assertEqual(data["days_until_due"], -2)
        self.assertTrue(data["is_overdue"])

    def test_finished_work_stops_counting_like_is_overdue(self):
        today = timezone.localdate()
        for finished in (
            ExtraWorkStatus.COMPLETED,
            ExtraWorkStatus.CANCELLED,
            ExtraWorkStatus.CUSTOMER_REJECTED,
        ):
            with self.subTest(status=finished):
                row = self._request(
                    status=finished, deadline=today - datetime.timedelta(days=9)
                )
                data = self._read(row)
                self.assertIsNone(data["days_until_due"])
                self.assertFalse(data["is_overdue"])
