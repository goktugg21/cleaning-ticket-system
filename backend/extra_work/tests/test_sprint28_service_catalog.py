"""
Sprint 28 Batch 5 — provider service catalog CRUD tests
(`ServiceCategory` + `Service`).

Coverage matrix:

  * SUPER_ADMIN + COMPANY_ADMIN can CRUD both ServiceCategory and
    Service (the catalog is provider-wide, not company-scoped, so
    EVERY COMPANY_ADMIN sees the same global list — there is no
    cross-company "isolation" to test on this surface).
  * BUILDING_MANAGER / STAFF / CUSTOMER_USER → 403 on every endpoint.
  * Unique constraints — duplicate ServiceCategory name and
    duplicate Service name within a category are 400.
  * `?category=<id>` and `?is_active=true|false` filtering.
  * Deleting a ServiceCategory with attached Service rows is blocked
    (PROTECT), returns 400 with structured payload.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from extra_work.models import (
    ExtraWorkPricingUnitType,
    Service,
    ServiceCategory,
)
from test_utils import TenantFixtureMixin


CATEGORY_LIST_URL = "/api/services/categories/"
CATEGORY_DETAIL_URL = "/api/services/categories/{cat_id}/"
SERVICE_LIST_URL = "/api/services/"
SERVICE_DETAIL_URL = "/api/services/{svc_id}/"


class ServiceCategoryCrudTests(TenantFixtureMixin, APITestCase):
    def test_super_admin_can_create_and_list_categories(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            CATEGORY_LIST_URL,
            {"name": "Cleaning", "description": "Regular cleaning"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Cleaning")
        # List call returns the row.
        list_resp = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in list_resp.data["results"]}
        self.assertIn("Cleaning", names)

    def test_company_admin_cannot_crud_category(self):
        # Sprint 3B narrows ServiceCategory writes to SUPER_ADMIN
        # only because the model is global. Provider Admin attempts
        # land on 403 with the stable code; the pre-Sprint-3B "PA
        # may CRUD categories" surface is intentionally gone.
        self.authenticate(self.company_admin)
        create = self.client.post(
            CATEGORY_LIST_URL, {"name": "Maintenance"}, format="json"
        )
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)

        # Reads still work — the GET surface is unchanged.
        cat = ServiceCategory.objects.create(name="Maintenance-PA-read")
        retrieve = self.client.get(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id)
        )
        self.assertEqual(retrieve.status_code, status.HTTP_200_OK)

        # PATCH / DELETE land on 403 too.
        update = self.client.patch(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id),
            {"description": "Hijack"},
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_403_FORBIDDEN)
        delete = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id)
        )
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(
            ServiceCategory.objects.filter(pk=cat.id).exists()
        )

    def test_duplicate_category_name_returns_400(self):
        ServiceCategory.objects.create(name="Cleaning")
        self.authenticate(self.super_admin)
        response = self.client.post(
            CATEGORY_LIST_URL, {"name": "Cleaning"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_is_active_filter(self):
        ServiceCategory.objects.create(name="Active Cat", is_active=True)
        ServiceCategory.objects.create(name="Inactive Cat", is_active=False)
        self.authenticate(self.super_admin)
        only_active = self.client.get(CATEGORY_LIST_URL + "?is_active=true")
        self.assertEqual(only_active.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in only_active.data["results"]}
        self.assertIn("Active Cat", names)
        self.assertNotIn("Inactive Cat", names)

        only_inactive = self.client.get(CATEGORY_LIST_URL + "?is_active=false")
        names_inactive = {row["name"] for row in only_inactive.data["results"]}
        self.assertIn("Inactive Cat", names_inactive)
        self.assertNotIn("Active Cat", names_inactive)

    def test_building_manager_blocked_on_write_endpoints(self):
        """Sprint 29 Batch 29.8.5 — BM can GET (catalog is reference
        data the EW create form needs to populate) but is blocked
        from every write endpoint."""
        cat = ServiceCategory.objects.create(name="Existing")
        self.authenticate(self.manager)
        list_resp = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        retrieve_resp = self.client.get(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_200_OK)

        create_resp = self.client.post(
            CATEGORY_LIST_URL, {"name": "Nope"}, format="json"
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)
        patch_resp = self.client.patch(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id),
            {"description": "Hijack"},
            format="json",
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_403_FORBIDDEN)
        delete_resp = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id)
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_can_read_blocked_on_writes(self):
        """Sprint 29 Batch 29.8.5 — CUSTOMER_USER GETs catalog (needed
        by the EW create form's category dropdown); writes are
        still 403."""
        cat = ServiceCategory.objects.create(name="Existing")
        self.authenticate(self.customer_user)
        list_resp = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        retrieve_resp = self.client.get(
            CATEGORY_DETAIL_URL.format(cat_id=cat.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_200_OK)
        create_resp = self.client.post(
            CATEGORY_LIST_URL, {"name": "Nope"}, format="json"
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_role_can_read_blocked_on_writes(self):
        """Sprint 29 Batch 29.8.5 — STAFF can GET catalog; cannot write."""
        staff_user = self.make_user("staff-cat@example.com", UserRole.STAFF)
        self.authenticate(staff_user)
        list_resp = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        create_resp = self.client.post(
            CATEGORY_LIST_URL, {"name": "Nope"}, format="json"
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)


class ServiceCrudTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.cat_a = ServiceCategory.objects.create(name="Category A")
        self.cat_b = ServiceCategory.objects.create(name="Category B")

    def test_super_admin_can_create_and_list_services(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.cat_a.id,
                "name": "Floor polishing",
                "unit_type": ExtraWorkPricingUnitType.SQUARE_METERS,
                "default_unit_price": "12.50",
                "default_vat_pct": "21.00",
                "description": "Standard floor polish",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["category"], self.cat_a.id)
        self.assertEqual(response.data["category_name"], "Category A")
        self.assertEqual(response.data["name"], "Floor polishing")
        # Decimals are serialized as strings by DRF DecimalField.
        self.assertEqual(response.data["default_unit_price"], "12.50")
        self.assertEqual(response.data["default_vat_pct"], "21.00")

    def test_company_admin_can_crud_service(self):
        self.authenticate(self.company_admin)
        create = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.cat_a.id,
                "name": "Cleaning shift",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "32.00",
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        svc_id = create.data["id"]

        retrieve = self.client.get(SERVICE_DETAIL_URL.format(svc_id=svc_id))
        self.assertEqual(retrieve.status_code, status.HTTP_200_OK)

        update = self.client.patch(
            SERVICE_DETAIL_URL.format(svc_id=svc_id),
            {"default_unit_price": "35.00"},
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(update.data["default_unit_price"], "35.00")

        delete = self.client.delete(SERVICE_DETAIL_URL.format(svc_id=svc_id))
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Service.objects.filter(pk=svc_id).exists())

    def test_filter_by_category(self):
        Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Service A1",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("10.00"),
        )
        Service.objects.create(
            category=self.cat_b,
            company=self.company,
            name="Service B1",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("10.00"),
        )
        self.authenticate(self.super_admin)
        response = self.client.get(SERVICE_LIST_URL + f"?category={self.cat_a.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {row["name"] for row in response.data["results"]}
        self.assertEqual(names, {"Service A1"})

    def test_is_active_filter(self):
        Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Active Svc",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("99.00"),
            is_active=True,
        )
        Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Inactive Svc",
            unit_type=ExtraWorkPricingUnitType.FIXED,
            default_unit_price=Decimal("99.00"),
            is_active=False,
        )
        self.authenticate(self.super_admin)
        only_active = self.client.get(SERVICE_LIST_URL + "?is_active=true")
        names = {row["name"] for row in only_active.data["results"]}
        self.assertIn("Active Svc", names)
        self.assertNotIn("Inactive Svc", names)

    def test_duplicate_name_within_same_category_rejected(self):
        Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("12.50"),
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.cat_a.id,
                "name": "Floor polishing",
                "unit_type": ExtraWorkPricingUnitType.SQUARE_METERS,
                "default_unit_price": "13.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_name_different_category_allowed(self):
        Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Floor polishing",
            unit_type=ExtraWorkPricingUnitType.SQUARE_METERS,
            default_unit_price=Decimal("12.50"),
        )
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.cat_b.id,
                "name": "Floor polishing",
                "unit_type": ExtraWorkPricingUnitType.SQUARE_METERS,
                "default_unit_price": "12.50",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_negative_default_unit_price_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.cat_a.id,
                "name": "Bad price",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "-1.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("default_unit_price", response.data)

    def test_building_manager_blocked_on_service_writes(self):
        """Sprint 29 Batch 29.8.5 — BM can GET Service rows; cannot write."""
        svc = Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Existing Svc",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("10.00"),
        )
        self.authenticate(self.manager)
        # GETs now succeed.
        self.assertEqual(
            self.client.get(SERVICE_LIST_URL).status_code, status.HTTP_200_OK
        )
        self.assertEqual(
            self.client.get(SERVICE_DETAIL_URL.format(svc_id=svc.id)).status_code,
            status.HTTP_200_OK,
        )
        # Writes still blocked.
        for resp in (
            self.client.post(
                SERVICE_LIST_URL,
                {
                    "company": self.company.id,
                    "category": self.cat_a.id,
                    "name": "Nope",
                    "unit_type": ExtraWorkPricingUnitType.HOURS,
                    "default_unit_price": "1.00",
                },
                format="json",
            ),
            self.client.patch(
                SERVICE_DETAIL_URL.format(svc_id=svc.id),
                {"description": "hijack"},
                format="json",
            ),
            self.client.delete(SERVICE_DETAIL_URL.format(svc_id=svc.id)),
        ):
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_can_read_service_blocked_on_writes(self):
        """Sprint 29 Batch 29.8.5 — CUSTOMER_USER can GET Service rows
        (needed by EW create form); cannot write."""
        svc = Service.objects.create(
            category=self.cat_a,
            company=self.company,
            name="Existing Svc",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("10.00"),
        )
        self.authenticate(self.customer_user)
        list_resp = self.client.get(SERVICE_LIST_URL)
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        retrieve_resp = self.client.get(
            SERVICE_DETAIL_URL.format(svc_id=svc.id)
        )
        self.assertEqual(retrieve_resp.status_code, status.HTTP_200_OK)
        create_resp = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.cat_a.id,
                "name": "Nope",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_403_FORBIDDEN)


class ServiceCategoryProtectsServiceTests(TenantFixtureMixin, APITestCase):
    """A ServiceCategory cannot be deleted while it still has Service
    rows pointing at it (PROTECT). The view catches the resulting
    `ProtectedError` and surfaces a 400 with a structured payload."""

    def setUp(self):
        super().setUp()
        self.cat = ServiceCategory.objects.create(name="Locked Cat")
        self.svc = Service.objects.create(
            category=self.cat,
            company=self.company,
            name="Attached Svc",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("15.00"),
        )

    def test_delete_protected_category_returns_400(self):
        self.authenticate(self.super_admin)
        response = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=self.cat.id)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("code"), "category_protected")
        # Row survives the failed delete.
        self.assertTrue(
            ServiceCategory.objects.filter(pk=self.cat.id).exists()
        )

    def test_delete_succeeds_after_attached_services_removed(self):
        self.authenticate(self.super_admin)
        # Detach by deleting the service first.
        self.client.delete(SERVICE_DETAIL_URL.format(svc_id=self.svc.id))
        # Now the category delete succeeds.
        response = self.client.delete(
            CATEGORY_DETAIL_URL.format(cat_id=self.cat.id)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class ServiceCustomUnitLabelTests(TenantFixtureMixin, APITestCase):
    """RF-2 (mirror of CustomerCustomPrice) — `Service.custom_unit_label` is
    the operator-supplied unit name for `unit_type == OTHER`. OTHER REQUIRES a
    non-blank label (stable code `custom_unit_label_required`); a concrete unit
    type forces it blank rather than rejecting."""

    def setUp(self):
        super().setUp()
        self.cat = ServiceCategory.objects.create(name="Custom-unit cat")

    def _payload(self, **over):
        base = {
            "company": self.company.id,
            "category": self.cat.id,
            "name": "Sand delivery",
            "unit_type": ExtraWorkPricingUnitType.OTHER,
            "custom_unit_label": "m3",
            "default_unit_price": "80.00",
            "default_vat_pct": "21.00",
        }
        base.update(over)
        return base

    def test_create_other_without_label_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL, self._payload(custom_unit_label=""), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("custom_unit_label", response.data)
        self.assertEqual(
            response.data["custom_unit_label"][0].code,
            "custom_unit_label_required",
        )

    def test_create_other_with_whitespace_label_rejected(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            self._payload(custom_unit_label="   "),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["custom_unit_label"][0].code,
            "custom_unit_label_required",
        )

    def test_create_other_with_label_accepted_and_stripped(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            self._payload(custom_unit_label="  pallet  "),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["custom_unit_label"], "pallet")
        svc = Service.objects.get(pk=response.data["id"])
        self.assertEqual(svc.custom_unit_label, "pallet")

    def test_create_concrete_unit_forces_label_blank(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            SERVICE_LIST_URL,
            self._payload(
                unit_type=ExtraWorkPricingUnitType.HOURS,
                custom_unit_label="m3",
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["custom_unit_label"], "")
        svc = Service.objects.get(pk=response.data["id"])
        self.assertEqual(svc.custom_unit_label, "")

    def test_patch_away_from_other_clears_stale_label(self):
        self.authenticate(self.super_admin)
        svc = Service.objects.create(
            company=self.company,
            category=self.cat,
            name="Sand delivery",
            unit_type=ExtraWorkPricingUnitType.OTHER,
            custom_unit_label="m3",
            default_unit_price=Decimal("80.00"),
        )
        response = self.client.patch(
            SERVICE_DETAIL_URL.format(svc_id=svc.id),
            {"unit_type": ExtraWorkPricingUnitType.HOURS},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["custom_unit_label"], "")
        svc.refresh_from_db()
        self.assertEqual(svc.custom_unit_label, "")
