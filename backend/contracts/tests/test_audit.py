"""
Sprint 160 — every contracts model lands on the AuditLog (H-10).

Four models take the generic full-CRUD trio and one is
membership-shaped, so this file checks both handler sets. The point is
not that the audit machinery works — it has its own tests — but that
THESE models are actually registered: a new audited model that nobody
wired up fails silently, and the only thing that catches it is a test
that asks for its rows by name.
"""
from __future__ import annotations

from datetime import date

from rest_framework import status

from audit.models import AuditAction, AuditLog

from contracts.models import ContractBuilding

from .fixtures import (
    CONTRACTS_URL,
    TYPES_URL,
    ContractsFixture,
    contract_detail_url,
    contract_revisions_url,
    revision_lines_url,
    type_detail_url,
)


class ContractAuditTests(ContractsFixture):
    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def logs_for(self, model, **extra):
        return AuditLog.objects.filter(target_model=model, **extra)

    def test_creating_a_contract_writes_a_create_log(self):
        response = self.api(self.ca_a).post(
            CONTRACTS_URL,
            {
                "customer": self.customer_a.id,
                "start_date": "2027-01-01",
                "building_ids": [self.building_a.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        log = self.logs_for(
            "contracts.Contract", action=AuditAction.CREATE
        ).get()
        self.assertEqual(log.actor, self.ca_a)
        self.assertEqual(log.target_id, response.json()["id"])
        self.assertEqual(log.changes["contract_no"]["after"], "CNT-2027-0001")
        self.assertEqual(log.changes["start_date"]["after"], "2027-01-01")

        # The first revision is audited too — it is a business fact
        # with money attached, not an implementation detail of create.
        self.assertEqual(
            self.logs_for(
                "contracts.ContractRevision", action=AuditAction.CREATE
            ).count(),
            1,
        )
        # ...and so is the location link, membership-shaped.
        self.assertEqual(
            self.logs_for(
                "contracts.ContractBuilding", action=AuditAction.CREATE
            ).count(),
            1,
        )

    def test_editing_the_billing_terms_writes_a_diff(self):
        """A billing_day / billing_type change moves real money, so the
        before/after is what makes it attributable."""
        response = self.api(self.ca_a).patch(
            contract_detail_url(self.contract_a.id),
            {"billing_day": 15, "billing_type": "ARREARS"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = self.logs_for(
            "contracts.Contract", action=AuditAction.UPDATE
        ).get()
        self.assertEqual(log.changes["billing_day"]["before"], 1)
        self.assertEqual(log.changes["billing_day"]["after"], 15)
        self.assertEqual(log.changes["billing_type"]["after"], "ARREARS")

    def test_removing_a_location_writes_a_delete_log(self):
        response = self.api(self.ca_a).patch(
            contract_detail_url(self.contract_a.id),
            {"building_ids": [self.building_a2.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.logs_for(
                "contracts.ContractBuilding", action=AuditAction.DELETE
            ).count(),
            1,
        )
        self.assertEqual(
            self.logs_for(
                "contracts.ContractBuilding", action=AuditAction.CREATE
            ).count(),
            1,
        )
        self.assertEqual(
            set(
                ContractBuilding.objects.filter(
                    contract=self.contract_a
                ).values_list("building_id", flat=True)
            ),
            {self.building_a2.id},
        )

    def test_deleting_a_contract_writes_a_delete_log(self):
        contract_id = self.contract_a2.id
        response = self.api(self.ca_a).delete(contract_detail_url(contract_id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        log = self.logs_for(
            "contracts.Contract", action=AuditAction.DELETE, target_id=contract_id
        ).get()
        self.assertEqual(log.actor, self.ca_a)


class ContractRevisionAuditTests(ContractsFixture):
    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_authoring_a_revision_and_its_lines_is_audited(self):
        created = self.api(self.ca_a).post(
            contract_revisions_url(self.contract_a.id),
            {
                "label": "Prijsverhoging 2027",
                "effective_from": "2027-01-01",
                "copy_lines": False,
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        revision_log = AuditLog.objects.filter(
            target_model="contracts.ContractRevision",
            action=AuditAction.CREATE,
        ).get()
        self.assertEqual(revision_log.actor, self.ca_a)
        self.assertEqual(
            revision_log.changes["effective_from"]["after"], "2027-01-01"
        )

        added = self.api(self.ca_a).post(
            revision_lines_url(created.json()["id"]),
            {"name": "Nieuw project", "amount": "250.00", "hours": "5.00"},
            format="json",
        )
        self.assertEqual(added.status_code, status.HTTP_201_CREATED)
        line_log = AuditLog.objects.filter(
            target_model="contracts.ContractLine", action=AuditAction.CREATE
        ).get()
        self.assertEqual(line_log.changes["amount"]["after"], "250.00")

    def test_a_price_change_on_a_future_revision_is_audited(self):
        created = self.api(self.ca_a).post(
            contract_revisions_url(self.contract_a.id),
            {"label": "2027", "effective_from": "2027-01-01"},
            format="json",
        )
        line_id = created.json()["lines"][0]["id"]
        AuditLog.objects.all().delete()
        response = self.api(self.ca_a).patch(
            f"/api/contracts/lines/{line_id}/",
            {"amount": "1234.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.filter(
            target_model="contracts.ContractLine", action=AuditAction.UPDATE
        ).get()
        self.assertEqual(log.changes["amount"]["before"], "1000.00")
        self.assertEqual(log.changes["amount"]["after"], "1234.00")


class ContractTypeAuditTests(ContractsFixture):
    def setUp(self):
        super().setUp()
        AuditLog.objects.all().delete()

    def test_the_catalog_gets_the_full_crud_trio(self):
        created = self.api(self.ca_a).post(
            TYPES_URL, {"name": "Onderhoud"}, format="json"
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        type_id = created.json()["id"]

        renamed = self.api(self.ca_a).patch(
            type_detail_url(type_id), {"name": "Groot onderhoud"}, format="json"
        )
        self.assertEqual(renamed.status_code, status.HTTP_200_OK)

        deleted = self.api(self.ca_a).delete(type_detail_url(type_id))
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

        actions = list(
            AuditLog.objects.filter(
                target_model="contracts.ContractType", target_id=type_id
            )
            .order_by("id")
            .values_list("action", flat=True)
        )
        self.assertEqual(
            actions,
            [AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE],
        )
        rename = AuditLog.objects.get(
            target_model="contracts.ContractType",
            target_id=type_id,
            action=AuditAction.UPDATE,
        )
        # The rename is the point of auditing a catalog: a relabelled
        # type later makes an old contract look like something else.
        self.assertEqual(rename.changes["name"]["before"], "Onderhoud")
        self.assertEqual(rename.changes["name"]["after"], "Groot onderhoud")
