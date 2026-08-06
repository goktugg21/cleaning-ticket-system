"""
Sprint 152.3 — `HourType.standard_slot`: derivation, detach/re-attach,
the migration's backfill rule, and the slot on every payload.

The design under test: `name` stays ONE operator-typed column, and the
six STANDARD kinds are RECOGNISED from it rather than stored in
per-language columns. So the slot must be a pure function of the name at
all times, from every write path.
"""
from __future__ import annotations

import datetime as dt

from timesheets.models import HourType
from timesheets.standard_set import (
    SLOT_OVERTIME,
    SLOT_VACATION,
    STANDARD_SLOTS,
    render_standard_label,
    slot_for_name,
)

from .fixtures import (
    ENTRIES_URL,
    HOUR_TYPES_URL,
    STANDARD_SET_URL,
    SUMMARY_CSV_URL,
    SUMMARY_URL,
    TimesheetsFixture,
    hour_type_detail_url,
)


MONDAY = dt.date(2026, 8, 3)


class SlotDerivationTests(TimesheetsFixture):
    """`save()` is the single derivation point, so a DIRECT ORM write
    must derive the slot too — not only a write through the API.
    """

    def test_dutch_name_attaches_via_orm(self):
        row = HourType.objects.create(
            company=self.company_b, name="Overwerk"
        )
        self.assertEqual(row.standard_slot, SLOT_OVERTIME)
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, SLOT_OVERTIME)

    def test_english_name_attaches_via_orm(self):
        row = HourType.objects.create(company=self.company_b, name="Overtime")
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, SLOT_OVERTIME)

    def test_custom_name_stays_blank(self):
        row = HourType.objects.create(
            company=self.company_b, name="Nachtdienst"
        )
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, "")

    def test_derivation_is_case_and_whitespace_insensitive(self):
        row = HourType.objects.create(
            company=self.company_b, name="  OVERTIME  "
        )
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, SLOT_OVERTIME)

    def test_every_standard_name_in_both_languages_attaches(self):
        for slot, nl_name, en_name, _multiplier, _sort in STANDARD_SLOTS:
            self.assertEqual(slot_for_name(nl_name), slot, nl_name)
            self.assertEqual(slot_for_name(en_name), slot, en_name)

    def test_fixture_rows_attached_on_creation(self):
        # The fixture creates its hour types through the ORM, so they go
        # through `save()` like anything else.
        self.normal_a.refresh_from_db()
        self.overtime_a.refresh_from_db()
        self.assertEqual(self.normal_a.standard_slot, "normal_hours")
        self.assertEqual(self.overtime_a.standard_slot, SLOT_OVERTIME)

    def test_a_client_cannot_set_the_slot(self):
        response = self.api(self.ca_a).post(
            HOUR_TYPES_URL,
            {
                "name": "Nachtdienst",
                "multiplier": "1.25",
                "standard_slot": SLOT_VACATION,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["standard_slot"], "")


class SlotDetachReattachTests(TimesheetsFixture):
    """The slot is DERIVED, never latched — so detaching and
    re-attaching must be symmetric.
    """

    def test_renaming_to_a_custom_name_detaches(self):
        response = self.api(self.ca_a).patch(
            hour_type_detail_url(self.overtime_a.id),
            {"name": "Extra ploegendienst"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.overtime_a.refresh_from_db()
        self.assertEqual(self.overtime_a.standard_slot, "")
        # And the typed name is kept verbatim.
        self.assertEqual(self.overtime_a.name, "Extra ploegendienst")

    def test_renaming_back_in_dutch_reattaches(self):
        self.overtime_a.name = "Extra ploegendienst"
        self.overtime_a.save()
        self.assertEqual(self.overtime_a.standard_slot, "")

        self.overtime_a.name = "Overwerk"
        self.overtime_a.save()
        self.overtime_a.refresh_from_db()
        self.assertEqual(self.overtime_a.standard_slot, SLOT_OVERTIME)

    def test_renaming_back_in_english_reattaches(self):
        self.overtime_a.name = "Extra ploegendienst"
        self.overtime_a.save()
        response = self.api(self.ca_a).patch(
            hour_type_detail_url(self.overtime_a.id),
            {"name": "Overtime"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["standard_slot"], SLOT_OVERTIME)

    def test_a_targeted_save_cannot_leave_a_stale_slot(self):
        """`save(update_fields=["name"])` must carry `standard_slot`
        with it — otherwise the row would persist a new name beside the
        old slot, the exact contradiction the derivation prevents.
        """
        self.overtime_a.name = "Nachtploeg"
        self.overtime_a.save(update_fields=["name", "updated_at"])
        self.overtime_a.refresh_from_db()
        self.assertEqual(self.overtime_a.name, "Nachtploeg")
        self.assertEqual(self.overtime_a.standard_slot, "")

    def test_a_custom_name_matching_a_standard_word_attaches(self):
        """Accepted and intended: it is the same word for the same
        concept, and a stored flag would drift from the name instead.
        """
        row = HourType.objects.create(company=self.company_b, name="Vakantie")
        self.assertEqual(row.standard_slot, SLOT_VACATION)


class SlotBackfillTests(TimesheetsFixture):
    """The data migration's rule.

    Tests the shared derivation the migration CALLS, rather than
    re-running the migration itself — `0003` imports `slot_for_name` and
    does nothing else, so duplicating the name list here would create the
    second source of truth the migration was written to avoid.
    """

    def test_backfill_rule_attaches_pre_existing_rows(self):
        # Simulate a pre-152.3 row: created, then the column blanked, as
        # `0002`'s default would have left it.
        row = HourType.objects.create(company=self.company_b, name="Feestdag")
        HourType.objects.filter(pk=row.pk).update(standard_slot="")
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, "")

        # What the migration does, on the row it finds.
        derived = slot_for_name(row.name)
        HourType.objects.filter(pk=row.pk).update(standard_slot=derived)
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, "public_holiday")

    def test_backfill_leaves_custom_rows_blank(self):
        row = HourType.objects.create(company=self.company_b, name="Nachtwerk")
        self.assertEqual(slot_for_name(row.name), "")

    def test_reverse_rule_clears_every_slot(self):
        HourType.objects.exclude(standard_slot="").update(standard_slot="")
        self.assertFalse(
            HourType.objects.exclude(standard_slot="").exists()
        )
        # And forwards reconstructs it exactly — nothing is lost, because
        # the value is derived.
        for row in HourType.objects.all():
            HourType.objects.filter(pk=row.pk).update(
                standard_slot=slot_for_name(row.name)
            )
        self.normal_a.refresh_from_db()
        self.assertEqual(self.normal_a.standard_slot, "normal_hours")


class StandardSetSlotSkipTests(TimesheetsFixture):
    """Cross-language idempotency, now via the slot. The Sprint 152.1
    tests for this are UNCHANGED and still pass; these add the slot's own
    path.
    """

    def test_slot_check_skips_a_renamed_language_variant(self):
        HourType.objects.filter(company=self.company_b).delete()
        HourType.objects.create(company=self.company_b, name="Overtime")

        self.ca_b.language = "nl"
        self.ca_b.save(update_fields=["language"])
        response = self.api(self.ca_b).post(
            STANDARD_SET_URL, {}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        names = set(
            HourType.objects.filter(company=self.company_b).values_list(
                "name", flat=True
            )
        )
        self.assertIn("Overtime", names)
        self.assertNotIn("Overwerk", names)
        self.assertEqual(len(names), len(STANDARD_SLOTS))

    def test_a_row_with_no_slot_is_still_skipped_by_the_alias_backstop(self):
        """A pre-152.3 row that the migration somehow missed: the slot is
        blank, so only the NAME alias check can catch it.
        """
        HourType.objects.filter(company=self.company_b).delete()
        row = HourType.objects.create(company=self.company_b, name="Vakantie")
        HourType.objects.filter(pk=row.pk).update(standard_slot="")

        self.api(self.ca_b).post(STANDARD_SET_URL, {}, format="json")
        self.assertEqual(
            HourType.objects.filter(company=self.company_b).count(),
            len(STANDARD_SLOTS),
        )


class SlotInPayloadsTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        self.custom = HourType.objects.create(
            company=self.company_a, name="Nachtdienst", multiplier="1.25"
        )
        self.make_entry(self.staff_a, MONDAY, self.overtime_a, "4.00")
        self.make_entry(self.staff_a, MONDAY, self.custom, "2.00")

    def test_hour_type_payload(self):
        response = self.api(self.ca_a).get(HOUR_TYPES_URL)
        by_id = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(
            by_id[self.overtime_a.id]["standard_slot"], SLOT_OVERTIME
        )
        self.assertEqual(by_id[self.custom.id]["standard_slot"], "")
        # `name` still carries the STORED value in every payload.
        self.assertEqual(by_id[self.overtime_a.id]["name"], "Overwerk")
        self.assertEqual(by_id[self.custom.id]["name"], "Nachtdienst")

    def test_time_entry_payload(self):
        response = self.api(self.ca_a).get(ENTRIES_URL)
        rows = {
            row["hour_type"]: row for row in response.data["results"]
        }
        self.assertEqual(
            rows[self.overtime_a.id]["hour_type_standard_slot"], SLOT_OVERTIME
        )
        self.assertEqual(rows[self.custom.id]["hour_type_standard_slot"], "")
        self.assertEqual(rows[self.overtime_a.id]["hour_type_name"], "Overwerk")
        self.assertEqual(rows[self.custom.id]["hour_type_name"], "Nachtdienst")

    def test_summary_bucket_payload(self):
        response = self.api(self.ca_a).get(
            SUMMARY_URL, {"company": self.company_a.id}
        )
        buckets = {
            row["hour_type"]: row for row in response.data["by_hour_type"]
        }
        self.assertEqual(
            buckets[self.overtime_a.id]["standard_slot"], SLOT_OVERTIME
        )
        self.assertEqual(buckets[self.custom.id]["standard_slot"], "")
        self.assertEqual(
            buckets[self.overtime_a.id]["hour_type_name"], "Overwerk"
        )


class CsvLabelLanguageTests(TimesheetsFixture):
    """The CSV is the ONE surface that resolves the label server-side."""

    def setUp(self):
        super().setUp()
        self.custom = HourType.objects.create(
            company=self.company_a, name="Nachtdienst", multiplier="1.25"
        )
        self.make_entry(self.staff_a, MONDAY, self.overtime_a, "4.00")
        self.make_entry(self.staff_a, MONDAY, self.custom, "2.00")

    def _csv_labels(self, user):
        response = self.api(user).get(
            SUMMARY_CSV_URL, {"company": self.company_a.id}
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8").lstrip("﻿")
        return [
            line.split(",")[2]
            for line in body.splitlines()
            if line.startswith("HOUR_TYPE,")
        ]

    def test_english_user_gets_english_labels(self):
        self.ca_a.language = "en"
        self.ca_a.save(update_fields=["language"])
        labels = self._csv_labels(self.ca_a)
        self.assertIn("Overtime", labels)
        self.assertNotIn("Overwerk", labels)

    def test_dutch_user_gets_dutch_labels(self):
        self.ca_a.language = "nl"
        self.ca_a.save(update_fields=["language"])
        labels = self._csv_labels(self.ca_a)
        self.assertIn("Overwerk", labels)
        self.assertNotIn("Overtime", labels)

    def test_custom_type_keeps_its_stored_name_in_both_languages(self):
        for language in ("nl", "en"):
            self.ca_a.language = language
            self.ca_a.save(update_fields=["language"])
            self.assertIn("Nachtdienst", self._csv_labels(self.ca_a), language)

    def test_render_helper_fallbacks(self):
        self.assertEqual(
            render_standard_label("", "Nachtdienst", "en"), "Nachtdienst"
        )
        # Unknown language -> Dutch (the project's primary).
        self.assertEqual(
            render_standard_label(SLOT_OVERTIME, "Overwerk", "de"), "Overwerk"
        )
        self.assertEqual(
            render_standard_label(SLOT_OVERTIME, "Overwerk", None), "Overwerk"
        )
        # An unknown slot key falls back to the stored name rather than
        # rendering nothing.
        self.assertEqual(
            render_standard_label("no_such_slot", "Iets", "en"), "Iets"
        )
