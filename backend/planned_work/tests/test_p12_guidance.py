"""
P-12 E — the recurring guidance contracts:

  * E2: the create answers with the READ shape (the id above all), so
    the page can move the person to the rule they just made.
  * E3: a rule saved without a department / work type stores the
    customer's seeded "Algemeen" pair — ask, don't force, never leave
    a hole. An explicit choice always wins; a PATCH that does not
    mention the field never overwrites one.
  * E1: the occurrence stats answer the window's NO-CREW count and the
    soonest uncrewed visit (the Start-here door).
"""
from __future__ import annotations

import datetime

from rest_framework import status
from rest_framework.test import APITestCase

from customers.models import Department, WorkType
from customers.signals import DEFAULT_LABEL_NAME
from planned_work.models import PlannedOccurrence, PlannedOccurrenceStatus

from ._base import PlannedWorkFixtureMixin

JOBS_URL = "/api/planned-work/recurring-jobs/"
STATS_URL = "/api/planned-work/planned-occurrences/stats/"


class CreateAnswersReadShapeTests(PlannedWorkFixtureMixin, APITestCase):
    def test_create_returns_id_and_read_fields(self):
        self.authenticate(self.company_admin)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIn("id", resp.data)
        self.assertIn("occurrences_count", resp.data)
        self.assertEqual(resp.data["title"], "Weekly clean")


class DefaultLabelsFillTests(PlannedWorkFixtureMixin, APITestCase):
    def test_omitted_labels_store_the_seeded_pair(self):
        self.authenticate(self.company_admin)
        resp = self.client.post(JOBS_URL, self.recurring_job_payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNotNone(resp.data["department"])
        self.assertIsNotNone(resp.data["work_type"])
        self.assertEqual(resp.data["department_name"], DEFAULT_LABEL_NAME)
        self.assertEqual(resp.data["work_type_name"], DEFAULT_LABEL_NAME)

    def test_explicit_choice_wins_and_patch_does_not_overwrite(self):
        chosen_department = Department.objects.create(
            customer=self.customer, name="Kantoren"
        )
        WorkType.objects.create(customer=self.customer, name="Glas")
        self.authenticate(self.company_admin)
        resp = self.client.post(
            JOBS_URL,
            self.recurring_job_payload(department=chosen_department.id),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["department"], chosen_department.id)
        # A PATCH that does not mention the field leaves the choice.
        job_id = resp.data["id"]
        patch = self.client.patch(
            f"{JOBS_URL}{job_id}/", {"title": "Renamed"}, format="json"
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.data)
        detail = self.client.get(f"{JOBS_URL}{job_id}/")
        self.assertEqual(detail.data["department"], chosen_department.id)
        # An explicit null coerces to the seeded pair — "none" is not an
        # option in the data.
        patch2 = self.client.patch(
            f"{JOBS_URL}{job_id}/", {"department": None}, format="json"
        )
        self.assertEqual(patch2.status_code, status.HTTP_200_OK, patch2.data)
        detail2 = self.client.get(f"{JOBS_URL}{job_id}/")
        self.assertEqual(detail2.data["department_name"], DEFAULT_LABEL_NAME)


class NoCrewStatsTests(PlannedWorkFixtureMixin, APITestCase):
    def test_no_crew_counts_and_names_the_soonest(self):
        job = self.make_recurring_job()
        job.title = "Uncrewed rule"
        job.save(update_fields=["title"])
        window = self.default_window(job)
        today = datetime.date.today()
        soon = PlannedOccurrence.objects.create(
            recurring_job=job,
            company=job.company,
            building=job.building,
            customer=job.customer,
            planned_date=today + datetime.timedelta(days=1),
            status=PlannedOccurrenceStatus.PLANNED,
            source_window=window,
        )
        PlannedOccurrence.objects.create(
            recurring_job=job,
            company=job.company,
            building=job.building,
            customer=job.customer,
            planned_date=today + datetime.timedelta(days=3),
            status=PlannedOccurrenceStatus.PLANNED,
            source_window=window,
        )
        self.authenticate(self.company_admin)
        resp = self.client.get(
            STATS_URL,
            {
                "date_from": today.isoformat(),
                "date_to": (today + datetime.timedelta(days=6)).isoformat(),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["no_crew"], 2)
        self.assertEqual(resp.data["no_crew_first"]["occurrence"], soon.id)
        self.assertEqual(resp.data["no_crew_first"]["recurring_job"], job.id)
        self.assertEqual(
            resp.data["no_crew_first"]["recurring_job_title"], "Uncrewed rule"
        )
