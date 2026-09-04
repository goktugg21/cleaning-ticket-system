"""
Sprint 173 §1 — where an hour came from.

`TimeEntry` now carries a `(source_type, source_id)` pair and resolves
neither: `timesheets` imports nothing from `tickets` or `extra_work`,
so the resolution lives in `reports/`, the app that may read across.

What these pin are the two consequences the prompt said to handle
rather than discover later:

  * an id that no longer resolves renders as a plain label and never
    breaks a screen;
  * a source id must never expose a record the actor could not open
    anyway — a foreign id yields NO title, the same answer a fictional
    one gives, which is the H-1 equivalence.

Plus the reason the pair exists at all: `timesheets` must not import
the modules whose ids it stores.
"""
from __future__ import annotations

from datetime import date

from reports.hour_sources import resolve_sources, source_label
from tickets.models import Ticket, TicketType
from timesheets.models import HourSource, TimeEntry

from timesheets.tests.fixtures import TimesheetsFixture


MONDAY = date(2026, 3, 2)


class ModuleIndependenceTests(TimesheetsFixture):
    def test_timesheets_does_not_import_tickets_or_extra_work(self):
        """The architectural rule the type+id pair exists to keep.

        A source scanned rather than inferred: four nullable foreign
        keys would have been the obvious modelling and would have made
        the hours module depend on both of the others.
        """
        import pathlib

        import timesheets

        root = pathlib.Path(timesheets.__file__).parent
        offenders = []
        for path in root.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            # P-16 repin — the boundary is MODULE-LOAD independence:
            # no top-level import of tickets/extra_work (four nullable
            # FKs stay impossible). A CALL-TIME import inside a
            # function is the documented seam (`_source_in_scope`
            # resolves a source id through the owning module's scoper
            # "imported at call time so this module keeps its import
            # boundary" — its own words). Scan unindented lines only.
            for line in path.read_text(encoding="utf-8").splitlines():
                if line != line.lstrip():
                    continue  # indented = call-time, the allowed seam
                for forbidden in (
                    "from tickets",
                    "import tickets",
                    "from extra_work",
                ):
                    if line.startswith(forbidden):
                        offenders.append(f"{path.name}: {forbidden}")
        self.assertEqual(offenders, [])

    def test_the_source_is_a_pair_not_a_foreign_key(self):
        field = TimeEntry._meta.get_field("source_id")
        self.assertIsNone(getattr(field, "related_model", None))

    def test_an_existing_row_defaults_to_OTHER(self):
        """Not backfilled with a guess: every row written before the
        column existed has a real source nobody recorded."""
        entry = self.make_entry(
            self.staff_a, MONDAY, self.normal_a, company=self.company_a
        )
        self.assertEqual(entry.source_type, HourSource.OTHER)
        self.assertIsNone(entry.source_id)


class ResolutionTests(TimesheetsFixture):
    def setUp(self):
        super().setUp()
        from customers.models import Customer

        self.customer = Customer.objects.create(
            company=self.company_a, name="Res customer", contact_email="r@x.nl"
        )
        self.ticket = Ticket.objects.create(
            company=self.company_a,
            customer=self.customer,
            building=self.building_a,
            title="Lekkage",
            description="x",
            type=TicketType.REPORT,
            created_by=self.ca_a,
        )

    def test_a_resolvable_ticket_gives_its_title(self):
        titles = resolve_sources(
            self.ca_a, [(HourSource.TICKET, self.ticket.id)]
        )
        label = source_label(HourSource.TICKET, self.ticket.id, titles)
        self.assertIn("Lekkage", label)
        self.assertIn(self.ticket.ticket_no, label)

    def test_an_id_that_no_longer_resolves_renders_as_a_plain_label(self):
        """A ticket can be deleted after its hours were logged. A report
        that raised, or rendered blank, would turn that into a broken
        screen."""
        titles = resolve_sources(self.ca_a, [(HourSource.TICKET, 9_999_999)])
        self.assertEqual(titles, {})
        self.assertEqual(
            source_label(HourSource.TICKET, 9_999_999, titles),
            "Ticket #9999999",
        )

    def test_a_foreign_id_yields_NO_title(self):
        """H-1: the id sits on a row the actor may read, but the TITLE is
        another module's data. An actor who could not open the ticket
        gets the same answer a fictional id gives."""
        titles = resolve_sources(
            self.ca_b, [(HourSource.TICKET, self.ticket.id)]
        )
        self.assertEqual(titles, {})
        # And the label it falls back to leaks nothing but the number
        # the caller already had.
        self.assertEqual(
            source_label(HourSource.TICKET, self.ticket.id, titles),
            f"Ticket #{self.ticket.id}",
        )

    def test_a_foreign_id_and_a_fictional_one_are_indistinguishable(self):
        foreign = resolve_sources(
            self.ca_b, [(HourSource.TICKET, self.ticket.id)]
        )
        fictional = resolve_sources(self.ca_b, [(HourSource.TICKET, 9_999_999)])
        self.assertEqual(foreign, fictional)

    def test_OTHER_with_no_id_has_no_label_at_all(self):
        """Different from "recorded but gone": nobody said, and the UI
        shows an em dash rather than a type name."""
        self.assertIsNone(source_label(HourSource.OTHER, None, {}))

    def test_resolution_is_one_query_per_type_not_per_row(self):
        others = [
            Ticket.objects.create(
                company=self.company_a,
                customer=self.customer,
                building=self.building_a,
                title=f"T{n}",
                description="x",
                type=TicketType.REPORT,
                created_by=self.ca_a,
            )
            for n in range(5)
        ]
        pairs = [(HourSource.TICKET, t.id) for t in others]
        with self.assertNumQueries(1):
            titles = resolve_sources(self.ca_a, pairs)
        self.assertEqual(len(titles), 5)


class FilterTests(TimesheetsFixture):
    def test_the_entries_filter_narrows_by_source(self):
        contract_entry = self.make_entry(
            self.staff_a, MONDAY, self.normal_a, company=self.company_a
        )
        contract_entry.source_type = HourSource.CONTRACT
        contract_entry.save(update_fields=["source_type"])
        self.make_entry(
            self.staff_a, MONDAY, self.normal_a, hours="2.00", company=self.company_a
        )

        client = self.api(self.ca_a)
        response = client.get(
            "/api/timesheets/entries/", {"source_type": "CONTRACT"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["source_type"], HourSource.CONTRACT
        )

    def test_an_unrecognised_source_yields_nothing_not_everything(self):
        """Silently returning everything reads as "the filter is off"
        when the operator believes it is on."""
        self.make_entry(
            self.staff_a, MONDAY, self.normal_a, company=self.company_a
        )
        client = self.api(self.ca_a)
        response = client.get(
            "/api/timesheets/entries/", {"source_type": "NONSENSE"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
