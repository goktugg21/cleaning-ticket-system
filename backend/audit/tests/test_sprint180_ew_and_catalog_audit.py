"""Sprint 180 §3/§5 — audit coverage for `billed_to` and two catalogs.

Three registrations land in `audit/signals.py` this sprint, and this
module is the test CLAUDE.md's audit rule requires for each:

  * §3 `ExtraWorkRequest.billed_to` joins `_EW_TRACKED_FIELDS`, the
    targeted-field UPDATE handler shared with the billing columns and
    the two label FKs. It decides where money lands, so a change to it
    has to be attributable (H-10).
  * §5 `BuildingType` (Sprint 178) and `ManagedUnit` (Sprint 123) join
    the full CRUD trio. Every other per-company catalog was already
    there; these two were simply missed, and a RENAME is the change
    worth auditing in both — every building points at its type by id,
    and every priced row that adopted a managed unit keeps
    `custom_unit_label` in sync with the unit's current label.

The `billed_to` handler is UPDATE-only by design (H-11: a create is not
a billing event), so the test drives a real field change rather than a
create and asserts the diff.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingType
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import (
    ExtraWorkBilledTo,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ManagedUnit,
)


User = get_user_model()
PASSWORD = "StrongerTestPassword180!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class _Sprint180AuditFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Prov", slug="prov-180-audit")
        cls.ca = _mk("ca-180-audit@example.com", "COMPANY_ADMIN")
        CompanyUserMembership.objects.create(user=cls.ca, company=cls.company)
        cls.building = Building.objects.create(
            company=cls.company, name="B", address="B 1"
        )
        cls.customer = Customer.objects.create(
            company=cls.company, name="Cust 180", building=cls.building
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def logs(self, model, action=None, target_id=None):
        qs = AuditLog.objects.filter(target_model=model)
        if action is not None:
            qs = qs.filter(action=action)
        if target_id is not None:
            qs = qs.filter(target_id=target_id)
        return qs


class BilledToAuditTests(_Sprint180AuditFixture):
    def _make_ew(self):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.ca,
            title="Audited EW",
            description="d",
            status=ExtraWorkStatus.REQUESTED,
            subtotal_amount=Decimal("0.00"),
            vat_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
        )

    def test_changing_billed_to_writes_one_update_row_with_the_diff(self):
        ew = self._make_ew()
        AuditLog.objects.all().delete()

        ew.billed_to = ExtraWorkBilledTo.CUSTOMER
        ew.save(update_fields=["billed_to", "updated_at"])

        rows = self.logs("extra_work.ExtraWorkRequest", target_id=ew.id)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.action, AuditAction.UPDATE)
        self.assertEqual(
            row.changes["billed_to"],
            {"before": "BUILDING", "after": "CUSTOMER"},
        )

    def test_creating_an_extra_work_writes_no_billing_row(self):
        """H-11 separation, unchanged: the handler is UPDATE-only, so a
        create — which is not a billing event — emits nothing here."""
        AuditLog.objects.filter(
            target_model="extra_work.ExtraWorkRequest"
        ).delete()
        ew = self._make_ew()
        self.assertFalse(
            self.logs("extra_work.ExtraWorkRequest", target_id=ew.id).exists()
        )

    def test_a_write_that_does_not_touch_billed_to_emits_nothing(self):
        ew = self._make_ew()
        AuditLog.objects.all().delete()
        ew.title = "Renamed, not rebilled"
        ew.save(update_fields=["title", "updated_at"])
        self.assertFalse(
            self.logs("extra_work.ExtraWorkRequest", target_id=ew.id).exists()
        )


class BuildingTypeAuditTests(_Sprint180AuditFixture):
    def test_create_update_delete_are_logged(self):
        client = self.api(self.ca)
        created = client.post(
            "/api/buildings/types/",
            {"name": "Zorggebouw", "company": self.company.id},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        type_id = created.data["id"]

        create_log = self.logs(
            "buildings.BuildingType", AuditAction.CREATE, type_id
        ).get()
        self.assertEqual(create_log.actor_id, self.ca.id)

        renamed = client.patch(
            f"/api/buildings/types/{type_id}/",
            {"name": "Zorgcomplex"},
            format="json",
        )
        self.assertEqual(renamed.status_code, 200, renamed.data)
        update_log = self.logs(
            "buildings.BuildingType", AuditAction.UPDATE, type_id
        ).latest("id")
        self.assertEqual(update_log.actor_id, self.ca.id)
        self.assertEqual(
            update_log.changes["name"],
            {"before": "Zorggebouw", "after": "Zorgcomplex"},
        )

        client.delete(f"/api/buildings/types/{type_id}/")
        self.assertTrue(
            self.logs(
                "buildings.BuildingType", AuditAction.DELETE, type_id
            ).exists()
        )

    def test_archiving_is_logged_as_an_is_active_diff(self):
        bt = BuildingType.objects.create(company=self.company, name="Kantoor")
        AuditLog.objects.all().delete()
        bt.is_active = False
        bt.save(update_fields=["is_active"])
        row = self.logs(
            "buildings.BuildingType", AuditAction.UPDATE, bt.id
        ).get()
        self.assertEqual(
            row.changes["is_active"], {"before": True, "after": False}
        )


class ManagedUnitAuditTests(_Sprint180AuditFixture):
    def test_create_update_delete_are_logged(self):
        client = self.api(self.ca)
        created = client.post(
            "/api/services/units/",
            {"label": "m3", "company": self.company.id},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        unit_id = created.data["id"]

        create_log = self.logs(
            "extra_work.ManagedUnit", AuditAction.CREATE, unit_id
        ).get()
        self.assertEqual(create_log.actor_id, self.ca.id)

        relabelled = client.patch(
            f"/api/services/units/{unit_id}/",
            {"label": "m3 (gestort)"},
            format="json",
        )
        self.assertEqual(relabelled.status_code, 200, relabelled.data)
        update_log = self.logs(
            "extra_work.ManagedUnit", AuditAction.UPDATE, unit_id
        ).latest("id")
        self.assertEqual(update_log.actor_id, self.ca.id)
        self.assertEqual(
            update_log.changes["label"],
            {"before": "m3", "after": "m3 (gestort)"},
        )

        client.delete(f"/api/services/units/{unit_id}/")
        self.assertTrue(
            self.logs(
                "extra_work.ManagedUnit", AuditAction.DELETE, unit_id
            ).exists()
        )

    def test_archiving_is_logged_as_an_is_active_diff(self):
        unit = ManagedUnit.objects.create(company=self.company, label="stuks")
        AuditLog.objects.all().delete()
        unit.is_active = False
        unit.save(update_fields=["is_active"])
        row = self.logs(
            "extra_work.ManagedUnit", AuditAction.UPDATE, unit.id
        ).get()
        self.assertEqual(
            row.changes["is_active"], {"before": True, "after": False}
        )
