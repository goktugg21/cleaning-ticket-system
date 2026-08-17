"""
Sprint 183 §4 — which company a ContractHours row belongs to.

The domain audit's finding F5 said `ContractHours` "silently resolves the
wrong company when an employee belongs to two, and never re-checks it on
update". The sprint brief asked for it to be treated as a LEAD, not a
fact. It was verified against the code and both halves are real:

    # serializers_contract_hours.py, before this sprint
    candidates = employee_company_ids(employee) & scope
    validated_data["company_id"] = sorted(candidates)[0]   # <- the guess

and `company` sat in `read_only_fields` with no `update()` override, so
the anchor was never revisited when `employee` changed. The bulk grid
carried its own copy of the same two lines.

These tests pin the answer in both directions: which company a
dual-company employee's row lands in, and that the row follows its
anchors when they change.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from buildings.models import BuildingStaffVisibility
from timesheets.contract_hours_company import (
    ContractHoursCompanyError,
    resolve_company_id,
)
from timesheets.models import ContractHours

from .fixtures import TimesheetsFixture


CONTRACT_HOURS_URL = "/api/timesheets/contract-hours/"


def detail_url(row_id):
    return f"{CONTRACT_HOURS_URL}{row_id}/"


class DualCompanyEmployeeFixture(TimesheetsFixture):
    """`staff_a` made an employee of BOTH companies.

    The base fixture gives each company its own staff member; this adds a
    second company's membership to one of them, which is the shape the
    audit finding is about and which the old code resolved by picking the
    lower company id.
    """

    def setUp(self):
        super().setUp()
        # Employed by company B as well, via the same three-way
        # definition `scope.employee_company_ids` uses.
        BuildingStaffVisibility.objects.create(
            user=self.staff_a, building=self.building_b
        )

    def _payload(self, **overrides):
        payload = {
            "employee": self.staff_a.id,
            "building": self.building_a.id,
            "hour_type": self.normal_a.id,
            "valid_from": "2026-01-01",
            "monday": "3.00",
        }
        payload.update(overrides)
        return payload

    def assertBothCompanies(self):
        """Guard the fixture's own premise.

        If this ever stops holding, every assertion below becomes
        vacuously true while still passing — the worst kind of green.
        """
        from timesheets.scope import employee_company_ids

        self.assertEqual(
            employee_company_ids(self.staff_a),
            frozenset({self.company_a.id, self.company_b.id}),
        )


class ResolverTests(DualCompanyEmployeeFixture):
    def test_the_fixture_really_is_dual_company(self):
        self.assertBothCompanies()

    def test_the_building_settles_the_company(self):
        # The row says "this person, at this building". `Building.company`
        # is a single non-null FK, so the answer is a FACT — the old code
        # ignored the one unambiguous signal and guessed from the
        # ambiguous one.
        self.assertEqual(
            resolve_company_id(
                employee=self.staff_a,
                building=self.building_b,
                actor=self.sa,
            ),
            self.company_b.id,
        )
        self.assertEqual(
            resolve_company_id(
                employee=self.staff_a,
                building=self.building_a,
                actor=self.sa,
            ),
            self.company_a.id,
        )

    def test_building_wins_even_when_it_is_the_higher_company_id(self):
        # The regression this whole item is about. The old rule was
        # `sorted(candidates)[0]` — the LOWER id — so a row at a building
        # belonging to the higher-id company was filed against the wrong
        # tenant. Skipped rather than asserted blindly if the fixture's
        # ids happen to run the other way, so the test says what it means
        # instead of passing by luck.
        if self.company_b.id < self.company_a.id:
            self.skipTest("fixture ids run the other way; see sibling test")
        self.assertGreater(self.company_b.id, self.company_a.id)
        resolved = resolve_company_id(
            employee=self.staff_a,
            building=self.building_b,
            actor=self.sa,
        )
        self.assertEqual(resolved, self.company_b.id)
        self.assertNotEqual(
            resolved,
            sorted({self.company_a.id, self.company_b.id})[0],
            "resolved to the lower company id — the old guess is back",
        )

    def test_no_building_and_two_companies_refuses_rather_than_guessing(self):
        # THE CASE THE AUDIT FOUND. Nothing on the row settles it, so the
        # honest answer is an error the operator can act on, not a coin
        # flip that mis-files a standing agreement.
        with self.assertRaises(ContractHoursCompanyError):
            resolve_company_id(
                employee=self.staff_a, building=None, actor=self.sa
            )

    def test_no_building_and_one_company_resolves_cleanly(self):
        # The common case must not be collateral damage of the fix.
        self.assertEqual(
            resolve_company_id(
                employee=self.staff_b, building=None, actor=self.sa
            ),
            self.company_b.id,
        )

    def test_actor_scope_narrows_the_candidates(self):
        # A company admin of A only ever anchors rows in A, even for an
        # employee who is also in B.
        self.assertEqual(
            resolve_company_id(
                employee=self.staff_a, building=None, actor=self.ca_a
            ),
            self.company_a.id,
        )

    def test_employee_outside_the_buildings_company_is_refused(self):
        # The row would claim somebody works at a building whose company
        # does not employ them.
        with self.assertRaises(ContractHoursCompanyError):
            resolve_company_id(
                employee=self.staff_b,
                building=self.building_a,
                actor=self.sa,
            )

    def test_employee_the_actor_does_not_manage_is_refused(self):
        with self.assertRaises(ContractHoursCompanyError):
            resolve_company_id(
                employee=self.staff_b, building=None, actor=self.ca_a
            )


class CreateThroughTheApiTests(DualCompanyEmployeeFixture):
    def test_created_row_is_anchored_by_its_building(self):
        response = self.api(self.sa).post(
            CONTRACT_HOURS_URL,
            self._payload(building=self.building_b.id),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        row = ContractHours.objects.get(pk=response.data["id"])
        self.assertEqual(row.company_id, self.company_b.id)

    def test_ambiguous_create_is_a_400_not_a_silent_wrong_company(self):
        response = self.api(self.sa).post(
            CONTRACT_HOURS_URL,
            self._payload(building=None),
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("employee", response.data)
        self.assertEqual(ContractHours.objects.count(), 0)


class UpdateReResolvesTests(DualCompanyEmployeeFixture):
    """The second half of the finding: the anchor was never re-checked."""

    def _make_row(self):
        return ContractHours.objects.create(
            company=self.company_a,
            employee=self.staff_a,
            building=self.building_a,
            hour_type=self.normal_a,
            valid_from=date(2026, 1, 1),
            monday=Decimal("3.00"),
            created_by=self.ca_a,
        )

    def test_moving_the_row_to_another_companys_building_moves_the_company(self):
        row = self._make_row()
        self.assertEqual(row.company_id, self.company_a.id)

        response = self.api(self.sa).patch(
            detail_url(row.id),
            {"building": self.building_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(
            row.company_id,
            self.company_b.id,
            "the row still belongs to the company it was created in",
        )

    def test_an_unrelated_edit_does_not_move_the_row_between_tenants(self):
        # Re-resolving on EVERY patch would make an hours edit a tenant
        # move as a side effect, and would start failing the new
        # ambiguity rule for rows that already exist.
        row = self._make_row()
        response = self.api(self.sa).patch(
            detail_url(row.id), {"tuesday": "4.00"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        row.refresh_from_db()
        self.assertEqual(row.company_id, self.company_a.id)
        self.assertEqual(row.tuesday, Decimal("4.00"))

    def test_patching_the_employee_re_resolves_too(self):
        # `staff_b` is only in company B, and the row's building is A's,
        # so this patch must be refused rather than silently leaving a
        # company-A row whose employee is not in company A.
        row = self._make_row()
        response = self.api(self.sa).patch(
            detail_url(row.id), {"employee": self.staff_b.id}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        row.refresh_from_db()
        self.assertEqual(row.company_id, self.company_a.id)
        self.assertEqual(row.employee_id, self.staff_a.id)
