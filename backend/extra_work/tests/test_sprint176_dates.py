"""
Sprint 176 §3 — the deadline's editing surfaces, and who may set one.

Sprint 173 put `deadline` / `planned_end_date` in the database. Sprint 174
put them on the create form. Neither gave anyone a way to CHANGE one, which
is the wrong shape for a deadline specifically: a deadline is the kind of
thing agreed after the fact, on the phone, once someone has actually looked
at the job.

Three things are pinned here.

1. **`PATCH /api/extra-work/<id>/dates/`** sets and clears both fields, and
   the endpoint RENDERS the row back with them — Sprint 174 §0's rule, the
   one that exists because Sprint 173 shipped a live 500 by declaring
   fields on a serializer that did not list them.

2. **`POST /api/extra-work/bulk-dates/`** is all-or-nothing and honours
   "leave unchanged". The second half is the one worth testing hardest: a
   bulk edit that silently wipes a date nobody touched is a data-loss bug
   that looks like a successful save.

3. **The deadline is provider-only** — the §3 decision. A customer-side
   actor is refused on create AND on the two date endpoints. The reasoning
   is recorded on the serializer and the view: the customer already has
   `preferred_date` ("I would like it around then"); the deadline is what
   turns a row red and what an operator is measured against, so a customer
   who could set it could make the provider look late by typing a date.
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from extra_work.models import ExtraWorkRequest

from .test_extra_work_mvp import ExtraWorkFixtureMixin
from customers.models import Department, WorkType


class _Base(ExtraWorkFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_fixture()

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def mk(self, **kwargs):
        defaults = dict(
            company=self.provider_a,
            customer=self.customer_a,
            building=self.building_a1,
            title="Dated job",
            description="x",
            created_by=self.admin_a,
        )
        defaults.update(kwargs)
        return ExtraWorkRequest.objects.create(**defaults)


class DatesEndpointTests(_Base):
    """The per-request surface."""

    def test_a_deadline_can_be_set_after_creation(self):
        row = self.mk()
        self.assertIsNone(row.deadline)
        due = timezone.localdate() + timedelta(days=5)

        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {"deadline": due.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.deadline, due)

    def test_the_response_RENDERS_the_dates_it_just_set(self):
        """Sprint 174 §0: a field is not done until a test renders the
        endpoint carrying it. This endpoint returns the detail serializer,
        so a `fields` mismatch would assert here rather than on the live
        site."""
        row = self.mk()
        due = timezone.localdate() + timedelta(days=5)
        end = timezone.localdate() + timedelta(days=7)

        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {"deadline": due.isoformat(), "planned_end_date": end.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        for key in (
            "deadline",
            "planned_end_date",
            "preferred_date",
            "is_overdue",
            "started_before_plan",
        ):
            with self.subTest(key=key):
                self.assertIn(key, response.data)
        self.assertEqual(str(response.data["deadline"]), due.isoformat())
        self.assertEqual(
            str(response.data["planned_end_date"]), end.isoformat()
        )

    def test_an_explicit_null_CLEARS_a_deadline(self):
        """Distinct from "absent" — see the next test."""
        row = self.mk(deadline=timezone.localdate())

        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {"deadline": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertIsNone(row.deadline)

    def test_an_ABSENT_field_is_left_alone(self):
        """The whole "leave unchanged" convention in one test. Sending only
        a planned end must not touch the deadline already stored."""
        due = timezone.localdate() + timedelta(days=3)
        row = self.mk(deadline=due)

        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {
                "planned_end_date": (
                    timezone.localdate() + timedelta(days=9)
                ).isoformat()
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.deadline, due)

    def test_an_empty_body_changes_nothing_and_400s(self):
        row = self.mk()
        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "no_dates_provided")

    def test_a_planned_end_before_the_planned_start_is_refused(self):
        row = self.mk(preferred_date=timezone.localdate() + timedelta(days=10))

        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {
                "planned_end_date": (
                    timezone.localdate() + timedelta(days=2)
                ).isoformat()
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "planned_end_before_start")
        row.refresh_from_db()
        self.assertIsNone(row.planned_end_date)

    def test_a_deadline_BEFORE_the_planned_window_is_allowed(self):
        """Deliberately not an error. A job planned for next month and due
        next week is going to be late — that is a fact worth recording, not
        an input to refuse. `is_overdue` is what surfaces it."""
        row = self.mk(preferred_date=timezone.localdate() + timedelta(days=30))

        response = self.api(self.admin_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {
                "deadline": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat()
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)


class DeadlineIsProviderOnlyTests(_Base):
    """The §3 decision, stated as tests so reversing it is one obvious
    edit rather than a hunt."""

    def test_a_customer_cannot_PATCH_dates(self):
        row = self.mk()
        response = self.api(self.cust_basic_a).patch(
            f"/api/extra-work/{row.id}/dates/",
            {"deadline": timezone.localdate().isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "deadline_provider_only")
        row.refresh_from_db()
        self.assertIsNone(row.deadline)

    def test_a_customer_cannot_bulk_set_dates(self):
        row = self.mk()
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/bulk-dates/",
            {
                "requests": [row.id],
                "deadline": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        row.refresh_from_db()
        self.assertIsNone(row.deadline)

    def test_the_role_gate_runs_BEFORE_the_lookup(self):
        """A customer aiming at another tenant's id gets the same 403 as
        one aiming at their own — not a 404 that would confirm the row does
        not exist for them (H-1)."""
        mine = self.mk()
        response_mine = self.api(self.cust_basic_a).patch(
            f"/api/extra-work/{mine.id}/dates/",
            {"deadline": timezone.localdate().isoformat()},
            format="json",
        )
        response_absent = self.api(self.cust_basic_a).patch(
            "/api/extra-work/99999/dates/",
            {"deadline": timezone.localdate().isoformat()},
            format="json",
        )
        self.assertEqual(response_mine.status_code, 403)
        self.assertEqual(response_absent.status_code, 403)


class BulkDatesTests(_Base):
    """The batch surface — a week's worth of jobs agreed in one call."""

    def test_one_date_lands_on_every_named_row(self):
        rows = [self.mk(title=f"Job {i}") for i in range(3)]
        due = timezone.localdate() + timedelta(days=4)

        response = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {"requests": [r.id for r in rows], "deadline": due.isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated"], 3)
        for row in rows:
            row.refresh_from_db()
            self.assertEqual(row.deadline, due)

    def test_a_field_the_dialog_did_not_touch_is_not_wiped(self):
        """The data-loss bug this convention exists to prevent: bulk-set a
        deadline across three rows, and the planned end date one of them
        already had must survive."""
        keep = timezone.localdate() + timedelta(days=20)
        rows = [self.mk(title=f"Job {i}") for i in range(3)]
        rows[1].planned_end_date = keep
        rows[1].save(update_fields=["planned_end_date"])

        response = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {
                "requests": [r.id for r in rows],
                "deadline": (
                    timezone.localdate() + timedelta(days=4)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        rows[1].refresh_from_db()
        self.assertEqual(rows[1].planned_end_date, keep)

    def test_an_out_of_scope_id_rejects_the_WHOLE_batch(self):
        """All-or-nothing: a partial bulk edit is worse than a failed one,
        because the operator cannot see which half landed."""
        mine = self.mk()
        theirs = ExtraWorkRequest.objects.create(
            company=self.provider_b,
            customer=self.customer_b,
            building=self.building_b,
            title="Other tenant",
            description="x",
            created_by=self.admin_b,
        )

        response = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {
                "requests": [mine.id, theirs.id],
                "deadline": timezone.localdate().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        mine.refresh_from_db()
        self.assertIsNone(mine.deadline)

    def test_an_out_of_scope_id_and_a_nonexistent_one_answer_alike(self):
        """H-1: a distinguishable answer would let a caller enumerate what
        exists in another tenant."""
        theirs = ExtraWorkRequest.objects.create(
            company=self.provider_b,
            customer=self.customer_b,
            building=self.building_b,
            title="Other tenant",
            description="x",
            created_by=self.admin_b,
        )
        body = {"deadline": timezone.localdate().isoformat()}

        cross = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {"requests": [theirs.id], **body},
            format="json",
        )
        absent = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {"requests": [99999], **body},
            format="json",
        )

        self.assertEqual(cross.status_code, absent.status_code)
        self.assertEqual(cross.data, absent.data)

    def test_a_refused_row_rolls_the_batch_back(self):
        good = self.mk(title="Good")
        bad = self.mk(
            title="Bad", preferred_date=timezone.localdate() + timedelta(days=30)
        )

        response = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {
                "requests": [good.id, bad.id],
                "planned_end_date": (
                    timezone.localdate() + timedelta(days=2)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], "planned_end_before_start")
        good.refresh_from_db()
        self.assertIsNone(good.planned_end_date)

    def test_a_body_naming_no_date_is_refused(self):
        row = self.mk()
        response = self.api(self.admin_a).post(
            "/api/extra-work/bulk-dates/",
            {"requests": [row.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)


class CreateRefusesACustomerDeadlineTests(_Base):
    """The third surface: the create form itself."""

    def _payload(self, **extra):
        payload = {
            "company": self.provider_a.id,
            "customer": self.customer_a.id,
            # Sprint 186 — required on create; the customer is seeded one
            # of each when it is created.
            "department": Department.objects.filter(
                customer=self.customer_a
            ).first().id,
            "work_type": WorkType.objects.filter(
                customer=self.customer_a
            ).first().id,
            "building": self.building_a1.id,
            "title": "Customer request",
            "description": "please",
            "line_items": [
                {
                    "custom_description": "ad hoc work",
                    "quantity": "1.00",
                    # Field-level validation runs BEFORE `validate()`, so an
                    # incomplete line would fail the request for the wrong
                    # reason and the deadline gate would never be reached.
                    "requested_date": (
                        timezone.localdate() + timedelta(days=2)
                    ).isoformat(),
                }
            ],
        }
        payload.update(extra)
        return payload

    def test_a_customer_setting_a_deadline_is_refused_with_400(self):
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(deadline=timezone.localdate().isoformat()),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("deadline", str(response.data))

    def test_a_customer_may_still_state_a_preferred_date(self):
        """The wish is not what is refused — only the commitment."""
        wish = timezone.localdate() + timedelta(days=6)
        response = self.api(self.cust_basic_a).post(
            "/api/extra-work/",
            self._payload(preferred_date=wish.isoformat()),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(str(response.data["preferred_date"]), wish.isoformat())
        # And the row carries no deadline: the customer said when they would
        # like it, and committed the provider to nothing.
        self.assertIsNone(response.data["deadline"])
