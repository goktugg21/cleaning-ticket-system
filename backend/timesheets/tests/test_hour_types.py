"""
Sprint 152 — the hour-type catalog: per-company uniqueness, the
no-oracle duplicate pre-check, archiving, PROTECT-on-delete, the
standard set, and cross-company isolation.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import IntegrityError, transaction

from timesheets.models import HourType
from timesheets.standard_set import STANDARD_HOUR_TYPES

from .fixtures import (
    HOUR_TYPES_URL,
    STANDARD_SET_URL,
    TimesheetsFixture,
    hour_type_detail_url,
)


class HourTypeUniquenessTests(TimesheetsFixture):
    def test_same_name_allowed_in_two_companies(self):
        # Both fixture companies already carry "Normale uren"; the row
        # existing at all is the assertion.
        self.assertEqual(
            HourType.objects.filter(name="Normale uren").count(), 2
        )

    def test_duplicate_name_per_company_rejected_at_db_level(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HourType.objects.create(
                    company=self.company_a, name="normale UREN "
                )

    def test_duplicate_name_returns_friendly_400(self):
        response = self.api(self.ca_a).post(
            HOUR_TYPES_URL,
            {"name": "  overwerk ", "multiplier": "1.50"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["name"][0].code, "hour_type_name_not_unique"
        )

    def test_rename_onto_a_sibling_name_rejected(self):
        response = self.api(self.ca_a).patch(
            hour_type_detail_url(self.overtime_a.id),
            {"name": "Normale uren"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["name"][0].code, "hour_type_name_not_unique"
        )

    def test_renaming_a_row_to_its_own_name_is_allowed(self):
        response = self.api(self.ca_a).patch(
            hour_type_detail_url(self.overtime_a.id),
            {"name": "Overwerk", "sort_order": 25},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sort_order"], 25)


class HourTypeNoOracleTests(TimesheetsFixture):
    """RBAC H-1 / the Sprint 142.1 defect class.

    A COMPANY_ADMIN of company A aims the create endpoint at company B.
    The two cases — B already owns that name, B does not — must produce
    BYTE-IDENTICAL responses. If they differ, the status code alone
    reports whether a rival provider carries an hour type by that name.
    """

    def _post_at_company_b(self, name):
        return self.api(self.ca_a).post(
            HOUR_TYPES_URL,
            {"name": name, "multiplier": "1.00", "company": self.company_b.id},
            format="json",
        )

    def test_foreign_company_existing_name_and_novel_name_are_identical(self):
        # "Normale uren" EXISTS in company B; "Nachtdienst" does not.
        existing = self._post_at_company_b("Normale uren")
        novel = self._post_at_company_b("Nachtdienst")

        self.assertEqual(existing.status_code, 403)
        self.assertEqual(novel.status_code, 403)
        self.assertEqual(existing.data, novel.data)
        self.assertEqual(
            existing.data["code"], "timesheet_cross_company_forbidden"
        )

    def test_no_name_is_echoed_back_for_a_foreign_company(self):
        response = self._post_at_company_b("Normale uren")
        self.assertNotIn("Normale uren", str(response.data))

    def test_nothing_is_written_into_the_rival_company(self):
        self._post_at_company_b("Nachtdienst")
        self.assertFalse(
            HourType.objects.filter(
                company=self.company_b, name="Nachtdienst"
            ).exists()
        )


class HourTypeRoleMatrixTests(TimesheetsFixture):
    def test_customer_user_is_forbidden_on_every_method(self):
        client = self.api(self.customer_user)
        self.assertEqual(client.get(HOUR_TYPES_URL).status_code, 403)
        self.assertEqual(
            client.post(
                HOUR_TYPES_URL, {"name": "X"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            client.get(hour_type_detail_url(self.normal_a.id)).status_code, 403
        )
        self.assertEqual(
            client.patch(
                hour_type_detail_url(self.normal_a.id),
                {"name": "Y"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.delete(
                hour_type_detail_url(self.normal_a.id)
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(STANDARD_SET_URL, {}, format="json").status_code, 403
        )

    def test_staff_may_read_but_not_write(self):
        client = self.api(self.staff_a)
        self.assertEqual(client.get(HOUR_TYPES_URL).status_code, 200)
        self.assertEqual(
            client.post(
                HOUR_TYPES_URL, {"name": "Zelfbedacht"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            client.patch(
                hour_type_detail_url(self.normal_a.id),
                {"multiplier": "9.00"},
                format="json",
            ).status_code,
            403,
        )

    def test_building_manager_may_read_but_not_write(self):
        client = self.api(self.bm_a)
        self.assertEqual(client.get(HOUR_TYPES_URL).status_code, 200)
        self.assertEqual(
            client.post(
                HOUR_TYPES_URL, {"name": "Zelfbedacht"}, format="json"
            ).status_code,
            403,
        )

    def test_company_admin_creates_in_own_company_without_naming_it(self):
        response = self.api(self.ca_a).post(
            HOUR_TYPES_URL,
            {"name": "Nachtdienst", "multiplier": "1.25"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["company"], self.company_a.id)

    def test_super_admin_must_name_a_company_when_several_exist(self):
        response = self.api(self.sa).post(
            HOUR_TYPES_URL, {"name": "Nachtdienst"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["company"][0].code, "timesheet_company_required"
        )

    def test_super_admin_creates_in_the_named_company(self):
        response = self.api(self.sa).post(
            HOUR_TYPES_URL,
            {"name": "Nachtdienst", "company": self.company_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["company"], self.company_b.id)


class HourTypeScopeTests(TimesheetsFixture):
    def test_company_admin_lists_only_own_company(self):
        response = self.api(self.ca_a).get(HOUR_TYPES_URL)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.normal_a.id, self.overtime_a.id})
        self.assertNotIn(self.normal_b.id, ids)

    def test_staff_lists_only_own_company(self):
        response = self.api(self.staff_a).get(HOUR_TYPES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertNotIn(self.normal_b.id, ids)

    def test_foreign_detail_is_404_not_403(self):
        # 404, so an out-of-scope id is indistinguishable from a
        # fictional one.
        response = self.api(self.ca_a).get(
            hour_type_detail_url(self.normal_b.id)
        )
        self.assertEqual(response.status_code, 404)

    def test_company_query_param_cannot_widen(self):
        response = self.api(self.ca_a).get(
            HOUR_TYPES_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_super_admin_sees_both_companies_unfiltered(self):
        response = self.api(self.sa).get(HOUR_TYPES_URL)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.normal_a.id, ids)
        self.assertIn(self.normal_b.id, ids)


class HourTypeLifecycleTests(TimesheetsFixture):
    def test_multiplier_bounds_rejected(self):
        client = self.api(self.ca_a)
        too_big = client.post(
            HOUR_TYPES_URL,
            {"name": "Te hoog", "multiplier": "10.00"},
            format="json",
        )
        self.assertEqual(too_big.status_code, 400)
        negative = client.post(
            HOUR_TYPES_URL,
            {"name": "Negatief", "multiplier": "-1.00"},
            format="json",
        )
        self.assertEqual(negative.status_code, 400)

    def test_zero_multiplier_is_legal(self):
        response = self.api(self.ca_a).post(
            HOUR_TYPES_URL,
            {"name": "Onbetaald verlof", "multiplier": "0.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data["multiplier"]), Decimal("0.00"))

    def test_unused_type_can_be_deleted(self):
        response = self.api(self.ca_a).delete(
            hour_type_detail_url(self.overtime_a.id)
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            HourType.objects.filter(pk=self.overtime_a.pk).exists()
        )

    def test_used_type_delete_is_a_friendly_400(self):
        self.make_entry(self.staff_a, dt.date(2026, 8, 3), self.normal_a)
        response = self.api(self.ca_a).delete(
            hour_type_detail_url(self.normal_a.id)
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "hour_type_protected")
        self.assertTrue(HourType.objects.filter(pk=self.normal_a.pk).exists())

    def test_entry_count_drives_the_delete_affordance(self):
        self.make_entry(self.staff_a, dt.date(2026, 8, 3), self.normal_a)
        response = self.api(self.ca_a).get(HOUR_TYPES_URL)
        counts = {
            row["id"]: row["entry_count"] for row in response.data["results"]
        }
        self.assertEqual(counts[self.normal_a.id], 1)
        self.assertEqual(counts[self.overtime_a.id], 0)

    def test_archiving_keeps_the_row_and_its_entries(self):
        entry = self.make_entry(
            self.staff_a, dt.date(2026, 8, 3), self.normal_a
        )
        response = self.api(self.ca_a).patch(
            hour_type_detail_url(self.normal_a.id),
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.hour_type_id, self.normal_a.id)

    def test_is_active_filter(self):
        self.overtime_a.is_active = False
        self.overtime_a.save(update_fields=["is_active"])
        response = self.api(self.staff_a).get(
            HOUR_TYPES_URL, {"is_active": "true"}
        )
        ids = {row["id"] for row in response.data["results"]}
        self.assertEqual(ids, {self.normal_a.id})

    def test_company_is_pinned_on_update(self):
        response = self.api(self.sa).patch(
            hour_type_detail_url(self.normal_a.id),
            {"company": self.company_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.normal_a.refresh_from_db()
        self.assertEqual(self.normal_a.company_id, self.company_a.id)


class StandardSetTests(TimesheetsFixture):
    def test_standard_set_creates_the_missing_ones_and_skips_the_rest(self):
        response = self.api(self.ca_a).post(STANDARD_SET_URL, {}, format="json")
        self.assertEqual(response.status_code, 201)
        # "Normale uren" and "Overwerk" already exist in company A.
        self.assertEqual(sorted(response.data["skipped"]),
                         ["Normale uren", "Overwerk"])
        self.assertEqual(response.data["created_count"], 4)
        self.assertEqual(
            HourType.objects.filter(company=self.company_a).count(),
            len(STANDARD_HOUR_TYPES),
        )

    def test_standard_set_is_idempotent(self):
        self.api(self.ca_a).post(STANDARD_SET_URL, {}, format="json")
        second = self.api(self.ca_a).post(STANDARD_SET_URL, {}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["created_count"], 0)
        self.assertEqual(second.data["skipped_count"], len(STANDARD_HOUR_TYPES))
        self.assertEqual(
            HourType.objects.filter(company=self.company_a).count(),
            len(STANDARD_HOUR_TYPES),
        )

    def test_skip_is_case_and_whitespace_insensitive(self):
        HourType.objects.create(company=self.company_b, name="  vakantie ")
        self.api(self.ca_b).post(STANDARD_SET_URL, {}, format="json")
        self.assertEqual(
            HourType.objects.filter(company=self.company_b).count(),
            # 2 pre-existing (Normale uren + the padded "vakantie"),
            # 4 created — Vakantie was skipped on the fuzzy match.
            len(STANDARD_HOUR_TYPES),
        )

    def test_standard_set_cannot_target_a_rival_company(self):
        response = self.api(self.ca_a).post(
            STANDARD_SET_URL, {"company": self.company_b.id}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            HourType.objects.filter(company=self.company_b).count(), 1
        )

    def test_multipliers_match_the_declared_set(self):
        self.api(self.ca_b).post(STANDARD_SET_URL, {}, format="json")
        created = {
            h.name: h.multiplier
            for h in HourType.objects.filter(company=self.company_b)
        }
        for name, multiplier, _sort in STANDARD_HOUR_TYPES:
            self.assertEqual(created[name], multiplier, name)
