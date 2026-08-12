"""
Sprint 169 §4 — contract types read in the reader's language.

The `HourType.standard_slot` pattern (Sprint 152.3) applied to contract
types. What these pin is not the happy path — it is the three
consequences of deriving a slot from a name, each of which is
surprising until you see why it is right:

  * renaming a standard type to the company's own wording DETACHES it,
  * renaming it back, in EITHER language, re-attaches it,
  * a custom type spelled like a standard one reads as the standard one.

Plus the invariant that makes all three safe: the derivation happens in
`save()`, so it cannot be bypassed by a management command, a data
migration or a shell write — none of which go through a serializer.
"""
from __future__ import annotations

from rest_framework import status

from companies.models import Company
from contracts.models import ContractType
from contracts.standard_types import slot_for_name

from .fixtures import ContractsFixture


TYPES_URL = "/api/contracts/types/"
STANDARD_SET_URL = "/api/contracts/types/standard-set/"


class SlotDerivationTests(ContractsFixture):
    """These need to CREATE standard-named types, and the shared fixture
    already gives company_a a "Schoonmaak". Its own company, so the
    per-company uniqueness constraint is not the thing under test."""

    def setUp(self):
        super().setUp()
        self.own = Company.objects.create(name="Slot co", slug="slot-co-169")

    def mk(self, name):
        return ContractType.objects.create(company=self.own, name=name)

    def test_a_standard_dutch_name_gets_its_slot(self):
        self.assertEqual(self.mk("Schoonmaak").standard_slot, "cleaning")

    def test_a_standard_english_name_gets_the_same_slot(self):
        """Both names identify the slot, which is what makes a rename in
        either language re-attach."""
        self.assertEqual(self.mk("Cleaning").standard_slot, "cleaning")

    def test_recognition_ignores_case_and_surrounding_space(self):
        """The same normalisation the uniqueness constraint uses. If the
        two disagreed, a row could be a duplicate by one rule and a
        different slot by the other."""
        self.assertEqual(self.mk("  MACHINEWERK  ").standard_slot, "machine")

    def test_a_company_s_own_name_has_no_slot(self):
        self.assertEqual(self.mk("Gevelreiniging").standard_slot, "")

    def test_renaming_a_standard_type_DETACHES_it(self):
        row = self.mk("Schoonmaak")
        row.name = "Ons schoonmaakwerk"
        row.save()
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, "")
        # And the typed name is kept verbatim — it is theirs now.
        self.assertEqual(row.name, "Ons schoonmaakwerk")

    def test_renaming_it_back_RE_ATTACHES_it(self):
        row = self.mk("Schoonmaak")
        row.name = "Ons schoonmaakwerk"
        row.save()
        row.name = "Cleaning"  # back, in the OTHER language
        row.save()
        row.refresh_from_db()
        self.assertEqual(row.standard_slot, "cleaning")

    def test_the_derivation_cannot_be_bypassed_by_a_client(self):
        """`standard_slot` is read-only on the serializer AND derived in
        save(), so a caller cannot claim a row is a standard kind whose
        name says otherwise."""
        client = self.api(self.sa)
        response = client.post(
            TYPES_URL,
            {
                "company": self.own.id,
                "name": "Gevelreiniging",
                "standard_slot": "cleaning",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["standard_slot"], "")
        self.assertEqual(
            ContractType.objects.get(id=response.data["id"]).standard_slot, ""
        )

    def test_a_custom_name_matching_a_standard_one_reads_as_standard(self):
        """Accepted, and stated: the alternative is a hidden flag that
        makes two identically-named rows behave differently."""
        self.assertEqual(slot_for_name("Overig"), "other")


class StandardSetLanguageTests(ContractsFixture):
    """Seeded into a company with an EMPTY catalog — which is the state
    the button exists for, and company_a already has a type."""

    def setUp(self):
        super().setUp()
        self.own = Company.objects.create(name="Seed co", slug="seed-co-169")

    def test_an_english_operator_seeds_english_names(self):
        self.sa.language = "en"
        self.sa.save(update_fields=["language"])
        client = self.api(self.sa)
        response = client.post(
            STANDARD_SET_URL, {"company": self.own.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("Cleaning", response.data["created"])
        slots = set(
            ContractType.objects.filter(company=self.own).values_list(
                "standard_slot", flat=True
            )
        )
        self.assertEqual(slots, {"cleaning", "extra_work", "machine", "other"})

    def test_pressing_it_in_the_OTHER_language_creates_nothing(self):
        """Idempotent ACROSS languages — the part that needs a test.
        Comparing only the name about to be created would hand a
        Dutch-seeded company four English duplicates, and the
        per-company uniqueness constraint would not object because
        "Meerwerk" and "Extra Works" genuinely are different strings."""
        client = self.api(self.sa)
        self.sa.language = "nl"
        self.sa.save(update_fields=["language"])
        first = client.post(
            STANDARD_SET_URL, {"company": self.own.id}, format="json"
        )
        self.assertEqual(len(first.data["created"]), 4)

        self.sa.language = "en"
        self.sa.save(update_fields=["language"])
        second = client.post(
            STANDARD_SET_URL, {"company": self.own.id}, format="json"
        )
        self.assertEqual(second.data["created"], [])
        self.assertEqual(len(second.data["skipped"]), 4)
        self.assertEqual(
            ContractType.objects.filter(company=self.own).count(), 4
        )

    def test_the_payload_carries_the_slot_for_the_client_to_translate(self):
        client = self.api(self.sa)
        client.post(STANDARD_SET_URL, {"company": self.own.id}, format="json")
        listed = client.get(TYPES_URL, {"company": self.own.id})
        # This endpoint is unpaginated (`pagination_class = None`), so
        # the payload is the list itself, not a page object.
        rows = listed.data
        by_name = {row["name"]: row["standard_slot"] for row in rows}
        self.assertEqual(by_name.get("Meerwerk"), "extra_work")


class ScopingTests(ContractsFixture):
    def test_seeding_another_companys_catalog_is_refused(self):
        other = Company.objects.create(name="Other prov", slug="other-prov-169")
        client = self.api(self.ca_a)
        response = client.post(
            STANDARD_SET_URL, {"company": other.id}, format="json"
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN),
        )
        self.assertEqual(ContractType.objects.filter(company=other).count(), 0)
