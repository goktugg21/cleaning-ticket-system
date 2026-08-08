"""
Sprint 155 §5 — the week grid takes MANY employees in one request.

Sprint 154's grid used the Hours page's employee FILTER as both "whose
rows am I looking at" and "whose week am I writing", so an operator could
only ever file one person's week, and changing the filter silently moved
the write target. The fix on the wire is a per-cell `employee`; the
top-level one stays and is now the DEFAULT.

What these tests exist to guarantee, beyond "it works":

  1. **The all-or-nothing property survives the widening.** One bad cell
     for employee B must roll back employee A's rows too — otherwise
     multi-employee entry is strictly worse than the loop it replaces,
     because the operator has to work out which people saved.
  2. **The permission guard covers the NEW surface.** A non-manager who
     cannot name someone else at the top level must not be able to name
     them on a cell instead.
  3. **H-1, the Sprint 142.1 oracle class.** A foreign employee id and a
     fictional one must produce EQUAL response bodies — not merely two
     errors. Asserted by comparing the bodies, because "both 400" would
     still leak if the messages differed.
  4. **The normal save path.** Every row still gets
     `multiplier_snapshot` and the derived `iso_year` / `iso_week`; those
     are the immutability core of this module and a bulk write that
     bypassed `save()` would break every weighted total silently.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from timesheets.models import TimeEntry

from .fixtures import TimesheetsFixture


BULK_WEEK_URL = "/api/timesheets/entries/bulk-week/"

# ISO 2026-W32 runs Mon 2026-08-03 .. Sun 2026-08-09.
MONDAY = dt.date(2026, 8, 3)
TUESDAY = dt.date(2026, 8, 4)
ISO_YEAR, ISO_WEEK = 2026, 32


class MultiEmployeeWeekGridTests(TimesheetsFixture):
    def _body(self, cells, **extra):
        body = {"iso_year": ISO_YEAR, "iso_week": ISO_WEEK, "cells": cells}
        body.update(extra)
        return body

    def _cell(self, date, hour_type, hours, employee=None, building=None):
        cell = {
            "date": date.isoformat(),
            "hour_type": hour_type.id,
            "hours": hours,
        }
        if employee is not None:
            cell["employee"] = employee.id
        if building is not None:
            cell["building"] = building.id
        return cell

    # -- the headline capability ------------------------------------------

    def test_manager_files_two_employees_in_one_request(self):
        response = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a
                    ),
                    self._cell(
                        MONDAY, self.normal_a, "6.00", employee=self.staff_a2
                    ),
                    self._cell(
                        TUESDAY, self.normal_a, "4.00", employee=self.staff_a2
                    ),
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 3)

        self.assertEqual(
            TimeEntry.objects.filter(employee=self.staff_a).count(), 1
        )
        self.assertEqual(
            TimeEntry.objects.filter(employee=self.staff_a2).count(), 2
        )

    def test_every_row_still_goes_through_the_normal_save_path(self):
        """The snapshot and the derived week are the module's core."""
        self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a
                    ),
                    self._cell(
                        TUESDAY, self.overtime_a, "3.00", employee=self.staff_a2
                    ),
                ]
            ),
            format="json",
        )
        for entry in TimeEntry.objects.all():
            self.assertIsNotNone(
                entry.multiplier_snapshot,
                "a bulk row was written without its multiplier snapshot",
            )
            self.assertEqual((entry.iso_year, entry.iso_week), (ISO_YEAR, ISO_WEEK))
        overtime = TimeEntry.objects.get(employee=self.staff_a2)
        self.assertEqual(
            overtime.multiplier_snapshot, self.overtime_a.multiplier
        )

    def test_top_level_employee_still_works_as_the_default(self):
        """Sprint 154's body shape must keep working verbatim."""
        response = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [self._cell(MONDAY, self.normal_a, "8.00")],
                employee=self.staff_a.id,
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            TimeEntry.objects.get().employee_id, self.staff_a.id
        )

    def test_a_cell_employee_overrides_the_top_level_default(self):
        self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(MONDAY, self.normal_a, "8.00"),
                    self._cell(
                        TUESDAY, self.normal_a, "5.00", employee=self.staff_a2
                    ),
                ],
                employee=self.staff_a.id,
            ),
            format="json",
        )
        self.assertEqual(
            TimeEntry.objects.get(date=MONDAY).employee_id, self.staff_a.id
        )
        self.assertEqual(
            TimeEntry.objects.get(date=TUESDAY).employee_id, self.staff_a2.id
        )

    # -- all-or-nothing ----------------------------------------------------

    def test_one_bad_cell_rolls_back_every_employee(self):
        """The property that makes multi-employee entry safe at all."""
        response = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a
                    ),
                    self._cell(
                        MONDAY, self.normal_a, "6.00", employee=self.staff_a2
                    ),
                    # Company B's hour type — invalid for these employees.
                    self._cell(
                        TUESDAY, self.normal_b, "4.00", employee=self.staff_a2
                    ),
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            TimeEntry.objects.count(),
            0,
            "employee A's rows survived a failure on employee B's cell",
        )

    def test_a_forbidden_employee_rolls_back_the_allowed_ones(self):
        response = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a
                    ),
                    # Company B's employee — outside this manager's scope.
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_b
                    ),
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(TimeEntry.objects.count(), 0)

    # -- the guard on the new surface --------------------------------------

    def test_staff_cannot_name_someone_else_on_a_cell(self):
        """The bypass the per-cell field would otherwise have opened."""
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a2
                    )
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data["code"], "timesheet_employee_forbidden"
        )
        self.assertEqual(TimeEntry.objects.count(), 0)

    def test_staff_may_still_name_themselves_on_a_cell(self):
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a
                    )
                ]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            TimeEntry.objects.get().employee_id, self.staff_a.id
        )

    def test_staff_omitting_the_employee_still_writes_their_own(self):
        response = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_a, "8.00")]),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            TimeEntry.objects.get().employee_id, self.staff_a.id
        )

    def test_customer_user_is_still_403_on_the_whole_endpoint(self):
        response = self.api(self.customer_user).post(
            BULK_WEEK_URL,
            self._body([self._cell(MONDAY, self.normal_a, "8.00")]),
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.data)

    # -- H-1: no existence oracle -----------------------------------------

    def test_foreign_employee_is_indistinguishable_from_a_fictional_one(self):
        """H-1 / the Sprint 142.1 oracle class.

        `staff_b` is a REAL user in company B. `999_999` is nobody. A
        company-A manager must not be able to tell the two apart, so the
        two bodies are compared for EQUALITY rather than both merely
        being checked for "is an error" — two 400s with DIFFERENT
        wording would still answer "does this id exist", which is the
        whole leak.

        The one thing that legitimately differs is the id each message
        echoes back, so the comparison substitutes it out. Echoing the
        id the CALLER just sent is not an oracle: it tells them nothing
        they did not already type. What would be an oracle is the two
        answers differing in kind — "not yours" for one and "no such
        thing" for the other — and that is exactly what the normalised
        comparison below catches.
        """
        foreign = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_b
                    )
                ]
            ),
            format="json",
        )
        fictional = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    {
                        "date": MONDAY.isoformat(),
                        "hour_type": self.normal_a.id,
                        "hours": "8.00",
                        "employee": 999_999,
                    }
                ]
            ),
            format="json",
        )
        self.assertEqual(foreign.status_code, fictional.status_code)
        self.assertEqual(
            str(foreign.data).replace(str(self.staff_b.id), "<ID>"),
            str(fictional.data).replace("999999", "<ID>"),
            "a foreign employee id reads differently from a fictional one",
        )
        # And the machine-readable half, which is what a client branches
        # on: the same field, the same code, for both.
        self.assertEqual(
            foreign.data["employee"][0].code,
            fictional.data["employee"][0].code,
        )
        self.assertEqual(foreign.data["employee"][0].code, "does_not_exist")

    def test_the_forbidden_message_names_no_user(self):
        """The non-manager 403 must not become an oracle either.

        It says "not you" and nothing else — in particular it must not
        confirm that the id it was handed belongs to a real person.
        """
        real = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    self._cell(
                        MONDAY, self.normal_a, "8.00", employee=self.staff_a2
                    )
                ]
            ),
            format="json",
        )
        fictional = self.api(self.staff_a).post(
            BULK_WEEK_URL,
            self._body(
                [
                    {
                        "date": MONDAY.isoformat(),
                        "hour_type": self.normal_a.id,
                        "hours": "8.00",
                        "employee": 999_999,
                    }
                ]
            ),
            format="json",
        )
        self.assertEqual(real.status_code, fictional.status_code)
        self.assertEqual(str(real.data), str(fictional.data))

    # -- clearing, across employees ---------------------------------------

    def test_zero_clears_only_the_named_employees_cell(self):
        self.make_entry(self.staff_a, MONDAY, self.normal_a, "8.00")
        self.make_entry(self.staff_a2, MONDAY, self.normal_a, "6.00")

        response = self.api(self.ca_a).post(
            BULK_WEEK_URL,
            self._body(
                [self._cell(MONDAY, self.normal_a, "0", employee=self.staff_a)]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["deleted"], 1)
        self.assertFalse(
            TimeEntry.objects.filter(employee=self.staff_a).exists()
        )
        self.assertEqual(
            TimeEntry.objects.get(employee=self.staff_a2).hours,
            Decimal("6.00"),
            "clearing one employee's cell touched another's",
        )
