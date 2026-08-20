"""Sprint W4-Q §2 — the thresholds admin API.

`sla` had no HTTP surface at all before this sprint, so every rule this
endpoint has is new and none of it is inherited. Three things are worth
a test each:

  * WHO reaches it. Provider management, and narrower than that:
    SUPER_ADMIN and COMPANY_ADMIN. A BUILDING_MANAGER manages one
    building and these numbers govern a whole company. A CUSTOMER_USER
    must not even learn the endpoint exists — 403, not an empty list.
  * WHICH companies a COMPANY_ADMIN reaches. Their own, and a probe at
    somebody else's id gets 404 rather than 403, so the response code
    cannot be used to enumerate company ids.
  * The read shape keeps `override` and `effective` apart, so
    "configured to 24" and "inherited 24" do not render the same.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from sla.models import SlaWarningThreshold
from test_utils import TenantFixtureMixin

LIST_URL = "/api/sla/warning-thresholds/"


def detail_url(company_id):
    return f"/api/sla/warning-thresholds/{company_id}/"


def field(payload, name):
    for row in payload["thresholds"]:
        if row["field"] == name:
            return row
    raise AssertionError(f"{name} missing from payload")


class ThresholdApiAccessTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_sees_every_company(self):
        self.authenticate(self.super_admin)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["company"] for row in response.data["results"]}
        self.assertIn(self.company.id, ids)
        self.assertIn(self.other_company.id, ids)

    def test_company_admin_sees_only_their_own_company(self):
        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["company"] for row in response.data["results"]}
        self.assertEqual(ids, {self.company.id})

    def test_building_manager_is_refused(self):
        self.authenticate(self.manager)
        self.assertEqual(
            self.client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_customer_user_is_refused(self):
        """Not an empty list — a customer must not learn the shape of a
        screen that describes their provider's internal rhythm."""
        self.authenticate(self.customer_user)
        self.assertEqual(
            self.client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_staff_is_refused(self):
        staff = self.make_user("staff-w4q@example.com", UserRole.STAFF)
        self.authenticate(staff)
        self.assertEqual(
            self.client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_anonymous_is_refused(self):
        self.assertIn(
            self.client.get(LIST_URL).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_a_company_admin_probing_another_company_gets_404(self):
        self.authenticate(self.company_admin)
        self.assertEqual(
            self.client.get(detail_url(self.other_company.id)).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_a_company_admin_cannot_write_another_companys_numbers(self):
        self.authenticate(self.company_admin)
        response = self.client.put(
            detail_url(self.other_company.id),
            {"manager_review_business_hours": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(
            SlaWarningThreshold.objects.filter(
                company=self.other_company
            ).exists()
        )


class ThresholdApiReadShapeTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.super_admin)

    def test_an_unconfigured_company_reports_null_overrides(self):
        response = self.client.get(detail_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_customized"])
        row = field(response.data, "manager_review_business_hours")
        self.assertIsNone(row["override"])
        self.assertEqual(row["effective"], 8)
        self.assertEqual(row["default"], 8)

    def test_a_stored_value_shows_as_an_override(self):
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=3
        )
        response = self.client.get(detail_url(self.company.id))
        row = field(response.data, "manager_review_business_hours")
        self.assertEqual(row["override"], 3)
        self.assertEqual(row["effective"], 3)
        self.assertEqual(row["default"], 8)
        self.assertTrue(response.data["is_customized"])

    def test_an_override_equal_to_the_default_is_still_an_override(self):
        """It stops tracking the default the moment it is saved, so the
        screen has to be able to say so."""
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=8
        )
        response = self.client.get(detail_url(self.company.id))
        row = field(response.data, "manager_review_business_hours")
        self.assertEqual(row["override"], 8)
        self.assertTrue(response.data["is_customized"])

    def test_the_business_window_is_reported_so_the_screen_can_explain(self):
        response = self.client.get(LIST_URL)
        window = response.data["business_window"]
        self.assertEqual(window["start"], "09:00")
        self.assertEqual(window["end"], "17:00")
        self.assertEqual(window["days"], [0, 1, 2, 3, 4])
        self.assertEqual(window["hours_per_day"], 8.0)

    def test_every_field_declares_its_unit(self):
        response = self.client.get(detail_url(self.company.id))
        units = {r["field"]: r["unit"] for r in response.data["thresholds"]}
        self.assertEqual(units["approval_cutoff_days"], "days")
        self.assertEqual(units["manager_review_business_hours"], "business_hours")
        self.assertEqual(units["cooldown_hours"], "hours")


class ThresholdApiWriteTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.company_admin)

    def test_put_creates_the_row_and_stamps_who_changed_it(self):
        response = self.client.put(
            detail_url(self.company.id),
            {"manager_review_business_hours": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = SlaWarningThreshold.objects.get(company=self.company)
        self.assertEqual(row.manager_review_business_hours, 4)
        self.assertEqual(row.updated_by_id, self.company_admin.id)
        self.assertIsNotNone(response.data["updated_at"])

    def test_zero_is_stored_and_not_treated_as_a_clear(self):
        response = self.client.put(
            detail_url(self.company.id),
            {"manager_review_business_hours": 0},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            SlaWarningThreshold.objects.get(
                company=self.company
            ).manager_review_business_hours,
            0,
        )
        row = field(response.data, "manager_review_business_hours")
        self.assertEqual(row["override"], 0)
        self.assertEqual(row["effective"], 0)

    def test_null_clears_one_override_back_to_the_default(self):
        SlaWarningThreshold.objects.create(
            company=self.company,
            manager_review_business_hours=4,
            not_started_business_hours=2,
        )
        response = self.client.put(
            detail_url(self.company.id),
            {"manager_review_business_hours": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = SlaWarningThreshold.objects.get(company=self.company)
        self.assertIsNone(row.manager_review_business_hours)
        # The other override is untouched — a PUT is partial here.
        self.assertEqual(row.not_started_business_hours, 2)

    def test_delete_resets_the_company_to_the_platform_defaults(self):
        SlaWarningThreshold.objects.create(
            company=self.company, manager_review_business_hours=4
        )
        response = self.client.delete(detail_url(self.company.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            SlaWarningThreshold.objects.filter(company=self.company).exists()
        )
        self.assertFalse(response.data["is_customized"])
        self.assertEqual(
            field(response.data, "manager_review_business_hours")["effective"],
            8,
        )

    def test_an_escalation_below_the_first_threshold_is_refused(self):
        """The hop is `crossed >= escalate_target`. An escalation smaller
        than the first threshold fires in the same tick as the first
        notice, and one hop silently becomes 'tell everybody at once'."""
        response = self.client.put(
            detail_url(self.company.id),
            {
                "manager_review_business_hours": 10,
                "manager_review_escalate_business_hours": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "manager_review_escalate_business_hours", response.data
        )
        self.assertFalse(
            SlaWarningThreshold.objects.filter(company=self.company).exists()
        )

    def test_the_pair_is_validated_against_the_inherited_half(self):
        """Submitting only ONE of the pair must still be checked against
        the default the company is inheriting for the other."""
        response = self.client.put(
            detail_url(self.company.id),
            {"manager_review_business_hours": 40},  # default escalate is 24
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_cutoff_pair_is_validated_the_other_way_round(self):
        """The approval-cutoff figures count DOWN to a date, so the
        escalation window is the SMALLER number."""
        response = self.client.put(
            detail_url(self.company.id),
            {
                "approval_cutoff_days": 3,
                "approval_cutoff_escalate_days": 7,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("approval_cutoff_escalate_days", response.data)

    def test_a_negative_value_is_refused(self):
        response = self.client.put(
            detail_url(self.company.id),
            {"cooldown_hours": -1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_super_admin_may_write_any_company(self):
        self.authenticate(self.super_admin)
        response = self.client.put(
            detail_url(self.other_company.id),
            {"cooldown_hours": 6},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            SlaWarningThreshold.objects.get(
                company=self.other_company
            ).cooldown_hours,
            6,
        )

    def test_a_building_manager_cannot_write(self):
        self.authenticate(self.manager)
        response = self.client.put(
            detail_url(self.company.id),
            {"cooldown_hours": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_customer_user_cannot_write(self):
        self.authenticate(self.customer_user)
        response = self.client.put(
            detail_url(self.company.id),
            {"cooldown_hours": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ThresholdListOrderingTests(TenantFixtureMixin, APITestCase):
    """The screen opens on `results[0]`, so the order IS the default
    company. Reported wrong four waves running because the previous fix
    lived on the screen and asked `me.company_ids` which company was the
    caller's own — a set that is EVERY company for a SUPER_ADMIN, so the
    lookup matched row zero and changed nothing."""

    def test_super_admin_gets_the_platform_company_first(self):
        # "Company B" is this deployment's own company and sorts LAST by
        # name, so a passing assertion cannot be alphabetical luck.
        self.authenticate(self.super_admin)
        with self.settings(PLATFORM_BRAND_SLUG=self.other_company.slug):
            response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["results"][0]["company"], self.other_company.id
        )

    def test_the_rest_stay_in_name_order(self):
        self.authenticate(self.super_admin)
        with self.settings(PLATFORM_BRAND_SLUG=self.other_company.slug):
            response = self.client.get(LIST_URL)
        names = [row["company_name"] for row in response.data["results"]]
        self.assertEqual(names[0], self.other_company.name)
        self.assertEqual(names[1:], sorted(names[1:]))

    def test_unknown_brand_slug_falls_back_to_name_order(self):
        """A deployment whose brand slug matches no company still gets a
        stable list rather than an arbitrary one."""
        self.authenticate(self.super_admin)
        with self.settings(PLATFORM_BRAND_SLUG="not-a-company"):
            response = self.client.get(LIST_URL)
        names = [row["company_name"] for row in response.data["results"]]
        self.assertEqual(names, sorted(names))

    def test_company_admin_gets_their_own_company_first(self):
        """Trivially true — they only receive their own — and asserted so
        that a future "own company first" rule cannot quietly drop it."""
        self.authenticate(self.company_admin)
        response = self.client.get(LIST_URL)
        self.assertEqual(
            response.data["results"][0]["company"], self.company.id
        )
