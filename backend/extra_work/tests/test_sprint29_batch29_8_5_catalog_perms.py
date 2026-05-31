"""
Sprint 29 Batch 29.8.5 — catalog permission split.

The four service-catalog views
(`ServiceCategoryListCreateView`, `ServiceCategoryDetailView`,
`ServiceListCreateView`, `ServiceDetailView`) used to gate every
method behind `IsSuperAdminOrCompanyAdmin`. That blocked CUSTOMER_USER
from even reading the catalog, which cascaded into the Extra Work
create form's mount-time `Promise.all` hitting a 403 and surfacing a
misleading "no permission" banner.

The 29.8.5 contract:

  * **GET (list + retrieve)** on all four views is open to any
    authenticated user. The catalog is provider-wide reference data;
    every role with a login can read it.
  * **POST / PATCH / DELETE** on all four views stay locked to
    `IsSuperAdminOrCompanyAdmin`.
  * **Anonymous** requests are 401 on every method (rejected by
    `IsAuthenticated` / DRF's anonymous user check).

Coverage below pins the seven mandated cases plus a detail-GET happy
path for CUSTOMER_USER.
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
SERVICE_LIST_URL = "/api/services/"
SERVICE_DETAIL_URL = "/api/services/{svc_id}/"


class CatalogPermissionSplitTests(TenantFixtureMixin, APITestCase):
    """Sprint 29 Batch 29.8.5 — per-method catalog gating."""

    def setUp(self):
        super().setUp()
        # Seed at least one category + service so the detail GET test
        # for CUSTOMER_USER has a row to fetch. The list tests pass
        # purely on status code regardless of result count.
        self.category = ServiceCategory.objects.create(
            name="29.8.5 Reference Category"
        )
        self.service = Service.objects.create(
            category=self.category,
            company=self.company,
            name="29.8.5 Reference Service",
            unit_type=ExtraWorkPricingUnitType.HOURS,
            default_unit_price=Decimal("42.00"),
        )

    # ------------------------------------------------------------------
    # CUSTOMER_USER — the role the batch primarily unblocks.
    # ------------------------------------------------------------------
    def test_customer_user_can_get_services_list(self):
        self.authenticate(self.customer_user)
        response = self.client.get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Paginated payload shape; the row may or may not be present
        # depending on filter, but `results` must exist.
        self.assertIn("results", response.data)

    def test_customer_user_can_get_service_detail(self):
        """Detail GETs must also work (the EW create form may fetch
        individual rows by id when computing line-item defaults)."""
        self.authenticate(self.customer_user)
        response = self.client.get(
            SERVICE_DETAIL_URL.format(svc_id=self.service.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.service.id)

    def test_customer_user_post_services_forbidden(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            SERVICE_LIST_URL,
            {
                "company": self.company.id,
                "category": self.category.id,
                "name": "Customer-created service",
                "unit_type": ExtraWorkPricingUnitType.HOURS,
                "default_unit_price": "1.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_user_can_get_service_categories(self):
        self.authenticate(self.customer_user)
        response = self.client.get(CATEGORY_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_customer_user_post_service_categories_forbidden(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            CATEGORY_LIST_URL,
            {"name": "Customer-created category"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ------------------------------------------------------------------
    # BUILDING_MANAGER — also gets read access (catalog is provider-
    # global reference data, no per-building scoping).
    # ------------------------------------------------------------------
    def test_building_manager_can_get_services(self):
        self.authenticate(self.manager)
        response = self.client.get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # STAFF — also gets read access (no scope check; provider-global).
    # ------------------------------------------------------------------
    def test_staff_can_get_services(self):
        staff_user = self.make_user(
            "staff-29-8-5@example.com", UserRole.STAFF
        )
        self.authenticate(staff_user)
        response = self.client.get(SERVICE_LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Anonymous — 401 unaffected by the GET-opening.
    # ------------------------------------------------------------------
    def test_anonymous_get_services_unauthorized(self):
        # No authenticate() — request hits IsAuthenticated guard.
        response = self.client.get(SERVICE_LIST_URL)
        self.assertEqual(
            response.status_code, status.HTTP_401_UNAUTHORIZED
        )
