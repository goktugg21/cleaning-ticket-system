"""
W4-R — the rate endpoints, and the fact that a wage is personal data.

The owner decided who sees a wage and the decision is not open:

    SUPER_ADMIN       may see and set a rate.
    COMPANY_ADMIN     may see and set a rate, within their own company.
    BUILDING_MANAGER  MAY NOT. Not the rate, and not a per-person cost
                      figure derived from one. A BM routes work and
                      oversees completion; what a colleague earns is not
                      part of that job.
    STAFF             may not see anyone's rate, INCLUDING their own,
                      and including inferring it from a cost.
    CUSTOMER_USER     may not see any of it, ever.

**This is tested against the ENDPOINT, not against a screen.** Hiding a
field in the frontend while the API still returns it is not a
permission, it is a decoration — so every role below calls every verb on
every URL, and the tenant isolation is asserted with company B genuinely
populated (an isolation test that passes because the other side is empty
proves nothing).

The last class is the BACK DOOR: a one-person job's labour cost divided
by its hours IS that person's hourly rate. It is closed by the hours
panel returning NO cost block at all to a BUILDING_MANAGER, on every
job, whatever the crew size — see `reports/extra_work_hours.py` for why
no partial answer works.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import override_settings
from rest_framework import status

from audit.models import AuditLog
from extra_work.models import ExtraWorkCategory, ExtraWorkRequest, ExtraWorkStatus
from reports.models import EmployeeHourlyRate
from timesheets.models import HourSource
from timesheets.tests.fixtures import TimesheetsFixture


LIST_URL = "/api/reports/employee-hourly-rates/"
JANUARY = date(2026, 1, 12)
MARCH = date(2026, 3, 2)


def detail_url(rate_id: int) -> str:
    return f"/api/reports/employee-hourly-rates/{rate_id}/"


class RateApiBase(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.rate_a = EmployeeHourlyRate.objects.create(
            company=self.company_a,
            employee=self.staff_a,
            hourly_rate=Decimal("20.00"),
            valid_from=JANUARY,
            created_by=self.ca_a,
        )
        self.rate_b = EmployeeHourlyRate.objects.create(
            company=self.company_b,
            employee=self.staff_b,
            hourly_rate=Decimal("80.00"),
            valid_from=JANUARY,
            created_by=self.ca_b,
        )

    def payload(self, **overrides):
        body = {
            "company": self.company_a.id,
            "employee": self.staff_a2.id,
            "hourly_rate": "25.50",
            "valid_from": MARCH.isoformat(),
            "note": "New starter rate",
        }
        body.update(overrides)
        return body

    def rows(self, response):
        data = response.data
        return data["results"] if isinstance(data, dict) and "results" in data else data


class WhoMayReachTheRateAtAllTests(RateApiBase):
    """The admit matrix, verb by verb, against the real URLs."""

    def test_a_super_admin_may_read_and_write(self):
        listed = self.api(self.sa).get(LIST_URL)
        created = self.api(self.sa).post(LIST_URL, self.payload(), format="json")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)

    def test_a_company_admin_may_read_and_write(self):
        listed = self.api(self.ca_a).get(LIST_URL)
        created = self.api(self.ca_a).post(LIST_URL, self.payload(), format="json")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)

    def test_A_BUILDING_MANAGER_IS_REFUSED_EVERY_VERB(self):
        """The deliberate one. A BM is admitted to every OTHER reports
        surface by `IsRevenueReportConsumer`; this endpoint is where
        that habit stops."""
        client = self.api(self.bm_a)

        self.assertEqual(
            client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            client.post(LIST_URL, self.payload(), format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            client.get(detail_url(self.rate_a.id)).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            client.patch(
                detail_url(self.rate_a.id), {"hourly_rate": "99.00"}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            client.delete(detail_url(self.rate_a.id)).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_STAFF_ARE_REFUSED_INCLUDING_THEIR_OWN_RATE(self):
        """`self.rate_a` IS this worker's own rate. A worker reading
        their wage from a reporting endpoint is a payroll surface nobody
        designed, and the same refusal is what stops anyone reading a
        colleague's."""
        client = self.api(self.staff_a)

        self.assertEqual(
            client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            client.get(detail_url(self.rate_a.id)).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            client.post(LIST_URL, self.payload(), format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_a_customer_user_is_refused(self):
        client = self.api(self.customer_user)

        self.assertEqual(
            client.get(LIST_URL).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            client.get(detail_url(self.rate_a.id)).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_an_anonymous_caller_is_refused(self):
        from rest_framework.test import APIClient

        response = APIClient().get(LIST_URL)

        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_a_refused_role_cannot_delete_a_row_it_cannot_see(self):
        """Belt and braces: the 403 above must also have changed
        nothing."""
        self.api(self.bm_a).delete(detail_url(self.rate_a.id))

        self.assertTrue(
            EmployeeHourlyRate.objects.filter(pk=self.rate_a.id).exists()
        )


class TenantIsolationTests(RateApiBase):
    def test_a_company_admin_sees_only_their_own_companys_rates(self):
        rows = self.rows(self.api(self.ca_a).get(LIST_URL))

        self.assertEqual([row["id"] for row in rows], [self.rate_a.id])

    def test_a_super_admin_sees_both(self):
        rows = self.rows(self.api(self.sa).get(LIST_URL))

        self.assertEqual(
            {row["id"] for row in rows}, {self.rate_a.id, self.rate_b.id}
        )

    def test_another_tenants_row_is_a_404_and_so_is_a_fiction(self):
        """H-1: out of scope must be indistinguishable from
        nonexistent."""
        foreign = self.api(self.ca_a).get(detail_url(self.rate_b.id))
        fictional = self.api(self.ca_a).get(detail_url(98765432))

        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(fictional.status_code, status.HTTP_404_NOT_FOUND)

    def test_another_tenants_row_cannot_be_edited_or_deleted(self):
        patched = self.api(self.ca_a).patch(
            detail_url(self.rate_b.id), {"hourly_rate": "1.00"}, format="json"
        )
        deleted = self.api(self.ca_a).delete(detail_url(self.rate_b.id))

        self.assertEqual(patched.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)
        self.rate_b.refresh_from_db()
        self.assertEqual(self.rate_b.hourly_rate, Decimal("80.00"))

    def test_writing_into_another_tenant_reads_as_NONEXISTENT_not_forbidden(self):
        """The Sprint 142.1 rule: 'exists but forbidden' is an existence
        oracle against another tenant's staff list."""
        response = self.api(self.ca_a).post(
            LIST_URL,
            self.payload(company=self.company_b.id, employee=self.staff_b.id),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("company", response.data)
        self.assertEqual(
            response.data["company"][0].code, "does_not_exist", response.data
        )

    def test_an_out_of_scope_employee_filter_yields_nothing_not_a_leak(self):
        rows = self.rows(
            self.api(self.ca_a).get(f"{LIST_URL}?employee={self.staff_b.id}")
        )

        self.assertEqual(rows, [])


class WriteRuleTests(RateApiBase):
    def test_the_employee_must_actually_work_for_that_company(self):
        """Two scoped fields both passing does not make the PAIR valid —
        a SUPER_ADMIN reaches every company and every person."""
        response = self.api(self.sa).post(
            LIST_URL,
            self.payload(company=self.company_a.id, employee=self.staff_b.id),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("employee", response.data)

    def test_a_customer_user_can_never_be_given_a_rate(self):
        response = self.api(self.sa).post(
            LIST_URL,
            self.payload(employee=self.customer_user.id),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_wage_of_zero_is_refused_with_a_sentence(self):
        response = self.api(self.ca_a).post(
            LIST_URL, self.payload(hourly_rate="0.00"), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("hourly_rate", response.data)

    def test_a_second_rate_on_the_same_start_date_is_refused(self):
        """Two rows on one date make "the row in force" a coin flip
        decided by insertion order. Refused with a sentence that says
        what to do instead — a non-field error, because the clash is in
        the COMBINATION rather than in any one field."""
        response = self.api(self.ca_a).post(
            LIST_URL,
            self.payload(employee=self.staff_a.id, valid_from=JANUARY.isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)
        self.assertIn(
            "already has a rate starting on that date",
            str(response.data["non_field_errors"][0]),
        )

    def test_a_raise_is_a_NEW_ROW_and_leaves_the_old_one_standing(self):
        response = self.api(self.ca_a).post(
            LIST_URL,
            self.payload(
                employee=self.staff_a.id,
                hourly_rate="31.75",
                valid_from=MARCH.isoformat(),
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        history = list(
            EmployeeHourlyRate.objects.filter(
                company=self.company_a, employee=self.staff_a
            )
        )
        self.assertEqual(
            [(str(row.hourly_rate), row.valid_from) for row in history],
            [("31.75", MARCH), ("20.00", JANUARY)],
        )

    def test_created_by_is_the_ACTOR_and_not_client_supplied(self):
        response = self.api(self.ca_a).post(
            LIST_URL,
            self.payload(**{"created_by": self.sa.id}),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        row = EmployeeHourlyRate.objects.get(pk=response.data["id"])
        self.assertEqual(row.created_by_id, self.ca_a.id)

    def test_the_history_of_ONE_person_is_the_list_filtered_to_them(self):
        EmployeeHourlyRate.objects.create(
            company=self.company_a,
            employee=self.staff_a2,
            hourly_rate=Decimal("18.00"),
            valid_from=JANUARY,
            created_by=self.ca_a,
        )

        rows = self.rows(
            self.api(self.ca_a).get(f"{LIST_URL}?employee={self.staff_a.id}")
        )

        self.assertEqual([row["id"] for row in rows], [self.rate_a.id])

    def test_correcting_a_typo_is_allowed_and_is_not_a_silent_reprice(self):
        """A raise writes a new row; a CORRECTION edits the row that is
        wrong. Both are deliberate acts by somebody who can see what
        they are changing — which is the opposite of a rate change
        moving history as a side effect."""
        response = self.api(self.ca_a).patch(
            detail_url(self.rate_a.id), {"hourly_rate": "20.40"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.rate_a.refresh_from_db()
        self.assertEqual(self.rate_a.hourly_rate, Decimal("20.40"))


class AuditTests(RateApiBase):
    """A corrected wage has to be attributable afterwards (H-10's shape)."""

    def test_creating_a_rate_writes_an_audit_row(self):
        response = self.api(self.ca_a).post(LIST_URL, self.payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        log = AuditLog.objects.filter(
            target_model="reports.EmployeeHourlyRate",
            target_id=response.data["id"],
            action="CREATE",
        )
        self.assertTrue(log.exists())
        self.assertEqual(log.first().actor_id, self.ca_a.id)

    def test_correcting_a_rate_writes_a_BEFORE_AND_AFTER_diff(self):
        self.api(self.ca_a).patch(
            detail_url(self.rate_a.id), {"hourly_rate": "20.40"}, format="json"
        )

        log = AuditLog.objects.filter(
            target_model="reports.EmployeeHourlyRate",
            target_id=self.rate_a.id,
            action="UPDATE",
        ).first()

        self.assertIsNotNone(log)
        self.assertIn("hourly_rate", log.changes)

    def test_removing_a_rate_writes_an_audit_row(self):
        rate_id = self.rate_a.id

        response = self.api(self.ca_a).delete(detail_url(rate_id))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(
            AuditLog.objects.filter(
                target_model="reports.EmployeeHourlyRate",
                target_id=rate_id,
                action="DELETE",
            ).exists()
        )


class TheBackDoorTests(RateApiBase):
    """A single-person job's cost divided by its hours IS that person's rate.

    The panel is where that division would be available, so this is
    where it is closed: a BUILDING_MANAGER gets NO cost block, on every
    job, whatever the crew size. Not a rounded one, not a total without
    a breakdown — the breakdown is right there in the same response, so
    any figure at all is a wage.
    """

    def setUp(self):
        super().setUp()
        from customers.models import Customer

        self.customer_org = Customer.objects.create(
            company=self.company_a, name="Customer for the back door"
        )
        self.ew = ExtraWorkRequest.objects.create(
            company=self.company_a,
            building=self.building_a,
            customer=self.customer_org,
            created_by=self.sa,
            title="A one-person job",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.IN_PROGRESS,
        )
        self.hours_url = f"/api/reports/extra-work/{self.ew.id}/hours/"

    def book(self, employee, day, hours):
        return self.make_entry(
            employee,
            day,
            self.normal_a,
            hours=hours,
            company=self.company_a,
            created_by=self.ca_a,
            source_type=HourSource.EXTRA_WORK,
            source_id=self.ew.id,
        )

    def test_a_building_manager_gets_NO_COST_on_a_ONE_PERSON_job(self):
        self.book(self.staff_a, MARCH, "8.00")

        body = self.api(self.bm_a).get(self.hours_url).data

        self.assertIsNone(body["cost"])

    def test_a_building_manager_gets_NO_COST_on_their_OWN_one_person_job(self):
        """The subtlest version: a BM who worked the job themselves sees
        their own hours, so a cost figure would divide out their own
        wage."""
        EmployeeHourlyRate.objects.create(
            company=self.company_a,
            employee=self.bm_a,
            hourly_rate=Decimal("28.00"),
            valid_from=JANUARY,
            created_by=self.ca_a,
        )
        self.book(self.bm_a, MARCH, "4.00")

        body = self.api(self.bm_a).get(self.hours_url).data

        self.assertEqual(body["visibility"], "self")
        self.assertEqual(body["totals"]["hours"], "4.00")
        self.assertIsNone(body["cost"])

    @override_settings(LABOUR_COST_HOURLY_RATE_EUR="25.00")
    def test_a_deployment_rate_does_not_open_the_door_either(self):
        """W3-H's global rate is not a secret, but the response shape
        must not depend on which rate is in play — a cost block that
        appeared for a BM only when the rate was global would be a
        BM-visible signal about how the company prices people."""
        self.book(self.staff_a, MARCH, "8.00")

        body = self.api(self.bm_a).get(self.hours_url).data

        self.assertIsNone(body["cost"])

    def test_a_company_admin_on_the_same_job_DOES_see_the_cost(self):
        """The control. If this passed for nobody the test above would
        be proving the endpoint is broken, not that it is private.

        Costed at `self.rate_a` — EUR 20.00 for staff_a from January,
        created by the base fixture. Creating a second row here would
        clash with it on (company, employee, valid_from), which is
        exactly the constraint the write tests above pin."""
        self.book(self.staff_a, MARCH, "8.00")

        body = self.api(self.ca_a).get(self.hours_url).data

        self.assertEqual(body["cost"]["hours_cost"], "160.00")
        self.assertEqual(body["cost"]["hourly_rate"], "20.00")
