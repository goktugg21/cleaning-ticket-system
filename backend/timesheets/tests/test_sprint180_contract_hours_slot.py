"""
Sprint 180 §4 — `work_type_standard_slot` on the contract-hours payload.

`WorkType.standard_slot` exists so the UI can print a recognised work
type in the READER's language while `name` stays one operator-typed
column — the `HourType.standard_slot` pattern, added in Sprint 170 §5.
`frontend/.../ContractHoursTab.tsx` declared the field and fed it to
`workTypeLabel()` from that day, and `ContractHoursSerializer` never
sent it. The value was permanently `undefined`, the helper fell back to
the stored name, and an English reader looking at a standard Dutch work
type read Dutch — the exact bug the slot exists to prevent, fixed on the
work-type catalog endpoints and missed on this read path.

A filter test would not have caught it: it issues a query and never
serialises a row. So these render the endpoint and read the field off
the payload, which is the only shape of test that can fail when a
`fields` entry is missing.
"""

from datetime import date

from rest_framework import status

from timesheets.models import ContractHours, WorkType

from .fixtures import TimesheetsFixture


URL = "/api/timesheets/contract-hours/"


class ContractHoursSlotPayloadTests(TimesheetsFixture):
    def mk_row(self, work_type=None):
        return ContractHours.objects.create(
            company=self.company_a,
            employee=self.staff_a,
            building=self.building_a,
            hour_type=self.normal_a,
            work_type=work_type,
            valid_from=date(2026, 1, 1),
            monday="8.00",
            created_by=self.ca_a,
        )

    def get_rows(self):
        response = self.api(self.ca_a).get(URL, {"company": self.company_a.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data
        return data["results"] if isinstance(data, dict) else data

    def test_the_list_renders_the_slot_beside_the_name(self):
        # "Meerwerk" is one of the four recognised kinds, so `save()`
        # derives `standard_slot` for it — that derivation is the whole
        # reason the field is worth sending.
        work_type = WorkType.objects.create(
            company=self.company_a, name="Meerwerk"
        )
        self.assertNotEqual(work_type.standard_slot, "")
        row = self.mk_row(work_type=work_type)

        payload = {item["id"]: item for item in self.get_rows()}[row.id]
        self.assertIn("work_type_standard_slot", payload)
        self.assertEqual(payload["work_type_name"], "Meerwerk")
        self.assertEqual(
            payload["work_type_standard_slot"], work_type.standard_slot
        )

    def test_a_custom_work_type_renders_an_empty_slot(self):
        # A company's own word for its own kind of work: no slot, and the
        # frontend helper then renders the stored name, which is correct.
        work_type = WorkType.objects.create(
            company=self.company_a, name="Gevelreiniging"
        )
        self.assertEqual(work_type.standard_slot, "")
        row = self.mk_row(work_type=work_type)

        payload = {item["id"]: item for item in self.get_rows()}[row.id]
        self.assertEqual(payload["work_type_standard_slot"], "")

    def test_a_row_without_a_work_type_renders_null_not_a_missing_key(self):
        # The FK is nullable, and traversing `work_type.standard_slot` on
        # a row that has none must render rather than raise. The `default`
        # on the serializer field is what makes this true.
        row = self.mk_row(work_type=None)

        payload = {item["id"]: item for item in self.get_rows()}[row.id]
        self.assertIn("work_type_standard_slot", payload)
        self.assertIsNone(payload["work_type_standard_slot"])
        self.assertIsNone(payload["work_type_name"])
