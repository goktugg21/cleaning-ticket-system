"""
Sprint 123 — managed-unit catalog: CRUD API, case/whitespace-insensitive
uniqueness (DB-level, not just the friendly serializer pre-check),
cross-tenant isolation, and the Service / CustomerCustomPrice
integration (managed_unit forced None off OTHER, custom_unit_label
auto-synced from the linked unit, archive-does-not-break-existing-rows,
cross-company rejection, PROTECT-on-delete-while-in-use).

Explicitly NOT covered here (by design, not oversight): ProposalLine.
Its `custom_unit_label` is untouched by this sprint -- see
`extra_work/models.py::ManagedUnit`'s docstring for why.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from companies.models import Company, CompanyUserMembership
from customers.models import Customer
from extra_work.models import (
    CustomerCustomPrice,
    ManagedUnit,
    Service,
    ServiceCategory,
)

User = get_user_model()
PASSWORD = "StrongerTestPassword123!"

UNITS_URL = "/api/services/units/"


def _unit_detail_url(unit_id):
    return f"/api/services/units/{unit_id}/"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, role=role, full_name=email.split("@")[0],
        **extra,
    )


class _TwoCompanyFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_a = Company.objects.create(name="Prov A", slug="prov-a-123")
        cls.company_b = Company.objects.create(name="Prov B", slug="prov-b-123")
        cls.sa = _mk("sa-123@example.com", "SUPER_ADMIN")
        cls.ca_a = _mk("ca-a-123@example.com", "COMPANY_ADMIN")
        cls.ca_b = _mk("ca-b-123@example.com", "COMPANY_ADMIN")
        cls.staff_a = _mk("staff-a-123@example.com", "STAFF")
        cls.customer_user_a = _mk("cu-a-123@example.com", "CUSTOMER_USER")
        CompanyUserMembership.objects.create(user=cls.ca_a, company=cls.company_a)
        CompanyUserMembership.objects.create(user=cls.ca_b, company=cls.company_b)
        cls.category = ServiceCategory.objects.create(name="Cat 123 shared")
        cls.customer_a = Customer.objects.create(
            company=cls.company_a, name="Customer A"
        )
        cls.customer_b = Customer.objects.create(
            company=cls.company_b, name="Customer B"
        )

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c


class ManagedUnitCrudTests(_TwoCompanyFixture):
    def test_ca_creates_unit_defaults_to_own_company(self):
        resp = self._api(self.ca_a).post(UNITS_URL, {"label": "m3"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["company"], self.company_a.id)
        self.assertTrue(resp.data["is_active"])
        self.assertEqual(resp.data["label"], "m3")

    def test_sa_must_disambiguate_company(self):
        resp = self._api(self.sa).post(UNITS_URL, {"label": "m3"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_sa_creates_for_named_company(self):
        resp = self._api(self.sa).post(
            UNITS_URL,
            {"label": "m3", "company": self.company_a.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["company"], self.company_a.id)

    def test_list_scoped_to_own_company(self):
        ManagedUnit.objects.create(company=self.company_a, label="m3")
        ManagedUnit.objects.create(company=self.company_b, label="pallet")
        resp = self._api(self.ca_a).get(UNITS_URL)
        self.assertEqual(resp.status_code, 200)
        labels = {row["label"] for row in resp.data["results"]}
        self.assertEqual(labels, {"m3"})

    def test_staff_and_customer_forbidden(self):
        for user in (self.staff_a, self.customer_user_a):
            resp = self._api(user).get(UNITS_URL)
            self.assertEqual(resp.status_code, 403)
            resp = self._api(user).post(UNITS_URL, {"label": "m3"}, format="json")
            self.assertEqual(resp.status_code, 403)

    def test_rename_unit(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m3")
        resp = self._api(self.ca_a).patch(
            _unit_detail_url(unit.id), {"label": "m³ (kubieke meter)"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["label"], "m³ (kubieke meter)")

    def test_archive_and_reactivate(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m3")
        resp = self._api(self.ca_a).patch(
            _unit_detail_url(unit.id), {"is_active": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_active"])

        resp = self._api(self.ca_a).patch(
            _unit_detail_url(unit.id), {"is_active": True}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_active"])

    def test_delete_unused_unit_succeeds(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="unused")
        resp = self._api(self.ca_a).delete(_unit_detail_url(unit.id))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(ManagedUnit.objects.filter(pk=unit.pk).exists())

    def test_delete_unit_in_use_rejected_with_clean_400(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m3")
        Service.objects.create(
            company=self.company_a,
            category=self.category,
            name="svc-using-m3",
            unit_type="OTHER",
            custom_unit_label="m3",
            managed_unit=unit,
            default_unit_price="1.00",
        )
        resp = self._api(self.ca_a).delete(_unit_detail_url(unit.id))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "managed_unit_protected")
        self.assertTrue(ManagedUnit.objects.filter(pk=unit.pk).exists())


class ManagedUnitUniquenessTests(_TwoCompanyFixture):
    def test_api_rejects_case_and_whitespace_variant_duplicate(self):
        self._api(self.ca_a).post(UNITS_URL, {"label": "m3"}, format="json")
        for variant in ("M3", " m3", "m3 ", "  M3  "):
            resp = self._api(self.ca_a).post(
                UNITS_URL, {"label": variant}, format="json"
            )
            self.assertEqual(
                resp.status_code, 400, f"expected 400 for variant {variant!r}"
            )
            self.assertEqual(
                resp.data["label"][0].code, "managed_unit_label_not_unique"
            )

    def test_same_label_allowed_in_different_companies(self):
        resp_a = self._api(self.ca_a).post(UNITS_URL, {"label": "m3"}, format="json")
        resp_b = self._api(self.ca_b).post(UNITS_URL, {"label": "M3"}, format="json")
        self.assertEqual(resp_a.status_code, 201)
        self.assertEqual(resp_b.status_code, 201)

    def test_db_constraint_is_the_real_backstop_not_just_the_serializer(self):
        """Bypass the serializer's Python-side pre-check entirely (direct
        ORM .create()) to prove the case/whitespace-insensitive rule is
        ALSO enforced at the database layer, not only in application code.
        """
        ManagedUnit.objects.create(company=self.company_a, label="m3")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ManagedUnit.objects.create(company=self.company_a, label="  M3  ")
        # The company_a row count is still exactly 1 -- the failed insert
        # did not partially land.
        self.assertEqual(
            ManagedUnit.objects.filter(company=self.company_a).count(), 1
        )

    def test_renaming_to_a_colliding_label_is_rejected(self):
        ManagedUnit.objects.create(company=self.company_a, label="m3")
        other = ManagedUnit.objects.create(company=self.company_a, label="pallet")
        resp = self._api(self.ca_a).patch(
            _unit_detail_url(other.id), {"label": "M3"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["label"][0].code, "managed_unit_label_not_unique"
        )

    def test_renaming_to_its_own_current_label_is_not_a_self_collision(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m3")
        resp = self._api(self.ca_a).patch(
            _unit_detail_url(unit.id), {"label": "m3", "is_active": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)


class ManagedUnitCrossTenantTests(_TwoCompanyFixture):
    """Every endpoint this sprint added, probed from company B's admin
    against company A's data. Every one must 404 or 403 -- never a leak,
    never a cross-tenant mutation."""

    def setUp(self):
        self.unit_a = ManagedUnit.objects.create(company=self.company_a, label="m3")

    def test_foreign_ca_cannot_read_detail(self):
        resp = self._api(self.ca_b).get(_unit_detail_url(self.unit_a.id))
        self.assertEqual(resp.status_code, 404)

    def test_foreign_ca_cannot_see_it_in_list(self):
        resp = self._api(self.ca_b).get(UNITS_URL)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertNotIn(self.unit_a.id, ids)

    def test_foreign_ca_cannot_rename(self):
        resp = self._api(self.ca_b).patch(
            _unit_detail_url(self.unit_a.id), {"label": "hijacked"}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        self.unit_a.refresh_from_db()
        self.assertEqual(self.unit_a.label, "m3")

    def test_foreign_ca_cannot_archive(self):
        resp = self._api(self.ca_b).patch(
            _unit_detail_url(self.unit_a.id), {"is_active": False}, format="json"
        )
        self.assertEqual(resp.status_code, 404)
        self.unit_a.refresh_from_db()
        self.assertTrue(self.unit_a.is_active)

    def test_foreign_ca_cannot_delete(self):
        resp = self._api(self.ca_b).delete(_unit_detail_url(self.unit_a.id))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(ManagedUnit.objects.filter(pk=self.unit_a.pk).exists())

    def test_sa_sees_and_can_manage_both_companies(self):
        unit_b = ManagedUnit.objects.create(company=self.company_b, label="pallet")
        resp = self._api(self.sa).get(UNITS_URL)
        ids = {row["id"] for row in resp.data["results"]}
        self.assertEqual(ids, {self.unit_a.id, unit_b.id})

    def test_service_cannot_link_a_foreign_companys_managed_unit_on_create(self):
        resp = self._api(self.ca_b).post(
            "/api/services/",
            {
                "category": self.category.id,
                "name": "cross-tenant-attempt",
                "unit_type": "OTHER",
                "managed_unit": self.unit_a.id,
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["managed_unit"][0].code, "managed_unit_company_mismatch"
        )
        self.assertFalse(
            Service.objects.filter(name="cross-tenant-attempt").exists()
        )

    def test_service_cannot_be_repointed_at_a_foreign_unit_on_update(self):
        svc = Service.objects.create(
            company=self.company_b,
            category=self.category,
            name="svc-b",
            unit_type="OTHER",
            custom_unit_label="pallet",
            default_unit_price="1.00",
        )
        resp = self._api(self.ca_b).patch(
            f"/api/services/{svc.id}/",
            {"managed_unit": self.unit_a.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["managed_unit"][0].code, "managed_unit_company_mismatch"
        )

    def test_customer_custom_price_cannot_link_a_foreign_managed_unit(self):
        resp = self._api(self.ca_b).post(
            f"/api/customers/{self.customer_b.id}/custom-pricing/",
            {
                "custom_name": "cross-tenant-ccp",
                "unit_type": "OTHER",
                "managed_unit": self.unit_a.id,
                "unit_price": "1.00",
                "valid_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["managed_unit"][0].code, "managed_unit_company_mismatch"
        )


class ServiceManagedUnitIntegrationTests(_TwoCompanyFixture):
    """The Service <-> ManagedUnit wiring in serializers_catalog.py:
    label auto-sync, forced-None off OTHER, and archive-safety."""

    def test_picking_a_managed_unit_syncs_custom_unit_label(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m³")
        resp = self._api(self.ca_a).post(
            "/api/services/",
            {
                "category": self.category.id,
                "name": "svc-picks-unit",
                "unit_type": "OTHER",
                "managed_unit": unit.id,
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["custom_unit_label"], "m³")
        self.assertEqual(resp.data["managed_unit"], unit.id)
        self.assertEqual(resp.data["managed_unit_label"], "m³")

    def test_client_supplied_label_ignored_when_managed_unit_set(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m³")
        resp = self._api(self.ca_a).post(
            "/api/services/",
            {
                "category": self.category.id,
                "name": "svc-conflicting-label",
                "unit_type": "OTHER",
                "managed_unit": unit.id,
                "custom_unit_label": "something else entirely",
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        # The linked unit's label wins -- not the client-supplied text.
        self.assertEqual(resp.data["custom_unit_label"], "m³")

    def test_switching_off_other_clears_managed_unit(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="m³")
        svc = Service.objects.create(
            company=self.company_a,
            category=self.category,
            name="svc-switch",
            unit_type="OTHER",
            custom_unit_label="m³",
            managed_unit=unit,
            default_unit_price="1.00",
        )
        resp = self._api(self.ca_a).patch(
            f"/api/services/{svc.id}/",
            {"unit_type": "HOURS"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["managed_unit"])
        self.assertEqual(resp.data["custom_unit_label"], "")
        svc.refresh_from_db()
        self.assertIsNone(svc.managed_unit_id)

    def test_archiving_a_unit_does_not_break_the_row_using_it(self):
        unit = ManagedUnit.objects.create(company=self.company_a, label="rare-unit")
        svc = Service.objects.create(
            company=self.company_a,
            category=self.category,
            name="svc-rare",
            unit_type="OTHER",
            custom_unit_label="rare-unit",
            managed_unit=unit,
            default_unit_price="1.00",
        )
        unit.is_active = False
        unit.save(update_fields=["is_active"])

        resp = self._api(self.ca_a).get(f"/api/services/{svc.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["custom_unit_label"], "rare-unit")
        self.assertEqual(resp.data["managed_unit"], unit.id)

        # And the archived unit no longer shows in the ACTIVE picker list...
        active_resp = self._api(self.ca_a).get(UNITS_URL, {"is_active": "true"})
        active_ids = {row["id"] for row in active_resp.data["results"]}
        self.assertNotIn(unit.id, active_ids)
        # ...but still exists / is visible in the unfiltered admin list.
        all_resp = self._api(self.ca_a).get(UNITS_URL)
        all_ids = {row["id"] for row in all_resp.data["results"]}
        self.assertIn(unit.id, all_ids)

    def test_legacy_free_text_row_unaffected_when_no_managed_unit_supplied(self):
        # Pre-Sprint-123 shape: OTHER + custom_unit_label, no managed_unit
        # at all. Must behave exactly as before.
        resp = self._api(self.ca_a).post(
            "/api/services/",
            {
                "category": self.category.id,
                "name": "svc-legacy-shape",
                "unit_type": "OTHER",
                "custom_unit_label": "legacy-freetext",
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["custom_unit_label"], "legacy-freetext")
        self.assertIsNone(resp.data["managed_unit"])

    def test_other_still_requires_a_label_when_no_managed_unit_given(self):
        resp = self._api(self.ca_a).post(
            "/api/services/",
            {
                "category": self.category.id,
                "name": "svc-blank-other",
                "unit_type": "OTHER",
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["custom_unit_label"][0].code,
            "custom_unit_label_required",
        )
