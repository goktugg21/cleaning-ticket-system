"""
Sprint 160 — the contracts HTTP surface: the role matrix, tenant
isolation (H-1), and the create / edit paths.

Company B is genuinely populated in the fixture, so every isolation
assertion here is a real one — an isolation test that passes because
the other side is empty proves nothing.
"""
from __future__ import annotations

from datetime import date

from rest_framework import status

from buildings.models import Building
from customers.models import Customer

from contracts.models import Contract, ContractLifecycle, ContractRevision, ContractType

from .fixtures import (
    CONTRACTS_URL,
    OPTIONS_URL,
    STATS_URL,
    TYPES_URL,
    ContractsFixture,
    contract_detail_url,
    contract_forecast_url,
    contract_revisions_url,
    line_detail_url,
    revision_detail_url,
    revision_lines_url,
)


class RoleMatrixTests(ContractsFixture):
    """Who may reach the module at all.

    STAFF and CUSTOMER_USER are 403'd on EVERY endpoint — a contract
    carries the customer's negotiated prices, and this sprint opens no
    customer-facing surface. Tested on every endpoint rather than on a
    representative one, because "403 on the list" has never implied
    "403 on the nested route" in this codebase.
    """

    def endpoints(self):
        return [
            CONTRACTS_URL,
            STATS_URL,
            OPTIONS_URL,
            TYPES_URL,
            contract_detail_url(self.contract_a.id),
            contract_revisions_url(self.contract_a.id),
            contract_forecast_url(self.contract_a.id),
            revision_detail_url(self.contract_a.revisions.get().id),
            revision_lines_url(self.contract_a.revisions.get().id),
        ]

    def test_customer_user_is_forbidden_everywhere(self):
        client = self.api(self.customer_user)
        for url in self.endpoints():
            with self.subTest(url=url):
                self.assertEqual(
                    client.get(url).status_code,
                    status.HTTP_403_FORBIDDEN,
                )

    def test_staff_is_forbidden_everywhere(self):
        client = self.api(self.staff_a)
        for url in self.endpoints():
            with self.subTest(url=url):
                self.assertEqual(
                    client.get(url).status_code,
                    status.HTTP_403_FORBIDDEN,
                )

    def test_anonymous_is_unauthenticated(self):
        from rest_framework.test import APIClient

        response = APIClient().get(CONTRACTS_URL)
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_customer_user_cannot_write_either(self):
        """The read 403 above is the first floor; this is the second.
        A role that cannot GET a resource must not be able to POST it
        by guessing the route."""
        client = self.api(self.customer_user)
        response = client.post(
            CONTRACTS_URL,
            {
                "customer": self.customer_a.id,
                "start_date": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Contract.objects.count(), 3)


class BuildingManagerIsReadOnlyTests(ContractsFixture):
    def test_a_building_manager_may_read(self):
        response = self.api(self.bm_a).get(CONTRACTS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_a_building_manager_may_not_create_edit_or_delete(self):
        client = self.api(self.bm_a)
        create = client.post(
            CONTRACTS_URL,
            {"customer": self.customer_a.id, "start_date": "2026-01-01"},
            format="json",
        )
        patch = client.patch(
            contract_detail_url(self.contract_a.id),
            {"notes": "changed"},
            format="json",
        )
        delete = client.delete(contract_detail_url(self.contract_a.id))
        for response in (create, patch, delete):
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.contract_a.refresh_from_db()
        self.assertEqual(self.contract_a.notes, "")

    def test_a_building_manager_sees_only_contracts_on_their_buildings(self):
        """Narrower than the company scope, and that is the point:
        contract_a2 belongs to the SAME company but covers a building
        bm_a does not manage."""
        response = self.api(self.bm_a).get(CONTRACTS_URL)
        numbers = {row["contract_no"] for row in response.json()["results"]}
        self.assertIn(self.contract_a.contract_no, numbers)
        self.assertNotIn(self.contract_a2.contract_no, numbers)

    def test_a_contract_outside_their_buildings_is_a_404(self):
        response = self.api(self.bm_a).get(
            contract_detail_url(self.contract_a2.id)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TenantIsolationTests(ContractsFixture):
    def test_a_company_admin_sees_only_their_own_contracts(self):
        response = self.api(self.ca_a).get(CONTRACTS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {self.contract_a.id, self.contract_a2.id})

    def test_a_foreign_contract_reads_as_nonexistent(self):
        """404, not 403. 'It exists but is not yours' is the existence
        oracle this module is built to avoid."""
        foreign = self.api(self.ca_a).get(
            contract_detail_url(self.contract_b.id)
        )
        fictional_id = Contract.objects.order_by("-id").first().id + 10_000
        fictional = self.api(self.ca_a).get(contract_detail_url(fictional_id))
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(fictional.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), fictional.json())

    def test_a_foreign_revision_reads_as_nonexistent(self):
        foreign = self.api(self.ca_a).get(
            revision_detail_url(self.contract_b.revisions.get().id)
        )
        fictional_id = (
            ContractRevision.objects.order_by("-id").first().id + 10_000
        )
        fictional = self.api(self.ca_a).get(revision_detail_url(fictional_id))
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), fictional.json())

    def test_a_foreign_forecast_reads_as_nonexistent(self):
        foreign = self.api(self.ca_a).get(
            contract_forecast_url(self.contract_b.id)
        )
        fictional_id = Contract.objects.order_by("-id").first().id + 10_000
        fictional = self.api(self.ca_a).get(contract_forecast_url(fictional_id))
        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), fictional.json())

    def test_stats_count_only_the_actors_own_contracts(self):
        response = self.api(self.ca_a).get(STATS_URL)
        self.assertEqual(response.json()["total"], 2)


class ForeignAndFictionalRejectIdenticallyTests(ContractsFixture):
    """H-1, the property that actually matters: for ONE request shape,
    an id belonging to another tenant and an id that never existed must
    be indistinguishable. Anything else lets a caller walk integer ids
    and learn which ones are real.

    Compared body-for-body, not merely "both are errors" — that weaker
    assertion is what the Sprint 142.1 defect passed.
    """

    def _create(self, **overrides):
        payload = {
            "customer": self.customer_a.id,
            "start_date": "2026-03-01",
            "building_ids": [self.building_a.id],
        }
        payload.update(overrides)
        return self.api(self.ca_a).post(CONTRACTS_URL, payload, format="json")

    def test_foreign_and_fictional_customer_reject_identically(self):
        foreign = self._create(customer=self.customer_b.id)
        fictional_id = Customer.objects.order_by("-id").first().id + 10_000
        fictional = self._create(customer=fictional_id)
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.json(), fictional.json())

    def test_foreign_and_fictional_building_reject_identically(self):
        foreign = self._create(building_ids=[self.building_b.id])
        fictional_id = Building.objects.order_by("-id").first().id + 10_000
        fictional = self._create(building_ids=[fictional_id])
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.json(), fictional.json())

    def test_foreign_and_fictional_contract_type_reject_identically(self):
        foreign = self._create(contract_type=self.type_b.id)
        fictional_id = ContractType.objects.order_by("-id").first().id + 10_000
        fictional = self._create(contract_type=fictional_id)
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.json(), fictional.json())

    def test_a_super_admin_gets_a_real_cross_company_400_instead(self):
        """A SUPER_ADMIN can resolve BOTH ids, so hiding the difference
        would only hide a mistake from someone entitled to see it. The
        distinct code is correct here and an oracle nowhere else,
        because nobody else reaches this branch."""
        response = self.api(self.sa).post(
            CONTRACTS_URL,
            {
                "company": self.company_a.id,
                "customer": self.customer_a.id,
                "start_date": "2026-03-01",
                "building_ids": [self.building_b.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # `.data`, not `.json()`: the CODE is the stable contract the
        # frontend maps on, the message is prose that may be reworded.
        self.assertEqual(
            response.data["building_ids"][0].code, "building_cross_company"
        )


class CreateContractTests(ContractsFixture):
    def test_creating_a_contract_numbers_it_and_gives_it_a_first_revision(self):
        response = self.api(self.ca_a).post(
            CONTRACTS_URL,
            {
                "customer": self.customer_a.id,
                "contract_type": self.type_a.id,
                "start_date": "2027-02-01",
                "building_ids": [self.building_a.id, self.building_a2.id],
                "billing_period": "MONTHLY",
                "billing_day": 5,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["contract_no"], "CNT-2027-0001")
        # A contract is NEVER revision-less.
        self.assertIsNotNone(body["active_revision"])
        self.assertEqual(
            body["active_revision"]["effective_from"], "2027-02-01"
        )
        self.assertEqual(
            {b["id"] for b in body["buildings"]},
            {self.building_a.id, self.building_a2.id},
        )
        contract = Contract.objects.get(id=body["id"])
        self.assertEqual(contract.company, self.company_a)
        self.assertEqual(contract.revisions.count(), 1)

    def test_the_number_year_comes_from_the_start_date(self):
        """A 2028 contract drafted today is a 2028 contract, and its
        number says so."""
        response = self.api(self.ca_a).post(
            CONTRACTS_URL,
            {"customer": self.customer_a.id, "start_date": "2028-06-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["contract_no"], "CNT-2028-0001")

    def test_a_company_admin_cannot_create_for_another_company(self):
        response = self.api(self.ca_a).post(
            CONTRACTS_URL,
            {
                "company": self.company_b.id,
                "customer": self.customer_a.id,
                "start_date": "2027-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_an_end_date_before_the_start_date_is_a_400(self):
        response = self.api(self.ca_a).post(
            CONTRACTS_URL,
            {
                "customer": self.customer_a.id,
                "start_date": "2027-06-01",
                "end_date": "2027-01-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["end_date"][0].code, "end_date_before_start_date"
        )

    def test_the_derived_status_is_serialized(self):
        contract = self.contract_a
        contract.lifecycle = ContractLifecycle.ACTIVE
        # After the contract's own start date (2026-01-01) so the
        # end_after_start CHECK is satisfied, and in the past so the
        # DERIVED status is EXPIRED.
        contract.end_date = date(2026, 6, 30)
        contract.save(update_fields=["lifecycle", "end_date"])
        response = self.api(self.ca_a).get(contract_detail_url(contract.id))
        self.assertEqual(response.json()["status"], "EXPIRED")


class RevisionEndpointTests(ContractsFixture):
    def test_creating_a_revision_copies_the_current_lines(self):
        response = self.api(self.ca_a).post(
            contract_revisions_url(self.contract_a.id),
            {"label": "Prijsverhoging 2027", "effective_from": "2027-01-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(len(body["lines"]), 1)
        self.assertEqual(body["lines"][0]["name"], "Dagelijkse schoonmaak")
        # ...and the previous revision is untouched.
        self.assertEqual(self.contract_a.revisions.count(), 2)

    def test_copy_lines_false_starts_empty(self):
        response = self.api(self.ca_a).post(
            contract_revisions_url(self.contract_a.id),
            {
                "label": "Nieuwe scope",
                "effective_from": "2027-01-01",
                "copy_lines": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["lines"], [])

    def test_a_revision_in_force_cannot_be_edited(self):
        """The whole reason a revision is worth having: if history
        could be edited, last month's invoice total would silently
        change when this month's price did."""
        revision = self.contract_a.revisions.get()
        response = self.api(self.ca_a).patch(
            revision_detail_url(revision.id),
            {"label": "Herschreven"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["revision"][0].code, "revision_locked")

    def test_lines_of_a_revision_in_force_cannot_be_added_or_edited(self):
        revision = self.contract_a.revisions.get()
        line = revision.lines.get()
        add = self.api(self.ca_a).post(
            revision_lines_url(revision.id),
            {"name": "Nieuw project", "amount": "100.00"},
            format="json",
        )
        edit = self.api(self.ca_a).patch(
            line_detail_url(line.id), {"amount": "999.00"}, format="json"
        )
        delete = self.api(self.ca_a).delete(line_detail_url(line.id))
        for response in (add, edit, delete):
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        line.refresh_from_db()
        self.assertEqual(str(line.amount), "1000.00")

    def test_a_future_revision_is_fully_editable(self):
        created = self.api(self.ca_a).post(
            contract_revisions_url(self.contract_a.id),
            {"label": "2027", "effective_from": "2027-01-01"},
            format="json",
        )
        revision_id = created.json()["id"]
        added = self.api(self.ca_a).post(
            revision_lines_url(revision_id),
            {"name": "Extra project", "amount": "250.00", "hours": "5.00"},
            format="json",
        )
        self.assertEqual(added.status_code, status.HTTP_201_CREATED)
        renamed = self.api(self.ca_a).patch(
            revision_detail_url(revision_id),
            {"label": "2027 definitief"},
            format="json",
        )
        self.assertEqual(renamed.status_code, status.HTTP_200_OK)

    def test_a_contract_cannot_lose_its_last_revision(self):
        contract = self.contract_a
        future = ContractRevision.objects.create(
            contract=contract, label="2099", effective_from=date(2099, 1, 1)
        )
        # The future one may go...
        first = self.api(self.ca_a).delete(revision_detail_url(future.id))
        self.assertEqual(first.status_code, status.HTTP_204_NO_CONTENT)
        # ...but the last remaining one is refused, and it is also in
        # force, so both guards agree.
        remaining = contract.revisions.get()
        second = self.api(self.ca_a).delete(revision_detail_url(remaining.id))
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(contract.revisions.count(), 1)

    def test_a_line_may_only_name_a_building_the_contract_covers(self):
        created = self.api(self.ca_a).post(
            contract_revisions_url(self.contract_a.id),
            {"label": "2027", "effective_from": "2027-01-01"},
            format="json",
        )
        revision_id = created.json()["id"]
        # contract_a covers building_a only.
        response = self.api(self.ca_a).post(
            revision_lines_url(revision_id),
            {
                "name": "Project",
                "amount": "100.00",
                "building": self.building_a2.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OptionsEndpointTests(ContractsFixture):
    def test_options_offer_only_the_companys_own_rows(self):
        response = self.api(self.ca_a).get(OPTIONS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(
            {row["id"] for row in body["customers"]}, {self.customer_a.id}
        )
        self.assertEqual(
            {row["id"] for row in body["buildings"]},
            {self.building_a.id, self.building_a2.id},
        )
        self.assertEqual(
            {row["id"] for row in body["contract_types"]}, {self.type_a.id}
        )

    def test_everything_offered_is_accepted_by_the_write_path(self):
        """Offerable equals acceptable BY CONSTRUCTION — the picker and
        the validator read the same scoped querysets. Walked end to end
        rather than asserted structurally, the Sprint 152.1 pattern."""
        options = self.api(self.ca_a).get(OPTIONS_URL).json()
        for customer in options["customers"]:
            for contract_type in options["contract_types"]:
                response = self.api(self.ca_a).post(
                    CONTRACTS_URL,
                    {
                        "customer": customer["id"],
                        "contract_type": contract_type["id"],
                        "start_date": "2029-01-01",
                        "building_ids": [
                            row["id"] for row in options["buildings"]
                        ],
                    },
                    format="json",
                )
                self.assertEqual(
                    response.status_code,
                    status.HTTP_201_CREATED,
                    msg=response.content,
                )

    def test_a_building_manager_cannot_read_the_options(self):
        """The pickers exist to fill in a write form, and a BM has no
        write path here."""
        self.assertEqual(
            self.api(self.bm_a).get(OPTIONS_URL).status_code,
            status.HTTP_403_FORBIDDEN,
        )


class ContractTypeTests(ContractsFixture):
    def test_names_are_unique_per_company_case_insensitively(self):
        first = self.api(self.ca_a).post(
            TYPES_URL, {"name": "Onderhoud"}, format="json"
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        duplicate = self.api(self.ca_a).post(
            TYPES_URL, {"name": "  onderhoud "}, format="json"
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            duplicate.data["name"][0].code, "contract_type_name_not_unique"
        )

    def test_two_companies_may_each_carry_the_same_name(self):
        a = self.api(self.ca_a).post(
            TYPES_URL, {"name": "Gedeeld"}, format="json"
        )
        b = self.api(self.ca_b).post(
            TYPES_URL, {"name": "Gedeeld"}, format="json"
        )
        self.assertEqual(a.status_code, status.HTTP_201_CREATED)
        self.assertEqual(b.status_code, status.HTTP_201_CREATED)

    def test_a_type_in_use_cannot_be_deleted(self):
        from .fixtures import type_detail_url

        response = self.api(self.ca_a).delete(type_detail_url(self.type_a.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(ContractType.objects.filter(id=self.type_a.id).exists())


class FilterTests(ContractsFixture):
    def test_status_filter_uses_the_derived_status(self):
        expired = self.contract_a
        expired.end_date = date(2026, 6, 30)
        expired.lifecycle = ContractLifecycle.ACTIVE
        expired.save(update_fields=["end_date", "lifecycle"])

        response = self.api(self.ca_a).get(CONTRACTS_URL, {"status": "EXPIRED"})
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {expired.id})

        active = self.api(self.ca_a).get(CONTRACTS_URL, {"status": "ACTIVE"})
        self.assertEqual(
            {row["id"] for row in active.json()["results"]},
            {self.contract_a2.id},
        )

    def test_an_unrecognised_status_returns_nothing_rather_than_everything(self):
        """Silently ignoring a filter reads as 'the filter is off' when
        the user believes it is on."""
        response = self.api(self.ca_a).get(CONTRACTS_URL, {"status": "BANANA"})
        self.assertEqual(response.json()["results"], [])

    def test_building_filter_narrows_to_that_building(self):
        response = self.api(self.ca_a).get(
            CONTRACTS_URL, {"building": self.building_a2.id}
        )
        self.assertEqual(
            {row["id"] for row in response.json()["results"]},
            {self.contract_a2.id},
        )

    def test_a_filter_cannot_widen_what_an_actor_sees(self):
        """`?company=` NARROWS only: it is applied before scoping, so
        naming another tenant's company yields nothing rather than
        their rows."""
        response = self.api(self.ca_a).get(
            CONTRACTS_URL, {"company": self.company_b.id}
        )
        self.assertEqual(response.json()["results"], [])


class ForecastEndpointTests(ContractsFixture):
    def test_the_forecast_reads_for_a_company_admin(self):
        response = self.api(self.ca_a).get(
            contract_forecast_url(self.contract_a.id), {"year": 2026}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["year"], 2026)
        self.assertEqual(body["invoices_per_year"], 12)
        self.assertTrue(all(row["status"] == "PLANNED" for row in body["rows"]))

    def test_a_building_manager_may_read_a_forecast_on_their_building(self):
        response = self.api(self.bm_a).get(
            contract_forecast_url(self.contract_a.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_an_unparseable_year_falls_back_to_the_current_one(self):
        from django.utils import timezone

        response = self.api(self.ca_a).get(
            contract_forecast_url(self.contract_a.id), {"year": "banana"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["year"], timezone.localdate().year)

    def test_the_forecast_endpoint_is_read_only(self):
        """No POST route exists. Generating a real invoice is Sprint
        158's, and this endpoint must not grow one by accident."""
        response = self.api(self.ca_a).post(
            contract_forecast_url(self.contract_a.id), {}, format="json"
        )
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
